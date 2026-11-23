// 手机录物流单 · 原型交互（示例数据，不连后端）
// 流程：待录列表 → 拍运单（实时边缘框）→ 自动裁正+增强 → 识别 → 核对 → 同步物流信息 → 提交

const $app = document.getElementById('app')
const $overlay = document.getElementById('overlay')
const $toast = document.getElementById('toast')
const $scenario = document.getElementById('scenario')

const ICON = {
  camera: '<path d="M4 8h3l2-3h6l2 3h3v11H4z"/><circle cx="12" cy="13" r="3.5"/>',
  search: '<circle cx="11" cy="11" r="6.5"/><path d="m20 20-4.2-4.2"/>',
  check: '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
  alert: '<path d="M12 4 2.8 20h18.4z"/><path d="M12 10v4.5M12 17.5v.01"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5.5M12 7.5v.01"/>',
  refresh: '<path d="M20 11a8 8 0 0 0-14.6-4.5M4 4v4h4M4 13a8 8 0 0 0 14.6 4.5M20 20v-4h-4"/>',
  image: '<rect x="3.5" y="4.5" width="17" height="15" rx="2"/><circle cx="9" cy="10" r="1.8"/><path d="m20.5 16-5-5-8.5 8.5"/>',
  back: '<path d="M15 5 8 12l7 7"/>',
}
const icon = (name, cls = 'i') => `<svg class="${cls}" viewBox="0 0 24 24" aria-hidden="true">${ICON[name]}</svg>`

const SCENARIO = {
  normal: { waybill: '1234567890', source: 'barcode', sync: 'found', labelCountry: 'United States' },
  not_found: { waybill: '5583019274', source: 'barcode', sync: 'not_found', labelCountry: 'United Kingdom', aiAlt: '5583019247' },
  failed: { waybill: '7720465813', source: 'barcode', sync: 'failed', labelCountry: 'Nigeria' },
  exists: { waybill: '4819203376', source: 'barcode', sync: 'exists', labelCountry: 'United States' },
  colleague: { waybill: '6120938475', source: 'barcode', sync: 'exists', colleague: true, labelCountry: 'United States' },
  mismatch: { waybill: '3390118425', source: 'barcode', sync: 'found', labelCountry: 'United Kingdom', aiCountry: '英国', dest: '英国' },
  ocr_only: { waybill: '6604721958', source: 'ocr', sync: 'found', labelCountry: 'United States', taped: true },
  none: { waybill: '', source: 'none', sync: 'found', labelCountry: 'United States', blurry: true },
  no_edge: { waybill: '2045968113', source: 'barcode', sync: 'found', labelCountry: 'United States', noEdge: true },
  other_customer: { waybill: '9036612870', source: 'barcode', sync: 'other_customer', labelCountry: 'Canada' },
  ups: { waybill: '1Z999AA10123456784', source: 'ocr', carrier: 'UPS', sync: 'unsupported', labelCountry: 'United States' },
  conflict: { waybill: '1234567890', source: 'barcode', sync: 'found', labelCountry: 'United States', submitConflict: true },
  no_perm: { waybill: '1234567890', source: 'barcode', sync: 'found', labelCountry: 'United States', noPerm: true },
}

const state = {
  scenario: 'normal',
  tab: 'pending',
  keyword: '',
  showOlder: false,
  nextId: null,
  pending: [
    { id: 101, no: 'SHT261187', customer: 'Sarah Johnson Hair Studio', recipient: 'Sarah Johnson', country: '美国', submitted: '今天 10:42', items: 6, is9610: true, alibaba: '2928374650019283746', shop: '大莱莎' },
    { id: 102, no: 'SHT261185', customer: 'Bella Wigs Ltd', recipient: 'Emma Clarke', country: '英国', submitted: '今天 09:58', items: 3 },
    { id: 103, no: 'SHT261183', customer: 'Lagos Luxe Hair', recipient: 'Adaeze Okafor', country: '尼日利亚', submitted: '今天 09:21', items: 12 },
    { id: 104, no: 'SHT261180', customer: 'Maison Cheveux', recipient: 'Claire Martin', country: '法国', submitted: '昨天 17:46', items: 2, is9610: true, alibaba: '', shop: '小莱莎' },
    { id: 105, no: 'SHT261176', customer: 'Crown & Glory LLC', recipient: 'Tasha Reed', country: '美国', submitted: '昨天 15:03', items: 8 },
    { id: 106, no: 'SHT261102', customer: 'Hair Haven Pty', recipient: 'Mia Nguyen', country: '澳大利亚', submitted: '11-06 14:20', items: 4, older: true },
  ],
  done: [
    { id: 98, no: 'SHT261170', customer: 'Diamond Tresses', country: '美国', waybill: '4819203376', time: '今天 09:31',
      photo: { waybill: '4819203376', recipient: 'Kayla Brooks', labelCountry: 'United States', source: 'barcode', by: '王小雅', at: '今天 09:30' }, history: [] },
    { id: 97, no: 'SHT261168', customer: 'Velvet Mane Co.', country: '加拿大', waybill: '9036612870', time: '今天 09:12',
      photo: { waybill: '9036612870', recipient: 'Olivia Tremblay', labelCountry: 'Canada', source: 'ocr', by: '跟单 李晨', at: '今天 09:11' },
      history: [{ waybill: '9036612807', recipient: 'Olivia Tremblay', labelCountry: 'Canada', source: 'manual', by: '跟单 李晨', at: '今天 08:52', replacedAt: '今天 09:12' }] },
  ],
  flow: null,
}

