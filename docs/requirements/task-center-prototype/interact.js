/* 交互层：快速建任务浮层、页内确认框、toast、筛选、视图切换、看板拖拽 */

/* ── toast（带撤销） ── */
let toastTimer
window.toast = function (msg, undo) {
  const el = $('#toast')
  el.innerHTML = esc(msg) + (undo ? '<a data-undo>撤销</a>' : '')
  el.onclick = (e) => { if (e.target.dataset.undo !== undefined && undo) { undo(); el.hidden = true } }
  el.hidden = false; el.classList.add('is-enter')
  requestAnimationFrame(() => el.classList.remove('is-enter'))
  clearTimeout(toastTimer)
  toastTimer = setTimeout(() => { el.classList.add('is-enter'); setTimeout(() => { el.hidden = true }, 180) }, undo ? 5000 : 2400)
}

/* ── 页内确认/输入框（替代 confirm/prompt） ── */
window.ask = function ({ title, body = '', input = false, value = '', placeholder = '', ok = '确定', danger = false }) {
  return new Promise((resolve) => {
    const wrap = document.createElement('div')
    wrap.className = 'ask-scrim'
    wrap.innerHTML = `<div class="ask" role="alertdialog" aria-label="${esc(title)}">
      <b>${esc(title)}</b>${body ? `<p>${esc(body)}</p>` : ''}
      ${input ? `<textarea rows="2" placeholder="${esc(placeholder)}">${esc(value)}</textarea>` : ''}
      <div class="ask-actions"><button class="btn btn-ghost btn-sm" data-r="0">取消</button>
      <button class="btn ${danger ? 'btn-danger-ghost' : 'btn-primary'} btn-sm" data-r="1">${esc(ok)}</button></div></div>`
    document.body.appendChild(wrap)
    const ta = $('textarea', wrap)
    ;(ta || $('[data-r="1"]', wrap)).focus()
    const done = (yes) => {
      if (yes && input && !ta.value.trim()) { ta.focus(); ta.classList.add('is-err'); return }
      wrap.remove(); resolve(yes ? (input ? ta.value.trim() : true) : null)
    }
    wrap.addEventListener('click', (e) => { if (e.target === wrap) done(false); if (e.target.dataset.r) done(e.target.dataset.r === '1') })
    wrap.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') { e.stopPropagation(); done(false) }
      if (e.key === 'Enter' && (!input || e.ctrlKey || e.metaKey)) { e.preventDefault(); done(true) }
    })
  })
}

/* ── 快速建任务浮层 ── */
const Q = { mod: null, parent: null, draft: null, anchor: null }
const DRAFTS = [
  { match: /汇率|结汇/, title: '结汇顾问：汇率波动提醒阈值可配置', prio: 'P2', acceptance: ['阈值在后台可配', '超阈值推钉钉', '历史提醒可查'] },
  { match: /慢|卡|性能/, title: '列表加载慢：分页查询加索引并压到 1 秒内', prio: 'P1', acceptance: ['首屏接口 P95 < 1s', 'EXPLAIN 走索引', '回归测试不变'] },
]
function guessDraft(text) {
  const hit = DRAFTS.find((d) => d.match.test(text))
  const base = hit || { title: text.replace(/[。！!]+$/, '').slice(0, 40), prio: /紧急|马上|今天|老板/.test(text) ? 'P0' : 'P2', acceptance: ['功能按描述可用', '补一条回归测试', '文档同步'] }
  const mod = Q.mod || 'custom.research'
  const dup = TASKS.find((t) => t.mod === mod && !CLOSED.has(t.status) && t.id !== Q.parent && text.split('').filter((c) => t.title.includes(c)).length > 6)
  const parent = Q.parent ?? TASKS.find((t) => t.mod === mod && !t.parent && !CLOSED.has(t.status))?.id ?? null
  return { ...base, mod, parent, dup: dup?.id || null, due: base.prio === 'P0' ? TODAY : '' }
}

