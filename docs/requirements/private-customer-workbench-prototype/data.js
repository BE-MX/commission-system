(function(root){
  'use strict';
  const NOW='2026-09-24T09:00:00+08:00';
  const customers=[
    {id:'a',name:'Aurelia Hair Studio',initials:'AH',country:'英国 · 伦敦',contact:'Emma Wilson',stage:'稳定复购',tier:'重点客户',scope:'primary',scenario:'可靠复购',color:'#1B / #613',model:'M101 · 轻薄发块',market:'沙龙连锁',timezone:'Europe/London',bound:true,sourceAllowed:true},
    {id:'b',name:'Novelle Beauty',initials:'NB',country:'美国 · 洛杉矶',contact:'Mia Carter',stage:'样品测试',tier:'成长客户',scope:'primary',scenario:'样品未测试',color:'#2',model:'M201 · 全蕾丝',market:'精品沙龙',timezone:'America/Los_Angeles',bound:true,sourceAllowed:true},
    {id:'c',name:'Maison Élise',initials:'ME',country:'法国 · 巴黎',contact:'Élise Martin',stage:'维护中',tier:'一般客户',scope:'primary',scenario:'联系受限',color:'待确认',model:'M101',market:'零售门店',timezone:'Europe/Paris',bound:true,sourceAllowed:true,dnc:true},
    {id:'d',name:'Solace Hair Co.',initials:'SH',country:'澳大利亚 · 悉尼',contact:'Alex Lee',stage:'待核验',tier:'新客户',scope:'primary',scenario:'同名身份待绑定',color:'未知',model:'待确认',market:'待确认',timezone:'Australia/Sydney',bound:false,sourceAllowed:true},
    {id:'e',name:'Lumière Atelier',initials:'LA',country:'加拿大 · 多伦多',contact:'Sophie Roy',stage:'需求沟通',tier:'成长客户',scope:'collaborator',scenario:'消息断流 / 源权限受限',color:'未知',model:'M201',market:'沙龙',timezone:'America/Toronto',bound:true,sourceAllowed:false},
    {id:'f',name:'Velvet Crown',initials:'VC',country:'德国 · 柏林',contact:'Lena Fischer',stage:'报价中',tier:'成长客户',scope:'primary',scenario:'并发修订冲突',color:'#4',model:'M101',market:'专业门店',timezone:'Europe/Berlin',bound:true,sourceAllowed:true,conflict:true}
  ].map(c=>({...c,version:3,inputSeq:8,bindingVersion:c.bound?1:0,note:'',privateNote:'',history:[],suggestions:[{id:'pref-'+c.id,field:c.id==='b'?'note':'color',label:c.id==='b'?'样品安排':'颜色偏好',value:c.id==='b'?'客户尚未开始测试样品':'#613，偏好自然根色',source:'WhatsApp · 消息 '+c.id+'-wa-2',sourceType:'message',sourceId:c.id+'-wa-2',channel:'WhatsApp',bindingVersion:c.bound?1:0,analysisVersion:1,status:'pending'}]}));
  const messages=customers.flatMap(c=>[
    {id:c.id+'-wa-1',customer:c.id,channel:'WhatsApp',who:c.contact,time:'09.23 16:08',text:'Please confirm the lead time for our next order.'},
    {id:c.id+'-wa-2',customer:c.id,channel:'WhatsApp',who:c.contact,time:'09.23 16:20',text:c.id==='b'?'The samples arrived, but we have not started testing yet. Can we confirm a new date?':'Could you send photos of #613 with natural roots? Our new salon opens in October?'},
    {id:c.id+'-wa-3',customer:c.id,channel:'WhatsApp',who:'林悦',time:'09.23 16:30',text:'I will check the details and reply.',out:true},
    {id:c.id+'-ali-1',customer:c.id,channel:'阿里询盘',who:c.contact,time:'09.22 10:00',text:'Please quote 100 pcs of M101 and confirm the MOQ and arrival schedule.'},
    {id:c.id+'-ali-2',customer:c.id,channel:'阿里询盘',who:'林悦',time:'09.22 10:30',text:'We will confirm the quote and schedule.',out:true}
  ]);
  const tasks=[
    {id:'t1',customer:'a',event:'message:wa-102:promise-1',title:'回复 Emma 的色板确认',priority:'urgent',kind:'message',channel:'WhatsApp',due:'2026-09-23T18:00:00+08:00',reason:'客户昨日询问 #613 根色过渡；已承诺昨天发送实拍色板。',evidence:'M2 · 9 月 23 日 16:20',next:'核对色板，回复客户并确认接受情况。'},
    {id:'t2',customer:'a',event:'reorder:batch-a3:hairpiece',windowId:'w-a-hairpiece',family:'发块',title:'确认 10 月补货计划',priority:'high',kind:'reorder',channel:'WhatsApp',due:'2026-09-26T18:00:00+08:00',reason:'最近 4 个商业采购批次间隔为 28、32、30 天，已进入下单观察窗口。',evidence:'订单 A01–A04 · 模型 pcw_v1',next:'询问本月门店需求，确认型号与颜色组合。'},
    {id:'t3',customer:'b',event:'sample:sample-b:feedback',title:'确认样品是否开始测试',priority:'high',kind:'sample',channel:'WhatsApp',due:'2026-09-24T17:00:00+08:00',reason:'样品已签收，客户确认尚未测试。原约定今天确认测试安排。',evidence:'样品 S-B01 · 客户反馈',next:'约定实际测试日期，避免重复催反馈。'},
    {id:'t4',customer:'c',event:'internal:contact-restriction-c',title:'核验客户联系限制',priority:'normal',kind:'internal',channel:'内部',due:'2026-09-24T18:00:00+08:00',reason:'客户已要求暂停联系，保留内部核验任务；营销任务不生成。',evidence:'已确认联系限制 · v2',next:'与负责人核对限制依据，不向客户发送。'},
    {id:'t5',customer:'f',event:'inquiry:ali-f:quote-1',title:'跟进轻薄发块报价',priority:'normal',kind:'message',channel:'阿里询盘',due:'2026-09-25T18:00:00+08:00',reason:'报价已发送两天，客户关注交期与最小订单量。',evidence:'询盘 ALI-F01',next:'确认型号、起订量与目标到货日期。'},
    {id:'t6',customer:'e',event:'internal:source-e',title:'恢复沟通数据授权',priority:'normal',kind:'internal',channel:'内部',due:'2026-09-24T18:00:00+08:00',reason:'消息同步中断且源账号不可访问，不能据此推断客户没有回复。',evidence:'连接健康报告',next:'请账号管理员核验连接和共享范围。'}
  ].map(t=>({...t,status:'pending',version:1,snoozedUntil:null,originalDue:t.due,results:[]}));
  const orders=[
    ...['2026-06-01','2026-06-29','2026-07-31','2026-08-30'].map((date,i)=>({id:'A0'+(i+1),customer:'a',date,currency:'USD',amount:[8400,9200,10600,9800][i],type:'bulk',valid:true,batch:'a'+i,items:[{family:'发块',model:'M101',color:'#1B',length:'16 in',qty:60,unit:'pcs',amount:[5040,5520,6360,5880][i]},{family:'发块',model:'M201',color:'#613',length:'18 in',qty:40,unit:'pcs',amount:[3360,3680,4240,3920][i]}]})),
    {id:'S-B01',customer:'b',date:'2026-09-11',currency:'USD',amount:120,type:'sample',valid:true,batch:'b1',items:[{family:'发块',model:'M201',color:'#2',length:'18 in',qty:2,unit:'pcs',amount:120}]},
    {id:'C01',customer:'c',date:'2026-07-18',currency:'GBP',amount:3200,type:'bulk',valid:true,batch:'c1',items:[{family:'发束',model:'B01',color:null,length:'20 in',qty:20,unit:'bundles',amount:3200}]},
    {id:'C02',customer:'c',date:'2026-08-19',currency:'USD',amount:2400,type:'bulk',valid:true,batch:'c2',items:[{family:'发块',model:'M101',color:'#1B',length:'16 in',qty:30,unit:'pcs',amount:2400}]}
  ];
  const seed=()=>({schema:2,now:NOW,customers:structuredClone(customers),messages:structuredClone(messages),tasks:structuredClone(tasks).map(t=>({...t,issueId:t.event,attempt:1,...(t.id==='t3'?{planId:'p1',sampleId:'sample-b'}:{})})),orders:structuredClone(orders),windows:[{id:'w-a-hairpiece',customer:'a',family:'发块',anchor:'2026-08-30',from:'2026-09-22',to:'2026-10-06',state:'open',task:'t2'}],requests:{},scanCount:1,
    scans:{at:NOW,expected:6,rulesSuccess:5,rulesFailed:1,aiSuccess:3,aiSkipped:2,aiFailed:1},
    analysis:{a:{status:'ready',version:1},b:{status:'ready',version:1},c:{status:'ready',version:1},d:{status:'unbound',version:0},e:{status:'restricted',version:0},f:{status:'ready',version:1}},
    subscriptions:[{id:'sub1',customer:'a',channel:'官网',url:'https://aurelia.example/news',enabled:true,status:'active',last:'2026-09-24 07:30',baseline:true},{id:'sub2',customer:'a',channel:'Instagram',url:'https://instagram.example/aurelia',enabled:true,status:'failed',error:'来源暂不可访问',last:'2026-09-22 07:30',baseline:true}],
    events:[{id:'ev1',customer:'a',key:'a:new-store:2026-10',title:'伦敦第二家门店将于 10 月开业',old:'官网显示 1 家门店',value:'新增 Marylebone 门店，预计 10 月开业',published:'2026-09-23',found:'2026-09-24 07:30',sources:['官网 /news/new-store','Instagram 同一公告转发'],status:'pending'}],
    plans:[{id:'p1',customer:'b',type:'sample',title:'样品测试安排',date:'2026-09-24',stage:'未开始测试',task:'t3',version:1},{id:'p2',customer:'a',type:'birthday',title:'Emma 的生日问候',date:'2026-09-28',stage:'已确认适用',version:1},{id:'p3',customer:'a',type:'holiday',title:'圣诞备货沟通',date:'2026-09-30',stage:'客户确认的采购计划',version:1},{id:'p4',customer:'b',type:'shipping',title:'样品已签收 · 查看发货记录',date:'2026-09-18',stage:'已签收，未开始测试',version:1}],notifications:[],history:[]});
  root.PCWData={seed,NOW}; if(typeof module!=='undefined')module.exports=root.PCWData;
})(globalThis);