const ISO = { '美国': 'US', 'united states': 'US', '英国': 'GB', 'united kingdom': 'GB', '尼日利亚': 'NG', nigeria: 'NG', '法国': 'FR', france: 'FR', '澳大利亚': 'AU', australia: 'AU', '加拿大': 'CA', canada: 'CA' }
const iso = v => ISO[String(v || '').trim().toLowerCase()] || String(v || '').trim().toUpperCase()
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c])
const sc = () => SCENARIO[state.scenario]
const wait = ms => new Promise(r => setTimeout(r, ms))
const reduced = () => matchMedia('(prefers-reduced-motion: reduce)').matches

let toastTimer
function toast(text) {
  $toast.textContent = text
  $toast.classList.add('show')
  clearTimeout(toastTimer)
  toastTimer = setTimeout(() => $toast.classList.remove('show'), 2600)
}

/* ── 列表 ─────────────────────────── */
function renderList() {
  const kw = state.keyword.trim().toLowerCase()
  const match = r => !kw || r.no.toLowerCase().includes(kw) || r.customer.toLowerCase().includes(kw)
  const pending = state.pending.filter(r => match(r) && (kw || state.showOlder || !r.older))
  const olderHidden = !kw && !state.showOlder && state.pending.some(r => r.older)
  const done = state.done.filter(match)
  const noPerm = !!sc().noPerm
  const rows = state.tab === 'pending' ? pending : done

  $app.innerHTML = `
    <header class="topbar"><h1>手机录物流单</h1><span class="who">王小雅 · 业务</span></header>
    ${noPerm ? `<div class="notice" data-tone="danger">${icon('alert')}<div>你还没有<b>物流单上传权限</b>，可以查看列表，但不能拍运单。请联系管理员开通。</div></div>` : ''}
    <div class="tabs" role="tablist">
      <button class="tab" role="tab" data-tab="pending" aria-selected="${state.tab === 'pending'}">待录<span class="count">${state.pending.length}</span></button>
      <button class="tab" role="tab" data-tab="done" aria-selected="${state.tab === 'done'}">今天已录<span class="count">${state.done.length}</span></button>
    </div>
    <div class="search">${icon('search')}<input id="kw" type="search" inputmode="search" placeholder="搜出库单号或客户" value="${esc(state.keyword)}" aria-label="搜索验货单"></div>
    <div class="list">
      ${rows.length ? rows.map(r => state.tab === 'pending' ? pendingCard(r, noPerm) : doneCard(r, noPerm)).join('') :
        `<div class="empty">${state.tab === 'pending' ? (kw ? '没有匹配的验货单' : '待发货的单都录好了') : '今天还没有录入物流单'}</div>`}
    </div>
    ${state.tab === 'pending' && olderHidden ? `<button class="btn block more" data-act="older">查看更早提交的验货单</button>` : ''}
    <p class="foot">默认显示近 14 天提交、未关联物流单的验货单</p>`
}

function pendingCard(r, noPerm) {
  return `<article class="card ${state.nextId === r.id ? 'is-next' : ''}" data-id="${r.id}">
    <div class="no num">${esc(r.no)}${r.is9610 ? '<span class="badge">9610</span>' : ''}</div>
    <div class="cust">${esc(r.customer)}</div>
    <div class="meta">${esc(r.country)} · ${r.items} 件 · 提交于 ${esc(r.submitted)}</div>
    <div class="act"><button class="btn primary" data-act="shoot" data-id="${r.id}" ${noPerm ? 'disabled' : ''}>${icon('camera')}拍运单</button></div>
  </article>`
}

function doneCard(r, noPerm) {
  return `<article class="card has-thumb" data-id="${r.id}">
    <button class="thumb" data-act="photo" data-id="${r.id}" aria-label="查看 ${esc(r.no)} 的物流单照片">${labelHTML(null, 'label flat enhanced', r.photo)}</button>
    <div class="no num">${esc(r.no)}<span class="badge" data-tone="muted">DHL ${esc(r.waybill)}</span></div>
    <div class="cust">${esc(r.customer)}</div>
    <div class="meta">${esc(r.country)} · 录入于 ${esc(r.time)}</div>
    <div class="act"><button class="btn" data-act="replace" data-id="${r.id}" ${noPerm ? 'disabled' : ''}>更换</button></div>
  </article>`
}

