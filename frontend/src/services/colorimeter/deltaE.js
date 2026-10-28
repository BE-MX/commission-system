// CIEDE2000 / CIE76 and Lab -> sRGB preview. Server remains the source of truth for stats.

const RAD = Math.PI / 180
const DEG = 180 / Math.PI

export function de76(p, q) {
  return Math.hypot(p[0] - q[0], p[1] - q[1], p[2] - q[2])
}

export function de00([L1, a1, b1], [L2, a2, b2]) {
  const C1 = Math.hypot(a1, b1)
  const C2 = Math.hypot(a2, b2)
  const Cb = (C1 + C2) / 2
  const G = 0.5 * (1 - Math.sqrt(Cb ** 7 / (Cb ** 7 + 25 ** 7)))
  const ap1 = (1 + G) * a1
  const ap2 = (1 + G) * a2
  const Cp1 = Math.hypot(ap1, b1)
  const Cp2 = Math.hypot(ap2, b2)
  const hp = (b, ap) => (b === 0 && ap === 0 ? 0 : (Math.atan2(b, ap) * DEG + 360) % 360)
  const h1 = hp(b1, ap1)
  const h2 = hp(b2, ap2)
  const dL = L2 - L1
  const dC = Cp2 - Cp1
  let dh = 0
  if (Cp1 * Cp2 !== 0) {
    dh = h2 - h1
    if (dh > 180) dh -= 360
    else if (dh < -180) dh += 360
  }
  const dH = 2 * Math.sqrt(Cp1 * Cp2) * Math.sin((dh / 2) * RAD)
  const Lb = (L1 + L2) / 2
  const Cpb = (Cp1 + Cp2) / 2
  let hb = h1 + h2
  if (Cp1 * Cp2 !== 0) {
    if (Math.abs(h1 - h2) <= 180) hb /= 2
    else hb = hb < 360 ? (hb + 360) / 2 : (hb - 360) / 2
  }
  const T = 1 - 0.17 * Math.cos((hb - 30) * RAD) + 0.24 * Math.cos(2 * hb * RAD)
    + 0.32 * Math.cos((3 * hb + 6) * RAD) - 0.2 * Math.cos((4 * hb - 63) * RAD)
  const dTheta = 30 * Math.exp(-(((hb - 275) / 25) ** 2))
  const Rc = 2 * Math.sqrt(Cpb ** 7 / (Cpb ** 7 + 25 ** 7))
  const Sl = 1 + (0.015 * (Lb - 50) ** 2) / Math.sqrt(20 + (Lb - 50) ** 2)
  const Sc = 1 + 0.045 * Cpb
  const Sh = 1 + 0.015 * Cpb * T
  const Rt = -Math.sin(2 * dTheta * RAD) * Rc
  return Math.sqrt((dL / Sl) ** 2 + (dC / Sc) ** 2 + (dH / Sh) ** 2 + Rt * (dC / Sc) * (dH / Sh))
}

export function averageLab(labs) {
  if (!labs.length) return null
  return [0, 1, 2].map((i) => labs.reduce((sum, lab) => sum + lab[i], 0) / labs.length)
}

export function labToRgb([L, a, b]) {
  let y = (L + 16) / 116
  let x = a / 500 + y
  let z = y - b / 200
  const f = (t) => (t ** 3 > 0.008856 ? t ** 3 : (t - 16 / 116) / 7.787)
  x = 0.95047 * f(x); y = f(y); z = 1.08883 * f(z)
  const lin = [
    x * 3.2406 + y * -1.5372 + z * -0.4986,
    x * -0.9689 + y * 1.8758 + z * 0.0415,
    x * 0.0557 + y * -0.204 + z * 1.057,
  ]
  const gamma = (c) => (c > 0.0031308 ? 1.055 * c ** (1 / 2.4) - 0.055 : 12.92 * c)
  return lin.map((c) => Math.max(0, Math.min(255, Math.round(gamma(c) * 255))))
}

export function rgbCss(rgb) {
  return `rgb(${rgb[0]}, ${rgb[1]}, ${rgb[2]})`
}
