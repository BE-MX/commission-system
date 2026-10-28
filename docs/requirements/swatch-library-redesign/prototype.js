'use strict';
/* ============ 色彩计算 ============ */
const ColorMath = {
  labToRgb([L, a, b]) {
    let y = (L + 16) / 116, x = a / 500 + y, z = y - b / 200;
    const f = t => (t ** 3 > 0.008856 ? t ** 3 : (t - 16 / 116) / 7.787);
    x = 0.95047 * f(x); y = 1.0 * f(y); z = 1.08883 * f(z);
    let r = x * 3.2406 + y * -1.5372 + z * -0.4986;
    let g = x * -0.9689 + y * 1.8758 + z * 0.0415;
    let bl = x * 0.0557 + y * -0.204 + z * 1.057;
    const gam = c => (c > 0.0031308 ? 1.055 * c ** (1 / 2.4) - 0.055 : 12.92 * c);
    return [r, g, bl].map(c => Math.max(0, Math.min(255, Math.round(gam(c) * 255))));
  },
  hex(rgb) { return '#' + rgb.map(v => v.toString(16).padStart(2, '0')).join('').toUpperCase(); },
  de76(p, q) { return Math.hypot(p[0] - q[0], p[1] - q[1], p[2] - q[2]); },
  de00([L1, a1, b1], [L2, a2, b2]) {
    const rad = Math.PI / 180, deg = 180 / Math.PI;
    const C1 = Math.hypot(a1, b1), C2 = Math.hypot(a2, b2), Cb = (C1 + C2) / 2;
    const G = 0.5 * (1 - Math.sqrt(Cb ** 7 / (Cb ** 7 + 25 ** 7)));
    const ap1 = (1 + G) * a1, ap2 = (1 + G) * a2;
    const Cp1 = Math.hypot(ap1, b1), Cp2 = Math.hypot(ap2, b2);
    const hp = (b, ap) => (b === 0 && ap === 0 ? 0 : (Math.atan2(b, ap) * deg + 360) % 360);
    const h1 = hp(b1, ap1), h2 = hp(b2, ap2);
    const dL = L2 - L1, dC = Cp2 - Cp1;
    let dh = 0;
    if (Cp1 * Cp2 !== 0) { dh = h2 - h1; if (dh > 180) dh -= 360; else if (dh < -180) dh += 360; }
    const dH = 2 * Math.sqrt(Cp1 * Cp2) * Math.sin((dh / 2) * rad);
    const Lb = (L1 + L2) / 2, Cpb = (Cp1 + Cp2) / 2;
    let hb = h1 + h2;
    if (Cp1 * Cp2 !== 0) { hb = Math.abs(h1 - h2) <= 180 ? hb / 2 : (hb < 360 ? (hb + 360) / 2 : (hb - 360) / 2); }
    const T = 1 - 0.17 * Math.cos((hb - 30) * rad) + 0.24 * Math.cos(2 * hb * rad) + 0.32 * Math.cos((3 * hb + 6) * rad) - 0.2 * Math.cos((4 * hb - 63) * rad);
    const dTh = 30 * Math.exp(-(((hb - 275) / 25) ** 2));
    const Rc = 2 * Math.sqrt(Cpb ** 7 / (Cpb ** 7 + 25 ** 7));
    const Sl = 1 + (0.015 * (Lb - 50) ** 2) / Math.sqrt(20 + (Lb - 50) ** 2);
    const Sc = 1 + 0.045 * Cpb, Sh = 1 + 0.015 * Cpb * T;
    const Rt = -Math.sin(2 * dTh * rad) * Rc;
    return Math.sqrt((dL / Sl) ** 2 + (dC / Sc) ** 2 + (dH / Sh) ** 2 + Rt * (dC / Sc) * (dH / Sh));
  },
  rgbToCmyk([r, g, b]) {
    const k = 1 - Math.max(r, g, b) / 255;
    if (k >= 1) return [0, 0, 0, 100];
    return [r, g, b].map(v => Math.round(((1 - v / 255 - k) / (1 - k)) * 100)).concat(Math.round(k * 100));
  },
};

