/** 数据一致性校验：node verify-data.js（加载 data.js 核对关键合计） */
const D = require('./data.js');
const r2 = D.round2;
let fail = 0;
function check(label, actual, expected, tol = 0.005) {
  const ok = typeof expected === 'number'
    ? Math.abs(actual - expected) <= tol
    : actual === expected;
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${label}: actual=${actual} expected=${expected}`);
  if (!ok) fail++;
}

/* 1. 主名单 9 月底真实值（与 Excel 验收口径一致） */
check('主名单 GMV完成(9月底)', r2(D.company.sep.gmv), 11621958.08);
check('主名单 GMV目标合计', D.company.targets.gmv, 15697000);
check('主名单 新签完成(9月底)', D.company.sep.ns, 695);
check('主名单 新签目标合计', D.company.targets.ns, 998);

/* 2. 10 月增量与合计 */
console.log(`INFO  10月增量: GMV=${r2(D.company.oct.gmv)} 新签=${D.company.oct.ns} 复购客户=${D.company.oct.rc} 复购金额=${r2(D.company.oct.ra)}`);
console.log(`INFO  截至10-23合计: GMV=${r2(D.company.total.gmv)} 新签=${D.company.total.ns} 复购客户=${D.company.total.rc} 复购金额=${r2(D.company.total.ra)}`);
check('合计 = 9月底 + 10月增量 (GMV)', r2(D.company.sep.gmv + D.company.oct.gmv), r2(D.company.total.gmv));
check('合计 = 9月底 + 10月增量 (新签)', D.company.sep.ns + D.company.oct.ns, D.company.total.ns);

/* 3. 明细订单合计 = 汇总卡（主名单） */
const mainIds = new Set(D.people.filter(p => !p.ungrouped).map(p => p.id));
const gmvOrders = D.orders.filter(o => mainIds.has(o.personId));
check('GMV订单合计 = 汇总卡GMV', r2(gmvOrders.reduce((a, o) => a + o.amount, 0)), r2(D.company.total.gmv));
const nsMain = D.nsCustomers.filter(c => mainIds.has(c.personId));
check('新签客户行数 = 汇总卡新签数', nsMain.length, D.company.total.ns);
const rcMain = D.rcCustomers.filter(c => mainIds.has(c.personId));
check('复购客户行数 = 汇总卡复购客户数', rcMain.length, D.company.total.rc);
const raOrders = D.orders.filter(o => o.tag === '复购' && mainIds.has(o.personId));
check('复购金额订单合计 = 汇总卡复购金额', r2(raOrders.reduce((a, o) => a + o.amount, 0)), r2(D.company.total.ra));

/* 4. 每人核对：订单/客户行 与 个人合计 */
let personBad = 0;
D.people.forEach(p => {
  const gmv = r2(D.orders.filter(o => o.personId === p.id).reduce((a, o) => a + o.amount, 0));
  const ns = D.nsCustomers.filter(c => c.personId === p.id).length;
  const rc = D.rcCustomers.filter(c => c.personId === p.id).length;
  const ra = r2(D.orders.filter(o => o.personId === p.id && o.tag === '复购').reduce((a, o) => a + o.amount, 0));
  if (Math.abs(gmv - p.total.gmv) > 0.005 || ns !== p.total.ns || rc !== p.total.rc || Math.abs(ra - p.total.ra) > 0.005) {
    personBad++;
    console.log(`FAIL  个人合计不一致: ${p.name} gmv=${gmv}/${p.total.gmv} ns=${ns}/${p.total.ns} rc=${rc}/${p.total.rc} ra=${ra}/${p.total.ra}`);
  }
});
check('个人合计全部一致(23人)', personBad, 0);

/* 5. 战队 = 成员之和；公司(主名单) = 有目标成员之和 */
D.teams.forEach(t => {
  const ms = t.members.map(id => D.people.find(p => p.id === id));
  const gmv = r2(ms.reduce((a, p) => a + p.total.gmv, 0));
  if (Math.abs(gmv - t.total.gmv) > 0.005) { fail++; console.log(`FAIL  战队合计: ${t.name}`); }
});
const teamGmvAll = r2(D.teams.reduce((a, t) => a + t.total.gmv, 0));
const extraGmv = r2(D.people.filter(p => p.ungrouped).reduce((a, p) => a + p.total.gmv, 0));
check('8战队合计 = 公司主名单 + 单列完成值', teamGmvAll, r2(D.company.total.gmv + extraGmv));

/* 6. 月度曲线锚定：9月累计=真实值，10月=合计 */
let curveBad = 0;
D.people.forEach(p => {
  ['gmv', 'ns', 'rc', 'ra'].forEach(k => {
    if (Math.abs(p.series[k].cum[8] - p.sep[k]) > 0.005) curveBad++;
    if (Math.abs(p.series[k].cum[9] - p.total[k]) > 0.005) curveBad++;
    if (k === 'ns' || k === 'rc') {
      const incSum = p.series[k].inc.slice(0, 10).reduce((a, b) => a + b, 0);
      if (incSum !== p.total[k]) curveBad++;
    }
  });
});
check('月度曲线锚定全部通过', curveBad, 0);

/* 7. 新签月度曲线 = 明细订单月度分布（整数口径应精确） */
let nsMonthBad = 0;
D.people.forEach(p => {
  for (let m = 1; m <= 10; m++) {
    const cnt = D.nsCustomers.filter(c => c.personId === p.id && c.month === m).length;
    if (cnt !== p.series.ns.inc[m - 1]) nsMonthBad++;
  }
});
check('新签月度分布=订单分布', nsMonthBad, 0);

/* 8. 季度拆分校验（目标设置页）：除故意制造的 3 行外，季度之和=年度 */
let qBad = 0, qKnown = 0;
D.people.filter(p => !p.ungrouped).forEach(p => {
  ['gmv', 'ns', 'rc', 'ra'].forEach(k => {
    const sum = r2(p.quarters[k].reduce((a, b) => a + b, 0));
    if (Math.abs(sum - p.targets[k]) > 0.005) {
      qBad++;
      console.log(`INFO  季度拆分不一致(预期内3处): ${p.name} ${k} Q和=${sum} 年度=${p.targets[k]} 差异=${r2(sum - p.targets[k])}`);
    }
  });
});
check('季度拆分不一致行数(故意保留)', qBad, 3);

/* 9. 关键速率/态势抽查 */
const rate = (d, t) => Math.round((d / t) * 1000) / 10;
console.log(`INFO  公司GMV完成率=${rate(D.company.total.gmv, D.company.targets.gmv)}% 新签=${rate(D.company.total.ns, D.company.targets.ns)}% 复购客户=${rate(D.company.total.rc, D.company.targets.rc)}% 复购金额=${rate(D.company.total.ra, D.company.targets.ra)}%`);
['尹德魁', '翟佳盟', '高瑞杰'].forEach(n => {
  const p = D.byName[n];
  if (p.total.gmv < p.targets.gmv) { fail++; console.log(`FAIL  ${n} GMV应已完成`); }
});
console.log(`INFO  复购金额率: 翟佳盟=${rate(D.byName['翟佳盟'].total.ra, D.byName['翟佳盟'].targets.ra)}% 尹德魁=${rate(D.byName['尹德魁'].total.ra, D.byName['尹德魁'].targets.ra)}% 代晴玉=${rate(D.byName['代晴玉'].total.ra, D.byName['代晴玉'].targets.ra)}% 田雯=${rate(D.byName['田雯'].total.ra, D.byName['田雯'].targets.ra)}%`);
const teamRates = D.teams.map(t => `${t.name}=${rate(t.total.gmv, t.targets.gmv)}%`).join(' ');
console.log(`INFO  战队GMV完成率: ${teamRates}`);
console.log(fail === 0 ? '\nALL CHECKS PASSED' : `\n${fail} CHECK(S) FAILED`);
process.exit(fail === 0 ? 0 : 1);
