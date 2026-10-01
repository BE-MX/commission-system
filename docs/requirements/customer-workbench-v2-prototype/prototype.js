
(() => {
const TODAY = new Date(2026, 8, 30);
const DAY = 86400000;
const REDUCED = matchMedia('(prefers-reduced-motion: reduce)').matches;
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const fmtMoney = n => n >= 1000 ? '$' + (n / 1000).toFixed(n >= 100000 ? 0 : 1) + 'k' : '$' + Math.round(n);
const fmtDate = d => `${d.getMonth() + 1}月${d.getDate()}日`;
const fmtYMD = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
const daysAgo = n => new Date(TODAY.getTime() - n * DAY);
const $ = id => document.getElementById(id);

function rng(seed) {
  return () => { seed |= 0; seed = seed + 0x6D2B79F5 | 0; let t = Math.imul(seed ^ seed >>> 15, 1 | seed); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; };
}

const PREFIX = ['Glamour', 'Bella', 'Crown', 'Luxe', 'Velvet', 'Royal', 'Silk', 'Divine', 'Halo', 'Aura', 'Mane', 'Nova', 'Opal', 'Pearl', 'Ruby', 'Sable', 'Tress', 'Vivid', 'Zuri', 'Ebony', 'Queen', 'Amara', 'Glow', 'Lush', 'Ivy', 'Onyx', 'Posh', 'Radiant', 'Sleek', 'Kinky', 'Afro', 'Belle', 'Diva', 'Essence', 'Flair'];
const SUFFIX = ['Hair', 'Wigs', 'Beauty', 'Hair Studio', 'Extensions', 'Salon Supply', 'Hair Co.', 'Tresses', 'Hair Boutique', 'Hair Lounge'];
const COUNTRIES = [['US', '美国', 'Atlanta', '+1 404'], ['US', '美国', 'Houston', '+1 713'], ['US', '美国', 'Chicago', '+1 312'], ['GB', '英国', 'London', '+44 20'], ['NG', '尼日利亚', 'Lagos', '+234 1'], ['ZA', '南非', 'Johannesburg', '+27 11'], ['GH', '加纳', 'Accra', '+233 30'], ['FR', '法国', 'Paris', '+33 1'], ['CA', '加拿大', 'Toronto', '+1 416'], ['AU', '澳大利亚', 'Sydney', '+61 2'], ['AE', '阿联酋', 'Dubai', '+971 4'], ['DE', '德国', 'Berlin', '+49 30']];
const FIRST = ['Sarah', 'Aisha', 'Monique', 'Tasha', 'Grace', 'Chioma', 'Emily', 'Keisha', 'Nadia', 'Latoya', 'Fatima', 'Olivia', 'Brianna', 'Zainab', 'Jasmine', 'Ruth'];
const TYPES = ['批发商', '沙龙', '零售店', '电商卖家'];
const FAMILIES = ['Bundles 束发', 'Lace Wig 蕾丝假发', 'Closure 发块', 'Frontal 前额发块', 'Ponytail 马尾', 'Topper 发顶片'];
const FAMILY_EN = { 'Bundles 束发': 'bundles', 'Lace Wig 蕾丝假发': 'lace wigs', 'Closure 发块': 'closures', 'Frontal 前额发块': 'frontals', 'Ponytail 马尾': 'ponytails', 'Topper 发顶片': 'toppers' };
const COLORS = ['Natural Black 1B', '#613 Blonde', '#27 Honey', 'Ombre 1B/30', '#99J Burgundy', '#4 Brown'];
const LENGTHS = ['14"', '16"', '18"', '20"', '22"', '26"'];
const SEGS = [
  { key: 'active', name: '活跃', color: 'var(--seg-active)', hint: '核对需求与未兑现承诺' },
  { key: 'reorder', name: '复购窗口', color: 'var(--seg-reorder)', hint: '历史节奏线索，需求待确认' },
  { key: 'new', name: '新客培育', color: 'var(--seg-new)', hint: '推动第一单' },
  { key: 'wake', name: '需唤醒', color: 'var(--seg-wake)', hint: '采购放缓，先问原因' },
  { key: 'sleep', name: '沉睡', color: 'var(--seg-sleep)', hint: '尊重偏好，按需恢复' },
];
const SEG = Object.fromEntries(SEGS.map(s => [s.key, s]));
const segGrad = s => `linear-gradient(90deg, color-mix(in srgb, ${s.color} 60%, white), ${s.color})`;

function classify(c) {
  if (c.orders.length >= 3 && c.lastOrderDays / c.cycle >= 0.85 && c.lastOrderDays / c.cycle <= 1.5) return 'reorder';
  if ((c.orders.length && c.lastOrderDays <= 90) || c.lastContactDays <= 30) return 'active';
  if (!c.orders.length && c.lastContactDays <= 60) return 'new';
  if (c.orders.length && c.lastOrderDays > 90 && c.lastOrderDays <= 240) return 'wake';
  return 'sleep';
}

function makeCustomer(r, i, kind) {
  const name = `${PREFIX[Math.floor(r() * PREFIX.length)]} ${SUFFIX[Math.floor(r() * SUFFIX.length)]}`;
  const [cc, country, city, dial] = COUNTRIES[Math.floor(r() * COUNTRIES.length)];
  const fam = FAMILIES[Math.floor(r() * 4)];
  const fam2 = FAMILIES[Math.floor(r() * FAMILIES.length)];
  const color = COLORS[Math.floor(r() * COLORS.length)];
  const len = LENGTHS[Math.floor(r() * LENGTHS.length)];
  const cycle = Math.round(45 + r() * 75);
  const base = Math.round(1500 + Math.pow(r(), 2.2) * 26000);
  const unit = Math.round(22 + r() * 40);
  let lastOrder, n, contact;
  if (kind === 'active') { lastOrder = Math.round(r() * 70); n = 3 + Math.floor(r() * 12); contact = Math.round(1 + r() * 25); }
  else if (kind === 'reorder') { lastOrder = Math.round(cycle * (0.9 + r() * 0.5)); n = 4 + Math.floor(r() * 10); contact = Math.round(12 + r() * 50); }
  else if (kind === 'wake') { lastOrder = Math.max(Math.round(130 + r() * 100), Math.round(cycle * 1.6)); n = 2 + Math.floor(r() * 6); contact = Math.round(40 + r() * 90); }
  else if (kind === 'sleep') { lastOrder = Math.round(260 + r() * 400); n = r() < 0.35 ? 0 : 1 + Math.floor(r() * 3); contact = Math.round(90 + r() * 300); }
  else { lastOrder = null; n = 0; contact = Math.round(1 + r() * 45); }
  const orders = [];
  let d = lastOrder;
  for (let k = 0; k < n && d <= 900; k++) {
    const f = r() < 0.72 ? fam : fam2;
    const qty = Math.max(10, Math.round(base / unit * (0.7 + r() * 0.6) / 5) * 5);
    orders.push({ id: `ORD-${2026 - Math.floor(d / 365)}-${String(1000 + Math.floor(r() * 8999))}`, days: d, date: daysAgo(d), family: f, color: r() < 0.7 ? color : COLORS[Math.floor(r() * COLORS.length)], length: r() < 0.7 ? len : LENGTHS[Math.floor(r() * LENGTHS.length)], qty, unit, amount: qty * unit });
    d += Math.round(cycle * (0.82 + r() * 0.36));
  }
  const c = {
    id: i, name, cc, country, city, dial, contact: FIRST[Math.floor(r() * FIRST.length)], type: TYPES[Math.floor(r() * TYPES.length)],
    fam, color, len, unit, cycle: orders.length >= 3 ? Math.round((orders[orders.length - 1].days - orders[0].days) / (orders.length - 1)) : cycle,
    orders, lastOrderDays: orders.length ? orders[0].days : null, lastContactDays: contact,
    total: orders.reduce((s, o) => s + o.amount, 0),
    completeness: Math.round(28 + r() * 64),
    slug: name.toLowerCase().replace(/[^a-z]+/g, ''),
  };
  c.monthly = Array.from({ length: 12 }, (_, m) => orders.filter(o => o.days >= (11 - m) * 30.4 && o.days < (12 - m) * 30.4).reduce((s, o) => s + o.amount, 0));
  c.seg = classify(c);
  return c;
}

function buildBook(persona) {
  const r = rng(persona === 'senior' ? 20260930 : 20260931);
  const plan = persona === 'senior'
    ? [['active', 44], ['reorder', 16], ['wake', 40], ['sleep', 139], ['new', 47]]
    : [['active', 7], ['reorder', 3], ['wake', 3], ['sleep', 4], ['new', 17]];
  const list = [];
  plan.forEach(([kind, n]) => { for (let k = 0; k < n; k++) list.push(makeCustomer(r, list.length, kind)); });
  return list;
}

/* ── 话术：允许引用历史订单与价格 ── */
function draftFor(c, type) {
  const o = c.orders[0];
  const who = c.contact;
  if (type === 'reorder') return `Hi ${who}, hope business is going well! It's been about ${Math.max(1, Math.round(c.lastOrderDays / 30))} months since your last order — ${o.qty} pcs of ${o.color} ${o.length} ${FAMILY_EN[o.family]} at $${o.unit}/pc. Are you planning any purchases at the moment? If so, would the same items still suit your needs? I can check current availability and lead time before confirming.`;
  if (type === 'wake') return `Hi ${who}, it's been a while since your ${o.date.getMonth() + 1}/${o.date.getDate()} order of ${o.color} ${FAMILY_EN[o.family]}. How did that batch sell? If anything about quality, price or delivery didn't work for you, I'd really like to hear it so we can fix it. I can check the current sample options and terms if useful.`;
  if (type === 'quote') return `Hi ${who}, just following up on the quotation I sent on 9/24 (total $${c.quoteAmount.toLocaleString()}). Any questions on pricing or lead time? If the quantity is flexible, I can check whether we can hold this price for another week.`;
  if (type === 'sample') return `Hi ${who}, the ${c.color} ${FAMILY_EN[c.fam]} samples were delivered on 9/21. Have you had a chance to install or test them? I'd love your honest feedback on texture, shedding and color match — it helps us get your bulk order exactly right.`;
  if (type === 'inquiry') return `Hi ${who}, thanks for your message! I will check availability, current pricing and delivery options for ${c.inquiryQty} pcs of ${c.color} ${c.len} ${FAMILY_EN[c.fam]} before confirming an offer.`;
  if (type === 'active') return `Hi ${who}, quick one — would you like me to check current options for ${c.color} ${FAMILY_EN[c.fam]}? Your historical price was (${o ? `$${o.unit}/pc` : 'price on request'}). Want me to add a few pcs to your next order so you can test it with customers?`;
  if (type === 'first') return `Hi ${who}, following up on your interest in ${FAMILY_EN[c.fam]}. Some ${c.type === '沙龙' ? 'salons' : 'shops'} start with a small mixed trial order (subject to current minimum order terms) to test the market. I can put together a starter pack with our best sellers after checking current pricing — would that be useful?`;
  if (type === 'shipping') return `Hi ${who}, we are checking a change to the dispatch plan. I will confirm a workable option and its timing before asking for your decision. Historical terms are not a new commitment.`;
  return '';
}

function buildTasks(book, persona) {
  const r = rng(persona === 'senior' ? 7 : 9);
  const senior = persona === 'senior';
  const tasks = [];
  const pick = (seg, n, sortFn) => book.filter(c => c.seg === seg && !c._tasked).sort(sortFn).slice(0, n);
  const mark = c => (c._tasked = true, c);
  pick('active', senior ? 2 : 1, (a, b) => b.total - a.total).forEach(c => {
    mark(c); c.inquiryQty = 30 + Math.round(r() * 6) * 10;
    tasks.push({ c, type: 'inquiry', p: 0, label: '新询盘待回复', tone: 'bad', why: `<b>昨天 21:40 WhatsApp</b> 询问 ${esc(c.color)} ${esc(c.len)} 现货和 ${c.inquiryQty} 件的价格，已超过 12 小时未回复。`, src: 'WhatsApp 消息 · 9月29日 21:40' });
  });
  pick('reorder', senior ? 10 : 2, (a, b) => b.lastOrderDays / b.cycle - a.lastOrderDays / a.cycle).forEach(c => {
    mark(c);
    tasks.push({ c, type: 'reorder', p: 1, label: '复购到期', tone: 'warn', why: `过去 ${c.orders.length} 单以 <b>${esc(c.orders[0].family)}</b> 为主，平均 ${c.cycle} 天下一单，现在距上次下单已 <b>${c.lastOrderDays} 天</b>。`, cycle: true, src: `订单 ${c.orders.slice(0, 3).map(o => o.id).join('、')}` });
  });
  pick('active', senior ? 3 : 1, (a, b) => b.total - a.total).forEach(c => {
    mark(c); c.quoteAmount = Math.round((2000 + r() * 9000) / 10) * 10;
    tasks.push({ c, type: 'quote', p: 1, label: '报价未回复', tone: 'warn', why: `9月24日发出报价 <b>$${c.quoteAmount.toLocaleString()}</b>，已 4 个工作日没有回复。`, src: '邮件 · 报价单 Q-2026-0924' });
  });
  pick(senior ? 'active' : 'new', senior ? 2 : 1, (a, b) => b.total - a.total).forEach(c => {
    mark(c);
    tasks.push({ c, type: 'sample', p: 1, label: '样品待反馈', tone: 'info', why: `样品 <b>9月21日签收</b>，客户约定一周内测试，今天到期。`, src: '物流签收 · DHL 3312 7788 90' });
  });
  pick('wake', senior ? 9 : 1, (a, b) => b.total - a.total).forEach(c => {
    mark(c);
    tasks.push({ c, type: 'wake', p: 2, label: '采购放缓', tone: 'muted', why: `累计 <b>${fmtMoney(c.total)}</b> 的老客户，平均 ${c.cycle} 天一单，现在已 <b>${c.lastOrderDays} 天</b>没有下单，${c.lastContactDays} 天没有联系。`, src: `订单 ${c.orders[0].id} · 最近沟通 ${fmtDate(daysAgo(c.lastContactDays))}` });
  });
  if (!senior) {
    pick('new', 4, (a, b) => a.lastContactDays - b.lastContactDays).forEach(c => {
      mark(c);
      tasks.push({ c, type: 'first', p: 2, label: '推动首单', tone: 'info', why: `询过 <b>${esc(c.fam)}</b> 但还没下单，${c.lastContactDays} 天前最后一次沟通。联系频率应根据客户约定调整。`, src: `询盘 · ${fmtDate(daysAgo(c.lastContactDays + 6))}` });
    });
  }
  tasks.unshift({ c: book[0], type: 'shipping', p: 0, label: '交期变化待核实', tone: 'bad', why: '仓库通知备货延迟，可能影响客户已确认的备货安排。<b>先核实可供方案，再作承诺。</b>', src: '仓库事件 WH-0930 · 09:10（模拟）', goal: '客户接受调整方案，且跟单确认相应发运安排' });
  return tasks.sort((a, b) => a.p - b.p);
}

/* ── 状态 ── */
const W = WorkbenchState;
const state = { view: 'focus', endedFilter: 'all', session: null, edits: {}, persona: 'senior', book: [], tasks: [], done: 0, seg: null, sort: 'value', q: '', page: 1, pageSize: 20, taskPage: 1, open: null, tab: 'overview', enrich: {}, adopt: { yes: 36, total: 50 } };
const CAP = { senior: 22, junior: 10 };
const TASK_PAGE = 6;

function load(persona, reset = false) {
  state.persona = persona; state.book = buildBook(persona);
  const seeds = buildTasks(state.book, persona);
  let saved;
  try { saved = reset ? null : JSON.parse(localStorage.getItem('cw-review-v3-' + persona)); } catch (_) {}
  state.session = saved?.session?.schema === 3 ? saved.session : W.create(seeds, persona);
  state.tasks = state.session.tasks;
  state.tasks.forEach(t => { t.c = state.book.find(c => c.id === t.customerId); });
  state.edits = saved?.edits || {}; state.enrich = saved?.enrich || {};
  Object.entries(state.enrich).forEach(([id,e]) => { if (e.status !== 'done') delete state.enrich[id]; });
  state.book.forEach(c => { c.completeness = Math.min(100, c.completeness + Object.values(state.enrich[c.id]?.decided || {}).filter(x=>x !== 'ignore').length * 8); });
  state.view = 'focus'; state.seg = null; state.page = 1; state.taskPage = 1; state.q = ''; $('search').value = '';
  $('persona').dataset.at = persona;
  $('persona').querySelectorAll('button').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.persona === persona)));
  refresh(); renderSegments();
}
function save() {
  try { localStorage.setItem('cw-review-v3-' + state.persona, JSON.stringify({session:state.session, edits:state.edits, enrich:state.enrich})); }
  catch (_) { $('storage-note').textContent = '浏览器未允许本地保存；本次更改仅保留到页面关闭。'; }
}
function refresh() { save(); renderHead(); renderTasks(); renderTable(); if(state.open !== null) renderDrawer(); }