/* ============ LSColor 协议（按技术说明 v1.0） ============ */
const Proto = {
  PROFILES: [
    { name: 'A', notifySvc: 0xffe0, notifyChr: 0xffe4, writeSvc: 0xffe5, writeChr: 0xffe9 },
    { name: 'B', notifySvc: 0xfff0, notifyChr: 0xfff1, writeSvc: 0xfff0, writeChr: 0xfff1 },
    { name: 'C', notifySvc: 0x1001, notifyChr: 0x1002, writeSvc: 0x1001, writeChr: 0x1002 },
  ],
  SERVICES: [0xffe0, 0xffe5, 0xfff0, 0x1001],
  CMD: { info: 'AB2005001200946B', measure: 'AB440000000036001864', voltage: 'AB200B0002009B43', eventRead: 'AB400000000014004504' },
  PREFIX: { info: 'ab2005001200', measure: 'ab4400000000', voltage: 'ab200b000200', event: 'aba00479e3', eventData: 'ab40000000001400' },
  crc16(data) {
    let crc = 0xffff;
    for (const v of data) { crc ^= v; for (let i = 0; i < 8; i++) crc = crc & 1 ? (crc >>> 1) ^ 0xa001 : crc >>> 1; }
    return crc;
  },
  validCRC(f) { if (f.length < 3) return false; const c = this.crc16(f.subarray(0, f.length - 2)); return f[f.length - 2] === (c & 0xff) && f[f.length - 1] === c >> 8; },
  hexToBytes(h) { return Uint8Array.from(h.match(/../g).map(x => parseInt(x, 16))); },
  toHex(b) { return Array.from(b, x => x.toString(16).padStart(2, '0')).join(''); },
  decodeMeasurement(frame) {
    const v = new DataView(frame.buffer, frame.byteOffset, frame.byteLength);
    const i16 = (o, d = 100) => v.getInt16(o, true) / d;
    const unsignedHue = parseInt(this.toHex(frame.slice(20, 26)), 16) > 32767;
    return {
      lab: [i16(8), i16(10), i16(12)], luv: [i16(14), i16(16), i16(18)],
      lch: [i16(20), i16(22), (unsignedHue ? v.getUint16(24, true) : v.getInt16(24, true)) / 100],
      yxy: [i16(26), i16(28, 10000), i16(30, 10000)],
      cmyk: Array.from(frame.slice(32, 36)), rgb: Array.from(frame.slice(36, 39)),
      raw: this.toHex(frame).toUpperCase(),
    };
  },
  decodeInfo(frame) {
    const v = new DataView(frame.buffer, frame.byteOffset, frame.byteLength);
    return { sn: String(v.getUint32(12, true)), material: v.getUint32(16, true), fw: (v.getUint16(22, true) / 100).toFixed(2) };
  },
  /* 模拟器用：构造一条 CRC 有效的 64 字节 44 帧 */
  buildMeasureFrame(lab) {
    const f = new Uint8Array(64); f.set(this.hexToBytes('AB44000000003600'));
    const v = new DataView(f.buffer);
    const s = (o, x, d = 100) => v.setInt16(o, Math.round(x * d), true);
    const [L, a, b] = lab, C = Math.hypot(a, b), h = (Math.atan2(b, a) * 180 / Math.PI + 360) % 360;
    const rgb = ColorMath.labToRgb(lab), cmyk = ColorMath.rgbToCmyk(rgb);
    s(8, L); s(10, a); s(12, b); s(14, L); s(16, a * 1.18); s(18, b * 1.05);
    s(20, L); s(22, C); v.setUint16(24, Math.round(h * 100), true);
    const Y = ((L + 16) / 116) ** 3 * 100; s(26, Y); s(28, 0.3127 + a / 2200, 10000); s(30, 0.329 + b / 2600, 10000);
    f.set(cmyk, 32); f.set(rgb, 36);
    const c = this.crc16(f.subarray(0, 62)); f[62] = c & 0xff; f[63] = c >> 8;
    return f;
  },
};

/* 简化组帧：拼接分片 → 找 AB → 按类型定边界并校验 CRC */
class FrameStream {
  constructor(onFrame, onLog) { this.buf = new Uint8Array(0); this.onFrame = onFrame; this.onLog = onLog; this.timer = null; }
  push(chunk) {
    const n = new Uint8Array(this.buf.length + chunk.length); n.set(this.buf); n.set(chunk, this.buf.length); this.buf = n;
    if (this.buf.length > 2048) { this.onLog('缓存溢出，已丢弃'); this.buf = new Uint8Array(0); return; }
    clearTimeout(this.timer); this.timer = setTimeout(() => { if (this.buf.length) { this.onLog('不完整帧超时，已清空'); this.buf = new Uint8Array(0); } }, 2000);
    this.drain();
  }
  drain() {
    for (;;) {
      const s = this.buf.indexOf(0xab); if (s < 0) { this.buf = new Uint8Array(0); return; }
      if (s > 0) this.buf = this.buf.slice(s);
      if (this.buf.length < 5) return;
      const t = this.buf[1]; let end = 0;
      if (t === 0x20) { if (this.buf.length < 6) return; const len = 8 + (this.buf[4] | (this.buf[5] << 8)); if (len > 1024) { this.buf = this.buf.slice(1); continue; } if (this.buf.length < len) return; end = len; if (!Proto.validCRC(this.buf.subarray(0, end))) { this.onLog('20 类 CRC 错误'); this.buf = this.buf.slice(1); continue; } }
      else if (t === 0x44 || t === 0x40 || t === 0xa0) { const min = t === 0x44 ? 41 : t === 0x40 ? 10 : 5; for (let L = min; L <= Math.min(this.buf.length, 1024); L++) if (Proto.validCRC(this.buf.subarray(0, L))) { end = L; break; } if (!end) return; }
      else { this.buf = this.buf.slice(1); continue; }
      const frame = this.buf.slice(0, end); this.buf = this.buf.slice(end); this.onFrame(frame);
    }
  }
}