function quickHtml() {
  const m = MODS[Q.mod], d = Q.draft
  const modOpts = Object.values(MODS).map((x) => `<option value="${x.key}" ${d && x.key === d.mod ? 'selected' : ''}>${x.group} · ${x.title}</option>`).join('')
  const parentOpts = `<option value="">（顶层任务）</option>` + TASKS.filter((t) => !CLOSED.has(t.status)).map((t) => `<option value="${t.id}" ${d && d.parent === t.id ? 'selected' : ''}>T-${t.id} ${esc(t.title)}</option>`).join('')
  return `<div class="quick-head"><b>${Q.parent ? '加子任务' : '记任务'}</b>
      ${m ? `<span class="mod-pill">${esc(m.group)} · ${esc(m.title)}<button data-q="unmod" aria-label="取消模块">×</button></span>` : '<span class="mod-pill" style="opacity:.7">AI 自动识别模块</span>'}
      <button class="x" data-q="close" aria-label="关闭">×</button></div>
    <textarea id="qText" placeholder="一句话说清要做什么，例如：回款列表按业务员筛选时很慢，明天前搞定">${esc(Q.text || '')}</textarea>
    ${Q.loading ? '<div class="thinking"><span class="ai-dot">AI</span>正在补全标题、重要性和验收标准<span class="shimmer"></span></div>' : ''}
    ${d ? `<div class="draft">
      ${d.dup ? `<div class="dup">可能和 <a data-open="${d.dup}">T-${d.dup} ${esc(byId(d.dup).title)}</a> 重复，确认是新任务再创建</div>` : ''}
      <div><div class="lbl">标题</div><input id="dTitle" value="${esc(d.title)}"></div>
      <div class="grid2"><div><div class="lbl">重要性</div><select id="dPrio">${Object.entries(PRIO).map(([p, l]) => `<option value="${p}" ${p === d.prio ? 'selected' : ''}>${p} ${l}</option>`).join('')}</select></div>
        <div><div class="lbl">截止</div><input id="dDue" type="date" value="${d.due}"></div></div>
      <div class="grid2"><div><div class="lbl">关联模块</div><select id="dMod">${modOpts}</select></div>
        <div><div class="lbl">父任务</div><select id="dParent">${parentOpts}</select></div></div>
      <div><div class="lbl">验收标准（AI 草拟，可改）</div><ul>${d.acceptance.map((a) => `<li>${esc(a)}</li>`).join('')}</ul></div>
    </div>` : ''}
    <div class="quick-actions"><span class="kbd"><kbd>Ctrl</kbd> + <kbd>Enter</kbd> ${d ? '创建' : 'AI 补全'} · <kbd>Esc</kbd> 关闭</span>
      ${d ? '<button class="btn btn-ghost btn-sm" data-q="redo">重新补全</button><button class="btn btn-primary btn-sm" data-q="create">创建任务</button>'
        : '<button class="btn btn-ghost btn-sm" data-q="raw">直接创建</button><button class="btn btn-primary btn-sm" data-q="ai" ' + (Q.loading ? 'disabled' : '') + '>AI 补全</button>'}</div>`
}

function paintQuick(first) {
  const el = $('#quick')
  el.innerHTML = quickHtml()
  const ta = $('#qText')
  ta.oninput = () => { Q.text = ta.value }
  if (first) {
    const r = Q.anchor.getBoundingClientRect(), W = 420, H = 460
    const inSidebar = !!Q.anchor.closest('.aside')
    let left = inSidebar ? r.right + 10 : r.right - W, top = inSidebar ? r.top - 8 : r.bottom + 8
    left = Math.max(12, Math.min(left, innerWidth - W - 12)); top = Math.max(12, Math.min(top, innerHeight - H - 12))
    el.style.left = left + 'px'; el.style.top = top + 'px'
    el.style.setProperty('--origin', inSidebar ? 'left top' : 'right top')
    el.hidden = false; el.classList.add('is-enter')
    requestAnimationFrame(() => requestAnimationFrame(() => el.classList.remove('is-enter')))
  }
  if (!Q.draft) { ta.focus(); ta.setSelectionRange(ta.value.length, ta.value.length) }
}

window.openQuick = function (anchor, mod = null, parent = null) {
  Object.assign(Q, { anchor, mod, parent, draft: null, text: '', loading: false })
  if (parent) Q.mod = byId(parent).mod
  paintQuick(true)
}
function closeQuick() { const el = $('#quick'); if (el.hidden) return; el.classList.add('is-enter'); setTimeout(() => { el.hidden = true }, 150); Q.anchor?.focus?.() }

