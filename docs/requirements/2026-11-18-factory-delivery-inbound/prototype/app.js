import { drafts, reviewGroups, desktopRows } from './data.js'

const $ = (sel, el = document) => el.querySelector(sel)
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]))
const icon = {
  back: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M15 18l-6-6 6-6"/></svg>',
  close: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg>',
  camera: '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M4 8h3l2-3h6l2 3h3v11H4z"/><circle cx="12" cy="13" r="3.5"/></svg>',
  doc: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M6 3h9l3 3v15H6z"/><path d="M9 9h6M9 13h6M9 17h4"/></svg>',
  ok: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M5 12l5 5 9-10"/></svg>',
  wait: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>',
  warn: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 4l9 16H3z"/><path d="M12 10v4M12 17v.5"/></svg>',
}

const freshGroups = () => {
  const gs = reviewGroups()
  gs.forEach(g => g.lines.forEach(l => { l.selected = l.status === 'matched'; l.batch = null }))
  return gs
}

const state = {
  view: 'mobile',
  screen: 'drafts',      // drafts | scan | recognizing | review | result
  lastScreen: '',
  photo: '',             // 本次拍到的校正图（仅内存）
  groups: freshGroups(),
  batches: 0,
  resultMode: 'synced',  // synced | sending | uncertain
  scanner: null,
}

/* ── 外壳 ─────────────────────────────────── */
function renderShell() {
  document.querySelectorAll('[data-view-btn]').forEach(b => b.setAttribute('aria-pressed', b.dataset.viewBtn === state.view))
  const stage = $('#stage')
  stage.dataset.view = state.view
  if (state.view === 'desktop') { renderDesktop(stage); return }
  stage.innerHTML = '<div class="phone" id="phone"></div>'
  state.lastScreen = ''
  renderPhone()
}

function go(screen) {
  if (state.scanner && screen !== 'scan') { state.scanner.destroy(); state.scanner = null }
  state.screen = screen
  renderPhone()
}

function renderPhone() {
  const phone = $('#phone'); if (!phone) return
  const s = state.screen
  if (s === 'scan') { state.lastScreen = s; phone.innerHTML = '<div id="scan-root" style="display:contents"></div>'; startScanner(); return }
  phone.innerHTML = { drafts: draftsHtml, recognizing: recognizingHtml, review: reviewHtml, result: resultHtml }[s]()
  if (state.lastScreen !== s) phone.firstElementChild?.classList.add('enter')  // 只在换屏时淡入
  state.lastScreen = s
  if (s === 'review') bindReview()
}

async function startScanner() {
  const root = $('#scan-root')
  try {
    const { mountScanner } = await import('./scanner.js')
    state.scanner = mountScanner(root, {
      onCaptured: ({ url }) => { state.photo = url; state.groups = freshGroups(); state.batches = 0; go('recognizing'); fakeRecognition() },
      onCancel: () => go('drafts'),
    })
  } catch (e) {
    root.innerHTML = `<div class="scan screen"><div class="scan-body"><div class="scan-empty">
      <p>扫描模块加载失败。请在仓库根目录启动静态服务后再打开本原型（见设计开发文档开头）。</p>
      <button class="btn btn-primary" id="skip-scan">跳过拍照，看示例识别结果</button></div></div></div>`
    $('#skip-scan').onclick = () => { go('recognizing'); fakeRecognition() }
    console.error(e)
  }
}

function fakeRecognition() {
  setTimeout(() => { if (state.screen === 'recognizing') go('review') }, 2600)
}