/* ============ 设备层：模拟 / Web Bluetooth ============ */
const Device = {
  state: 0, // 0 未连接 1 GATT 2 通知 3 初始化已确认 4 可测量
  info: null, voltage: null, name: null, profile: null, sessionId: null,
  pending: null, queue: Promise.resolve(), ble: null,
  listeners: {},
  on(e, fn) { (this.listeners[e] ||= []).push(fn); },
  emit(e, d) { (this.listeners[e] || []).forEach(fn => fn(d)); },
  setState(s) { this.state = s; this.emit('state', s); },
  log(m) { this.emit('log', m); },

  handleFrame(frame) {
    const hex = Proto.toHex(frame);
    this.log('FRAME ' + hex.toUpperCase().slice(0, 40) + (hex.length > 40 ? '…' : ''));
    if (hex === Proto.PREFIX.event) { this.log('A0 事件 → 排队读取 40 类（仅诊断，不入库）'); this.send(Proto.CMD.eventRead, Proto.PREFIX.eventData).catch(() => {}); return; }
    if (this.pending && hex.startsWith(this.pending.prefix)) { const p = this.pending; this.pending = null; p.resolve(frame); return; }
    if (hex.startsWith(Proto.PREFIX.measure)) this.emit('late', Proto.decodeMeasurement(frame));
  },

  send(cmdHex, prefix, timeout = 8000) {
    const run = () => new Promise((resolve, reject) => {
      const timer = setTimeout(() => { this.pending = null; reject(new Error('结果超时（8 秒），未自动重发')); }, timeout);
      this.pending = { prefix, resolve: f => { clearTimeout(timer); resolve(f); } };
      this.log('TX ' + cmdHex);
      (devMode === 'sim' ? Sim.write(cmdHex) : this.bleWrite(Proto.hexToBytes(cmdHex))).catch(e => { clearTimeout(timer); this.pending = null; reject(e); });
    });
    const p = this.queue.then(run, run); this.queue = p.catch(() => {}); return p;
  },

  async connect() {
    this.sessionId = crypto.randomUUID ? crypto.randomUUID() : String(Date.now());
    this.stream = new FrameStream(f => this.handleFrame(f), m => this.log(m));
    if (devMode === 'sim') await Sim.connect(this);
    else await this.bleConnect();
    try {
      const info = Proto.decodeInfo(await this.send(Proto.CMD.info, Proto.PREFIX.info)); this.info = info;
      const vf = await this.send(Proto.CMD.voltage, Proto.PREFIX.voltage); const dv = new DataView(vf.buffer, vf.byteOffset);
      this.voltage = (dv.getUint16(6, true) / 10).toFixed(1);
      this.setState(3); await wait(250); this.setState(4);
    } catch (e) { this.log('初始化未确认：' + e.message); this.emit('initWarn'); this.setState(2); }
  },

  async bleConnect() {
    const dev = await navigator.bluetooth.requestDevice({ filters: [{ namePrefix: 'LS' }], optionalServices: Proto.SERVICES });
    this.name = dev.name; dev.addEventListener('gattserverdisconnected', () => this.reset('设备断开'));
    const server = await dev.gatt.connect(); this.setState(1); this.log('GATT 已连接 ' + dev.name);
    for (const p of Proto.PROFILES) {
      try {
        const ns = await server.getPrimaryService(p.notifySvc), nc = await ns.getCharacteristic(p.notifyChr);
        const ws = p.writeSvc === p.notifySvc ? ns : await server.getPrimaryService(p.writeSvc), wc = await ws.getCharacteristic(p.writeChr);
        if (!nc.properties.notify || !(wc.properties.write || wc.properties.writeWithoutResponse)) continue;
        this.ble = { dev, server, nc, wc, onValue: e => { const d = e.target.value; this.stream.push(new Uint8Array(d.buffer.slice(d.byteOffset, d.byteOffset + d.byteLength))); } };
        nc.addEventListener('characteristicvaluechanged', this.ble.onValue);
        await nc.startNotifications(); this.profile = p.name; this.setState(2); this.log('通知已开，配置 ' + p.name); return;
      } catch (_) { /* 尝试下一套 */ }
    }
    server.disconnect(); throw new Error('未找到可用的 GATT 通道（A/B/C 均不满足）');
  },
  bleWrite(bytes) { const c = this.ble.wc; return c.properties.write ? c.writeValueWithResponse(bytes) : c.writeValueWithoutResponse(bytes); },

  reset(reason) {
    if (this.pending) { this.pending = null; }
    if (this.ble) { try { this.ble.nc.removeEventListener('characteristicvaluechanged', this.ble.onValue); this.ble.server.disconnect(); } catch (_) {} this.ble = null; }
    Sim.disconnect(); this.info = null; this.voltage = null; this.profile = null; this.setState(0); if (reason) this.log(reason);
  },
  async measure() { return Proto.decodeMeasurement(await this.send(Proto.CMD.measure, Proto.PREFIX.measure)); },
};

/* 模拟仪器：返回 CRC 有效帧，并把每帧拆成 20 字节通知分片，走与真机相同的组帧路径 */
const Sim = {
  dev: null, target: null,
  async connect(dev) {
    this.dev = dev; dev.name = 'LS171-SIM'; await wait(400); dev.setState(1); dev.log('GATT 已连接 LS171-SIM（模拟）');
    await wait(300); dev.profile = 'A'; dev.setState(2); dev.log('通知已开，配置 A（FFE0/FFE4 → FFE5/FFE9）');
  },
  disconnect() { this.dev = null; },
  async write(hex) {
    const d = this.dev; if (!d) throw new Error('未连接');
    await wait(hex.startsWith('AB44') ? 650 + Math.random() * 300 : 120);
    let f;
    if (hex === Proto.CMD.info) { f = new Uint8Array(26); f.set(Proto.hexToBytes('AB20050012000000')); const v = new DataView(f.buffer); v.setUint32(12, 2410803317, true); v.setUint32(16, 1171, true); v.setUint16(22, 152, true); }
    else if (hex === Proto.CMD.voltage) { f = new Uint8Array(10); f.set(Proto.hexToBytes('AB200B000200')); new DataView(f.buffer).setUint16(6, 40, true); }
    else if (hex === Proto.CMD.measure) { const t = this.target || [50, 0, 0]; f = Proto.buildMeasureFrame([t[0] + rnd(0.45), t[1] + rnd(0.3), t[2] + rnd(0.35)]); }
    else return;
    if (hex === Proto.CMD.info || hex === Proto.CMD.voltage) { const c = Proto.crc16(f.subarray(0, f.length - 2)); f[f.length - 2] = c & 0xff; f[f.length - 1] = c >> 8; }
    for (let i = 0; i < f.length; i += 20) { d.stream.push(f.slice(i, i + 20)); await wait(15); }
  },
};
const wait = ms => new Promise(r => setTimeout(r, ms));
const rnd = s => (Math.random() * 2 - 1) * s;
let devMode = 'sim';

