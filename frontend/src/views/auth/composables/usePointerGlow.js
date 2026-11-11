import { onMounted, onUnmounted } from 'vue'

// Moves soft light spots inside `host` toward the pointer, lighting up as it comes near.
// Positions ease at a pace independent of frame rate, and the loop stops once everything has settled.
export function usePointerGlow(hostRef, glowRefs) {
  let dispose = () => {}

  onMounted(() => {
    const host = hostRef.value
    const glows = glowRefs.map(item => item.value).filter(Boolean)
    if (!host || !glows.length) return
    const fine = window.matchMedia('(hover: hover) and (pointer: fine)')
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)')
    const target = { x: 0, y: 0, power: 0 }
    let frame = 0, previous = 0, x = 0, y = 0, power = 0

    function step(time) {
      const delta = Math.min(Math.max(time - previous, 0), 100)
      previous = time
      // A light that was off appears under the pointer instead of sliding in from its last position.
      const ease = power < 0.02 ? 1 : 1 - Math.exp(-delta / 90)
      x += (target.x - x) * ease
      y += (target.y - y) * ease
      power += (target.power - power) * (1 - Math.exp(-delta / 200))
      for (const glow of glows) {
        glow.style.transform = `translate3d(${x.toFixed(1)}px, ${y.toFixed(1)}px, 0) translate(-50%, -50%)`
        glow.style.opacity = power.toFixed(3)
      }
      const settled = Math.abs(target.x - x) + Math.abs(target.y - y) < 0.3 && Math.abs(target.power - power) < 0.004
      frame = settled ? 0 : requestAnimationFrame(step)
    }

    function wake() {
      if (frame) return
      previous = performance.now()
      frame = requestAnimationFrame(step)
    }

    function track(event) {
      if (event.pointerType === 'touch' || !fine.matches || reduced.matches) return
      const rect = host.getBoundingClientRect()
      target.x = event.clientX - rect.left
      target.y = event.clientY - rect.top
      const gap = Math.hypot(
        Math.max(rect.left - event.clientX, 0, event.clientX - rect.right),
        Math.max(rect.top - event.clientY, 0, event.clientY - rect.bottom),
      )
      const next = Math.max(0, 1 - gap / 260)
      // Far from the card with the light already out: nothing to animate, so no frame is requested.
      if (next === 0 && target.power === 0 && power < 0.01) return
      target.power = next
      wake()
    }

    function release() {
      target.power = 0
      wake()
    }

    window.addEventListener('pointermove', track, { passive: true })
    document.documentElement.addEventListener('pointerleave', release)
    reduced.addEventListener('change', release)
    dispose = () => {
      cancelAnimationFrame(frame)
      window.removeEventListener('pointermove', track)
      document.documentElement.removeEventListener('pointerleave', release)
      reduced.removeEventListener('change', release)
    }
  })
  onUnmounted(() => dispose())
}