function countUp(el, to, fmt = v => Math.round(v)) { el.textContent = fmt(to); }

function renderHead() {
  const n = W.counts(state.session);
  $('greet').textContent = state.persona === 'senior' ? '早上好，Sarah' : '早上好，Kevin';
  $('greet-sub').textContent = `演示日期 ${state.session.day} · 订单快照 2026-09-30 08:00 · 来源分别核验`;
  $('focus-select').value = state.session.focus;
  const sum = state.book.reduce((s,c)=>s+c.orders.filter(o=>o.days<=90).reduce((a,o)=>a+o.amount,0),0);
  $('kpis').innerHTML = `<div class="kpi"><span>近 90 天成交 · 示例事实</span><strong>${fmtMoney(sum)}</strong></div><div class="kpi"><span>今天已处理 / 当前有效解决</span><strong>${n.handled} <em>/ ${n.resolved}</em></strong></div>`;
}

function renderSegments(play) {
  const counts = Object.fromEntries(SEGS.map(s => [s.key, state.book.filter(c => c.seg === s.key).length]));
  $('seg-total').textContent = state.book.length;
  const bar = $('seg-bar');
  bar.innerHTML = SEGS.map(s => `<i style="flex-grow:${counts[s.key]};background:${segGrad(s)}"></i>`).join('');
  bar.classList.remove('play'); if (play && !REDUCED) { void bar.offsetWidth; bar.classList.add('play'); }
  $('seg-chips').innerHTML = SEGS.map(s => `
    <button type="button" class="seg-chip" data-seg="${s.key}" aria-pressed="${state.seg === s.key}" style="--c:${s.color}">
      <span class="name"><i></i>${s.name}</span>
      <strong class="tnum" data-count="${counts[s.key]}">${counts[s.key]}</strong>
      <small>${s.hint}</small>
    </button>`).join('');
  if (play) document.querySelectorAll('.seg-chip strong').forEach(el => countUp(el, Number(el.dataset.count)));
}