$app.addEventListener('click', e => {
  const t = e.target.closest('[data-tab],[data-act]')
  if (!t) return
  if (t.dataset.tab) { state.tab = t.dataset.tab; state.nextId = null; renderList(); return }
  const act = t.dataset.act
  if (act === 'older') { state.showOlder = true; renderList() }
  if (act === 'shoot') startFlow(state.pending.find(r => r.id === +t.dataset.id), false)
  if (act === 'photo') { openViewer(state.done.find(r => r.id === +t.dataset.id)); return }
  if (act === 'replace') {
    const row = state.done.find(r => r.id === +t.dataset.id)
    openSheet({
      title: '更换物流单？',
      body: `${row.no} 当前关联 DHL ${row.waybill}。重新拍摄并提交后，新运单替换旧运单，旧运单照片保留并标记「已替换」。`,
      ok: '重新拍运单',
      onOk: () => startFlow({ ...row, recipient: 'Kayla Brooks', items: 5 }, true),
    })
  }
})
$app.addEventListener('input', e => {
  if (e.target.id !== 'kw') return
  state.keyword = e.target.value
  const pos = e.target.selectionStart
  renderList()
  const input = document.getElementById('kw')
  input.focus(); input.setSelectionRange(pos, pos)
})

/* ── 全屏层 ───────────────────────── */
let screenEl = null
function showScreen(html, { light = false } = {}) {
  const first = !screenEl
  if (first) {
    screenEl = document.createElement('section')
    screenEl.className = 'screen'
    screenEl.setAttribute('role', 'dialog')
    screenEl.setAttribute('aria-modal', 'true')
    if (!reduced()) screenEl.setAttribute('data-enter', '')
    $overlay.appendChild(screenEl)
    requestAnimationFrame(() => requestAnimationFrame(() => screenEl?.removeAttribute('data-enter')))
    document.body.style.overflow = 'hidden'
  }
  screenEl.classList.toggle('light', light)
  screenEl.innerHTML = html
  screenEl.scrollTop = 0
  document.querySelector('.sticky-submit')?.remove()
}
function closeScreen() {
  stopDetection()
  document.querySelector('.sticky-submit')?.remove()
  const el = screenEl
  screenEl = null
  state.flow = null
  document.body.style.overflow = ''
  if (!el) return
  if (reduced()) { el.remove(); return }
  el.setAttribute('data-enter', '')
  setTimeout(() => el.remove(), 200)
}

const sceneHTML = (f, withQuad = true) => `
  <div class="scene" id="scene">
    <div class="box"></div>
    ${labelHTML(f, 'label')}
    ${withQuad ? '<div class="guide" id="guide"></div><svg class="quad" id="quad" viewBox="0 0 1 1" preserveAspectRatio="none" aria-hidden="true"><polygon points="" vector-effect="non-scaling-stroke" style="display:none"/></svg>' : ''}
    <div class="flash" id="flash"></div>
  </div>`

function labelHTML(f, cls, photo = null) {
  const s = photo ? { waybill: photo.waybill, labelCountry: photo.labelCountry } : sc()
  const recipient = photo ? photo.recipient : f.item.recipient
  const no = s.waybill || '0000000000'
  const spaced = `${no.slice(0, 2)} ${no.slice(2, 6)} ${no.slice(6)}`
  return `<div class="${cls} ${s.blurry ? 'blurry' : ''}">
    <div class="band">EXPRESS WORLDWIDE</div>
    <div class="ln">From: <b>LeShine Hair</b> · Qingdao, China</div>
    <div class="ln">To: <b>${esc(recipient)}</b></div>
    <div class="ln">${esc(s.labelCountry)}</div>
    <div class="awb">WAYBILL ${spaced}</div>
    <div class="bars">${s.taped ? '<div class="tape"></div>' : ''}</div>
    <div class="tiny">(J) JD01 4600 0123 4567 8901 · 2LUS77002+48000000</div>
  </div>`
}

/* ── 1. 取景：实时边缘框 ───────────── */
let detectTimer = null
function startFlow(item, replacing) {
  state.flow = { item, replacing, found: false, corners: null, waybill: '', source: '', carrier: 'DHL', sync: null, syncing: false, editing: false, confirmedMismatch: false, cropped: false }
  renderCamera()
}

function renderCamera() {
  const f = state.flow
  showScreen(`
    <div class="screen-top">
      <button class="btn ghost" data-act="cancel">取消</button>
      <div class="ctx">${f.replacing ? '更换 · ' : ''}${esc(f.item.no)}</div>
    </div>
    <div class="cam-cust">核对包裹：<b>${esc(f.item.customer)}</b> · ${esc(f.item.country)}</div>
    <p class="hint" id="hint" role="status">把运单四个角都放进画面</p>
    ${sceneHTML(f)}
    <div class="shutter-row">
      <button class="btn ghost side" data-act="album">${icon('image')}相册</button>
      <button class="shutter" id="shutter" data-act="shutter" aria-label="拍照"><span></span></button>
      <span></span>
    </div>`)
  startDetection()
}

function labelCorners() {
  const scene = document.getElementById('scene')
  const label = scene?.querySelector('.label')
  if (!label) return null
  const W = scene.clientWidth, H = scene.clientHeight
  const w = label.offsetWidth, h = label.offsetHeight
  const cx = label.offsetLeft + w / 2, cy = label.offsetTop + h / 2
  const a = -7 * Math.PI / 180
  return [[-1, -1], [1, -1], [1, 1], [-1, 1]].map(([sx, sy]) => {
    const x = sx * w / 2, y = sy * h / 2
    return [(cx + x * Math.cos(a) - y * Math.sin(a)) / W, (cy + x * Math.sin(a) + y * Math.cos(a)) / H]
  })
}

