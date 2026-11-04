(function(){
'use strict';
const $=s=>document.querySelector(s);
const safe=s=>String(s??'').replace(/[&<>"']/g,x=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[x]));
const button=(a,t,cls='',v='')=>`<button class="${cls}" data-act="${a}" data-value="${safe(v)}">${t}</button>`;
const tag=(s,c='')=>`<span class="tag ${c}">${safe(s)}</span>`;
const avatar=(c,large=false)=>`<span class="av ${large?'large':''}" style="background:${c.tone}">${c.name.split(' ').map(x=>x[0]).slice(0,2).join('')}</span>`;
const icons={layers:'m3 8 9-5 9 5-9 5z M3 12l9 5 9-5 M3 16l9 5 9-5',users:'M4 20v-2a5 5 0 0 1 5-5h2a5 5 0 0 1 5 5v2 M10 10a3 3 0 1 0 0-6 3 3 0 1 0 0 6 M16 5a3 3 0 0 1 0 6 M18 14a5 5 0 0 1 3 5',calendar:'M4 6h16v14H4z M4 10h16 M8 3v5 M16 3v5',brief:'M4 5h16v14H4z M7 9h10 M7 13h6',search:'M16 16l5 5 M11 18a7 7 0 1 0 0-14 7 7 0 1 0 0 14'};
document.querySelectorAll('[data-icon]').forEach(el=>el.innerHTML=`<svg viewBox="0 0 24 24" aria-hidden="true"><path d="${icons[el.dataset.icon]}"/></svg>`);
let mode='今日建议',filter='',current=0,axis='全部',chat=0,q='',feedbackTimer;
const storageKey='ark-private-sea-demo-v2';
let saved={};
try{saved=JSON.parse(sessionStorage.getItem(storageKey)||'{}')}catch{}
const st=saved.clients||{};
(saved.chats||[]).forEach((c,i)=>{if(chats[i])Object.assign(chats[i],c)});
function persist(){try{sessionStorage.setItem(storageKey,JSON.stringify({clients:st,chats:chats.map(({resolved,customer})=>({resolved,customer}))}))}catch{}}
const db=i=>st[i]??=( {grade:clients[i].grade,note:clients[i].note||'',date:'',extra:[],vote:'',closed:''} );
const pending=()=>clients.map((c,i)=>i).filter(i=>clients[i].type&&!db(i).closed);
const leftChats=()=>chats.map((c,i)=>i).filter(i=>!chats[i].resolved);
const notify=t=>{clearTimeout(feedbackTimer);$('#toast').textContent=t;$('#toast').hidden=false;feedbackTimer=setTimeout(()=>$('#toast').hidden=true,2200)};
const show=(title,html)=>{$('#modal').innerHTML=`<h2>${title}</h2>${html}`;if(!$('#dialog').open)$('#dialog').showModal()};
const close=()=>$('#dialog').close();
const form=(body,label='保存')=>`<form id="form">${body}<div class="actions"><button class="primary" type="submit">${label}</button></div></form>`;
function list(){
 const allowed=mode==='未关联会话'?leftChats():mode==='今日建议'?pending():clients.map((_,i)=>i);
 return allowed.filter(i=>{const c=mode==='未关联会话'?chats[i]:clients[i];return [c.name,c.country,c.code,c.mask].join(' ').toLowerCase().includes(q.toLowerCase())&&(!filter||(mode==='全部客户'?(filter==='S/A'?['S','A'].includes(db(i).grade):db(i).grade===filter):c.type===filter))});
}
function paint(){
 persist();
 const ids=list(),orphan=mode==='未关联会话';
 if(orphan&&!ids.includes(chat))chat=ids[0];
 if(!orphan&&!ids.includes(current))current=ids[0];
 $('#tabs').innerHTML=['今日建议','全部客户','未关联会话'].map((v,i)=>button('tab',`${v} ${[pending().length,clients.length,leftChats().length][i]}`,mode===v?'on':'',v)).join('');
 $('#chips').innerHTML=(mode==='今日建议'?['待回复','等客户回','跟进到期','新客户']:mode==='全部客户'?['S/A','B','未分级']:[]).map(v=>button('filter',v+(mode==='今日建议'?' '+pending().filter(i=>clients[i].type===v).length:''),filter===v?'on':'',v)).join('');
 $('#rows').innerHTML=ids.map(i=>{if(orphan){let c=chats[i];return button('pick',`<span class="av" style="background:#edf1f3">WA</span><span><strong>${c.name}</strong><p>${c.mask}</p><span class="meta">WhatsApp · ${c.age}</span></span>`,'row '+(chat===i?'sel':''),i)}
 const c=clients[i];return button('pick',`${avatar(c)}<span><span class="flex"><strong>${c.name}</strong>${tag(db(i).grade)}</span><p>${c.reason}</p><span class="meta">${c.code} · ${c.overCap||c.ambiguous||i===3?'手工跟进':c.crm?'WhatsApp':c.unseen||c.rule?'OKKI':'WhatsApp'} · ${c.age}</span></span>`,'row '+(current===i?'sel':''),i)}).join('')||`<div class="empty"><h3>${q?'没有匹配的客户或会话':mode==='今日建议'?'今天没有需要特别跟进的客户':'暂无记录'}</h3><p class="sub">${q?'试试其他名称或国家。':mode==='今日建议'?`私海中还有 ${clients.filter((_,i)=>db(i).grade==='未分级').length} 位未分级客户。`:''}</p>${mode==='今日建议'&&!q?button('ungraded','查看未分级客户'):''}</div>`;
 $('#count').textContent=`${ids.length} ${orphan?'个会话':'位客户'}　·　仅我的私海`;
 if(orphan&&chats.some(c=>c.resolved))$('#count').innerHTML+='　'+button('history','已处理会话','link');
 $('#detail').innerHTML=button('back','‹　返回队列','back')+(!ids.length?'<div class="empty muted">没有可展示的详情</div>':orphan?`<div class="identity"><div class="eyebrow">UNLINKED CONVERSATION</div><h2>${chats[chat].name}</h2><p class="meta">${chats[chat].mask} · ${chats[chat].age}</p></div><div class="block"><h3>确认会话归属</h3><p class="human">关联前不展示聊天正文，不进入客户画像。</p><div class="actions" style="margin-top:14px">${button('linkchat','关联到客户','primary')}${button('ignore','不是客户')}</div></div>`:detail());
}
function analysisState(c,s){
 const quota=s.runs||0;
 if(!c.revoked&&!c.failed&&!c.ambiguous)return '';
 const status=s.fresh?'已根据当前可见档案重新分析':c.revoked?'授权已变更，需重新分析':c.failed?'AI 分析未通过检查':'结果不确定 · 未自动重试';
 const explanation=s.fresh?'本次仅使用可见的建档记录和人工备注，无可验证的新草稿。':c.revoked?'旧画像与草稿已隐藏；重新分析仅使用当前获授权的资料。':c.failed?'草稿引用未通过校验，仅展示规则原因。':'上次分析超时，无法确认结果。可手动发起新的分析。';
 return `<div class="analysisnote"><strong>${status}</strong><p class="sub">${explanation}</p><div class="actions"><button data-act="reanalyze" ${quota>=3?'disabled':''}>重新分析</button><small>本地演示 · 今日已用 ${quota}/3 次${quota>=3?'，明日可再试':''}</small></div></div>`;
}
const title=i=>i===0?'先回应 Anna 的库存与价格问题':clients[i].reason;
function events(){
 const c=clients[current],ev=[...db(current).extra];
 if(c.overCap||c.ambiguous)ev.push({channel:'跟进',date:c.overCap?'10-28':'10-21',title:c.overCap?'电话 · 约定首次采购回访':'寄样 · 约定色卡回访',text:'Stella 写 · 下次跟进为 2026-11-04。',ref:'evidence'});
 if(c.quote)ev.push({channel:'WhatsApp',date:current===0?'11-03':c.age,title:current===0?'2 条消息 · 客户询问现货与价格':'1 条消息 · 最近一次沟通',text:(current===0?'Anna · 18:18　Hi Stella!<br>Anna · 18:21 · M-90121　':'')+safe(c.quote),ref:'evidence'});
 if(current===0)ev.push({channel:'跟进',date:'10-15',title:'电话 · 确认门店周年庆',text:'Stella 写 · Anna 计划在 11 月办周年庆。'},{channel:'订单',date:'08-12',title:'订单 · $1,350',text:'天才片 20″ × 6，来源为订单记录。'},{channel:'背调',date:'03-18',title:'官网 · 门店信息',text:'官网门店页列出德州 3 家门店。示例脱敏。'});
 ev.push({channel:'建档',date:c.since||'近期',title:`${c.source} · 客户建档`,text:'来源：个人私海客户档案。',ref:c.rule?'evidence':''});
 return ev.filter(e=>axis==='全部'||e.channel===axis).map(e=>`<details ${e.ref?`id="${e.ref}"`:''}><summary>${safe(e.date)}　<b>${safe(e.title)}</b></summary><p>${e.text}</p></details>`).join('')||'<p class="sub">此渠道暂无可见记录。</p>';
}
function detail(){
 const c=clients[current],s=db(current);
 const ai=c.rule||c.unseen?'':`<div class="guide"><b>先查什么</b><span>${c.check}</span><b>怎么跟</b><span>${c.plan}</span></div><div class="draft"><span class="eyebrow">回复草稿</span><p lang="en">${c.draft}</p></div>${c.risk?'<p class="sub" style="color:#914b14;margin:0 0 8px">含库存与报价占位符，发送前请核对。</p>':''}<div class="actions">${button('wa','在 WhatsApp 打开 ↗','primary')}${button('copy','复制草稿')}</div>`;
 return `<div class="identity"><div class="custhead"><div class="flex">${avatar(c,true)}<div><h2>${c.name}</h2><div class="meta">${c.country} · ${c.source} · ${c.since||'2026'} 建档${c.person?' · 联系人 '+safe(c.person):''}</div></div></div>${tag(c.type||'未分析',c.type==='待回复'?'warn':'')}</div><div class="tierline"><label>分级 <select id="tier">${['S','A','B','C','D','E','未分级'].map(v=>`<option ${s.grade===v?'selected':''}>${v}</option>`).join('')}</select></label>${current===0&&s.grade==='B'&&!s.humanGrade?`<span class="goldbox">AI 建议 A · 6 单 $8.4k</span>${button('adopt','采纳','link')}`:''}${s.humanGrade?tag('Stella 确认','teal'):''}<span>下次跟进 ${button('followdate',s.date||'选日期','link')}</span></div><div class="human"><b>关键备注</b>　${safe(s.note)||'待补充'} ${s.note?'<small> · Stella 写</small>':''} ${button('note','编辑','link')}</div></div>
 <div class="advice"><div class="sectionline"><div class="eyebrow">✦　${c.rule?'规则提醒':c.unseen?'分析状态':'今日建议'}</div>${tag(s.closed|| (s.fresh?'已重新分析':c.rule?'仅规则':c.ambiguous?'结果不确定':c.revoked?'需重新分析':c.crm?'仅 CRM 可读':c.unseen?'未做 AI 分析':(current===0?'高优先级 · ':'')+'AI · 06:52'),s.closed?'teal':'gold')}</div><h3>${c.unseen?(c.crm?'聊天仅供 CRM 查看':c.revoked?'授权状态':c.reason):title(current)}</h3>${c.unseen?`<p class="sub">${c.revoked||c.ambiguous?'':c.crm?'会话消息只在时间轴可见，不进入 AI 资料包。':'本轮 40 位分析名额已用完，仅展示规则原因。'}</p>`:`<p>${c.reason}。 ${button('cite',c.rule?'建档记录 ↘':current===0?'M-90121 ↘':'沟通记录 ↘','link')}</p>`}${c.overCap||c.ambiguous?button('cite','跟进记录 ↘','link'):''}${analysisState(c,s)}${ai}${!c.type||s.closed?'':`<div class="actions feedback">${['有用','没用'].map(v=>button('vote',(s.vote===v?'✓ ':'')+v,s.vote===v?'goldbox':'',v)).join('')}${button('snooze','稍后…')}${button('done','标记已跟进','link')}</div>`}</div>
 <section class="block"><div class="sectionline"><h3>客户画像</h3><span class="sub">${c.profile?'AI · 11-04 06:52':'暂无 AI 画像'}</span></div><p class="human">${c.profile||'当前仅可查看已同步的客户档案。'}</p><div class="tiles"><div class="tile"><span class="sub">历史订单</span><br><b>${c.orders||'暂无可见订单'}</b>${orderDetails[current]?`<p class="sub">最近下单 ${orderDetails[current][0]} · ${orderDetails[current][1]}</p><p class="sub">常买 ${orderDetails[current][2]}</p>`:''}</div><div class="tile"><span class="sub">客户背调</span><br>${current===0?`<b>德州 · 3 家门店</b> ${button('research','展开全文','link')}`:'暂无可见背调'}</div></div></section><section class="block timeline"><div class="sectionline"><h3>时间轴</h3>${button('record','＋ 记一笔')}</div><div class="chips">${['全部','WhatsApp','订单','背调','跟进'].map(v=>button('axis',v,v===axis?'on':'',v)).join('')}</div><div id="events">${events()}</div></section><div class="foot">仅含方舟可见渠道 · WhatsApp 同步于 06:20</div>`;
}
let save;
function dateField(label,value='',min=''){return `<label>${label}<input type="date" id="when" required value="${safe(value)}" min="${min}"></label>`}
function finish(t){close();paint();notify(t)}
function openWA(i){show('WhatsApp 草稿预览',`<p class="meta">离线模拟 · ${clients[i].name}</p><label>可编辑的回复草稿<textarea>${safe(clients[i].draft)}</textarea></label><p class="sub">此处模拟打开聊天，不会发送消息，也不计为已跟进。</p>`)}
document.addEventListener('click',async e=>{
 const btn=e.target.closest('[data-act]');if(!btn)return;
 const {act:a,value:v}=btn.dataset,s=current===undefined?null:db(current);
 if(a==='tab'||a==='ungraded'){mode=a==='tab'?v:'全部客户';filter=a==='ungraded'?'未分级':'';q='';$('#search').value='';axis='全部';paint()}
 if(a==='filter'){filter=filter===v?'':v;paint()}
 if(a==='pick'){if(mode==='未关联会话')chat=Number(v);else current=Number(v);axis='全部';document.body.classList.add('reading');paint();if(matchMedia('(max-width:720px)').matches)window.scrollTo(0,0)}
 if(a==='back'){document.body.classList.remove('reading');window.scrollTo(0,0);$('.row.sel')?.focus({preventScroll:true})}
 if(a==='adopt'){s.grade='A';s.humanGrade=true;paint();notify('已采纳分级 A')}
 if(a==='wa')openWA(current);
 if(a==='copy'){try{await navigator.clipboard.writeText(clients[current].draft);notify('草稿已复制')}catch{show('复制草稿',`<label>请选中并复制<textarea readonly>${safe(clients[current].draft)}</textarea></label>`);$('#modal textarea').select()}}
 if(a==='reanalyze'&&(s.runs||0)<3){s.runs=(s.runs||0)+1;s.fresh=true;paint();notify('已按当前授权完成模拟分析')}
 if(a==='vote'){s.vote=v;if(v==='没用'){s.closed='同规则冷却 14 天';document.body.classList.remove('reading')}paint();notify(v==='没用'?'已记录没用，同规则冷却 14 天':'已记录有用')}
 if(a==='done'){s.closed='已跟进';document.body.classList.remove('reading');paint();notify('已标记跟进，建议已移出今日队列')}
 if(a==='snooze'||a==='followdate'){show(a==='snooze'?'稍后提醒':'下次跟进',form(dateField('跟进日期',s.date,a==='snooze'?'2026-11-05':today)));save=()=>{s.date=$('#when').value;if(a==='snooze'){s.closed='已延后';document.body.classList.remove('reading')}finish('已保存跟进日期')}}
 if(a==='note'){show('关键备注',form(`<label>Stella 写<textarea id="note" maxlength="600">${safe(s.note)}</textarea></label>`));save=()=>{s.note=$('#note').value.trim();finish('已保存关键备注')}}
 if(a==='research')show('客户背调',`<p>示例官网的门店页列出德州 3 家沙龙。公开账号展示浅色接发安装案例。</p><p class="sub">来源 · 官网门店页与公开社交账号，03-18 记录。</p>`);
 if(a==='history'){show('已处理会话',chats.map((c,i)=>c.resolved?'<p class="detailtext">'+c.name+' · '+(c.resolved==='linked'?'已关联 '+clients[c.customer].name:'已忽略')+' '+button('undo','撤销','link',i)+'</p>':'').join(''))}
 if(a==='undo'){const id=Number(v),c=chats[id];if(c.resolved==='linked')db(c.customer).extra=db(c.customer).extra.filter(x=>x.binding!==id);delete c.resolved;delete c.customer;chat=id;finish('会话已恢复至未关联队列')}
 if(a==='axis'){axis=v;paint()}
 if(a==='cite'){axis='全部';paint();let row=$('#evidence');if(row){row.open=true;row.classList.add('highlight');row.scrollIntoView({block:'center'});row.querySelector('summary').focus({preventScroll:true})}}
 if(a==='record'){show('记一笔',form('<label>渠道<select id="channel"><option>电话</option><option>WhatsApp</option><option>邮件</option><option>TM</option><option>寄样</option><option>见面</option><option>其他</option></select></label><label>内容<textarea id="memo" required></textarea></label><label>发生时间<input id="eventtime" type="datetime-local" required value="2026-11-04T09:00"></label><label>下次跟进（选填）<input id="next" type="date"></label>'));
 const suggest=()=>{if($('#channel').value!=='寄样')return;const d=new Date($('#eventtime').value);if(!Number.isFinite(+d))return;for(let n=0;n<10;){d.setDate(d.getDate()+1);if(d.getDay()!==0&&d.getDay()!==6)n++}$('#next').value=[d.getFullYear(),String(d.getMonth()+1).padStart(2,'0'),String(d.getDate()).padStart(2,'0')].join('-')};$('#channel').onchange=suggest;$('#eventtime').onchange=suggest;save=()=>{s.extra.unshift({channel:'跟进',date:$('#eventtime').value.replace('T',' '),title:$('#channel').value+' · Stella 写',text:safe($('#memo').value)});if($('#next').value)s.date=$('#next').value;axis='全部';finish('跟进已记录')}}
 if(a==='ignore'){chats[chat].resolved='ignored';document.body.classList.remove('reading');paint();notify('已忽略此会话')}
 if(a==='linkchat'){
  show('关联到我的客户',form('<label>搜索私海客户<input id="findclient" type="search" placeholder="客户或联系人名称"></label>'+button('clearcontact','清空搜索','link')+'<label>选择客户<select id="match" required></select></label>','确认关联'));
  const search=()=>{
   const query=$('#findclient').value.trim().toLowerCase();
   const matches=clients.map((c,i)=>({c,i})).filter(({c})=>[c.name,c.person].join(' ').toLowerCase().includes(query));
   $('#match').innerHTML='<option value="">'+(matches.length?'请手动选择客户':'没有匹配客户')+'</option>'+matches.map(({c,i})=>`<option value="${i}">${safe(c.name)}${c.person?' · '+safe(c.person):''}</option>`).join('');
  };
  $('#findclient').value=chats[chat].contact;search();$('#findclient').oninput=search;
  $('[data-act="clearcontact"]').onclick=e=>{e.preventDefault();$('#findclient').value='';search();$('#findclient').focus()};
  save=()=>{const id=Number($('#match').value);chats[chat].resolved='linked';chats[chat].customer=id;db(id).extra.unshift({binding:chat,channel:'WhatsApp',date:today,title:'已关联 WhatsApp 会话',text:'Stella 手动关联 '+safe(chats[chat].mask)});document.body.classList.remove('reading');finish('已关联到 '+clients[id].name)}
 }
});
$('#close').onclick=close;
document.addEventListener('submit',e=>{if(e.target.id==='form'){e.preventDefault();save?.()}});
if($('#search')){
 window.addEventListener('pageshow',e=>{if(e.persisted){try{const data=JSON.parse(sessionStorage.getItem(storageKey)||'{}');Object.assign(st,data.clients||{});(data.chats||[]).forEach((c,i)=>{delete chats[i].resolved;delete chats[i].customer;Object.assign(chats[i],c)});paint()}catch{}}});
 $('#search').oninput=e=>{q=e.target.value;paint()};
 document.addEventListener('change',e=>{if(e.target.id==='tier'){const s=db(current);s.grade=e.target.value;s.humanGrade=true;paint();notify('分级已由 Stella 更新')}});
 if(location.hash==='#unlinked')mode='未关联会话';
 paint();
}else{
 const morning=morningSnapshot.indices;
 $('#briefcount').textContent=morning.length;
 $('#briefunlinked').textContent=morningSnapshot.unresolvedChats+' 个未关联会话';
 $('#snapshottime').textContent=morningSnapshot.time+' 生成快照';
 $('#briefrows').innerHTML=morning.map((i,n)=>`<div class="briefrow"><div class="sectionline"><strong>${n+1}. ${clients[i].name}　${tag(clients[i].grade)}</strong>${clients[i].draft?button('briefwa','在 WhatsApp 打开 ↗','link',i):''}</div><p>${clients[i].reason}${clients[i].risk?' · 先查库存与报价':''}</p></div>`).join('');
 document.addEventListener('click',e=>{const b=e.target.closest('[data-act="briefwa"]');if(b)openWA(Number(b.dataset.value))});
}
})();