/* ── 今日清单：固定高度 + 内部滚动 + 分页 ── */
function taskHtml(t, idx) {
  const action = (op,label,primary=false) => `<button type="button" class="btn ${primary?'primary':''}" data-action="${op}" data-id="${t.uid}">${label}</button>`;
  const closed = W.CLOSED.has(t.status);
  let buttons = '';
  if(closed) buttons = action('reopen',t.sourceValid?'重开事项':'结果需复核，重开事项');
  else if(t.status === 'paused') buttons = action('resume','恢复事项',true) + action('terminate','终止事项');
  else {
    if(!t.sourceValid || t.suggestionInvalid) buttons += action('reverify','模拟重新核实',true);
    else if(t.status === 'working') buttons += action('agent_result','模拟核实完成',true);
    else if(t.type === 'shipping' && !t.selectedPlan && t.agent === 'prepared') buttons += action('choose_plan','采用分批方案',true);
    else if(t.type === 'shipping' && !t.selectedPlan) buttons += action('delegate','委派核实与准备方案',true);
    else if(t.awaitingResponse) buttons += action('reply','模拟客户接受方案',true);
    else if(t.status === 'awaiting_colleague') buttons += action('colleague_done','模拟跟单确认发运',true);
    else buttons += action('wait','已联系，等回复',true);
    buttons += action('resolve','登记解决结果') + action('pause','暂无需求，暂停') + action('snooze','明天再处理');
  }
  const notice = !t.sourceValid ? '依据已失效，旧方案不可采用' : t.suggestionInvalid ? '原建议已撤下，事实仍待核实' : t.agent === 'prepared' ? '已准备：分批方案与说明草稿（模拟）' : t.status === 'awaiting_reply' ? '等待客户回复；不会自动催促' : t.status === 'awaiting_colleague' ? '客户已接受，仍需跟单完成发运行动' : '需本人判断：确认下一步与当前约束';
  return `<article class="task p${t.p}" data-idx="${idx}" data-task-id="${t.uid}"><div class="task-inner"><div class="task-body"><div class="task-main">
    <div class="task-top"><button type="button" class="cust-btn" data-open="${t.c.id}">${esc(t.c.name)}</button><span class="pill ${t.tone}">${W.LABELS[t.status]}</span>${t.p===0?'<span class="pill hot">紧急 · 来源变化 / 承诺</span>':''}</div>
    <h3 class="task-goal">${esc(t.goal || t.label)}</h3><p class="why">${t.why}</p><p class="meta">${notice}</p>
    <div class="btn-row task-actions">${buttons}</div>
    <details class="task-detail"><summary>依据、协作与操作记录 · ${t.uid}</summary>
      <p>依据：${esc(t.src)} · 来源版本 ${t.sourceVersion} · ${t.sourceValid?'有效（示例）':'已失效'}</p>
      <p>原承诺 ${t.originalDue}${t.originalDue < state.session.day && !closed ? ' · 已过原期限，需核对影响' : ''} · 下一次核验 ${t.nextCheck}</p>
      ${t.status==='paused'?`<p>暂停原因：${esc(t.pauseReason)}；须人工恢复，不因跨日自动运行。</p>`:''}
      ${t.type==='shipping'?`<p>沟通行动：${t.replyReceived?(t.replyVersion===t.sourceVersion?'客户已接受当前方案':'曾接受旧方案，当前待核验'):'等待确认'} · 跟单行动：${t.colleagueDone?(t.fulfillmentVersion===t.sourceVersion?'已确认当前发运安排':'已有发运记录，当前方案待核验'):'未完成'}。两项分别完成，历史事实保留。</p>`:''}
      ${closed?`<p>结果：${esc(t.result)}；依据：${esc(t.resultEvidence || '终止原因单独保留')}</p>`:''}
      <div class="draft open">${!t.sourceValid || t.suggestionInvalid ? '旧草稿已撤下，核实后再准备。' : esc(draftFor(t.c,t.type))}</div>
      <div class="btn-row">${!closed && t.status!=='paused'?action('later','约一周后核验')+action('terminate','终止事项')+action('invalidate','模拟来源失效'):''}${t.status==='resolved'&&t.sourceValid?action('invalidate','模拟结果证据撤回'):''}${!closed&&t.sourceValid&&!t.suggestionInvalid?`<button class="btn" type="button" data-copy="${idx}">复制草稿</button>`:''}</div>
      <div class="feedback-grid">${[['accuracy','事实准确'],['applicability','当前适用'],['adoption','实际采纳']].map(([key,label])=>`<div>${label}：${['yes','no'].map(v=>`<button type="button" class="btn" aria-pressed="${t.feedback[key]===v}" data-feedback="${key}" data-value="${v}" data-id="${t.uid}">${v==='yes'?'是':'否'}</button>`).join('')}</div>`).join('')}</div>
      <ol class="history">${t.history.map(h=>`<li>${h.day} · ${esc(h.text)}</li>`).join('') || '<li>待核实来源与可行方案。</li>'}</ol>
    </details></div></div></div></article>`;
}

function pagerHtml(page, pages, kind) {
  if (pages <= 1) return '';
  const nums = [];
  for (let p = 1; p <= pages; p++) {
    if (p === 1 || p === pages || Math.abs(p - page) <= 1) nums.push(p);
    else if (nums[nums.length - 1] !== '…') nums.push('…');
  }
  return `<button type="button" class="pg" data-${kind}-page="${page - 1}" ${page === 1 ? 'disabled' : ''} aria-label="上一页">‹</button>` +
    nums.map(p => p === '…' ? '<span class="meta">…</span>' : `<button type="button" class="pg" data-${kind}-page="${p}" ${p === page ? 'aria-current="page"' : ''}>${p}</button>`).join('') +
    `<button type="button" class="pg" data-${kind}-page="${page + 1}" ${page === pages ? 'disabled' : ''} aria-label="下一页">›</button>`;
}