function startDetection() {
  stopDetection()
  const started = performance.now()
  detectTimer = setInterval(() => {
    const f = state.flow
    const poly = document.querySelector('#quad polygon')
    const guide = document.getElementById('guide')
    const hint = document.getElementById('hint')
    const shutter = document.getElementById('shutter')
    if (!f || !poly) return stopDetection()
    const found = !sc().noEdge && performance.now() - started > 700
    f.found = found
    if (found) {
      const base = labelCorners()
      if (!base) return
      const jit = base.map(([x, y]) => [x + (Math.random() - 0.5) * 0.006, y + (Math.random() - 0.5) * 0.006])
      f.corners = jit
      poly.setAttribute('points', jit.map(p => p.join(',')).join(' '))
      poly.style.display = ''
      guide.style.display = 'none'
    } else {
      poly.style.display = 'none'
      guide.style.display = ''
    }
    const bc = found && sc().source === 'barcode' ? sc().waybill : ''
    hint.textContent = found ? (bc ? `已读到 ${bc.slice(0, 2)} ${bc.slice(2, 6)} ${bc.slice(6)}，可以拍照` : '已对准运单，可以拍照') : '把运单四个角都放进画面'
    hint.classList.toggle('ok', found)
    shutter.classList.toggle('ready', found)
  }, 135)
}
function stopDetection() { clearInterval(detectTimer); detectTimer = null }

async function shoot() {
  const f = state.flow
  stopDetection()
  const flash = document.getElementById('flash')
  if (flash && !reduced()) { flash.classList.remove('on'); void flash.offsetWidth; flash.classList.add('on') }
  await wait(reduced() ? 0 : 220)
  if (state.flow !== f) return
  if (f.found) recognize()
  else renderCrop()
}

/* ── 1b. 没找到边缘：拖四角 ─────────── */
function renderCrop() {
  const f = state.flow
  f.corners = [[0.16, 0.2], [0.84, 0.2], [0.84, 0.8], [0.16, 0.8]]
  f.cropped = true
  showScreen(`
    <div class="screen-top">
      <button class="btn ghost" data-act="retake">重拍</button>
      <div class="ctx">调整边缘</div>
    </div>
    <p class="hint" role="status">没找到完整边缘，拖动四个角对准运单</p>
    ${sceneHTML(f, false)}
    <div class="shutter-row" style="grid-template-columns:1fr">
      <button class="btn primary block" data-act="apply-crop">应用校正</button>
    </div>`)
  const scene = document.getElementById('scene')
  scene.insertAdjacentHTML('beforeend', `<svg class="quad" viewBox="0 0 1 1" preserveAspectRatio="none" aria-hidden="true"><polygon vector-effect="non-scaling-stroke"/></svg>
    ${f.corners.map((_, i) => `<button class="handle" data-i="${i}" aria-label="拖动第 ${i + 1} 个角"></button>`).join('')}`)
  drawCrop()
  let dragging = false
  scene.addEventListener('pointerdown', e => {
    const h = e.target.closest('.handle')
    if (!h || dragging) return // 拖动中忽略第二根手指，防止角点跳动
    dragging = true
    e.preventDefault()
    h.setPointerCapture(e.pointerId)
    const i = +h.dataset.i
    const move = ev => {
      const r = scene.getBoundingClientRect()
      f.corners[i] = [Math.min(1, Math.max(0, (ev.clientX - r.left) / r.width)), Math.min(1, Math.max(0, (ev.clientY - r.top) / r.height))]
      drawCrop()
    }
    const up = () => { dragging = false; h.removeEventListener('pointermove', move); h.removeEventListener('pointerup', up); h.removeEventListener('pointercancel', up) }
    h.addEventListener('pointermove', move)
    h.addEventListener('pointerup', up)
    h.addEventListener('pointercancel', up)
  })
}
function drawCrop() {
  const f = state.flow
  const scene = document.getElementById('scene')
  if (!scene) return
  scene.querySelector('.quad polygon').setAttribute('points', f.corners.map(p => p.join(',')).join(' '))
  scene.querySelectorAll('.handle').forEach((h, i) => { h.style.left = f.corners[i][0] * 100 + '%'; h.style.top = f.corners[i][1] * 100 + '%' })
}

/* ── 2. 识别 ─────────────────────── */
async function recognize() {
  const f = state.flow
  const s = sc()
  const steps = [
    ['裁正并增强', '已完成'],
    ['读取条码', s.source === 'barcode' ? '读出 10 位单号' : '没读到条码'],
    ['AI 识别收件信息', s.source === 'none' ? '没认出单号' : '已识别'],
  ]
  const draw = k => `<div class="screen-top"><span></span><div class="ctx">${esc(f.item.no)}</div></div>
    <div class="processing">
      <h2 style="font-size:19px">正在识别运单号…</h2>
      <ol class="steps">${steps.map(([t, r], i) => `<li class="${i < k ? 'done' : i === k ? 'doing' : ''}"><span class="dot">${i < k ? icon('check') : ''}</span>${t}${i < k ? ` · ${r}` : ''}</li>`).join('')}</ol>
    </div>`
  for (let k = 0; k <= steps.length; k++) {
    if (state.flow !== f) return
    showScreen(draw(k))
    if (k < steps.length) await wait([350, 450, 700][k])
  }
  await wait(150)
  if (state.flow !== f) return
  f.waybill = s.waybill && s.source !== 'none' ? s.waybill : ''
  f.source = s.source === 'none' ? 'manual' : s.source
  f.carrier = s.carrier || 'DHL'
  f.editing = s.source === 'none'
  f.recipient = f.item.recipient
  f.country = s.aiCountry || f.item.country
  renderReview()
}

