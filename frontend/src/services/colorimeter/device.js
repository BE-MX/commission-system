// LSColor device session: serial command queue (single pending, 8 s timeout, no auto
// resend), Web Bluetooth transport and an in-page simulator sharing the same framing path.
import {
  COMMANDS, PREFIX, PROFILES, SERVICES, FrameStream,
  buildInfoFrame, buildMeasureFrame, buildVoltageFrame,
  decodeInfo, decodeMeasurement, decodeVoltage, hexToBytes, toHex,
} from './protocol.js'
import { labToRgb } from './deltaE.js'

export const STATE = Object.freeze({ IDLE: 0, GATT: 1, NOTIFY: 2, READY: 3 })
const RESULT_TIMEOUT_MS = 8000
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

export function bluetoothSupport() {
  const g = globalThis
  if (!g.isSecureContext) return { ok: false, reason: '需要 HTTPS 或 localhost 才能使用蓝牙' }
  if (!g.navigator?.bluetooth) return { ok: false, reason: '当前浏览器不支持 Web Bluetooth，请用安卓 Chrome 打开' }
  return { ok: true, reason: '' }
}

function newId() {
  return globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`
}

class BleTransport {
  constructor(session) { this.session = session; this.ble = null }

  async open() {
    const device = await navigator.bluetooth.requestDevice({
      filters: [{ namePrefix: 'LS' }], optionalServices: SERVICES,
    })
    this.onGone = () => this.session.disconnect('设备已断开')
    device.addEventListener('gattserverdisconnected', this.onGone)
    const server = await device.gatt.connect()
    this.session.deviceName = device.name || 'LS'
    this.session.setState(STATE.GATT)
    this.session.log(`GATT 已连接 ${this.session.deviceName}`)
    for (const profile of PROFILES) {
      try {
        const ns = await server.getPrimaryService(profile.notifySvc)
        const nc = await ns.getCharacteristic(profile.notifyChr)
        const ws = profile.writeSvc === profile.notifySvc ? ns : await server.getPrimaryService(profile.writeSvc)
        const wc = await ws.getCharacteristic(profile.writeChr)
        if (!nc.properties.notify || !(wc.properties.write || wc.properties.writeWithoutResponse)) continue
        const onValue = (event) => {
          const dv = event.target.value
          this.session.stream.push(new Uint8Array(dv.buffer.slice(dv.byteOffset, dv.byteOffset + dv.byteLength)))
        }
        nc.addEventListener('characteristicvaluechanged', onValue)
        await nc.startNotifications()
        this.ble = { device, server, nc, wc, onValue }
        this.session.profile = profile.name
        this.session.setState(STATE.NOTIFY)
        this.session.log(`通知已开启，通道配置 ${profile.name}`)
        return
      } catch (err) {
        this.session.log(`通道 ${profile.name} 不可用：${err?.message || err}`)
      }
    }
    server.disconnect()
    throw new Error('未找到可用的 GATT 通道（配置 A/B/C 均不满足）')
  }

  write(bytes) {
    const wc = this.ble?.wc
    if (!wc) return Promise.reject(new Error('设备未连接'))
    return wc.properties.write ? wc.writeValueWithResponse(bytes) : wc.writeValueWithoutResponse(bytes)
  }

  close() {
    if (!this.ble) return
    const { device, server, nc, onValue } = this.ble
    this.ble = null
    try {
      nc.removeEventListener('characteristicvaluechanged', onValue)
      device.removeEventListener('gattserverdisconnected', this.onGone)
      if (server.connected) server.disconnect()
    } catch (err) {
      console.warn('[colorimeter] close failed', err)
    }
  }
}

/** Deterministic-enough simulator: emits CRC-valid frames in 20-byte chunks. */
class SimTransport {
  constructor(session) { this.session = session; this.open_ = false; this.target = [50, 0, 0] }

  async open() {
    this.open_ = true
    this.session.deviceName = 'LS171-SIM'
    await wait(300)
    this.session.setState(STATE.GATT)
    this.session.log('GATT 已连接 LS171-SIM（模拟设备）')
    await wait(200)
    this.session.profile = 'A'
    this.session.setState(STATE.NOTIFY)
    this.session.log('通知已开启，通道配置 A')
  }

  async write(bytes) {
    if (!this.open_) throw new Error('设备未连接')
    const hex = toHex(bytes).toUpperCase()
    let frame
    if (hex === COMMANDS.info) frame = buildInfoFrame({ sn: 2410803317, material: 1171, fw: 1.52 })
    else if (hex === COMMANDS.voltage) frame = buildVoltageFrame(4.0)
    else if (hex === COMMANDS.measure) {
      await wait(600 + Math.random() * 300)
      const jitter = (s) => (Math.random() * 2 - 1) * s
      const [L, a, b] = this.target
      const lab = [L + jitter(0.45), a + jitter(0.3), b + jitter(0.35)]
      const rgb = labToRgb(lab)
      const k = 1 - Math.max(...rgb) / 255
      const cmyk = k >= 1 ? [0, 0, 0, 100]
        : rgb.map((c) => Math.round(((1 - c / 255 - k) / (1 - k)) * 100)).concat(Math.round(k * 100))
      frame = buildMeasureFrame(lab, rgb, cmyk)
    } else return
    await wait(60)
    for (let i = 0; i < frame.length; i += 20) {
      if (!this.open_) return
      this.session.stream.push(frame.slice(i, i + 20))
      await wait(10)
    }
  }

  close() { this.open_ = false }
}

export class ColorimeterSession {
  constructor({ onState = () => {}, onLog = () => {}, onLate = () => {} } = {}) {
    this.onState = onState
    this.onLog = onLog
    this.onLate = onLate
    this.state = STATE.IDLE
    this.reset()
  }

  reset() {
    this.transport = null
    this.pending = null
    this.queue = Promise.resolve()
    this.deviceName = ''
    this.profile = ''
    this.info = null
    this.voltage = null
    this.sessionId = ''
    this.initWarning = ''
    this.stream?.reset()
  }

  setState(state) { this.state = state; this.onState(state, this) }
  log(message) { this.onLog(message) }
  get simulated() { return this.transport instanceof SimTransport }
  setSimTarget(lab) { if (this.transport instanceof SimTransport && lab) this.transport.target = lab }

  async connect({ simulate = false } = {}) {
    if (this.state !== STATE.IDLE) return
    if (!simulate) {
      const support = bluetoothSupport()
      if (!support.ok) throw new Error(support.reason)
    }
    this.sessionId = newId()
    this.stream = new FrameStream({ onFrame: (f) => this.handleFrame(f), onLog: (m) => this.log(m) })
    this.transport = simulate ? new SimTransport(this) : new BleTransport(this)
    try {
      await this.transport.open()
    } catch (err) {
      this.disconnect()
      throw err
    }
    try {
      this.info = decodeInfo(await this.send(COMMANDS.info, PREFIX.info))
      this.voltage = decodeVoltage(await this.send(COMMANDS.voltage, PREFIX.voltage))
      this.log(`设备 SN ${this.info.sn}，版本 v${this.info.fw}，电压 ${this.voltage.toFixed(1)} V`)
      this.setState(STATE.READY)
    } catch (err) {
      // Notifications work; allow measuring but surface that init was not confirmed.
      this.initWarning = `初始化未确认：${err.message}`
      this.log(this.initWarning)
      this.setState(STATE.NOTIFY)
    }
  }

  disconnect(reason) {
    if (this.pending) {
      this.pending.reject(new Error(reason || '连接已断开'))
      this.pending = null
    }
    this.transport?.close()
    const wasConnected = this.state !== STATE.IDLE
    this.reset()
    if (wasConnected) {
      if (reason) this.log(reason)
      this.setState(STATE.IDLE)
    }
  }

  handleFrame(frame) {
    const hex = toHex(frame)
    this.log(`RX ${hex.toUpperCase().slice(0, 48)}${hex.length > 48 ? '…' : ''}`)
    if (hex === PREFIX.event) {
      // Doc §6.4: A0 is a device event; read 40 for diagnostics only, never persist.
      this.log('A0 事件 → 读取 40 类诊断数据（不入库）')
      this.send(COMMANDS.eventRead, PREFIX.eventData).catch(() => {})
      return
    }
    if (this.pending && hex.startsWith(this.pending.prefix)) {
      const pending = this.pending
      this.pending = null
      pending.resolve(frame)
      return
    }
    if (hex.startsWith(PREFIX.measure)) {
      this.onLate({ ...decodeMeasurement(frame), receivedAt: new Date() })
    }
  }

  send(commandHex, prefix, timeoutMs = RESULT_TIMEOUT_MS) {
    const run = () => new Promise((resolve, reject) => {
      if (!this.transport) { reject(new Error('设备未连接')); return }
      const timer = setTimeout(() => {
        if (this.pending?.timer === timer) this.pending = null
        reject(new Error('结果超时（8 秒），未自动重发'))
      }, timeoutMs)
      this.pending = {
        prefix,
        timer,
        resolve: (frame) => { clearTimeout(timer); resolve(frame) },
        reject: (err) => { clearTimeout(timer); reject(err) },
      }
      this.log(`TX ${commandHex}`)
      this.transport.write(hexToBytes(commandHex)).catch((err) => {
        if (this.pending?.timer === timer) this.pending = null
        clearTimeout(timer)
        reject(err)
      })
    })
    const task = this.queue.then(run, run)
    this.queue = task.catch(() => {})
    return task
  }

  async measure() {
    if (this.state < STATE.NOTIFY) throw new Error('色差仪未就绪')
    const requestedAt = new Date()
    const frame = await this.send(COMMANDS.measure, PREFIX.measure)
    return {
      ...decodeMeasurement(frame),
      requestedAt,
      receivedAt: new Date(),
      deviceName: this.deviceName,
      deviceSn: this.info?.sn || null,
      deviceFw: this.info?.fw || null,
      sessionId: this.sessionId,
      source: this.simulated ? 'simulation' : 'device',
    }
  }
}
