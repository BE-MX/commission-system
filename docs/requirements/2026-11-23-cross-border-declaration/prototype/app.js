// 跨境申报核对 · 原型交互（原生 JS，无依赖）
import { records as seed, ISSUES, LOGISTICS, SHOPS, imports, orphanReceipts, audit } from './data.js'

const rows = structuredClone(seed)
const state = {
  card: 'block',                       // block | ready | remind | exported | all
  form: { q: '', shop: '', logistics: '', issue: '' },
  applied: { q: '', shop: '', logistics: '', issue: '' },
  selected: new Set(),
  importedToday: true,
}

const $app = document.getElementById('app')
const $layer = document.getElementById('layer')

/* ── 图标（简化线稿，正式实现用 Element Plus 图标） ── */
const I = {
  alert: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 9v4M12 17h.01"/><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"/></svg>',
  check: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/></svg>',
  bell: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M6 8a6 6 0 1 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.9 1.9 0 0 0 3.4 0"/></svg>',
  folder: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z"/><path d="m9 13 2 2 4-4"/></svg>',
  upload: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 15V3M7 8l5-5 5 5"/><path d="M5 21h14"/></svg>',
  download: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 3v12M7 10l5 5 5-5"/><path d="M5 21h14"/></svg>',
  eye: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/></svg>',
  truck: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M3 6h11v10H3zM14 10h4l3 3v3h-7"/><circle cx="7" cy="18" r="2"/><circle cx="17" cy="18" r="2"/></svg>',
  link: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M10 14a4 4 0 0 0 6 0l3-3a4 4 0 0 0-6-6l-1 1"/><path d="M14 10a4 4 0 0 0-6 0l-3 3a4 4 0 0 0 6 6l1-1"/></svg>',
  ban: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><path d="m6 6 12 12"/></svg>',
  refresh: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M20 11a8 8 0 1 0-2.3 5.7"/><path d="M20 4v7h-7"/></svg>',
  cols: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16M15 4v16"/></svg>',
  density: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M4 6h16M4 12h16M4 18h16"/></svg>',
  full: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/></svg>',
  x: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M6 6l12 12M18 6 6 18"/></svg>',
}

/* ── 派生状态 ── */
const blocking = r => r.issues.filter(k => ISSUES[k].level === 'block')
const reminds = r => r.issues.filter(k => ISSUES[k].level === 'remind')
const isBlocked = r => !r.exported && !r.excluded && blocking(r).length > 0
const isReady = r => !r.exported && !r.excluded && blocking(r).length === 0
const money = v => v == null ? '—' : Number(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const round2 = s => Math.round(Number(s) * 100) / 100
const tail = s => s.slice(-6)
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]))

function cardFilter(r) {
  switch (state.card) {
    case 'block': return isBlocked(r)
    case 'ready': return isReady(r)
    case 'remind': return !r.exported && !r.excluded && reminds(r).length > 0
    case 'exported': return r.exported
    default: return true
  }
}
function visibleRows() {
  const a = state.applied
  return rows.filter(cardFilter).filter(r =>
    (!a.q || r.orderNo.includes(a.q) || r.ticket?.invoices.some(i => i.no.includes(a.q.toUpperCase())) || r.ticket?.waybill.includes(a.q)) &&
    (!a.shop || r.shop === a.shop) &&
    (!a.logistics || (r.ticket?.logistics ?? 'none') === a.logistics) &&
    (!a.issue || r.issues.includes(a.issue)))
}
const pendingSearch = () => JSON.stringify(state.form) !== JSON.stringify(state.applied)