function renderTasks() {
  const n = W.counts(state.session);
  $('today-sub').textContent = `普通事项每日预算 ${state.session.budget} 条 · 完成不补位 · 紧急事项单列`;
  $('done-label').textContent = `今日已处理 ${n.handled} · 已解决 ${n.resolved} · 已终止 ${n.cancelled}`;
  $('done-bar').style.width = `${Math.min(100,n.handled/Math.max(1,state.session.admissions[state.session.day].length+n.urgent)*100)}%`;
  $('view-tabs').innerHTML = [['focus','待我处理'],['progress','推进中'],['ended','已结束']].map(([k,l])=>`<button type="button" class="btn" aria-pressed="${state.view===k}" data-view="${k}">${l} ${n[k]}</button>`).join('');
  $('ended-filter').hidden = state.view !== 'ended';
  $('coach').innerHTML = state.persona==='junior'?'<div class="coach"><p>新人建议：先核实客户需求和已作承诺；没有新增需求时可以保持等待。</p></div>':'';
  let shown = state.tasks.filter(t=>W.group(state.session,t)===state.view && (state.view!=='ended'||state.endedFilter==='all'||t.status===state.endedFilter));
  shown.sort((a,b)=>a.p-b.p || (state.session.focus==='需求确认' ? Number(b.type==='inquiry')-Number(a.type==='inquiry') : state.session.focus==='复购核实' ? Number(b.type==='reorder')-Number(a.type==='reorder') : 0));
  const pages = Math.max(1,Math.ceil(shown.length/TASK_PAGE)); state.taskPage=Math.min(state.taskPage,pages);
  $('task-list').innerHTML=shown.slice((state.taskPage-1)*TASK_PAGE,state.taskPage*TASK_PAGE).map(t=>taskHtml(t,state.tasks.indexOf(t))).join('')||'<div class="empty-done">当前视图没有事项。等待与暂停的工作保留在「推进中」。</div>';
  $('today-foot').innerHTML=`候选 ${n.queued} 条 · 今日普通已领取 ${state.session.admissions[state.session.day].length}<button class="link-btn" data-claim type="button" ${n.queued?'':'disabled'}>主动再领一条</button>`;
  $('task-pager').innerHTML=pagerHtml(state.taskPage,pages,'task');
}

/* ── 全部客户：固定高度 + 吸顶表头 + 分页 ── */
function nextStep(c) {
  const t = state.tasks.find(x => x.c === c && !W.CLOSED.has(x.status));
  if (t) return `<span class="pill ${t.tone}">${W.LABELS[t.status]}</span>`;
  return { reorder: '<span class="meta">需求待核实</span>', active: '<span class="meta">保持节奏</span>', new: '<span class="meta">推动首单</span>', wake: '<span class="meta">了解放缓原因</span>', sleep: '<span class="meta">按需恢复</span>' }[c.seg];
}
const enrichLabel = c => ({ queued: '排队中', running: '补全中', done: '有新结果' }[state.enrich[c.id]?.status] || '');

function filteredRows() {
  const q = state.q.trim().toLowerCase();
  const rows = state.book.filter(c => (!state.seg || c.seg === state.seg) && (!q || `${c.name} ${c.country} ${c.fam} ${c.contact}`.toLowerCase().includes(q)));
  const inf = v => v == null ? 1e9 : v;
  const sorters = { value: (a, b) => b.total - a.total, order: (a, b) => inf(b.lastOrderDays) - inf(a.lastOrderDays), contact: (a, b) => b.lastContactDays - a.lastContactDays, profile: (a, b) => a.completeness - b.completeness };
  return rows.sort(sorters[state.sort]);
}

function renderTable(play) {
  const rows = filteredRows();
  document.querySelectorAll('th button[data-sort]').forEach(b => b.dataset.sort === state.sort ? b.setAttribute('aria-sort', 'descending') : b.removeAttribute('aria-sort'));
  const pages = Math.max(1, Math.ceil(rows.length / state.pageSize));
  state.page = Math.min(state.page, pages);
  const slice = rows.slice((state.page - 1) * state.pageSize, state.page * state.pageSize);
  const thin = rows.filter(c => c.completeness < 60 && !state.enrich[c.id]).length;
  const bb = $('batch-enrich'); bb.textContent = thin ? `批量补全资料 · ${thin} 位` : '资料都已补全'; bb.disabled = !thin;
  $('filter-note').innerHTML = state.seg ? `只看「${SEG[state.seg].name}」<button class="link-btn" type="button" data-clear-seg>清除</button>` : '';
  const tbody = $('rows');
  tbody.classList.toggle('stagger-rows', Boolean(play) && !REDUCED);
  tbody.innerHTML = slice.map((c, i) => {
    const max = Math.max(...c.monthly, 1);
    const spark = c.monthly.map(v => v ? `<i style="height:${Math.max(3, v / max * 22)}px"></i>` : '<i class="zero"></i>').join('');
    const ratio = c.orders.length >= 2 && c.lastOrderDays != null ? c.lastOrderDays / c.cycle : null;
    const orderCell = c.lastOrderDays == null ? '<span class="meta">未成交</span>' : `<span class="days ${ratio && ratio > 1 ? 'hot' : ''}">${c.lastOrderDays} 天</span>${ratio ? `<span class="mini-cycle" title="平均周期 ${c.cycle} 天"><i class="${ratio > 1 ? 'over' : ''}" style="width:${Math.min(ratio, 1) * 100}%"></i></span>` : ''}`;
    const el = enrichLabel(c);
    return `<tr data-open="${c.id}" tabindex="0" style="--i:${i}">
      <td><span class="cname">${esc(c.name)}</span><span class="cmeta">${esc(c.country)} · ${esc(c.type)} · ${esc(c.fam.split(' ')[1] || c.fam)}</span></td>
      <td><span class="pill muted" style="border-color:transparent;color:var(--ink)"><span style="display:inline-block;width:7px;height:7px;border-radius:50%;background:${SEG[c.seg].color};margin-right:5px"></span>${SEG[c.seg].name}</span></td>
      <td><div class="spark" aria-label="近12个月订单">${spark}</div></td>
      <td class="num">${c.total ? fmtMoney(c.total) : '—'}<div class="cmeta">${c.orders.length} 单</div></td>
      <td>${orderCell}</td>
      <td><span class="days ${c.lastContactDays > 60 ? 'hot' : ''}">${c.lastContactDays} 天</span></td>
      <td><span class="ring" style="--p:${c.completeness}" title="资料完整度 ${c.completeness}%"><span>${c.completeness}</span></span>${el ? `<span class="enrich-chip">${el}</span>` : ''}</td>
      <td>${nextStep(c)}</td>
    </tr>`;
  }).join('') || `<tr><td colspan="8" class="meta" style="text-align:center;padding:40px">没有符合条件的客户，换个关键词或清除分层筛选</td></tr>`;
  const from = rows.length ? (state.page - 1) * state.pageSize + 1 : 0;
  $('table-foot').innerHTML = `<span class="tnum">第 ${from}–${Math.min(state.page * state.pageSize, rows.length)} 位，共 ${rows.length} 位</span>`;
  $('table-pager').innerHTML = `<select id="page-size" aria-label="每页条数">${[20, 50, 100].map(n => `<option value="${n}" ${n === state.pageSize ? 'selected' : ''}>${n} 条/页</option>`).join('')}</select>` + pagerHtml(state.page, pages, 'table');
}

/* ── 作战卡 ── */
function judge(c) {
  const o = c.orders[0];
  const famShare = c.orders.length ? Math.round(c.orders.filter(x => x.family === o.family).length / c.orders.length * 100) : 0;
  const t = state.tasks.find(x => x.c === c && !W.CLOSED.has(x.status));
  if (t && t.type === 'inquiry') return { title: '先回复询盘，再顺带确认补货', body: `客户昨晚询问 ${c.color} ${c.len} 现货，这是询价事实，采购需求尚待确认。先核实当前报价和交期；她过去 ${famShare}% 的订单都是 ${o.family.split(' ')[0]}，可以一起问是否补货。`, level: '依据充分', type: 'inquiry' };
  if (t && t.type === 'quote') return { title: '跟进报价，问清卡在哪里', body: `报价 4 个工作日没有回复。她一般 ${c.cycle} 天下一单，现在不算晚。先问价格还是交期有顾虑，不要急着降价。`, level: '依据充分', type: 'quote' };
  if (t && t.type === 'sample') return { title: '收集样品测试反馈', body: `样品已签收 9 天，约定的测试时间到了。问具体的问题（掉发、色差、手感），比问“觉得怎么样”更容易拿到有用反馈。`, level: '依据充分', type: 'sample' };
  const map = {
    reorder: () => ({ title: '进入复购观察窗口', body: `过去 ${c.orders.length} 单里 ${famShare}% 是 ${o.family.split(' ')[0]}，常用 ${o.color} ${o.length}，平均 ${c.cycle} 天一单，现在是第 ${c.lastOrderDays} 天。这是历史节奏推算，当前库存与采购计划未知；先确认需求。`, level: c.orders.length >= 4 ? '依据充分' : '依据有限，样本较少', type: 'reorder' }),
    wake: () => ({ title: '采购放缓，先问原因', body: `此前平均 ${c.cycle} 天一单，已经 ${c.lastOrderDays} 天没有下单。可能转向了其他供应商，也可能是库存积压。第一次联系先问上批货卖得怎样，不要直接推新品。`, level: '依据有限，缺少竞品信息', type: 'wake' }),
    active: () => ({ title: '关系健康，保持节奏', body: `近 ${c.lastContactDays} 天内有沟通，下单节奏正常。下次联系时可以顺带推荐同色系新品（${c.color}）。`, level: '依据充分', type: 'active' }),
    new: () => ({ title: '还没成交，推动试单', body: `询过 ${c.fam.split(' ')[0]}，但还没下单。新客户常见的顾虑是起订量和质量。可核实当前试单政策，不能直接把历史起订量当作本次承诺。`, level: '依据有限，只有询盘记录', type: 'first' }),
    sleep: () => ({ title: '长期没有互动，低成本触达', body: `${c.lastContactDays} 天没有联系。先检查沟通偏好与历史约定；没有有效新信息时保持等待。`, level: '依据有限', type: c.orders.length ? 'wake' : 'first' }),
  };
  return map[c.seg]();
}