function runAI() {
  if (!Q.text?.trim()) { $('#qText').focus(); return toast('先写一句话') }
  Q.loading = true; Q.draft = null; paintQuick()
  setTimeout(() => { Q.loading = false; Q.draft = guessDraft(Q.text); paintQuick() }, 900)
}
function createTask(raw) {
  const text = Q.text?.trim(); if (!text) { $('#qText').focus(); return toast('先写一句话') }
  const id = Math.max(...TASKS.map((t) => t.id)) + 1
  const d = raw ? { title: text.slice(0, 60), prio: 'P2', mod: Q.mod || 'custom.research', parent: Q.parent, due: '', acceptance: null }
    : { ...Q.draft, title: $('#dTitle').value, prio: $('#dPrio').value, due: $('#dDue').value, mod: $('#dMod').value, parent: $('#dParent').value ? +$('#dParent').value : null }
  TASKS.push({ id, parent: d.parent, title: d.title, prio: d.prio, status: 'todo', mod: d.mod, due: d.due || null, acceptance: d.acceptance })
  if (d.parent) S.open.add(d.parent)
  S.flash = id; closeQuick(); setView('tree'); renderAll()
  toast(`已创建 T-${id}`, () => { TASKS.splice(TASKS.findIndex((t) => t.id === id), 1); renderAll() })
}

$('#quick').addEventListener('click', (e) => {
  const a = e.target.closest('[data-q]')?.dataset.q
  const o = e.target.closest('[data-open]')
  if (o) { closeQuick(); return openDrawer(+o.dataset.open) }
  if (a === 'close') closeQuick()
  if (a === 'unmod') { Q.mod = null; if (Q.draft) Q.draft.mod = 'custom.research'; paintQuick() }
  if (a === 'ai' || a === 'redo') runAI()
  if (a === 'raw') createTask(true)
  if (a === 'create') createTask(false)
})
$('#quick').addEventListener('keydown', (e) => {
  if (e.key === 'Escape') { e.stopPropagation(); closeQuick() }
  if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); Q.draft ? createTask(false) : runAI() }
})
document.addEventListener('mousedown', (e) => {
  const q = $('#quick')
  if (!q.hidden && !q.contains(e.target) && !e.target.closest('[data-quick],#headerQuick,#newTask,[data-child],.ask-scrim')) closeQuick()
})

/* ── 抽屉内 prompt/confirm 换成 ask() ── */
const _drawerAction = window.drawerAction
window.drawerAction = async function (act, el) {
  const t = byId(S.selected); if (!t) return
  if (act === 'confirm') {
    const open = kids(t.id).filter((c) => !CLOSED.has(c.status))
    if (open.length && !(await ask({ title: `还有 ${open.length} 个子任务没结束`, body: '父任务标记完成后，子任务保持原状态不变。', ok: '仍然完成' }))) return
    const prev = t.status; t.status = 'done'
    toast(`T-${t.id} 已完成`, () => { t.status = prev; openDrawer(t.id) }); return openDrawer(t.id)
  }
  if (act === 'reject') {
    const r = await ask({ title: `驳回 T-${t.id} 的完成提议`, body: '理由写入时间线，AI 下次提议会参考。', input: true, value: '列表页按操作人筛选还没做', ok: '驳回' })
    if (r === null) return
    t.status = 'doing'; toast(`已驳回，T-${t.id} 回到进行中`); return openDrawer(t.id)
  }
  return _drawerAction(act, el)
}
window.drawerField = async function (field, value) {
  const t = byId(S.selected); if (!t) return
  if (field === 'status' && value === 'done') return drawerAction('confirm')
  if (field === 'status' && value === 'blocked') {
    const r = await ask({ title: '受阻原因（必填）', input: true, placeholder: '例如：等财务给 9 月汇率口径', ok: '标记受阻' })
    if (!r) return openDrawer(t.id); t.blocked = r
  }
  t[field] = value; toast('已保存'); openDrawer(t.id)
}