/* ── 渲染 ── */
function render() {
  const counts = {
    block: rows.filter(isBlocked).length,
    ready: rows.filter(isReady).length,
    remind: rows.filter(r => !r.exported && !r.excluded && reminds(r).length).length,
    exported: rows.filter(r => r.exported).length,
  }
  const list = visibleRows()
  const selectable = list.filter(isReady)
  for (const id of state.selected) if (!rows.find(r => r.id === id && isReady(r))) state.selected.delete(id)

  $app.innerHTML = `
    <div class="page-head">
      <h2>跨境申报核对</h2>
      <p>DHL9610 申报与方舟发票、运单、收款逐条核对，通过后导出报关订单与收款单</p>
    </div>

    <div class="metrics">
      ${metric('block', 'danger', I.alert, '待处理', counts.block, '有阻断问题，不能报关')}
      ${metric('ready', 'success', I.check, '可报关', counts.ready, '核对通过，未导出')}
      ${metric('remind', 'warning', I.bell, '有提醒', counts.remind, '不挡导出，建议看一眼')}
      ${metric('exported', 'violet', I.folder, '已导出', counts.exported, '已生成报关文件')}
    </div>

    <div class="import-strip" role="status">
      <span>最近导入 · 订单 <b>${imports[0].at}</b>（${imports[0].rows} 条）</span>
      <span>收款单 <b>${imports[1].at}</b>（${imports[1].rows} 条）</span>
      ${orphanReceipts.length ? `<span class="warn">${orphanReceipts.length} 条收款单暂无订单，导入最新订单文件后自动配上</span>` : ''}
    </div>

    <section class="table-card">
      <div class="toolbar">
        <input class="ctl" id="f-q" placeholder="阿里订单号 / 发票号 / 运单号" value="${esc(state.form.q)}">
        <select class="ctl w160" id="f-shop" aria-label="店铺">
          <option value="">全部店铺</option>${SHOPS.map(s => `<option ${state.form.shop === s ? 'selected' : ''}>${s}</option>`).join('')}
        </select>
        <select class="ctl w160" id="f-logistics" aria-label="物流状态">
          <option value="">全部物流状态</option>${Object.entries(LOGISTICS).filter(([k]) => k !== 'none').map(([k, v]) => `<option value="${k}" ${state.form.logistics === k ? 'selected' : ''}>${v.label}</option>`).join('')}
        </select>
        <select class="ctl" id="f-issue" aria-label="问题类型">
          <option value="">全部问题类型</option>${Object.entries(ISSUES).map(([k, v]) => `<option value="${k}" ${state.form.issue === k ? 'selected' : ''}>${v.label}</option>`).join('')}
        </select>
        <button class="btn primary" data-act="search">查询</button>
        <button class="btn secondary" data-act="reset">重置</button>
        ${pendingSearch() ? '<span class="pending-hint">条件已修改，查询后生效</span>' : ''}
      </div>

      <div class="action-bar">
        <button class="btn primary" data-act="export" ${counts.ready ? '' : 'disabled'}>${I.download}导出报关文件${state.selected.size ? `（已选 ${state.selected.size}）` : counts.ready ? `（全部可报关 ${counts.ready}）` : ''}</button>
        <button class="btn secondary" data-act="import">${I.upload}导入 DHL 文件</button>
        <span class="spacer"></span>
        <span class="tools">
          <button title="刷新" aria-label="刷新" data-act="refresh">${I.refresh}</button>
          <button title="列显示" aria-label="列显示">${I.cols}</button>
          <button title="密度" aria-label="密度">${I.density}</button>
          <button title="全屏" aria-label="全屏">${I.full}</button>
        </span>
      </div>

      ${list.length ? table(list, selectable) : emptyState()}
      <div class="pager">共 ${list.length} 条 <span>20 条/页</span></div>
    </section>`
}

function metric(key, tone, icon, label, value, sub) {
  return `<button class="metric" data-tone="${tone}" data-card="${key}" aria-pressed="${state.card === key}">
    <span class="ic" aria-hidden="true">${icon}</span>
    <span class="lbl">${label}</span>
    <span class="val num">${value}</span>
    <span class="sub">${sub}</span>
    <span class="wm" aria-hidden="true">${icon}</span>
  </button>`
}