/* ── 草稿首页 ─────────────────────────────── */
function draftsHtml() {
  return `<div class="screen">
    <header class="appbar"><h2>工厂到货入库<span class="sub">鄄城工厂 · 送(销)货单</span></h2></header>
    <div class="scroll">
      <div class="card hero-action">
        <p>拍一张送货单，识别后逐行核对，确认即入库。</p>
        <button class="btn btn-primary btn-lg btn-block" data-go="scan">${icon.camera}拍新单</button>
      </div>
      <p class="section-label">我的草稿</p>
      ${drafts.map(d => `
        <button class="draft" data-draft="${d.state}">
          <strong class="num">${d.delivery}</strong>
          <span class="tag ${d.state === 'review' ? 'tag-warning' : d.state === 'recognizing' ? 'tag-info' : 'tag-gold'}">${d.label}</span>
          <span class="num">${d.inbound} · 单据日期 ${d.date}</span>
        </button>`).join('')}
    </div>
  </div>`
}

/* ── 识别中 ───────────────────────────────── */
function recognizingHtml() {
  return `<div class="screen">
    <header class="appbar"><button class="icon-btn" data-go="drafts" aria-label="返回">${icon.back}</button><h2>正在识别<span class="sub">FI20261118-003</span></h2></header>
    <div class="scroll" aria-busy="true">
      <div class="card doc-head">
        <div class="thumb">${state.photo ? `<img src="${state.photo}" alt="">` : icon.doc}</div>
        <div class="doc-meta"><div class="skeleton" style="height:18px;width:60%"></div><div class="skeleton" style="height:12px;width:80%"></div></div>
      </div>
      ${[0, 1, 2].map(() => `<div class="card" style="padding:14px;display:grid;gap:10px">
        <div class="skeleton" style="height:14px;width:40%"></div>
        <div class="skeleton" style="height:12px;width:90%"></div>
        <div class="skeleton" style="height:12px;width:75%"></div></div>`).join('')}
      <p class="wait-note" role="status">一般需要 20–60 秒。可以先离开，稍后在「我的草稿」继续。</p>
    </div>
  </div>`
}

/* ── 核对页 ───────────────────────────────── */
const allLines = () => state.groups.flatMap(g => g.lines)
const openLines = () => allLines().filter(l => !l.batch)
const pickable = l => l.status === 'matched' && !l.batch

function counts() {
  const ls = openLines()
  const c = { matched: 0, choose: 0, decide: 0, blocked: 0, skipped: 0 }
  ls.forEach(l => c[l.status]++)
  const sel = ls.filter(l => pickable(l) && l.selected)
  return { ...c, pending: c.choose + c.decide, selLines: sel.length, selQty: sel.reduce((a, l) => a + l.qty, 0) }
}

function targetNote(l) {
  const t = l.target; if (!t) return ''
  if (t.kind === 'po') return `回写${t.label} · 可分配 ${t.open} → ${t.open - l.qty}`
  if (t.kind === 'invoice') return l.qty > t.open
    ? `对应${t.label}，超出发票数量 ${l.qty - t.open} 件，超出部分只入库`
    : `对应${t.label} · 发票余量 ${t.open} → ${t.open - l.qty}`
  return t.label
}

function lineHtml(l) {
  const tag = { matched: ['tag-success', '已匹配'], choose: ['tag-warning', l.ruleConfirm ? '待确认' : '待选择'], decide: ['tag-warning', '待选择'], blocked: ['tag-danger', '无法入库'], skipped: ['tag', '不入库'] }[l.status]
  const noteCls = l.status === 'matched' ? '' : l.status === 'blocked' ? 'danger' : 'warn'
  const note = l.status === 'matched' ? targetNote(l) : l.why
  const chooseLabel = l.status === 'decide' ? '选择订单' : l.ruleConfirm ? '确认换算' : '选择产品'
  return `<div class="line" data-status="${l.status}" data-line="${l.id}">
    <span class="line-bar" aria-hidden="true"></span>
    <div class="line-main">
      <span class="line-raw">${esc(l.raw)}</span>
      <span class="line-spec">${esc(l.spec)}</span>
      ${note ? `<span class="line-note ${noteCls}">${esc(note)}</span>` : ''}
      ${l.inherited ? `<span class="line-note">${esc(l.inherited)}</span>` : ''}
      ${l.rule ? `<span class="line-note">${esc(l.rule)}</span>` : ''}
      ${l.status !== 'skipped' ? `<div class="line-actions">
        ${l.status === 'choose' || l.status === 'decide' ? `<button class="chip-btn primary" data-choose="${l.id}">${chooseLabel}</button>` : ''}
        ${l.edit ? `<button class="chip-btn" data-edit="${l.id}">修改识别值</button>` : ''}
        ${pickable(l) ? `<label class="switch"><input type="checkbox" data-sel="${l.id}" ${l.selected ? 'checked' : ''}>本次入库</label>` : ''}
      </div>` : ''}
    </div>
    <div class="line-side">
      ${l.qty ? `<span class="qty">${l.qty}<small>${l.unit}</small></span>` : ''}
      <span class="tag ${tag[0]}">${tag[1]}</span>
    </div>
  </div>`
}

