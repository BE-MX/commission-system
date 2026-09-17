import '../../styles/tokens.css'
import './september-screen.css'
import { currentBeijingDate, formatBeijingShortDateTime } from '../../utils/datetime.js'
import { validPayload, snapshotIsStale, screenUrl } from './september-screen-state.js'

const $ = id => document.getElementById(id)
const qs = new URLSearchParams(location.search)
const logos = {
  '乘风': 'chengfeng', '行则将至': 'xingzejiangzhi', '星星之火': 'xingxingzhihuo',
  '无名': 'wuming', '稻乐偲': 'daolesi', '专治不服': 'zhuanzhibufu', '多财多亿': 'duocaiduoyi', '嘉树': 'jiashu',
}
const escape = value => String(value).replace(/[&<>"']/g, char => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
}[char]))
let snapshot = null
let failure = ''
let request = null
let disposed = false

function fit() {
  const scale = Math.min(window.innerWidth / 1920, window.innerHeight / 1080)
  $('stage').style.transform = `translate(-50%, -50%) scale(${scale})`
}

function render(data) {
  const { total, groups, champion, data_quality: quality } = data
  const clean = quality.ok
  $('total-done').textContent = total.done ?? '—'
  $('total-rate').innerHTML = `${total.rate?.toFixed(1) ?? '—'}<span>%</span>`
  $('remaining-label').textContent = total.excess > 0 ? '已超总目标' : total.done === total.target ? '总目标已达成' : '距总目标'
  $('total-remaining').innerHTML = `${clean ? total.excess || total.remaining : '—'}<span> 个</span>`
  $('qualified').innerHTML = `${total.achieved_groups ?? '—'}<span> / ${groups.length}</span>`
  const progress = $('department-bar')
  progress.firstElementChild.style.transform = `scaleX(${clean ? Math.min(total.done / total.target, 1) : 0})`
  if (clean) progress.setAttribute('aria-valuenow', Math.min(total.rate, 100))
  else progress.removeAttribute('aria-valuenow')
  progress.setAttribute('aria-valuetext', clean ? `实际完成率 ${total.rate.toFixed(1)}%` : '数据待核对')
  $('department-caption').textContent = !clean ? '数据待核对，完整总进度暂不可用。'
    : total.done >= total.target ? '共同目标已达成，每一步都在创造新纪录。'
      : total.done === 0 ? '目标已就位，期待9月的第一位新客户。' : '每一个新客户，都是团队向前的一步。'

  const first = groups.find(group => group.first)
  const panel = document.querySelector('.champion')
  panel.classList.toggle('is-empty', !first)
  panel.classList.toggle('is-tie', champion.names.length > 1)
  panel.classList.toggle('is-many', champion.names.length > 2)
  const prefix = data.phase === 'finalized' ? '9月' : '当前'
  $('champion-label').textContent = `${prefix}${champion.tied ? '并列' : ''}第一团队${data.phase === 'pending_review' ? ' · 待复核' : ''}`
  if (first) $('champion-name').innerHTML = champion.names.map(name => `<span class="winner-name">${escape(name)}</span>`).join(' · ')
  else $('champion-name').textContent = clean ? '席位待产生' : '数据待核对'
  $('champion-detail').innerHTML = first
    ? `<strong>${first.rate.toFixed(1)}%</strong><span>${champion.tied ? '同完成率 · 同新签金额' : `${first.done} / ${first.target} 个 · ${first.excess ? `已超额 ${first.excess} 个` : '目标已达成'}`}</span>`
    : `<span>${clean ? '期待首个达标团队' : '第一团队评选已暂停'}</span>`
  $('champion-foot').textContent = !clean ? '请核对参赛名册和客户归属后重新获取'
    : !first ? '至少2人且完成率≥100%，才参与第一名评选'
      : champion.tied ? '同率同额，依规则并列展示'
        : champion.by_revenue ? '完成率相同，按新签金额决胜' : '达标团队中，目标完成率领先'
  $('teams').innerHTML = groups.map(group => {
    const name = escape(group.name)
    const caption = group.achieved ? (group.excess ? `已超额 ${group.excess} 个` : '目标已达成') : `还差 ${group.remaining} 个`
    const logo = logos[group.name]
    const status = group.first ? (champion.tied ? '并列第一' : '当前第一') : group.achieved ? '● 已达标' : '冲刺中'
    return `<article class="team glass ${group.first ? 'is-first' : ''} ${group.achieved ? 'is-achieved' : ''}" aria-label="${name}，完成${group.done}个，目标${group.target}个，完成率${group.rate.toFixed(1)}%">
      <div class="team-heading"><img class="team-logo" alt="" src="/festival/assets/team-logos/${logo}.png"><h3>${name}${group.solo ? ' <small>单人</small>' : ''}</h3><span class="status ${group.first ? 'winner' : group.achieved ? 'achieved' : ''}">${data.phase === 'finalized' && group.first && !champion.tied ? '9月第一' : status}</span></div>
      <div class="team-stats"><span class="team-count">${group.done}<small>/ ${group.target} 个</small></span><span class="team-rate">${group.rate.toFixed(1)}<small>%</small></span></div>
      <div class="bar" role="progressbar" aria-label="${name}完成率" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${Math.min(group.rate, 100)}" aria-valuetext="实际完成率${group.rate.toFixed(1)}%"><i style="transform:scaleX(${Math.min(group.done / group.target, 1)})"></i></div>
      <div class="team-caption"><span>${group.solo ? '计入总目标 · 不参与第一评选' : group.members < 2 ? '不足2人 · 不参与第一评选' : `9月目标 ${group.target} 个`}</span><b>${caption}</b></div>
    </article>`
  }).join('')
  $('rule-summary').textContent = clean ? '统计口径：9月有效新签 · 同客不重复 · 退款失效重算' : quality.message
}

