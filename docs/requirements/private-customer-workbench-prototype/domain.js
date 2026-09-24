(function(root){
  'use strict';
  const rank={urgent:0,high:1,normal:2,low:3};
  const canonical=v=>v&&typeof v==='object'?Array.isArray(v)?'['+v.map(canonical).join(',')+']':'{'+Object.keys(v).sort().map(k=>JSON.stringify(k)+':'+canonical(v[k])).join(',')+'}':JSON.stringify(v);
  const fail=(code,message)=>{const e=new Error(message);e.code=code;throw e;};
  const customer=(s,id)=>s.customers.find(c=>c.id===id)||fail('NOT_FOUND','客户不存在');
  const active=t=>['pending','snoozed'].includes(t.status);
  const recommendable=(s,t)=>active(t)&&(!t.snoozedUntil||t.snoozedUntil<=s.now);
  const overdue=(s,t)=>active(t)&&!!t.due&&t.due<s.now;
  function taskList(s,{scope='primary',filter='all',query=''}={}){
    const ids=new Set(s.customers.filter(c=>scope==='all'||c.scope===scope).map(c=>c.id));
    return s.tasks.filter(t=>ids.has(t.customer)).filter(t=>[customer(s,t.customer).name,t.title].join(' ').toLowerCase().includes(query.toLowerCase())).filter(t=>filter==='done'?t.status==='done':filter==='snoozed'?t.status==='snoozed':filter==='overdue'?overdue(s,t):filter==='high'?active(t)&&rank[t.priority]<2:filter==='reorder'?active(t)&&t.kind==='reorder':active(t)).sort((a,b)=>rank[a.priority]-rank[b.priority]||a.due.localeCompare(b.due));
  }
  function createTask(s,task){
    const existing=s.tasks.find(t=>t.event===task.event);
    if(existing)return existing;
    const c=customer(s,task.customer);
    if(c.dnc&&task.kind!=='internal')fail('CONTACT_BLOCKED','客户有已确认的联系限制，不能创建触达任务。');
    const row={...task,id:'task-'+(s.tasks.length+1),version:1,status:'pending',originalDue:task.due,snoozedUntil:null,results:[]};s.tasks.push(row);return row;
  }
  function replay(s,key,payload,fn){
    if(!key)fail('KEY_REQUIRED','缺少操作标识');
    const hash=canonical(payload),old=s.requests[key];
    if(old){if(old.hash!==hash)fail('IDEMPOTENCY_CONFLICT','同一操作标识对应不同内容');return old.result;}
    const result=fn();s.requests[key]={hash,result};return result;
  }
  function complete(s,id,payload,key){return replay(s,key,{id,...payload},()=>{
    const t=s.tasks.find(x=>x.id===id)||fail('NOT_FOUND','任务不存在');
    if(t.version!==payload.version||!active(t))fail('VERSION_CONFLICT','任务已改变，请刷新后重试。');
    if(!payload.summary?.trim())fail('RESULT_REQUIRED','请填写实际跟进结果。');
    if(payload.outcome!=='resolved'&&!payload.next?.trim())fail('NEXT_REQUIRED','事项尚未解决，请填写下一步与日期。');
    if(payload.next&&!payload.nextDate)fail('DATE_REQUIRED','请填写下一步日期。');
    if(customer(s,t.customer).dnc&&t.kind!=='internal')fail('CONTACT_BLOCKED','当前联系限制已生效。');
    if(payload.nextDate&&payload.nextDate<=s.now.slice(0,10))fail('DATE_INVALID','下一步请选择演示日之后的日期。');
    const next=payload.next?createTask(s,{customer:t.customer,event:(t.issueId||t.event)+':attempt:'+((t.attempt||1)+1),issueId:t.issueId||t.event,attempt:(t.attempt||1)+1,planId:t.planId,sampleId:t.sampleId,windowId:t.windowId,family:t.family,title:payload.next,kind:t.kind,channel:t.channel,priority:'normal',due:payload.nextDate+'T18:00:00+08:00',reason:'来自已登记结果的后续安排。',evidence:'跟进结果 '+id,next:payload.next}):null;
    t.status='done';t.eventState=payload.outcome==='resolved'?'resolved':'awaiting_reply';t.version++;t.results.push({summary:payload.summary,outcome:payload.outcome,at:s.now});
    const plan=s.plans.find(p=>p.task===id);if(plan){plan.previousTasks=[...(plan.previousTasks||[]),id];plan.task=next?.id||id;plan.status=next?'active':'done';plan.stage=next?'本次联系已完成，等待后续；测试尚未结束':'本次计划已完成；不代表样品测试结束';if(next)plan.date=payload.nextDate;plan.version++;}
    s.history.push({type:'complete',id,at:s.now,summary:payload.summary});return {id,next:next?.id||null};
  });}
  function snooze(s,id,date){const t=s.tasks.find(x=>x.id===id);if(!t||!active(t))fail('STATE_CONFLICT','任务状态已改变');if(date<=s.now.slice(0,10))fail('DATE_INVALID','延后日期应晚于演示日');t.snoozedUntil=date+'T09:00:00+08:00';t.status='snoozed';t.version++;}
  function dismiss(s,id,reason){const t=s.tasks.find(x=>x.id===id);if(!reason?.trim())fail('REASON_REQUIRED','请填写忽略原因');if(!t||!active(t))fail('STATE_CONFLICT','任务状态已改变');t.status='dismissed';t.version++;s.history.push({type:'dismiss',id,reason,at:s.now});}
  function revise(s,id,payload){const c=customer(s,id);if(c.version!==payload.version)fail('VERSION_CONFLICT','档案已有新版本。请查看最新值后再保存。');const allowed=['color','model','market','note'];if(!allowed.includes(payload.field))fail('GOVERNED_FIELD','该字段必须通过治理流程变更。');if(!payload.value?.trim()||!payload.reason?.trim())fail('VALUE_REQUIRED','新值和修订依据必填。');c.history.unshift({version:c.version+1,field:payload.field,old:c[payload.field],value:payload.value,reason:payload.reason,at:s.now});c[payload.field]=payload.value;c.version++;c.inputSeq++;for(const suggestion of c.suggestions){if(suggestion.field===payload.field&&['pending','later'].includes(suggestion.status))suggestion.status='stale';}return c;}
  function suggestion(s,id,sid,operation,value,version,reason){const c=customer(s,id),p=c.suggestions.find(x=>x.id===sid);if(!c.bound||!c.sourceAllowed)fail('SOURCE_FORBIDDEN','来源未绑定或不可访问，不能采纳建议');if(!p||!['pending','later'].includes(p.status))fail('STATE_CONFLICT','建议已经处理');if(p.sourceType!=='event'&&(s.analysis[id].status!=='ready'||p.bindingVersion!==c.bindingVersion||p.analysisVersion!==s.analysis[id].version||!s.messages.some(m=>m.id===p.sourceId&&m.customer===id&&m.channel===p.channel)))fail('SUGGESTION_STALE','绑定或分析版本已变化，请重新分析');if(operation==='accepted'){revise(s,id,{version:version??c.version,field:p.field,value:value||p.value,reason:reason||'人工核对 '+p.source});}p.status=operation;}
  const days=(a,b)=>Math.round((Date.parse(a+'T00:00:00+08:00')-Date.parse(b+'T00:00:00+08:00'))/86400000);
  const median=a=>{const v=[...a].sort((x,y)=>x-y),m=Math.floor(v.length/2);return v.length%2?v[m]:(v[m-1]+v[m])/2;};
  const addDays=(date,n)=>new Date(Date.parse(date+'T00:00:00Z')+n*86400000).toISOString().slice(0,10);
  function cycle(orders,family='发块'){const dates=[...new Set(orders.filter(o=>o.valid&&o.type==='bulk'&&o.items.some(i=>i.family===family)).map(o=>o.date))].sort();const intervals=dates.slice(1).map((d,i)=>days(d,dates[i]));if(dates.length<4)return {status:'insufficient',family,samples:dates.length,intervals,days:null};const typical=median(intervals),irregular=(Math.max(...intervals)-Math.min(...intervals))/typical>0.6;return {status:irregular?'irregular':'observed',family,samples:dates.length,intervals,days:typical,last:dates.at(-1),from:addDays(dates.at(-1),typical-7),to:addDays(dates.at(-1),typical+7)};}
  function analytics(s,id,{type='bulk',currency='USD',unit='pcs',dimension='model',measure='quantity',match='',from='',to='',cycleFamily='发块'}={}){
    const all=s.orders.filter(o=>o.customer===id&&o.valid&&o.type===type&&(!from||o.date>=from)&&(!to||o.date<=to)&&(!match||o.items.some(i=>(i[dimension]||'未知')===match))),orders=all.filter(o=>o.currency===currency),groups={};
    let total=0,known=0,lines=0,usable=0;
    for(const o of orders){const seen=new Set();for(const item of o.items){if(item.unit!==unit)continue;const label=item[dimension]||'未知';if(match&&label!==match)continue;lines++;if(item[dimension])known++;const value=measure==='amount'?item.amount:measure==='orders'?1:item.qty;if(value==null)continue;usable++;if(measure==='orders'&&seen.has(label))continue;seen.add(label);groups[label]=(groups[label]||0)+value;if(measure!=='orders')total+=value;}if(measure==='orders'&&seen.size)total++;}
    return {orders,all,groups,total,coverage:lines?Math.round(known/lines*100):null,metricCoverage:lines?Math.round(usable/lines*100):null,unknownValues:lines-usable,cycle:cycle(s.orders.filter(o=>o.customer===id),cycleFamily),currencies:[...new Set(all.map(o=>o.currency))],units:[...new Set(all.flatMap(o=>o.items.map(i=>i.unit)))]};
  }
  function bind(s,id){const c=customer(s,id);if(!c.sourceAllowed)fail('SOURCE_FORBIDDEN','源账号不允许共享');c.bound=true;c.bindingVersion=(c.bindingVersion||0)+1;for(const p of c.suggestions){if(p.sourceType!=='event'&&['pending','later'].includes(p.status))p.status='stale';}s.analysis[id]={status:'stale',version:0};}
  function analyze(s,id){
    const c=customer(s,id);if(!c.sourceAllowed)fail('SOURCE_FORBIDDEN','源权限不足，摘要不展示');if(!c.bound)fail('UNBOUND','请先确认会话与客户的绑定');
    const a=s.analysis[id];a.status='ready';a.version++;
    for(const p of c.suggestions)if(p.sourceType!=='event'&&['pending','later'].includes(p.status))p.status='stale';
    c.suggestions.push({id:'analysis-'+id+'-'+a.version,field:id==='b'?'note':'color',label:id==='b'?'样品安排':'颜色偏好',value:id==='b'?'客户尚未开始测试样品':'#613，偏好自然根色',source:'WhatsApp · 消息 '+id+'-wa-2 · 新分析 v'+a.version,sourceType:'message',sourceId:id+'-wa-2',channel:'WhatsApp',analysisVersion:a.version,bindingVersion:c.bindingVersion,status:'pending'});
  }
  function toggleSubscription(s,id){const sub=s.subscriptions.find(x=>x.id===id)||fail('NOT_FOUND','订阅不存在');sub.enabled=!sub.enabled;return sub;}
  function collectSubscription(s,id){const sub=s.subscriptions.find(x=>x.id===id)||fail('NOT_FOUND','订阅不存在');if(!sub.enabled)fail('STATE_CONFLICT','请先恢复监控计划');const first=!sub.baseline;sub.status='active';sub.error=null;sub.baseline=true;sub.last='2026-09-24 09:00（模拟）';return first;}
  function subscribe(s,id,url,channel){let u;try{u=new URL(url);}catch{fail('URL_INVALID','请填写完整 https 网址');}if(u.protocol!=='https:'||u.username||u.password||/^(localhost|127\.|10\.|192\.168\.|\[|0\.)/.test(u.hostname))fail('URL_INVALID','请输入不含凭据的公开 HTTPS 地址');if(s.subscriptions.some(x=>x.customer===id&&x.url===u.href))fail('DUPLICATE','该渠道已订阅');s.subscriptions.push({id:'sub-'+(s.subscriptions.length+1),customer:id,channel,url:u.href,enabled:true,status:'baseline',last:'未采集',baseline:false});}
  function decideEvent(s,id,operation){const e=s.events.find(x=>x.id===id);if(!e)fail('NOT_FOUND','事件不存在');if(e.status!=='pending')return;if(operation==='confirmed'){createTask(s,{customer:e.customer,event:'monitor:'+e.key,title:'跟进新门店筹备需求',kind:'message',channel:'WhatsApp',priority:'high',due:'2026-09-25T18:00:00+08:00',reason:e.title,evidence:e.sources.join('；'),next:'确认新店开业时间与产品需求。'});const c=customer(s,e.customer);c.suggestions.push({id:'event-'+e.id,field:'note',label:'经营动态',value:e.value,source:e.sources[0],sourceType:'event',sourceId:e.id,status:'pending'});}e.status=operation;}
  function changeSample(s,id,date){const p=s.plans.find(x=>x.id===id);if(!p||p.type!=='sample')fail('NOT_FOUND','样品计划不存在');if(date<=s.now.slice(0,10))fail('DATE_INVALID','请安排在演示日之后');const t=s.tasks.find(x=>x.id===p.task);if(!t||!active(t))fail('STATE_CONFLICT','样品任务已经结束，请新建后续维护计划');p.date=date;p.stage='客户已改约，待开始测试';p.version++;t.due=date+'T17:00:00+08:00';t.status='pending';t.snoozedUntil=null;t.version++;s.history.push({type:'reschedule',id,originalDue:t.originalDue,at:s.now,date});}
  function addPlan(s,id,title,date,type){if(!title?.trim()||!date)fail('VALUE_REQUIRED','计划名称和日期必填');if(date<s.now.slice(0,10))fail('DATE_INVALID','计划日期不能早于演示日');const pid='p'+(s.plans.length+1);const t=createTask(s,{customer:id,event:'plan:'+pid+':'+date,title,kind:'message',channel:'WhatsApp',priority:'normal',due:date+'T18:00:00+08:00',reason:'业务员确认的维护计划。',evidence:'计划 '+pid,next:title});s.plans.push({id:pid,customer:id,title,date,type,stage:'已安排',task:t.id,status:'active',version:1});t.planId=pid;t.issueId='plan:'+pid+':'+date;t.attempt=1;return t;}
  function newOrder(s,provided){
    const o=provided?structuredClone(provided):{...structuredClone(s.orders[0]),id:'A05',date:'2026-09-24',batch:'a4',coversWindowIds:['w-a-hairpiece']};
    if(s.orders.some(x=>x.id===o.id))return;s.orders.push(o);
    if(!o.valid||o.type!=='bulk')return;
    for(const w of s.windows.filter(w=>w.customer===o.customer&&w.state==='open'&&(o.coversWindowIds||[]).includes(w.id)&&o.date>=w.from&&o.date<=w.to&&o.items.some(i=>i.family===w.family))){
      w.state='superseded';w.coveredBy=o.id;
      for(const t of s.tasks.filter(t=>t.windowId===w.id&&active(t))){t.status='cancelled';t.version++;t.cancelReason='新商业订单 '+o.id+' 已覆盖对应产品族窗口';}
    }
  }
  function scan(s){let created=0;for(const t of root.PCWData.seed().tasks){if(!s.tasks.some(x=>x.event===t.event)){createTask(s,t);created++;}}s.scanCount++;return created;}
  root.PCW={rank,customer,active,recommendable,overdue,taskList,createTask,complete,snooze,dismiss,revise,suggestion,median,cycle,analytics,bind,analyze,toggleSubscription,collectSubscription,subscribe,decideEvent,changeSample,addPlan,newOrder,scan};if(typeof module!=='undefined')module.exports=root.PCW;
})(globalThis);