/* ── 视图、筛选 ── */
function setView(v) {
  S.view = v
  document.querySelectorAll('#viewSeg button').forEach((b) => b.classList.toggle('is-on', b.dataset.view === v))
  $('#viewTree').hidden = v !== 'tree'; $('#viewBoard').hidden = v !== 'board'; $('#viewMap').hidden = v !== 'map'
  renderAll()
}
$('#viewSeg').addEventListener('click', (e) => { const v = e.target.dataset.view; if (v) setView(v) })
$('#fModule').innerHTML = '<option value="">全部模块</option>' + Object.values(MODS).map((m) => `<option value="${m.key}">${m.group} · ${m.title}</option>`).join('')
$('#fModule').onchange = (e) => { S.mod = e.target.value; renderAll() }
$('#fPriority').innerHTML = Object.keys(PRIO).map((p) => `<button class="chip" data-p="${p}">${p}</button>`).join('')
$('#fPriority').onclick = (e) => { const p = e.target.dataset.p; if (!p) return; S.prios.has(p) ? S.prios.delete(p) : S.prios.add(p); e.target.classList.toggle('is-on'); renderAll() }
$('#search').oninput = (e) => { S.q = e.target.value; renderAll() }
$('#fHideDone').onchange = (e) => { S.hideDone = e.target.checked; renderAll() }

/* ── 全局点击委托 ── */
document.addEventListener('click', (e) => {
  const t = e.target
  const quick = t.closest('[data-quick]'); if (quick) { e.stopPropagation(); return openQuick(quick, quick.dataset.quick) }
  if (t.closest('#headerQuick')) return openQuick($('#headerQuick'), 'task.center')
  if (t.closest('#newTask')) return openQuick($('#newTask'), S.mod || null)
  const child = t.closest('[data-child]'); if (child) { e.stopPropagation(); return openQuick(child, null, +child.dataset.child) }
  const tog = t.closest('[data-toggle]'); if (tog) { const id = +tog.dataset.toggle; S.open.has(id) ? S.open.delete(id) : S.open.add(id); return renderAll() }
  const act = t.closest('#drawer [data-act]'); if (act) return drawerAction(act.dataset.act, act)
  const map = t.closest('[data-map]'); if (map) { S.mod = map.dataset.map; $('#fModule').value = S.mod; return setView('tree') }
  const navItem = t.closest('.nav-item'); if (navItem && !t.closest('.nav-add')) { S.mod = navItem.dataset.mod; $('#fModule').value = S.mod; return setView('tree') }
  if (t.closest('#quick,.ask-scrim')) return
  const open = t.closest('[data-open]'); if (open) return openDrawer(+open.dataset.open)
})
$('#scrim').addEventListener('click', closeDrawer)
$('#drawer').addEventListener('change', (e) => { const f = e.target.dataset.field; if (f) drawerField(f, e.target.value) })
document.addEventListener('keydown', (e) => {
  if (document.querySelector('.ask-scrim')) return
  if (e.key === 'Escape') { if (!$('#quick').hidden) return closeQuick(); return closeDrawer() }
  const typing = /INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)
  if (!typing && (e.key === 'n' || e.key === 'N')) { e.preventDefault(); openQuick($('#newTask'), S.mod || null) }
})

/* ── 看板拖拽：拖到「已完成」同样要人确认 ── */
let dragId = null
document.addEventListener('dragstart', (e) => { const c = e.target.closest?.('[data-drag]'); if (!c) return; dragId = +c.dataset.drag; c.classList.add('is-drag') })
document.addEventListener('dragend', (e) => { e.target.closest?.('[data-drag]')?.classList.remove('is-drag'); document.querySelectorAll('.col.is-over').forEach((c) => c.classList.remove('is-over')) })
document.addEventListener('dragover', (e) => { const col = e.target.closest('.col'); if (!col || !dragId) return; e.preventDefault(); document.querySelectorAll('.col').forEach((c) => c.classList.toggle('is-over', c === col)) })
document.addEventListener('drop', async (e) => {
  const col = e.target.closest('.col'); if (!col || !dragId) return
  e.preventDefault(); const t = byId(dragId), to = col.dataset.col; dragId = null
  col.classList.remove('is-over')
  if (!t || t.status === to) return
  if (to === 'pending') return toast('「待确认」只能由 AI 根据 git 证据提议，不能手动拖入')
  if (to === 'blocked') { const r = await ask({ title: `T-${t.id} 受阻原因（必填）`, input: true, ok: '标记受阻' }); if (!r) return; t.blocked = r }
  if (to === 'done' && !(await ask({ title: `确认 T-${t.id} 已完成？`, body: t.title, ok: '确认完成' }))) return
  const prev = t.status; t.status = to; renderAll()
  toast(`T-${t.id} → ${STATUS[to][0]}`, () => { t.status = prev; renderAll() })
})

renderAll()
