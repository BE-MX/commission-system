/** Durable DB mode gate; independent environment flags cannot relax it. */
export const WORKER_LOCK = 'ark-okki-outbound-poller';
export async function readExecutionMode(conn) {
  try {
    let modes;
    try {
      [modes] = await conn.query(
        "SELECT code, version FROM ark_order_portal_auth_barriers WHERE code LIKE 'outbound-worker-%'");
    } catch (error) {
      // Metadata visibility depends on grants; it cannot prove table absence.
      if (error?.code !== 'ER_NO_SUCH_TABLE' || error?.errno !== 1146 || error?.sqlState !== '42S02')
        throw error;
      // Exact verified pre-portal releases; 176 creates the mode table after 175.
      // Read the same target schema on the same connection; no separate configuration fallback.
      const [heads] = await conn.query('SELECT version_num FROM alembic_version');
      if (!Array.isArray(heads) || heads.length !== 1 ||
          !['171_customer_tag_display_value','175_receipt_recovery'].includes(heads[0]?.version_num))
        throw Error('Unconfirmed pre-portal schema');
      return 'legacy';
    }
    if (!Array.isArray(modes)) throw Error('Invalid mode evidence');
    if (modes.length === 0) return 'legacy';
    if (modes.length !== 1 || modes[0]?.code !== 'outbound-worker-v1' || modes[0]?.version !== 1)
      throw Error('Unknown outbound protocol mode');
    return 'outbound-worker-v1';
  } catch {
    // Driver errors can include connection details; entry points log only this safe message.
    throw Error('Outbound protocol mode cannot be confirmed');
  }
}

export async function assertLegacyMode(conn) {
  if (await readExecutionMode(conn) !== 'legacy')
    throw Error('Enabled outbound worker owns execution; legacy creation is prohibited');
}

export async function acquireCreatorFence(conn, parentOwner) {
  if (parentOwner !== undefined) {
    if (!/^[1-9]\d*$/.test(String(parentOwner))) throw Error('Invalid poller lock owner');
    const [[owner]] = await conn.query('SELECT IS_USED_LOCK(?) AS owner',[WORKER_LOCK]);
    if (!owner || String(owner.owner) !== String(parentOwner)) throw Error('Poller executor fence is missing');
    return async () => {};
  }
  const [[lock]] = await conn.query('SELECT GET_LOCK(?,0) AS acquired',[WORKER_LOCK]);
  if (Number(lock?.acquired) !== 1) throw Error('Another outbound executor owns the fence');
  return async () => {await conn.query('SELECT RELEASE_LOCK(?)',[WORKER_LOCK]);};
}


/** Dedicated deployment connection only. No provider, queue or invoice write. */
export async function serveDeploymentFence(conn,operation,{input=process.stdin,output=process.stdout}={}) {
  if(!['observe','hold'].includes(operation))throw Error('Invalid mode control operation');
  const {createHash}=await import('node:crypto');
  const observe=async()=>{
    const [rows]=await conn.query('SELECT @@server_uuid AS server_uuid, DATABASE() AS schema_name');
    if(!Array.isArray(rows) || rows.length!==1 ||
       typeof rows[0]?.server_uuid!=='string' || !/^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(rows[0].server_uuid) ||
       typeof rows[0]?.schema_name!=='string' || !/^[A-Za-z0-9_]+$/.test(rows[0].schema_name))
      throw Error('Target database identity cannot be confirmed');
    return {mode:await readExecutionMode(conn),database_fingerprint:createHash('sha256')
      .update(JSON.stringify([rows[0].server_uuid.toLowerCase(),rows[0].schema_name])).digest('hex')};
  };
  const emit=(phase,observation)=>output.write(JSON.stringify({phase,...observation})+'\n');
  let observation=await observe();
  if(operation==='observe'){emit('observed',observation);return;}
  let held=false,connectionId;
  if(observation.mode==='legacy') {
    const [[identity]]=await conn.query('SELECT CONNECTION_ID() AS id, IS_USED_LOCK(?) AS owner',[WORKER_LOCK]);
    if(!Number.isSafeInteger(identity?.id) || identity.id<1 || identity.owner===identity.id)
      throw Error('Deployment connection ownership is invalid');
    connectionId=identity.id;
    const [[lock]]=await conn.query('SELECT GET_LOCK(?,0) AS acquired',[WORKER_LOCK]);
    if(lock?.acquired!==1)throw Error('Another outbound executor owns the fence');
    held=true;
    // A bootstrap may have committed mode between the initial observation and acquisition.
    observation=await observe();
  }
  const {createInterface}=await import('node:readline');
  const reader=createInterface({input,crlfDelay:Infinity});
  let released=false;
  try {
    emit('ready',observation);
    for await(const command of reader) {
      if(!['check','release'].includes(command))throw Error('Invalid mode control command');
      const current=await observe();
      if(current.mode!==observation.mode || current.database_fingerprint!==observation.database_fingerprint)
        throw Error('Mode control observation changed');
      if(command==='check'){emit('checked',current);continue;}
      if(held) {
        const [[lock]]=await conn.query('SELECT RELEASE_LOCK(?) AS released',[WORKER_LOCK]);
        const [[owner]]=await conn.query('SELECT IS_USED_LOCK(?) AS owner',[WORKER_LOCK]);
        if(lock?.released!==1 || !owner || owner.owner===connectionId ||
            !(owner.owner===null || (Number.isSafeInteger(owner.owner) && owner.owner>0)))
          throw Error('Deployment fence release cannot be confirmed');
      }
      released=true;emit('released',current);break;
    }
    if(!released)throw Error('Mode control ended without release confirmation');
  } finally {reader.close();input.pause?.();}
  // Caller must destroy its dedicated physical connection on every failed path.
}
