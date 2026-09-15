import { createHash, createHmac } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';
import { fileURLToPath } from 'node:url';
import sharp from 'sharp';

const projectDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const outputPath = path.join(projectDir, 'outputs', 'qa-artifact-immutability.json');
const baseUrl = (process.argv.find((value) => value.startsWith('--base-url='))?.split('=')[1] || 'http://localhost:4173').replace(/\/$/, '');
const templateId = 'tape-hair-super';

function assert(condition, message, details) {
  if (!condition) throw new Error(`${message}${details === undefined ? '' : `：${JSON.stringify(details)}`}`);
}

// 站内登录口已移除（账号与权限收归方舟）：用 .dev.vars 的 ARK_SSO_SECRET 自签 SSO 令牌换会话
function ssoSessionCookie() {
  const vars = readFileSync(path.join(projectDir, '.dev.vars'), 'utf8');
  const line = vars.split('\n').find((row) => row.startsWith('ARK_SSO_SECRET='));
  assert(line, '.dev.vars 缺少 ARK_SSO_SECRET');
  const secret = line.slice('ARK_SSO_SECRET='.length).trim();
  const b64 = (obj) => Buffer.from(JSON.stringify(obj)).toString('base64url');
  const now = Math.floor(Date.now() / 1000);
  const head = b64({ alg: 'HS256', typ: 'JWT' });
  const body = b64({ sub: 'qa-artifact', username: 'qa-artifact', name: 'QA-Artifact', views: ['library', 'inventory', 'master'], aud: 'colorwork', iat: now, exp: now + 120 });
  const sig = createHmac('sha256', secret).update(`${head}.${body}`).digest('base64url');
  return fetch(`${baseUrl}/api/auth/ark?token=${head}.${body}.${sig}&view=inventory`, { redirect: 'manual' })
    .then((response) => {
      assert(response.status === 302, 'SSO 落座失败', { status: response.status });
      const cookie = response.headers.get('set-cookie') || '';
      assert(cookie.includes('inventory_workbench_session='), 'SSO 没有返回站内会话', { cookie });
      return cookie.split(';', 1)[0];
    });
}
const sessionCookie = await ssoSessionCookie();

function sha256(value) {
  return createHash('sha256').update(value).digest('hex');
}

async function request(urlPath, options = {}) {
  const headers = { cookie: sessionCookie, ...options.headers };
  let body = options.body;
  if (options.json !== undefined) {
    headers['content-type'] = 'application/json';
    body = JSON.stringify(options.json);
  }
  const response = await fetch(`${baseUrl}${urlPath}`, { ...options, headers, body });
  const contentType = response.headers.get('content-type') || '';
  const data = contentType.includes('application/json') ? await response.json() : Buffer.from(await response.arrayBuffer());
  return { status: response.status, data };
}

async function expect(urlPath, options, expectedStatus) {
  const result = await request(urlPath, options);
  assert(result.status === expectedStatus, `${options?.method || 'GET'} ${urlPath} 状态错误`, result);
  return result;
}

async function createArtifact(snapshot, suffix) {
  const created = await expect('/api/artifacts', {
    method: 'POST',
    json: {
      name: `artifact-immutability-${suffix}`,
      templateId,
      expectedMasterRevision: snapshot.masterRevision,
      expectedInventoryRevision: snapshot.inventoryRevision,
      expectedSourceVersionId: snapshot.sourceVersion.id,
    },
  }, 201);
  return created.data.artifact.id;
}

const snapshot = (await expect(`/api/inventory/${templateId}`, {}, 200)).data;
const firstJpg = await sharp({
  create: {
    width: snapshot.template.width,
    height: snapshot.template.height,
    channels: 3,
    background: '#d8cab8',
  },
}).jpeg({ quality: 86 }).toBuffer();
const secondJpg = await sharp({
  create: {
    width: snapshot.template.width,
    height: snapshot.template.height,
    channels: 3,
    background: '#8aa5b5',
  },
}).jpeg({ quality: 86 }).toBuffer();

const sealedId = await createArtifact(snapshot, `sealed-${Date.now()}`);
await expect(`/api/artifacts/${sealedId}/file/jpg`, { method: 'PUT', body: firstJpg }, 200);
const overwrite = await expect(`/api/artifacts/${sealedId}/file/jpg`, { method: 'PUT', body: secondJpg }, 409);
assert(overwrite.data.code === 'ARTIFACT_IMMUTABLE', '不同内容没有被不可变保护拦截', overwrite.data);
await expect(`/api/artifacts/${sealedId}`, { method: 'PATCH', json: { jpgOnly: true } }, 200);
await expect(`/api/artifacts/${sealedId}`, { method: 'PATCH', json: { status: 'failed' } }, 409);
const sealedDownload = await expect(`/api/artifacts/${sealedId}/download/jpg`, {}, 200);
assert(sha256(sealedDownload.data) === sha256(firstJpg), '失败回调改变或删除了已封存成品。');
const sealedDetail = await expect(`/api/artifacts/${sealedId}`, {}, 200);
assert(sealedDetail.data.artifact.config.sourceVersion.id === snapshot.sourceVersion.id, '历史成品没有保持源版本关联。');

const races = [];
for (let index = 0; index < 3; index += 1) {
  const id = await createArtifact(snapshot, `race-${Date.now()}-${index + 1}`);
  await expect(`/api/artifacts/${id}/file/jpg`, { method: 'PUT', body: firstJpg }, 200);
  const [finalize, fail] = await Promise.all([
    request(`/api/artifacts/${id}`, { method: 'PATCH', json: { jpgOnly: true } }),
    request(`/api/artifacts/${id}`, { method: 'PATCH', json: { status: 'failed' } }),
  ]);
  assert([finalize.status, fail.status].sort((left, right) => left - right).join(',') === '200,409', '并发封存与失败回调没有唯一胜者', {
    finalizeStatus: finalize.status,
    failStatus: fail.status,
  });
  const download = await request(`/api/artifacts/${id}/download/jpg`);
  if (finalize.status === 200) {
    assert(download.status === 200 && sha256(download.data) === sha256(firstJpg), '封存胜出后文件不完整。', { downloadStatus: download.status });
  } else {
    assert(download.status === 403, '失败回调胜出后成品仍被当作已封存文件提供。', { downloadStatus: download.status });
  }
  races.push({ id, finalizeStatus: finalize.status, failStatus: fail.status, downloadStatus: download.status });
}

const report = {
  passed: true,
  templateId,
  sourceVersionId: snapshot.sourceVersion.id,
  sealedArtifact: {
    id: sealedId,
    hash: sha256(firstJpg),
    overwriteCode: overwrite.data.code,
    failureAfterReadyStatus: 409,
  },
  races,
};
await mkdir(path.dirname(outputPath), { recursive: true });
await writeFile(outputPath, `${JSON.stringify(report, null, 2)}\n`);
process.stdout.write(`${JSON.stringify({ passed: true, reportPath: outputPath, sealedArtifactId: sealedId, races }, null, 2)}\n`);
