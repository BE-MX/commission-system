/* Offline prototype state. No API, background worker, or real outbound action. */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.WorkbenchState = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  const CLOSED = new Set(['resolved', 'cancelled']);
  const LABELS = { open: '待处理', working: 'Agent 核实中', awaiting_reply: '等待客户', awaiting_colleague: '等待跟单', needs_decision: '待我决定', blocked: '受阻待核实', paused: '已暂停', resolved: '已解决', cancelled: '已终止' };
  const clone = value => JSON.parse(JSON.stringify(value));
  function addDays(date, n) {
    const [y, m, d] = date.split('-').map(Number);
    const next = new Date(Date.UTC(y, m - 1, d + n));
    return [next.getUTCFullYear(), String(next.getUTCMonth() + 1).padStart(2, '0'), String(next.getUTCDate()).padStart(2, '0')].join('-');
  }
  function find(session, id) {
    const task = session.tasks.find(t => t.uid === id);
    if (!task) throw new Error('事项已不存在，请刷新原型。');
    return task;
  }
  function makeTask(seed, index, day) {
    return { ...seed, uid: seed.uid || `CW-${String(index + 1).padStart(4, '0')}`, customerId: seed.c?.id ?? seed.customerId,
      status: seed.status || 'open', version: 1, sourceValid: true, sourceVersion: 1,
      originalDue: day, nextCheck: day, handledDates: [], history: [], feedback: {},
      agent: 'idle', evidence: [], replyReceived: false, colleagueDone: false,
      selectedPlan: false, pausedFrom: null, irreversibleRevision: 0, ...seed };
  }
  function create(seeds, persona, day = '2026-09-30') {
    const session = { schema: 3, persona, day, budget: persona === 'senior' ? 22 : 10, admissions: {}, focus: '承诺优先', tasks: seeds.map((t, i) => makeTask(t, i, day)) };
    admitDay(session);
    return session;
  }
  function isEligible(t, day) {
    return ['open', 'needs_decision', 'blocked'].includes(t.status) && t.nextCheck <= day;
  }
  function admitDay(session) {
    if (session.admissions[session.day]) return;
    session.admissions[session.day] = session.tasks.filter(t => t.p !== 0 && isEligible(t, session.day))
      .sort((a, b) => a.p - b.p).slice(0, session.budget).map(t => t.uid);
  }
  function group(session, t) {
    if (t.status === 'resolved' && !t.sourceValid) return 'focus';
    if (CLOSED.has(t.status)) return 'ended';
    if (isEligible(t, session.day)) {
      if (t.p === 0 || session.admissions[session.day]?.includes(t.uid)) return 'focus';
      return 'queued';
    }
    return 'progress';
  }
  function counts(session) {
    const result = { focus: 0, progress: 0, ended: 0, queued: 0, resolved: 0, cancelled: 0, handled: 0, urgent: 0 };
    session.tasks.forEach(t => {
      result[group(session, t)]++;
      if (t.status === 'resolved' && t.sourceValid) result.resolved++;
      if (t.status === 'cancelled') result.cancelled++;
      if (t.handledDates.includes(session.day)) result.handled++;
      if (group(session, t) === 'focus' && t.p === 0) result.urgent++;
    });
    return result;
  }
  function claim(session) {
    const task = session.tasks.find(t => group(session, t) === 'queued');
    if (!task) return null;
    session.admissions[session.day].push(task.uid);
    return task.uid;
  }
  function log(session, task, text, kind = 'record') {
    task.history.push({ id: `${task.uid}-${task.version + 1}-${task.history.length}`, day: session.day, kind, text });
  }
  function handled(session, task) {
    if (!task.handledDates.includes(session.day)) task.handledDates.push(session.day);
  }
  function resolutionError(task, payload) {
    if (!task.sourceValid || task.suggestionInvalid) return '依据已失效，请先重新核实。';
    if (task.status === 'working') return '核实尚未结束，不能登记解决。';
    if (!payload.summary?.trim() || !payload.evidence?.trim()) return '请填写实际结果并关联结果依据。';
    if (task.type === 'shipping' && (task.replyVersion !== task.sourceVersion || task.fulfillmentVersion !== task.sourceVersion)) return '需要客户接受当前方案和跟单确认当前发运安排两项依据；沟通完成不能关闭跟单行动。';
    if (task.status === 'paused') return '请先恢复暂停的事项，再登记结果。';
    return '';
  }
  function act(session, id, operation, payload = {}) {
    const t = find(session, id);
    if (payload.expectedVersion !== undefined && t.version !== payload.expectedVersion) throw new Error('事项已更新，请按最新进展重新决定。');
    if (CLOSED.has(t.status) && !['reopen', 'accuracy', 'applicability', 'adoption', 'invalidate'].includes(operation)) throw new Error('事项已结束，请先重开。');
    const snapshot = clone(t);
    let reversible = true;
    let text = '';
    switch (operation) {
      case 'wait':
        if (!t.sourceValid || t.suggestionInvalid) throw new Error('当前方案依据已失效，请先核实。');
        if (t.status === 'paused') throw new Error('请先恢复事项。');
        if (t.type === 'shipping' && !t.selectedPlan) throw new Error('请先核实并选定可兑现的方案。');
        if (t.status === 'awaiting_reply') return { changed: false };
        t.status = 'awaiting_reply'; t.awaitingResponse = true; t.waitingPlanVersion = t.sourceVersion;
        t.nextCheck = addDays(session.day, 3); handled(session, t);
        text = '记录已在其他沟通工具联系；等待客户回复，3 天后核验。本原型未发送消息。'; break;
      case 'later':
      case 'snooze':
        t.nextCheck = payload.date || addDays(session.day, operation === 'snooze' ? 1 : 7);
        if (t.nextCheck <= session.day) throw new Error('下一次处理时间必须晚于今天。');
        // Deferring a personal review must not change an executing or waiting workflow.
        handled(session, t); text = `下次处理：${t.nextCheck}；原承诺 ${t.originalDue} 保留。`; break;
      case 'pause':
        if (t.status === 'paused') return { changed: false };
        t.pausedFrom = t.status; t.status = 'paused'; t.agent = t.agent === 'running' ? 'paused' : t.agent;
        t.pauseReason = payload.reason || '客户暂时没有需求，等待客户主动提出或人工恢复';
        handled(session, t); text = `已暂停：${t.pauseReason}。不会自动恢复委派。`; break;
      case 'resume':
        if (t.status !== 'paused') throw new Error('该事项未暂停。');
        t.status = t.sourceValid ? (t.pausedFrom || 'open') : 'blocked';
        if (t.status === 'awaiting_reply' && t.replyVersion === t.sourceVersion) t.status = t.type === 'shipping' && t.fulfillmentVersion !== t.sourceVersion ? 'awaiting_colleague' : 'needs_decision';
        if (t.status === 'working') t.agent = 'running';
        t.nextCheck = session.day; t.pausedFrom = null;
        text = '人工恢复事项；继续按当前授权范围推进。'; break;
      case 'delegate':
        if (t.status === 'paused') throw new Error('请先恢复事项。');
        if (!t.sourceValid) throw new Error('来源不可用，请先核实来源。');
        if (t.agent === 'running') return { changed: false };
        t.status = 'working'; t.agent = 'running'; handled(session, t);
        text = '已委派核实事实与准备方案（本地模拟）；没有发送、改价或下单授权。'; break;
      case 'agent_result':
        if (t.agent !== 'running' || t.status !== 'working') throw new Error('只有执行中的委派可以接收结果。');
        t.agent = 'prepared'; t.status = 'needs_decision'; t.nextCheck = session.day;
        t.sourceVersion++; t.sourceValid = true; t.suggestionInvalid = false;
        t.evidence.push(`${session.day} 仓库确认可分批发运（模拟证据）`);
        text = '核实完成：分批发运方案和客户说明草稿已准备，等待业务员选择。'; reversible = false; break;
      case 'choose_plan':
        if (t.agent !== 'prepared' || !t.sourceValid || t.status !== 'needs_decision') throw new Error('请先让 Agent 完成核实，并使用最新方案。');
        t.selectedPlan = true; t.feedback.adoption = 'yes'; handled(session, t);
        text = '采用已核实的分批发运方案；沟通稿已准备，仍需记录实际沟通。'; break;
      case 'reply':
        if (!t.awaitingResponse && t.replyReceived) return { changed: false };
        if (!t.awaitingResponse) throw new Error('此事项尚未记录等待客户回复。');
        t.replyReceived = true; t.awaitingResponse = false; t.replyVersion = t.waitingPlanVersion;
        t.evidence.push(`${session.day} 客户接受来源版本 ${t.waitingPlanVersion} 的方案（模拟消息）`);
        if (t.status !== 'paused') t.status = !t.sourceValid || t.replyVersion !== t.sourceVersion ? 'blocked' : t.type === 'shipping' && t.fulfillmentVersion !== t.sourceVersion ? 'awaiting_colleague' : 'needs_decision';
        t.nextCheck = session.day;
        text = '客户回复已关联原事项（模拟）。客户响应与后续履约分别追踪。'; reversible = false; break;
      case 'colleague_done':
        if (t.type !== 'shipping') throw new Error('此事项没有跟单发运行动。');
        if (t.status === 'paused') throw new Error('请先恢复事项。');
        if (!t.selectedPlan || !t.sourceValid) throw new Error('当前方案尚未选定，不能确认发运。');
        if (t.fulfillmentVersion === t.sourceVersion) return { changed: false };
        t.colleagueDone = true; t.fulfillmentVersion = t.sourceVersion; t.evidence.push(`${session.day} 跟单确认来源版本 ${t.sourceVersion} 的分批发运（模拟源记录 SH-091）`);
        if (t.replyVersion === t.sourceVersion) { t.status = 'needs_decision'; t.nextCheck = session.day; }
        text = '跟单行动：已确认分批发运（模拟），不等于货物已送达，也不自动关闭客户事项。'; reversible = false; break;
      case 'resolve': {
        const error = resolutionError(t, payload); if (error) throw new Error(error);
        t.status = 'resolved'; t.result = payload.summary.trim(); t.resultEvidence = payload.evidence.trim(); t.endedOn = session.day;
        handled(session, t); text = `已解决：${t.result}；依据：${t.resultEvidence}`; break;
      }
      case 'terminate':
        if (!payload.reason?.trim()) throw new Error('请记录终止原因。');
        t.status = 'cancelled'; t.result = payload.reason.trim(); t.endedOn = session.day;
        t.agent = t.agent === 'running' || t.agent === 'paused' ? 'cancelled' : t.agent;
        handled(session, t); text = `已终止：${t.result}；不计入已解决或成交。`; break;
      case 'reopen':
        if (!CLOSED.has(t.status)) throw new Error('只有已结束事项可以重开。');
        if (!payload.reason?.trim()) throw new Error('请说明重开原因与新事实。');
        t.status = t.sourceValid ? 'open' : 'blocked'; t.nextCheck = session.day;
        t.sourceVersion++; t.awaitingResponse = false; t.selectedPlan = false; t.agent = 'idle';
        text = `重开原事项：${payload.reason.trim()}；之前的结果与证据保留，当前目标需要重新确认，事项编号不变。`; break;
      case 'invalidate':
        if (!t.sourceValid) return { changed: false };
        t.sourceValid = false; t.sourceVersion++;
        if (!CLOSED.has(t.status) && t.status !== 'paused') { t.status = 'blocked'; t.nextCheck = session.day; }
        t.agent = t.agent === 'running' ? 'blocked' : t.agent; t.selectedPlan = false;
        text = '来源已变化（模拟）；旧草稿不再可直接采用，需要重新核实。'; reversible = false; break;
      case 'reverify':
        if (t.status === 'paused') throw new Error('请先恢复事项。');
        t.sourceValid = true; t.suggestionInvalid = false; t.sourceVersion++; t.nextCheck = session.day;
        t.status = 'needs_decision'; t.agent = 'prepared';
        text = '已核对更新后的来源（模拟），新方案需要重新决定。'; reversible = false; break;
      case 'accuracy':
      case 'applicability':
      case 'adoption':
        if (!['yes', 'no'].includes(payload.value)) throw new Error('请选择有效反馈。');
        if (t.feedback[operation] === payload.value) return { changed: false };
        t.feedback[operation] = payload.value;
        if (operation === 'accuracy' && payload.value === 'no' && !CLOSED.has(t.status)) {
          if (t.status !== 'paused') { t.status = 'needs_decision'; t.nextCheck = session.day; }
          t.suggestionInvalid = true;
        }
        if (operation === 'accuracy' && payload.value === 'yes') t.suggestionInvalid = false;
        text = `${{ accuracy: '事实反馈', applicability: '建议适用性', adoption: '行动采纳' }[operation]}：${payload.value === 'yes' ? '是' : '否'}。分别记录，不自动训练模型。`; break;
      default: throw new Error('未知操作。');
    }
    if (!reversible) t.irreversibleRevision++;
    log(session, t, text, reversible ? 'record' : 'source'); t.version++;
    return { changed: true, text, undo: reversible ? { id, version: t.version, snapshot } : null };
  }
  function undo(session, receipt) {
    if (!receipt) throw new Error('此操作不可撤销。');
    const t = find(session, receipt.id);
    if (t.version !== receipt.version || t.irreversibleRevision !== receipt.snapshot.irreversibleRevision) throw new Error('已有新进展，不能撤销旧登记。已执行事实保持不变。');
    const history = t.history.slice(); const nextVersion = t.version + 1; const customer = t.c;
    Object.keys(t).forEach(k => delete t[k]); Object.assign(t, clone(receipt.snapshot));
    t.c = customer; t.history = history; t.version = nextVersion;
    log(session, t, '已撤销上一步本地登记；保留操作历史。');
  }
  function advance(session) {
    session.day = addDays(session.day, 1);
    session.tasks.forEach(t => {
      if (t.status === 'awaiting_reply' && t.nextCheck <= session.day) {
        t.status = 'needs_decision'; t.version++;
        log(session, t, '到达约定核验时间；请判断是否需要联系，系统未自动发送。');
      }
    });
    admitDay(session);
    return session.day;
  }
  function feedbackStats(session, dimension) {
    const entries = session.tasks.filter(t => t.feedback[dimension]);
    return { yes: entries.filter(t => t.feedback[dimension] === 'yes').length, total: entries.length };
  }
  return { LABELS, CLOSED, addDays, create, find, group, counts, claim, act, undo, advance, feedbackStats, resolutionError };
});