function groupTag(g) {
  const ls = g.lines.filter(l => !l.batch)
  const t = g.multi && !ls.some(l => l.status === 'decide') ? ['tag-info', '已选订单'] : g.tag
  return `<span class="tag ${t[0]}">${t[1]}</span>`
}

function reviewHtml() {
  const c = counts()
  const done = allLines().filter(l => l.batch)
  return `<div class="screen" id="review">
    <header class="appbar"><button class="icon-btn" data-go="drafts" aria-label="返回">${icon.back}</button>
      <h2>核对送货单<span class="sub num">FI20261118-003 · 工厂单据 7085384</span></h2></header>
    <div class="scroll">
      <div class="card doc-head">
        <button class="thumb" data-zoom aria-label="查看原图">${state.photo ? `<img src="${state.photo}" alt="">` : icon.doc}</button>
        <div class="doc-meta">
          <strong class="num">7085384 · 11 月 11 日</strong>
          <div class="stats">
            <span class="tag tag-success">已匹配 ${c.matched}</span>
            <span class="tag tag-warning">待处理 ${c.pending}</span>
            <span class="tag tag-danger">无法入库 ${c.blocked}</span>
            <span class="tag">不入库 ${c.skipped}</span>
          </div>
        </div>
      </div>
      ${done.length ? `<details class="card group"><summary class="group-head" style="cursor:pointer"><strong>已入库 ${done.length} 行</strong><span class="tag tag-success">批次 1</span><span class="sub">已提交的行只读，不能再次入库</span></summary>
        ${done.map(l => `<div class="line" data-status="matched"><span class="line-bar"></span><div class="line-main"><span class="line-spec">${esc(l.spec)}</span></div><div class="line-side"><span class="qty">${l.qty}<small>${l.unit}</small></span></div></div>`).join('')}</details>` : ''}
      ${state.groups.map(g => {
        const ls = g.lines.filter(l => !l.batch); if (!ls.length) return ''
        return `<section class="card group" aria-label="${esc(g.title)}">
          <div class="group-head"><strong>${esc(g.title)}</strong>${groupTag(g)}<span class="sub">${esc(g.sub)}</span></div>
          ${ls.map(lineHtml).join('')}
        </section>`
      }).join('')}
    </div>
    <div class="footer">
      <div class="submit-row">
        <div class="summary">已勾选 <strong class="num">${c.selLines} 行 · ${c.selQty.toLocaleString()}</strong>
          ${c.pending ? `<br><button class="pending-hint" data-jump>还有 ${c.pending} 行待处理</button>` : ''}</div>
        <button class="btn btn-primary btn-lg" data-submit ${c.selLines ? '' : 'disabled'}>确认入库</button>
      </div>
      ${c.blocked || c.pending ? `<span class="line-note" style="justify-content:center">未勾选的行留在本单，处理后可补录</span>` : ''}
    </div>
    <div id="sheet-root"></div>
  </div>`
}

const findLine = id => allLines().find(l => l.id === id)