function table(list, selectable) {
  const allOn = selectable.length && selectable.every(r => state.selected.has(r.id))
  return `<div class="table-wrap"><table class="list">
    <thead><tr>
      <th class="check"><input type="checkbox" aria-label="全选可报关" data-act="check-all" ${allOn ? 'checked' : ''} ${selectable.length ? '' : 'disabled'}></th>
      ${['阿里订单号', '店铺', '发票号', '业务员', '运单号', '物流状态'].map(h => `<th>${h}<span class="sort">⇅</span></th>`).join('')}
      <th class="num">申报金额<span class="sort">⇅</span></th>
      <th class="num">票金额<span class="sort">⇅</span></th>
      <th class="num">差额<span class="sort">⇅</span></th>
      <th>收款单</th>
      <th>核对结果</th>
      <th>操作</th>
    </tr></thead>
    <tbody>${list.map(rowHtml).join('')}</tbody>
  </table></div>`
}

function rowHtml(r) {
  const t = r.ticket
  const lg = LOGISTICS[t?.logistics ?? 'none']
  const ready = isReady(r)
  const declared = round2(r.goodsValue)
  const ticketAmt = t ? (t.kind === 'split' ? `<span class="muted">下限</span> ${money(t.floor)}` : money(t.amount)) : '—'
  const diff = t?.kind === 'exact' && Math.abs(declared - t.amount) > 0.001 ? (declared - t.amount) : null
  const invoices = t ? t.invoices.map(i => i.no).join('、') : (r.invoiceNoWaybill ?? '—')
  const result = r.exported ? `<span class="tag gold">已导出</span>`
    : r.excluded ? `<span class="tag neutral">本单不报</span>`
    : r.issues.length ? r.issues.map(k => `<span class="tag ${ISSUES[k].level === 'block' ? 'danger' : 'warning'}">${ISSUES[k].label}</span>`).join('')
    : r.released ? `<span class="tag success">已放行</span>` : `<span class="tag success">通过</span>`
  const act = blocking(r).map(k => ISSUES[k].action).find(Boolean)
  return `<tr data-row="${r.id}" class="${isBlocked(r) ? 'is-blocked' : ''} ${state.selected.has(r.id) ? 'is-selected' : ''}">
    <td class="check" data-stop><input type="checkbox" aria-label="选择 ${r.orderNo}" data-check="${r.id}" ${state.selected.has(r.id) ? 'checked' : ''} ${ready ? '' : 'disabled'}></td>
    <td><span class="key num" title="${r.orderNo}">${r.orderNo}</span></td>
    <td>${r.shop ? `<span class="tag neutral">${r.shop}</span>` : '<span class="muted">—</span>'}</td>
    <td class="num">${invoices}</td>
    <td>${r.sales ?? '<span class="muted">—</span>'}</td>
    <td class="num">${t?.waybill ?? '<span class="muted">—</span>'}</td>
    <td><span class="tag ${lg.tone}">${lg.label}</span></td>
    <td class="num">${money(declared)}</td>
    <td class="num">${ticketAmt}</td>
    <td class="num">${diff == null ? '<span class="muted">—</span>' : `<span class="diff">${diff > 0 ? '+' : ''}${money(diff)}</span>`}</td>
    <td>${r.receipt ? `<span class="num">${money(r.receipt.charge)}</span>` : '<span class="tag danger">缺</span>'}</td>
    <td><div class="tags">${result}</div></td>
    <td class="actions" data-stop>
      <button class="link" data-open="${r.id}">${I.eye}查看</button>
      ${act === 'confirm_shipped' ? `<button class="link warning" data-review="${r.id}" data-kind="confirm_shipped">${I.truck}确认已发</button>` : ''}
      ${act === 'assign' ? `<button class="link warning" data-review="${r.id}" data-kind="assign">${I.link}指定配对</button>` : ''}
      ${!r.exported && !r.excluded ? `<button class="link danger" data-review="${r.id}" data-kind="exclude">${I.ban}本单不报</button>` : ''}
    </td>
  </tr>`
}

function emptyState() {
  const filtered = Object.values(state.applied).some(Boolean)
  const msg = state.card === 'block' && !filtered ? '没有待处理的申报，可以导出报关文件了' : '暂无数据'
  return `<div class="empty">${msg}${filtered ? '<button class="btn secondary" data-act="reset">重置筛选</button>' : ''}</div>`
}