function barChart(c) {
  const W = 520, H = 170, L = 40, B = 24, T = 10;
  const max = Math.max(...c.monthly, 1);
  const step = max > 20000 ? 10000 : max > 8000 ? 5000 : max > 3000 ? 2000 : 1000;
  const top = Math.ceil(max / step) * step;
  const bw = (W - L - 8) / 12;
  const months = Array.from({ length: 12 }, (_, i) => { const d = new Date(TODAY.getFullYear(), TODAY.getMonth() - 11 + i, 1); return `${d.getMonth() + 1}月`; });
  let g = '';
  for (let v = 0; v <= top; v += step) { const y = T + (H - T - B) * (1 - v / top); g += `<line class="grid-line" x1="${L}" x2="${W}" y1="${y}" y2="${y}"/><text x="${L - 6}" y="${y + 3}" text-anchor="end">${v ? '$' + v / 1000 + 'k' : '0'}</text>`; }
  c.monthly.forEach((v, i) => {
    const h = v ? Math.max(2, (H - T - B) * v / top) : 2;
    const x = L + 4 + i * bw;
    g += `<rect class="bar-rect ${v ? '' : 'zero'}" x="${x + 3}" y="${H - B - h}" width="${bw - 6}" height="${h}" rx="3"><title>${months[i]} ${v ? '$' + v.toLocaleString() : '无订单'}</title></rect>`;
    if (i % 2 === 1 || i === 11) g += `<text x="${x + bw / 2}" y="${H - 8}" text-anchor="middle">${months[i]}</text>`;
  });
  return `<svg viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="近12个月订单金额">${g}</svg>`;
}

function cycleLine(c) {
  if (c.orders.length < 2) return '<p class="meta">订单不足 2 笔，还算不出采购周期。</p>';
  const W = 860, H = 64, span = Math.min(Math.max(...c.orders.map(o => o.days)) + 20, 720), fwd = Math.max(20, Math.round(c.cycle * 1.5 - c.lastOrderDays + 15));
  const x = days => Math.min(W - 12, Math.max(12, 12 + (W - 24) * (span - days) / (span + fwd)));
  const w0 = x(c.lastOrderDays - c.cycle * 0.85), w1 = x(c.lastOrderDays - c.cycle * 1.5);
  let g = `<line class="tl-axis" x1="12" x2="${W - 12}" y1="30" y2="30"/>`;
  g += `<rect class="tl-window" x="${Math.min(w0, w1)}" y="14" width="${Math.abs(w1 - w0)}" height="32" rx="6"/>`;
  g += `<text x="${(w0 + w1) / 2}" y="10" text-anchor="middle">预计下单窗口</text>`;
  c.orders.filter(o => o.days <= span).forEach(o => { g += `<circle class="tl-dot" cx="${x(o.days)}" cy="30" r="6"><title>${fmtYMD(o.date)} · ${o.id} · $${o.amount.toLocaleString()}</title></circle>`; });
  g += `<line class="tl-today" x1="${x(0)}" x2="${x(0)}" y1="12" y2="50"/><text x="${x(0)}" y="62" text-anchor="middle">今天</text>`;
  return `<svg viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="采购周期时间轴">${g}</svg>`;
}

function prefBars(c) {
  if (!c.orders.length) return '<p class="meta">还没有成交订单。询盘里提到的产品会显示在「档案」页。</p>';
  const by = {}, byColor = {};
  c.orders.forEach(o => { by[o.family] = (by[o.family] || 0) + o.amount; byColor[o.color] = (byColor[o.color] || 0) + o.amount; });
  const rows = obj => Object.entries(obj).sort((a, b) => b[1] - a[1]).slice(0, 4).map(([k, v]) => `<div class="pref-row"><span>${esc(k)}</span><span class="t"><i style="width:${v / c.total * 100}%"></i></span><span>${Math.round(v / c.total * 100)}%</span></div>`).join('');
  return `<div class="pref"><div class="meta">产品族 · 按金额</div>${rows(by)}<div class="meta" style="margin-top:6px">颜色 · 按金额</div>${rows(byColor)}</div>`;
}

function messages(c) {
  const d = n => fmtDate(daysAgo(c.lastContactDays + n));
  const o = c.orders[0];
  const list = [
    { t: d(0), ch: 'WhatsApp', who: c.contact, text: o ? `Thanks, got the ${o.color} ${FAMILY_EN[o.family]}. Customers like the density.` : `Do you have ${c.color} ${c.len} in stock? What's the MOQ?`, note: o ? 'AI 提取：客户认可密度 → 已加入「偏好」候选' : 'AI 提取：关注起订量 → 首单顾虑' },
    { t: d(3), ch: 'WhatsApp', who: '我', text: o ? `Tracking number DHL 3312 7788 90, ETA 5 days.` : `Hi ${c.contact}, MOQ is 10 pcs for mixed colors. Price list attached.` },
    { t: d(9), ch: '邮件', who: c.contact, text: o ? `Please confirm the invoice, we'll pay by T/T this week.` : `We are a ${c.type === '沙龙' ? 'salon' : 'shop'} in ${c.city}, looking for a stable supplier.` },
    { t: d(20), ch: '阿里巴巴', who: c.contact, text: `Inquiry: ${FAMILY_EN[c.fam]}, ${c.color}, ${c.len}, quantity 30-50 pcs.` },
  ];
  return `<div class="msgs">${list.map(m => `<div class="msg"><time>${m.t}</time><div><div class="who">${esc(m.who)} <span class="pill muted">${m.ch}</span></div><p>${esc(m.text)}</p>${m.note ? `<div class="ai-note">${esc(m.note)}</div>` : ''}</div></div>`).join('')}</div>`;
}

/* 一键补全：对应 4428ebc0 的 private-enrichment-v1 四项重点 */
const ENRICH_STEPS = [['site', '官网与主体'], ['biz', '公司业务'], ['contact', '公开联系方式'], ['product', '主营产品']];
function enrichFinds(c) {
  const phoneOld = `${c.dial} 555-0${String(100 + c.id % 900).slice(-3)}`;
  const phoneNew = `${c.dial} 555-0${String(199 + c.id % 700).slice(-3)}`;
  return [
    { key: 'site', label: '官网', value: `www.${c.slug}.com`, src: `官网首页 · 9月30日采集`, url: `https://www.${c.slug}.com`, note: '页脚公司名与客户名一致，主体已核实' },
    { key: 'biz', label: '公司业务', value: `${c.type}，${c.city} 有 ${1 + c.id % 3} 家门店，零售和批发都做，线上开 Shopify 店`, src: '官网 About 页 · Google 商家信息', url: `https://www.${c.slug}.com/about` },
    { key: 'contact', label: '公开联系方式', value: `sales@${c.slug}.com`, src: '官网 Contact 页', url: `https://www.${c.slug}.com/contact`, conflict: { old: phoneOld, oldSrc: '小满客户资料', neu: phoneNew, neuSrc: '官网 Contact 页' } },
    { key: 'product', label: '主营产品', value: `HD Lace Wig、${c.fam.split(' ')[0]}；主推 ${c.color}`, src: `官网产品页 · Instagram @${c.slug}`, url: `https://www.${c.slug}.com/collections` },
  ];
}

