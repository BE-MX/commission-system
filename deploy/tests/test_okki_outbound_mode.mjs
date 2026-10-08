import test from 'node:test';
import assert from 'node:assert/strict';
import {assertLegacyMode,readExecutionMode,acquireCreatorFence,WORKER_LOCK} from '../okki_outbound_mode.mjs';

const SAFE = 'Outbound protocol mode cannot be confirmed';
const PARENT = '171_customer_tag_display_value';
const missing = (changes={}) => Object.assign(Error('private-driver-connection-data'),
  {code:'ER_NO_SUCH_TABLE',errno:1146,sqlState:'42S02'},changes);
const rejectSafe = promise => assert.rejects(promise,error=>{
  assert.equal(error.message,SAFE); assert.equal(error.cause,undefined); return true;
});

test('known durable mode prohibits legacy; readable initial empty namespace allows it',async()=>{
  await assertLegacyMode({query:async()=>[[]]});
  const conn={query:async()=>[[{code:'outbound-worker-v1',version:1}]]};
  assert.equal(await readExecutionMode(conn),'outbound-worker-v1');
  await assert.rejects(assertLegacyMode(conn),/legacy creation is prohibited/);
});

test('standalone creator owns and releases the same DB executor fence',async()=>{
  const calls=[];
  const release=await acquireCreatorFence({query:async(sql,args)=>{calls.push([sql,args]);return [[{acquired:1}]];}});
  await release();assert.deepEqual(calls.map(row=>row[1]),[[WORKER_LOCK],[WORKER_LOCK]]);
});
test('busy standalone and missing parent ownership stop creation',async()=>{
  await assert.rejects(acquireCreatorFence({query:async()=>[[{acquired:0}]]}),/Another outbound/);
  await assert.rejects(acquireCreatorFence({query:async()=>[[{owner:6}]]},'7'),/missing/);
  await assert.rejects(acquireCreatorFence({query:async()=>{throw Error('unexpected SQL');}},'007'),/Invalid/);
});
test('managed creator validates its parent DB session rather than acquiring a second lock',async()=>{
  const calls=[];
  const release=await acquireCreatorFence({query:async(sql,args)=>{calls.push([sql,args]);return [[{owner:7}]];}},'7');
  await release();assert.equal(calls.length,1);assert.match(calls[0][0],/IS_USED_LOCK/);
});

for (const [name,rows] of [
  ['future mode',[{code:'outbound-worker-v2',version:1}]],
  ['bad known version',[{code:'outbound-worker-v1',version:2}]],
  ['missing version',[{code:'outbound-worker-v1'}]],
  ['string version',[{code:'outbound-worker-v1',version:'1'}]],
  ['multiple modes',[{code:'outbound-worker-v1',version:1},{code:'outbound-worker-v2',version:1}]],
  ['invalid result',undefined],['null result',null],['object result',{}],['null row',[null]],
]) test('unconfirmed '+name+' cannot permit legacy',async()=>{
  await rejectSafe(assertLegacyMode({query:async(sql)=>[
    sql.includes("WHERE code='outbound-worker-v1'")?rows.filter(row=>row.code==='outbound-worker-v1'):rows
  ]}));
});

test('mode SQL reads the complete protocol namespace directly, without metadata absence inference',async()=>{
  const calls=[];
  await assertLegacyMode({query:async(sql)=>{calls.push(sql);return [[]];}});
  assert.equal(calls.length,1);assert.match(calls[0],/SELECT code,\s*version/);
  assert.match(calls[0],/LIKE 'outbound-worker-%'/);assert.doesNotMatch(calls[0],/information_schema/);
});

test('verified missing table and exact sole pre-portal head permit legacy on the same connection',async()=>{
  const calls=[];
  const conn={query:async(sql)=>{
    calls.push(sql);if(calls.length===1)throw missing();return [[{version_num:PARENT}]];
  }};
  await assertLegacyMode(conn);
  assert.equal(calls.length,2);assert.match(calls[0],/FROM ark_order_portal_auth_barriers/);
  assert.equal(calls[1],'SELECT version_num FROM alembic_version');
});

for(const [name,error] of [
  ['table permission denial',Object.assign(Error('private-password-data'),{code:'ER_TABLEACCESS_DENIED_ERROR',errno:1142,sqlState:'42000'})],
  ['schema permission denial',Object.assign(Error('private-password-data'),{code:'ER_DBACCESS_DENIED_ERROR',errno:1044,sqlState:'42000'})],
  ['transport failure',Object.assign(Error('private-password-data'),{code:'ECONNRESET'})],
  ['only symbolic missing',missing({errno:undefined,sqlState:undefined})],
  ['wrong numeric error',missing({errno:1142})],['string numeric error',missing({errno:'1146'})],
  ['wrong SQL state',missing({sqlState:'42000'})],['plain message',Error('ER_NO_SUCH_TABLE 1146 42S02 private-password-data')],
]) test(name+' never enters pre-portal compatibility',async()=>{
  let calls=0;
  await rejectSafe(readExecutionMode({query:async()=>{
    if(++calls===1)throw error;return [[{version_num:PARENT}]];
  }}));assert.equal(calls,1);
});

for(const [name,heads] of [
  ['empty',[]],['multiple',[{version_num:PARENT},{version_num:'175_customer_order_portal'}]],
  ['duplicate parent',[{version_num:PARENT},{version_num:PARENT}]],
  ['missing value',[{}]],['null row',[null]],['non-array',{}],['undefined',undefined],
  ['portal migration',[{version_num:'175_customer_order_portal'}]],
  ['PI migration',[{version_num:'176_portal_pi_header'}]],['unknown',[{version_num:'999_unknown'}]],
  ['older unverified',[{version_num:'170_order_channel'}]],['whitespace',[{version_num:PARENT+' '}]],
]) test('missing mode table with '+name+' head fails closed',async()=>{
  let calls=0;
  await rejectSafe(assertLegacyMode({query:async()=>{if(++calls===1)throw missing();return [heads];}}));
  assert.equal(calls,2);
});

for(const error of [missing(),Object.assign(Error('private-password-data'),{errno:1142}),Error('private-password-data')])
  test('unavailable schema-head read returns only the safe error '+String(error.errno||'other'),async()=>{
    let calls=0;
    await rejectSafe(assertLegacyMode({query:async()=>{if(++calls===1)throw missing();throw error;}}));
    assert.equal(calls,2);
  });