/* ── 抽屉 ── */
let lastFocus = null
function openDrawer(id) {
  const r = rows.find(x => x.id === id)
  lastFocus = document.activeElement
  const t = r.ticket
  const declared = round2(r.goodsValue)
  const issueCards = r.issues.length ? r.issues.map(k => {
    const d = ISSUES[k]
    const btn = d.action === 'confirm_shipped' ? `<button class="btn secondary act" data-review="${r.id}" data-kind="confirm_shipped">${I.truck}确认已发</button>`
      : d.action === 'assign' ? `<button class="btn secondary act" data-review="${r.id}" data-kind="assign">${I.link}指定配对</button>`
      : d.action === 'void' ? `<button class="btn secondary act" data-review="${r.id}" data-kind="void">作废旧条目</button>` : ''
    return `<div class="issue ${d.level}"><strong>${d.label}</strong><p>${d.hint}</p>${btn}</div>`
  }).join('') : `<div class="issue ok"><strong>${r.exported ? `已导出 · ${r.exportedAt}` : r.released ? `已放行 · ${r.released.action}` : '核对通过'}</strong>${r.released ? `<p>${r.released.by} · ${r.released.at} · ${esc(r.released.reason)}</p>` : ''}</div>`

  const compare = t ? (t.kind === 'split'
    ? `<div class="compare">
        <div><span>申报金额</span><b class="num">${money(declared)}</b></div>
        <div class="${declared < t.floor ? 'bad' : ''}"><span>本票产品金额（下限）</span><b class="num">${money(t.floor)}</b></div>
        <div><span>发票应付合计</span><b class="num">${money(t.split.invoiceTotal)}</b></div>
      </div>
      <p class="muted" style="font-size:12px;margin-top:8px">分票发货：本票出库 ${t.split.shippedQty} / 发票 ${t.split.invoiceQty} 件。费用各票各算，发票全部发完后校验各票合计。</p>`
    : `<div class="compare">
        <div><span>申报金额</span><b class="num">${money(declared)}</b></div>
        <div><span>票金额（应付合计）</span><b class="num">${money(t.amount)}</b></div>
        <div class="${Math.abs(declared - t.amount) > 0.001 ? 'bad' : ''}"><span>差额</span><b class="num">${money(declared - t.amount)}</b></div>
      </div>`) : ''

  const invoices = t ? `<table class="mini"><thead><tr><th>发票号</th><th>产品</th><th>费用</th><th>应付合计</th></tr></thead><tbody>
      ${t.invoices.map(i => `<tr><td>${i.no}${i.cancelled ? ' <span class="tag danger">已取消</span>' : ''}</td><td class="num">${money(i.product)}</td><td class="num">${money(i.fees)}</td><td class="num">${money(i.total)}</td></tr>`).join('')}
    </tbody></table>` : `<p class="muted" style="font-size:13px">${r.invoiceNoWaybill ? `发票 ${r.invoiceNoWaybill} 还没上传物流单` : '方舟里没有这个阿里订单号的 DHL9610 发票'}</p>`

  const logs = audit[r.id] ?? [{ at: '2026-11-23 09:43', who: '张敏', text: '导入订单文件，新增本条申报' }]

  $layer.innerHTML = `<div class="scrim" data-close></div>
    <aside class="drawer" role="dialog" aria-modal="true" aria-labelledby="dw-title">
      <header>
        <div><h3 id="dw-title" class="num">${r.orderNo}</h3>
          <div class="sub">${[r.shop, r.sales, t ? `运单 ${t.waybill}` : null].filter(Boolean).join(' · ') || '未关联方舟订单'}</div></div>
        <button class="link x" data-close aria-label="关闭">${I.x}</button>
      </header>
      <div class="body">
        <section class="sec"><h4>核对结果</h4>${issueCards}</section>
        ${t ? `<section class="sec"><h4>金额核对</h4>${compare}</section>` : ''}
        <section class="sec"><h4>DHL 申报</h4>
          <dl class="kv">
            <dt>商品金额</dt><dd class="num">${r.goodsValue} USD</dd>
            <dt>运杂费</dt><dd class="num">${r.freight} USD</dd>
            <dt>明细</dt><dd>${r.line.itemName} · ${r.line.qty} ${r.line.unit === '015' ? '条' : '个'} × ${r.line.price}</dd>
            <dt>收款单</dt><dd>${r.receipt ? `<span class="num">${r.receipt.charge}</span> · 到账 ${r.receipt.accountingDate}` : '<span class="tag danger">缺收款单</span>'}</dd>
          </dl>
        </section>
        <section class="sec"><h4>方舟发票</h4>${invoices}</section>
        ${t ? `<section class="sec"><h4>物流</h4><dl class="kv">
            <dt>运单号</dt><dd class="num">${t.waybill}（DHL）</dd>
            <dt>状态</dt><dd><span class="tag ${LOGISTICS[t.logistics].tone}">${LOGISTICS[t.logistics].label}</span></dd>
            <dt>揽收时间</dt><dd>${t.pickedAt ?? '尚无揽收事件'}</dd>
            <dt>上传物流单</dt><dd>${r.boundAt}</dd>
          </dl></section>` : ''}
        <section class="sec"><h4>操作记录</h4><ul class="timeline">${logs.map(l => `<li><span>${l.at}</span><b>${l.who} · ${esc(l.text)}</b></li>`).join('')}</ul></section>
      </div>
      <footer>
        ${!r.exported && !r.excluded ? `<button class="btn secondary" data-review="${r.id}" data-kind="exclude">${I.ban}本单不报</button>` : ''}
        <button class="btn secondary" data-close>关闭</button>
      </footer>
    </aside>`
  requestAnimationFrame(() => {
    const drawer = $layer.querySelector('.drawer')
    if (!drawer) return // 首帧前已被 Esc 关闭
    $layer.querySelector('.scrim').classList.add('open')
    drawer.classList.add('open')
    drawer.querySelector('.x').focus()
  })
}

