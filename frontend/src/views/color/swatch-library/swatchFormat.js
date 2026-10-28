// Pure display/payload helpers for the swatch library (unit-tested via node --test).

export function normalizeCode(code) {
  return String(code || '').replace(/\s+/g, '').toUpperCase()
}

export function fmt(value, digits = 2) {
  return value == null || Number.isNaN(value) ? '—' : Number(value).toFixed(digits)
}

export function sizeLabel(value, unit) {
  return unit === 'inch' ? `${value}″` : `${value} ${unit}`
}

/** Map a device/simulator reading to the backend measurement payload. */
export function toMeasurementPayload(reading, { receiptStatus = 'matched' } = {}) {
  const id = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`
  return {
    client_request_id: id,
    source: reading.source || 'device',
    receipt_status: receiptStatus,
    lab: reading.lab,
    luv: reading.luv,
    lch: reading.lch,
    yxy: reading.yxy,
    cmyk: reading.cmyk,
    rgb: reading.rgb,
    raw_hex: reading.raw || null,
    device_name: reading.deviceName || null,
    device_sn: reading.deviceSn || null,
    device_fw: reading.deviceFw || null,
    session_id: reading.sessionId || null,
    // Offsets included so the server converts to Beijing time deterministically.
    requested_at: reading.requestedAt ? reading.requestedAt.toISOString() : null,
    received_at: reading.receivedAt ? reading.receivedAt.toISOString() : null,
  }
}

/** Verdict for a client-side preview; the server verdict is authoritative after save. */
export function verdict(stats, tolerance) {
  if (!stats?.count) return 'none'
  if (stats.base_de == null) return 'ok'
  return stats.base_de <= tolerance ? 'ok' : 'warn'
}

export function formatBeijing(value) {
  if (!value) return '—'
  // Server returns naive Beijing time; render it as-is rather than through the client zone.
  const m = String(value).match(/^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/)
  return m ? `${Number(m[2])}/${Number(m[3])} ${m[4]}:${m[5]}` : String(value)
}
