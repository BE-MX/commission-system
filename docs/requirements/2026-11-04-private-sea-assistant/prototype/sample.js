// Fictional records for offline interaction only.
const today = '2026-11-04';
const clients = [
 {name:'Velvet Crown',country:'美国',code:'US',grade:'B',type:'待回复',reason:'客户在等 #60 现货与 22″ 报价',age:'14 小时前',tone:'#eee3c8',person:'Anna',source:'阿里询盘',check:'核对 #60 库存、22″ 报价与可发货日期。',plan:'先回答库存和价格，再确认店庆备货数量。',draft:'Hi Anna, thanks for waiting. For shade #60 in 22 inches, the current availability is [stock status] and the price is [price]. How many packs would you like for the anniversary?',quote:'Do you have shade #60 in stock? Also, can you send the price for 22 inches?',profile:'德州沙龙连锁，老板 Anna 决策。近期关注浅金色接发，正在为门店周年庆备货。',orders:'6 笔 · $8,420',note:'店庆在 11 月，报价前先确认色号。',since:'2025-03',risk:true},
 {name:'Aurelia Hair',country:'英国',code:'UK',grade:'A',type:'等客户回',reason:'报价已发，4 个工作日未收到回复',age:'4 个工作日前',tone:'#e6e3f0',person:'Emma',source:'展会',check:'查看最新报价版本与客户当地营业时间。',plan:'确认报价是否收到，询问还需要哪些规格。',draft:'Hi Emma, did you receive the revised quote? I can help compare lengths before you decide.',quote:'I have sent the revised quote for your review.',profile:'伦敦专业接发工作室，采购偏好自然棕色。',orders:'3 笔 · $4,120'},
 {name:'Maison Lumière',country:'法国',code:'FR',grade:'未分级',type:'新客户',reason:'最近 7 个工作日无可见接触，尚无有效订单',age:'7 个工作日前建档',since:'2026-10-26',failed:true,tone:'#dcece7',person:'Camille',source:'阿里询盘',rule:true},
 {name:'Atlas Beauty',country:'加拿大',code:'CA',grade:'B',type:'跟进到期',reason:'今天到期，确认寄样试用结果',age:'10 个工作日前',tone:'#e0e8f2',person:'Maya',source:'展会',check:'核对签收记录与上一轮寄样清单。',plan:'问清安装体验，记录客户喜欢的颜色。',draft:'Hi Maya, how did the sample fitting go? I would love to hear which shades worked best.',quote:'The sample pack arrived, thank you!',profile:'多伦多独立沙龙，正在试用浅棕渐变色样品。',orders:'1 笔 · $560'},
 {name:'Sienna Studio',country:'意大利',code:'IT',grade:'S',type:'待回复',reason:'客户询问新版色卡',age:'昨天',tone:'#f1e1de',person:'Sofia',source:'老客介绍',check:'核对最新版色卡是否可寄。',plan:'问清客户需要的色系。',draft:'Ciao Sofia, quali tonalità vuoi vedere nella nuova cartella colori?',quote:'Avete una nuova cartella colori?',profile:'米兰发型设计工作室，关注新品色卡。',orders:'8 笔 · $12,320'},
 {name:'Northline Hair',country:'美国',code:'US',grade:'未分级',type:'跟进到期',reason:'预约回访今天到期，需确认首次采购计划',age:'10-28 电话',since:'2026-10-21',person:'Taylor',overCap:true,tone:'#e7e8ea',source:'OKKI',unseen:true},
 {name:'Cedar Salon',country:'澳大利亚',code:'AU',grade:'C',type:'',reason:'授权已变更，需重新分析',age:'10-20 建档',tone:'#eadfd9',source:'展会',unseen:true,revoked:true},
 {name:'Marble & Co.',country:'爱尔兰',code:'IE',grade:'C',type:'跟进到期',reason:'色卡寄出后，约定的回访日期已到',age:'10-21 寄样',tone:'#e9e6ee',person:'Nora',source:'展会',unseen:true,ambiguous:true},
 {name:'Pearl House',country:'新西兰',code:'NZ',grade:'D',type:'',reason:'WhatsApp 仅授权 CRM 可读',age:'昨天',tone:'#e1e7f1',source:'OKKI',unseen:true,crm:true,quote:'Could you send a colour chart?'}
];
const morningSnapshot = {indices:[0,1,2,3,4], unresolvedChats:2, time:'08:40'};
const orderDetails = {0:['08-12','无在途','天才片 20″'],1:['09-16','1 单在途','自然棕色接发'],3:['09-25','无在途','浅棕样品'],4:['10-09','无在途','接发色卡']};
const chats = [{name:'Anna · 0187',contact:'Anna',mask:'+1 ••• ••• 0187',age:'昨天 18:42'},{name:'Emma · 0426',contact:'Emma',mask:'+44 •••• 0426',age:'昨天 16:30'}];