function bindReview() {
  const root = $('#review')
  root.addEventListener('click', e => {
    const t = e.target
    const choose = t.closest('[data-choose]'); if (choose) return openChooseSheet(findLine(choose.dataset.choose))
    const edit = t.closest('[data-edit]'); if (edit) return openEditSheet(findLine(edit.dataset.edit))
    if (t.closest('[data-zoom]')) return openLightbox()
    if (t.closest('[data-jump]')) {
      const first = root.querySelector('.line[data-status="choose"], .line[data-status="decide"]')
      first?.scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'center' })
      first?.querySelector('button')?.focus({ preventScroll: true })
      return
    }
    const submit = t.closest('[data-submit]'); if (submit && !submit.disabled) return openSummarySheet()
  })
  root.addEventListener('change', e => {
    const sel = e.target.closest('[data-sel]'); if (!sel) return
    findLine(sel.dataset.sel).selected = sel.checked
    rerenderKeepScroll()
  })
}

function rerenderKeepScroll(focusLine) {
  const top = $('#review .scroll')?.scrollTop ?? 0
  renderPhone()
  const sc = $('#review .scroll'); if (sc) sc.scrollTop = top
  if (focusLine) $(`[data-line="${focusLine}"] button`)?.focus({ preventScroll: true })
}

/* 底部抽屉：先渲染关闭态，下一帧加 class，过渡可被打断重定向 */
function openSheet(inner, onMount) {
  const root = $('#sheet-root'); const review = $('#review')
  const opener = document.activeElement
  root.innerHTML = `<div class="sheet-backdrop" data-close></div>
    <div class="sheet" role="dialog" aria-modal="true"><div class="sheet-grip" aria-hidden="true"></div>${inner}</div>`
  requestAnimationFrame(() => requestAnimationFrame(() => review.classList.add('sheet-open')))
  const onKey = e => { if (e.key === 'Escape') close() }
  const close = (after) => {
    review.classList.remove('sheet-open')
    document.removeEventListener('keydown', onKey)
    setTimeout(() => { root.innerHTML = ''; if (typeof after === 'function') after(); else opener?.focus?.() }, 180)
  }
  document.addEventListener('keydown', onKey)
  root.querySelectorAll('[data-close]').forEach(el => el.addEventListener('click', () => close()))
  setTimeout(() => root.querySelector('.sheet button, .sheet input')?.focus(), 60)
  onMount?.(root, close)
}

function optionHtml(c, picked) {
  return `<button class="option" role="radio" aria-checked="${picked === c.id}" data-pick="${c.id}">
    <i class="radio" aria-hidden="true"></i><strong>${esc(c.name)}</strong>
    <span>${c.meta ? esc(c.meta) : `下单 <b class="num">${c.order}</b> · 未入库 <b class="num">${c.open}</b>`}
      ${c.qtyMatch ? '<em class="tag tag-success" style="font-style:normal">数量吻合</em>' : ''}</span>
  </button>`
}

function openChooseSheet(line) {
  const isOrder = line.status === 'decide'
  const list = isOrder ? line.orders : line.candidates
  let picked = null  // 数量吻合也不预选（需求 A3），由人点选
  const title = isOrder ? '这批货对应哪张单？' : line.ruleConfirm ? '确认颜色换算' : '选择产品'
  openSheet(`
    <div class="sheet-head"><h3>${title}</h3><p>${esc(line.raw)} · <b class="num">${line.qty}${line.unit}</b></p></div>
    <div class="sheet-body" role="radiogroup">${list.map(c => optionHtml(c, picked)).join('')}
      ${line.ruleConfirm ? '<label class="switch" style="padding:4px 2px"><input type="checkbox" id="save-alias">以后「878-18」都按 #8TP8/18 处理（提交管理员审核）</label>' : ''}</div>
    <div class="sheet-foot"><button class="btn" data-close>取消</button><button class="btn btn-primary" data-ok disabled>确定</button></div>`,
  (root, close) => {
    root.querySelector('.sheet-body').addEventListener('click', e => {
      const b = e.target.closest('[data-pick]'); if (!b) return
      picked = b.dataset.pick
      root.querySelectorAll('[data-pick]').forEach(x => x.setAttribute('aria-checked', x.dataset.pick === picked))
      root.querySelector('[data-ok]').disabled = false
    })
    root.querySelector('[data-ok]').addEventListener('click', () => {
      const c = list.find(x => x.id === picked)
      if (isOrder) {
        // 选定订单后回到该订单范围内的 SKU 匹配：两个等级都有时仍要人选
        const day = c.meta.split(' · ')[0]
        line.status = 'choose'; line.why = `已选 ${day} 的单，请选择等级`
        line.candidates = line.afterOrder
        line.target = { kind: 'invoice', label: `发票生产单 1054（${day}）` }
      } else {
        line.status = 'matched'; line.spec = c.name; line.selected = true
        if (line.ruleConfirm) { line.rule = '已确认规则换算：878-18 → #8TP8/18'; line.ruleConfirm = false }
        if (line.target && c.open != null) line.target.open = c.open
      }
      close(() => rerenderKeepScroll(line.id))
    })
  })
}

