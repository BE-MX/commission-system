/* 渲染层：侧栏、统计、简报、树形、看板、模块地图 */
const $ = (s, el = document) => el.querySelector(s)
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]))
const CLOSED = new Set(['done', 'shelved'])

window.MODS = {}
NAV.forEach((g) => g.items.forEach(([k, t]) => { MODS[k] = { key: k, title: t, group: g.title, kind: 'nav' } }))
EXTRA_MODULES.forEach((m) => { MODS[m.key] = m })

window.S = { view: 'tree', selected: null, open: new Set([118, 130, 150]), q: '', mod: '', prios: new Set(), hideDone: true, flash: null }

const byId = (id) => TASKS.find((t) => t.id === id)
const kids = (id) => TASKS.filter((t) => t.parent === id)
const PR = { P0: 0, P1: 1, P2: 2, P3: 3 }
const sortTasks = (list) => list.sort((a, b) => PR[a.prio] - PR[b.prio] || (a.due || '9').localeCompare(b.due || '9'))
function leaves(t) { const k = kids(t.id); return k.length ? k.flatMap(leaves) : [t] }
function progress(t) { const l = leaves(t); return [l.filter((x) => CLOSED.has(x.status)).length, l.length] }
function selfMatch(t) {
  const q = S.q.trim().toLowerCase()
  if (q && !(`t-${t.id}`.includes(q) || t.title.toLowerCase().includes(q))) return false
  if (S.mod && t.mod !== S.mod) return false
  if (S.prios.size && !S.prios.has(t.prio)) return false
  return !(S.hideDone && CLOSED.has(t.status))
}
function visible(t) { return selfMatch(t) || kids(t.id).some(visible) }
const statusTag = (s) => `<span class="status ${STATUS[s][1]}">${STATUS[s][0]}</span>`
const modLabel = (k) => { const m = MODS[k]; return m ? `<span class="mod ${m.kind === 'custom' ? 'is-custom' : ''}"><em>${esc(m.group)} · </em>${esc(m.title)}</span>` : '<span class="mod">—</span>' }
const dueLabel = (t) => t.due ? `<span class="due ${t.due < TODAY && !CLOSED.has(t.status) ? 'is-over' : ''}">${t.due.slice(5).replace('-', '/')}</span>` : '<span class="due">—</span>'
const openCount = (k) => TASKS.filter((t) => t.mod === k && !CLOSED.has(t.status) && !kids(t.id).length).length

function renderNav() {
  $('#nav').innerHTML = NAV.map((g) => `
    <div class="nav-group-title"><span class="gi">${g.icon}</span>${g.title}</div>
    ${g.items.map(([k, t]) => `
      <div class="nav-item ${k === 'task.center' ? 'is-active' : ''}" data-mod="${k}">
        ${t}${openCount(k) ? `<span class="count">${openCount(k)}</span>` : ''}
        <button class="nav-add" type="button" data-quick="${k}" aria-label="为「${t}」记任务" title="为「${t}」记任务">+</button>
      </div>`).join('')}`).join('')
}

function renderStats() {
  const open = TASKS.filter((t) => !CLOSED.has(t.status))
  const s = [
    ['进行中', open.filter((t) => t.status === 'doing').length, ''],
    ['待确认完成', open.filter((t) => t.status === 'pending').length, 'is-gold'],
    ['P0 未结束', open.filter((t) => t.prio === 'P0').length, 'is-red'],
    ['已逾期', open.filter((t) => t.due && t.due < TODAY).length, 'is-red'],
  ]
  $('#stats').innerHTML = s.map(([l, n, c]) => `<div class="stat ${c}"><b>${n}</b><span>${l}</span></div>`).join('')
}

function renderBrief() {
  const pend = TASKS.filter((t) => t.status === 'pending').length
  const top = [
    [140, '已逾期 4 天且卡住薪资 M2 上线；只需钉钉后台开权限，10 分钟能解'],
    [119, 'AI 已提议完成，确认后父任务 T-118 进度到 50%，解锁 T-120 联调'],
    [120, '依赖 T-119 口径，今天合完可赶 10/05 截止'],
  ]
  $('#brief').innerHTML = `
    <div>
      <div class="brief-title"><span class="ai-dot">AI</span>今日简报</div>
      <div class="brief-meta">09/30 周三 · 08:53 生成 · 已推送钉钉</div>
      <div class="brief-git">昨天 git：<b>3</b> 个分支合并进 main，<b>7</b> 个 commit 关联到 <b>5</b> 个任务；1 条未带编号的 commit 待你认领。</div>
    </div>
    <ol class="brief-list">${top.map(([id, why], i) => { const t = byId(id); return `
      <li data-open="${id}"><span class="n">${i + 1}</span><div><div class="t"><span class="code">T-${id}</span> ${esc(t.title)}</div><div class="why">${why}</div></div></li>` }).join('')}
    </ol>
    <div class="brief-confirm">${pend
      ? `<b>${pend}</b><p>项任务 AI 判定已完成，等你看证据确认</p><button class="btn btn-primary btn-sm" data-open="${TASKS.find((t) => t.status === 'pending').id}">逐个确认</button>`
      : `<b>0</b><p>没有待确认的完成提议</p>`}</div>`
}