/* ============ 业务数据（原型样例） ============ */
const ME = { id: 7, name: '亮哥' };
const customers = [
  { id: 101, name: 'Bellamy Hair Studio', country: 'US', role: 'primary', color: '#8F6508' },
  { id: 102, name: 'Glamour Extensions Ltd', country: 'UK', role: 'primary', color: '#0F8479' },
  { id: 103, name: 'Hair Couture Melbourne', country: 'AU', role: 'collaborator', color: '#5B6BB5' },
  { id: 104, name: 'Luxe Locks Toronto', country: 'CA', role: 'primary', color: '#B75B09' },
  { id: 105, name: 'Sahara Beauty Dubai', country: 'AE', role: 'primary', color: '#9a3b52' },
];
const publicSwatches = [
  ['#1', 'Jet Black', [16.2, 0.6, 0.4]], ['#1B', 'Natural Black', [19.8, 1.4, 1.9]], ['#2', 'Darkest Brown', [22.6, 3.1, 4.2]],
  ['#4', 'Chocolate Brown', [29.4, 6.6, 9.8]], ['#6', 'Chestnut Brown', [36.1, 9.2, 14.6]], ['#8', 'Ash Brown', [42.8, 5.1, 11.9]],
  ['#18', 'Ash Blonde', [58.3, 3.2, 14.1]], ['#22', 'Light Beige Blonde', [70.4, 4.4, 19.6]], ['#60', 'Platinum Blonde', [84.1, 0.9, 13.8]],
  ['#613', 'Bleach Blonde', [82.6, 2.2, 24.3]], ['#99J', 'Burgundy', [27.5, 22.4, 6.1]], ['#30', 'Auburn', [40.6, 17.9, 26.4]],
].map(([code, name, lab], i) => mkSwatch({ id: 1000 + i, scope: 'public', code, name, size: 18, lab, n: 5, spread: 0.2 }));
let seq = 2000;
const privateSwatches = [
  { c: 101, code: '#1C', name: 'Off Black · 客户订制', size: 18, base: '#1B', lab: [20.6, 1.6, 2.4], n: 4 },
  { c: 101, code: '#1C', name: 'Off Black · 客户订制', size: 22, base: '#1B', lab: [21.1, 1.9, 2.8], n: 3 },
  { c: 101, code: '#8/60', name: 'Ash Balayage 根部', size: 20, base: '#8', lab: [44.2, 5.6, 13.4], n: 3 },
  { c: 101, code: 'BH-ASH-02', name: 'Bellamy 冷棕 2 号', size: 18, base: '#8', lab: [41.0, 3.1, 8.2], n: 5, spread: 0.55 },
  { c: 101, code: '#613', name: '大货对色', size: 24, base: '#613', lab: [81.4, 2.9, 26.1], n: 0 },
  { c: 102, code: '#4', name: 'Mocha', size: 16, base: '#4', lab: [30.2, 6.4, 10.5], n: 3 },
  { c: 102, code: '#18/22', name: 'Rooted Blonde', size: 20, base: '#18', lab: [62.1, 4.0, 16.8], n: 2 },
  { c: 103, code: '#99J', name: 'Merlot', size: 18, base: '#99J', lab: [28.4, 24.1, 5.6], n: 3 },
  { c: 104, code: '#60', name: 'Icy Platinum', size: 22, base: '#60', lab: [85.5, -0.8, 9.2], n: 4 },
  { c: 105, code: '#2', name: 'Espresso', size: 26, base: '#2', lab: [22.9, 3.4, 4.6], n: 3 },
].map(s => mkSwatch({ id: seq++, scope: 'private', customer: s.c, code: s.code, name: s.name, size: s.size, base: s.base, lab: s.lab, n: s.n, spread: s.spread }));
privateSwatches[0].late = [Proto.decodeMeasurement(Proto.buildMeasureFrame([20.9, 1.5, 2.2]))];

function mkSwatch({ id, scope, customer = null, code, name, size, unit = 'inch', base = null, lab, n, spread = 0.25 }) {
  const now = Date.now();
  const ms = Array.from({ length: n }, (_, i) => {
    const r = Proto.decodeMeasurement(Proto.buildMeasureFrame([lab[0] + rnd(spread * 1.6), lab[1] + rnd(spread), lab[2] + rnd(spread * 1.2)]));
    return { ...r, id: id * 100 + i, seq: i + 1, at: new Date(now - (n - i) * 86400000 * 0.6 - 3600000 * i), sn: '2410803317', status: 'matched', included: true };
  });
  return { id, scope, customer, code, name, size, unit, base, lab, tol: 1.5, measurements: ms, late: [] };
}

