// LSColor colorimeter BLE protocol (D:\色差仪\LSColor蓝牙连接与数据读写控制技术说明.md v1.0).
// Pure functions only: safe for node --test and the browser.

export const PROFILES = [
  { name: 'A', notifySvc: 0xffe0, notifyChr: 0xffe4, writeSvc: 0xffe5, writeChr: 0xffe9 },
  { name: 'B', notifySvc: 0xfff0, notifyChr: 0xfff1, writeSvc: 0xfff0, writeChr: 0xfff1 },
  { name: 'C', notifySvc: 0x1001, notifyChr: 0x1002, writeSvc: 0x1001, writeChr: 0x1002 },
]

export const SERVICES = [0xffe0, 0xffe5, 0xfff0, 0x1001]

export const COMMANDS = Object.freeze({
  info: 'AB2005001200946B',
  measure: 'AB440000000036001864',
  voltage: 'AB200B0002009B43',
  eventRead: 'AB400000000014004504',
})

export const PREFIX = Object.freeze({
  info: 'ab2005001200',
  measure: 'ab4400000000',
  voltage: 'ab200b000200',
  event: 'aba00479e3',
  eventData: 'ab40000000001400',
})

export function crc16(data) {
  let crc = 0xffff
  for (const value of data) {
    crc ^= value
    for (let bit = 0; bit < 8; bit++) crc = crc & 1 ? (crc >>> 1) ^ 0xa001 : crc >>> 1
  }
  return crc
}

export function validCRC(frame) {
  if (frame.length < 3) return false
  const crc = crc16(frame.subarray(0, frame.length - 2))
  return frame[frame.length - 2] === (crc & 0xff) && frame[frame.length - 1] === crc >> 8
}

export function hexToBytes(hex) {
  const clean = hex.replace(/\s+/g, '')
  if (clean.length % 2) throw new Error('HEX 长度必须为偶数')
  return Uint8Array.from(clean.match(/../g) || [], (pair) => parseInt(pair, 16))
}

export function toHex(bytes) {
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')
}

function view(frame) {
  return new DataView(frame.buffer, frame.byteOffset, frame.byteLength)
}

function requireFrame(frame, prefix, minLength, label) {
  if (frame.length < minLength || toHex(frame.slice(0, prefix.length / 2)) !== prefix || !validCRC(frame)) {
    throw new Error(`${label}无效（前缀、长度或 CRC 不符）`)
  }
}

export function decodeMeasurement(frame) {
  requireFrame(frame, PREFIX.measure, 41, '测量帧')
  const v = view(frame)
  const i16 = (offset, divisor = 100) => v.getInt16(offset, true) / divisor
  // Keep the vendor App's hue rule: compare the whole 6-byte LCh wire hex with 32767.
  const unsignedHue = parseInt(toHex(frame.slice(20, 26)), 16) > 32767
  const hue = (unsignedHue ? v.getUint16(24, true) : v.getInt16(24, true)) / 100
  return {
    lab: [i16(8), i16(10), i16(12)],
    luv: [i16(14), i16(16), i16(18)],
    lch: [i16(20), i16(22), hue],
    yxy: [i16(26), i16(28, 10000), i16(30, 10000)],
    cmyk: Array.from(frame.slice(32, 36)),
    rgb: Array.from(frame.slice(36, 39)),
    raw: toHex(frame).toUpperCase(),
  }
}

export function decodeInfo(frame) {
  requireFrame(frame, PREFIX.info, 26, '设备信息帧')
  const v = view(frame)
  return {
    sn: String(v.getUint32(12, true)),
    material: v.getUint32(16, true),
    fw: String(v.getUint16(22, true)).padStart(3, '0').replace(/(\d{2})$/, '.$1'),
  }
}

export function decodeVoltage(frame) {
  requireFrame(frame, PREFIX.voltage, 10, '电压帧')
  return view(frame).getUint16(6, true) / 10
}

function sealed(frame) {
  const crc = crc16(frame.subarray(0, frame.length - 2))
  frame[frame.length - 2] = crc & 0xff
  frame[frame.length - 1] = crc >> 8
  return frame
}