function openEditSheet(line) {
  const e = line.edit
  const f = (id, label, val, mode = '') => `<div class="field"><label for="${id}">${label}</label><input id="${id}" ${mode} value="${esc(val)}"></div>`
  openSheet(`
    <div class="sheet-head"><h3>修改识别值</h3><p>改完会重新匹配和分配。原文：${esc(line.raw)}</p></div>
    <div class="sheet-body">
      <div class="fields">
        ${f('f-ref', '单号', e.ref, 'inputmode="numeric"')}
        ${f('f-grade', '等级', e.grade, 'placeholder="未写"')}
        ${f('f-len', '长度（英寸）', e.length, 'inputmode="decimal"')}
        ${f('f-w', '克重（g）', e.weight, 'inputmode="decimal"')}
        ${f('f-c', '颜色', e.color)}
        ${f('f-q', `数量（${esc(line.unit || '件')}）`, e.quantity, 'inputmode="numeric"')}
      </div>
      <span class="line-note">改单号会重新查找对应订单；改等级会重新筛选候选</span>
    </div>
    <div class="sheet-foot"><button class="btn" data-close>取消</button><button class="btn btn-primary" data-save>重新匹配</button></div>`,
  (root, close) => {
    root.querySelector('[data-save]').addEventListener('click', () => {
      const v = id => root.querySelector(id).value.trim()
      const q = parseInt(v('#f-q'), 10)
      const refChanged = v('#f-ref') !== e.ref
      Object.assign(e, { ref: v('#f-ref'), grade: v('#f-grade'), length: v('#f-len'), weight: v('#f-w'), color: v('#f-c') })
      if (q > 0) { line.qty = q; e.quantity = q }
      if (refChanged) {
        line.status = 'decide'; line.selected = false
        line.why = `单号改为 ${e.ref}，命中 1 张单，请确认订单`
        line.orders = [{ id: 'ox', name: `生产备货订单 · 编号 ${e.ref}`, meta: '示例 · 单单分配' }]
        line.afterOrder = line.candidates?.length ? line.candidates : [{ id: 'cx', name: line.spec, order: line.qty, open: line.qty }]
      } else if (line.status === 'blocked' && e.color.toUpperCase() !== 'R-I-C') {
        line.status = 'choose'; line.why = '已重新匹配，找到 2 个候选，请选择'
        line.candidates = [
          { id: 'r1', name: `Super Double Drawn Tape Hair / 18" / #${e.color} / 2.5g`, order: 40, open: 40 },
          { id: 'r2', name: `Standard Double Drawn Tape Hair / 18" / #${e.color} / 2.5g`, order: 60, open: 60 }]
      } else if (line.target?.kind === 'po' && line.target.open != null) {
        // 单单分配：超出该备货单可分配数量即标红（需求第 8 节）
        if (line.qty > line.target.open) {
          line.status = 'blocked'; line.selected = false
          line.why = `超出${line.target.label}可分配数量 ${line.qty - line.target.open} 件：请改数量，或把超出部分拆成单独一行`
        } else { line.status = 'matched'; line.selected = true }
      }
      close(() => rerenderKeepScroll(line.id))
    })
  })
}

