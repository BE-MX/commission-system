import { ensureDatabase, getD1 } from "../../../db/runtime";
import { requireAdminApi } from "../../lib/admin-auth";
import { getRetailPhone } from "../../lib/retail-session";
import { getWholesaleAccount } from "../../lib/wholesale-session";
import { normalizeCart, priceCart, type OptionProduct } from "../../lib/product-options";
import { withOrderItems } from "../../lib/order-items";
export const dynamic = "force-dynamic";
export async function GET() {
  const denied = await requireAdminApi(); if (denied) return denied;
  await ensureDatabase();
  const rows = await getD1().prepare(`SELECT id,order_no AS orderNo,channel,customer_phone AS customerPhone,customer_name AS customerName,level,sales_person AS salesPerson,status,payment_status AS paymentStatus,logistics_company AS logisticsCompany,tracking_no AS trackingNo,logistics_status AS logisticsStatus,item_count AS itemCount,amount,commission_amount AS commissionAmount,created_at AS createdAt,shipped_at AS shippedAt FROM orders ORDER BY created_at DESC LIMIT 200`).all<{id:number}>();
  return Response.json({ orders: await withOrderItems(rows.results) });
}
export async function POST(request: Request) {
  const body = await request.json().catch(() => null) as { mode?:string;lines?:unknown;promoCode?:string;requestId?:string } | null;
  if (!body) return Response.json({error:"订单数据无效"},{status:400});
  const mode = body.mode === "wholesale" ? "wholesale" : "retail";
  const account = mode === "wholesale" ? await getWholesaleAccount(request.headers.get("cookie")) : null;
  const phone = mode === "retail" ? await getRetailPhone(request.headers.get("cookie")) : account?.phone;
  if (!phone) return Response.json({error:"请重新登录后下单"},{status:401});
  if (!/^[0-9a-f-]{36}$/i.test(body.requestId ?? "")) return Response.json({error:"请刷新购物车后重试"},{status:400});
  let lines;
  try { lines=normalizeCart(body.lines); } catch(error) { return Response.json({error:(error as Error).message},{status:400}); }
  if (!lines.length) return Response.json({error:"请选择商品规格后再下单"},{status:400});
  await ensureDatabase(); const db=getD1();
  const promo=String(body.promoCode ?? "").trim().toUpperCase().slice(0,64);
  const signature=JSON.stringify({lines:[...lines].sort((a,b)=>`${a.id}:${a.variantKey}`.localeCompare(`${b.id}:${b.variantKey}`)),promo});
  const hash=[...new Uint8Array(await crypto.subtle.digest("SHA-256",new TextEncoder().encode(signature)))].map((byte)=>byte.toString(16).padStart(2,"0")).join("");
  const key=`${mode}:${phone}:${body.requestId}`;
  const existing=()=>db.prepare("SELECT order_no AS orderNo,amount,status,checkout_hash AS hash FROM orders WHERE checkout_key=?").bind(key).first<{orderNo:string;amount:number;status:string;hash:string}>();
  const replay=await existing();
  if(replay) return replay.hash===hash ? Response.json({ok:true,orderNo:replay.orderNo,amount:replay.amount,status:replay.status}) : Response.json({error:"购物车已变化，请重新提交"},{status:409});
  const ids=[...new Set(lines.map((line)=>line.id))];
  const result=await db.prepare(`SELECT id,name,length,variants,stock,status,min_level AS minLevel FROM products WHERE id IN (${ids.map(()=>"?").join(",")})`).bind(...ids).all<OptionProduct>();
  let priced;
  try {priced=priceCart(result.results,lines,account?.level ?? "retail");} catch(error) {return Response.json({error:(error as Error).message},{status:409});}
  const amount=Math.round(priced.reduce((sum,line)=>sum+line.price*line.quantity,0)*100)/100;
  const count=lines.reduce((sum,line)=>sum+line.quantity,0);
  const profile=await db.prepare("SELECT display_name AS name,store_name AS storeName,sales_person AS salesPerson FROM customer_profiles WHERE phone=?").bind(phone).first<{name:string;storeName:string;salesPerson:string}>();
  const now=new Date().toISOString(),orderNo=`LS${Date.now()}${crypto.randomUUID().slice(0,8)}`,commission=Math.round(amount*3)/100;
  const commands=[db.prepare(`INSERT INTO orders
    (order_no,channel,customer_phone,customer_name,level,sales_person,status,payment_status,logistics_company,tracking_no,logistics_status,item_count,amount,commission_amount,created_at,checkout_key,checkout_hash)
    VALUES (?,?,?,?,?,?,'待发货','待确认付款','','','等待仓库发货',?,?,?,?,?,?)`)
    .bind(orderNo,mode,phone,account?.companyName ?? profile?.storeName ?? profile?.name ?? "莱莎会员",account?.level ?? "retail",account?.salesPerson ?? profile?.salesPerson ?? "未分配",count,amount,commission,now,key,hash),
    ...priced.map((line)=>db.prepare(`INSERT INTO order_items(order_id,product_id,product_name,unit_price,quantity,variant_key,variant_label)
      VALUES((SELECT id FROM orders WHERE order_no=?),?,?,?,?,?,?)`).bind(orderNo,line.id,line.product.name,line.price,line.quantity,line.variantKey,line.label))];
  if(promo) {
    const owner=await db.prepare("SELECT name FROM sales_people WHERE promo_code=? OR store_code=? LIMIT 1").bind(promo,promo).first<{name:string}>();
    commands.push(db.prepare("INSERT INTO referrals(code,owner_name,visitor_phone,order_no,amount,commission,status,created_at) VALUES(?,?,?,?,?,?,'待结算',?)").bind(promo,owner?.name ?? "客户分销",phone,orderNo,amount,commission,now));
  }
  try { await db.batch(commands); }
  catch { const concurrent=await existing(); if(concurrent?.hash===hash) return Response.json({ok:true,orderNo:concurrent.orderNo,amount:concurrent.amount,status:concurrent.status});return Response.json({error:"库存或订单信息已变化，请刷新后重试"},{status:409}); }
  return Response.json({ok:true,orderNo,amount,status:"待发货"},{status:201});
}
