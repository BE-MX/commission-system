/* Read-only local prototype. It never calls Ark, OKKI or any business API. */
const dialog = document.querySelector('#detail-dialog');
const panel = document.querySelector('#detail-panel');
let current = 'partial';
let previewKey = 'partial';
let activeTab = 'order';
let selectedReceipt = null;
let toastTimer;
let returnFocus;
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const money = cents => (cents / 100).toLocaleString('en-US', {minimumFractionDigits:2, maximumFractionDigits:2});
const unitMoney = price => Number(price).toLocaleString('en-US', {minimumFractionDigits:2, maximumFractionDigits:4});
const usd = cents => `USD ${money(cents)}`;
const tag = (label, tone='neutral') => `<span class="tag ${tone}">${esc(label)}</span>`;
const field = (label, value, wide=false) => `<div class="info-field${wide?' wide':''}"><dt>${esc(label)}</dt><dd>${esc(value || '—')}</dd></div>`;
const qty = order => order.items.reduce((n, i) => n + i.quantity, 0);
const countOutbounds = order => order.outbounds.filter(row => row.number).length;
const empty = (symbol, title, explanation) => `<div class="empty-state"><div class="empty-icon" aria-hidden="true">${symbol}</div><h3>${esc(title)}</h3><p>${esc(explanation)}</p></div>`;

const previewListKeys = () => [previewKey,'complete','draft'];
function anomalyMarkup(order, interactive=false) {
  const anomalies=documentAnomalies(order);
  if(!anomalies.length) return '';
  const details=anomalies.map(a=>`${a.label}：${a.messages.join('；')}`).join('；');
  return `<span class="invoice-anomaly${interactive?'':' compact'}" title="${esc(details)}"><span class="anomaly-symbol" aria-hidden="true">!</span>${anomalies.map(a=>interactive?`<button data-anomaly-tab="${a.key}" aria-label="查看${a.label}">${a.label}</button>`:`<span>${a.label}</span>`).join('<span class="anomaly-divider" aria-hidden="true">/</span>')}</span>`;
}
function renderInvoiceList() {
  document.querySelector('#invoice-list').innerHTML=previewListKeys().map(key=>{
    const o=scenarios[key];
    return `<tr><td><button class="text-button invoice-link" data-order="${key}"><span>${o.number} ↗</span>${anomalyMarkup(o)}</button></td><td>${o.customer}<small>${o.company}</small></td><td>${tag(o.type,o.type==='预售单'?'gold':'neutral')}</td><td>${o.date}</td><td class="num">${money(o.total)}</td><td>${tag(o.sync,o.sync==='已同步'?'success':o.sync==='同步失败'?'danger':'neutral')}</td></tr>`;
  }).join('');
}
function renderNavigationAnomalies() {
  const issues=previewListKeys().flatMap(key=>documentAnomalies(scenarios[key]));
  document.querySelectorAll('[data-nav-anomaly]').forEach(badge=>{
    const matches=issues.filter(issue=>issue.key===badge.dataset.navAnomaly);
    badge.hidden=matches.length===0;
    badge.title=matches.map(issue=>`${issue.label}：${issue.messages.join('；')}`).join('；');
    badge.setAttribute('aria-label',matches.length?`${matches[0].label}，请查看异常单据`:'');
  });
}
renderInvoiceList();
renderNavigationAnomalies();