function openSummarySheet() {
  const sel = openLines().filter(l => pickable(l) && l.selected)
  const by = k => sel.filter(l => l.target?.kind === k)
  const sum = arr => arr.reduce((a, l) => a + l.qty, 0)
  const short = l => esc(l.spec.split(' / ').slice(0, 3).join(' / '))
  const grp = (title, arr, extra = '') => arr.length ? `<div class="sum-group"><h4>${title}</h4>
    ${arr.map(l => `<div class="sum-row"><span>${short(l)}</span><b>${l.qty}${l.unit}</b></div>`).join('')}${extra}</div>` : ''
  const cross = by('cross')
  openSheet(`
    <div class="sheet-head"><h3>确认入库</h3><p>将在小满生成 1 张采购入库单，共 <b class="num">${sel.length}</b> 行、<b class="num">${sum(sel).toLocaleString()}</b> 件。回写和对应在小满同步成功后生效。</p></div>
    <div class="sheet-body">
      ${grp('回写生产备货订单', by('po'))}
      ${grp('对应订单发票生产单（不改发票）', by('invoice'))}
      ${grp('跨单回写生产备货订单', cross, '<label class="switch" style="padding-top:4px"><input type="checkbox" id="cross-ok">我已核对跨单回写的订单和数量</label>')}
      ${grp('只入库，不回写', by('none'))}
    </div>
    <div class="sheet-foot"><button class="btn" data-close>返回修改</button><button class="btn btn-primary" data-confirm ${cross.length ? 'disabled' : ''}>确认入库</button></div>`,
  (root, close) => {
    const box = root.querySelector('#cross-ok'); const btn = root.querySelector('[data-confirm]')
    box?.addEventListener('change', () => { btn.disabled = !box.checked })
    btn.addEventListener('click', () => {
      state.batches++
      sel.forEach(l => { l.batch = state.batches; l.selected = false })
      close(() => go('result'))
    })
  })
}

function openLightbox() {
  const box = document.createElement('div')
  box.className = 'lightbox'; box.setAttribute('role', 'dialog'); box.setAttribute('aria-label', '原图')
  box.innerHTML = `<header class="appbar"><h2>送货单原图</h2><button class="icon-btn" aria-label="关闭">${icon.close}</button></header>
    ${state.photo ? `<img src="${state.photo}" alt="送货单">` : '<div class="scan-empty" style="flex:1;align-content:center"><p style="color:var(--text-on-dark)">示例数据没有照片。拍一张送货单后可在这里对照。</p></div>'}`
  box.querySelector('button').onclick = () => box.remove()
  $('#phone').append(box); box.querySelector('button').focus()
}