function startEnrich(id, silent) {
  const c = state.book.find(x => x.id === id);
  if (!c || (state.enrich[id] && state.enrich[id].status !== 'failed')) return;
  const e = state.enrich[id] = { status: 'queued', step: -1, finds: enrichFinds(c), decided: {}, adopted: {} };
  const tick = () => {
    if (state.enrich[id] !== e) return;
    if (e.status === 'queued') { e.status = 'running'; e.step = 0; }
    else if (e.step < ENRICH_STEPS.length - 1) e.step++;
    else { e.status = 'done'; }
    save(); refreshEnrich(id);
    if (e.status !== 'done') setTimeout(tick, 1100);
    else if (!silent || state.open === id) toast(`${c.name} 的资料补全完成，有 ${e.finds.length} 条新发现待你确认`);
  };
  setTimeout(tick, silent ? 900 + Math.random() * 3000 : 900);
  refreshEnrich(id);
}

function refreshEnrich(id) {
  if (state.open === id) {
    const box = $('enrich-box');
    if (box) box.outerHTML = enrichCard(state.book.find(x => x.id === id));
    const chip = $('dr-enrich-chip'); if (chip) chip.innerHTML = enrichChip(id);
  }
  renderTable();
}
const enrichChip = id => { const s = state.enrich[id]?.status; return s === 'done' ? '<span class="pill info">补全有新结果</span>' : s ? '<span class="pill warn">资料补全中…</span>' : ''; };

function enrichCard(c) {
  const e = state.enrich[c.id];
  const head = `<div class="enrich-intro"><div><h4 style="margin:0">一键补全资料</h4><p>本地模拟官网、公司业务、公开联系方式和主营产品的补全结果。已有资料不会被覆盖，每条新发现都附来源链接，由你确认后才写入档案。</p></div>`;
  if (!e) return `<section class="panel enrich" id="enrich-box">${head}<button type="button" class="btn primary" data-enrich="${c.id}">一键补全</button></div><p class="meta">资料完整度 ${c.completeness}%。本地模拟约 5 秒；没有真实检索或后台通知。</p></section>`;
  const steps = `<div class="steps">${ENRICH_STEPS.map(([k, l], i) => `<div class="step ${e.status === 'done' || i < e.step ? 'done' : i === e.step ? 'run' : ''}"><i></i>${l}</div>`).join('')}</div>`;
  if (e.status !== 'done') return `<section class="panel enrich" id="enrich-box">${head}<span class="pill warn">${e.status === 'queued' ? '排队中' : '正在核实'}</span></div>${steps}<div class="shimmer"></div><p class="meta">可以关掉卡片继续工作，完成后会提醒你。</p></section>`;
  const pending = e.finds.filter(f => !e.decided[f.key]).length;
  const finds = e.finds.map((f, i) => {
    const decided = e.decided[f.key];
    const acts = decided ? `<span class="pill ${decided === 'ignore' ? 'muted' : 'ok'}">${{ adopt: '已写入档案', keep: '保留原值', neu: '已换成新值', ignore: '已忽略' }[decided]}</span>`
      : f.conflict ? `<div class="btn-row"><button type="button" class="btn primary" data-find="${f.key}" data-act="neu">用新值</button><button type="button" class="btn" data-find="${f.key}" data-act="keep">保留原值</button></div>`
      : `<div class="btn-row"><button type="button" class="btn primary" data-find="${f.key}" data-act="adopt">写入档案</button><button type="button" class="btn ghost" data-find="${f.key}" data-act="ignore">忽略</button></div>`;
    return `<div class="find" style="--i:${i}"><dt>${f.label}</dt><div><div class="val">${esc(f.value)}</div>${f.note ? `<div class="src">${esc(f.note)}</div>` : ''}
      ${f.conflict ? `<div class="conflict"><div><small>电话 · 原值（${esc(f.conflict.oldSrc)}）</small>${esc(f.conflict.old)}</div><div class="new"><small>电话 · 新值（${esc(f.conflict.neuSrc)}）</small>${esc(f.conflict.neu)}</div></div>` : ''}
      <div class="src">来源：${esc(f.src)} · <a href="${f.url}" target="_blank" rel="noopener noreferrer" data-fake-link>打开来源</a></div></div>${acts}</div>`;
  }).join('');
  return `<section class="panel enrich" id="enrich-box">${head}<span class="pill ${pending ? 'info' : 'ok'}">${pending ? `${pending} 条待确认` : '全部处理完'}</span></div>
    <dl class="finds" style="margin:0">${finds}</dl>
    <p class="meta">这里只演示逐项选择。生产仍按现有质量复核流程；改为抽检尚待确认，身份类字段需走治理契约。</p></section>`;
}

function profileFields(c) {
  const o = c.orders[0];
  const ad = state.enrich[c.id]?.adopted || {};
  const fields = [
    ['公司类型', c.type], ['主营市场', `${c.country} · ${c.city}`], ['联系人', `${c.contact}（采购负责人）`], ['沟通渠道', 'WhatsApp 优先，邮件发合同'],
    ['官网', ad.site || null, null, '可以用上方「一键补全」自动查找'],
    ['公开联系方式', ad.contact || null],
    ['公司业务', ad.biz || null],
    ['主力产品', o ? o.family : (ad.product || null), !o && !ad.product ? { v: c.fam, src: `阿里询盘 · ${fmtDate(daysAgo(c.lastContactDays + 20))}：“${FAMILY_EN[c.fam]}, 30-50 pcs”` } : null],
    ['偏好颜色', c.id % 3 === 0 ? c.color : null, c.id % 3 !== 0 ? { v: c.color, src: `WhatsApp · ${fmtDate(daysAgo(c.lastContactDays))}：多次提到 ${c.color}` } : null],
    ['常用长度', c.id % 2 === 0 ? c.len : null, null, '下次可以问：“哪个长度卖得最快？”'],
    ['价格敏感度', c.id % 4 === 0 ? '中，接受 $' + c.unit + '/件' : null, c.id % 4 !== 0 ? { v: '较高，询价时会对比 2 家', src: `邮件 · ${fmtDate(daysAgo(c.lastContactDays + 9))}：“your price is higher than…”` } : null],
    ['付款方式', o ? 'T/T 30% 预付' : null, null, '首单前确认：T/T 还是 PayPal'],
  ];
  fields.forEach((f,i)=>{ const v=state.edits[c.id]?.[i]; if(v!==undefined){f[1]=v;f[2]=null;} });
  return `<dl class="fields" style="margin:0">${fields.map(([k, v, pend, ask], i) => `<div class="field"><dt>${k}</dt><dd>
    ${pend ? `<div class="pending"><strong>${esc(pend.v)}</strong><span class="src">AI 从 ${esc(pend.src)}</span><span class="acts"><button type="button" class="btn primary" data-pend-ok="${i}">确认</button><button type="button" class="btn ghost" data-pend-no="${i}">不对</button></span></div>`
      : `<button type="button" class="fv ${v ? '' : 'empty'} ${v && Object.values(ad).includes(v) ? 'fresh' : ''}" data-edit="${i}">${v ? esc(v) : '点击补充'}</button>${!v && ask ? `<div class="ask">${esc(ask)}</div>` : ''}`}
  </dd></div>`).join('')}</dl>`;
}

function plans(c) {
  const tasks=state.tasks.filter(t=>t.customerId===c.id);
  return tasks.map(t=>taskHtml(t,state.tasks.indexOf(t))).join('') || '<p>当前没有明确目标事项。分层只是判断线索，不自动安排联系。</p>';
}

