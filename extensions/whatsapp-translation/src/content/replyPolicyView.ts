import type { AutoReplyPolicy, AutoReplySchedule } from '@/shared/contracts'

export type PolicyHandlers = {
  read: () => Promise<AutoReplyPolicy | null>
  setChat: (list: 'block' | 'allow', value: boolean) => Promise<void>
  setAllowlistEnabled: (enabled: boolean) => Promise<void>
  setSchedule: (schedule: AutoReplySchedule | null) => Promise<void>
}

const DAY_LABELS = ['日', '一', '二', '三', '四', '五', '六']
const DEFAULT_SCHEDULE: AutoReplySchedule = { start: '09:00', end: '18:00', days: [1, 2, 3, 4, 5] }

export function createPolicyView(doc: Document, handlers: PolicyHandlers) {
  const root = doc.createElement('details')
  const summary = doc.createElement('summary'); summary.textContent = '自动接管名单与时段'
  const body = doc.createElement('div'); root.append(summary, body)
  const el = <K extends keyof HTMLElementTagNameMap>(tag: K, text = '') => {
    const node = doc.createElement(tag); node.textContent = text; return node
  }
  function button(text: string, action: () => void, disabled = false) {
    const node = el('button', text); node.type = 'button'; node.className = 'link'; node.disabled = disabled
    node.addEventListener('click', action); return node
  }
  let policy: AutoReplyPolicy | null | undefined
  let loading = false
  let notice = ''
  function checkbox(text: string, checked: boolean, action: (checked: boolean) => void, disabled = false) {
    const label = el('label'); const input = el('input') as HTMLInputElement
    input.type = 'checkbox'; input.checked = checked; input.disabled = disabled
    input.addEventListener('change', () => action(input.checked))
    label.append(input, doc.createTextNode(` ${text}`))
    return label
  }
  async function update(action: () => Promise<void>) {
    try { await action(); policy = await handlers.read(); notice = '' } catch { notice = '保存失败，请重试。' }
    build()
  }
  function readScheduleInputs(): AutoReplySchedule {
    const time = (name: string) => (body.querySelector(`input[data-auto-policy="${name}"]`) as HTMLInputElement | null)?.value ?? ''
    const days = [...body.querySelectorAll<HTMLInputElement>('input[data-auto-policy-day]')]
      .filter(input => input.checked).map(input => Number(input.dataset.autoPolicyDay))
    return { start: time('start'), end: time('end'), days }
  }
  function build() {
    body.replaceChildren()
    if (policy === undefined) { body.append(el('p', loading ? '正在读取自动接管设置…' : '')); return }
    if (notice) { const p = el('p', notice); p.setAttribute('role', 'alert'); body.append(p) }
    body.append(el('p', '仅当前设备生效；名单按聊天保存，不保存聊天名称。'))
    body.append(button(policy?.blocked ? '恢复此聊天自动接管' : '禁止此聊天自动接管',
      () => void update(() => handlers.setChat('block', !policy?.blocked))))
    body.append(checkbox('仅白名单自动接管', policy?.allowlistEnabled === true,
      checked => void update(() => handlers.setAllowlistEnabled(checked))))
    body.append(button(policy?.allowlisted ? '将此聊天移出白名单' : '将此聊天加入白名单',
      () => void update(() => handlers.setChat('allow', !policy?.allowlisted))))
    const schedule = policy?.schedule ?? null
    body.append(checkbox('限定自动接管时段（本地时间）', schedule !== null,
      checked => void update(() => handlers.setSchedule(checked ? (schedule ?? DEFAULT_SCHEDULE) : null))))
    if (schedule) {
      const times = el('div'); times.className = 'actions'
      for (const name of ['start', 'end'] as const) {
        const input = el('input') as HTMLInputElement
        input.type = 'time'; input.value = schedule[name]; input.dataset.autoPolicy = name
        input.setAttribute('aria-label', name === 'start' ? '时段开始' : '时段结束')
        input.addEventListener('change', () => void update(() => handlers.setSchedule(readScheduleInputs())))
        times.append(name === 'start' ? doc.createTextNode('从 ') : doc.createTextNode(' 到 '), input)
      }
      body.append(times)
      const days = el('div'); days.className = 'actions'
      for (let day = 0; day < 7; day++) {
        days.append(checkbox(`周${DAY_LABELS[day]}`, schedule.days.includes(day), () => {
          const next = readScheduleInputs()
          if (next.days.length) void update(() => handlers.setSchedule(next))
          else build()
        }))
        const input = days.lastElementChild?.querySelector('input')
        if (input) input.dataset.autoPolicyDay = String(day)
      }
      body.append(days)
    }
  }
  return {
    root,
    render(open: boolean) {
      root.hidden = !open
      if (open && policy === undefined && !loading) {
        loading = true; build()
        void handlers.read().then(value => { policy = value; notice = '' }).catch(() => { notice = '读取失败，请重试。' })
          .finally(() => { loading = false; build() })
      }
    },
  }
}