/* ── 结果 ─────────────────────────────────── */
function resultHtml() {
  const m = state.resultMode
  const done = allLines().filter(l => l.batch === state.batches)
  const qty = done.reduce((a, l) => a + l.qty, 0)
  const left = openLines().filter(l => l.status !== 'skipped').length
  const view = {
    synced: ['ok', icon.ok, '已入库', '小满采购入库单已生成。方舟库存显示会在下次同步后更新。'],
    sending: ['wait', icon.wait, '正在同步到小满', '可以离开此页，结果会在草稿和桌面列表里更新。'],
    uncertain: ['warn', icon.warn, '结果待核对', '小满没有及时回复，可能已经入库。为避免重复入库，系统不会自动重发，已通知管理员核对。'],
  }[m]
  const ok = m === 'synced'
  const po = [...new Set(done.filter(l => l.target?.kind === 'po' || l.target?.kind === 'cross').map(l => l.target.kind === 'cross' ? '备货单 1071、942' : '备货单 983'))].join('、') || '—'
  const inv = [...new Set(done.filter(l => l.target?.kind === 'invoice').map(l => l.id === 'l7' ? '发票生产单 1054' : '发票生产单 1009'))].join('、') || '—'
  return `<div class="screen">
    <header class="appbar"><button class="icon-btn" data-go="drafts" aria-label="返回">${icon.back}</button><h2>入库结果</h2></header>
    <div class="scroll">
      <div class="card result" role="status">
        <span class="result-icon ${view[0]}">${view[1]}</span><h3>${view[2]}</h3><p>${view[3]}</p>
      </div>
      <div class="card kv">
        <div><span>方舟入库单</span><b class="num">FI20261118-003-${state.batches || 1}</b></div>
        <div><span>小满入库单</span><b class="num">${ok ? 'CGRK2611180012' : '—'}</b></div>
        <div><span>本批行数 / 件数</span><b class="num">${done.length} 行 / ${qty.toLocaleString()}</b></div>
        <div><span>回写生产备货订单</span><b>${ok ? po : '同步成功后回写'}</b></div>
        <div><span>对应发票生产单</span><b>${ok ? inv : '同步成功后生效'}</b></div>
      </div>
      <div class="seg" role="group" aria-label="原型：切换结果" style="justify-self:center">
        ${[['synced', '成功'], ['sending', '同步中'], ['uncertain', '待核对']].map(([v, l]) => `<button data-result="${v}" aria-pressed="${m === v}">${l}</button>`).join('')}
      </div>
    </div>
    <div class="footer"><button class="btn btn-primary btn-lg btn-block" data-go="drafts">完成</button>
      ${left ? `<button class="btn btn-block" data-go="review">补录剩余 ${left} 行</button>` : ''}</div>
  </div>`
}