function renderDrawer(swap) {
  const c = state.book.find(x => x.id === state.open);
  const dr = $('drawer');
  if (!c) return;
  const j = judge(c);
  const item = state.tasks.find(t=>t.customerId===c.id&&!W.CLOSED.has(t.status));
  const ratio = c.lastOrderDays != null && c.orders.length >= 2 ? c.lastOrderDays / c.cycle : null;
  const tabs = [['overview', '概况'], ['talk', '沟通'], ['profile', '档案'], ['plan', '计划']];
  let body = '';
  if (state.tab === 'overview') body = `
    <section class="panel"><h4>当前经营目标</h4><p>${esc(item?.goal || item?.label || '确认真实需求，兑现已有承诺')}</p><p>已确认：历史订单与来源记录。待核实：当前库存、采购意向与适用交期。</p>${item?`<p>${item.uid} · ${W.LABELS[item.status]} · 下次核验 ${item.nextCheck}</p><button class="btn primary" data-tab="plan" type="button">查看事项与协作进展</button>`:''}</section>
    <section class="card ai">
      <div class="ai-top"><span class="ai-label">AI 判断 · ${esc(j.level)}</span><button type="button" class="link-btn" data-evidence aria-expanded="false">看依据</button></div>
      <h3>${esc(j.title)}</h3>
      <p>${esc(j.body)}</p>
      <div class="evidence" id="evidence">${c.orders.length ? `<table><tbody>${c.orders.slice(0, 4).map(o => `<tr><td class="tnum">${fmtYMD(o.date)}</td><td>${o.id}</td><td>${esc(o.family.split(' ')[0])} · ${esc(o.color)} · ${esc(o.length)}</td><td class="num">${o.qty} 件 × $${o.unit}</td><td class="num">$${o.amount.toLocaleString()}</td></tr>`).join('')}</tbody></table>` : '询盘和沟通记录见「沟通」页。'}</div>
      <p class="meta">历史价格仅作参考；当前承诺需核实。具体草稿与反馈在「计划」中的对应事项。</p>
    </section>
    <div class="grid2">
      <section class="panel"><h4>近 12 个月订单 <small>按月金额 · 美元</small></h4>${c.orders.length ? barChart(c) : '<p class="meta">还没有成交订单。</p>'}</section>
      <section class="panel"><h4>买什么 <small>全部订单</small></h4>${prefBars(c)}</section>
    </div>
    <section class="panel"><h4>采购周期 <small>圆点是历史订单，金色区域是预计下单窗口</small></h4>${cycleLine(c)}</section>`;
  if (state.tab === 'talk') body = `<section class="panel"><h4>沟通记录 <small>WhatsApp、邮件、阿里巴巴合并按时间排列</small></h4>${messages(c)}<h4>本轮事项登记（本地模拟，未发送）</h4>${state.tasks.filter(t=>t.customerId===c.id).flatMap(t=>t.history.map(h=>`<p>${h.day} · ${esc(h.text)}</p>`)).join('') || '<p>尚无登记。</p>'}</section>`;
  if (state.tab === 'profile') body = `${enrichCard(c)}<section class="panel"><h4>客户档案 <small>点击任意值直接修改；黄色是 AI 从沟通里找到的候选值，确认后才写入</small></h4>${profileFields(c)}</section><section class="panel"><h4>客户服务资产</h4><p>选品页 / 采购入口：尚未登记。使用与下单数据：尚未接入。</p><p class="meta">有可靠来源后再评价服务结果，本轮不建设网站平台。</p></section>`;
  if (state.tab === 'plan') body = `<section class="panel"><h4>目标事项与下一步</h4>${plans(c)}</section>`;
  dr.innerHTML = `
    <div class="dr-head">
      <div class="dr-title">
        <div><h2 id="dr-name">${esc(c.name)}</h2><div class="meta"><span>${esc(c.country)} · ${esc(c.type)} · ${esc(c.contact)}</span><span class="pill muted"><span style="display:inline-block;width:7px;height:7px;border-radius:50%;background:${SEG[c.seg].color};margin-right:5px"></span>${SEG[c.seg].name}</span><span class="pill muted">资料 ${c.completeness}%</span><span id="dr-enrich-chip">${enrichChip(c.id)}</span></div></div>
        <button type="button" class="close" data-close aria-label="关闭">×</button>
      </div>
      <div class="stats">
        <div class="stat"><span>累计金额</span><strong>${c.total ? fmtMoney(c.total) : '—'}</strong></div>
        <div class="stat"><span>订单数</span><strong>${c.orders.length}</strong></div>
        <div class="stat"><span>平均周期</span><strong>${c.orders.length >= 2 ? c.cycle + ' 天' : '—'}</strong></div>
        <div class="stat"><span>距上次下单</span><strong class="${ratio && ratio > 1 ? 'hot' : ''}">${c.lastOrderDays != null ? c.lastOrderDays + ' 天' : '未成交'}</strong></div>
        <div class="stat"><span>距上次联系</span><strong class="${c.lastContactDays > 60 ? 'hot' : ''}">${c.lastContactDays} 天</strong></div>
      </div>
      <div class="dr-tabs" role="tablist"><span class="ink" aria-hidden="true"></span>${tabs.map(([k, l]) => `<button type="button" role="tab" data-tab="${k}" aria-selected="${state.tab === k}">${l}</button>`).join('')}</div>
    </div>
    <div class="dr-body ${swap && !REDUCED ? 'swap' : ''}">${body}</div>`;
  placeInk();
}
function placeInk() {
  const tabs = document.querySelector('.dr-tabs');
  if (!tabs) return;
  const sel = tabs.querySelector('[aria-selected="true"]');
  const ink = tabs.querySelector('.ink');
  ink.style.width = sel.offsetWidth + 'px';
  ink.style.transform = `translateX(${sel.offsetLeft}px)`;
}

let lastFocus = null;
function openDrawer(id) {
  lastFocus = document.activeElement;
  state.open = id; state.tab = 'overview'; renderDrawer(true);
  const dr = $('drawer');
  $('main').inert = true;
  dr.classList.add('open'); dr.setAttribute('aria-hidden', 'false');
  $('scrim').classList.add('open');
  dr.querySelector('[data-close]').focus({ preventScroll: true });
  requestAnimationFrame(placeInk);
}
function closeDrawer() {
  const dr = $('drawer');
  dr.classList.remove('open'); dr.setAttribute('aria-hidden', 'true');
  $('scrim').classList.remove('open');
  state.open = null;
  $('main').inert = false;
  lastFocus?.focus?.({ preventScroll: true });
}

/* ── 反馈 ── */
let toastTimer;
function toast(text, undo) {
  const el = $('toast');
  $('toast-text').textContent = text;
  const u = $('toast-undo');
  u.hidden = !undo; u.onclick = () => { undo && undo(); el.classList.add('hide'); };
  el.classList.remove('hide');
  clearTimeout(toastTimer); toastTimer = setTimeout(() => el.classList.add('hide'), 4200);
}

function closeMenus() { document.querySelectorAll('.menu').forEach(m => { m.hidden = true; }); document.querySelectorAll('[data-menu]').forEach(b => b.setAttribute('aria-expanded', 'false')); }
const toTop = id => $(id).scrollTo({top:0,behavior:'instant'});

document.addEventListener('click', e => {
  if (e.target.closest('[data-fake-link]')) { e.preventDefault(); toast('原型里的来源链接是示例，正式版会打开 Agent 实际访问的页面'); return; }
  const el = e.target.closest('button, tr[data-open]');
  if (!el) { closeMenus(); return; }
  const d = el.dataset;
  if (handleWorkbench(d, el)) return;
  if (d.persona) { if (d.persona !== state.persona) load(d.persona); return; }
  if (el.id === 'rules-toggle') { const r = $('rules'); r.classList.toggle('open'); el.setAttribute('aria-expanded', r.classList.contains('open')); return; }
  if (el.id === 'batch-enrich') {
    const targets = filteredRows().filter(c => c.completeness < 60 && !state.enrich[c.id]);
    targets.forEach(c => startEnrich(c.id, true));
    toast(`已为 ${targets.length} 位资料不全的客户排队补全，完成后在「资料」列和作战卡里确认`);
    return;
  }
  if (d.seg) { state.seg = state.seg === d.seg ? null : d.seg; state.page = 1; renderSegments(); renderTable(true); toTop('table-scroll'); return; }
  if (d.segJump) { state.seg = d.segJump; state.page = 1; renderSegments(); renderTable(true); document.querySelector('.pane.all').scrollIntoView({ behavior: REDUCED ? 'auto' : 'smooth', block: 'start' }); return; }
  if ('clearSeg' in d) { state.seg = null; renderSegments(); renderTable(true); return; }
  if (d.sort) { state.sort = d.sort; state.page = 1; renderTable(true); toTop('table-scroll'); return; }
  if (d.tablePage) { state.page = Number(d.tablePage); renderTable(true); toTop('table-scroll'); return; }
  if (d.taskPage) { state.taskPage = Number(d.taskPage); renderTasks(true); toTop('task-scroll'); return; }
  if (d.open !== undefined) { closeMenus(); return openDrawer(Number(d.open)); }
  if (d.toggleDraft !== undefined) { const dr = $('draft-' + d.toggleDraft); dr.classList.toggle('open'); el.setAttribute('aria-expanded', dr.classList.contains('open')); el.textContent = dr.classList.contains('open') ? '收起话术' : '看话术'; return; }
  if (d.copy !== undefined) { copyDraft(Number(d.copy)); return; }
  if (d.close !== undefined) return closeDrawer();
  if (d.tab) { state.tab = d.tab; renderDrawer(true); return; }
  if (d.evidence !== undefined) { const ev = $('evidence'); ev.classList.toggle('open'); el.setAttribute('aria-expanded', ev.classList.contains('open')); el.textContent = ev.classList.contains('open') ? '收起依据' : '看依据'; return; }
  if (d.enrich !== undefined) { startEnrich(Number(d.enrich)); return toast('已提交补全，完成后会提醒你'); }
  if (d.find) {
    const e = state.enrich[state.open]; const f = e.finds.find(x => x.key === d.find);
    e.decided[f.key] = d.act;
    if (d.act === 'adopt') e.adopted[f.key] = f.value;
    if (d.act === 'neu') e.adopted[f.key] = `${f.value} · ${f.conflict.neu}`;
    if (d.act === 'keep') e.adopted[f.key] = `${f.value} · ${f.conflict.old}`;
    const c = state.book.find(x => x.id === state.open);
    if (d.act !== 'ignore') c.completeness = Math.min(100, c.completeness + 8);
    save(); renderDrawer(false); renderTable();
    return toast({ adopt: `已写入档案「${f.label}」，保留来源链接`, neu: '已换成官网上的新电话，原值保留在本地冲突对照中', keep: '保留原值，新值已记为不采纳', ignore: '已忽略这条发现' }[d.act]);
  }
  if (d.toast) return toast(d.toast);
  if (d.pendOk !== undefined || d.pendNo !== undefined) {
    const i=d.pendOk ?? d.pendNo; const box=el.closest('.pending');
    (state.edits[state.open] ||= {})[i]=d.pendOk!==undefined?box.querySelector('strong').textContent:'';
    save(); renderDrawer(); return toast('已保存本地演示选择；未写入生产档案');
  }
  if (d.edit !== undefined) {
    const cur = el.classList.contains('empty') ? '' : el.textContent;
    const input = document.createElement('input'); input.value = cur; input.id = 'edit-field-' + d.edit; input.setAttribute('aria-label', '编辑字段');
    el.replaceWith(input); input.focus();
    const commit = () => { const v = input.value.trim(); (state.edits[state.open] ||= {})[d.edit]=v; save(); const b = document.createElement('button'); b.type = 'button'; b.className = 'fv' + (v ? '' : ' empty') + (v && v !== cur ? ' fresh' : ''); b.dataset.edit = d.edit; b.textContent = v || '点击补充'; input.replaceWith(b); if (v && v !== cur) toast('已保存本地演示值'); };
    input.addEventListener('blur', commit, { once: true });
    input.addEventListener('keydown', ev => { if (ev.key === 'Enter') input.blur(); if (ev.key === 'Escape') { input.value = cur; input.blur(); } });
    return;
  }
  if (d.planOk !== undefined) { el.closest('.plan').querySelector('.btn-row').innerHTML = '<span class="pill ok">已确认</span>'; return; }
  if (d.planSkip !== undefined) { const row = el.closest('.plan'); row.classList.add('done'); row.querySelector('.btn-row').innerHTML = '<span class="pill muted">已跳过</span>'; return; }
});

