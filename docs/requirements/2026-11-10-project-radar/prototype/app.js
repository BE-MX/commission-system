/* 项目雷达原型交互。纯前端演示，不调用任何接口。 */
(() => {
  const D = window.RADAR_DATA;
  const items = D.items.map((x) => ({ ...x }));
  const $ = (s, el = document) => el.querySelector(s);
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const NOW = new Date('2026-11-10T08:30:00+08:00');
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  let view = 'updates';
  let nextId = 100;

  /* ── 工具 ── */
  function rel(s) {
    if (!s) return '未知';
    const t = new Date(s.replace(' ', 'T') + ':00+08:00');
    const h = Math.round((NOW - t) / 36e5);
    if (h < 1) return '刚刚';
    if (h < 24) return `${h} 小时前`;
    const d = Math.round(h / 24);
    if (d < 30) return `${d} 天前`;
    return s.slice(5, 10).replace('-', '月') + '日';
  }
  let toastTimer;
  function toast(msg) {
    const el = $('#toast');
    el.textContent = msg; el.hidden = false; el.classList.remove('is-hiding');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { el.classList.add('is-hiding'); setTimeout(() => { el.hidden = true; }, 200); }, 2600);
  }
  function canonical(raw) {
    let u = raw.trim().replace(/[，。；]+$/, '');
    try {
      const url = new URL(/^https?:/i.test(u) ? u : 'https://' + u);
      const host = url.hostname.replace(/^www\./, '').toLowerCase();
      if (host === 'github.com') {
        const [o, r] = url.pathname.split('/').filter(Boolean);
        if (o && r) return { host, path: `${o}/${r.replace(/\.git$/i, '')}`.toLowerCase(), raw: u };
      }
      return { host, path: url.pathname.replace(/\/$/, '').toLowerCase(), raw: u };
    } catch { return null; }
  }
  function findDup(c) {
    return items.find((x) => x.host === c.host && (x.kind !== 'repo' ? (!c.path || c.path === '/' || c.path === '') : x.path.toLowerCase() === c.path));
  }
  function parseInput(text) {
    const urls = text.match(/(https?:\/\/[^\s，。]+|github\.com\/[^\s，。]+)/gi) || [];
    let rest = text; urls.forEach((u) => { rest = rest.replace(u, ' '); });
    const tags = (rest.match(/#[^\s#]+/g) || []).map((t) => t.slice(1));
    const note = rest.replace(/#[^\s#]+/g, ' ').replace(/\s+/g, ' ').trim();
    return { urls, tags, note };
  }

  /* ── 视图与筛选 ── */
  const VIEWS = [
    ['updates', '有新更新', (x) => !!x.unread], ['all', '全部', () => true],
    ['inbox', '待看', (x) => x.status === 'inbox'], ['trying', '试用中', (x) => x.status === 'trying'],
    ['adopted', '已采用', (x) => x.status === 'adopted'], ['dropped', '已放弃', (x) => x.status === 'dropped'],
  ];
  function renderViews() {
    $('#views').innerHTML = VIEWS.map(([k, label, fn]) => {
      const n = items.filter((x) => !x.loading && fn(x)).length;
      return `<button role="tab" data-v="${k}" aria-selected="${k === view}" class="${k === 'updates' && n ? 'has-new' : ''}">${label}<span class="n">${n}</span></button>`;
    }).join('');
  }
  $('#views').addEventListener('click', (e) => {
    const b = e.target.closest('[data-v]'); if (!b) return;
    view = b.dataset.v; renderViews(); renderRows();
  });
  D.TYPES.forEach((t) => $('#fType').insertAdjacentHTML('beforeend', `<option>${t}</option>`));
  D.MODULES.forEach((m) => $('#fModule').insertAdjacentHTML('beforeend', `<option>${m}</option>`));
  ['#kw', '#fType', '#fModule', '#fRead'].forEach((s) => $(s).addEventListener('input', () => renderRows()));

  const STATUS_TAG = { inbox: 'tag-neutral', trying: 'tag-info', adopted: 'tag-success', dropped: 'tag-neutral' };
  function rowHTML(x, isNew) {
    if (x.loading) {
      const s = ['识别链接', x.kind === 'article' ? '读取文章' : '读取 README', 'AI 分析'];
      return `<div class="tr row is-loading ${isNew ? 'is-new' : ''}" data-id="${x.id}" role="row">
        <div class="proj"><div class="proj__ico ico-repo">…</div><div class="proj__main" style="flex:1">
          <div class="proj__path">${esc(x.raw)}</div>
          <div class="steps">${s.map((t, i) => `<span class="${i < x.step ? 'done' : i === x.step ? 'doing' : ''}">${i < x.step ? '✓ ' : ''}${t}${i === x.step ? '中…' : ''}</span>`).join('')}</div>
        </div></div>
        <div><div class="skel" style="width:80%"></div></div><div><div class="skel" style="width:60%"></div></div>
        <div><div class="skel" style="width:70%"></div></div><div><div class="skel" style="width:50%"></div></div></div>`;
    }
    const ico = x.kind === 'repo' ? ['ico-repo', 'Git'] : x.kind === 'site' ? ['ico-site', 'Web'] : ['ico-article', '文'];
    const newBadge = x.unread === 'key' ? `<span class="tag tag-gold new-badge">关键 · ${esc(x.version)}</span>`
      : x.unread === 'normal' ? '<span class="tag tag-gold new-badge">有更新</span>' : '';
    const readBadge = x.readState === 'limited' ? '<span class="tag tag-warning new-badge">读取受限</span>' : '';
    const sleepy = x.sleepy ? `<span class="tag tag-neutral new-badge">${x.sleepy} 天未看</span>` : '';
    const mods = x.modules.length ? x.modules.map((m) => `<span class="tag tag-neutral">${esc(m.name)}</span>`).join('') : '<span class="muted small">—</span>';
    const ver = x.kind === 'article' ? '<span class="muted small">不追踪</span>'
      : x.version ? `<span class="ver">${esc(x.version)}${x.unread === 'key' && x.prevVersion ? `<small>原 ${esc(x.prevVersion)}</small>` : ''}</span>` : '<span class="muted small">无版本</span>';
    return `<div class="tr row ${x.unread ? 'is-unread' : ''} ${isNew ? 'is-new' : ''}" data-id="${x.id}" role="row" tabindex="0" aria-label="${esc(x.title)}，查看详情">
      <div class="proj" role="cell"><div class="proj__ico ${ico[0]}">${ico[1]}</div><div class="proj__main">
        <div class="proj__title"><b>${esc(x.title)}</b><span class="tag tag-neutral new-badge">${esc(x.type)}</span>${newBadge}${readBadge}${sleepy}</div>
        <div class="proj__path">${esc(x.host)}${x.path ? '/' + esc(x.path) : ''}</div>
        <div class="proj__one">${esc(x.oneLiner)}</div></div></div>
      <div class="mods" role="cell">${mods}</div>
      <div role="cell">${ver}</div>
      <div class="when" role="cell" title="${x.updatedAt ? esc(x.updatedAt) + ' 北京时间' : ''}">${rel(x.updatedAt)}<small>${x.unread ? '未读' : ''}</small></div>
      <div role="cell"><span class="tag ${STATUS_TAG[x.status]}">${D.STATUS[x.status]}</span></div></div>`;
  }
  function visible() {
    const fn = VIEWS.find((v) => v[0] === view)[2];
    const kw = $('#kw').value.trim().toLowerCase(), t = $('#fType').value, m = $('#fModule').value, r = $('#fRead').value;
    return items.filter((x) => {
      if (x.loading) return true;
      if (!fn(x)) return false;
      if (t && x.type !== t) return false;
      if (m && !x.modules.some((mm) => mm.name === m)) return false;
      if (r && x.readState !== r) return false;
      if (kw && ![x.title, x.oneLiner, x.note, x.path, ...(x.tags || [])].join(' ').toLowerCase().includes(kw)) return false;
      return true;
    });
  }
  function renderRows(newId) {
    const list = visible();
    $('#rows').innerHTML = list.map((x) => rowHTML(x, x.id === newId)).join('');
    $('#empty').hidden = list.length > 0;
  }
  $('#rows').addEventListener('click', (e) => { const r = e.target.closest('.row:not(.is-loading)'); if (r) openDrawer(+r.dataset.id, r); });
  $('#rows').addEventListener('keydown', (e) => {
    if (e.key !== 'Enter' && e.key !== ' ') return;
    const r = e.target.closest('.row:not(.is-loading)'); if (r) { e.preventDefault(); openDrawer(+r.dataset.id, r); }
  });

  /* ── 收录 ── */
  function addLoading(raw, kind, extra = {}) {
    const x = { id: nextId++, loading: true, raw, kind, step: 0, ...extra };
    items.unshift(x);
    if (view !== 'all') { view = 'all'; renderViews(); }
    renderRows(x.id);
    const tick = () => {
      x.step += 1;
      if (x.step < 3) { renderRows(); setTimeout(tick, 650); return; }
      Object.assign(x, buildResult(x), { loading: false });
      renderViews(); renderRows(x.id);
      toast(`已收录「${x.title}」`);
    };
    setTimeout(tick, 650);
  }
  function buildResult(x) {
    const base = { status: 'inbox', watch: 'normal', unread: '', readState: 'ok', addedAt: '2026-11-10 08:30', timeline: [], locked: [], note: x.note || '', tags: x.tags || [],
      sources: [{ channel: '方舟页面', from: x.fromSource || x.raw, at: '2026-11-10 08:30', text: x.note || '' }], updateSummary: [], impact: '', prevVersion: '' };
    if (x.candidate) {
      return { ...base, kind: 'repo', host: 'github.com', path: x.candidate.path, title: x.candidate.title, type: '开源项目', oneLiner: x.candidate.oneLiner,
        modules: [{ name: '知识库', reason: '可作为内部 AI 对话入口的参考实现', effort: '中' }], version: 'v1.4.0', updatedAt: '2026-11-08 12:00',
        stars: '5.2 万', license: 'MIT', lang: 'TypeScript', detail: '（原型）AI 根据 README 生成的详细说明。' };
    }
    const c = canonical(x.raw) || { host: 'example.com', path: '' };
    if (c.host === 'github.com') {
      const s = D.samples.repo;
      if (c.path === s.path) return { ...base, ...s, tags: [...new Set([...(s.tags || []), ...base.tags])], detail: '（原型）AI 根据 README 生成的详细说明：能力、用法、限制、协议与部署要求。' };
      const name = c.path.split('/')[1] || c.path;
      return { ...base, kind: 'repo', host: c.host, path: c.path, title: name, type: '开源项目', oneLiner: '（原型）AI 根据 README 生成的一句话说明',
        modules: [{ name: 'Agent 任务中心', reason: '（原型）AI 给出的适用理由', effort: '中' }], version: 'v1.0.0', updatedAt: '2026-11-09 10:00', stars: '1.2 万', license: 'MIT', lang: 'Python', detail: '' };
    }
    return { ...base, kind: 'site', host: c.host, path: '', title: c.host, type: 'SaaS 工具', oneLiner: '（原型）AI 根据页面正文生成的一句话说明',
      modules: [{ name: '素材管理', reason: '（原型）AI 给出的适用理由', effort: '低' }], version: '', updatedAt: '2026-11-06 09:00', stars: '', license: '', lang: '', detail: '' };
  }
  function ingest(text) {
    const { urls, tags, note } = parseInput(text);
    if (!urls.length) { toast('没有识别到链接，粘贴以 http 开头的地址即可'); return; }
    urls.forEach((u) => {
      const c = canonical(u); if (!c) return;
      if (c.host === 'mp.weixin.qq.com') { openPick(u, tags, note); return; }
      if (c.host === 'x.com' || c.host === 'twitter.com') { addLoading(u, 'repo', { raw: 'https://github.com/' + D.samples.repo.path, fromSource: u, tags, note }); return; }
      const dup = findDup(c);
      if (dup) {
        dup.sources.push({ channel: '方舟页面', from: u, at: '2026-11-10 08:30', text: note });
        if (view !== 'all') { view = 'all'; renderViews(); }
        renderRows();
        const row = $(`.row[data-id="${dup.id}"]`);
        if (row) { row.scrollIntoView({ block: 'center', behavior: reduceMotion ? 'auto' : 'smooth' }); row.classList.add('is-flash'); setTimeout(() => row.classList.remove('is-flash'), 1600); }
        toast(`已在雷达里（${dup.addedAt.slice(5, 10)} 收录 · ${D.STATUS[dup.status]}），已追加本次来源`);
        return;
      }
      addLoading(u, 'repo', { tags, note });
    });
  }
  $('#captureForm').addEventListener('submit', (e) => { e.preventDefault(); const v = $('#captureInput').value; if (!v.trim()) return; ingest(v); $('#captureInput').value = ''; });
  document.querySelectorAll('[data-demo]').forEach((b) => b.addEventListener('click', () => { $('#captureInput').value = b.dataset.demo; $('#captureInput').focus(); }));

  /* ── 弹窗通用 ── */
  let lastFocus = null;
  function openModal(wrap) { lastFocus = document.activeElement; wrap.hidden = false; const f = wrap.querySelector('.modal__body input, .modal__body select, footer .btn-primary'); f && f.focus(); }
  function closeModal(wrap) { wrap.hidden = true; lastFocus && lastFocus.focus && lastFocus.focus(); }
  document.querySelectorAll('.modal-wrap').forEach((w) => {
    w.addEventListener('click', (e) => {
      if (e.target === w) closeModal(w);
      const c = e.target.closest('[data-close]');
      if (c) { if (c.dataset.toast) toast(c.dataset.toast); closeModal(w); }
    });
  });
  $('#openSettings').addEventListener('click', () => openModal($('#setWrap')));
  $('#setWrap').addEventListener('click', (e) => {
    const r = e.target.closest('.seg [role="radio"]'); if (!r) return;
    r.parentElement.querySelectorAll('[role="radio"]').forEach((b) => b.setAttribute('aria-checked', b === r));
  });

  /* 候选选择 */
  let pickCtx = null;
  function openPick(u, tags, note) {
    pickCtx = { u, tags, note };
    $('#pickList').innerHTML = D.samples.articleCandidates.map((c, i) => `<label class="pick"><input type="checkbox" data-i="${i}" ${c.checked ? 'checked' : ''}>
      <div><b>${esc(c.title)}</b> <span class="proj__path">github.com/${esc(c.path)}</span><p>${esc(c.oneLiner)}</p></div></label>`).join('');
    syncPick(); openModal($('#pickWrap'));
  }
  function syncPick() {
    const n = $('#pickList').querySelectorAll('input:checked').length;
    $('#pickOk').textContent = n ? `收录选中的 ${n} 项` : '请选择项目'; $('#pickOk').disabled = !n;
  }
  $('#pickList').addEventListener('change', syncPick);
  $('#pickArticle').addEventListener('click', () => {
    closeModal($('#pickWrap'));
    const x = { id: nextId++, kind: 'article', host: 'mp.weixin.qq.com', path: '', title: '公众号文章：AI 对话客户端横评', type: '文章教程',
      oneLiner: '对比几款开源 AI 对话客户端的功能与部署方式', modules: [], version: '', prevVersion: '', updatedAt: '2026-11-08 07:00', stars: '', license: '', lang: '',
      status: 'inbox', watch: 'silent', unread: '', readState: 'ok', addedAt: '2026-11-10 08:30', tags: pickCtx.tags || [], articleNote: '文章不追踪更新；需要时可在钉钉补发其中项目的链接',
      updateSummary: [], impact: '', detail: '', timeline: [], sources: [{ channel: '方舟页面', from: pickCtx.u, at: '2026-11-10 08:30', text: pickCtx.note || '' }], note: pickCtx.note || '', locked: [] };
    items.unshift(x); if (view !== 'all') view = 'all';
    renderViews(); renderRows(x.id); toast('已存为文章（不追踪更新）');
  });
  $('#pickOk').addEventListener('click', () => {
    const picked = [...$('#pickList').querySelectorAll('input:checked')].map((i) => D.samples.articleCandidates[+i.dataset.i]);
    closeModal($('#pickWrap'));
    picked.forEach((c, k) => setTimeout(() => addLoading('https://github.com/' + c.path, 'repo', { candidate: c, fromSource: pickCtx.u, tags: pickCtx.tags, note: pickCtx.note }), k * 250));
  });

  /* ── 详情抽屉 ── */
  const drawer = $('#drawer'), overlay = $('#overlay');
  let openId = null, drawerTrigger = null;
  function openDrawer(id, trigger) {
    const x = items.find((i) => i.id === id); if (!x) return;
    openId = id; drawerTrigger = trigger || null;
    const wasUnread = x.unread;
    renderDrawer(x, wasUnread);
    overlay.hidden = false; drawer.hidden = false;
    requestAnimationFrame(() => { overlay.classList.add('is-open'); drawer.classList.add('is-open'); });
    document.body.classList.add('drawer-open');
    $('.d-head h2', drawer).focus();
  }
  function closeDrawer() {
    overlay.classList.remove('is-open'); drawer.classList.remove('is-open');
    setTimeout(() => { overlay.hidden = true; drawer.hidden = true; }, reduceMotion ? 0 : 280);
    document.body.classList.remove('drawer-open');
    /* 看过即已读：关闭抽屉时才清除未读，避免打开时行从「有新更新」里消失 */
    const x = items.find((i) => i.id === openId);
    if (x && x.unread) { x.unread = ''; renderViews(); renderRows(); syncNavDot(); }
    openId = null;
    const r = drawerTrigger && $(`.row[data-id="${drawerTrigger.dataset.id}"]`); r && r.focus();
  }
  overlay.addEventListener('click', closeDrawer);
  /* 焦点锁定：aria-modal 的抽屉和弹窗内 Tab 循环 */
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Tab') return;
    const box = [...document.querySelectorAll('.modal-wrap')].find((w) => !w.hidden) || (openId !== null ? drawer : null);
    if (!box) return;
    const f = [...box.querySelectorAll('button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea, a[href], [tabindex]:not([tabindex="-1"])')].filter((el) => el.offsetParent !== null);
    if (!f.length) return;
    const first = f[0], last = f[f.length - 1];
    if (!box.contains(document.activeElement)) { e.preventDefault(); first.focus(); return; }
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  });
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return;
    const m = [...document.querySelectorAll('.modal-wrap')].find((w) => !w.hidden);
    if (m) { closeModal(m); return; }
    if (openId !== null) closeDrawer();
  });

  function renderDrawer(x, wasUnread) {
    const L = (f) => x.locked.includes(f) ? '<span class="lock-mark" title="你改过，扫描不会覆盖">已锁定</span>' : '<span class="ai-mark">AI 生成</span>';
    const facts = x.kind === 'repo'
      ? [['版本', x.version || '无版本'], ['最近更新', x.updatedAt ? x.updatedAt.slice(0, 10) : '未知'], ['Star', x.stars || '—'], ['协议', x.license || '—']]
      : [['版本', x.version || '无版本'], ['最近更新', x.updatedAt ? x.updatedAt.slice(0, 10) : '未知'], ['类型', x.type], ['读取', x.readState === 'ok' ? '正常' : '受限']];
    const factSrc = x.kind === 'repo' ? '版本与日期来自 GitHub Release / 默认分支，不由 AI 生成' : x.kind === 'site' ? (x.scanMode === 'agent' ? '日期来自 agent 检查，已重新抓取出处核对原文；官网无版本号' : '日期来自官网 changelog / 追踪页变化检测；官网无版本号') : '文章类条目不追踪更新';
    const upd = x.updateSummary.length ? `<div class="update-box"><b>${wasUnread === 'key' ? `新版本 ${esc(x.prevVersion)} → ${esc(x.version)}` : '最近更新'}</b> <span class="muted small">${esc(x.updatedAt)}</span>
      <ul>${x.updateSummary.map((s) => `<li>${esc(s)}</li>`).join('')}</ul>${x.impact ? `<div class="impact">对方舟：${esc(x.impact)}</div>` : ''}${x.levelReason ? `<div class="level-reason">分级依据　${esc(x.levelReason)}</div>` : ''}</div>` : '';
    const LV = { key: ['tag-gold', '关键'], normal: ['tag-info', '普通'], noise: ['tag-neutral', '噪音 · 未推送'], info: ['tag-neutral', '记录'] };
    drawer.innerHTML = `
      <div class="d-head"><div class="d-head__top">
        <div class="proj__ico ${x.kind === 'repo' ? 'ico-repo' : x.kind === 'site' ? 'ico-site' : 'ico-article'}">${x.kind === 'repo' ? 'Git' : x.kind === 'site' ? 'Web' : '文'}</div>
        <div style="flex:1;min-width:0"><h2 id="dTitle" tabindex="-1">${esc(x.title)}</h2>
          <div class="proj__path"><a href="#" onclick="return false">${esc(x.host)}${x.path ? '/' + esc(x.path) : ''} ↗</a></div></div>
        <button class="icon-btn" id="dClose" aria-label="关闭">✕</button></div>
        <div class="d-head__meta"><span class="tag tag-neutral">${esc(x.type)}</span>${x.lang ? `<span>${esc(x.lang)}</span>·` : ''}<span>收录于 ${esc(x.addedAt.slice(0, 10))}</span>
          ${x.tags.map((t) => `<span class="tag tag-gold">#${esc(t)}</span>`).join('')}</div></div>
      <div class="d-body">
        <section class="d-sec"><div class="d-controls">
          <div class="seg" role="radiogroup" aria-label="试用状态" id="dStatus">${Object.entries(D.STATUS).map(([k, v]) => `<button role="radio" data-s="${k}" aria-checked="${x.status === k}">${v}</button>`).join('')}</div>
          <select id="dWatch" aria-label="关注级别">${Object.entries(D.WATCH).map(([k, v]) => `<option value="${k}" ${x.watch === k ? 'selected' : ''}>关注：${v}</option>`).join('')}</select>
        </div><p class="muted small" style="margin:8px 0 0">${{ key: '重点：关键与普通更新都推送（7 天最多一次普通）', normal: '普通：只推送关键更新（主版本、破坏性、安全）', adopted: '已采用：只推送破坏性变更与安全更新', silent: '静默：只记录，不推送' }[x.watch]}</p></section>
        ${x.readState === 'limited' ? `<section class="d-sec"><div class="read-alert">${esc(x.readNote)}</div></section>` : ''}
        <section class="d-sec"><h3>一句话说明 ${L('oneLiner')}</h3>
          <div class="editable" id="oneWrap"><div class="one-liner">${esc(x.oneLiner)}</div><button class="btn btn-quiet edit-btn" id="editOne">编辑</button></div></section>
        <section class="d-sec"><h3>可用于方舟 ${L('modules')}</h3>
          ${x.modules.length ? `<div class="mod-cards">${x.modules.map((m) => `<div class="mod-card"><span class="tag tag-gold">${esc(m.name)}</span><p>${esc(m.reason)}</p><span class="effort">落地难度 ${esc(m.effort)}</span></div>`).join('')}</div>` : '<p class="muted small">暂无推荐</p>'}</section>
        <section class="d-sec"><h3>版本与更新</h3>
          <div class="facts">${facts.map(([k, v]) => `<div class="fact"><span>${k}</span><b class="${/[一-龥]/.test(v) ? 'plain' : ''}">${esc(v)}</b></div>`).join('')}</div>
          <div class="fact-src">ⓘ ${factSrc}</div>${upd}
          ${x.kind === 'article' ? '' : `<div class="scan-mode">
            <div><span class="tag ${x.scanMode === 'agent' ? 'tag-info' : 'tag-neutral'}">${x.scanMode === 'agent' ? 'agent 扫描 · 每周一' : '程序扫描 · 每天 06:30'}</span>
              <span class="muted small">${x.scanMode === 'agent' ? `上次 ${esc((x.lastAgentCheck || '').slice(5, 16))}` : x.readState === 'limited' ? '连续失败 3 天会自动转 agent 尝试' : ''}</span></div>
            <button class="btn btn-text" id="deepCheck">让 agent 深度看 <span class="tag tag-neutral new-badge">二期</span></button></div>
            ${x.agentNote ? `<p class="muted small" style="margin:6px 0 0">${esc(x.agentNote)}</p>` : ''}`}</section>
        ${x.timeline.length ? `<section class="d-sec"><h3>更新记录</h3><ul class="timeline">${x.timeline.map((t) => `<li class="${t.level}"><div class="t-head"><span class="t-date">${t.date}</span><b>${esc(t.title)}</b><span class="tag ${LV[t.level][0]} new-badge">${LV[t.level][1]}</span></div><div class="muted">${esc(t.text)}</div></li>`).join('')}</ul></section>` : ''}
        ${x.detail ? `<section class="d-sec"><h3>详细说明 ${L('detail')}</h3><p style="margin:0;font-size:13px;color:var(--text-secondary)">${esc(x.detail)}</p></section>` : ''}
        ${x.articleNote ? `<section class="d-sec"><div class="read-alert" style="background:var(--tag-info-bg);border-color:var(--tag-info-border);color:var(--tag-info-text)">${esc(x.articleNote)}</div></section>` : ''}
        <section class="d-sec"><h3>来源</h3>${x.sources.map((s) => `<div class="src"><span class="tag tag-neutral">${esc(s.channel)}</span><div><div>${esc(s.from)}</div><div class="muted small">${esc(s.at)}${s.text ? ` · <q>${esc(s.text)}</q>` : ''}</div></div></div>`).join('')}</section>
        <section class="d-sec"><h3>我的笔记</h3><textarea class="note-area" placeholder="试用结论、注意事项…">${esc(x.note)}</textarea></section>
      </div>
      <div class="d-foot"><button class="btn btn-quiet" id="reAnalyze">重新分析</button><span class="spacer"></span><button class="btn btn-danger-text" id="dRemove">移出雷达</button><button class="btn btn-primary" id="dDone">完成</button></div>`;
    $('#dClose').onclick = closeDrawer; $('#dDone').onclick = closeDrawer;
    $('#dRemove').onclick = (e) => {
      const b = e.currentTarget;
      if (!b.dataset.armed) {
        b.dataset.armed = '1'; b.textContent = '确认移出？'; b.classList.add('btn-danger-confirm');
        setTimeout(() => { if (b.isConnected) { delete b.dataset.armed; b.textContent = '移出雷达'; b.classList.remove('btn-danger-confirm'); } }, 4000);
        return;
      }
      const idx = items.indexOf(x); if (idx >= 0) items.splice(idx, 1);
      drawerTrigger = null; closeDrawer(); renderViews(); renderRows(); syncNavDot();
      toast(`已移出「${x.title}」。分析与历史保留，30 天内重新收录可恢复笔记与状态`);
    };
    const dc = $('#deepCheck');
    if (dc) dc.onclick = () => toast('已交给 agent 检查，约 5 分钟后在钉钉回复结果；版本与日期会先核对出处');
    $('#reAnalyze').onclick = () => toast(x.locked.length ? '已重新分析，已锁定的字段保持你的版本' : '已重新分析');
    $('#dStatus').onclick = (e) => {
      const b = e.target.closest('[data-s]'); if (!b) return;
      x.status = b.dataset.s;
      const auto = { trying: ['key', '已切换为重点关注'], adopted: ['adopted', '已切换为「已采用」：只推破坏性与安全更新'], dropped: ['silent', '已放弃，自动转为静默并停止扫描'] }[x.status];
      if (auto) { x.watch = auto[0]; toast(auto[1]); }
      renderDrawer(x, wasUnread); renderViews(); renderRows(); $('#dStatus [aria-checked="true"]').focus();
    };
    $('#dWatch').onchange = (e) => { x.watch = e.target.value; renderDrawer(x, wasUnread); $('#dWatch').focus(); };
    $('#editOne').onclick = () => {
      const w = $('#oneWrap');
      w.innerHTML = `<textarea id="oneTa" aria-label="一句话说明">${esc(x.oneLiner)}</textarea><div class="edit-actions"><button class="btn btn-quiet" id="oneCancel">取消</button><button class="btn btn-primary" id="oneSave">保存</button></div>`;
      const ta = $('#oneTa'); ta.focus(); ta.setSelectionRange(ta.value.length, ta.value.length);
      $('#oneCancel').onclick = () => renderDrawer(x, wasUnread);
      $('#oneSave').onclick = () => {
        x.oneLiner = ta.value.trim() || x.oneLiner;
        if (!x.locked.includes('oneLiner')) x.locked.push('oneLiner');
        renderDrawer(x, wasUnread); renderRows(); toast('已保存，此字段已锁定，扫描不会覆盖');
      };
    };
  }

  /* ── 原型视图切换 ── */
  function setPane(p) {
    document.querySelectorAll('[data-pane]').forEach((el) => { el.hidden = el.dataset.pane !== p; });
    document.querySelectorAll('.proto-bar [data-view]').forEach((b) => b.setAttribute('aria-selected', b.dataset.view === p));
    if (location.hash.slice(1) !== p) history.replaceState(null, '', p === 'web' ? location.pathname : '#' + p);
    if (p !== 'web' && openId !== null) closeDrawer();
  }
  document.querySelectorAll('.proto-bar [data-view]').forEach((b) => b.addEventListener('click', () => setPane(b.dataset.view)));
  document.querySelectorAll('[data-goto]').forEach((b) => b.addEventListener('click', () => setPane(b.dataset.goto)));
  $('.menu-btn').addEventListener('click', () => $('.aside').classList.toggle('is-open'));

  /* ── 钉钉对话 ── */
  const ME = '<div class="me-ava">亮</div>', BOT = '<div class="bot-ava">雷</div>';
  const me = (h) => `<div class="msg me">${ME}<div class="bubble">${h}</div></div>`;
  const bot = (h, raw) => `<div class="msg">${BOT}${raw ? h : `<div class="bubble">${h}</div>`}</div>`;
  const sep = (t) => `<div class="time-sep">${t}</div>`;
  const linkify = (t) => esc(t).replace(/(https?:\/\/[^\s]+)/g, '<a>$1</a>');
  function resultCard(x, extra = '') {
    return `<div class="dcard"><div class="dcard__head"><b>✓ 已收录 · ${esc(x.title)}</b></div><div class="dcard__body">
      <div>${esc(x.oneLiner)}</div>
      <div><b>1.</b> <span class="k">类型</span> ${esc(x.type)}　<span class="k">版本</span> ${esc(x.version || '无版本')}</div>
      <div><span class="k">可用于方舟</span><br>${x.modules.map((m) => `<span class="dtag">${esc(m.name)}</span>`).join('')}<br><span class="k">${esc(x.modules[0]?.reason || '')}</span></div>${extra}
      <div class="dcard__hint">回复「静默 1」停止推送 · 「放弃 1」移到已放弃</div>
      </div><div class="dcard__foot"><button>打开详情（免登录）</button></div></div>`;
  }
  const botHistory = [
    sep('10月30日 21:03'),
    me('<a>https://mp.weixin.qq.com/s/9xK…</a>'),
    bot('收到 1 个链接，正在读取…'),
    bot(`<div class="dcard"><div class="dcard__head"><b>这篇文章提到 3 个项目</b></div><div class="dcard__body">
      <div class="muted small" style="color:#8f959e">《10 个外贸人必备 AI 工具》</div>
      <div>1. MarkItDown — 文件转 Markdown</div><div>2. Cherry Studio — 桌面 AI 客户端</div><div>3. 沉浸式翻译 — 网页双语对照</div>
      <div class="k">回复数字收录，如「1 3」；回复「全部」收录全部。文章本身会记为来源。</div></div></div>`, true),
    me('1'),
    bot('已收录 <b>MarkItDown</b>，文章已记为来源。'),
    sep('昨天 23:48'),
    me('<a>https://suno.com</a>'),
    bot('收到 1 个链接，正在读取…'),
    bot(`<div class="dcard"><div class="dcard__head"><b>⚠ 读取受限 · Suno</b></div><div class="dcard__body">
      <div>网站拦截了自动读取，只拿到页面标题。</div><div class="k">30 分钟内直接回复一句话说明，我帮你补全分析。</div></div>
      <div class="dcard__foot"><button>打开详情（免登录）</button></div></div>`, true),
    me('AI 生成背景音乐，可以给产品短视频配乐'),
    bot('已补充 ✓ 类型：SaaS 工具 · 可用于：<span class="dtag">素材管理</span>'),
    sep('今天 08:31'),
  ];
  const chatBot = $('#chatBot');
  chatBot.innerHTML = botHistory.join('');
  const scrollChat = (c) => { c.scrollTop = c.scrollHeight; };
  requestAnimationFrame(() => scrollChat(chatBot));
  const later = (ms, fn) => setTimeout(fn, reduceMotion ? Math.min(ms, 200) : ms);
  function botReply(text) {
    chatBot.insertAdjacentHTML('beforeend', me(linkify(text))); scrollChat(chatBot);
    const { urls, tags, note } = parseInput(text);
    if (!urls.length) {
      const t = text.trim();
      const deep = t.match(/^深度看\s*(\d+)$/);
      if (deep) {
        later(500, () => { chatBot.insertAdjacentHTML('beforeend', bot(`已交给 agent 检查第 ${deep[1]} 项，约 5 分钟后回复。本周剩余 17 次。`)); scrollChat(chatBot); });
        later(2600, () => { chatBot.insertAdjacentHTML('beforeend', bot(`<div class="dcard"><div class="dcard__head"><b>agent 检查结果 · Suno</b></div><div class="dcard__body">
          <div>浏览 4 页（首页、博客、价格页、帮助中心），未发现新功能或新版本。</div>
          <div class="dcard__hint">博客 10 月 28 日的文章已在上次检查中记录。</div></div><div class="dcard__foot"><button>打开详情（免登录）</button></div></div>`, true)); scrollChat(chatBot); });
        return;
      }
      const reply = t === '最近' ? '最近收录：<br>1. browser-use（试用中）<br>2. n8n（待看）<br>3. MCP Servers 官方合集（待看）'
        : t === '帮助' ? '发链接即收录，可多条；链接后写的话会变成笔记，#词 变成标签。<br>「最近」看最近收录；「搜 关键词」查找；「静默 2」调整推送；「深度看 2」让 agent 浏览检查（二期）。'
        : '没找到链接。发送链接即可收录；发「帮助」查看用法。';
      later(500, () => { chatBot.insertAdjacentHTML('beforeend', bot(reply)); scrollChat(chatBot); });
      return;
    }
    later(500, () => { chatBot.insertAdjacentHTML('beforeend', bot(`收到 ${urls.length} 个链接，正在读取…`)); scrollChat(chatBot); });
    urls.forEach((u, i) => {
      const c = canonical(u);
      const dup = c && findDup(c);
      later(1700 + i * 700, () => {
        let html;
        if (dup) {
          html = bot(`<div class="dcard"><div class="dcard__head"><b>已在雷达里 · ${esc(dup.title)}</b></div><div class="dcard__body">
            <div>${dup.addedAt.slice(5, 7)}月${dup.addedAt.slice(8, 10)}日收录 · 状态：${D.STATUS[dup.status]} · 当前 ${esc(dup.version || '无版本')}</div>
            <div class="k">已追加本次来源，不会重复收录。</div></div><div class="dcard__foot"><button>打开详情（免登录）</button></div></div>`, true);
        } else {
          const isX = c && (c.host === 'x.com' || c.host === 'twitter.com');
          const x = c && c.host === 'github.com' && c.path !== D.samples.repo.path
            ? { ...D.samples.repo, title: c.path.split('/')[1], oneLiner: '（原型）AI 根据 README 生成的一句话说明' } : D.samples.repo;
          const extra = (isX ? '<div class="k">从 X 帖子中识别到项目，帖子已记为来源</div>' : '')
            + (note ? `<div><span class="k">笔记</span> ${esc(note)}</div>` : '') + (tags.length ? `<div>${tags.map((t) => `<span class="dtag">#${esc(t)}</span>`).join('')}</div>` : '');
          html = bot(resultCard(x, extra), true);
        }
        chatBot.insertAdjacentHTML('beforeend', html); scrollChat(chatBot);
      });
    });
  }
  $('#botForm').addEventListener('submit', (e) => { e.preventDefault(); const v = $('#botInput').value; if (!v.trim()) return; botReply(v); $('#botInput').value = ''; });
  document.querySelectorAll('[data-bot]').forEach((b) => b.addEventListener('click', () => { $('#botInput').value = b.dataset.bot; $('#botInput').focus(); }));

  /* ── 早报 ── */
  $('#chatDigest').innerHTML = [
    sep('11月6日 08:00'),
    bot(`<div class="dcard"><div class="dcard__head"><b>方舟雷达 · 11月6日早报</b></div><div class="dcard__body"><div><b>1.</b> 【关键】n8n v2.0.0（原 v1.118）主版本升级，自托管配置项有调整</div><div class="dcard__hint">扫描 11/11 完成</div></div><div class="dcard__foot"><button>打开项目雷达</button></div></div>`, true),
    sep('11月7日—9日 没有值得推送的更新，未打扰'),
    sep('今天 08:00'),
    bot(`<div class="dcard"><div class="dcard__head"><b>方舟雷达 · 11月10日早报</b></div><div class="dcard__body">
      <div>3 项有更新，其中 <b>1 项需要关注</b></div>
      <div class="dcard__group"><h4>关键</h4><b>1. browser-use v0.8.2 → v0.9.0</b>
        <ul><li>多标签页并行，长流程更稳</li><li>可复用本机 Chrome 登录态</li><li>移除旧 Controller API，升级需改调用</li></ul>
        <div><span class="dtag">订单发票</span><span class="dtag">私海助手</span>正在试用，升级前需改调用</div></div>
      <div class="dcard__group"><h4>更新</h4><b>2. MarkItDown v0.2.1</b>：新增 EPUB；PDF 表格识别改进
        <div><span class="dtag">知识库</span>报价单类 PDF 解析可受益</div>
        <div style="margin-top:6px"><b>3. 可灵 AI</b>（官网）：价格页新增团队版；API 新增首尾帧参数</div></div>
      <div class="dcard__group"><h4>需要处理</h4>ElevenLabs 读取受限，打开详情补一句说明即可</div>
      <div class="dcard__hint">扫描 11/12 完成 · 回复「静默 2」可停止推送某项</div>
      </div><div class="dcard__foot"><button>打开项目雷达</button><button>browser-use 详情</button></div></div>`, true),
  ].join('');
  requestAnimationFrame(() => scrollChat($('#chatDigest')));

  function syncNavDot() {
    const n = items.filter((x) => !x.loading && x.unread).length, dot = $('.nav-dot');
    dot.hidden = !n; dot.textContent = n; dot.setAttribute('aria-label', `有 ${n} 项新更新`);
  }

  /* 初始化 */
  renderViews(); renderRows();
  const paneFromHash = () => { const h = location.hash.slice(1); setPane(['bot', 'digest'].includes(h) ? h : 'web'); };
  window.addEventListener('hashchange', paneFromHash);
  paneFromHash();
})();
