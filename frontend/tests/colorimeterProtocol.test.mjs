import test from 'node:test'
import assert from 'node:assert/strict'
import {
  COMMANDS, FrameStream, PREFIX, buildInfoFrame, buildMeasureFrame, buildVoltageFrame,
  crc16, decodeInfo, decodeMeasurement, decodeVoltage, hexToBytes, toHex, validCRC,
} from '../src/services/colorimeter/protocol.js'
import { averageLab, de00, de76, labToRgb } from '../src/services/colorimeter/deltaE.js'
import { ColorimeterSession, STATE } from '../src/services/colorimeter/device.js'

const withCRC = (bytes) => {
  const crc = crc16(bytes)
  return Uint8Array.from([...bytes, crc & 0xff, crc >> 8])
}

// Independent fixture (mirrors D:\色差仪\demo\protocol.test.mjs) — not built by buildMeasureFrame.
function fixture() {
  const b = new Uint8Array(62)
  b.set(hexToBytes('ab44000000003600'))
  const d = new DataView(b.buffer)
  d.setInt16(8, 6321, true); d.setInt16(10, -1278, true); d.setInt16(12, 2314, true)
  d.setInt16(14, 6300, true); d.setInt16(16, -4321, true); d.setInt16(18, 9876, true)
  d.setInt16(20, 6321, true); d.setInt16(22, 2642, true); d.setUint16(24, 35900, true)
  d.setInt16(26, 3530, true); d.setInt16(28, 3127, true); d.setInt16(30, 3290, true)
  b.set([10, 20, 30, 40, 180, 120, 90], 32)
  return withCRC(b)
}

test('all seven documented fixed packets pass CRC; a damaged one fails', () => {
  for (const s of [...Object.values(COMMANDS), 'ABA00479E3', 'AB202E000200904F', 'AB200E0002009B8F']) {
    assert.ok(validCRC(hexToBytes(s)), s)
  }
  const bad = hexToBytes(COMMANDS.measure)
  bad[4] = 1
  assert.equal(validCRC(bad), false)
})

test('signed little-endian fields, unsigned hue and byte channels decode exactly', () => {
  const r = decodeMeasurement(fixture())
  assert.deepEqual(r.lab, [63.21, -12.78, 23.14])
  assert.deepEqual(r.luv, [63, -43.21, 98.76])
  assert.deepEqual(r.lch, [63.21, 26.42, 359])
  assert.deepEqual(r.yxy, [35.3, 0.3127, 0.329])
  assert.deepEqual(r.cmyk, [10, 20, 30, 40])
  assert.deepEqual(r.rgb, [180, 120, 90])
  assert.ok(r.raw.startsWith('AB4400000000'))
})

test('decoder honours typed-array byteOffset and rejects truncation / corruption', () => {
  const b = fixture()
  const padded = new Uint8Array(b.length + 8)
  padded.set(b, 4)
  assert.deepEqual(decodeMeasurement(padded.subarray(4, -4)).lab, [63.21, -12.78, 23.14])
  assert.throws(() => decodeMeasurement(b.slice(0, 30)))
  const corrupt = b.slice()
  corrupt[10] ^= 1
  assert.throws(() => decodeMeasurement(corrupt))
})

test('every split point and bytewise notifications yield exactly one frame', () => {
  const b = fixture()
  for (let i = 1; i < b.length; i++) {
    const frames = []
    const s = new FrameStream({ onFrame: (f) => frames.push(f), setTimer: () => 0, clearTimer: () => {} })
    s.push(b.slice(0, i))
    assert.equal(frames.length, 0, `split ${i}`)
    s.push(b.slice(i))
    assert.equal(frames.length, 1)
    assert.deepEqual(frames[0], b)
  }
  const frames = []
  const s = new FrameStream({ onFrame: (f) => frames.push(f), setTimer: () => 0, clearTimer: () => {} })
  for (const v of b) s.push(Uint8Array.of(v))
  assert.equal(frames.length, 1)
})

test('coalesced event, battery and measurement frames are separated', () => {
  const battery = withCRC(hexToBytes('ab200b0002002900'))
  const b = fixture()
  const frames = []
  const s = new FrameStream({ onFrame: (f) => frames.push(toHex(f)), setTimer: () => 0, clearTimer: () => {} })
  s.push(Uint8Array.from([0, 9, ...hexToBytes('aba00479e3'), ...battery, ...b]))
  assert.deepEqual(frames, ['aba00479e3', toHex(battery), toHex(b)])
  assert.equal(decodeVoltage(battery), 4.1)
})

test('bad-CRC 20 frame is skipped and the next valid frame is recovered', () => {
  const good = withCRC(hexToBytes('ab200b0002002900'))
  const corrupt = good.slice()
  corrupt[6] ^= 1
  const frames = []
  const logs = []
  const s = new FrameStream({ onFrame: (f) => frames.push(f), onLog: (m) => logs.push(m), setTimer: () => 0, clearTimer: () => {} })
  s.push(Uint8Array.from([...corrupt, ...good]))
  assert.equal(frames.length, 1)
  assert.deepEqual(frames[0], good)
  assert.ok(logs.some((m) => m.includes('CRC')))
})

test('oversized stream is discarded and never emits a measurement', () => {
  const frames = []
  const logs = []
  const s = new FrameStream({ onFrame: (f) => frames.push(f), onLog: (m) => logs.push(m), setTimer: () => 0, clearTimer: () => {} })
  const b = fixture()
  b[b.length - 1] ^= 1
  s.push(b)
  s.push(new Uint8Array(2050))
  assert.equal(frames.length, 0)
  assert.equal(s.buf.length, 0)
  assert.ok(logs.length)
})