function updateStatus() {
  $('clock-date').textContent = currentBeijingDate().replaceAll('-', '.')
  const stale = snapshot && snapshotIsStale(snapshot)
  const notice = $('data-notice')
  const interrupted = Boolean(failure || stale)
  const badData = snapshot && !snapshot.data_quality.ok
  notice.classList.toggle('error', interrupted || Boolean(badData))
  notice.classList.toggle('review', snapshot?.phase === 'pending_review')
  if (interrupted) notice.textContent = snapshot ? '更新中断 · 保留最后数据' : '数据暂不可用'
  else if (badData) notice.textContent = '数据待核对 · 第一评选暂停'
  else if (snapshot?.phase === 'pending_review') notice.textContent = '9月已结束 · 排名待复核'
  else if (snapshot?.phase === 'finalized') notice.textContent = '9月已复核'
  else if (snapshot?.phase === 'upcoming') notice.textContent = '9月活动尚未开始'
  else if (snapshot) notice.textContent = qs.has('preview') || qs.has('date_from') || qs.has('date_to')
    ? '9月正式统计 · 不使用预览日期' : '9月新签 · 目标进行中'
  $('sync').classList.toggle('stale', interrupted || Boolean(badData))
  $('sync').textContent = snapshot
    ? `● ${interrupted ? '更新中断 · ' : ''}数据截至 ${formatBeijingShortDateTime(snapshot.as_of)} · OKKI`
    : failure || '正在获取9月数据…'
  $('retry').hidden = !interrupted
  if (!snapshot && failure && $('loading-message')) $('loading-message').textContent = failure
}

async function refresh() {
  if (request || disposed) return
  const key = qs.get('key')
  if (!key) {
    failure = '缺少大屏访问码，请从方舟采购节看板进入'
    updateStatus()
    return
  }
  request = new AbortController()
  const timeout = setTimeout(() => request?.abort(), 15000)
  try {
    const query = new URLSearchParams({ key })
    // Standalone screen-key API, like existing public festival screens; no JWT client.
    const response = await fetch(`/api/public/festival/september-new-sign?${query}`, {
      signal: request.signal, cache: 'no-store', referrerPolicy: 'no-referrer',
    })
    if (!response.ok) throw new Error(response.status === 403
      ? '访问码无效或已停用，请从方舟采购节看板重新进入' : '暂时无法获取数据，请稍后重试')
    const body = await response.json()
    if (body.code !== 200 || !validPayload(body.data)) throw new Error('数据返回异常，请重新获取')
    if (disposed) return
    snapshot = body.data
    failure = ''
    render(snapshot)
  } catch (error) {
    if (disposed) return
    failure = error.name === 'AbortError' ? '取数超时，请检查网络后重新获取' : error.message
    console.warn('September screen refresh failed:', failure)
  } finally {
    clearTimeout(timeout)
    request = null
    if (!disposed) updateStatus()
  }
}

document.querySelectorAll('.guide-tabs a').forEach(link => {
  const filename = link.getAttribute('href').split('/').pop()
  link.href = screenUrl(filename, location.search)
})
$('retry').addEventListener('click', refresh)
window.addEventListener('resize', fit)
fit()
updateStatus()
refresh()
let refreshTimer, clockTimer, rotationTimer
function startTimers() {
  refreshTimer = setInterval(() => { if (!document.hidden) refresh() }, 30000)
  clockTimer = setInterval(updateStatus, 1000)
  rotationTimer = qs.get('stay') === '1' ? null : setTimeout(() => {
    location.href = screenUrl('zhaiyao.html', location.search)
  }, 30000)
}
startTimers()
document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh() })
window.addEventListener('pagehide', () => {
  disposed = true
  request?.abort()
  clearInterval(refreshTimer)
  clearInterval(clockTimer)
  clearTimeout(rotationTimer)
})
window.addEventListener('pageshow', event => {
  if (event.persisted) {
    disposed = false
    updateStatus()
    refresh()
    startTimers()
  }
})