/* ============ 统计 ============ */
let deMode = '00';
const DE = (p, q) => (deMode === '00' ? ColorMath.de00(p, q) : ColorMath.de76(p, q));
function stats(sw) {
  const ms = sw.measurements.filter(m => m.included);
  if (!ms.length) return null;
  const avg = [0, 1, 2].map(i => ms.reduce((s, m) => s + m.lab[i], 0) / ms.length);
  const des = ms.map(m => DE(m.lab, avg));
  const baseLab = baseOf(sw);
  return {
    n: ms.length, avg,
    meanDE: ms.length > 1 ? des.reduce((a, b) => a + b, 0) / des.length : null,
    maxDE: ms.length > 1 ? Math.max(...des) : null,
    baseDE: baseLab ? DE(avg, baseLab) : null,
    rgb: [0, 1, 2].map(i => Math.round(ms.reduce((s, m) => s + m.rgb[i], 0) / ms.length)),
    cmyk: [0, 1, 2, 3].map(i => Math.round(ms.reduce((s, m) => s + m.cmyk[i], 0) / ms.length)),
  };
}
function baseOf(sw) {
  if (sw.scope === 'public' || !sw.base) return null;
  const b = publicSwatches.find(p => p.code === sw.base); if (!b) return null;
  const s = stats({ ...b, scope: 'x' }); return s ? s.avg : b.lab;
}
const verdict = (sw, st) => (!st ? 'none' : st.baseDE == null ? 'ok' : st.baseDE <= sw.tol ? 'ok' : 'warn');
const chipColor = sw => { const st = stats(sw); return ColorMath.hex(ColorMath.labToRgb(st ? st.avg : sw.lab)); };
const f2 = x => (x == null ? '—' : x.toFixed(2));

/* ============ 视图 ============ */
let scope = 'private', curCust = 101, curSw = null, view = 'lab';
const $ = id => document.getElementById(id);

function setScope(s) {
  scope = s; $('tabPrivate').classList.toggle('on', s === 'private'); $('tabPublic').classList.toggle('on', s === 'public');
  $('rail').style.display = s === 'private' ? '' : 'none';
  $('layout').style.gridTemplateColumns = s === 'private' ? '' : '1fr';
  renderAll();
}
function renderAll() { renderCounts(); renderCustomers(); renderCtx(); renderSizeFilter(); renderGrid(); }
function renderCounts() { $('cntPrivate').textContent = privateSwatches.length; $('cntPublic').textContent = publicSwatches.length; }
function renderCustomers() {
  const q = $('custQ').value.trim().toLowerCase();
  const list = customers.filter(c => c.name.toLowerCase().includes(q));
  $('custCnt').textContent = customers.length;
  $('custList').innerHTML = list.map(c => {
    const n = privateSwatches.filter(s => s.customer === c.id).length;
    return `<div class="cust ${c.id === curCust ? 'on' : ''}" onclick="curCust=${c.id};renderAll()">
      <div class="fl" style="background:${c.color}">${c.country}</div>
      <div class="nm"><b>${c.name}</b><span>${c.role === 'primary' ? '主负责' : '协作'}</span></div><span class="c">${n}</span></div>`;
  }).join('');
}
function renderCtx() {
  if (scope === 'public') {
    $('ctx').innerHTML = `<div><h2>公库 · 公司标准色</h2><div class="meta">全员可查看，色彩管理员维护；私库色板以此为对比基准</div></div>`;
    $('pubNote').innerHTML = '';
    return;
  }
  const c = customers.find(x => x.id === curCust);
  const list = privateSwatches.filter(s => s.customer === c.id);
  const warn = list.filter(s => verdict(s, stats(s)) === 'warn').length;
  $('ctx').innerHTML = `<div class="fl" style="width:36px;height:36px;border-radius:10px;background:${c.color};color:#fff;display:grid;place-items:center;font:700 12px Outfit">${c.country}</div>
    <div><h2>${c.name}</h2><div class="meta">私库 · ${list.length} 个色板${warn ? ` · <span style="color:var(--warn)">${warn} 个偏差</span>` : ''}${c.role === 'collaborator' ? ' · 你是协作人' : ''}</div></div>`;
  $('pubNote').innerHTML = '';
}
function currentList() { return scope === 'public' ? publicSwatches : privateSwatches.filter(s => s.customer === curCust); }
function renderSizeFilter() {
  const sizes = [...new Set(currentList().map(s => s.size + '″'))].sort((a, b) => parseFloat(a) - parseFloat(b));
  const cur = $('fSize').value;
  $('fSize').innerHTML = '<option value="">全部尺寸</option>' + sizes.map(s => `<option ${s === cur ? 'selected' : ''}>${s}</option>`).join('');
}
function renderGrid() {
  const q = $('swQ').value.trim().toLowerCase(), fs = $('fSize').value, st = $('fState').value;
  const list = currentList().filter(s => (!q || (s.code + s.name).toLowerCase().includes(q)) && (!fs || s.size + '″' === fs) && (!st || verdict(s, stats(s)) === st));
  const tiles = list.map(s => {
    const x = stats(s), v = verdict(s, x);
    const tag = v === 'none' ? '<span class="tag tag-mute">未测量</span>' : s.scope === 'public' ? '<span class="tag tag-gold">标准</span>' : v === 'ok' ? '<span class="tag tag-ok">符合</span>' : '<span class="tag tag-warn">偏差</span>';
    return `<div class="sw" onclick="openDrawer(${s.id})" tabindex="0" onkeydown="if(event.key==='Enter')openDrawer(${s.id})">
      <div class="chip" style="background:${chipColor(s)}"><span class="size">${s.size}″</span></div>
      <div class="body"><div class="code">${s.code} ${tag}</div><div class="sub">${s.name}${s.base ? ' · 基准 ' + s.base : ''}</div>
      <div class="stats"><div><b class="num">${x ? x.n : 0}</b>测量组</div><div><b class="num">${f2(x && x.meanDE)}</b>组内ΔE</div><div><b class="num" style="${v === 'warn' ? 'color:var(--warn)' : ''}">${f2(x && x.baseDE)}</b>对基准</div></div></div></div>`;
  });
  if (scope === 'private') tiles.push(`<div class="add-tile" onclick="openCreate()"><div style="text-align:center"><div style="font-size:26px;line-height:1;margin-bottom:6px">+</div>为该客户新建色板</div></div>`);
  $('grid').innerHTML = tiles.join('') || '<div class="empty">没有符合条件的色板</div>';
}