function progressCard(type, order) {
  const isReceipt = type === 'receipt';
  const unavailable = order.restricted || order.unknown;
  const label = isReceipt ? '回款进度' : '出库进度';
  const numerator = isReceipt ? order.effective : order.shipped;
  const denominator = isReceipt ? order.total : qty(order);
  const pct = unavailable || denominator<=0 ? null : Math.min(100, Math.floor(numerator*1000/denominator)/10);
  const complete = !unavailable && denominator>0 && numerator>=denominator;
  const status = unavailable ? (order.restricted ? '无查看权限' : '待核验') : denominator<=0 ? '无进度基数' : isReceipt ? (complete?'已结清':numerator>0?'部分回款':'未回款') : (complete?'全部出库':numerator>0?'部分出库':'未出库');
  const detail = unavailable ? (order.restricted?'申请对应单据查看权限后可查看进度。':'关联单据事实未核验，暂不计算进度。') : isReceipt ? `已生效 ${usd(order.effective)} / ${money(order.total)}` : `已出库 ${order.shipped} / ${qty(order)} 件`;
  const foot = unavailable ? '关联明细与进度口径' : isReceipt ? `待生效 ${usd(order.pending)}` : `待出库 ${qty(order)-order.shipped} 件`;
  return `<button class="progress-card" data-go-tab="${type}"${order.restricted?' disabled':''} aria-label="${label}，${status}${pct==null?'':`，${pct}%`}，查看详情"><div class="metric-head"><span class="metric-label">${isReceipt?'▥':'▱'} ${label}</span>${tag(status,pct===100?'success':unavailable?'neutral':'gold')}</div><div class="progress-numbers"><strong>${pct==null?'—':`${pct}%`}</strong><span>${detail}</span></div><div class="track ${isReceipt?'':'gold'} ${unavailable?'unknown':''}"${pct==null?'':` role="progressbar" aria-label="${label}" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${pct}"`}><span style="width:${pct??0}%"></span></div><div class="progress-foot"><span>${foot}</span>${order.restricted?'':`<span class="link-arrow">查看${isReceipt?'回款':'出库'} →</span>`}</div></button>`;
}

function renderHeader() {
  const o = scenarios[current];
  document.querySelector('#dialog-title').textContent = o.number;
  document.querySelector('#dialog-anomaly').innerHTML = anomalyMarkup(o,true);
  document.querySelector('#header-tags').innerHTML = tag(o.type,'gold') + tag(o.sync,o.sync==='已同步'?'success':o.sync==='同步失败'?'danger':'neutral');
  document.querySelector('#customer-line').innerHTML = `<span class="avatar small">${o.customer[0]}</span><strong>${o.customer}</strong><span>${o.company}</span>${tag(`${o.grade} 级客户`,'neutral')}`;
  document.querySelector('#order-meta').innerHTML = `<span>业务员 <strong>${o.sales}</strong></span><span>发票日期 ${o.date}</span>`;
  document.querySelector('#progress-grid').innerHTML = `<div class="summary-total"><div class="metric-label">订单金额 <span class="tag neutral">USD</span></div><div class="amount"><span class="currency">$</span>${money(o.total)}</div><div class="metric-hint">${qty(o)} 件商品 · ${o.items.length} 行明细${o.type==='预售单'?' · 运费另结':''}</div></div>${progressCard('receipt',o)}${progressCard('outbound',o)}`;
  document.querySelector('#summary-notice').innerHTML = o.unknown ? `<div class="notice"><span>ⓘ</span><span>关联单据核验未完成，回款和出库进度暂不展示。请核对待核验单据，避免按旧金额或数量判断履约情况。</span></div>` : '';
  document.querySelector('#outbound-count').textContent = o.restricted ? '锁定' : countOutbounds(o);
  document.querySelector('#receipt-count').textContent = o.restricted ? '锁定' : o.receipts.length;
  document.querySelector('#footer-context').textContent = '示例数据 · 2026-10-08 14:32（北京时间）';
}