function closeLayer({ instant = false } = {}) {
  const els = $layer.querySelectorAll('.scrim, .drawer, .dialog-wrap')
  if (!els.length) return
  // 键盘触发（Esc）不做动画，立即关闭
  if (instant) { $layer.innerHTML = ''; lastFocus?.focus?.(); return }
  els.forEach(el => el.classList.remove('open'))
  setTimeout(() => { $layer.innerHTML = ''; lastFocus?.focus?.() }, 200)
}

/* ── 弹窗 ── */
function openDialog({ title, width = 480, body, okText, okClass = 'primary', onOk }) {
  lastFocus = document.activeElement
  $layer.innerHTML = `<div class="dialog-wrap" data-backdrop>
    <div class="dialog" role="dialog" aria-modal="true" aria-label="${esc(title)}" style="--w:${width}px">
      <header>${title}</header>
      <div class="body">${body}</div>
      <div class="dialog-footer">
        <button class="btn secondary" data-close>取消</button>
        <button class="btn ${okClass}" data-ok>${okText}</button>
      </div>
    </div></div>`
  const wrap = $layer.querySelector('.dialog-wrap')
  requestAnimationFrame(() => {
    if (!wrap.isConnected) return
    wrap.classList.add('open'); (wrap.querySelector('textarea, input, [data-ok]'))?.focus()
  })
  wrap.querySelector('[data-ok]').addEventListener('click', () => onOk(wrap))
}

const REVIEW = {
  confirm_shipped: { title: '确认已发', ok: '确认放行', okClass: 'primary', clears: ['not_picked'], hint: 'DHL 还没有揽收事件。确认货已交给 DHL 后，本条可以报关。申报内容变化时放行自动失效。' },
  assign: { title: '指定配对', ok: '确认配对', okClass: 'primary', clears: ['ambiguous'], hint: '选择这条申报对应的运单。' },
  exclude: { title: '本单不报', ok: '排除', okClass: 'danger', clears: [], hint: '退款、撤单、改走其他渠道等情况使用。排除后本条不出现在报关文件中，可在「全部」里查看。' },
  void: { title: '作废旧条目', ok: '作废', okClass: 'danger', clears: ['suspected'], hint: '确认这条旧申报已在 DHL 改过时作废。作废后只保留最新申报。' },
}

