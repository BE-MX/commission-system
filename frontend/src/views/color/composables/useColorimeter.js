import { onBeforeUnmount, reactive, shallowRef } from 'vue'
import { ColorimeterSession, STATE, bluetoothSupport } from '@/services/colorimeter/device.js'
import { formatBeijingTime } from '@/utils/datetime'

const LOG_LIMIT = 80

/** One colorimeter session per page; disconnects on unmount so GATT is never leaked. */
export function useColorimeter() {
  const support = bluetoothSupport()
  const device = reactive({
    state: STATE.IDLE,
    connecting: false,
    measuring: false,
    progress: '',
    name: '',
    profile: '',
    sn: '',
    fw: '',
    voltage: null,
    simulated: false,
    initWarning: '',
    error: '',
    logs: [],
  })
  const lateReadings = shallowRef([])
  let lateHandler = null

  const session = new ColorimeterSession({
    onState: (state, s) => {
      device.state = state
      device.name = s.deviceName
      device.profile = s.profile
      device.sn = s.info?.sn || ''
      device.fw = s.info?.fw || ''
      device.voltage = s.voltage
      device.simulated = s.simulated
      device.initWarning = s.initWarning
    },
    onLog: (message) => {
      const time = formatBeijingTime(new Date())
      device.logs = [`${time} ${message}`, ...device.logs].slice(0, LOG_LIMIT)
    },
    onLate: (reading) => {
      lateReadings.value = [...lateReadings.value, reading]
      lateHandler?.(reading)
    },
  })

  async function connect({ simulate = false } = {}) {
    device.error = ''
    device.connecting = true
    try {
      await session.connect({ simulate })
    } catch (err) {
      // User cancelling the chooser is not an error worth shouting about.
      device.error = err?.name === 'NotFoundError' ? '' : (err?.message || String(err))
      throw err
    } finally {
      device.connecting = false
    }
  }

  function disconnect() {
    session.disconnect('已手动断开')
  }

  /**
   * Measure `count` times strictly one after another. `onReading` runs per reading so
   * the caller can persist immediately; the target swatch is captured by the caller
   * before the first command to prevent cross-swatch mismatches.
   */
  async function measureSeries(count, onReading, { simTarget } = {}) {
    if (device.measuring) return 0
    device.measuring = true
    device.error = ''
    let done = 0
    try {
      if (simTarget) session.setSimTarget(simTarget)
      for (let i = 0; i < count; i++) {
        device.progress = count > 1 ? `${i + 1}/${count}` : ''
        const reading = await session.measure()
        await onReading(reading, i)
        done++
        if (i < count - 1) await new Promise((r) => setTimeout(r, 400))
      }
    } catch (err) {
      device.error = err?.message || String(err)
    } finally {
      device.measuring = false
      device.progress = ''
    }
    return done
  }

  function takeLate(reading) {
    lateReadings.value = lateReadings.value.filter((r) => r !== reading)
  }

  function onLateReading(fn) { lateHandler = fn }

  onBeforeUnmount(() => session.disconnect())

  return { STATE, support, device, lateReadings, connect, disconnect, measureSeries, takeLate, onLateReading }
}