function renderOrder() {
  const o = scenarios[current];
  const totalQty = qty(o);
  panel.innerHTML = `<section class="section basic-fields"><div class="section-heading"><h3>订单信息</h3><button class="text-button" id="copy-number">复制发票号 ⧉</button></div><dl class="info-grid">${field('客户 / 联系人',`${o.company} / ${o.contact}`)}${field('业务员 / 跟单员',`${o.sales} / ${o.merchandiser}`)}${field('订单类型',o.type)}${field('小满订单 ID',o.orderId)}${field('联系邮箱',o.email)}${field('联系电话',o.phone)}${field('付款条款',o.paymentTerm)}${field('发货方式',o.express)}${field('收货地址',o.address,true)}${field('付款方式',o.method)}${field('订单来源','方舟创建')}</dl></section><section><div class="section-heading"><h3>商品明细 <span class="section-caption">${o.items.length} 行 / ${totalQty} 件</span></h3><span class="section-caption">成交单价与行折扣按发票保存值展示 · USD</span></div><div class="table-scroll"><table aria-label="订单商品明细"><thead><tr><th class="row-index">#</th><th>商品 / 规格</th><th class="num">订单数量</th><th class="num">已出库</th><th class="num">成交单价</th><th class="num">行折扣</th><th class="num">金额</th></tr></thead><tbody>${o.items.map((i,index)=>`<tr><td class="row-index">${index+1}</td><td><div class="product-name">${esc(i.name)}</div><div class="product-spec">${esc(i.spec)}</div></td><td class="num">${i.quantity} 件</td><td class="num quantity-note">${o.restricted?'无权限':o.unknown?'待核验':`${i.shipped} 件`}</td><td class="num">${unitMoney(i.unitPrice)}</td><td class="num">${money(i.discount)}</td><td class="num"><strong>${money(i.lineAmount)}</strong></td></tr>`).join('')}</tbody></table><div class="table-total"><span>合计 ${totalQty} 件${o.restricted||o.unknown?'':` · 已出库 ${o.shipped} 件 · 待出库 ${totalQty-o.shipped} 件`}</span><strong>商品净额 ${usd(o.product)}</strong></div></div><div class="order-bottom"><div class="order-remark"><strong>订单备注</strong>${esc(o.remark)}</div><div class="amount-breakdown"><div><span>商品净额</span><strong>${money(o.product)}</strong></div><div><span>包装费</span><strong>${money(o.packaging)}</strong></div><div><span>运费${o.type==='预售单'?'（主单）':''}</span><strong>${money(o.shipping)}</strong></div><div><span>附加费</span><strong>${money(o.surcharge)}</strong></div><div class="grand"><span>发票总额 · USD</span><strong>${money(o.total)}</strong></div></div></div></section>`;
  document.querySelector('#copy-number').addEventListener('click', async () => {
    try { await navigator.clipboard.writeText(o.number); notify('发票号已复制'); }
    catch { notify(`发票号：${o.number}（此浏览器未授予剪贴板权限）`); }
  });
}

function renderOutbound() {
  const o = scenarios[current];
  if (o.restricted) { panel.innerHTML=empty('▱','暂无出库单查看权限','订单信息仍可查看。出库单与发货批次按各自权限及订单归属校验，请申请对应查看权限。');return; }
  if (!o.outbounds.length) { panel.innerHTML=empty('▱','暂无关联出库单',o.sync==='未同步'?'订单尚未同步小满，暂未关联出库单。后续生成或同步后将显示在这里。':'该订单暂未关联出库单，单据生成或同步后将显示在这里。');return; }
  panel.innerHTML = `<div class="compact-metrics"><dl class="compact-metric"><dt>订单数量</dt><dd>${qty(o)} <span class="currency">件</span></dd></dl><dl class="compact-metric"><dt>已确认出库</dt><dd>${o.unknown?'—':o.shipped} <span class="currency">件</span></dd><small>${o.unknown?'核验未完成':'以已核验出库事实计入'}</small></dl><dl class="compact-metric"><dt>${o.type==='预售单'?'待生成批次数量':'已生成待出库'}</dt><dd>${o.unknown?'—':o.reserved} <span class="currency">件</span></dd><small>${o.type==='预售单'?'已安排批次，尚未生成出库单':'单据已生成，尚未确认实际出库'}</small></dl><dl class="compact-metric"><dt>${o.type==='预售单'?'未安排批次数量':'未关联出库单数量'}</dt><dd>${o.unknown?'—':qty(o)-o.shipped-o.reserved} <span class="currency">件</span></dd><small>${o.type==='预售单'?'剩余商品可在后续批次安排':'本单已整单安排'}</small></dl></div><div class="section-heading"><h3>关联单据${o.type==='预售单'?'与发货批次':''} <span class="section-caption">${countOutbounds(o)} 张出库单${o.type==='预售单'?` / ${o.outbounds.length} 个批次`:''}</span></h3><input class="search-input" id="outbound-search" placeholder="搜索单号 / 批次" aria-label="搜索关联出库单或批次"></div><div id="outbound-documents">${o.outbounds.map((b,index)=>`<details class="doc-card" data-search="${esc(`${b.number||''} ${b.batch} ${b.settlement||''}`.toLowerCase())}"${index===0?' open':''}><summary><span class="doc-icon" aria-hidden="true">▱</span><span class="doc-identity"><strong>${esc(b.number||`${b.batch} · 待生成出库单`)}</strong><small>${esc(b.batch)}${b.settlement?` · ${esc(b.settlement)}`:''}</small></span><span class="doc-date">${b.date||'出库日期待定'}</span><span class="doc-quantity">${b.quantity} 件<small>${b.actual?'本单关联数量':'本批计划数量'}</small></span>${tag(abnormalStates.has(b.state)?b.state:o.unknown?'待核验':b.state,abnormalStates.has(b.state)?'warning':o.unknown?'neutral':b.tone)}<span class="chevron">⌄</span></summary><div class="doc-body"><p class="inline-note">${esc(o.unknown?'单据为已保存的关联记录，当前出库事实待核验，数量暂不计入进度。':b.detail)}</p><dl class="info-grid">${field('制单人',b.maker)}${field('检验状态',o.unknown?'待核验':b.inspection)}${field('订单关联',o.number)}${field('独立运费',o.type==='预售单'?usd(b.freight):'已计入主发票')}</dl><div class="table-scroll"><table aria-label="${esc(b.batch)}商品明细"><thead><tr><th>关联商品 / 规格</th><th class="num">${b.actual?'本次出库数量':'本批计划数量'}</th><th class="num">订单数量</th></tr></thead><tbody>${o.items.map((i,idx)=>`<tr><td>${esc(i.name)}<small>${esc(i.spec)}</small></td><td class="num">${b.quantities[idx]} 件</td><td class="num">${i.quantity} 件</td></tr>`).join('')}</tbody></table></div></div></details>`).join('')}</div><div id="outbound-no-results" hidden>${empty('⌕','没有匹配的关联单据','请调整单号或批次关键词。')}</div><p class="inline-note">${o.type==='预售单'?'等待生成的批次仅展示计划数量；单据生成、财务生效与实际出库分别核验。':'出库单生成状态、发货检验状态与实际出库状态分别展示。'}</p>`;
  document.querySelector('#outbound-search').addEventListener('input', e => {
    let visible = 0;
    document.querySelectorAll('#outbound-documents .doc-card').forEach(card => { card.hidden = !card.dataset.search.includes(e.target.value.trim().toLowerCase()); if(!card.hidden) visible++; });
    document.querySelector('#outbound-no-results').hidden = visible>0;
  });
}