/* ── 3. 核对 + 同步 ──────────────── */
const SRC = { barcode: '条码', ocr: 'AI 识别', manual: '手动' }

function renderReview() {
  const f = state.flow
  const s = sc()
  const it = f.item
  showScreen(`
    <div class="screen-top">
      <button class="btn link" data-act="cancel">${icon('back')}返回列表</button>
      <div class="ctx" style="opacity:1">${f.replacing ? '更换物流单' : '核对物流单'}</div>
    </div>
    <div class="review">
      <section class="panel">
        <div class="photo-row">
          ${labelHTML(f, 'label flat enhanced')}
          <div class="photo-actions">
            <small>${f.cropped ? '已按你调整的边缘裁正' : '已按取景时的边缘自动裁正'} · 增强</small>
            <button class="btn link" data-act="retake">${icon('camera')}重拍</button>
            <button class="btn link" data-act="adjust">调整边缘</button>
          </div>
        </div>
      </section>

      <section class="panel" aria-labelledby="h-no">
        <h2 id="h-no">运单号 ${f.waybill && !f.editing ? `<button class="btn link" data-act="edit">修改</button>` : ''}</h2>
        ${f.editing ? `
          ${s.source === 'none' && !f.waybill ? `<div class="notice" data-tone="warning">${icon('alert')}<div>没读出运单号。可以重拍，或照着面单手动输入。</div></div>` : ''}
          <div class="edit"><input id="no-input" inputmode="numeric" autocomplete="off" maxlength="20" placeholder="10 位数字" value="${esc(f.waybill)}" aria-label="运单号"><button class="btn primary" data-act="save-no">确定</button></div>
        ` : `
          <div class="number"><span class="val num">${esc(f.waybill)}</span><span class="src" data-src="${f.source}">${SRC[f.source]}</span></div>
          ${f.source === 'ocr' ? '<p class="sub">没读到条码，单号由 AI 从面单文字识别，请对照面单核对一遍。</p>' : ''}
          ${f.source === 'barcode' && s.aiAlt ? `<p class="sub">AI 识别为 ${esc(s.aiAlt)}，已按条码填写。</p>` : ''}
        `}
        ${f.source === 'barcode' ? '' : `<div class="carriers" role="group" aria-label="承运商">
          ${['DHL', 'FedEx', 'UPS'].map(c => `<button data-carrier="${c}" aria-pressed="${f.carrier === c}">${c}</button>`).join('')}
        </div>`}
        <p class="sub">${f.source === 'barcode' ? '按单号格式判定为 DHL' : f.source === 'manual' ? '手动输入时请确认承运商' : `AI 判断为 ${esc(f.carrier)}，请核对`}</p>
      </section>

      <section class="panel" aria-labelledby="h-sync" aria-live="polite">
        <h2 id="h-sync">物流信息</h2>
        <button class="btn block ${f.sync ? '' : 'primary'}" data-act="sync" ${f.syncing || f.editing || !f.waybill ? 'disabled' : ''}>
          ${icon('refresh')}${f.syncing ? '正在查询 DHL…' : f.sync ? '重新同步' : '同步物流信息'}
        </button>
        ${syncHTML()}
      </section>

      <section class="panel">
        <h2>验货单</h2>
        <dl class="ctx-grid">
          <dt>出库单号</dt><dd class="num">${esc(it.no)}</dd>
          <dt>客户</dt><dd>${esc(it.customer)}</dd>
          <dt>客户国家</dt><dd>${esc(it.country)}</dd>
          <dt>商品</dt><dd>${it.items} 件</dd>
        </dl>
      </section>

      ${it.is9610 ? `<div class="notice" data-tone="warning">${icon('alert')}<div><b>本单走 9610</b>，请确认已在 DHL 填写跨境申报。<br>${esc(it.shop)} · ${it.alibaba ? `阿里订单 ${esc(it.alibaba)}` : '发票未填阿里信保订单号，请到发票补录（不影响提交）'}</div></div>` : ''}

      <section class="panel">
        <details class="recv">
          <summary>收件信息<span>${s.aiCountry ? 'AI 识别' : 'AI 识别 · 订单预填'} · 可修改 ›</span></summary>
          <div class="fields">
            <label>收件人<input value="${esc(f.recipient)}" data-field="recipient"></label>
            <label>收件国家<input value="${esc(f.country)}" data-field="country"></label>
            <label>发件日期<input type="date" value="2026-11-23" data-field="date"></label>
          </div>
        </details>
      </section>

    </div>`, { light: true })
  renderSubmitBar()
}

