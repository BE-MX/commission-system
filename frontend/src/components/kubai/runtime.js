// Ark bridge to the Kubai Icons engine: one brand-gold palette and per-instance helpers.
import { go, mountIcon, runtime } from './engine.js'
import { ICONS_BY_NAME } from './icons.js'

// Only used if tokens.css has not loaded; keep in step with --color-primary.
const FALLBACK_ACCENT = '#D4941C'
let sequence = 0

function brandAccent() {
  try {
    const value = getComputedStyle(document.documentElement).getPropertyValue('--color-primary').trim()
    if (/^#[0-9a-f]{6}$/i.test(value)) return value.toUpperCase()
  } catch (error) {
    console.warn('[kubai] reading --color-primary failed', error)
  }
  return FALLBACK_ACCENT
}

// Every icon index resolves to the same accent, so instances never run out of colours.
function ensurePalette() {
  if (runtime.palette) return
  const accent = brandAccent()
  runtime.palette = { name: 'ark-gold', colors: new Proxy([], { get: (target, key) => (key === 'length' ? 0 : accent) }) }
}

export function mountKubaiIcon(name, host) {
  const icon = ICONS_BY_NAME[name]
  if (!icon || !host) return null
  ensurePalette()
  // The engine derives SVG ids from this key; the prefix keeps them apart from other SVGs.
  return mountIcon(icon, `ark${sequence++}`, host)
}

export function setKubaiHover(instance, hovered) {
  if (!instance) return
  instance.hover = hovered ? 1 : 0
  go(instance)
}

export function disposeKubaiIcon(instance) {
  if (instance) cancelAnimationFrame(instance.raf)
}