function renderReceipt() {
  const o = scenarios[current];
  if(o.restricted) { panel.innerHTML=empty('▥','暂无回款单查看权限','回款金额、单据数量与凭证均按回款权限及订单归属校验。请申请回款单查看权限。');return; }
  if(!o.receipts.length) { panel.innerHTML=empty('▥','暂无关联回款单',o.sync==='未同步'?'订单尚未同步小满，暂未生成回款单。已有收款资料和正式回款记录会分别展示。':'该订单暂未关联回款单，登记或同步后将显示在这里。');return; }
  const unavailable=o.unknown;
  const remaining=o.total-o.effective-o.pending;
  panel.innerHTML = `<div class="compact-metrics"><dl class="compact-metric"><dt>已生效回款 · USD</dt><dd>${unavailable?'—':money(o.effective)}</dd><small>与订单金额相同的含费口径</small></dl><dl class="compact-metric"><dt>待生效回款 · USD</dt><dd>${unavailable?'—':money(o.pending)}</dd><small>包括待同步、失败、未生效款项</small></dl><dl class="compact-metric"><dt>未结清金额 · USD</dt><dd>${unavailable?'—':money(o.total-o.effective)}</dd><small>订单金额 − 已生效回款</small></dl><dl class="compact-metric"><dt>${o.type==='预售单'?'主单未登记金额':'可登记余额'} · USD</dt><dd>${unavailable?'—':money(remaining)}</dd><small>${o.type==='预售单'?'登记需以当前批次结算余额为准':'订单金额 − 已登记 / 占用金额'}</small></dl></div>${o.type==='预售单'?`<div class="receipt-note"><span>预售运费独立结算，不计入上方商品款进度。</span><span>运费应收 <strong>${unavailable?'—':usd(o.freightTotal)}</strong> · 已生效 <strong>${unavailable?'—':usd(o.freightEffective)}</strong> · 待生效 ${unavailable?'—':usd(o.freightPending)}</span></div>`:''}<div class="section-heading"><h3>关联回款单 <span class="section-caption">${o.receipts.length} 笔${o.type==='预售单'?' · 含独立运费款':''}</span></h3><div class="filters-inline"><select id="receipt-purpose" aria-label="筛选回款用途"><option value="all">全部用途</option><option value="goods">商品款 / 预付款</option><option value="freight">运费</option></select><input id="receipt-search" class="search-input" placeholder="搜索回款单号 / 批次号" aria-label="搜索关联回款单"></div></div><div class="table-scroll"><table class="receipt-table" aria-label="关联回款单"><thead><tr><th>回款单号 / 日期</th><th>用途 / 关联对象</th><th class="num">回款金额（USD）</th><th>同步状态</th><th>财务状态</th><th>凭证</th></tr></thead><tbody id="receipt-rows"></tbody></table></div><div id="receipt-no-results" hidden>${empty('⌕','没有匹配的回款单','请调整用途筛选或关键词。')}</div><div id="receipt-detail"></div><p class="inline-note" style="margin-top:14px">${o.type==='预售单'?`当前第 2 批可登记余额 ${unavailable?'待核验':usd(o.batchAvailable)}（商品款 ${unavailable?'待核验':usd(o.batchAvailable)}，运费 0.00）。<br>`:''}每笔回款金额按方舟含费金额展示；远端记录按回款 ID 去重。预付款抵扣仅用于结算，不新增回款金额。</p>`;
  renderReceiptRows();
  document.querySelector('#receipt-search').addEventListener('input',renderReceiptRows);
  document.querySelector('#receipt-purpose').addEventListener('change',renderReceiptRows);
}