function syncHTML() {
  const f = state.flow
  if (!f.sync) return f.editing ? '' : '<p class="sub">提交前先查一次承运商，确认单号没拍错。</p>'
  const r = f.sync
  if (r.kind === 'bad_format') return `<div class="sync-result"><div class="notice" data-tone="danger">${icon('alert')}<div>这不像 DHL 运单号：DHL 单号应为 <b>10 位数字</b>。请修改单号或重拍。</div></div></div>`
  if (r.kind === 'not_found') return `<div class="sync-result"><div class="notice" data-tone="info">${icon('info')}<div>DHL 暂无这张运单的记录。包裹还没被揽收时很常见，提交后系统会持续跟踪。</div></div>${countryWarn()}</div>`
  if (r.kind === 'other_customer') return `<div class="sync-result"><div class="notice" data-tone="danger">${icon('alert')}<div><b>这张运单已关联到另一位客户的验货单</b>，很可能拍错了包裹。请核对手里的包裹后重拍。</div></div></div>`
  if (r.kind === 'unsupported') return `<div class="sync-result"><div class="notice" data-tone="info">${icon('info')}<div>方舟还不能查询 ${esc(f.carrier)} 轨迹，提交后只做登记。</div></div>${countryWarn()}</div>`
  if (r.kind === 'failed') return `<div class="sync-result"><div class="notice" data-tone="danger">${icon('alert')}<div>物流接口暂时查不到，可以重试，也可以先提交，系统稍后自动查询。</div></div>${countryWarn()}</div>`
  const events = r.events.map(e => `<li><time class="num">${e.t}</time>${esc(e.d)} · ${esc(e.l)}</li>`).join('')
  const it = f.item
  return `<div class="sync-result">
    <div class="status-line"><strong>${r.status}</strong><span class="sub" style="margin:0">寄往 ${esc(r.dest)}</span></div>
    <ul class="events">${events}</ul>
    ${countryWarn()}
    ${r.kind === 'exists' && sc().colleague ? `<div class="notice" data-tone="info">${icon('info')}<div>运单已由其他同事录入，还没关联其他客户的验货单。你是本单的业务员或跟单员，可以直接关联。</div></div>` : ''}
    ${r.kind === 'exists' && !sc().colleague ? `<div class="notice" data-tone="info">${icon('info')}<div>运单已录入物流跟踪，已关联<b>本客户</b> 1 张验货单。同一包裹合并发货时正常，提交后本单也关联到这张运单。</div></div>` : ''}
  </div>`
}

function mismatchDest() {
  const f = state.flow
  const want = iso(f.item.country)
  return [f.sync?.dest, f.country].filter(Boolean).find(c => iso(c) !== want) || ''
}
function countryWarn() {
  const d = mismatchDest()
  return d ? `<div class="notice" data-tone="warning">${icon('alert')}<div>运单寄往<b>${esc(d)}</b>，验货单客户在<b>${esc(state.flow.item.country)}</b>。请确认没有拍错包裹。</div></div>` : ''
}

function submitState() {
  const f = state.flow
  if (f.editing) return { disabled: true, text: '提交物流单', note: '先确定运单号' }
  if (!f.sync) return { disabled: true, text: '提交物流单', note: '先同步物流信息' }
  if (f.sync.kind === 'bad_format') return { disabled: true, text: '提交物流单', note: '运单号格式不对' }
  if (f.sync.kind === 'failed') return { disabled: false, text: '仍然提交', note: '物流信息稍后由系统自动补上' }
  if (!String(f.country || '').trim()) return { disabled: true, text: '提交物流单', note: '请在收件信息里填写收件国家' }
  if (f.sync.kind === 'other_customer') return { disabled: true, text: '提交物流单', note: '运单属于其他客户，不能关联' }
  if (f.sync.kind === 'exists') return { disabled: false, text: '关联已有运单', note: '' }
  return { disabled: false, text: f.replacing ? '替换为这张运单' : '提交物流单', note: '' }
}

function renderSubmitBar() {
  document.querySelector('.sticky-submit')?.remove()
  const st = submitState()
  const bar = document.createElement('div')
  bar.className = 'sticky-submit'
  bar.innerHTML = `<button class="btn primary block" data-act="submit" ${st.disabled || state.flow.submitting ? 'disabled' : ''}>${state.flow.submitting ? '正在提交…' : st.text}</button>${st.note ? `<p>${st.note}</p>` : ''}`
  $overlay.appendChild(bar)
}

async function sync() {
  const f = state.flow
  const s = sc()
  f.syncing = true
  f.confirmedMismatch = false
  renderReview()
  await wait(800)
  if (state.flow !== f) return
  f.syncing = false
  const it = f.item
  const dest = s.dest || it.country
  const events = [
    { t: '11-23 14:05', d: '快件已揽收', l: 'QINGDAO - CHINA' },
    { t: '11-23 11:32', d: '已收到运单信息', l: 'QINGDAO - CHINA' },
  ]
  if (f.carrier === 'DHL' && !/^\d{10}$/.test(f.waybill)) f.sync = { kind: 'bad_format' }
  else if (f.source === 'manual' && s.source === 'none') f.sync = { kind: 'found', status: '已揽收', dest, events }
  else if (s.sync === 'other_customer') f.sync = { kind: 'other_customer' }
  else if (s.sync === 'unsupported' || f.carrier === 'UPS') f.sync = { kind: 'unsupported' }
  else if (s.sync === 'not_found') f.sync = { kind: 'not_found' }
  else if (s.sync === 'failed') f.sync = { kind: 'failed' }
  else if (s.sync === 'exists') f.sync = { kind: 'exists', status: '运输中', dest, events: [{ t: '11-23 18:40', d: '已离开转运中心', l: 'SHANGHAI - CHINA' }, ...events] }
  else f.sync = { kind: 'found', status: '已揽收', dest, events }
  renderReview()
}

