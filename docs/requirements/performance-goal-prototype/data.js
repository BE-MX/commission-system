/**
 * 绩效目标管理原型 · mock 数据层
 * ---------------------------------------------------------------
 * 真实数据（取自《2026年度目标完成情况_截至9月.xlsx》）：
 *   - 20 人主名单的 年度GMV目标 / 截至9月GMV完成 / 年度新签目标 / 截至9月新签完成
 *   - 3 人单列（刘也 / 张心茹 / 凯丽比努尔）只有完成值、无年度目标
 *   - 8 支战队与队长归属
 * mock 数据（确定性伪随机，固定 seed = 20261023，每次打开一致）：
 *   - 复购客户数 / 复购金额 目标与完成（按任务书规则从新签/GMV派生）
 *   - 10 月（截至 10-23）增量
 *   - 1-9 月逐月累积曲线（9 月累计 = 真实值，10 月 = 真实值+增量）
 *   - 明细订单 / 客户行（按人锚定总额，合计与汇总卡严格一致）
 * 本文件同时可被浏览器（window.PerfData）与 node（module.exports）加载，
 * 供 verify-data.js 做数据一致性校验。
 */
(function (global) {
  'use strict';

  /* ---------------- 确定性伪随机 ---------------- */
  function mulberry32(a) {
    return function () {
      a |= 0; a = (a + 0x6D2B79F5) | 0;
      let t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  const rng = mulberry32(20261023);
  function pick(arr) { return arr[Math.floor(rng() * arr.length)]; }

  /* ---------------- 常量 ---------------- */
  const AS_OF = '2026-10-23';
  const TP_YEAR = 80.1;          // 全年工作日时间进度（%）
  const SEASON = [0.20, 0.25, 0.25, 0.30]; // 季度系数 Q1-Q4
  // 全年工作日累积进度（%，mock，10 月锚定 80.1）
  const PACE_CUM = [4.9, 12.6, 21.7, 29.4, 37.6, 45.8, 54.5, 63.6, 71.9, 80.1, 88.9, 100.0];
  // 目标计划线（按季度系数 20/25/25/30 线性内插，%）
  const PLAN_CUM = [6.7, 13.3, 20.0, 28.3, 36.7, 45.0, 53.3, 61.7, 70.0, 80.0, 90.0, 100.0];

  /* ---------------- 真实花名册 ---------------- */
  // gmvT/gmvS: 年度GMV目标 / 截至9月完成；nsT/nsS: 年度新签目标 / 截至9月完成
  const ROSTER = [
    { name: '毕晓珍', gmvT: 3100000, gmvS: 2110225.67, nsT: 25, nsS: 24 },
    { name: '李宝珠', gmvT: 2440000, gmvS: 1707421.89, nsT: 26, nsS: 9 },
    { name: '尹德魁', gmvT: 1170000, gmvS: 1530834.86, nsT: 30, nsS: 34 },
    { name: '夏新月', gmvT: 1100000, gmvS: 832654.75, nsT: 14, nsS: 10 },
    { name: '翟佳盟', gmvT: 730000, gmvS: 769294.07, nsT: 39, nsS: 76 },
    { name: '宋化通', gmvT: 780000, gmvS: 627727.88, nsT: 53, nsS: 43 },
    { name: '刘琳琳', gmvT: 900000, gmvS: 601077.83, nsT: 40, nsS: 35 },
    { name: '田雯', gmvT: 615000, gmvS: 447034.91, nsT: 74, nsS: 25 },
    { name: '宋皓月', gmvT: 750000, gmvS: 446913.83, nsT: 36, nsS: 32 },
    { name: '周露露', gmvT: 500000, gmvS: 341350.04, nsT: 60, nsS: 50 },
    { name: '潘康衡', gmvT: 370000, gmvS: 328976.80, nsT: 70, nsS: 45 },
    { name: '张砚斐', gmvT: 490000, gmvS: 319138.05, nsT: 53, nsS: 53 },
    { name: '代晴玉', gmvT: 900000, gmvS: 305740.26, nsT: 52, nsS: 6 },
    { name: '刘源', gmvT: 490000, gmvS: 253038.82, nsT: 55, nsS: 41 },
    { name: '刘行行', gmvT: 360000, gmvS: 238160.52, nsT: 46, nsS: 16 },
    { name: '张笑', gmvT: 290000, gmvS: 216353.65, nsT: 50, nsS: 25 },
    { name: '高瑞杰', gmvT: 195000, gmvS: 201848.33, nsT: 74, nsS: 49 },
    { name: '曲冉', gmvT: 270000, gmvS: 156535.03, nsT: 52, nsS: 29 },
    { name: '罗馨瑜', gmvT: 166000, gmvS: 141014.30, nsT: 77, nsS: 52 },
    { name: '胡宁宁', gmvT: 81000, gmvS: 46616.59, nsT: 72, nsS: 41 },
  ];
  // 单列（无年度目标，仍归属战队展示完成值）
  const ROSTER_EXTRA = [
    { name: '刘也', gmvS: 44100.82, nsS: 41 },
    { name: '张心茹', gmvS: 22509.11, nsS: 39 },
    { name: '凯丽比努尔', gmvS: 22589.04, nsS: 32 },
  ];
  const TEAMS = [
    { name: '专治不服', captain: '毕晓珍', members: ['毕晓珍', '代晴玉', '刘源', '张砚斐'] },
    { name: '多财多亿', captain: '刘琳琳', members: ['刘琳琳', '翟佳盟', '胡宁宁', '高瑞杰'] },
    { name: '稻乐偲', captain: '夏新月', members: ['夏新月', '宋化通', '潘康衡'] },
    { name: '行则将至', captain: '宋皓月', members: ['宋皓月', '张笑', '罗馨瑜'] },
    { name: '星星之火', captain: '李宝珠', members: ['李宝珠', '刘行行', '刘也'] },
    { name: '乘风', captain: '田雯', members: ['田雯', '曲冉', '凯丽比努尔'] },
    { name: '无名', captain: '尹德魁', members: ['尹德魁', '张心茹'] },
    { name: '嘉树', captain: '周露露', members: ['周露露'] },
  ];

  /* ---------------- 复购指标派生（mock 规则，见任务书） ---------------- */
  // 复购金额完成系数（完成 = GMV完成 × 系数）：翟佳盟/尹德魁 略超额；代晴玉/田雯 落后
  const RA_FACTOR = { '翟佳盟': 0.403, '尹德魁': 0.337, '代晴玉': 0.352, '田雯': 0.362 };

  function round2(x) { return Math.round(x * 100) / 100; }

  /* ---------------- 整数拆分（最大余数法） ---------------- */
  function allocate(total, weights) {
    const wsum = weights.reduce((a, b) => a + b, 0);
    const raw = weights.map(w => (w / wsum) * total);
    const base = raw.map(Math.floor);
    let rem = total - base.reduce((a, b) => a + b, 0);
    const order = raw.map((r, i) => [r - Math.floor(r), i]).sort((a, b) => b[0] - a[0]);
    for (let k = 0; k < rem; k++) base[order[k % order.length][1]]++;
    return base;
  }
  // 金额拆分：n 份、每份 >= minCents、合计精确（单位：分）
  function splitAmount(totalCents, n, minCents) {
    if (n <= 0) return [];
    if (totalCents < minCents * n) {
      const per = Math.floor(totalCents / n);
      const parts = new Array(n).fill(per);
      parts[n - 1] += totalCents - per * n;
      return parts;
    }
    const parts = new Array(n).fill(minCents);
    let rest = totalCents - minCents * n;
    const w = Array.from({ length: n }, () => 0.25 + rng() * 1.75);
    const wsum = w.reduce((a, b) => a + b, 0);
    let used = 0;
    for (let i = 0; i < n - 1; i++) {
      const add = Math.floor((rest * w[i]) / wsum);
      parts[i] += add; used += add;
    }
    parts[n - 1] += rest - used;
    return parts;
  }
  // 金额按权重拆分（浮点，末位调差），用于季度/月度目标拆分
  function splitBySeason(yearVal) {
    const q = SEASON.map(s => round2(yearVal * s));
    q[3] = round2(q[3] + (yearVal - q.reduce((a, b) => a + b, 0)));
    return q;
  }
  function splitCountBySeason(yearVal) { return allocate(yearVal, SEASON); }

  /* ---------------- 人员构建 ---------------- */
  const teamOf = {};
  TEAMS.forEach(t => t.members.forEach(m => { teamOf[m] = t.name; }));

  const people = [];
  function buildPerson(rec, ungrouped) {
    const name = rec.name;
    const p = {
      id: 'p' + String(people.length + 1).padStart(2, '0'),
      name,
      team: teamOf[name] || '未编组',
      ungrouped: !!ungrouped,
    };
    // --- 年度目标 ---
    const gmvT = ungrouped ? null : rec.gmvT;
    const nsT = ungrouped ? null : rec.nsT;
    const rcT = ungrouped ? null : Math.round(rec.nsT * 0.6);
    const raT = ungrouped ? null : Math.round((rec.gmvT * 0.42) / 100) * 100;
    // --- 截至9月完成 ---
    const gmvS = rec.gmvS;
    const nsS = rec.nsS;
    const rcS = Math.max(1, Math.round(nsS * (0.50 + rng() * 0.10)));
    const raF = RA_FACTOR[name] != null ? RA_FACTOR[name] : 0.37 + rng() * 0.06;
    const raS = round2(gmvS * raF);
    // --- 10月（截至10-23）增量：约月均值 50%-70% ---
    const gmvO = round2((gmvS / 9) * (0.50 + rng() * 0.20));
    const nsO = Math.round((nsS / 9) * (0.50 + rng() * 0.20));
    const rcO = Math.round((rcS / 9) * (0.50 + rng() * 0.20));
    const raO = round2((raS / 9) * (0.50 + rng() * 0.20));
    // --- 合计（截至10-23）---
    p.targets = { gmv: gmvT, ns: nsT, rc: rcT, ra: raT };
    p.sep = { gmv: gmvS, ns: nsS, rc: rcS, ra: raS };
    p.oct = { gmv: gmvO, ns: nsO, rc: rcO, ra: raO };
    p.total = {
      gmv: round2(gmvS + gmvO), ns: nsS + nsO,
      rc: rcS + rcO, ra: round2(raS + raO),
    };
    // --- 季度拆分（年度目标 → Q1-Q4，目标设置页数据源）---
    p.quarters = ungrouped ? null : {
      gmv: splitBySeason(gmvT), ns: splitCountBySeason(nsT),
      rc: splitCountBySeason(rcT), ra: splitBySeason(raT),
    };
    // --- 月度拆分（季度 → 3 个月均摊，末月调差）---
    if (!ungrouped) {
      p.months = { gmv: [], ns: [], rc: [], ra: [] };
      ['gmv', 'ra'].forEach(k => {
        p.quarters[k].forEach(qv => {
          const m = [round2(qv / 3), round2(qv / 3), 0];
          m[2] = round2(qv - m[0] - m[1]);
          p.months[k].push(...m);
        });
      });
      ['ns', 'rc'].forEach(k => {
        p.quarters[k].forEach(qv => { p.months[k].push(...allocate(qv, [1, 1, 1])); });
      });
    } else {
      p.months = null;
    }
    // --- 1-9 月逐月累积曲线（9月=真实值）+ 10月点（含增量）---
    const w = Array.from({ length: 9 }, (_, i) => (0.8 + (0.45 * (i + 1)) / 9) * (0.85 + rng() * 0.3));
    const wsum = w.reduce((a, b) => a + b, 0);
    function curve(total9, octVal, isInt) {
      const cum = [];
      let acc = 0;
      for (let i = 0; i < 8; i++) {
        acc += (total9 * w[i]) / wsum;
        cum.push(isInt ? Math.round(acc) : round2(acc));
      }
      cum.push(total9); // 9 月锚定真实值
      if (isInt) { // 整数曲线：用增量法保证单调且末值精确
        const inc = cum.map((v, i) => v - (i ? cum[i - 1] : 0));
        const alloc = allocate(total9, w);
        let run = 0;
        const cum2 = alloc.map(v => (run += v));
        return { cum: [...cum2, total9 + octVal, null, null], inc: [...alloc, octVal, null, null] };
      }
      const inc = cum.map((v, i) => round2(v - (i ? cum[i - 1] : 0)));
      return { cum: [...cum, round2(total9 + octVal), null, null], inc: [...inc, octVal, null, null] };
    }
    p.series = {
      gmv: curve(gmvS, gmvO, false),
      ns: curve(nsS, nsO, true),
      rc: curve(rcS, rcO, true),
      ra: curve(raS, raO, false),
    };
    people.push(p);
    return p;
  }
  ROSTER.forEach(r => buildPerson(r, false));
  ROSTER_EXTRA.forEach(r => buildPerson(r, true));

  /* ---------------- 目标设置页：故意制造 3 行季度之和不等于年度（校验演示） ---------------- */
  const byName = {};
  people.forEach(p => { byName[p.name] = p; });
  byName['毕晓珍'].quarters.gmv[3] += 5000;   // GMV Q4 多 5,000
  byName['代晴玉'].quarters.ns[2] += 2;       // 新签 Q3 多 2
  byName['刘源'].quarters.ra[1] -= 8000;      // 复购金额 Q2 少 8,000

  /* ---------------- 战队 / 公司汇总 ---------------- */
  function sumMetric(list, getter) {
    return list.reduce((acc, p) => {
      const v = getter(p);
      acc.gmv = round2(acc.gmv + (v.gmv || 0));
      acc.ns += v.ns || 0;
      acc.rc += v.rc || 0;
      acc.ra = round2(acc.ra + (v.ra || 0));
      return acc;
    }, { gmv: 0, ns: 0, rc: 0, ra: 0 });
  }
  const teams = TEAMS.map(t => {
    const members = t.members.map(n => byName[n]);
    const withTarget = members.filter(p => !p.ungrouped);
    return {
      name: t.name, captain: t.captain, members: members.map(p => p.id),
      targets: sumMetric(withTarget, p => p.targets),   // 目标 = 有目标成员之和
      sep: sumMetric(members, p => p.sep),              // 完成含单列成员完成值
      oct: sumMetric(members, p => p.oct),
      total: sumMetric(members, p => p.total),
    };
  });
  const mainList = people.filter(p => !p.ungrouped);
  const company = {
    targets: sumMetric(mainList, p => p.targets),
    sep: sumMetric(mainList, p => p.sep),
    oct: sumMetric(mainList, p => p.oct),
    total: sumMetric(mainList, p => p.total),
  };

  /* ---------------- 明细订单生成（按人锚定总额） ---------------- */
  const NAME_A = ['Sunshine', 'Golden', 'Everbright', 'Royal', 'Pacific', 'Starlight', 'Unity', 'Grand', 'New Era', 'Blue Sky', 'Harvest', 'Pioneer', 'Crown', 'Diamond', 'Pearl', 'Phoenix', 'Horizon', 'Summit', 'Victory', 'Elegant', 'Aurora', 'Crystal', 'Maple', 'Willow', 'Falcon', 'Lotus', 'Orchid', 'Savanna', 'Metro', 'Alpha', 'Bright', 'Cosmo', 'Delta', 'Elite', 'Flora', 'Gloria', 'Henna', 'Ivory', 'Jasmine', 'Karma'];
  const NAME_B = ['Trading Co., Ltd.', 'Hair Products Co., Ltd.', 'International Trade Co., Ltd.', 'Beauty Supply Inc.', 'Trading LLC', 'Import & Export Co., Ltd.', 'Commercial Brokers LLC', 'General Trading LLC', 'Distribution SARL', 'Trading GmbH', 'Pty Ltd', 'S.A. de C.V.', 'Hair & Beauty Ltd.', 'Wholesale BV', 'Merchant Corp.', 'Trading FZE'];
  const COUNTRIES = ['美国', '英国', '德国', '法国', '意大利', '西班牙', '荷兰', '澳大利亚', '加拿大', '巴西', '墨西哥', '南非', '阿联酋', '沙特阿拉伯', '尼日利亚', '肯尼亚', '加纳', '波兰', '俄罗斯', '日本', '韩国', '新加坡', '马来西亚', '泰国', '越南', '印度尼西亚', '印度', '土耳其', '埃及', '阿根廷', '智利', '哥伦比亚', '秘鲁', '以色列', '葡萄牙', '希腊'];
  function companyName() { return pick(NAME_A) + ' ' + pick(NAME_B); }

  const orders = [];       // GMV 订单（新签首单 + 复购订单）
  const nsCustomers = [];  // 新签客户（一人一行）
  const rcCustomers = [];  // 复购客户（一人一行）
  let orderSeq = 1;

  people.forEach(p => {
    const s = p.series;
    // --- 新签客户：按月度整数曲线落在各月 ---
    const nsCount = p.total.ns;
    const nsPoolCents = Math.round((p.total.gmv - p.total.ra) * 100); // 新签首单金额池
    const nsAmounts = splitAmount(nsPoolCents, nsCount, 30000);       // 每单 >= $300
    let nsIdx = 0;
    for (let m = 0; m < 10; m++) {
      const cnt = s.ns.inc[m] || 0;
      for (let k = 0; k < cnt; k++) {
        const day = m === 9 ? 1 + Math.floor(rng() * 23) : 1 + Math.floor(rng() * 28);
        const date = `2026-${String(m + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
        const cust = {
          id: 'C' + String(nsCustomers.length + 1).padStart(4, '0'),
          company: companyName(), country: pick(COUNTRIES),
          personId: p.id, person: p.name, team: p.team,
          firstDate: date, month: m + 1,
          amount: nsAmounts[nsIdx] / 100,
        };
        nsCustomers.push(cust);
        orders.push({
          no: 'LS2026' + String(orderSeq++).padStart(5, '0'),
          customerId: cust.id, company: cust.company, country: cust.country,
          amount: cust.amount, date, month: m + 1,
          personId: p.id, person: p.name, team: p.team, tag: '新签',
        });
        nsIdx++;
      }
    }
    // --- 复购客户：按月度整数曲线落在各月（首复购月），20% 客户有二单 ---
    const rcCount = p.total.rc;
    const raCents = Math.round(p.total.ra * 100);
    // 先确定每个客户的月份
    const custMonths = [];
    for (let m = 0; m < 10; m++) {
      const cnt = s.rc.inc[m] || 0;
      for (let k = 0; k < cnt; k++) custMonths.push(m);
    }
    // 订单数：每客户 1 单，约 20% 加 1 单（顺延 1-2 月，不超 10 月）
    const orderMonths = [];
    const custOrders = custMonths.map((m, i) => {
      const n = { custIdx: i, months: [m] };
      if (rng() < 0.20) n.months.push(Math.min(9, m + 1 + Math.floor(rng() * 2)));
      n.months.forEach(mm => orderMonths.push(mm));
      return n;
    });
    const raAmounts = splitAmount(raCents, orderMonths.length, 20000); // 每单 >= $200
    let raIdx = 0;
    custOrders.forEach((co, i) => {
      const cust = {
        id: 'R' + String(rcCustomers.length + 1).padStart(4, '0'),
        company: companyName(), country: pick(COUNTRIES),
        personId: p.id, person: p.name, team: p.team,
        orderCount: co.months.length, amount: 0, lastDate: '', month: 0,
      };
      co.months.forEach(mm => {
        const amt = raAmounts[raIdx++] / 100;
        const day = mm === 9 ? 1 + Math.floor(rng() * 23) : 1 + Math.floor(rng() * 28);
        const date = `2026-${String(mm + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
        cust.amount = round2(cust.amount + amt);
        if (date > cust.lastDate) { cust.lastDate = date; cust.month = mm + 1; }
        orders.push({
          no: 'LS2026' + String(orderSeq++).padStart(5, '0'),
          customerId: cust.id, company: cust.company, country: cust.country,
          amount: amt, date, month: mm + 1,
          personId: p.id, person: p.name, team: p.team, tag: '复购',
        });
      });
      rcCustomers.push(cust);
    });
  });
  orders.sort((a, b) => (a.date < b.date ? 1 : a.date > b.date ? -1 : 0));
  // 复购金额标签页 = 复购订单（orders 中 tag=复购 的子集）

  /* ---------------- 格式化工具 ---------------- */
  function fmtMoney(v, cents) {
    if (v == null) return '—';
    const opt = cents
      ? { minimumFractionDigits: 2, maximumFractionDigits: 2 }
      : { maximumFractionDigits: 0 };
    return '$' + Number(v).toLocaleString('en-US', opt);
  }
  function fmtInt(v) { return v == null ? '—' : Number(v).toLocaleString('en-US'); }
  function fmtRate(done, target) {
    if (target == null || target === 0) return null;
    return Math.round((done / target) * 1000) / 10;
  }
  function fmtRateText(rate) { return rate == null ? '—' : rate.toFixed(1) + '%'; }
  function fmtPp(v) { return (v >= 0 ? '+' : '') + v.toFixed(1) + 'pp'; }

  const api = {
    AS_OF, TP_YEAR, SEASON, PACE_CUM, PLAN_CUM,
    people, byName, teams, company, orders, nsCustomers, rcCustomers,
    fmtMoney, fmtInt, fmtRate, fmtRateText, fmtPp, round2,
    // 状态徽章：rate vs 时间进度
    statusOf(rate, tp) {
      if (rate == null) return { key: 'none', text: '未设目标' };
      if (rate >= 100) return { key: 'done', text: '已完成' };
      if (rate >= tp - 0.05) return { key: 'run', text: '进行中' };
      if (rate >= tp - 30) return { key: 'lag', text: '落后' };
      return { key: 'bad', text: '严重落后' };
    },
  };
  global.PerfData = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