function renderReceiptRows() {
  const o=scenarios[current];
  const keyword=document.querySelector('#receipt-search').value.trim().toLowerCase();
  const purpose=document.querySelector('#receipt-purpose').value;
  const rows=o.receipts.filter(r => (purpose==='all'||(purpose==='freight')===(r.purpose==='运费')) && `${r.number} ${r.batch||''} ${r.remote}`.toLowerCase().includes(keyword));
  document.querySelector('#receipt-rows').innerHTML=rows.map(r=>`<tr data-receipt-row="${r.id}" class="${selectedReceipt===r.id?'selected-row':''}"><td><button class="text-button" data-receipt="${r.id}">${r.number}</button><small>${r.date}</small></td><td>${tag(r.purpose,r.purpose==='运费'?'info':'neutral')}<small>${r.target}</small></td><td class="num"><strong>${money(r.amount)}</strong><small>手续费 ${money(r.fee)}</small></td><td>${tag(r.sync,r.sync==='同步失败'?'danger':r.sync==='待核对'?'warning':r.sync==='已同步'?'success':'neutral')}</td><td>${tag(o.unknown?'待核验':r.finance,o.unknown?'neutral':r.effective?'success':'warning')}</td><td><button class="text-button" data-receipt="${r.id}" aria-label="查看 ${r.number} 凭证">▧ 1 张</button></td></tr>`).join('');
  document.querySelector('#receipt-no-results').hidden=rows.length>0;
  if(selectedReceipt && !rows.some(r=>r.id===selectedReceipt)) {selectedReceipt=null;document.querySelector('#receipt-detail').innerHTML='';}
}

function renderReceiptDetail(identity) {
  const o=scenarios[current];
  const r=o.receipts.find(row=>row.id===identity);
  selectedReceipt=identity;
  renderReceiptRows();
  const target=document.querySelector('#receipt-detail');
  target.innerHTML=`<section class="receipt-detail"><div class="section-heading"><h3>${esc(r.number)}</h3><button class="icon-button" id="close-receipt-detail" aria-label="收起回款详情">×</button></div><dl class="info-grid">${field('回款日期',r.date)}${field('回款方式',o.method)}${field('回款金额（含手续费）',usd(r.amount))}${field('银行手续费',usd(r.fee))}${field('实际净额',usd(r.amount-r.fee))}${field('小满回款编号',r.remote)}${field('创建来源',r.source)}${field('回款批次',r.batch||'非批量登记')}</dl><div class="receipt-detail-bottom"><div><p class="inline-note"><strong>回款备注</strong><br>${esc(r.note)}</p><p class="inline-note" style="margin-top:10px">同步状态：${esc(r.sync)} · 财务状态：${esc(o.unknown?'待核验':r.finance)}</p></div><button class="proof-button" id="proof-preview"><span class="doc-icon">▧</span><span>${esc(r.proof)}<small>示例凭证 · 点击预览</small></span></button></div><div id="proof-container"></div></section>`;
  document.querySelector('#close-receipt-detail').addEventListener('click',()=>{selectedReceipt=null;target.innerHTML='';renderReceiptRows();});
  document.querySelector('#proof-preview').addEventListener('click',()=>{
    const container=document.querySelector('#proof-container');
    container.innerHTML=container.innerHTML?'':`<div class="proof-image" role="img" aria-label="模拟银行回单，仅为演示"><div class="proof-title">BANK TRANSFER · 示例回单</div><p>此凭证由原型模拟，不是真实银行单据。</p><p>付款人：${esc(o.customer)}<br>回款日期：${r.date}<br>本笔回款：${usd(r.amount)}<br>回款批次：${esc(r.batch||'单笔回款')}<br>关联发票：${o.number}</p></div>`;
  });
  target.scrollIntoView({block:'nearest',behavior:'instant'});
}