async function submit() {
  const f = state.flow
  const r = f.sync
  const md = mismatchDest()
  if (md && !f.confirmedMismatch) {
    openSheet({
      title: '确认没有拍错包裹？',
      body: `运单寄往${md}，验货单 ${f.item.no} 的客户在${f.item.country}。确认这张运单就是这个包裹的，再提交。`,
      ok: '确认无误，提交', cancel: '返回检查',
      onOk: () => { f.confirmedMismatch = true; submit() },
    })
    return
  }
  f.submitting = true
  renderSubmitBar()
  await wait(700)
  if (state.flow !== f) return
  if (sc().submitConflict) {
    closeScreen()
    renderList()
    toast('验货单已变化（可能刚被撤回），列表已刷新')
    return
  }
  const it = f.item
  if (f.replacing) {
    const row = state.done.find(d => d.id === it.id)
    if (row) {
      row.history = [{ ...row.photo, replacedAt: '刚刚' }, ...(row.history || [])]
      row.photo = newPhoto(f)
      row.waybill = f.waybill; row.time = '刚刚'
    }
    state.nextId = null
  } else {
    const idx = state.pending.findIndex(p => p.id === it.id)
    state.pending.splice(idx, 1)
    state.done.unshift({ id: it.id, no: it.no, customer: it.customer, country: it.country, waybill: f.waybill, time: '刚刚', photo: newPhoto(f), history: [] })
    const next = state.pending.filter(p => state.showOlder || !p.older)[Math.min(idx, state.pending.length - 1)]
    state.nextId = next?.id ?? null
  }
  closeScreen()
  renderList()
  toast(`${f.sync.kind === 'exists' ? '已关联' : '已录入'} · ${f.carrier} ${f.waybill}`)
  requestAnimationFrame(() => document.querySelector('.card.is-next')?.scrollIntoView({ block: 'center', behavior: reduced() ? 'auto' : 'smooth' }))
}

/* ── 物流单照片查看器 ─────────────── */
const SRC_TEXT = { barcode: '条码', ocr: 'AI 识别', manual: '手动' }
function newPhoto(f) {
  return { waybill: f.waybill, recipient: f.recipient || f.item.recipient, labelCountry: sc().labelCountry, source: f.source, by: '王小雅', at: '刚刚' }
}

let viewerEl = null
function openViewer(row, idx = 0) {
  const photos = [row.photo, ...(row.history || [])]
  const view = { variant: 'rectified', zoom: false, idx }
  const el = document.createElement('section')
  el.className = 'viewer'
  el.setAttribute('role', 'dialog')
  el.setAttribute('aria-modal', 'true')
  el.setAttribute('aria-label', '物流单照片')
  if (!reduced()) el.setAttribute('data-enter', '')
  document.body.appendChild(el)
  viewerEl = el
  const draw = () => {
    const ph = photos[view.idx]
    const img = view.variant === 'rectified'
      ? labelHTML(null, 'label flat enhanced', ph)
      : `<div class="raw">${labelHTML(null, 'label', ph)}</div>`
    el.innerHTML = `
      <div class="viewer-top">
        <button class="btn ghost" data-v="close">关闭</button>
        <div class="ctx">${esc(row.no)} · ${esc(row.customer)}</div>
      </div>
      ${ph.replacedAt ? `<div class="notice" data-tone="warning">${icon('alert')}<div>这是已替换的旧照片（${esc(ph.replacedAt)} 被替换）</div></div>` : ''}
      <div class="seg" role="group" aria-label="图片版本">
        <button data-v="rectified" aria-pressed="${view.variant === 'rectified'}">增强图</button>
        <button data-v="original" aria-pressed="${view.variant === 'original'}">原图</button>
      </div>
      <div class="stage ${view.zoom ? 'zoomed' : ''}" data-v="zoom" title="双击放大">${img}</div>
      <p class="zoom-hint">${view.zoom ? '双击缩小，拖动查看' : '双击放大（真机支持双指缩放）'}</p>
      <dl class="photo-meta">
        <dt>运单号</dt><dd class="num">DHL ${esc(ph.waybill)}</dd>
        <dt>单号来源</dt><dd>${SRC_TEXT[ph.source] || '—'}</dd>
        <dt>拍摄</dt><dd>${esc(ph.by)} · ${esc(ph.at)}</dd>
      </dl>
      <button class="btn block" data-v="download">下载${view.variant === 'rectified' ? '增强图' : '原图'}</button>
      ${photos.length > 1 ? `<div class="history"><h3>${view.idx === 0 ? '历史照片' : '其他照片'}</h3>${photos.map((p, i) => i === view.idx ? '' : `
        <button class="hist-row" data-v="pick" data-i="${i}"><span class="thumb">${labelHTML(null, 'label flat enhanced', p)}</span>
          <span><b class="num">DHL ${esc(p.waybill)}</b><small>${p.replacedAt ? `已替换 · ${esc(p.replacedAt)}` : '当前照片'} · ${esc(p.by)}</small></span></button>`).join('')}</div>` : ''}`
  }
  draw()
  requestAnimationFrame(() => requestAnimationFrame(() => viewerEl?.removeAttribute('data-enter')))
  el.addEventListener('click', e => {
    const b = e.target.closest('[data-v]')
    if (!b) return
    const v = b.dataset.v
    if (v === 'close') closeViewer()
    if (v === 'rectified' || v === 'original') { view.variant = v; draw() }
    if (v === 'download') toast(`已下载 ${row.no} 物流单${view.variant === 'rectified' ? '增强图' : '原图'}（原型示意）`)
    if (v === 'pick') { view.idx = +b.dataset.i; view.zoom = false; draw(); el.scrollTop = 0 }
  })
  el.addEventListener('dblclick', e => { if (e.target.closest('.stage')) { view.zoom = !view.zoom; draw() } })
  el.querySelector('[data-v="close"]').focus()
}
function closeViewer() {
  const el = viewerEl
  viewerEl = null
  if (!el) return
  if (reduced()) { el.remove(); return }
  el.setAttribute('data-leave', '')
  setTimeout(() => el.remove(), 180)
}

