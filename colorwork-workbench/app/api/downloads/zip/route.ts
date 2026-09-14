import { env } from 'cloudflare:workers';
import { authErrorResponse, requireView } from '@/lib/server/auth';

type Item = { kind: 'template' | 'artifact'; id: string; name?: string };

function crc32(data: Uint8Array) {
  let crc = 0xffffffff;
  for (const byte of data) {
    crc ^= byte;
    for (let bit = 0; bit < 8; bit += 1) crc = (crc >>> 1) ^ (crc & 1 ? 0xedb88320 : 0);
  }
  return (crc ^ 0xffffffff) >>> 0;
}

function u16(value: number) { return [value & 255, (value >>> 8) & 255]; }
function u32(value: number) { return [value & 255, (value >>> 8) & 255, (value >>> 16) & 255, (value >>> 24) & 255]; }

function zip(files: Array<{ name: string; data: Uint8Array }>) {
  const encoder = new TextEncoder();
  const chunks: Uint8Array[] = [];
  const central: Uint8Array[] = [];
  let offset = 0;
  for (const file of files) {
    const name = encoder.encode(file.name);
    const crc = crc32(file.data);
    const local = Uint8Array.from([0x50, 0x4b, 0x03, 0x04, ...u16(20), ...u16(0x800), ...u16(0), ...u16(0), ...u16(0), ...u32(crc), ...u32(file.data.length), ...u32(file.data.length), ...u16(name.length), ...u16(0), ...name]);
    chunks.push(local, file.data);
    const entry = Uint8Array.from([0x50, 0x4b, 0x01, 0x02, ...u16(20), ...u16(20), ...u16(0x800), ...u16(0), ...u16(0), ...u16(0), ...u16(0), ...u32(crc), ...u32(file.data.length), ...u32(file.data.length), ...u16(name.length), ...u16(0), ...u16(0), ...u16(0), ...u16(0), ...u32(offset), ...name]);
    central.push(entry);
    offset += local.length + file.data.length;
  }
  const centralOffset = offset;
  const centralSize = central.reduce((sum, entry) => sum + entry.length, 0);
  const end = Uint8Array.from([0x50, 0x4b, 0x05, 0x06, ...u16(0), ...u16(0), ...u16(files.length), ...u16(files.length), ...u32(centralSize), ...u32(centralOffset), ...u16(0)]);
  const output = new Uint8Array(centralOffset + centralSize + end.length);
  let cursor = 0;
  for (const chunk of [...chunks, ...central, end]) { output.set(chunk, cursor); cursor += chunk.length; }
  return output;
}

export async function POST(request: Request) {
  try {
    const user = await requireView('library');
    const input = await request.json<{ items?: unknown }>().catch(() => ({ items: undefined }));
    const items = Array.isArray(input.items) ? input.items.filter((item: unknown): item is Item => {
      if (!item || typeof item !== 'object') return false;
      const value = item as Partial<Item>;
      return (value.kind === 'template' || value.kind === 'artifact') && typeof value.id === 'string' && value.id.length <= 160;
    }).slice(0, 100) : [];
    if (!items.length) return Response.json({ error: '请选择至少一张图片。' }, { status: 400 });
    const files: Array<{ name: string; data: Uint8Array }> = [];
    for (const item of items) {
      const row = item.kind === 'template'
        ? await env.DB.prepare(`SELECT reference_jpg_key AS key, reference_jpg_name AS name FROM template_files WHERE template_id = ?`).bind(item.id).first<{ key: string; name: string }>()
        : await env.DB.prepare(`SELECT jpg_key AS key, name FROM artifacts WHERE id = ? AND status = 'ready'`).bind(item.id).first<{ key: string; name: string }>();
      if (!row) continue;
      if (item.kind === 'artifact' && user.role !== 'admin') {
        const allowed = await env.DB.prepare(`SELECT 1 AS ok FROM artifacts a JOIN users u ON u.id = a.owner_user_id WHERE a.id = ? AND (a.owner_user_id = ? OR u.role = 'admin')`).bind(item.id, user.id).first();
        if (!allowed) continue;
      }
      const object = await env.FILES.get(row.key);
      if (!object) continue;
      const safe = (item.name || row.name || `${item.id}.jpg`).replace(/[\\/:*?"<>|]/g, '-').replace(/\.jpg$/i, '') + '.jpg';
      files.push({ name: safe, data: new Uint8Array(await object.arrayBuffer()) });
    }
    if (!files.length) return Response.json({ error: '所选图片暂时不可用。' }, { status: 404 });
    const body = zip(files);
    return new Response(body, { headers: { 'content-type': 'application/zip', 'content-disposition': `attachment; filename*=UTF-8''${encodeURIComponent('库存图片批量下载.zip')}`, 'content-length': String(body.byteLength), 'cache-control': 'private, no-store' } });
  } catch (error) { return authErrorResponse(error); }
}