document.addEventListener('change', e => { if (e.target.id === 'page-size') { state.pageSize = Number(e.target.value); state.page = 1; renderTable(true); toTop('table-scroll'); } });
document.addEventListener('keydown', e => {
  if (e.key === 'Escape' && !$('workbench-dialog').open) { if (state.open != null) closeDrawer(); closeMenus(); }
  if (e.key === 'Enter' && e.target.matches('tr[data-open]')) openDrawer(Number(e.target.dataset.open));
});
window.addEventListener('resize', placeInk);
$('scrim').addEventListener('click', closeDrawer);
$('search').addEventListener('input', e => { state.q = e.target.value; state.page = 1; renderTable(); });

let dialogAction = null;
function showDialog(title,body,submit) {
  dialogAction=submit;
  $('dialog-content').innerHTML=`<h2 id="dialog-title">${title}</h2>${body}<div class="btn-row"><button class="btn" value="cancel" formnovalidate>关闭</button>${submit?'<button class="btn primary" value="save">保存登记</button>':''}</div>`;
  $('workbench-dialog').showModal();
}
function perform(id,op,payload={}) {
  try {
    const receipt=W.act(state.session,id,op,{expectedVersion:W.find(state.session,id).version,...payload});
    refresh();
    toast(receipt.text || '状态已是最新，无重复登记',receipt.undo?()=>{try{W.undo(state.session,receipt.undo);refresh();}catch(e){toast(e.message);}}:null);
  } catch(e) { toast(e.message); }
}
async function copyDraft(idx) {
  try { if(!navigator.clipboard) throw new Error(); await navigator.clipboard.writeText(draftFor(state.tasks[idx].c,state.tasks[idx].type)); toast('已复制草稿；请核实当前条件后再使用'); }
  catch (_) { toast('未能访问剪贴板，请展开草稿后手动复制'); }
}
function handleWorkbench(d,el) {
  if(d.action) {
    if(['resolve','terminate','reopen'].includes(d.action)) {
      const t=W.find(state.session,d.id); const version=t.version;
      const fields=d.action==='resolve'?'<label>实际结果<textarea name="summary" required placeholder="这次事项的目标实际达成了什么？"></textarea></label><label>结果依据<input name="evidence" required placeholder="已有消息 / 源记录编号，原型仅保存本地文本"></label>':'<label>原因与依据<textarea name="reason" required placeholder="说明原因及新事实"></textarea></label>';
      showDialog({resolve:'登记解决结果',terminate:'终止本次事项',reopen:'重开原事项'}[d.action],`<p>${esc(t.goal||t.label)} · ${t.uid}</p>${fields}`,form=>perform(d.id,d.action,{...Object.fromEntries(new FormData(form)),expectedVersion:version}));
    } else perform(d.id,d.action);
    return true;
  }
  if(d.feedback){perform(d.id,d.feedback,{value:d.value});return true;}
  if(d.view){state.view=d.view;state.taskPage=1;renderTasks();return true;}
  if('claim' in d){W.claim(state.session);refresh();toast('已主动增加一条普通事项；当日已领取预算保留');return true;}
  if('advance' in d){W.advance(state.session);refresh();toast(`演示日期推进至 ${state.session.day}，未自动发送或恢复暂停项`);return true;}
  if('reset' in d){showDialog('重置当前演示视角','<p>清除这个视角在本浏览器的演示登记，恢复虚构初始数据。</p>',()=>{closeDrawer();load(state.persona,true);});return true;}
  if('summary' in d){const t=state.tasks.find(t=>t.type==='shipping');showDialog('全员工作台摘要 · 对应关系示意',`<p>共享事项 <b>${t.uid}</b> · ${W.LABELS[t.status]}</p><p>业务员：${t.replyReceived?'已有沟通确认记录，当前方案见事项':'待核实方案及客户回应'}</p><p>跟单：${t.colleagueDone?'已有发运记录，当前安排见事项':'待协调实际发运'}</p><p>设计岗位仅展示自己负责的设计交付，不套用客户复购排序。</p><p class="meta">这里只展示摘要对应关系，不模拟真实岗位权限。来源模块仍维护执行事实。</p><button type="button" class="btn primary" data-summary-open="${t.c.id}">打开同一客户事项</button>`);return true;}
  if(d.summaryOpen!==undefined){$('workbench-dialog').close();openDrawer(Number(d.summaryOpen));state.tab='plan';renderDrawer();return true;}
  if('review' in d){showDialog('本轮复盘 · 当前演示样本',`<p>三个维度独立记录，重复选择不会扩大样本量。</p>${[['accuracy','事实准确'],['applicability','建议适用'],['adoption','行动采纳']].map(([key,label])=>{const n=W.feedbackStats(state.session,key);return `<p>${label}：${n.total?`${Math.round(n.yes/n.total*100)}%（${n.yes}/${n.total}）`:'暂无可评价样本'}</p>`;}).join('')}<p>本轮已解决 ${W.counts(state.session).resolved} · 已终止 ${W.counts(state.session).cancelled}。执行耗时与收益未接入，不能据此推算 AI 创收。</p>`);return true;}
  return false;
}
$('dialog-form').addEventListener('submit',e=>{
  if(e.submitter?.value==='cancel') return;
  if(dialogAction){e.preventDefault();const action=dialogAction; $('workbench-dialog').close();action(e.target);}
});
$('ended-filter').addEventListener('change',e=>{state.endedFilter=e.target.value;state.taskPage=1;renderTasks();});
$('focus-select').addEventListener('change',e=>{state.session.focus=e.target.value;refresh();});
document.addEventListener('keydown',e=>{
  if(e.key==='Tab' && state.open!==null && !$('workbench-dialog').open){
    const nodes=[...$('drawer').querySelectorAll('button,input,select,textarea,summary,[tabindex="0"]')].filter(x=>x.getClientRects().length);
    const first=nodes[0],last=nodes[nodes.length-1];
    if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus();}
    else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus();}
  }
});

load('senior');
})();
