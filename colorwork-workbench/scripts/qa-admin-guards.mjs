import { createHmac } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { mkdir, writeFile } from 'node:fs/promises';
import { request as httpRequest } from 'node:http';
import path from 'node:path';
import process from 'node:process';
import { fileURLToPath } from 'node:url';

const projectDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const outputPath = path.join(projectDir, 'outputs', 'qa-admin-guards.json');
const baseUrl = (process.argv.find((value) => value.startsWith('--base-url='))?.split('=')[1] || 'http://127.0.0.1:4174').replace(/\/$/, '');
const templateId = 'tape-hair-super';

function assert(condition, message, details) {
  if (!condition) throw new Error(`${message}${details === undefined ? '' : `：${JSON.stringify(details)}`}`);
}

async function request(urlPath, identity, options = {}) {
  const headers = { connection: 'close', ...(typeof identity === 'string' ? {} : identity), ...options.headers };
  let body = options.body;
  if (options.json !== undefined) {
    headers['content-type'] = 'application/json';
    body = JSON.stringify(options.json);
  }
  if (body != null) headers['content-length'] = String(Buffer.byteLength(body));
  for (let attempt = 0; attempt < 3; attempt += 1) {
    let result;
    try {
      result = await new Promise((resolve, reject) => {
        const call = httpRequest(`${baseUrl}${urlPath}`, {
          method: options.method || 'GET',
          headers,
          agent: false,
        }, (response) => {
          const chunks = [];
          response.on('data', (chunk) => chunks.push(chunk));
          response.on('end', () => {
            const payload = Buffer.concat(chunks);
            const contentType = response.headers['content-type'] || '';
            let data = payload;
            if (contentType.includes('application/json')) {
              try {
                data = JSON.parse(payload.toString('utf8'));
              } catch {
                reject(new Error('接口返回了无效 JSON。'));
                return;
              }
            }
            resolve({ status: response.statusCode || 0, data, headers: response.headers });
          });
        });
        call.setTimeout(45_000, () => call.destroy(new Error('请求超过 45 秒。')));
        call.on('error', reject);
        if (body != null) call.write(body);
        call.end();
      });
    } catch (error) {
      throw new Error(`${options.method || 'GET'} ${urlPath} 请求失败：${error instanceof Error ? error.message : String(error)}`);
    }
    if (result.status !== 503 || attempt === 2) return result;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error('请求没有返回结果。');
}

// 账号与设置收归方舟后，站内登录口已移除；QA 用 .dev.vars 的 ARK_SSO_SECRET 自签
// SSO 令牌走 /api/auth/ark 落座，模拟方舟侧不同页面权限的用户。
function ssoSecret() {
  const vars = readFileSync(path.join(projectDir, '.dev.vars'), 'utf8');
  const line = vars.split('\n').find((row) => row.startsWith('ARK_SSO_SECRET='));
  assert(line, '.dev.vars 缺少 ARK_SSO_SECRET');
  return line.slice('ARK_SSO_SECRET='.length).trim();
}

function mintSsoToken(secret, claims) {
  const b64 = (obj) => Buffer.from(JSON.stringify(obj)).toString('base64url');
  const head = b64({ alg: 'HS256', typ: 'JWT' });
  const body = b64({ aud: 'colorwork', iat: Math.floor(Date.now() / 1000), exp: Math.floor(Date.now() / 1000) + 120, ...claims });
  const sig = createHmac('sha256', secret).update(`${head}.${body}`).digest('base64url');
  return `${head}.${body}.${sig}`;
}

async function ssoLogin(username, views) {
  const token = mintSsoToken(ssoSecret(), { sub: `qa-${username}`, username, name: username, views });
  const result = await request(`/api/auth/ark?token=${encodeURIComponent(token)}&view=${views[0]}`, {});
  assert(result.status === 302, `${username} SSO 落座失败`, result);
  const cookieHeader = result.headers?.['set-cookie'];
  const cookie = Array.isArray(cookieHeader) ? cookieHeader[0] : cookieHeader;
  assert(typeof cookie === 'string' && cookie.includes('inventory_workbench_session='), `${username} 没有返回站内会话`, result);
  return { cookie: cookie.split(';', 1)[0] };
}
const admin = await ssoLogin('QaAdmin', ['library', 'inventory', 'master']);
const member = await ssoLogin('QaMember', ['library', 'inventory']);
const adminList = await request(`/api/template-sources/${templateId}`, admin);
assert(adminList.status === 200 && Array.isArray(adminList.data.versions), '管理员无法读取源文件版本记录', adminList);
// 未导入素材的环境 versions 为空：跳过需要真实源版本的用例（activate），其余权限校验照常
const sourceVersion = adminList.data.versions[0] ?? null;
const checks = [];
for (const test of [
  {
    name: '业务账号不能读取源版本管理接口',
    call: () => request(`/api/template-sources/${templateId}`, member),
    status: 403,
  },
  {
    name: '业务账号不能创建源版本',
    call: () => request(`/api/template-sources/${templateId}`, member, { method: 'POST', json: {} }),
    status: 403,
  },
  {
    name: '业务账号仍可读取当前业务库存',
    call: () => request(`/api/inventory/${templateId}`, member),
    status: 200,
  },
  {
    name: '库存图权限账号不能访问母版当前快照',
    call: () => request(`/api/master/${templateId}/current`, member),
    status: 403,
  },
  ...(sourceVersion ? [{
    // Keep this dynamic mutation route last. Wrangler's production-build
    // watcher restarts once when it compiles the route for the first time.
    name: '业务账号不能启用源版本',
    call: () => request(`/api/template-sources/${templateId}/${sourceVersion.id}/activate`, member, { method: 'POST', json: {} }),
    status: 403,
  }] : []),
]) {
  const result = await test.call();
  assert(result.status === test.status, test.name, { expected: test.status, actual: result.status, data: result.data });
  checks.push({ name: test.name, status: result.status });
}

const report = {
  passed: true,
  baseUrl,
  templateId,
  adminSourceVersionCount: adminList.data.versions.length,
  checks,
};
await mkdir(path.dirname(outputPath), { recursive: true });
await writeFile(outputPath, `${JSON.stringify(report, null, 2)}\n`);
process.stdout.write(`${JSON.stringify({ passed: true, reportPath: outputPath, checks }, null, 2)}\n`);