/* ── 桌面端 ───────────────────────────────── */
function renderDesktop(stage) {
  stage.innerHTML = `<div class="desk" id="desk">
    <nav class="side" aria-label="示意导航"><b>莱莎方舟</b><span>工作台</span><span>订单管理</span><span>备货管理</span><span class="active">工厂到货入库</span><span>本地成品库存账</span><span>生产订单</span></nav>
    <main class="desk-main">
      <div class="desk-title"><h2>工厂到货入库</h2><button class="btn">维护词表</button></div>
      <div class="card filters">
        <input type="search" placeholder="入库单号 / 工厂单据编号" aria-label="搜索">
        <select aria-label="状态"><option>全部状态</option><option>待核对</option><option>部分入库</option><option>已完成</option><option>结果待核对</option></select>
        <select aria-label="同步"><option>全部同步状态</option><option>已同步</option><option>待核对</option><option>失败</option></select>
        <input type="date" aria-label="日期" value="2026-11-18">
      </div>
      <div class="card table-card">
        <table><thead><tr><th>入库单号</th><th>工厂单据</th><th>创建时间</th><th>操作人</th><th>行数</th><th>件数</th><th>状态</th><th>小满同步</th></tr></thead>
        <tbody>${desktopRows.map((r, i) => `<tr data-row="${i}" tabindex="0"><td class="num">${r.inbound}</td><td class="num">${r.delivery}</td><td class="num">${r.date}</td><td>${r.who}</td><td class="num">${r.lines}</td><td class="num">${r.qty.toLocaleString()}</td><td><span class="tag ${r.status[0]}">${r.status[1]}</span></td><td>${r.sync}</td></tr>`).join('')}</tbody></table>
      </div>
    </main>
    <div class="drawer-backdrop" data-dclose></div>
    <aside class="drawer" role="dialog" aria-modal="true" aria-label="入库单详情" id="drawer"></aside>
  </div>`
  const desk = $('#desk')
  const open = i => {
    const r = desktopRows[i]
    const uncertain = r.sync === '待核对'
    $('#drawer').innerHTML = `
      <div class="drawer-head"><h3 class="num">${r.inbound} · 工厂单据 ${r.delivery}</h3><span class="tag ${r.status[0]}">${r.status[1]}</span><button class="icon-btn" data-dclose aria-label="关闭">${icon.close}</button></div>
      <div class="drawer-body">
        <div style="display:flex;flex-wrap:wrap;gap:8px" aria-label="管理员操作">
          ${uncertain ? '<button class="btn btn-primary">核清：小满已建，补记单号</button><button class="btn">核清：确认未建，重新发送</button>' : ''}
          <button class="btn">改分配</button>
          <button class="btn">作废未提交行</button>
          <button class="btn">登记更正</button>
        </div>
        <div class="compare">
          <div class="imgbox">${state.photo ? `<img src="${state.photo}" alt="校正后的送货单">` : '校正图 / 原图对照<br>（拍照后显示）'}</div>
          <div class="card" style="overflow:auto"><table class="mini-table"><thead><tr><th>识别原文</th><th>确认产品</th><th>数量</th><th>对应</th></tr></thead><tbody>
            ${allLines().filter(l => l.status !== 'skipped').map(l => `<tr><td>${esc(l.raw)}</td><td>${esc(l.spec.split(' / ').slice(0, 3).join(' / '))}</td><td class="num">${l.qty}${l.unit}</td><td>${l.status === 'matched' ? ({ po: '备货单', invoice: '发票', cross: '跨单', none: '只入库' }[l.target?.kind] || '—') : `<span class="tag ${l.status === 'blocked' ? 'tag-danger' : 'tag-warning'}">${l.status === 'blocked' ? '无法入库' : '待选择'}</span>`}</td></tr>`).join('')}
          </tbody></table></div>
        </div>
        <div class="card" style="padding:14px 16px;display:grid;gap:10px"><h4 style="margin:0;font-family:var(--font-display)">批次与同步</h4>
          <div class="timeline">
            <div><span>11-18 10:42:05</span>王 上传照片，识别完成（38 秒）</div>
            <div><span>11-18 10:49:31</span>王 确认批次 1：8 行 / 1,330 件</div>
            ${uncertain ? '<div><span>11-18 10:49:45</span>小满请求超时，结果待核对；系统未重发</div>'
              : '<div><span>11-18 10:49:33</span>小满采购入库单 CGRK2611180012 已生成，回读一致</div><div><span>11-18 10:49:34</span>回写备货单 983、1071、942；对应发票生产单 1009</div>'}
          </div>
        </div>
      </div>`
    desk.classList.add('drawer-open'); $('#drawer [data-dclose]').focus()
  }
  desk.addEventListener('click', e => {
    const tr = e.target.closest('tr[data-row]'); if (tr) open(+tr.dataset.row)
    if (e.target.closest('[data-dclose]')) desk.classList.remove('drawer-open')
  })
  desk.addEventListener('keydown', e => {
    const tr = e.target.closest('tr[data-row]'); if (tr && e.key === 'Enter') open(+tr.dataset.row)
    if (e.key === 'Escape') desk.classList.remove('drawer-open')
  })
}

/* ── 全局事件 ─────────────────────────────── */
document.addEventListener('click', e => {
  const v = e.target.closest('[data-view-btn]'); if (v) { state.view = v.dataset.viewBtn; renderShell(); return }
  const g = e.target.closest('[data-go]'); if (g) { go(g.dataset.go); return }
  const d = e.target.closest('[data-draft]')
  if (d) {
    if (d.dataset.draft === 'recognizing') { go('recognizing'); fakeRecognition(); return }
    state.groups = freshGroups(); state.batches = 0
    if (d.dataset.draft === 'partial') {  // 演示：已入库一批、剩余待补录
      state.batches = 1; allLines().filter(l => l.status === 'matched').forEach(l => { l.batch = 1; l.selected = false })
    }
    go(d.dataset.draft === 'partial' ? 'result' : 'review'); return
  }
  const r = e.target.closest('[data-result]'); if (r) { state.resultMode = r.dataset.result; renderPhone() }
})

renderShell()
