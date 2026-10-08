/* Deterministic synthetic data. All money is generated in whole CNY.
   Never connected to a backend. Fixed demonstration date: 2026-10-08 Beijing. */
(() => {
  const DAY = 86400000;
  const END = Date.UTC(2026, 9, 8);
  const iso = day => new Date(END - day * DAY).toISOString().slice(0, 10);
  const people = ['林雨晴', '陈嘉宁', '周亦然', '许知夏', '沈思齐'];
  const names = ['青禾形象 · 杭州店','悦己美发 · 苏州店','拾光假发 · 上海店','初见美学 · 宁波店','木槿造型 · 南京店','可颂形象 · 成都店','素颜时光 · 合肥店','如初美发 · 武汉店','岚山形象 · 青岛店','简予假发 · 深圳店','沐光造型 · 杭州店','玖月形象 · 西安店','知禾美学 · 郑州店','予她假发 · 济南店','南风美发 · 长沙店','念初形象 · 厦门店','栖木假发 · 福州店','春日造型 · 广州店'];
  const cities = ['杭州','苏州','上海','宁波','南京','成都','合肥','武汉','青岛','深圳','杭州','西安','郑州','济南','长沙','厦门','福州','广州'];
  const products = [
    {id:0,type:'cap',craft:'递顶',length:'35厘米',size:'M',density:'不适用',series:'纹理',color:'自然黑',net:'绿网全头套',price:1280},
    {id:1,type:'cap',craft:'中分界',length:'40厘米',size:'L',density:'不适用',series:'直发',color:'深棕色',net:'紫网全头套',price:1490},
    {id:2,type:'cap',craft:'递旋',length:'15厘米',size:'S',density:'80%',series:'纹理',color:'自然黑',net:'红网全头套',price:780},
    {id:3,type:'cap',craft:'左分界',length:'35厘米',size:'M',density:'不适用',series:'卷发',color:'栗棕色',net:'绿网九分头',price:1380},
    {id:4,type:'piece',craft:'全递针',length:'30厘米',size:'13*15',density:'不适用',series:'不适用',color:'自然黑',net:'不适用',price:1180},
    {id:5,type:'piece',craft:'U型',length:'35厘米',size:'14*16',density:'不适用',series:'不适用',color:'深棕色',net:'不适用',price:1470},
    {id:6,type:'cap',craft:'递顶',length:'40厘米',size:'M',density:'不适用',series:'直发',color:'自然黑',net:'黑网九分头',price:1580},
    {id:7,type:'cap',craft:'递旋',length:'15厘米',size:'M',density:'90%',series:'卷发',color:'栗棕色',net:'红网全头套',price:820},
    {id:8,type:'piece',craft:'全递针',length:'40厘米',size:'15*17',density:'不适用',series:'不适用',color:'自然黑',net:'不适用',price:1890},
    {id:9,type:'cap',craft:'大U型',length:'45厘米',size:'L',density:'不适用',series:'来图卷发',color:'混色 2/4',net:'紫网全头套',price:1760},
    {id:10,type:'cap',craft:'递顶',length:'35厘米',size:'S',density:'不适用',series:'纹理',color:'深棕色',net:'绿网全头套',price:1280},
    {id:11,type:'piece',craft:'U型',length:'25厘米',size:'13*15',density:'不适用',series:'不适用',color:'栗棕色',net:'不适用',price:1060}
  ];
  const customers = names.map((name,id) => ({id,name,city:cities[id],owner:people[id%5],mode:id%5===4?'credit':'prepay',level:['黑卡','至尊','银卡'][id%3],store:id%3===0?'形象工作室':id%3===1?'综合美发店':'假发专营店',source:['老客转介绍','线下拜访','展会','微信'][id%4],initial:id%5===4?0:6000+id*400}));
  const orders=[];
  customers.forEach(c => {
    const gap=7+c.id%5;
    const stop=[3,8,13].includes(c.id)?38+c.id:2+c.id%6;
    for(let d=177-c.id%8,j=0;d>=stop;d-=gap,j++) {
      const count=1+(j+c.id)%3;
      const lines=Array.from({length:count},(_,k)=>{
        const pid=(j<8?(c.id+j+k)%12:(c.id%4===0&&k===0?0:(c.id+j+k)%12));
        const p=products[pid];
        return {...p,qty:1+((c.id*3+j+k)%4),amount:0};
      }).map(p=>({...p,amount:p.price*p.qty}));
      orders.push({id:orders.length+1,customer:c.id,day:d,date:iso(d),lines,amount:lines.reduce((a,p)=>a+p.amount,0),qty:lines.reduce((a,p)=>a+p.qty,0),channel:['微信','电话','线下拜访','展会'][j%4],category:j%9===0?'特单':'普货',status:d<9?'生产中':d<19?'已完工':'已发货'});
    }
  });
  orders.sort((a,b)=>b.day-a.day||a.id-b.id);
  const ledger=[];
  customers.forEach(c=>{
    let balance=c.initial;
    const add=(type,amount,day,order=null)=>{
      ledger.push({id:ledger.length+1,customer:c.id,type,amount,before:balance,after:balance+amount,day,date:iso(day),order});
      balance+=amount;
    };
    add('期初余额',0,181);
    orders.filter(o=>o.customer===c.id).forEach((o,i)=>{
      if(c.mode==='prepay'&&balance<o.amount+2500) add('充值入账',Math.ceil((o.amount+12000-balance)/5000)*5000,o.day);
      if(c.mode==='credit'&&i>0&&i%3===0) add('充值入账',Math.round(Math.max(0,-balance)*.9/100)*100,o.day);
      add('订单扣款',-o.amount,o.day,o.id);
    });
    c.balance=balance;
    c.lastDay=Math.min(...orders.filter(o=>o.customer===c.id).map(o=>o.day));
  });
  window.DEMO={people,products,customers,orders,ledger,iso,END,DAY};
})();