function activateTab(name, focus=false) {
  activeTab=name;
  selectedReceipt=null;
  document.querySelectorAll('[role=tab]').forEach(tab=>{const active=tab.dataset.tab===name;tab.setAttribute('aria-selected',String(active));tab.tabIndex=active?0:-1;});
  panel.setAttribute('aria-labelledby',`tab-${name}`);
  if(name==='order') renderOrder();
  else if(name==='outbound') renderOutbound();
  else renderReceipt();
  panel.scrollTop=0;
  if(focus) document.querySelector(`#tab-${name}`).focus();
}

function openOrder(key, trigger=null) {
  if(trigger && !dialog.contains(trigger)) returnFocus=trigger;
  if(!returnFocus?.isConnected) returnFocus=document.querySelector(`.invoice-link[data-order="${key}"]`)||document.querySelector('.invoice-link');
  current=key;
  document.querySelector('#scenario').value=key;
  document.querySelector('#dialog-scenario').value=key;
  renderHeader();
  activateTab('order');
  if(!dialog.open) dialog.showModal();
}
function notify(message) {const toast=document.querySelector('#toast');toast.textContent=message;toast.classList.add('visible');clearTimeout(toastTimer);toastTimer=setTimeout(()=>toast.classList.remove('visible'),2400);}

// The native modal makes its surroundings inert, so scenario controls also live inside it.
const demoSelect=document.createElement('select');
demoSelect.id='dialog-scenario';
demoSelect.className='scenario-select';
demoSelect.setAttribute('aria-label','切换演示场景');
demoSelect.innerHTML=document.querySelector('#scenario').innerHTML;
document.querySelector('#footer-context').after(demoSelect);
document.querySelectorAll('#scenario,#dialog-scenario').forEach(select=>select.addEventListener('change',e=>{
  const key=e.target.value;
  previewKey=['complete','draft'].includes(key)?'partial':key;
  renderInvoiceList();
  renderNavigationAnomalies();
  openOrder(key);
}));
document.querySelector('#invoice-list').addEventListener('click',e=>{const link=e.target.closest('.invoice-link');if(link)openOrder(link.dataset.order,link);});
document.querySelector('#dialog-anomaly').addEventListener('click',e=>{const button=e.target.closest('[data-anomaly-tab]');if(button)activateTab(button.dataset.anomalyTab);});
document.querySelectorAll('[role=tab]').forEach(tab=>tab.addEventListener('click',()=>activateTab(tab.dataset.tab)));
document.querySelector('.tab-bar').addEventListener('keydown',e=>{
  if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key)) return;
  e.preventDefault();
  const names=['order','outbound','receipt'];
  const index=names.indexOf(activeTab);
  const next=e.key==='Home'?0:e.key==='End'?2:(index+(e.key==='ArrowRight'?1:2))%3;
  activateTab(names[next],true);
});
document.querySelector('#progress-grid').addEventListener('click',e=>{const button=e.target.closest('[data-go-tab]');if(button&&!button.disabled)activateTab(button.dataset.goTab);});
panel.addEventListener('click',e=>{const link=e.target.closest('[data-receipt]');if(link)renderReceiptDetail(link.dataset.receipt);});
document.querySelectorAll('#close-top,#close-bottom').forEach(b=>b.addEventListener('click',()=>dialog.close()));
dialog.addEventListener('close',()=>{if(returnFocus?.isConnected)returnFocus.focus();});
document.querySelector('#expand-dialog').addEventListener('click',()=>{dialog.classList.toggle('wide');});
document.querySelector('#print-preview').addEventListener('click',()=>{activateTab('order');window.print();});
openOrder('partial');