/* ── 底部弹层 ─────────────────────── */
let sheetEls = null
function openSheet({ title, body, ok, cancel = '取消', onOk }) {
  closeSheet(true)
  const scrim = document.createElement('div')
  scrim.className = 'scrim'
  const sheet = document.createElement('div')
  sheet.className = 'sheet'
  sheet.setAttribute('role', 'alertdialog')
  sheet.setAttribute('aria-modal', 'true')
  sheet.innerHTML = `<h3>${esc(title)}</h3><p>${esc(body)}</p><div class="row"><button class="btn block" data-s="cancel">${esc(cancel)}</button><button class="btn primary block" data-s="ok">${esc(ok)}</button></div>`
  if (!reduced()) { scrim.setAttribute('data-enter', ''); sheet.setAttribute('data-enter', '') }
  document.body.append(scrim, sheet)
  requestAnimationFrame(() => requestAnimationFrame(() => { scrim.removeAttribute('data-enter'); sheet.removeAttribute('data-enter') }))
  sheetEls = { scrim, sheet }
  scrim.onclick = () => closeSheet()
  sheet.onclick = e => {
    const b = e.target.closest('[data-s]')
    if (!b) return
    closeSheet()
    if (b.dataset.s === 'ok') onOk()
  }
  sheet.querySelector('[data-s="ok"]').focus()
}
function closeSheet(instant = false) {
  if (!sheetEls) return
  const { scrim, sheet } = sheetEls
  sheetEls = null
  if (instant || reduced()) { scrim.remove(); sheet.remove(); return }
  scrim.setAttribute('data-leave', ''); sheet.setAttribute('data-leave', '')
  setTimeout(() => { scrim.remove(); sheet.remove() }, 190)
}

/* ── 全屏层事件 ───────────────────── */
$overlay.addEventListener('click', e => {
  const f = state.flow
  if (!f) return
  const c = e.target.closest('[data-carrier]')
  if (c) { f.carrier = c.dataset.carrier; f.sync = null; f.confirmedMismatch = false; renderReview(); return }
  const t = e.target.closest('[data-act]')
  if (!t) return
  const act = t.dataset.act
  if (act === 'cancel') closeScreen()
  if (act === 'shutter') shoot()
  if (act === 'album') { toast('原型中用当前画面代替相册照片'); shoot() }
  if (act === 'retake') { f.cropped = false; f.sync = null; renderCamera() }
  if (act === 'adjust') renderCrop()
  if (act === 'apply-crop') recognize()
  if (act === 'edit') { f.editing = true; renderReview(); document.getElementById('no-input')?.focus() }
  if (act === 'save-no') saveNumber()
  if (act === 'sync') sync()
  if (act === 'submit') submit()
})
$overlay.addEventListener('keydown', e => { if (e.key === 'Enter' && e.target.id === 'no-input') saveNumber() })
$overlay.addEventListener('change', e => {
  const k = e.target.dataset?.field
  if (!k || !state.flow) return
  state.flow[k] = e.target.value
  if (k === 'country') { state.flow.sync = null; state.flow.confirmedMismatch = false; renderReview() }
})
function saveNumber() {
  const f = state.flow
  const v = (document.getElementById('no-input')?.value || '').replace(/\s+/g, '')
  if (!v) { toast('请输入运单号'); return }
  if (v !== f.waybill || f.source !== 'manual') { f.waybill = v; f.source = 'manual'; f.sync = null; f.confirmedMismatch = false }
  f.editing = false
  renderReview()
}

document.addEventListener('keydown', e => {
  if (e.key !== 'Escape') return
  if (sheetEls) closeSheet()
  else if (viewerEl) closeViewer()
  else if (state.flow) closeScreen()
})

$scenario.addEventListener('change', () => {
  state.scenario = $scenario.value
  closeSheet(true)
  if (state.flow) closeScreen()
  state.nextId = null
  renderList()
})

renderList()