/* drawer */
function openDrawer(id) {
  curSw = [...publicSwatches, ...privateSwatches].find(s => s.id === id);
  Sim.target = curSw.lab; renderDrawer();
  $('dMask').classList.add('on'); $('drawer').classList.add('on');
}
function closeDrawer() { $('dMask').classList.remove('on'); $('drawer').classList.remove('on'); curSw = null; renderGrid(); renderCtx(); }
function setDE(m) { deMode = m; $('de00').classList.toggle('on', m === '00'); $('de76').classList.toggle('on', m === '76'); renderDrawer(); renderGrid(); }
function setView(v, el) { view = v; el.parentNode.querySelectorAll('button').forEach(b => b.classList.toggle('on', b === el)); renderTable(); }

function renderDrawer() {
  const s = curSw, x = stats(s), c = customers.find(k => k.id === s.customer);
  $('dChip').style.background = chipColor(s);
  $('dTitle').innerHTML = `${s.code} <span class="tag tag-mute">${s.size} ${s.unit}</span> ${s.scope === 'public' ? '<span class="tag tag-gold">公库</span>' : '<span class="tag tag-ok" style="background:#eef3fb;color:#2b4a74">私库</span>'}`;
  $('dSub').textContent = `${s.name}${c ? ' · ' + c.name : ''}`;
  const v = verdict(s, x);
  $('kpis').innerHTML = `
    <div class="kpi"><span>平均 Lab</span><b class="num" style="font-size:16px;line-height:1.7">${x ? x.avg.map(n => n.toFixed(2)).join(' / ') : '—'}</b><small>${x ? x.n + ' 组参与平均' : '尚未测量'}</small></div>
    <div class="kpi hl"><span>组内平均 ΔE${deMode}</span><b class="num">${f2(x && x.meanDE)}</b><small>${x && x.meanDE != null ? (x.meanDE > 0.8 ? '离散偏大，建议加测' : '测量一致性良好') : '至少 2 组'}</small></div>
    <div class="kpi"><span>组内最大 ΔE</span><b class="num">${f2(x && x.maxDE)}</b><small>单组偏离均值的最大值</small></div>
    <div class="kpi" style="${v === 'warn' ? 'border-color:#f0c48a;background:#fffaf2' : ''}"><span>对基准 ΔE${deMode}</span><b class="num" style="${v === 'warn' ? 'color:var(--warn)' : v === 'ok' && x && x.baseDE != null ? 'color:var(--ok)' : ''}">${f2(x && x.baseDE)}</b><small>${s.base ? (x ? (v === 'ok' ? '符合' : '超出') + ' 阈值 ' + s.tol : '待测量') : '无基准'}</small></div>`;
  const baseLab = baseOf(s);
  $('compare').innerHTML = baseLab && x ? `<div class="cmp-chip" style="background:${ColorMath.hex(ColorMath.labToRgb(baseLab))}"><em>基准 ${s.base}</em></div><div class="cmp-mid">ΔE${deMode}<b class="num">${f2(x.baseDE)}</b></div><div class="cmp-chip" style="background:${ColorMath.hex(ColorMath.labToRgb(x.avg))}"><em>本色板均值</em></div>` : '';
  renderTable(); renderDevice(); renderProps();
  const ln = s.late.length;
  $('lateBox').innerHTML = ln ? `<div class="late"><span class="tag tag-warn">待确认</span><div style="flex:1">${ln} 条超时后到达的读数 <span class="num" style="color:var(--t2)">L ${s.late[0].lab[0].toFixed(2)} a ${s.late[0].lab[1].toFixed(2)} b ${s.late[0].lab[2].toFixed(2)}</span>，未计入平均</div><button class="btn btn-o btn-s" onclick="acceptLate()">计入本色板</button><button class="btn btn-o btn-s" onclick="curSw.late=[];renderDrawer()">丢弃</button></div>` : '';
}
function renderTable() {
  const s = curSw, x = stats(s);
  const heads = { lab: ['组', '时间', 'L*', 'a*', 'b*', 'ΔE→均值', '操作'], cmyk: ['组', '时间', 'C', 'M', 'Y', 'K', 'R', 'G', 'B', '操作'], all: ['组', 'Lab', 'Luv', 'LCh', 'Yxy', '操作'] };
  $('mHead').innerHTML = '<tr>' + heads[view].map(h => `<th>${h}</th>`).join('') + '</tr>';
  if (!s.measurements.length) { $('mBody').innerHTML = `<tr><td colspan="${heads[view].length}" style="text-align:center;color:var(--t3);padding:28px">连接色差仪后点击“测量”，每组读数自动加入</td></tr>`; return; }
  const t = d => `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
  const op = m => `<button class="lnk" onclick="toggleInc(${m.id})">${m.included ? '剔除' : '恢复'}</button>`;
  const j = a => a.map(n => n.toFixed(2)).join(' / ');
  $('mBody').innerHTML = s.measurements.slice().reverse().map(m => {
    const cls = (m.included ? '' : 'excl') + (m.fresh ? ' new' : '');
    const first = `<td><span class="mini" style="background:${ColorMath.hex(m.rgb)}"></span>#${m.seq}${m.included ? '' : ' <span class="tag tag-mute">已剔除</span>'}</td>`;
    if (view === 'lab') return `<tr class="${cls}">${first}<td>${t(m.at)}</td><td>${m.lab[0].toFixed(2)}</td><td>${m.lab[1].toFixed(2)}</td><td>${m.lab[2].toFixed(2)}</td><td>${x && m.included ? DE(m.lab, x.avg).toFixed(2) : '—'}</td><td>${op(m)}</td></tr>`;
    if (view === 'cmyk') return `<tr class="${cls}">${first}<td>${t(m.at)}</td>${m.cmyk.map(n => `<td>${n}</td>`).join('')}${m.rgb.map(n => `<td>${n}</td>`).join('')}<td>${op(m)}</td></tr>`;
    return `<tr class="${cls}">${first}<td>${j(m.lab)}</td><td>${j(m.luv)}</td><td>${j(m.lch)}</td><td>${m.yxy[0].toFixed(2)} / ${m.yxy[1].toFixed(4)} / ${m.yxy[2].toFixed(4)}</td><td>${op(m)}</td></tr>`;
  }).join('') + (x ? `<tr style="background:#fafbfe;font-weight:600">${view === 'lab' ? `<td>平均</td><td></td><td>${x.avg[0].toFixed(2)}</td><td>${x.avg[1].toFixed(2)}</td><td>${x.avg[2].toFixed(2)}</td><td>${f2(x.meanDE)}</td><td></td>` : view === 'cmyk' ? `<td>平均 <span class="tag tag-mute">设备换算值</span></td><td></td>${x.cmyk.map(n => `<td>${n}</td>`).join('')}${x.rgb.map(n => `<td>${n}</td>`).join('')}<td></td>` : `<td>平均</td><td>${j(x.avg)}</td><td colspan="4"></td>`}</tr>` : '');
  s.measurements.forEach(m => (m.fresh = false));
}
function renderProps() {
  const s = curSw, c = customers.find(k => k.id === s.customer);
  $('props').innerHTML = `<span>色号</span><b>${s.code}</b><span>尺寸</span><b>${s.size} ${s.unit}</b><span>名称</span><b>${s.name}</b>
    ${c ? `<span>客户</span><b>${c.name}</b>` : ''}<span>对比基准</span><b>${s.base ? '公库 ' + s.base : '—'}</b><span>允许色差</span><b>ΔE ≤ ${s.tol}</b>
    <span>创建人</span><b>${ME.name}</b>`
    + (s.scope === 'private' ? `<span></span><b><button class="lnk" onclick="toast('已提交纳入公库申请，等待色彩管理员审核')">申请纳入公库</button></b>` : '');
}
function toggleInc(id) { const m = curSw.measurements.find(k => k.id === id); m.included = !m.included; renderDrawer(); toast(m.included ? '已恢复，统计已重算' : '已剔除，统计已重算（原始读数保留）'); }
function acceptLate() { curSw.late.forEach(r => addReading(r, 'late')); curSw.late = []; renderDrawer(); }