test('default timers are not invoked with FrameStream as this (browser Illegal invocation)', () => {
  const realSet = globalThis.setTimeout
  const realClear = globalThis.clearTimeout
  const strict = (real) => function (...args) {
    if (this !== undefined && this !== globalThis) throw new TypeError('Illegal invocation')
    return real(...args)
  }
  globalThis.setTimeout = strict(realSet)
  globalThis.clearTimeout = strict(realClear)
  try {
    const s = new FrameStream({ onFrame: () => {} })
    s.push(fixture().slice(0, 10))
    assert.ok(s.buf.length > 0)
    s.reset()
  } finally {
    globalThis.setTimeout = realSet
    globalThis.clearTimeout = realClear
  }
})

test('info and voltage frames decode SN / material / version / volts', () => {
  assert.deepEqual(decodeInfo(buildInfoFrame({ sn: 12345678, material: 25622170, fw: 1.23 })),
    { sn: '12345678', material: 25622170, fw: '1.23' })
  assert.equal(decodeVoltage(buildVoltageFrame(4.0)), 4)
  assert.throws(() => decodeInfo(buildVoltageFrame(4)))
})

test('simulator frame round-trips Lab within quantisation', () => {
  const r = decodeMeasurement(buildMeasureFrame([20.6, -1.62, 2.41], [40, 35, 33], [0, 5, 8, 84]))
  assert.deepEqual(r.lab, [20.6, -1.62, 2.41])
  assert.deepEqual(r.rgb, [40, 35, 33])
  assert.ok(toHex(hexToBytes(r.raw)).startsWith(PREFIX.measure))
})

test('CIEDE2000 matches Sharma 2005 reference pairs', () => {
  const pairs = [
    [[50, 2.6772, -79.7751], [50, 0, -82.7485], 2.0425],
    [[50, 3.1571, -77.2803], [50, 0, -82.7485], 2.8615],
    [[50, -1.3802, -84.2814], [50, 0, -82.7485], 1.0],
    [[50, 0, 0], [50, -1, 2], 2.3669],
    [[50, 2.5, 0], [73, 25, -18], 27.1492],
    [[2.0776, 0.0795, -1.135], [0.9033, -0.0636, -0.5514], 0.9082],
  ]
  for (const [p, q, expected] of pairs) assert.ok(Math.abs(de00(p, q) - expected) < 1e-4, `${p} → ${de00(p, q)}`)
  assert.equal(de76([0, 0, 0], [3, 4, 0]), 5)
  assert.deepEqual(averageLab([[10, 2, -4], [20, 4, 0]]), [15, 3, -2])
  assert.deepEqual(labToRgb([100, 0, 0]), [255, 255, 255])
})

function fakeSession() {
  const writes = []
  const session = new ColorimeterSession()
  session.stream = new FrameStream({ onFrame: (f) => session.handleFrame(f), setTimer: () => 0, clearTimer: () => {} })
  session.transport = { write: async (bytes) => { writes.push(toHex(bytes)) }, close() {} }
  session.state = STATE.READY
  return { session, writes }
}

test('commands are serial: second command waits for first result', async () => {
  const { session, writes } = fakeSession()
  const first = session.send(COMMANDS.info, PREFIX.info, 1000)
  const second = session.send(COMMANDS.voltage, PREFIX.voltage, 1000)
  await new Promise((r) => setTimeout(r, 5))
  assert.deepEqual(writes, [COMMANDS.info.toLowerCase()])
  session.stream.push(buildInfoFrame({ sn: 1 }))
  await first
  await new Promise((r) => setTimeout(r, 5))
  assert.equal(writes.length, 2)
  session.stream.push(buildVoltageFrame(3.9))
  assert.equal(decodeVoltage(await second), 3.9)
})

test('timeout does not resend; a late 44 frame goes to onLate, not the next request', async () => {
  const { session, writes } = fakeSession()
  const late = []
  session.onLate = (r) => late.push(r)
  await assert.rejects(session.send(COMMANDS.measure, PREFIX.measure, 20), /超时/)
  assert.equal(writes.length, 1)
  session.stream.push(buildMeasureFrame([30, 1, 2]))
  assert.equal(late.length, 1)
  assert.deepEqual(late[0].lab, [30, 1, 2])
})

test('disconnect rejects pending and clears session', async () => {
  const { session } = fakeSession()
  const pending = session.send(COMMANDS.measure, PREFIX.measure, 1000)
  await new Promise((r) => setTimeout(r, 1))
  session.disconnect('测试断开')
  await assert.rejects(pending, /测试断开/)
  assert.equal(session.state, STATE.IDLE)
  assert.equal(session.transport, null)
})

test('simulated session connects, initialises and measures through the framing path', async () => {
  const states = []
  const session = new ColorimeterSession({ onState: (s) => states.push(s) })
  await session.connect({ simulate: true })
  assert.equal(session.state, STATE.READY)
  assert.deepEqual(states, [STATE.GATT, STATE.NOTIFY, STATE.READY])
  assert.equal(session.info.sn, '2410803317')
  session.setSimTarget([20.6, 1.6, 2.4])
  const r = await session.measure()
  assert.equal(r.source, 'simulation')
  assert.ok(Math.abs(r.lab[0] - 20.6) < 0.5)
  assert.equal(r.deviceSn, '2410803317')
  session.disconnect()
})
