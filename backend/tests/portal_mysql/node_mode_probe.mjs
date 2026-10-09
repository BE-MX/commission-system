/** Actual mysql2 connection to an owned loopback MySQL only; never a provider call. */
import fs from 'node:fs';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
const config=JSON.parse(fs.readFileSync(0,'utf8'));
if(config.connection.host!=='127.0.0.1' || config.connection.database!=='portal_isolated_test' ||
    !Number.isInteger(config.connection.port) || config.connection.port<1 || config.connection.port>65535)
  throw Error('Invalid owned Node MySQL target');
const driver=await import(pathToFileURL(path.resolve(process.argv[2])).href);
const mysql=driver.default||driver;
const {readExecutionMode,assertLegacyMode}=await import(pathToFileURL(config.module).href);
let connection;
try {
  connection=await mysql.createConnection({...config.connection,connectTimeout:5000,trace:false});
  const [[identity]]=await connection.query('SELECT @@server_uuid AS uuid, @@bind_address AS address, @@port AS port');
  if(identity.uuid!==config.server_uuid || identity.address!=='127.0.0.1' || identity.port!==config.connection.port)
    throw Error('Owned server identity mismatch');
  const [[table]]=await connection.query(
    'SELECT COUNT(*) AS count FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name=?',
    ['ark_order_portal_auth_barriers']);
  let mode=null,mode_error=null,gate_error=null,legacy_allowed=false;
  try {mode=await readExecutionMode(connection);} catch(error) {mode_error=error.message;}
  try {await assertLegacyMode(connection);legacy_allowed=true;} catch(error) {gate_error=error.message;}
  console.log(JSON.stringify({metadata_count:table.count,mode,mode_error,legacy_allowed,gate_error}));
} catch {
  console.error('Owned Node mode probe is unavailable');
  process.exitCode=1;
} finally {
  if(connection)await connection.end();
}