/* device panel */
function renderDevice() {
  const st = Device.state;
  $('steps').querySelectorAll('.step').forEach((el, i) => { el.className = 'step' + (st > i ? ' done' : st === i && st > 0 ? ' cur' : ''); });
  const env = window.isSecureContext && 'bluetooth' in navigator;
  $('envAlert').innerHTML = devMode === 'ble' && !env ? '<div class="alert alert-warn">当前浏览器不支持 Web Bluetooth。请用安卓 Chrome 通过 HTTPS 打开；仍可查看数据或使用模拟设备。</div>' : st === 2 && Device.initWarn ? '<div class="alert alert-warn">通知已开，但设备信息未确认，可尝试测量。</div>' : '';
  $('devinfo').innerHTML = st ? `<span>设备</span><b>${Device.name || '—'}</b><span>SN</span><b class="num">${Device.info ? Device.info.sn : '—'}</b><span>固件</span><b>${Device.info ? 'v' + Device.info.fw : '—'}</b><span>电压</span><b>${Device.voltage ? Device.voltage + ' V' : '—'}</b><span>通道</span><b>${Device.profile ? '配置 ' + Device.profile : '—'}</b>` : '';
  $('btnConn').textContent = st ? '断开' : '连接色差仪';
  $('btnMeasure').disabled = st < 2 || measuring;
  document.querySelectorAll('input[name=mode]').forEach(i => (i.disabled = st > 0));
  $('topDot').className = 'dot' + (st >= 3 ? ' ok' : st ? ' mid' : '');
  $('topDevTxt').textContent = st >= 3 ? `${Device.name} · ${Device.voltage} V` : st ? '连接中…' : '色差仪未连接';
}
let measuring = false;
async function toggleConn() {
  if (Device.state) { Device.reset('已断开'); return; }
  if (devMode === 'ble' && !(window.isSecureContext && 'bluetooth' in navigator)) { renderDevice(); toast('当前浏览器不支持 Web Bluetooth'); return; }
  $('btnConn').disabled = true;
  try { await Device.connect(); toast('色差仪已就绪'); } catch (e) { Device.reset(); toast('连接失败：' + e.message); }
  $('btnConn').disabled = false; renderDevice();
}
async function measureSeries() {
  if (!curSw) return;
  const target = curSw, n = Math.max(1, Math.min(10, +$('rep').value || 1));
  measuring = true; $('btnMeasure').classList.add('busy'); renderDevice();
  for (let i = 0; i < n; i++) {
    $('mTxt').textContent = n > 1 ? `测量中 ${i + 1}/${n}` : '测量中…';
    try { const r = await Device.measure(); addReading(r, 'matched', target); }
    catch (e) { toast(e.message); break; }
    if (i < n - 1) await wait(500);
  }
  measuring = false; $('btnMeasure').classList.remove('busy'); $('mTxt').textContent = '测量'; renderDevice();
}
function addReading(r, status, sw = curSw) {
  const seqNo = sw.measurements.length + 1;
  sw.measurements.push({ ...r, id: sw.id * 100 + seqNo + Math.random(), seq: seqNo, at: new Date(), sn: Device.info ? Device.info.sn : '', status, included: true, fresh: true, sessionId: Device.sessionId });
  if (curSw === sw) renderDrawer();
}
Device.on('state', renderDevice);
Device.on('initWarn', () => (Device.initWarn = true));
Device.on('log', m => { const el = $('log'); const t = new Date().toTimeString().slice(0, 8); el.textContent = (t + ' ' + m + '\n' + el.textContent).slice(0, 4000); });
Device.on('late', r => { const sw = curSw; if (sw) { sw.late.push(r); renderDrawer(); toast('收到一条超时后到达的读数，已放入待确认'); } });

