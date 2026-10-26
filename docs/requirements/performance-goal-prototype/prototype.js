/**
 * 绩效目标管理原型 · 交互与渲染
 * 依赖：data.js（window.PerfData）、ECharts 6（CDN）
 */
(function () {
  'use strict';
  const D = window.PerfData;
  const $ = s => document.querySelector(s);
  const $$ = s => Array.from(document.querySelectorAll(s));
  const esc = s => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  const C_ACT = '#2563eb', C_TARGET = '#94a3b8', C_GREEN = '#16a34a',
    C_RED = '#dc2626', C_AMBER = '#f59e0b', C_ORANGE = '#ea580c', C_GRAY = '#cbd5e1';

  const METRICS = [
    { key: 'gmv', name: 'GMV', unit: 'USD', money: true },
    { key: 'ns', name: '新签客户', unit: '个', money: false },
    { key: 'rc', name: '复购客户', unit: '个', money: false },
    { key: 'ra', name: '复购金额', unit: 'USD', money: true },
  ];
  const MKEYS = METRICS.map(m => m.key);
  const mName = k => METRICS.find(m => m.key === k).name;
  const mUnit = k => METRICS.find(m => m.key === k).unit;
  const fmtV = (k, v) => (METRICS.find(m => m.key === k).money ? D.fmtMoney(v) : D.fmtInt(v) + ' ' + mUnit(k));
  const fmtVShort = (k, v) => (METRICS.find(m => m.key === k).money ? D.fmtMoney(v) : D.fmtInt(v));
  const rateOf = (done, target) => (target ? Math.round((done / target) * 1000) / 10 : null);
  const ELAPSED_DAYS = 296;   // 2026-01-01 → 2026-10-23
  const REMAIN_DAYS = 365 - ELAPSED_DAYS;

  /* ==================== 全局状态 ==================== */
  const state = {
    view: 'dashboard',
    scope: 'company', objectTeam: '专治不服', objectPerson: '翟佳盟',
    period: 'year',
    trendMetric: 'gmv', monthlyMetric: 'gmv', teamMetric: 'gmv',
    sort: { key: 'gmvRate', dir: -1 },
    detail: { tab: 'gmv', person: '', team: '', range: '', page: 1 },
    gran: 'year', qMetric: 'gmv',
    teamFactors: { '专治不服': 105 },
    teamTrails: { '专治不服': '2026-01-10 admin 上调 5%' },
    teamDirty: {},
  };
  const charts = {};
  function chartOf(id) {
    if (!window.echarts) return null;
    if (!charts[id]) charts[id] = echarts.init(document.getElementById(id));
    return charts[id];
  }
  function chartFallback(id) {
    const el = document.getElementById(id);
    if (el && !window.echarts) el.innerHTML = '<div class="chart-fallback">图表组件（ECharts CDN）加载失败，请联网后刷新</div>';
  }
  let toastTimer = null;
  function toast(msg) {
    const t = $('#toast');
    t.textContent = msg; t.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => t.classList.remove('show'), 2200);
  }

  /* ==================== 数据聚合 ==================== */
  function sumOver(list, fn) {
    const r = { gmv: 0, ns: 0, rc: 0, ra: 0 };
    list.forEach(p => {
      const v = fn(p);
      if (!v) return;
      MKEYS.forEach(k => { r[k] = D.round2(r[k] + (v[k] || 0)); });
    });
    return r;
  }
  function currentPeople() {
    if (state.scope === 'company') return D.people.filter(p => !p.ungrouped);
    if (state.scope === 'team') {
      const t = D.teams.find(t => t.name === state.objectTeam);
      return t.members.map(id => D.people.find(p => p.id === id));
    }
    return [D.byName[state.objectPerson]];
  }
  function scopeLabel() {
    if (state.scope === 'company') return '全员总览（主名单 20 人）';
    if (state.scope === 'team') return `战队 · ${state.objectTeam}`;
    return `个人 · ${state.objectPerson}`;
  }
  const PERIOD_LABEL = { year: '年度（1月1日-10月23日）', q3: 'Q3（7-9月）', m9: '9月（单月）' };
  /** 当前周期下，一组人的 目标/完成/上期完成/时间进度 */
  function periodAgg(people, period) {
    const tp = period === 'year' ? D.TP_YEAR : 100;
    let target, done, prev, momLabel;
    if (period === 'year') {
      target = sumOver(people, p => (p.ungrouped ? null : p.targets));
      done = sumOver(people, p => p.total);
      prev = sumOver(people, p => p.sep);
      momLabel = '较9月底';
    } else if (period === 'q3') {
      target = sumOver(people, p => (p.ungrouped ? null : { gmv: p.quarters.gmv[2], ns: p.quarters.ns[2], rc: p.quarters.rc[2], ra: p.quarters.ra[2] }));
      done = sumOver(people, p => ({ gmv: p.series.gmv.inc[6] + p.series.gmv.inc[7] + p.series.gmv.inc[8], ns: p.series.ns.inc[6] + p.series.ns.inc[7] + p.series.ns.inc[8], rc: p.series.rc.inc[6] + p.series.rc.inc[7] + p.series.rc.inc[8], ra: p.series.ra.inc[6] + p.series.ra.inc[7] + p.series.ra.inc[8] }));
      prev = sumOver(people, p => ({ gmv: p.series.gmv.inc[6] + p.series.gmv.inc[7], ns: p.series.ns.inc[6] + p.series.ns.inc[7], rc: p.series.rc.inc[6] + p.series.rc.inc[7], ra: p.series.ra.inc[6] + p.series.ra.inc[7] }));
      momLabel = '较8月底';
    } else {
      target = sumOver(people, p => (p.ungrouped ? null : { gmv: p.months.gmv[8], ns: p.months.ns[8], rc: p.months.rc[8], ra: p.months.ra[8] }));
      done = sumOver(people, p => ({ gmv: p.series.gmv.inc[8], ns: p.series.ns.inc[8], rc: p.series.rc.inc[8], ra: p.series.ra.inc[8] }));
      prev = sumOver(people, p => ({ gmv: p.series.gmv.inc[7], ns: p.series.ns.inc[7], rc: p.series.rc.inc[7], ra: p.series.ra.inc[7] }));
      momLabel = '较8月单月';
    }
    return { target, done, prev, tp, momLabel };
  }
  function scopeSeries(people, k) {
    const cum = new Array(12).fill(0), inc = new Array(12).fill(0);
    people.forEach(p => {
      for (let i = 0; i < 12; i++) {
        cum[i] += p.series[k].cum[i] || 0;
        inc[i] += p.series[k].inc[i] || 0;
      }
    });
    return { cum: cum.map(v => D.round2(v)), inc: inc.map(v => D.round2(v)) };
  }

  /* ==================== 视图 A · 汇总卡 ==================== */
  function renderCards() {
    const agg = periodAgg(currentPeople(), state.period);
    $('#metric-cards').innerHTML = METRICS.map(m => {
      const t = agg.target[m.key], d = agg.done[m.key];
      const rate = rateOf(d, t);
      const delta = rate == null ? null : D.round2(rate - agg.tp);
      const momPp = t ? D.round2(((d - agg.prev[m.key]) / t) * 100) : null;
      const fillW = rate == null ? 0 : Math.min(rate, 100);
      const tpW = Math.min(agg.tp, 100);
      return `<div class="mcard">
        <div class="m-name">${m.name} <span class="m-tag">${m.unit} · ${PERIOD_LABEL[state.period].split('（')[0]}</span></div>
        <div class="m-rate">${rate == null ? '<span style="font-size:20px;color:var(--faint)">未设目标</span>' : rate.toFixed(1) + '<small>%</small>'}</div>
        <div class="m-nums"><span>已完成 <b>${fmtVShort(m.key, d)}</b></span><span>目标 <b>${t ? fmtVShort(m.key, t) : '—'}</b></span></div>
        <div class="m-progress">
          <div class="fill ${rate != null && rate >= 100 ? 'over' : ''}" style="width:${fillW}%"></div>
          <div class="tp-mark" style="left:${tpW}%" data-tp="${agg.tp}%"></div>
        </div>
        <div class="m-foot">
          ${delta == null ? '<span class="delta" style="color:var(--faint)">—</span>'
          : `<span class="delta ${delta >= 0 ? 'up' : 'down'}">${delta >= 0 ? '超前' : '落后'} ${D.fmtPp(delta)}</span>`}
          <span class="mom">${momPp == null ? '' : `${agg.momLabel} ${D.fmtPp(momPp)}`}</span>
        </div>
      </div>`;
    }).join('');
  }

  /* ==================== 视图 A · 子弹图 ==================== */
  function renderBullets() {
    const agg = periodAgg(currentPeople(), state.period);
    const wrap = $('#bullet-wrap');
    wrap.innerHTML = METRICS.map(m => {
      const t = agg.target[m.key], d = agg.done[m.key];
      const rate = rateOf(d, t);
      const delta = rate == null ? null : D.round2(rate - agg.tp);
      return `<div class="bullet-item">
        <div class="b-head">
          <span><b>${m.name}</b> ${fmtVShort(m.key, d)} / ${t ? fmtVShort(m.key, t) : '—'}</span>
          <span>${rate == null ? '—' : rate.toFixed(1) + '%'} ${delta == null ? '' : `<span class="delta ${delta >= 0 ? 'up' : 'down'}">${D.fmtPp(delta)}</span>`}</span>
        </div>
        <div class="bullet-chart" id="bullet-${m.key}"></div>
      </div>`;
    }).join('');
    METRICS.forEach(m => {
      const id = 'bullet-' + m.key;
      if (!window.echarts) { chartFallback(id); return; }
      const ch = chartOf(id);
      const t = agg.target[m.key], d = agg.done[m.key];
      const rate = rateOf(d, t);
      const scale = Math.max(t || 0, d) * 1.12 || 1;
      const color = rate == null ? C_TARGET : rate >= 100 ? C_GREEN : rate >= agg.tp ? C_ACT : rate >= agg.tp - 30 ? C_ORANGE : C_RED;
      ch.setOption({
        grid: { left: 2, right: 2, top: 8, bottom: 8 },
        xAxis: { type: 'value', max: scale, show: false },
        yAxis: { type: 'category', data: [''], show: false },
        animationDuration: 400,
        series: [
          { type: 'bar', barWidth: 18, barGap: '-100%', silent: true, data: [scale], itemStyle: { color: '#f1f5f9', borderRadius: 3 }, tooltip: { show: false } },
          { type: 'bar', barWidth: 18, barGap: '-100%', silent: true, data: [t || 0], itemStyle: { color: '#dbe3ec', borderRadius: 3 }, tooltip: { show: false } },
          {
            type: 'bar', barWidth: 9, barGap: '-100%', data: [d], itemStyle: { color, borderRadius: 2 },
            markLine: t ? {
              symbol: 'none', silent: true, animation: false,
              data: [{ xAxis: (t * agg.tp) / 100 }],
              lineStyle: { color: C_AMBER, type: 'dashed', width: 2 },
              label: { show: false },
            } : undefined,
          },
        ],
      }, true);
    });
  }

  /* ==================== 视图 A · 冲刺提示 ==================== */
  function buildHints() {
    const people = currentPeople().filter(p => !p.ungrouped);
    const cands = [];
    people.forEach(p => {
      MKEYS.forEach(k => {
        const t = p.targets[k], d = p.total[k];
        if (!t) return;
        const rate = rateOf(d, t);
        const proj = (d / ELAPSED_DAYS) * 365;
        const projRate = rateOf(proj, t);
        if (rate < D.TP_YEAR || projRate < 100) {
          cands.push({ p, k, t, d, rate, projRate, gap: D.round2(t - d) });
        }
      });
    });
    cands.sort((a, b) => a.projRate - b.projRate);
    // 按人去重：每人只保留最严重的一条，再取前 3
    const seen = new Set();
    const list = [];
    for (const c of cands) {
      if (seen.has(c.p.id)) continue;
      seen.add(c.p.id);
      list.push(c);
      if (list.length >= 3) break;
    }
    if (!list.length) {
      return '<div class="hint-item ok"><b>✓</b> 当前范围各指标按现有速率均可如期完成，无需冲刺。</div>';
    }
    return list.map(c => `<div class="hint-item">
      <span class="h-name">${esc(c.p.name)}</span> · ${mName(c.k)}
      缺口 <b>${fmtV(c.k, c.gap)}</b>，按当前速率预计期末完成 <b>${c.projRate.toFixed(1)}%</b><br>
      <span style="color:var(--faint)">当前 ${c.rate.toFixed(1)}% / 时间进度 ${D.TP_YEAR}% · 剩余 ${REMAIN_DAYS} 天需日均 ${fmtV(c.k, D.round2(c.gap / REMAIN_DAYS))}</span>
    </div>`).join('');
  }
  function renderHints() { $('#hint-list').innerHTML = buildHints(); }

  /* ==================== 视图 A · 趋势图 ==================== */
  // 9 月逐日累积权重（固定 seed，一次性生成）
  const DAY_CUM = (() => {
    let s = 20261023;
    const r = () => { s = (s * 1103515245 + 12345) % 2147483648; return s / 2147483648; };
    const w = Array.from({ length: 30 }, (_, i) => (0.7 + (0.6 * i) / 30) * (0.85 + 0.3 * r()));
    const sum = w.reduce((a, b) => a + b, 0);
    let acc = 0;
    return w.map(v => (acc += v / sum));
  })();

  function metricSwitchHtml(active) {
    return METRICS.map(m => `<button data-metric="${m.key}" class="${m.key === active ? 'active' : ''}">${m.name}</button>`).join('');
  }
  function renderTrend() {
    $('#trend-metric-switch').innerHTML = metricSwitchHtml(state.trendMetric);
    const notes = {
      year: '实线=实际累积 · 虚线=10月进行中 · 灰实线=目标计划（季度拆分）· 灰虚线=时间进度',
      q3: 'Q3 内累积：7-9 月 · 灰实线=季度目标季内均分 · 灰虚线=季内时间进度',
      m9: '9 月逐日累积（mock 分布，月总量锚定真实值）· 灰线=月度目标线性计划',
    };
    $('#trend-note').textContent = notes[state.period];
    const k = state.trendMetric;
    const people = currentPeople();
    const ch = chartOf('chart-trend');
    if (!ch) { chartFallback('chart-trend'); return; }
    const money = METRICS.find(m => m.key === k).money;
    const agg = periodAgg(people, state.period);
    const T = agg.target[k] || 0;
    let option;
    const common = {
      animationDuration: 400,
      tooltip: { trigger: 'axis', valueFormatter: v => (v == null ? '—' : money ? D.fmtMoney(v) : D.fmtInt(v) + ' 个') },
      legend: { bottom: 0, itemWidth: 14, textStyle: { fontSize: 12, color: '#6b7280' } },
      grid: { left: 16, right: 24, top: 30, bottom: 34, containLabel: true },
    };
    if (state.period === 'year') {
      const s = scopeSeries(people, k);
      const x = Array.from({ length: 12 }, (_, i) => (i + 1) + '月');
      option = Object.assign(common, {
        xAxis: { type: 'category', data: x, boundaryGap: false, axisLine: { lineStyle: { color: '#d1d5db' } } },
        yAxis: { type: 'value', splitLine: { lineStyle: { color: '#f0f2f5' } }, axisLabel: { formatter: v => (money ? '$' + (v >= 10000 ? (v / 10000) + '万' : v) : v) } },
        series: [
          { name: '实际累积', type: 'line', data: s.cum.slice(0, 9), smooth: true, symbolSize: 5, lineStyle: { width: 2.5, color: C_ACT }, itemStyle: { color: C_ACT }, areaStyle: { color: 'rgba(37,99,235,.07)' } },
          { name: '10月进行中', type: 'line', data: [...Array(8).fill(null), s.cum[8], s.cum[9]], smooth: true, symbolSize: 5, lineStyle: { width: 2.5, color: C_ACT, type: 'dashed' }, itemStyle: { color: C_ACT } },
          { name: '目标计划（季度拆分）', type: 'line', data: D.PLAN_CUM.map(p => D.round2((T * p) / 100)), symbol: 'none', lineStyle: { width: 1.5, color: C_TARGET }, itemStyle: { color: C_TARGET } },
          { name: '时间进度参考', type: 'line', data: D.PACE_CUM.map(p => D.round2((T * p) / 100)), symbol: 'none', lineStyle: { width: 1.5, color: C_GRAY, type: 'dashed' }, itemStyle: { color: C_GRAY } },
        ],
      });
    } else if (state.period === 'q3') {
      const s = scopeSeries(people, k);
      const c6 = s.inc[6], c7 = c6 + s.inc[7], c8 = c7 + s.inc[8];
      option = Object.assign(common, {
        xAxis: { type: 'category', data: ['7月', '8月', '9月'], boundaryGap: false },
        yAxis: { type: 'value', splitLine: { lineStyle: { color: '#f0f2f5' } }, axisLabel: { formatter: v => (money ? '$' + (v >= 10000 ? (v / 10000) + '万' : v) : v) } },
        series: [
          { name: '实际累积（Q3内）', type: 'line', data: [c6, c7, c8], symbolSize: 6, lineStyle: { width: 2.5, color: C_ACT }, itemStyle: { color: C_ACT }, areaStyle: { color: 'rgba(37,99,235,.07)' } },
          { name: '目标计划（季内均分）', type: 'line', data: [T / 3, (2 * T) / 3, T].map(v => D.round2(v)), symbol: 'none', lineStyle: { width: 1.5, color: C_TARGET }, itemStyle: { color: C_TARGET } },
          { name: '时间进度参考', type: 'line', data: [0.32 * T, 0.65 * T, T].map(v => D.round2(v)), symbol: 'none', lineStyle: { width: 1.5, color: C_GRAY, type: 'dashed' }, itemStyle: { color: C_GRAY } },
        ],
      });
    } else {
      const s = scopeSeries(people, k);
      const sep = s.inc[8];
      option = Object.assign(common, {
        xAxis: { type: 'category', data: Array.from({ length: 30 }, (_, i) => (i + 1) + '日'), boundaryGap: false },
        yAxis: { type: 'value', splitLine: { lineStyle: { color: '#f0f2f5' } } },
        series: [
          { name: '实际累积（9月逐日）', type: 'line', data: DAY_CUM.map(c => D.round2(sep * c)), symbol: 'none', lineStyle: { width: 2.5, color: C_ACT }, itemStyle: { color: C_ACT }, areaStyle: { color: 'rgba(37,99,235,.07)' } },
          { name: '目标计划（线性）', type: 'line', data: DAY_CUM.map((_, i) => D.round2((T * (i + 1)) / 30)), symbol: 'none', lineStyle: { width: 1.5, color: C_TARGET }, itemStyle: { color: C_TARGET } },
          { name: '时间进度参考', type: 'line', data: DAY_CUM.map((_, i) => D.round2((T * (i + 1)) / 30)), symbol: 'none', lineStyle: { width: 1.5, color: C_GRAY, type: 'dashed' }, itemStyle: { color: C_GRAY } },
        ],
      });
    }
    ch.setOption(option, true);
  }

  /* ==================== 视图 A · 单月柱状图 ==================== */
  function renderMonthly() {
    $('#monthly-metric-switch').innerHTML = metricSwitchHtml(state.monthlyMetric);
    const k = state.monthlyMetric;
    const ch = chartOf('chart-monthly');
    if (!ch) { chartFallback('chart-monthly'); return; }
    const people = currentPeople();
    const s = scopeSeries(people, k);
    const money = METRICS.find(m => m.key === k).money;
    const T = periodAgg(people, 'year').target[k] || 0;
    const data = s.inc.slice(0, 10).map((v, i) => ({
      value: v,
      itemStyle: { color: i === 9 ? C_AMBER : C_ACT, borderRadius: [4, 4, 0, 0] },
    }));
    ch.setOption({
      animationDuration: 400,
      tooltip: { trigger: 'axis', valueFormatter: v => (money ? D.fmtMoney(v) : D.fmtInt(v) + ' 个') },
      grid: { left: 16, right: 24, top: 30, bottom: 26, containLabel: true },
      xAxis: { type: 'category', data: Array.from({ length: 10 }, (_, i) => (i + 1) + '月'), axisLine: { lineStyle: { color: '#d1d5db' } } },
      yAxis: { type: 'value', splitLine: { lineStyle: { color: '#f0f2f5' } }, axisLabel: { formatter: v => (money ? '$' + (v >= 10000 ? (v / 10000) + '万' : v) : v) } },
      series: [{
        name: mName(k) + ' 单月完成', type: 'bar', data, barMaxWidth: 42,
        markLine: {
          symbol: 'none', silent: true,
          data: [{ yAxis: D.round2(T / 12), label: { formatter: '月均目标', position: 'insideEndTop', fontSize: 11, color: '#6b7280' } }],
          lineStyle: { color: C_TARGET, type: 'dashed' },
        },
      }],
    }, true);
  }

  /* ==================== 视图 A · 团队区 ==================== */
  function teamPeriodStats(metric) {
    return D.teams.map(t => {
      const members = t.members.map(id => D.people.find(p => p.id === id));
      const agg = periodAgg(members, state.period);
      const rate = rateOf(agg.done[metric], agg.target[metric]);
      return { t, members, agg, rate };
    });
  }
  function renderTeamChart() {
    $('#team-metric-switch').innerHTML = metricSwitchHtml(state.teamMetric);
    const ch = chartOf('chart-teams');
    if (!ch) { chartFallback('chart-teams'); return; }
    const k = state.teamMetric;
    const tp = state.period === 'year' ? D.TP_YEAR : 100;
    const stats = teamPeriodStats(k).sort((a, b) => (b.rate || 0) - (a.rate || 0));
    const money = METRICS.find(m => m.key === k).money;
    ch.setOption({
      animationDuration: 400,
      tooltip: {
        trigger: 'axis', axisPointer: { type: 'shadow' },
        formatter: ps => {
          const s = stats[ps[0].dataIndex];
          return `${s.t.name}（队长 ${s.t.captain}）<br/>${mName(k)}：${fmtVShort(k, s.agg.done[k])} / ${fmtVShort(k, s.agg.target[k])} · <b>${s.rate == null ? '—' : s.rate.toFixed(1) + '%'}</b>`;
        },
      },
      grid: { left: 16, right: 130, top: 10, bottom: 10, containLabel: true },
      xAxis: { type: 'value', splitLine: { lineStyle: { color: '#f0f2f5' } }, axisLabel: { formatter: v => (money ? '$' + (v >= 10000 ? (v / 10000) + '万' : v) : v) } },
      yAxis: { type: 'category', inverse: true, data: stats.map(s => s.t.name), axisLine: { lineStyle: { color: '#d1d5db' } } },
      series: [{
        type: 'bar', barWidth: 18,
        data: stats.map(s => ({
          value: s.agg.done[k],
          itemStyle: { color: s.rate == null ? C_TARGET : s.rate >= 100 ? C_GREEN : s.rate >= tp ? C_ACT : C_ORANGE, borderRadius: [0, 4, 4, 0] },
        })),
        label: {
          show: true, position: 'right', fontSize: 11.5, color: '#4b5563',
          formatter: p => {
            const s = stats[p.dataIndex];
            return `${s.rate == null ? '—' : s.rate.toFixed(1) + '%'}  ${fmtVShort(k, s.agg.done[k])} / ${fmtVShort(k, s.agg.target[k])}`;
          },
        },
      }],
    }, true);
  }
  function miniBar(rate, w) {
    const cls = rate == null ? 'none' : rate >= 100 ? 'over' : rate >= (state.period === 'year' ? D.TP_YEAR : 100) ? '' : 'lag';
    return `<span class="tm-bar"><i class="${cls}" style="width:${Math.min(w == null ? (rate || 0) : w, 100)}%"></i></span>`;
  }
  function renderTeamCards() {
    const hl = state.scope === 'team' ? state.objectTeam : (state.scope === 'person' ? (D.byName[state.objectPerson] || {}).team : '');
    $('#team-grid').innerHTML = teamPeriodStats('gmv').map(({ t, members }) => {
      const agg = periodAgg(members, state.period);
      const gRate = rateOf(agg.done.gmv, agg.target.gmv);
      const metricRows = METRICS.map(m => {
        const r = rateOf(agg.done[m.key], agg.target[m.key]);
        return `<div class="t-metric"><span class="tm-name">${m.name}</span>${miniBar(r)}<span class="tm-val">${r == null ? '—' : r.toFixed(1) + '%'}</span></div>`;
      }).join('');
      const memberRows = members.map(p => {
        const pa = periodAgg([p], state.period);
        const r = p.ungrouped ? null : rateOf(pa.done.gmv, pa.target.gmv);
        return `<div class="t-member"><span class="tm-name">${esc(p.name)}${p.ungrouped ? '*' : ''}</span>${miniBar(r)}<span class="tm-val">${r == null ? '未设目标' : r.toFixed(1) + '%'}</span></div>`;
      }).join('');
      return `<div class="team-card ${t.name === hl ? 'hl' : ''}">
        <div class="t-head"><b>${esc(t.name)}</b><span>队长 ${esc(t.captain)} · ${members.length}人</span><span class="t-rate" style="color:${gRate != null && gRate >= 100 ? C_GREEN : C_ACT}">${gRate == null ? '—' : gRate.toFixed(1) + '%'}</span></div>
        <div class="t-metrics">${metricRows}</div>
        <div class="t-members">${memberRows}</div>
      </div>`;
    }).join('') + '<div class="footnote" style="grid-column:1/-1;margin-top:0">* 未设年度目标成员：展示完成值、不参与完成率计算；战队目标 = 有目标成员目标汇总自动得出。完成值含 10 月 1-23 日进展。</div>';
  }

  /* ==================== 视图 A · 个人排名 ==================== */
  const SORTS = {
    gmvRate: (a, b) => a._r.gmv - b._r.gmv,
    gmvTarget: (a, b) => a._agg.target.gmv - b._agg.target.gmv,
    gmvDone: (a, b) => a._agg.done.gmv - b._agg.done.gmv,
    nsRate: (a, b) => a._r.ns - b._r.ns,
    rcRate: (a, b) => a._r.rc - b._r.rc,
    raRate: (a, b) => a._r.ra - b._r.ra,
    paceDiff: (a, b) => (a._r.gmv - a._tp) - (b._r.gmv - b._tp),
  };
  function rankingRows() {
    let targeted, extras;
    if (state.scope === 'team') {
      const members = currentPeople();
      targeted = members.filter(p => !p.ungrouped);
      extras = members.filter(p => p.ungrouped);
    } else {
      targeted = D.people.filter(p => !p.ungrouped);
      extras = D.people.filter(p => p.ungrouped);
    }
    targeted.forEach(p => {
      p._agg = periodAgg([p], state.period);
      p._tp = p._agg.tp;
      p._r = { gmv: rateOf(p._agg.done.gmv, p._agg.target.gmv) || 0, ns: rateOf(p._agg.done.ns, p._agg.target.ns) || 0, rc: rateOf(p._agg.done.rc, p._agg.target.rc) || 0, ra: rateOf(p._agg.done.ra, p._agg.target.ra) || 0 };
    });
    extras.forEach(p => { p._agg = periodAgg([p], state.period); p._tp = p._agg.tp; });
    targeted.sort((a, b) => SORTS[state.sort.key](a, b) * state.sort.dir);
    return { targeted, extras };
  }
  function thCell(label, key, cls) {
    const cur = state.sort.key === key;
    const arrow = cur ? (state.sort.dir === -1 ? '▼' : '▲') : '';
    return `<th class="sortable ${cls || ''}" data-sort="${key}">${label}<span class="arrow">${arrow}</span></th>`;
  }
  function renderRanking() {
    const { targeted, extras } = rankingRows();
    const aggAll = periodAgg(targeted, state.period);
    const totalRate = { gmv: rateOf(aggAll.done.gmv, aggAll.target.gmv), ns: rateOf(aggAll.done.ns, aggAll.target.ns), rc: rateOf(aggAll.done.rc, aggAll.target.rc), ra: rateOf(aggAll.done.ra, aggAll.target.ra) };
    const metricCell = (p, k) => {
      const t = p._agg.target[k], d = p._agg.done[k], r = rateOf(d, t);
      return `<div>${fmtVShort(k, d)} <span style="color:var(--faint)">/ ${fmtVShort(k, t)}</span></div><div style="font-size:11.5px;color:${r >= 100 ? C_GREEN : r >= p._tp ? C_ACT : C_RED}">${r.toFixed(1)}%</div>`;
    };
    const rows = targeted.map((p, i) => {
      const diff = D.round2(p._r.gmv - p._tp);
      const st = D.statusOf(p._r.gmv, p._tp);
      const hlRow = state.scope === 'person' && p.name === state.objectPerson;
      return `<tr class="${hlRow ? 'row-hl' : ''}" data-person="${esc(p.name)}">
        <td class="c">${i + 1}</td>
        <td><b>${esc(p.name)}</b>${p.team && p.team === p.name ? '' : ''}${isCaptain(p.name) ? ' <span class="tag blue">队长</span>' : ''}</td>
        <td>${esc(p.team)}</td>
        <td class="r">${D.fmtMoney(p._agg.target.gmv)}</td>
        <td class="r"><b>${D.fmtMoney(p._agg.done.gmv)}</b></td>
        <td class="r" style="color:${p._r.gmv >= 100 ? C_GREEN : p._r.gmv >= p._tp ? C_ACT : C_RED};font-weight:600">${p._r.gmv.toFixed(1)}%</td>
        <td class="c">${metricCell(p, 'ns')}</td>
        <td class="c">${metricCell(p, 'rc')}</td>
        <td class="c">${metricCell(p, 'ra')}</td>
        <td class="r"><span class="delta ${diff >= 0 ? 'up' : 'down'}">${D.fmtPp(diff)}</span></td>
        <td><span class="tag ${st.key}">${st.text}</span></td>
      </tr>`;
    }).join('');
    const extraRows = extras.map(p => `<tr class="row-dim">
      <td class="c">—</td><td>${esc(p.name)} <span class="tag gray">未设目标</span></td><td>${esc(p.team)}</td>
      <td class="r">—</td><td class="r">${D.fmtMoney(p._agg.done.gmv)}</td><td class="r">—</td>
      <td class="c"><div>${D.fmtInt(p._agg.done.ns)} / —</div><div style="font-size:11.5px">—</div></td>
      <td class="c"><div>${D.fmtInt(p._agg.done.rc)} / —</div><div style="font-size:11.5px">—</div></td>
      <td class="c"><div>${D.fmtMoney(p._agg.done.ra)} / —</div><div style="font-size:11.5px">—</div></td>
      <td class="r">—</td><td><span class="tag gray">未设目标</span></td>
    </tr>`).join('');
    const totalRow = `<tr class="row-total">
      <td></td><td>${state.scope === 'team' ? `队内有目标成员合计（${targeted.length}人）` : `主名单合计（${targeted.length}人）`}</td><td>—</td>
      <td class="r">${D.fmtMoney(aggAll.target.gmv)}</td><td class="r">${D.fmtMoney(aggAll.done.gmv)}</td>
      <td class="r">${totalRate.gmv.toFixed(1)}%</td>
      <td class="c">${D.fmtInt(aggAll.done.ns)} / ${D.fmtInt(aggAll.target.ns)} · ${totalRate.ns.toFixed(1)}%</td>
      <td class="c">${D.fmtInt(aggAll.done.rc)} / ${D.fmtInt(aggAll.target.rc)} · ${totalRate.rc.toFixed(1)}%</td>
      <td class="c">${D.fmtMoney(aggAll.done.ra)} / ${D.fmtMoney(aggAll.target.ra)} · ${totalRate.ra.toFixed(1)}%</td>
      <td class="r"><span class="delta ${totalRate.gmv - aggAll.tp >= 0 ? 'up' : 'down'}">${D.fmtPp(D.round2(totalRate.gmv - aggAll.tp))}</span></td>
      <td>—</td>
    </tr>`;
    $('#ranking-wrap').innerHTML = `<table class="tbl">
      <thead><tr>
        <th class="c">排名</th><th>姓名</th><th>战队</th>
        ${thCell('GMV目标', 'gmvTarget', 'r')}${thCell('GMV完成', 'gmvDone', 'r')}${thCell('GMV完成率', 'gmvRate', 'r')}
        ${thCell('新签 完成/目标', 'nsRate', 'c')}${thCell('复购客户 完成/目标', 'rcRate', 'c')}${thCell('复购金额 完成/目标', 'raRate', 'c')}
        ${thCell('与时间进度差', 'paceDiff', 'r')}<th>状态</th>
      </tr></thead>
      <tbody>${totalRow}${rows}${extraRows}</tbody>
    </table>
    <div class="footnote">周期：${PERIOD_LABEL[state.period]} · 时间进度 ${state.period === 'year' ? D.TP_YEAR : 100}% · 完成值含 10 月 1-23 日进展；单列 3 人（未设年度目标）置灰列于表尾，不计入合计。</div>`;
    if (state.scope === 'person') {
      const tr = $('#ranking-wrap tr.row-hl');
      if (tr) setTimeout(() => tr.scrollIntoView({ block: 'center', behavior: 'smooth' }), 60);
    }
  }
  function isCaptain(name) { return D.teams.some(t => t.captain === name); }

  /* ==================== 视图 A · 指标明细 ==================== */
  const DETAIL_TABS = [
    { key: 'gmv', name: 'GMV订单', tag: null },
    { key: 'ns', name: '新签客户', tag: '新签' },
    { key: 'rc', name: '复购客户', tag: '复购' },
    { key: 'ra', name: '复购金额', tag: '复购' },
  ];
  const RANGES = [
    { key: '', name: '全部时间' }, { key: 'q1', name: 'Q1' }, { key: 'q2', name: 'Q2' },
    { key: 'q3', name: 'Q3' }, { key: 'm9', name: '9月' }, { key: 'oct', name: '10月至今' },
  ];
  function rangeOk(month, range) {
    if (!range) return true;
    if (range === 'q1') return month >= 1 && month <= 3;
    if (range === 'q2') return month >= 4 && month <= 6;
    if (range === 'q3') return month >= 7 && month <= 9;
    if (range === 'm9') return month === 9;
    if (range === 'oct') return month === 10;
    return true;
  }
  function detailRows() {
    const f = state.detail;
    const ok = r => (!f.person || r.person === f.person) && (!f.team || r.team === f.team) && rangeOk(r.month, f.range);
    if (f.tab === 'gmv') return D.orders.filter(ok);
    if (f.tab === 'ns') return D.nsCustomers.filter(ok);
    if (f.tab === 'rc') return D.rcCustomers.filter(ok);
    return D.orders.filter(o => o.tag === '复购').filter(ok);
  }
  function renderDetail() {
    const f = state.detail;
    $('#detail-tabs').innerHTML = DETAIL_TABS.map(t => `<button data-tab="${t.key}" class="${t.key === f.tab ? 'active' : ''}">${t.name}</button>`).join('');
    const personOpts = ['<option value="">全部业务员</option>'].concat(D.people.map(p => `<option ${p.name === f.person ? 'selected' : ''}>${p.name}</option>`)).join('');
    const teamOpts = ['<option value="">全部战队</option>'].concat(D.teams.map(t => `<option ${t.name === f.team ? 'selected' : ''}>${t.name}</option>`)).join('');
    const rangeOpts = RANGES.map(r => `<option value="${r.key}" ${r.key === f.range ? 'selected' : ''}>${r.name}</option>`).join('');
    const rows = detailRows();
    const totalAmt = D.round2(rows.reduce((a, r) => a + (r.amount || 0), 0));
    const mainIds = new Set(D.people.filter(p => !p.ungrouped).map(p => p.id));
    const mainAmt = D.round2(rows.filter(r => mainIds.has(r.personId)).reduce((a, r) => a + (r.amount || 0), 0));
    const isCountTab = f.tab === 'ns' || f.tab === 'rc';
    const sumText = isCountTab
      ? `共 <b>${rows.length}</b> 个客户 · 金额合计 <b>${D.fmtMoney(totalAmt)}</b>`
      : `共 <b>${rows.length}</b> 条 · 合计 <b>${D.fmtMoney(totalAmt)}</b>`;
    const splitNote = (!f.person && !f.team && totalAmt !== mainAmt)
      ? `（主名单 ${D.fmtMoney(mainAmt)} · 单列 ${D.fmtMoney(D.round2(totalAmt - mainAmt))}）` : '';
    $('#detail-filters').innerHTML = `
      <label style="color:var(--muted);font-size:13px">业务员</label><select class="select" id="df-person">${personOpts}</select>
      <label style="color:var(--muted);font-size:13px">战队</label><select class="select" id="df-team">${teamOpts}</select>
      <label style="color:var(--muted);font-size:13px">时间范围</label><select class="select" id="df-range">${rangeOpts}</select>
      <span class="sum">${sumText}${splitNote}</span>`;
    // 表格
    const pageSize = 15;
    const pages = Math.max(1, Math.ceil(rows.length / pageSize));
    if (f.page > pages) f.page = pages;
    const pageRows = rows.slice((f.page - 1) * pageSize, f.page * pageSize);
    let head, body;
    const tagHtml = t => `<span class="tag ${t === '新签' ? 'blue' : 'green'}">${t}</span>`;
    if (f.tab === 'gmv' || f.tab === 'ra') {
      head = '<tr><th>订单号</th><th>客户公司</th><th>国家</th><th class="r">金额(USD)</th><th>下单日期</th><th>业务员</th><th>战队</th><th>指标标记</th></tr>';
      body = pageRows.map(o => `<tr><td>${o.no}</td><td>${esc(o.company)}</td><td>${o.country}</td><td class="r"><b>${D.fmtMoney(o.amount, true)}</b></td><td>${o.date}</td><td>${o.person}</td><td>${o.team}</td><td>${tagHtml(o.tag)}</td></tr>`).join('');
    } else if (f.tab === 'ns') {
      head = '<tr><th>客户编号</th><th>客户公司</th><th>国家</th><th class="r">首单金额(USD)</th><th>首单日期</th><th>业务员</th><th>战队</th><th>指标标记</th></tr>';
      body = pageRows.map(c => `<tr><td>${c.id}</td><td>${esc(c.company)}</td><td>${c.country}</td><td class="r"><b>${D.fmtMoney(c.amount, true)}</b></td><td>${c.firstDate}</td><td>${c.person}</td><td>${c.team}</td><td>${tagHtml('新签')}</td></tr>`).join('');
    } else {
      head = '<tr><th>客户编号</th><th>客户公司</th><th>国家</th><th class="c">复购订单数</th><th class="r">复购金额累计(USD)</th><th>最近复购日期</th><th>业务员</th><th>战队</th><th>指标标记</th></tr>';
      body = pageRows.map(c => `<tr><td>${c.id}</td><td>${esc(c.company)}</td><td>${c.country}</td><td class="c">${c.orderCount}</td><td class="r"><b>${D.fmtMoney(c.amount, true)}</b></td><td>${c.lastDate}</td><td>${c.person}</td><td>${c.team}</td><td>${tagHtml('复购')}</td></tr>`).join('');
    }
    $('#detail-table').innerHTML = `<table class="tbl"><thead>${head}</thead><tbody>${body || '<tr><td colspan="9" style="text-align:center;color:var(--faint);padding:30px">当前筛选无数据</td></tr>'}</tbody></table>`;
    // 分页
    let btns = '';
    const win = [];
    for (let i = 1; i <= pages; i++) {
      if (i === 1 || i === pages || Math.abs(i - f.page) <= 2) win.push(i);
    }
    let last = 0;
    win.forEach(i => {
      if (i - last > 1) btns += '<span>…</span>';
      btns += `<button data-page="${i}" class="${i === f.page ? 'active' : ''}">${i}</button>`;
      last = i;
    });
    $('#detail-pager').innerHTML = `<span>每页 15 条 · 共 ${rows.length} 条</span>
      <button data-page="${f.page - 1}" ${f.page <= 1 ? 'disabled' : ''}>‹</button>${btns}<button data-page="${f.page + 1}" ${f.page >= pages ? 'disabled' : ''}>›</button>`;
  }

  /* ==================== 视图 A · 总渲染 ==================== */
  function renderDashboard() {
    renderCards();
    renderBullets();
    renderHints();
    renderTrend();
    renderMonthly();
    renderTeamChart();
    renderTeamCards();
    renderRanking();
    renderDetail();
  }

  /* ==================== 视图 B · 目标设置 ==================== */
  function splitSeason(v) {
    const q = D.SEASON.map(s => D.round2(v * s));
    q[3] = D.round2(q[3] + (v - q.reduce((a, b) => a + b, 0)));
    return q;
  }
  function allocInt(total, weights) {
    const wsum = weights.reduce((a, b) => a + b, 0);
    const raw = weights.map(w => (w / wsum) * total);
    const base = raw.map(Math.floor);
    let rem = total - base.reduce((a, b) => a + b, 0);
    const order = raw.map((r, i) => [r - Math.floor(r), i]).sort((a, b) => b[0] - a[0]);
    for (let k = 0; k < rem; k++) base[order[k % order.length][1]]++;
    return base;
  }
  function resplitPerson(p, metricOnly) {
    const ks = metricOnly ? [metricOnly] : MKEYS;
    ks.forEach(k => {
      if (k === 'ns' || k === 'rc') p.quarters[k] = allocInt(p.targets[k], D.SEASON);
      else p.quarters[k] = splitSeason(p.targets[k]);
    });
    rebuildMonths(p);
  }
  function rebuildMonths(p) {
    ['gmv', 'ra'].forEach(k => {
      p.months[k] = [];
      p.quarters[k].forEach(qv => {
        const m = [D.round2(qv / 3), D.round2(qv / 3), 0];
        m[2] = D.round2(qv - m[0] - m[1]);
        p.months[k].push(...m);
      });
    });
    ['ns', 'rc'].forEach(k => {
      p.months[k] = [];
      p.quarters[k].forEach(qv => p.months[k].push(...allocInt(qv, [1, 1, 1])));
    });
  }
  function quarterIssues(metricOnly) {
    const issues = [];
    D.people.filter(p => !p.ungrouped).forEach(p => {
      (metricOnly ? [metricOnly] : MKEYS).forEach(k => {
        const sum = D.round2(p.quarters[k].reduce((a, b) => a + b, 0));
        const diff = D.round2(sum - p.targets[k]);
        if (Math.abs(diff) > 0.005) issues.push({ person: p.name, k, diff });
      });
    });
    return issues;
  }
  function monthIssues() {
    const issues = [];
    D.people.filter(p => !p.ungrouped).forEach(p => {
      const sum = D.round2(p.months.gmv.reduce((a, b) => a + b, 0));
      const diff = D.round2(sum - p.targets.gmv);
      if (Math.abs(diff) > 0.005) issues.push({ person: p.name, diff });
    });
    return issues;
  }
  function updateValidateStatus() {
    const el = $('#validate-status');
    if (state.gran === 'quarter') {
      const iss = quarterIssues(state.qMetric);
      el.className = 'v-status ' + (iss.length ? 'err' : 'ok');
      el.textContent = iss.length
        ? `✕ ${iss.length} 行季度之和 ≠ 年度：${iss.map(i => `${i.person}（差异 ${i.diff > 0 ? '+' : ''}${fmtVShort(i.k, i.diff)}）`).join('、')}`
        : '✓ 校验通过：全部行 季度之和 = 年度';
    } else if (state.gran === 'month') {
      const iss = monthIssues();
      el.className = 'v-status ' + (iss.length ? 'err' : 'ok');
      el.textContent = iss.length ? `✕ ${iss.length} 行月度之和 ≠ 年度` : '✓ 校验通过：全部行 月度之和 = 年度';
    } else {
      const iss = quarterIssues();
      el.className = 'v-status ' + (iss.length ? 'err' : 'ok');
      el.textContent = iss.length ? `✕ ${iss.length} 个「指标×人」季度之和 ≠ 年度（切换到季度粒度查看）` : '✓ 季度拆分全部校验通过';
    }
  }
  function renderTargetEditor() {
    const notes = {
      year: '年度粒度：每指标一列，可直接编辑；修改后季度拆分需重新「一键拆分」',
      quarter: '季度粒度：当前指标 = ' + mName(state.qMetric) + '（Q1-Q4 可编辑，校验：Q列之和 = 年度）',
      month: '月度粒度：仅展示 GMV（M1-M12 可编辑，校验：月度之和 = 年度）',
    };
    $('#gran-note').textContent = notes[state.gran];
    let html = '';
    if (state.gran === 'year') {
      html = `<table class="tbl"><thead><tr>
        <th>姓名</th><th class="r">GMV 年度（USD）</th><th class="r">新签 年度（个）</th>
        <th class="r">复购客户 年度（个）</th><th class="r">复购金额 年度（USD）</th></tr></thead><tbody>`;
      D.teams.forEach(t => {
        const members = t.members.map(id => D.people.find(p => p.id === id));
        const targeted = members.filter(p => !p.ungrouped);
        const sums = sumOver(targeted, p => p.targets);
        html += `<tr class="group-head"><td>${esc(t.name)}（队长 ${esc(t.captain)}）</td>
          <td class="r">小计 ${D.fmtMoney(sums.gmv)}</td><td class="r">小计 ${D.fmtInt(sums.ns)}</td>
          <td class="r">小计 ${D.fmtInt(sums.rc)}</td><td class="r">小计 ${D.fmtMoney(sums.ra)}</td></tr>`;
        members.forEach(p => {
          if (p.ungrouped) {
            html += `<tr class="row-dim"><td>${esc(p.name)} <span class="tag gray">未设目标</span></td>
              <td class="r">—</td><td class="r">—</td><td class="r">—</td><td class="r">—</td></tr>`;
          } else {
            html += `<tr><td><b>${esc(p.name)}</b>${t.captain === p.name ? ' <span class="tag blue">队长</span>' : ''}</td>
              <td class="r editable"><input class="cell-input" data-edit="target" data-person="${p.id}" data-k="gmv" value="${p.targets.gmv}"></td>
              <td class="r editable"><input class="cell-input" data-edit="target" data-person="${p.id}" data-k="ns" value="${p.targets.ns}"></td>
              <td class="r editable"><input class="cell-input" data-edit="target" data-person="${p.id}" data-k="rc" value="${p.targets.rc}"></td>
              <td class="r editable"><input class="cell-input" data-edit="target" data-person="${p.id}" data-k="ra" value="${p.targets.ra}"></td></tr>`;
          }
        });
      });
      html += '</tbody></table>';
    } else if (state.gran === 'quarter') {
      const k = state.qMetric;
      const issues = quarterIssues(k);
      const issueMap = {};
      issues.forEach(i => { issueMap[i.person] = i.diff; });
      html = `<div class="seg" id="seg-qmetric" style="margin-bottom:12px">
          ${MKEYS.map(mk => `<button data-qm="${mk}" class="${mk === k ? 'active' : ''}">${mName(mk)}</button>`).join('')}
        </div>
        <table class="tbl"><thead><tr><th>姓名</th><th class="r">年度</th>
        <th class="r">Q1</th><th class="r">Q2</th><th class="r">Q3</th><th class="r">Q4</th><th>校验状态</th></tr></thead><tbody>`;
      D.teams.forEach(t => {
        const members = t.members.map(id => D.people.find(p => p.id === id));
        const targeted = members.filter(p => !p.ungrouped);
        const tSum = D.round2(targeted.reduce((a, p) => a + p.targets[k], 0));
        const qSums = [0, 1, 2, 3].map(qi => D.round2(targeted.reduce((a, p) => a + p.quarters[k][qi], 0)));
        html += `<tr class="group-head"><td>${esc(t.name)}（队长 ${esc(t.captain)}）</td><td class="r">小计 ${fmtVShort(k, tSum)}</td>
          ${qSums.map(v => `<td class="r">小计 ${fmtVShort(k, v)}</td>`).join('')}<td></td></tr>`;
        members.forEach(p => {
          if (p.ungrouped) {
            html += `<tr class="row-dim"><td>${esc(p.name)} <span class="tag gray">未设目标</span></td><td class="r">—</td><td class="r">—</td><td class="r">—</td><td class="r">—</td><td class="r">—</td><td>—</td></tr>`;
          } else {
            const bad = issueMap[p.name] != null;
            html += `<tr><td><b>${esc(p.name)}</b></td><td class="r">${fmtVShort(k, p.targets[k])}</td>
              ${[0, 1, 2, 3].map(qi => `<td class="r editable ${bad ? 'cell-err' : ''}"><input class="cell-input" data-edit="quarter" data-person="${p.id}" data-k="${k}" data-q="${qi}" value="${p.quarters[k][qi]}"></td>`).join('')}
              <td>${bad ? `<span class="cell-err-msg">Q列之和 ≠ 年度，差异 ${issueMap[p.name] > 0 ? '+' : ''}${fmtVShort(k, issueMap[p.name])}</span>` : '<span class="tag green">通过</span>'}</td></tr>`;
          }
        });
      });
      html += '</tbody></table>';
    } else {
      const issues = monthIssues();
      const issueMap = {};
      issues.forEach(i => { issueMap[i.person] = i.diff; });
      html = `<table class="tbl"><thead><tr><th>姓名</th><th class="r">GMV 年度</th>
        ${Array.from({ length: 12 }, (_, i) => `<th class="r">${i + 1}月</th>`).join('')}<th>校验状态</th></tr></thead><tbody>`;
      D.teams.forEach(t => {
        const members = t.members.map(id => D.people.find(p => p.id === id));
        html += `<tr class="group-head"><td>${esc(t.name)}（队长 ${esc(t.captain)}）</td><td colspan="14"></td></tr>`;
        members.forEach(p => {
          if (p.ungrouped) {
            html += `<tr class="row-dim"><td>${esc(p.name)} <span class="tag gray">未设目标</span></td><td class="r">—</td>${'<td class="r">—</td>'.repeat(12)}<td>—</td></tr>`;
          } else {
            const bad = issueMap[p.name] != null;
            html += `<tr><td><b>${esc(p.name)}</b></td><td class="r">${D.fmtMoney(p.targets.gmv)}</td>
              ${p.months.gmv.map((v, mi) => `<td class="r editable ${bad ? 'cell-err' : ''}" style="min-width:86px"><input class="cell-input" data-edit="month" data-person="${p.id}" data-m="${mi}" value="${v}"></td>`).join('')}
              <td>${bad ? `<span class="cell-err-msg">月度之和 ≠ 年度，差异 ${issueMap[p.name] > 0 ? '+' : ''}${D.fmtMoney(issueMap[p.name])}</span>` : '<span class="tag green">通过</span>'}</td></tr>`;
          }
        });
      });
      html += '</tbody></table>';
    }
    $('#target-editor').innerHTML = html;
    updateValidateStatus();
  }

  function renderTeamGoalPanel() {
    const rows = D.teams.map(t => {
      const targeted = t.members.map(id => D.people.find(p => p.id === id)).filter(p => !p.ungrouped);
      const memberSum = D.round2(targeted.reduce((a, p) => a + p.targets.gmv, 0));
      const factor = state.teamFactors[t.name] != null ? state.teamFactors[t.name] : 100;
      const goal = D.round2((memberSum * factor) / 100);
      const dirty = state.teamDirty[t.name];
      const trail = state.teamTrails[t.name] || '—';
      return `<tr>
        <td><b>${esc(t.name)}</b> <span style="color:var(--faint);font-size:12px">队长 ${esc(t.captain)}</span></td>
        <td class="c">${t.members.length}（有目标 ${targeted.length}）</td>
        <td class="r">${D.fmtMoney(memberSum)}${dirty ? '<span class="recalc-flag">● 待重算</span>' : ''}</td>
        <td class="c"><input class="cell-input factor-input" data-factor="${esc(t.name)}" value="${factor}"> %</td>
        <td class="r"><b>${D.fmtMoney(goal)}</b></td>
        <td style="color:var(--muted);font-size:12px">${esc(trail)}</td>
        <td><button class="btn small" data-recalc="${esc(t.name)}">重算</button></td>
      </tr>`;
    }).join('');
    $('#team-goal-panel').innerHTML = `<table class="tbl"><thead><tr>
      <th>战队</th><th class="c">成员数</th><th class="r">GMV 成员汇总</th><th class="c">加权系数</th>
      <th class="r">战队目标（自动计算）</th><th>调整留痕</th><th>操作</th></tr></thead><tbody>${rows}</tbody></table>
      <div class="footnote">说明：战队目标基于队内人员目标汇总制定（成员目标之和 × 加权系数）。成员目标变更后显示「待重算」，点击「重算」按最新成员目标刷新；系数微调会保留调整留痕。</div>`;
  }

  function renderAudits() {
    const rows = [
      ['2026-01-05 09:12', 'admin', '2026 年度目标', '发布年度批次 v3（全员四指标目标）', 'v2 → v3（已生效）'],
      ['2026-01-10 14:33', 'admin', '专治不服', '战队加权系数调整', '100% → 105%'],
      ['2026-03-02 10:05', 'admin', '毕晓珍', 'GMV 年度目标调整', '$3,000,000 → $3,100,000'],
      ['2026-07-15 16:40', '毕晓珍（组长）', '代晴玉', '提交新签年度目标建议（待 admin 确认）', '52 → 40（已驳回，维持 52）'],
      ['2026-09-30 18:22', 'admin', '田雯', '新签年度目标调整（Q4 冲刺对齐）', '70 → 74'],
    ];
    $('#audit-table').innerHTML = `<table class="tbl"><thead><tr>
      <th>时间</th><th>操作人</th><th>对象</th><th>变更内容</th><th>旧值 → 新值</th></tr></thead>
      <tbody>${rows.map(r => `<tr>${r.map(c => `<td>${esc(c)}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
  }

  /* ==================== 视图 C · 战报推送 ==================== */
  function renderPushRules() {
    $('#push-countdown').innerHTML = `下次推送：<b>2026-11-01 09:00</b>（距今 9 天） · 触发后 09:05 / 09:15 自动补发失败项 · 时区 Asia/Shanghai`;
    const items = [
      { date: '2026-10-01 09:00', status: 'done', text: '10 月第 1 期 · 全部送达', meta: '业务员 23 + 组长 8 + 管理层 3 · 海报 2 张 · 平均耗时 3.4s' },
      { date: '2026-10-10 09:00', status: 'done', text: '10 月第 2 期 · 全部送达', meta: '业务员 23 + 组长 8 + 管理层 3 · 海报 2 张 · 平均耗时 3.1s' },
      { date: '2026-10-20 09:00', status: 'warn', text: '10 月第 3 期 · 部分降级', meta: '1 人未绑定钉钉ID 降级群@（张心茹） · 1 条失败后 09:15 重试成功' },
      { date: '2026-11-01 09:00', status: 'next', text: '11 月第 1 期 · 待推送', meta: '将按 10 月末快照生成（数据截至 10-31）' },
    ];
    $('#push-timeline').innerHTML = items.map(i => `<div class="tl-item">
      <span class="tl-dot ${i.status === 'warn' ? 'warn' : i.status === 'next' ? 'next' : ''}"></span>
      <div class="tl-body"><b>${i.date}</b>　${i.text}<div class="tl-meta">${i.meta}</div></div>
    </div>`).join('');
  }

  function reportNumbers() {
    const p = D.byName['翟佳盟'];
    const z = {
      gmvR: rateOf(p.total.gmv, p.targets.gmv), nsR: rateOf(p.total.ns, p.targets.ns),
      rcR: rateOf(p.total.rc, p.targets.rc), raR: rateOf(p.total.ra, p.targets.ra),
      nsOver: p.total.ns - p.targets.ns,
      raPerCust: D.round2(p.total.ra / p.total.rc),
      nsPerCust: D.round2((p.total.gmv - p.total.ra) / p.total.ns),
      incNs: p.series.ns.inc[9] || 0, incRc: p.series.rc.inc[9] || 0,
      gap: p.total,
    };
    const team = D.teams.find(t => t.name === '专治不服');
    const tMembers = team.members.map(id => D.people.find(x => x.id === id));
    const tAgg = sumOver(tMembers, x => x.total);
    const tTgt = sumOver(tMembers.filter(x => !x.ungrouped), x => x.targets);
    const tGmvR = rateOf(tAgg.gmv, tTgt.gmv);
    const dqy = D.byName['代晴玉'];
    const main = D.people.filter(x => !x.ungrouped);
    const doneCount = main.filter(x => x.total.gmv >= x.targets.gmv);
    const cAgg = sumOver(main, x => x.total);
    const cTgt = sumOver(main, x => x.targets);
    const teamRates = D.teams.map(t => {
      const ms = t.members.map(id => D.people.find(x => x.id === id));
      return { name: t.name, rate: rateOf(sumOver(ms, x => x.total).gmv, sumOver(ms.filter(x => !x.ungrouped), x => x.targets).gmv) };
    }).sort((a, b) => b.rate - a.rate);
    const proj = D.round2((cAgg.gmv / ELAPSED_DAYS) * 365);
    return {
      z, team, tMembers, tAgg, tTgt, tGmvR, dqy, main, doneCount, cAgg, cTgt, teamRates, proj,
      projRate: rateOf(proj, cTgt.gmv),
      gmvGap: D.round2(cTgt.gmv - cAgg.gmv),
    };
  }

  function renderDdCards() {
    const N = reportNumbers();
    const z = N.z;
    const tp = D.TP_YEAR;
    const pp = r => `<span class="${r >= tp ? 'up' : 'down'}">${D.fmtPp(D.round2(r - tp))}</span>`;
    // —— 业务员版（翟佳盟）——
    const card1 = `<div class="dd-card">
      <div class="dd-head"><span class="dd-robot">🤖</span><div class="dd-app">绩效战报<small>工作通知 · 业务员版</small></div><span class="dd-time">09:00</span></div>
      <div class="dd-body">
        <h3>绩效战报 · 翟佳盟 · 截至10-20</h3>
        <div class="dd-md">
          <table>
            <tr><th>指标</th><th>目标</th><th>完成</th><th>完成率</th><th>与进度差</th></tr>
            <tr><td>GMV</td><td>${D.fmtMoney(730000)}</td><td>${D.fmtMoney(N.z.gap.gmv)}</td><td><b>${z.gmvR.toFixed(1)}%</b></td><td>${pp(z.gmvR)}</td></tr>
            <tr><td>新签客户</td><td>39 个</td><td>${z.gap.ns} 个</td><td><b>${z.nsR.toFixed(1)}%</b></td><td>${pp(z.nsR)}</td></tr>
            <tr><td>复购客户</td><td>23 个</td><td>${z.gap.rc} 个</td><td><b>${z.rcR.toFixed(1)}%</b></td><td>${pp(z.rcR)}</td></tr>
            <tr><td>复购金额</td><td>${D.fmtMoney(306600)}</td><td>${D.fmtMoney(z.gap.ra)}</td><td><b>${z.raR.toFixed(1)}%</b></td><td>${pp(z.raR)}</td></tr>
          </table>
          <p><span class="sec">【亮点】</span>GMV、新签<b>双达标</b>：新签 ${z.gap.ns} 个，<span class="up">超额 ${z.nsOver} 个</span>，为全公司新签王；GMV 完成率 ${z.gmvR.toFixed(1)}%，四指标全部提前撞线。</p>
          <p><span class="sec">【风险】</span>复购金额完成率 ${z.raR.toFixed(1)}% 为四指标中最低；10 月以来新签 +${N.z.incNs} 个、复购客户仅 +${N.z.incRc} 个，<span class="down">新签客户向复购的转化节奏偏慢</span>。</p>
          <p><span class="sec">【建议】</span>Q4 重点挖复购：对已成交 ${z.gap.ns} 个新客户做二次回访，优先推进 10 个高潜客户的返单，把复购客单价从 ${D.fmtMoney(z.raPerCust)} 拉至 $9,000 以上。</p>
        </div>
        <a class="dd-btn" href="javascript:void(0)" data-preview>查看详情 ›</a>
      </div>
      <div class="dd-foot"><span class="ok">✓ 钉钉工作通知 · 已送达 09:00:12</span></div>
    </div>`;
    // —— 组长版（毕晓珍 / 专治不服）——
    const rankRows = N.tMembers.filter(m => !m.ungrouped)
      .map(m => ({ m, g: rateOf(m.total.gmv, m.targets.gmv), n: rateOf(m.total.ns, m.targets.ns) }))
      .sort((a, b) => b.g - a.g)
      .map((r, i) => `<tr><td>${i + 1}</td><td>${r.m.name}</td><td>${r.g.toFixed(1)}%</td><td>${r.n.toFixed(1)}%</td><td>${D.statusOf(r.g, tp).text}</td></tr>`).join('');
    const dqyNsR = rateOf(N.dqy.total.ns, N.dqy.targets.ns);
    const teamGap = D.round2(N.tTgt.gmv - N.tAgg.gmv);
    const card2 = `<div class="dd-card">
      <div class="dd-head" style="background:#7c3aed"><span class="dd-robot">🤖</span><div class="dd-app">绩效战报<small>工作通知 · 组长版</small></div><span class="dd-time">09:00</span></div>
      <div class="dd-body">
        <h3>绩效战报 · 专治不服（队长 毕晓珍）· 截至10-20</h3>
        <div class="dd-md">
          <p><span class="sec">【本人摘要】</span>GMV ${D.fmtMoney(N.tMembers[0].total.gmv)} / ${D.fmtMoney(N.tMembers[0].targets.gmv)}（<b>${rateOf(N.tMembers[0].total.gmv, N.tMembers[0].targets.gmv).toFixed(1)}%</b>，${pp(rateOf(N.tMembers[0].total.gmv, N.tMembers[0].targets.gmv))}）；新签 ${N.tMembers[0].total.ns}/25（${rateOf(N.tMembers[0].total.ns, 25).toFixed(1)}%）。</p>
          <p><span class="sec">【战队概览】</span>GMV 完成率 <b>${N.tGmvR.toFixed(1)}%</b>（${D.fmtMoney(N.tAgg.gmv)} / ${D.fmtMoney(N.tTgt.gmv)}），8 支战队第 ${N.teamRates.findIndex(t => t.name === '专治不服') + 1} 位。</p>
          <table><tr><th>#</th><th>成员</th><th>GMV率</th><th>新签率</th><th>状态</th></tr>${rankRows}</table>
          <p><span class="sec">【掉队预警】</span><span class="down">代晴玉 新签完成率 ${dqyNsR.toFixed(1)}%（${N.dqy.total.ns}/${N.dqy.targets.ns}），严重落后</span>；GMV 完成率 ${rateOf(N.dqy.total.gmv, N.dqy.targets.gmv).toFixed(1)}%，与时间进度差 ${D.fmtPp(D.round2(rateOf(N.dqy.total.gmv, N.dqy.targets.gmv) - tp))}。</p>
          <p><span class="sec">【缺口分解建议】</span>战队 GMV 缺口 ${D.fmtMoney(teamGap)}：建议代晴玉聚焦 2 个在谈大客户（Q4 需日均 $9,600），刘源、张砚斐各承接缺口 25%，队长本人跟进广州展回流客户。</p>
        </div>
        <a class="dd-btn" href="javascript:void(0)" data-preview>查看详情 ›</a>
      </div>
      <div class="dd-foot"><span class="ok">✓ 钉钉工作通知 · 已送达 09:00:15</span> · <span>战报群 @毕晓珍 · 已送达</span></div>
    </div>`;
    // —— 管理层版 ——
    const top = N.teamRates[0], last = N.teamRates[N.teamRates.length - 1];
    const card3 = `<div class="dd-card">
      <div class="dd-head" style="background:#0f766e"><span class="dd-robot">🤖</span><div class="dd-app">绩效战报<small>工作通知 · 管理层版</small></div><span class="dd-time">09:00</span></div>
      <div class="dd-body">
        <h3>绩效战报 · 公司整体 · 截至10-20</h3>
        <div class="dd-md">
          <table>
            <tr><th>指标</th><th>年度目标</th><th>已完成</th><th>完成率</th><th>与进度差</th></tr>
            <tr><td>GMV</td><td>${D.fmtMoney(N.cTgt.gmv)}</td><td>${D.fmtMoney(N.cAgg.gmv)}</td><td><b>${rateOf(N.cAgg.gmv, N.cTgt.gmv).toFixed(1)}%</b></td><td>${pp(rateOf(N.cAgg.gmv, N.cTgt.gmv))}</td></tr>
            <tr><td>新签客户</td><td>${D.fmtInt(N.cTgt.ns)} 个</td><td>${D.fmtInt(N.cAgg.ns)} 个</td><td><b>${rateOf(N.cAgg.ns, N.cTgt.ns).toFixed(1)}%</b></td><td>${pp(rateOf(N.cAgg.ns, N.cTgt.ns))}</td></tr>
            <tr><td>复购客户</td><td>${D.fmtInt(N.cTgt.rc)} 个</td><td>${D.fmtInt(N.cAgg.rc)} 个</td><td><b>${rateOf(N.cAgg.rc, N.cTgt.rc).toFixed(1)}%</b></td><td>${pp(rateOf(N.cAgg.rc, N.cTgt.rc))}</td></tr>
            <tr><td>复购金额</td><td>${D.fmtMoney(N.cTgt.ra)}</td><td>${D.fmtMoney(N.cAgg.ra)}</td><td><b>${rateOf(N.cAgg.ra, N.cTgt.ra).toFixed(1)}%</b></td><td>${pp(rateOf(N.cAgg.ra, N.cTgt.ra))}</td></tr>
          </table>
          <p><span class="sec">【战队对比】</span>TOP：<b>${top.name} ${top.rate.toFixed(1)}%</b>（尹德魁超额带动）；末位：${last.name} ${last.rate.toFixed(1)}%、行则将至 ${N.teamRates[N.teamRates.length - 2].rate.toFixed(1)}%。</p>
          <p><span class="sec">【达标情况】</span>GMV 已达标 <b>${N.doneCount.length}/20</b> 人（${N.doneCount.map(x => x.name).join('、')}）。</p>
          <p><span class="sec">【缺口与预测】</span>GMV 缺口 ${D.fmtMoney(N.gmvGap)}；按当前日均速率外推年末完成 ${D.fmtMoney(N.proj)}（<b>${N.projRate.toFixed(1)}%</b>），Q4 需提速至日均 ${D.fmtMoney(D.round2(N.gmvGap / REMAIN_DAYS))}。</p>
          <p><span class="sec">【需关注名单】</span><span class="down">代晴玉（新签 ${rateOf(N.dqy.total.ns, N.dqy.targets.ns).toFixed(1)}% 严重落后）、田雯（复购金额 ${rateOf(D.byName['田雯'].total.ra, D.byName['田雯'].targets.ra).toFixed(1)}% 落后）、李宝珠（新签 ${rateOf(D.byName['李宝珠'].total.ns, D.byName['李宝珠'].targets.ns).toFixed(1)}% 落后）</span>。</p>
        </div>
        <a class="dd-btn" href="javascript:void(0)" data-preview>查看详情 ›</a>
      </div>
      <div class="dd-foot"><span class="ok">✓ 钉钉工作通知 · 已送达 09:00:18</span> · <span>战报群海报 · 已送达</span></div>
    </div>`;
    $('#dd-cards').innerHTML = card1 + card2 + card3;
  }

  function renderLedger() {
    const rows = [
      ['2026-10-20', '业务员报告', '翟佳盟', '工作通知', '已送达', '3.2s'],
      ['2026-10-20', '业务员报告', '代晴玉', '工作通知', '已送达', '3.5s'],
      ['2026-10-20', '业务员报告', '张心茹', '群@（降级）', '降级群@ · 未绑定钉钉ID', '2.8s'],
      ['2026-10-20', '业务员报告', '刘行行', '工作通知', '失败重试成功（09:15 补发）', '3.9s'],
      ['2026-10-20', '组长报告', '毕晓珍', '工作通知', '已送达', '4.1s'],
      ['2026-10-20', '组长报告', '刘琳琳', '工作通知', '已送达', '3.7s'],
      ['2026-10-20', '管理层报告', '亮哥', '工作通知', '已送达', '4.4s'],
      ['2026-10-20', '整体海报', '战报群', '群机器人', '已送达', '6.2s'],
      ['2026-10-10', '业务员报告', '李宝珠', '工作通知', '已送达', '3.3s'],
      ['2026-10-10', '组长报告', '田雯', '工作通知', '已送达', '3.6s'],
      ['2026-10-10', '管理层报告', '亮哥', '工作通知', '已送达', '4.0s'],
      ['2026-10-01', '业务员报告', '尹德魁', '工作通知', '已送达', '3.1s'],
      ['2026-10-01', '整体海报', '战报群', '群机器人', '已送达', '5.8s'],
      ['2026-10-01', '组长报告', '夏新月', '工作通知', '已送达', '3.4s'],
    ];
    const stTag = s => s.startsWith('已送达') ? 'green' : s.startsWith('降级') ? 'amber' : 'orange';
    $('#ledger-table').innerHTML = `<table class="tbl"><thead><tr>
      <th>期次</th><th>报告类型</th><th>接收人</th><th>通道</th><th>状态</th><th class="r">耗时</th><th>操作</th></tr></thead>
      <tbody>${rows.map(r => `<tr>
        <td>${r[0]} 09:00</td><td>${r[1]}</td><td>${r[2]}</td><td>${r[3]}</td>
        <td><span class="tag ${stTag(r[4])}">${r[4]}</span></td><td class="r">${r[5]}</td>
        <td><button class="btn small" data-preview>预览</button> <button class="btn small" data-resend="${r[2]}">补发</button></td>
      </tr>`).join('')}</tbody></table>
      <div class="footnote">状态机：pending → sending → sent / failed（5/15 分钟重试）→ uncertain；未绑定钉钉ID 的接收人自动降级为战报群 @ 并标记。绑定检查：22/23 已绑定，张心茹 未绑定。</div>`;
  }

  /* ==================== 事件绑定 ==================== */
  function bindEvents() {
    // 主页签
    $('#main-tabs').addEventListener('click', e => {
      const btn = e.target.closest('button[data-view]');
      if (!btn) return;
      state.view = btn.dataset.view;
      $$('#main-tabs button').forEach(b => b.classList.toggle('active', b === btn));
      $$('.view').forEach(v => v.classList.remove('active'));
      $('#view-' + state.view).classList.add('active');
      if (state.view === 'dashboard') renderDashboard();
      if (state.view === 'targets') { renderTargetEditor(); renderTeamGoalPanel(); }
    });
    // 视角
    $('#seg-scope').addEventListener('click', e => {
      const btn = e.target.closest('button[data-scope]');
      if (!btn) return;
      state.scope = btn.dataset.scope;
      $$('#seg-scope button').forEach(b => b.classList.toggle('active', b === btn));
      const showObj = state.scope !== 'company';
      $('#ctl-object').hidden = !showObj;
      $('#ctl-object-label').textContent = state.scope === 'team' ? '选择战队' : '选择业务员';
      const sel = $('#sel-object');
      if (state.scope === 'team') {
        sel.innerHTML = D.teams.map(t => `<option ${t.name === state.objectTeam ? 'selected' : ''}>${t.name}</option>`).join('');
      } else {
        sel.innerHTML = D.people.map(p => `<option value="${p.name}" ${p.name === state.objectPerson ? 'selected' : ''}>${p.name}${p.ungrouped ? '（未设目标）' : ''}</option>`).join('');
      }
      // 明细联动过滤
      state.detail.person = state.scope === 'person' ? state.objectPerson : '';
      state.detail.team = state.scope === 'team' ? state.objectTeam : '';
      state.detail.page = 1;
      renderDashboard();
    });
    $('#sel-object').addEventListener('change', e => {
      if (state.scope === 'team') {
        state.objectTeam = e.target.value;
        state.detail.team = state.objectTeam;
      } else {
        state.objectPerson = e.target.value;
        state.detail.person = state.objectPerson;
      }
      state.detail.page = 1;
      renderDashboard();
    });
    // 周期
    $('#seg-period').addEventListener('click', e => {
      const btn = e.target.closest('button[data-period]');
      if (!btn) return;
      state.period = btn.dataset.period;
      $$('#seg-period button').forEach(b => b.classList.toggle('active', b === btn));
      renderDashboard();
    });
    // 指标切换（事件委托）
    document.addEventListener('click', e => {
      const ms = e.target.closest('.metric-switch button, #seg-qmetric button');
      if (ms) {
        const metric = ms.dataset.metric || ms.dataset.qm;
        const parent = ms.parentElement.id;
        if (parent === 'trend-metric-switch') { state.trendMetric = metric; renderTrend(); }
        else if (parent === 'monthly-metric-switch') { state.monthlyMetric = metric; renderMonthly(); }
        else if (parent === 'team-metric-switch') { state.teamMetric = metric; renderTeamChart(); }
        else if (parent === 'seg-qmetric') { state.qMetric = metric; renderTargetEditor(); }
        return;
      }
      // 明细标签页
      const dt = e.target.closest('#detail-tabs button[data-tab]');
      if (dt) { state.detail.tab = dt.dataset.tab; state.detail.page = 1; renderDetail(); return; }
      // 分页
      const pg = e.target.closest('#detail-pager button[data-page]');
      if (pg && !pg.disabled) { state.detail.page = Number(pg.dataset.page); renderDetail(); return; }
      // 排序
      const th = e.target.closest('th.sortable');
      if (th) {
        const key = th.dataset.sort;
        if (state.sort.key === key) state.sort.dir *= -1;
        else state.sort = { key, dir: -1 };
        renderRanking();
        return;
      }
      // 预览/补发（演示）
      if (e.target.closest('[data-preview]')) { toast('报告预览（演示）：此处打开完整报告弹窗'); return; }
      const rs = e.target.closest('[data-resend]');
      if (rs) { toast(`已向 ${rs.dataset.resend} 重新推送（演示）`); return; }
    });
    // 明细过滤器
    document.addEventListener('change', e => {
      if (e.target.id === 'df-person') { state.detail.person = e.target.value; state.detail.page = 1; renderDetail(); }
      if (e.target.id === 'df-team') { state.detail.team = e.target.value; state.detail.page = 1; renderDetail(); }
      if (e.target.id === 'df-range') { state.detail.range = e.target.value; state.detail.page = 1; renderDetail(); }
    });
    // 目标编辑（input 失焦/回车提交）
    document.addEventListener('change', e => {
      const inp = e.target.closest('input[data-edit]');
      if (inp) {
        const p = D.people.find(x => x.id === inp.dataset.person);
        const v = Number(inp.value);
        if (isNaN(v) || v < 0) { toast('请输入非负数字'); setTimeout(renderTargetEditor, 0); return; }
        if (inp.dataset.edit === 'target') {
          p.targets[inp.dataset.k] = v;
          state.teamDirty[p.team] = true;
          toast(`${p.name} ${mName(inp.dataset.k)}年度目标已更新为 ${fmtVShort(inp.dataset.k, v)}（演示）`);
        } else if (inp.dataset.edit === 'quarter') {
          p.quarters[inp.dataset.k][Number(inp.dataset.q)] = v;
        } else if (inp.dataset.edit === 'month') {
          p.months.gmv[Number(inp.dataset.m)] = v;
        }
        // 延迟重渲染，避免 change/blur 期间替换正被编辑的节点
        setTimeout(() => { renderTargetEditor(); renderTeamGoalPanel(); }, 0);
        return;
      }
      const f = e.target.closest('input[data-factor]');
      if (f) {
        const v = Number(f.value);
        if (isNaN(v) || v <= 0) { toast('系数需为正数'); setTimeout(renderTeamGoalPanel, 0); return; }
        state.teamFactors[f.dataset.factor] = v;
        state.teamTrails[f.dataset.factor] = `2026-10-23 admin 调整系数至 ${v}%（演示）`;
        setTimeout(renderTeamGoalPanel, 0);
        toast(`「${f.dataset.factor}」加权系数已更新，战队目标已重算`);
      }
    });
    // 目标设置工具栏
    $('#seg-granularity').addEventListener('click', e => {
      const btn = e.target.closest('button[data-gran]');
      if (!btn) return;
      state.gran = btn.dataset.gran;
      $$('#seg-granularity button').forEach(b => b.classList.toggle('active', b === btn));
      renderTargetEditor();
    });
    $('#btn-split').addEventListener('click', () => {
      D.people.filter(p => !p.ungrouped).forEach(p => resplitPerson(p));
      renderTargetEditor(); renderTeamGoalPanel();
      toast('已按季节系数 20/25/25/30% 将全员年度目标重新拆分为季度目标');
    });
    $('#btn-season').addEventListener('click', () => {
      if (state.gran === 'quarter') {
        D.people.filter(p => !p.ungrouped).forEach(p => resplitPerson(p, state.qMetric));
        toast(`已按 20/25/25/30% 重新拆分「${mName(state.qMetric)}」季度目标`);
      } else if (state.gran === 'month') {
        D.people.filter(p => !p.ungrouped).forEach(p => rebuildMonths(p));
        toast('已按季度均分重建 GMV 月度拆分');
      } else {
        D.people.filter(p => !p.ungrouped).forEach(p => resplitPerson(p));
        toast('已按季节系数 20/25/25/30% 重新拆分全部指标');
      }
      renderTargetEditor(); renderTeamGoalPanel();
    });
    $('#btn-validate').addEventListener('click', () => {
      renderTargetEditor();
      const iss = state.gran === 'month' ? monthIssues() : quarterIssues(state.gran === 'quarter' ? state.qMetric : null);
      toast(iss.length ? `校验完成：${iss.length} 行未通过（页面已标红）` : '校验完成：全部通过');
    });
    $('#btn-history').addEventListener('click', () => toast('历史版本：v1（2026-01-02 草稿）· v2（2026-01-04）· v3（当前生效）——演示'));
    $('#btn-import').addEventListener('click', () => toast('Excel 导入（演示）：上传模板 → 解析 23 行 → 差异预览 → 生成新版本'));
    // 战队目标重算
    document.addEventListener('click', e => {
      const rc = e.target.closest('[data-recalc]');
      if (rc) {
        delete state.teamDirty[rc.dataset.recalc];
        renderTeamGoalPanel();
        toast(`「${rc.dataset.recalc}」已按最新成员目标重算`);
      }
    });
    // 窗口缩放
    let rsTimer = null;
    window.addEventListener('resize', () => {
      clearTimeout(rsTimer);
      rsTimer = setTimeout(() => Object.values(charts).forEach(c => c && c.resize()), 150);
    });
  }

  /* ==================== 启动 ==================== */
  function init() {
    bindEvents();
    renderDashboard();
    renderTargetEditor();
    renderTeamGoalPanel();
    renderAudits();
    renderPushRules();
    renderDdCards();
    renderLedger();
  }
  init();
})();