function treeRows(list, depth) {
  return sortTasks(list.filter(visible)).map((t) => {
    const k = kids(t.id), isOpen = S.open.has(t.id) || S.q
    const [d, n] = progress(t)
    const git = t.git ? `<span class="git-mark ${t.merged ? 'is-merged' : ''}" title="${esc(t.git)}">${t.merged ? '⎇ 已合并' : '⎇ ' + esc(t.git.split('/')[0])}</span>` : ''
    return `
    <div class="row ${k.length ? 'is-parent' : ''} ${CLOSED.has(t.status) ? 'is-closed' : ''} ${t.status === 'pending' ? 'is-pending' : ''} ${S.selected === t.id ? 'is-selected' : ''} ${S.flash === t.id ? 'is-flash' : ''}" data-open="${t.id}" role="row">
      <div class="cell-title" style="padding-left:${depth * 22}px">
        <button class="caret ${k.length ? '' : 'is-leaf'} ${isOpen ? 'is-open' : ''}" data-toggle="${t.id}" aria-label="展开">▸</button>
        <span class="code">T-${t.id}</span><span class="title">${esc(t.title)}</span>${git}
        <button class="row-add" data-child="${t.id}" type="button">+ 子任务</button>
      </div>
      <span class="prio ${t.prio}">${t.prio} ${PRIO[t.prio]}</span>
      ${modLabel(t.mod)}
      ${k.length ? `<div class="progress"><div class="bar"><i style="width:${(d / n) * 100}%"></i></div>${d}/${n}</div>` : statusTag(t.status)}
      ${dueLabel(t)}
      ${k.length ? statusTag(t.status) : '<span></span>'}
    </div>${k.length && isOpen ? treeRows(k, depth + 1) : ''}`
  }).join('')
}

function renderTree() {
  const rows = treeRows(TASKS.filter((t) => !t.parent), 0)
  $('#viewTree').innerHTML = `<div class="tree-head"><span>任务</span><span>重要性</span><span>关联模块</span><span>状态 / 进度</span><span>截止</span><span>父级状态</span></div>
    ${rows || '<div class="empty">没有符合条件的任务，换个筛选或直接新建</div>'}`
}

const COLS = ['todo', 'doing', 'blocked', 'pending', 'done']
function renderBoard() {
  // 看板始终显示「已完成」列，所以这里不套用「隐藏已结束」开关；搁置任务不上看板
  const leafs = TASKS.filter((t) => !kids(t.id).length && t.status !== 'shelved' && selfMatch({ ...t, status: 'todo' }))
  $('#viewBoard').innerHTML = COLS.map((c) => { const list = sortTasks(leafs.filter((t) => t.status === c)); return `
    <div class="col" data-col="${c}"><div class="col-head">${STATUS[c][0]}<span>${list.length}</span></div>
    ${list.map((t) => `<div class="card" draggable="true" data-drag="${t.id}" data-open="${t.id}">
      <div class="top"><span class="code">T-${t.id}</span><span class="prio ${t.prio}">${t.prio}</span></div>
      <div class="t">${esc(t.title)}</div>${t.parent ? `<div class="parent">↳ ${esc(byId(t.parent).title)}</div>` : ''}
      <div class="foot">${modLabel(t.mod)}${dueLabel(t)}</div></div>`).join('')}</div>` }).join('')
}

function renderMap() {
  const groups = {}
  Object.values(MODS).forEach((m) => { (groups[m.group] ||= []).push(m) })
  const max = Math.max(1, ...Object.keys(MODS).map(openCount))
  $('#viewMap').innerHTML = Object.entries(groups).map(([g, ms]) => { const sum = ms.reduce((a, m) => a + openCount(m.key), 0); return `
    <div class="mgroup lg-card is-static"><h3>${g}<span>${sum} 项未结束</span></h3>
    ${ms.map((m) => { const n = openCount(m.key), p0 = TASKS.some((t) => t.mod === m.key && t.prio === 'P0' && !CLOSED.has(t.status)); return `
      <div class="mcell" data-map="${m.key}"><span class="name">${m.title}</span>${p0 ? '<span class="p0" title="含 P0"></span>' : ''}
      <span class="heat"><i style="width:${(n / max) * 100}%"></i></span><span class="num">${n}</span></div>` }).join('')}</div>` }).join('')
}

window.renderAll = function () {
  renderNav(); renderStats(); renderBrief()
  ;({ tree: renderTree, board: renderBoard, map: renderMap })[S.view]()
  S.flash = null
}