/* create dialog */
let cScope = 'private';
function setCScope(s) { cScope = s; $('cPriv').classList.toggle('on', s === 'private'); $('cPub').classList.toggle('on', s === 'public'); $('cCustRow').style.display = s === 'private' ? '' : 'none'; }
function openCreate() {
  setCScope(scope);
  $('cCust').innerHTML = customers.map(c => `<option value="${c.id}" ${c.id === curCust ? 'selected' : ''}>${c.name}</option>`).join('');
  $('cBase').innerHTML = '<option value="">不设置</option>' + publicSwatches.map(p => `<option>${p.code}</option>`).join('');
  $('quickSize').innerHTML = [10, 12, 14, 16, 18, 20, 22, 24, 26, 28, 30].map(n => `<button type="button" onclick="$('cSize').value=${n}">${n}″</button>`).join('');
  ['cCode', 'cSize', 'cName'].forEach(k => ($(k).value = '')); $('cErr').textContent = '';
  $('cMask').classList.add('on'); $('dlg').classList.add('on'); setTimeout(() => $('cCode').focus(), 50);
}
function closeCreate() { $('cMask').classList.remove('on'); $('dlg').classList.remove('on'); }
$('cCode').addEventListener('input', () => { const m = publicSwatches.find(p => p.code.toLowerCase() === $('cCode').value.trim().toLowerCase()); if (m) $('cBase').value = m.code; });
function submitCreate(thenMeasure) {
  const code = $('cCode').value.trim(), size = parseFloat($('cSize').value), unit = $('cUnit').value, cust = +$('cCust').value;
  if (!code) return ($('cErr').textContent = '请填写色号');
  if (!(size > 0)) return ($('cErr').textContent = '请填写尺寸');
  const pool = cScope === 'public' ? publicSwatches : privateSwatches;
  if (pool.some(s => s.code.toLowerCase() === code.toLowerCase() && s.size === size && s.unit === unit && (cScope === 'public' || s.customer === cust)))
    return ($('cErr').textContent = `该${cScope === 'public' ? '公库' : '客户'}下已存在 ${code} · ${size} ${unit}`);
  const base = $('cBase').value || null, bs = publicSwatches.find(p => p.code === base);
  const sw = mkSwatch({ id: seq++, scope: cScope, customer: cScope === 'private' ? cust : null, code, name: $('cName').value.trim() || code, size, unit, base, lab: bs ? bs.lab.map((v, i) => v + [1.2, 0.8, 1.6][i]) : [45, 6, 14], n: 0 });
  sw.tol = parseFloat($('cTol').value) || 1.5; pool.push(sw);
  closeCreate(); if (cScope === 'private') curCust = cust; setScope(cScope);
  toast('色板已创建'); if (thenMeasure) openDrawer(sw.id);
}
document.addEventListener('keydown', e => { if (e.key === 'Escape') { if ($('dlg').classList.contains('on')) closeCreate(); else if (curSw) closeDrawer(); } });

let tt; function toast(m) { const el = $('toast'); el.textContent = m; el.classList.add('on'); clearTimeout(tt); tt = setTimeout(() => el.classList.remove('on'), 2200); }

/* 自检：固定命令 CRC（技术说明 5.4） */
(() => { const ok = Object.values(Proto.CMD).concat('ABA00479E3', 'AB202E000200904F', 'AB200E0002009B8F').every(h => Proto.validCRC(Proto.hexToBytes(h))); console.info('LSColor 固定帧 CRC 自检：', ok ? '7/7 通过' : '失败'); })();
setScope('private');