/** Simulator only: build a CRC-valid 64-byte 44 frame for a target Lab. */
export function buildMeasureFrame(lab, rgb = [0, 0, 0], cmyk = [0, 0, 0, 0]) {
  const frame = new Uint8Array(64)
  frame.set(hexToBytes('AB44000000003600'))
  const v = new DataView(frame.buffer)
  const s = (offset, value, divisor = 100) => v.setInt16(offset, Math.round(value * divisor), true)
  const [L, a, b] = lab
  const chroma = Math.hypot(a, b)
  const hue = ((Math.atan2(b, a) * 180) / Math.PI + 360) % 360
  s(8, L); s(10, a); s(12, b)
  s(14, L); s(16, a * 1.18); s(18, b * 1.05)
  s(20, L); s(22, chroma); v.setUint16(24, Math.round(hue * 100), true)
  s(26, ((L + 16) / 116) ** 3 * 100); s(28, 0.3127 + a / 2200, 10000); s(30, 0.329 + b / 2600, 10000)
  frame.set(cmyk, 32)
  frame.set(rgb, 36)
  return sealed(frame)
}

export function buildInfoFrame({ sn = 0, material = 0, fw = 0 } = {}) {
  const frame = new Uint8Array(26)
  frame.set(hexToBytes('AB2005001200'))
  const v = new DataView(frame.buffer)
  v.setUint32(12, sn, true)
  v.setUint32(16, material, true)
  v.setUint16(22, Math.round(fw * 100), true)
  return sealed(frame)
}

export function buildVoltageFrame(volts) {
  const frame = new Uint8Array(10)
  frame.set(hexToBytes('AB200B000200'))
  new DataView(frame.buffer).setUint16(6, Math.round(volts * 10), true)
  return sealed(frame)
}

const MAX_BUFFER = 2048
const MAX_FRAME = 1024
const MIN_LENGTH = { 0x44: 41, 0x40: 10, 0xa0: 5 }

/**
 * Bounded reassembly of notification fragments. 20-type frames use the declared
 * payload length; 40/44/A0 search for the first CRC-valid boundary because the
 * vendor length rule is not confirmed (doc §10.2).
 */
export class FrameStream {
  constructor({ onFrame, onLog = () => {}, staleMs = 2000, setTimer = setTimeout, clearTimer = clearTimeout }) {
    this.buf = new Uint8Array(0)
    this.onFrame = onFrame
    this.onLog = onLog
    this.staleMs = staleMs
    this.setTimer = setTimer
    this.clearTimer = clearTimer
    this.timer = null
  }

  push(chunk) {
    const next = new Uint8Array(this.buf.length + chunk.length)
    next.set(this.buf)
    next.set(chunk, this.buf.length)
    this.buf = next
    if (this.buf.length > MAX_BUFFER) {
      this.onLog('接收缓存超过 2048 字节，已丢弃')
      this.reset()
      return
    }
    this.drain()
    this.clearTimer(this.timer)
    this.timer = this.buf.length
      ? this.setTimer(() => {
          if (this.buf.length) this.onLog('不完整帧超时，已清空缓存')
          this.buf = new Uint8Array(0)
        }, this.staleMs)
      : null
  }

  reset() {
    this.clearTimer(this.timer)
    this.timer = null
    this.buf = new Uint8Array(0)
  }

  drain() {
    for (;;) {
      const start = this.buf.indexOf(0xab)
      if (start < 0) { this.buf = new Uint8Array(0); return }
      if (start > 0) this.buf = this.buf.slice(start)
      if (this.buf.length < 2) return
      const type = this.buf[1]
      let end = 0
      if (type === 0x20) {
        if (this.buf.length < 6) return
        const total = 8 + (this.buf[4] | (this.buf[5] << 8))
        if (total > MAX_FRAME) { this.buf = this.buf.slice(1); continue }
        if (this.buf.length < total) return
        if (!validCRC(this.buf.subarray(0, total))) {
          this.onLog('20 类帧 CRC 错误，重新同步')
          this.buf = this.buf.slice(1)
          continue
        }
        end = total
      } else if (type in MIN_LENGTH) {
        const limit = Math.min(this.buf.length, MAX_FRAME)
        for (let len = MIN_LENGTH[type]; len <= limit; len++) {
          if (validCRC(this.buf.subarray(0, len))) { end = len; break }
        }
        if (!end) return
      } else {
        this.buf = this.buf.slice(1)
        continue
      }
      const frame = this.buf.slice(0, end)
      this.buf = this.buf.slice(end)
      this.onFrame(frame)
    }
  }
}