function openReview(id, kind) {
  const r = rows.find(x => x.id === id)
  const cfg = REVIEW[kind]
  const choices = kind === 'assign' ? `<div class="radio-list">${r.candidates.map((c, i) =>
    `<label><input type="radio" name="cand" value="${c.waybill}" ${i === 0 ? 'checked' : ''}><span>运单 ${c.waybill} · ${c.kind} · ${c.amount} · ${c.invoices}</span></label>`).join('')}</div>` : ''
  openDialog({
    title: `${cfg.title} · 尾号 ${tail(r.orderNo)}`,
    body: `<p style="color:var(--text-secondary);line-height:1.6">${cfg.hint}</p>${choices}
      <div class="field"><label for="reason">原因（必填，记入操作记录）</label><textarea id="reason"></textarea><span class="err" hidden>请填写原因</span></div>`,
    okText: cfg.ok, okClass: cfg.okClass,
    onOk(wrap) {
      const ta = wrap.querySelector('#reason')
      if (!ta.value.trim()) { wrap.querySelector('.err').hidden = false; ta.focus(); return }
      if (kind === 'exclude') r.excluded = true
      r.issues = r.issues.filter(k => !cfg.clears.includes(k))
      if (kind !== 'exclude') r.released = { action: cfg.title, by: '张敏', at: '2026-11-23 14:20', reason: ta.value.trim() }
      closeLayer(); render(); toast(`已${cfg.ok}：尾号 ${tail(r.orderNo)}`)
    },
  })
}

function openImport() {
  openDialog({
    title: '导入 DHL 文件', width: 640, okText: '导入',
    body: `<div class="drop"><b>拖入或选择 DHL 跨境申报页导出的文件</b><span>订单、收款单可一起传，也可单独传；支持 .xls / .xlsx</span></div>
      ${imports.map(f => `<div class="file-row"><span class="tag ${f.kind === 'order' ? 'gold' : 'info'}">${f.kind === 'order' ? '订单' : '收款单'}</span>
        <div class="grow"><div class="name">${f.name}</div><div class="meta">识别为${f.kind === 'order' ? '订单文件（OrderHead / OrderList）' : '收款单文件（ReceiptsHead）'} · ${f.rows} 条</div></div></div>`).join('')}`,
    onOk(wrap) {
      const o = imports[0], c = imports[1]
      wrap.querySelector('.body').innerHTML = `
        <div class="result">
          <div><span>新增申报</span><b class="num">${o.added}</b></div>
          <div><span>已导入过</span><b class="num">${o.existed}</b></div>
          <div><span>可能已被修改</span><b class="num">${o.suspected}</b></div>
        </div>
        <div class="result">
          <div><span>新增收款</span><b class="num">${c.added}</b></div>
          <div><span>已导入过</span><b class="num">${c.existed}</b></div>
          <div><span>暂无订单</span><b class="num">${orphanReceipts.length}</b></div>
        </div>
        <p style="color:var(--text-secondary)">核对已按最新数据重算。</p>`
      const footer = wrap.querySelector('.dialog-footer')
      footer.innerHTML = '<button class="btn primary" data-close>查看核对结果</button>'
      footer.querySelector('[data-close]').focus()
    },
  })
}

