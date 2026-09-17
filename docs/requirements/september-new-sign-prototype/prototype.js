'use strict';
// Prototype fixtures only. No API, credentials, storage writes, or production integration.
const groups = [
  {name: '乘风', target: 21, logo: 'chengfeng'},
  {name: '行则将至', target: 15, logo: 'xingzejiangzhi'},
  {name: '星星之火', target: 11, logo: 'xingxingzhihuo'},
  {name: '无名', target: 10, logo: 'wuming'},
  {name: '稻乐偲', target: 14, logo: 'daolesi'},
  {name: '专治不服', target: 15, logo: 'zhuanzhibufu'},
  {name: '多财多亿', target: 22, logo: 'duocaiduoyi'},
  {name: '嘉树', target: 5, solo: true, logo: 'jiashu'},
];
const fixtures = {
  progress: [17, 18, 8, 7, 10, 12, 16, 6],
  none: [16, 13, 8, 7, 10, 12, 16, 6],
  all: [23, 18, 12, 11, 16, 17, 24, 7],
  tie: [17, 18, 8, 7, 10, 18, 16, 6],
  amount: [17, 18, 8, 7, 10, 18, 16, 6],
  empty: [0, 0, 0, 0, 0, 0, 0, 0],
  stale: [17, 18, 8, 7, 10, 12, 16, 6],
};
const $ = (id) => document.getElementById(id);
const percent = (done, target) => (done / target * 100).toFixed(1);
function render(scenario) {
  const rows = groups.map((group, index) => ({...group, done: fixtures[scenario][index], amount: scenario === 'amount' && index === 5 ? 21000 : 18000}));
  const candidates = rows.filter(row => !row.solo && row.done >= row.target);
  candidates.sort((a, b) => b.done * a.target - a.done * b.target || b.amount - a.amount);
  const first = candidates[0];
  const winners = first ? candidates.filter(row => row.done * first.target === first.done * row.target && row.amount === first.amount) : [];
  const done = rows.reduce((sum, row) => sum + row.done, 0);
  const target = rows.reduce((sum, row) => sum + row.target, 0);
  $('total-done').textContent = done;
  $('total-rate').innerHTML = `${percent(done, target)}<span>%</span>`;
  $('remaining-label').textContent = done > target ? '已超总目标' : done === target ? '总目标已达成' : '距总目标';
  $('total-remaining').innerHTML = `${Math.abs(target - done)}<span> 个</span>`;
  $('qualified').innerHTML = `${rows.filter(row => row.done >= row.target).length}<span> / 8</span>`;
  $('department-bar').firstElementChild.style.transform = `scaleX(${Math.min(done / target, 1)})`;
  $('department-bar').setAttribute('aria-valuenow', Math.min(Number(percent(done, target)), 100));
  $('department-bar').setAttribute('aria-valuetext', `实际完成率 ${percent(done, target)}%`);
  $('department-caption').textContent = done >= target ? '共同目标已达成，每一步都在创造新纪录。' : done === 0 ? '目标已就位，期待9月的第一位新客户。' : '每一个新客户，都是团队向前的一步。';
  const champion = document.querySelector('.champion');
  champion.classList.toggle('is-empty', !first);
  champion.classList.toggle('is-tie', winners.length > 1);
  $('champion-label').textContent = winners.length > 1 ? '当前并列第一团队' : '当前第一团队';
  $('champion-name').textContent = first ? winners.map(row => row.name).join(' · ') : '席位待产生';
  $('champion-detail').innerHTML = first ? `<strong>${percent(first.done, first.target)}%</strong><span>${winners.length > 1 ? '同完成率 · 同新签金额' : `${first.done} / ${first.target} 个 · ${first.done > first.target ? `已超额 ${first.done - first.target} 个` : '目标已达成'}`}</span>` : '<span>期待首个达标团队</span>';
  $('champion-foot').textContent = !first ? '至少2人且完成率≥100%，才参与第一名评选' : scenario === 'amount' ? '完成率相同，按新签金额决胜' : winners.length > 1 ? '同率同额，依规则并列展示' : '达标团队中，目标完成率领先';
  $('teams').innerHTML = rows.map(row => {
    const winner = winners.includes(row);
    const achieved = row.done >= row.target;
    const caption = achieved ? (row.done === row.target ? '目标已达成' : `已超额 ${row.done - row.target} 个`) : `还差 ${row.target - row.done} 个`;
    return `<article class="team glass ${winner ? 'is-first' : ''} ${achieved ? 'is-achieved' : ''}" aria-label="${row.name}，完成${row.done}个，目标${row.target}个，完成率${percent(row.done, row.target)}%">
      <div class="team-heading"><img class="team-logo" alt="" src="../../../frontend/public/festival/assets/team-logos/${row.logo}.png"><h3>${row.name}${row.solo ? ' <small>单人</small>' : ''}</h3><span class="status ${winner ? 'winner' : achieved ? 'achieved' : ''}">${winner ? (winners.length > 1 ? '并列第一' : '当前第一') : achieved ? '● 已达标' : '冲刺中'}</span></div>
      <div class="team-stats"><span class="team-count">${row.done}<small>/ ${row.target} 个</small></span><span class="team-rate">${percent(row.done, row.target)}<small>%</small></span></div>
      <div class="bar" role="progressbar" aria-label="${row.name}完成率" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${Math.min(Number(percent(row.done, row.target)), 100)}" aria-valuetext="实际完成率${percent(row.done, row.target)}%"><i style="transform:scaleX(${Math.min(row.done / row.target, 1)})"></i></div>
      <div class="team-caption"><span>${row.solo ? '计入总目标 · 不参与第一评选' : `9月目标 ${row.target} 个`}</span><b>${caption}</b></div>
    </article>`;
  }).join('');
  $('sync').classList.toggle('stale', scenario === 'stale');
  $('sync').textContent = scenario === 'stale' ? '● 更新中断 · 保留 09.17 10:20 数据（演示）' : '● 演示数据 · 截至 09.17 10:30';
}
function fit() {
  const viewport = $('viewport');
  const scale = Math.min(viewport.clientWidth / 1920, viewport.clientHeight / 1080);
  $('stage').style.transform = `translate(-50%, -50%) scale(${scale})`;
}
function immersive(enabled) {
  document.body.classList.toggle('immersive', enabled);
  $('exit-display').hidden = !enabled;
  fit();
}
$('scenario').addEventListener('change', event => render(event.target.value));
$('rules-open').addEventListener('click', () => $('rules-dialog').showModal());
$('display-toggle').addEventListener('click', () => immersive(true));
$('exit-display').addEventListener('click', () => immersive(false));
document.addEventListener('keydown', event => { if (event.key === 'Escape' && !$('rules-dialog').open) immersive(false); });
window.addEventListener('resize', fit);
const query = new URLSearchParams(location.search);
const initial = Object.hasOwn(fixtures, query.get('scenario')) ? query.get('scenario') : 'progress';
$('scenario').value = initial;
render(initial);
immersive(query.get('display') === '1');