function openExport() {
  const pick = state.selected.size ? rows.filter(r => state.selected.has(r.id)) : rows.filter(isReady)
  const suspected = pick.filter(r => r.issues.includes('suspected'))
  const remind = pick.filter(r => reminds(r).length)
  openDialog({
    title: '导出报关文件', okText: `生成 2 个文件`,
    body: `<p>将导出 <b class="num">${pick.length}</b> 条申报，生成：</p>
      <div class="file-row"><span class="tag gold">订单</span><div class="grow"><div class="name">报关订单_20261123.xlsx</div><div class="meta">OrderHead / OrderList / BaseTransfer</div></div></div>
      <div class="file-row"><span class="tag info">收款单</span><div class="grow"><div class="name">报关收款单_20261123.xlsx</div><div class="meta">ReceiptsHead / BaseTransfer</div></div></div>
      ${remind.length ? `<div class="note">${remind.length} 条带提醒（${[...new Set(remind.flatMap(reminds))].map(k => ISSUES[k].label).join('、')}），不影响导出。</div>` : ''}
      ${suspected.length ? `<label class="check-line"><input type="checkbox" id="ack"><span>尾号 ${suspected.map(r => tail(r.orderNo)).join('、')} 有「可能已被修改」的旧申报，我已核对，确认导出</span></label><span class="err" hidden style="font-size:12px;color:var(--tag-danger-text)">请先勾选确认</span>` : ''}`,
    onOk(wrap) {
      const ack = wrap.querySelector('#ack')
      if (ack && !ack.checked) { wrap.querySelector('.err').hidden = false; return }
      pick.forEach(r => { r.exported = true; r.exportedAt = '2026-11-23 14:30' })
      state.selected.clear()
      closeLayer(); render(); toast(`已生成 2 个文件，共 ${pick.length} 条`)
    },
  })
}

let toastTimer
function toast(text) {
  document.querySelector('.toast')?.remove()
  const el = Object.assign(document.createElement('div'), { className: 'toast', role: 'status', textContent: text })
  document.body.append(el)
  requestAnimationFrame(() => el.classList.add('show'))
  clearTimeout(toastTimer)
  toastTimer = setTimeout(() => { el.classList.remove('show'); setTimeout(() => el.remove(), 200) }, 2400)
}

/* ── 事件 ── */
document.addEventListener('click', e => {
  const t = e.target
  const card = t.closest('[data-card]')
  if (card) { state.card = state.card === card.dataset.card ? 'all' : card.dataset.card; render(); return }
  const act = t.closest('[data-act]')?.dataset.act
  if (act === 'search') { state.applied = { ...state.form }; render(); return }
  if (act === 'reset') { state.form = { q: '', shop: '', logistics: '', issue: '' }; state.applied = { ...state.form }; render(); return }
  if (act === 'import') return openImport()
  if (act === 'export') return openExport()
  if (act === 'refresh') { render(); toast('已刷新物流状态与核对结果'); return }
  if (act === 'check-all') {
    const sel = visibleRows().filter(isReady)
    const on = t.checked
    sel.forEach(r => on ? state.selected.add(r.id) : state.selected.delete(r.id)); render(); return
  }
  const chk = t.closest('[data-check]')
  if (chk) { chk.checked ? state.selected.add(chk.dataset.check) : state.selected.delete(chk.dataset.check); render(); return }
  const rv = t.closest('[data-review]')
  if (rv) { if ($layer.innerHTML) { $layer.innerHTML = '' } return openReview(rv.dataset.review, rv.dataset.kind) }
  const op = t.closest('[data-open]')
  if (op) return openDrawer(op.dataset.open)
  if (t.closest('[data-close]') || t.matches('[data-backdrop]')) return closeLayer()
  if (t.closest('[data-stop]')) return
  const row = t.closest('[data-row]')
  if (row) openDrawer(row.dataset.row)
})

document.addEventListener('input', e => {
  const map = { 'f-q': 'q', 'f-shop': 'shop', 'f-logistics': 'logistics', 'f-issue': 'issue' }
  const key = map[e.target.id]
  if (!key) return
  state.form[key] = e.target.value
  const hint = document.querySelector('.pending-hint')
  if (pendingSearch() && !hint) document.querySelector('[data-act="reset"]').insertAdjacentHTML('afterend', '<span class="pending-hint">条件已修改，查询后生效</span>')
  if (!pendingSearch() && hint) hint.remove()
})

document.addEventListener('keydown', e => {
  if (e.key === 'Escape') closeLayer({ instant: true })
  if (e.key === 'Enter' && e.target.id === 'f-q' && !e.isComposing) { state.applied = { ...state.form }; render(); document.getElementById('f-q').focus() }
})

render()
