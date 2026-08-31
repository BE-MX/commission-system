"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import type { AccessLog, CustomerProfile, LevelCode, Order, Product, SalesPerson, WholesaleAccount, WholesaleLevel } from "../lib/types";

const emptyProduct: Omit<Product, "id" | "createdAt"> = {
  name: "", material: "保鳞发", length: "15厘米", color: "自然色", retailPrice: 0,
  priceA: 0, priceB: 0, minLevel: "retail", stock: 0, status: "active", tone: "espresso", category: "安心系列", sku: "",
  construction: "递针旋", hairVolume: "常规款", parting: "", craft: "", description: "",
  highlights: [], audience: [], scenarios: [], images: [], videoUrl: "",
};
const levelName: Record<LevelCode, string> = { retail: "所有客户", a: "批发A及以上", b: "仅批发B" };

type Tab = "dashboard" | "products" | "levels" | "customers" | "orders" | "sales" | "finance" | "analytics" | "access";

export default function AdminPage() {
  const [tab, setTab] = useState<Tab>("dashboard");
  const [products, setProducts] = useState<Product[]>([]);
  const [levels, setLevels] = useState<WholesaleLevel[]>([]);
  const [accessLogs, setAccessLogs] = useState<AccessLog[]>([]);
  const [wholesaleAccounts, setWholesaleAccounts] = useState<WholesaleAccount[]>([]);
  const [orders, setOrders] = useState<Order[]>([]);
  const [customers, setCustomers] = useState<CustomerProfile[]>([]);
  const [sales, setSales] = useState<SalesPerson[]>([]);
  const [referrals, setReferrals] = useState<Array<{ id: number; code: string; ownerName: string; visitorPhone: string; orderNo: string; amount: number; commission: number; status: string; createdAt: string }>>([]);
  const [dashboard, setDashboard] = useState<{ summary?: Record<string, Record<string, number>>; daily?: Array<{ day: string; orders: number; revenue: number }> }>({});
  const [accountForm, setAccountForm] = useState({ companyName: "", phone: "", level: "a", salesPerson: "", note: "" });
  const [salesForm, setSalesForm] = useState({ name: "", phone: "", role: "销售顾问", customerService: "小莱客服" });
  const [editing, setEditing] = useState<Product | null>(null);
  const [form, setForm] = useState<Omit<Product, "id" | "createdAt">>(emptyProduct);
  const [modalOpen, setModalOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [notice, setNotice] = useState("");
  const [adminPassword, setAdminPassword] = useState("");
  const [adminAccess, setAdminAccess] = useState<"checking" | "allowed" | "denied">("checking");

  const load = async () => {
    const [p, l, a, w, o, c, s, d] = await Promise.all([
      fetch("/api/products").then((r) => r.json()), fetch("/api/levels").then((r) => r.json()),
      fetch("/api/access-logs").then((r) => r.json()), fetch("/api/wholesale-accounts").then((r) => r.json()),
      fetch("/api/orders").then((r) => r.json()), fetch("/api/customer-profiles").then((r) => r.json()),
      fetch("/api/sales-team").then((r) => r.json()), fetch("/api/dashboard").then((r) => r.json()),
    ]);
    setProducts(p.products ?? []); setLevels(l.levels ?? []); setAccessLogs(a.logs ?? []); setWholesaleAccounts(w.accounts ?? []);
    setOrders(o.orders ?? []); setCustomers(c.customers ?? []); setSales(s.sales ?? []); setReferrals(s.referrals ?? []); setDashboard(d ?? {});
  };
  useEffect(() => {
    fetch("/api/admin-auth").then(async (response) => {
      if (!response.ok) { setAdminAccess("denied"); return; }
      setAdminAccess("allowed"); await load();
    });
  }, []);

  const submitAdminLogin = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); setNotice(""); setSaving(true);
    const response = await fetch("/api/admin-auth", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ password: adminPassword }) });
    const data = await response.json();
    if (!response.ok) { setNotice(data.error ?? "登录失败"); setSaving(false); return; }
    setAdminPassword(""); setAdminAccess("allowed"); await load(); setSaving(false);
  };

  const activeCount = products.filter((item) => item.status === "active").length;
  const stockCount = products.reduce((sum, item) => sum + item.stock, 0);
  const lowStock = products.filter((item) => item.stock < 25).length;
  const levelDraft = useMemo(() => levels.map((item) => ({ ...item })), [levels]);

  const openCreate = () => { setEditing(null); setForm(emptyProduct); setModalOpen(true); };
  const openEdit = (product: Product) => {
    setEditing(product);
    const { id: _id, createdAt: _createdAt, ...values } = product;
    setForm(values); setModalOpen(true);
  };
  const updateForm = (key: keyof typeof form, value: string | number) => setForm((current) => ({ ...current, [key]: value }));

  const uploadFiles = async (files: FileList | null, kind: "images" | "video") => {
    if (!files?.length) return;
    setUploading(true); setNotice("");
    try {
      const urls: string[] = [];
      for (const file of Array.from(files)) {
        const payload = new FormData(); payload.append("file", file);
        const response = await fetch("/api/uploads", { method: "POST", body: payload });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error ?? "素材上传失败");
        urls.push(data.url);
      }
      setForm((current) => kind === "images" ? { ...current, images: [...current.images, ...urls].slice(0, 8) } : { ...current, videoUrl: urls[0] });
      setNotice(kind === "images" ? `已上传${urls.length}张图片` : "视频已上传");
    } catch (error) { setNotice(error instanceof Error ? error.message : "素材上传失败"); }
    setUploading(false);
  };

  const saveProduct = async (event: FormEvent) => {
    event.preventDefault(); setSaving(true); setNotice("");
    const response = await fetch(editing ? `/api/products/${editing.id}` : "/api/products", {
      method: editing ? "PUT" : "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(form),
    });
    const data = await response.json();
    if (!response.ok) setNotice(data.error ?? "保存失败，请重试");
    else { setModalOpen(false); setNotice(editing ? "款式信息已更新" : "新款式已添加"); await load(); }
    setSaving(false);
  };

  const toggleStatus = async (product: Product) => {
    await fetch(`/api/products/${product.id}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...product, status: product.status === "active" ? "draft" : "active" }) });
    setNotice(product.status === "active" ? "商品已下架" : "商品已上架"); await load();
  };

  const saveLevels = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const formData = new FormData(event.currentTarget);
    const payload = levelDraft.map((level) => ({ ...level, name: String(formData.get(`${level.code}-name`) ?? level.name), threshold: Number(formData.get(`${level.code}-threshold`) ?? level.threshold) }));
    await fetch("/api/levels", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ levels: payload }) });
    setNotice("批发等级要求已保存"); await load();
  };

  const addWholesaleAccount = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); setNotice("");
    const response = await fetch("/api/wholesale-accounts", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(accountForm) });
    const data = await response.json();
    if (!response.ok) return setNotice(data.error ?? "添加失败");
    setAccountForm({ companyName: "", phone: "", level: "a", salesPerson: "", note: "" });
    setNotice("批发商手机号账户已添加，可以进行验证登录"); await load();
  };

  const updateCustomer = async (customer: CustomerProfile, patch: Partial<CustomerProfile>) => {
    const next = { ...customer, ...patch };
    const response = await fetch(`/api/customer-profiles/${customer.id}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(next) });
    if (!response.ok) return setNotice("客户资料修改失败");
    setNotice("客户身份、店面和备注已更新"); await load();
  };

  const shipOrder = async (order: Order) => {
    const trackingNo = window.prompt("请输入物流单号", order.trackingNo || `SF${Date.now()}`);
    if (!trackingNo) return;
    const logisticsCompany = window.prompt("请输入物流公司", order.logisticsCompany || "顺丰速运") || "顺丰速运";
    await fetch(`/api/orders/${order.id}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status: "已发货", logisticsCompany, trackingNo, logisticsStatus: "快件已揽收，等待运输" }) });
    setNotice("订单已发货，客户现在可以查看物流轨迹"); await load();
  };

  const addSalesPerson = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const response = await fetch("/api/sales-team", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(salesForm) });
    const data = await response.json();
    if (!response.ok) return setNotice(data.error ?? "添加销售失败");
    setSalesForm({ name: "", phone: "", role: "销售顾问", customerService: "小莱客服" });
    setNotice("销售员已添加，推广码与店面宣传码已自动生成"); await load();
  };

  if (adminAccess === "checking") return <main className="admin-access-state"><div><span>莱</span><h1>正在验证管理员身份</h1><p>请稍候…</p></div></main>;
  if (adminAccess === "denied") return <main className="admin-access-state"><div><span>锁</span><h1>莱莎经营后台</h1><p>请输入后台管理密码后继续。</p><form onSubmit={submitAdminLogin}><input type="password" value={adminPassword} onChange={(event) => setAdminPassword(event.target.value)} placeholder="后台管理密码" autoComplete="current-password" required />{notice && <div className="login-message">{notice}</div>}<button type="submit" disabled={saving}>{saving ? "正在登录…" : "进入管理后台"}</button></form><a href="/">返回前台</a></div></main>;

  return (
    <div className="admin-shell">
      <aside className="admin-sidebar">
        <a className="brand admin-brand" href="/"><span className="brand-mark">莱</span><span>莱莎管理台</span></a>
        <div className="admin-menu-label">经营管理</div>
        <button className={tab === "dashboard" ? "selected" : ""} onClick={() => setTab("dashboard")}><span>总</span>经营总览</button>
        <button className={tab === "products" ? "selected" : ""} onClick={() => setTab("products")}><span>款</span>商品与款式</button>
        <button className={tab === "levels" ? "selected" : ""} onClick={() => setTab("levels")}><span>级</span>批发等级</button>
        <button className={tab === "customers" ? "selected" : ""} onClick={() => setTab("customers")}><span>客</span>批发商账户</button>
        <button className={tab === "orders" ? "selected" : ""} onClick={() => setTab("orders")}><span>单</span>订单与发货 <i>{orders.filter((item) => item.status === "待发货").length || ""}</i></button>
        <button className={tab === "sales" ? "selected" : ""} onClick={() => setTab("sales")}><span>销</span>销售与推广</button>
        <button className={tab === "finance" ? "selected" : ""} onClick={() => setTab("finance")}><span>财</span>财务与佣金</button>
        <button className={tab === "analytics" ? "selected" : ""} onClick={() => setTab("analytics")}><span>数</span>运营数据</button>
        <button className={tab === "access" ? "selected" : ""} onClick={() => setTab("access")}><span>访</span>进入记录 <i>{accessLogs.length || ""}</i></button>
        <a className="back-store" href="/">← 返回店铺访问端</a>
      </aside>

      <main className="admin-main">
        <header className="admin-top"><div><small>山东自营仓 · 演示环境</small><strong>管理员</strong></div><span className="admin-avatar">管</span></header>
        {notice && <div className="notice" role="status">{notice}<button onClick={() => setNotice("")}>×</button></div>}

        {tab === "dashboard" && <>
          <div className="admin-title"><div><p>经营总览</p><h1>零售、批发与分销一体化后台</h1><span>价格、客户、订单、物流、销售归属和财务数据集中管理</span></div><button className="admin-primary" onClick={load}>刷新数据</button></div>
          <section className="stat-grid dashboard-stats">
            <article><span>累计销售额</span><strong>¥{Number(dashboard.summary?.orders?.revenue ?? 0).toLocaleString()}</strong><small>{dashboard.summary?.orders?.count ?? 0} 笔订单</small></article>
            <article><span>有效客户</span><strong>{dashboard.summary?.customers?.count ?? customers.length}</strong><small>批发客户 {dashboard.summary?.customers?.wholesale ?? 0}</small></article>
            <article><span>待发货订单</span><strong>{orders.filter((item) => item.status === "待发货").length}</strong><small>请及时录入物流</small></article>
            <article><span>库存预警</span><strong>{dashboard.summary?.products?.lowStock ?? lowStock}</strong><small>总库存 {dashboard.summary?.products?.stock ?? stockCount} 件</small></article>
          </section>
          <div className="dashboard-layout">
            <section className="admin-panel dashboard-orders"><div className="panel-head"><div><strong>最新订单</strong><span>零售与批发订单统一显示</span></div><button className="text-action" onClick={() => setTab("orders")}>查看全部</button></div>{orders.slice(0, 5).map((order) => <article key={order.id}><div><b>{order.customerName}</b><span>{order.orderNo} · {order.itemCount}件</span></div><strong>¥{order.amount.toLocaleString()}</strong><i className={order.status === "待发货" ? "pending" : ""}>{order.status}</i></article>)}</section>
            <section className="admin-panel operations-card"><div className="panel-head"><div><strong>今日运营重点</strong><span>按当前经营数据自动汇总</span></div></div><ul><li><b>{orders.filter((item) => item.status === "待发货").length}</b><span>笔订单等待仓库发货</span></li><li><b>{lowStock}</b><span>款商品库存低于25件</span></li><li><b>{referrals.filter((item) => item.status === "待结算").length}</b><span>笔推广佣金等待结算</span></li><li><b>{accessLogs.filter((item) => item.result === "success").length}</b><span>个账户最近成功进入商城</span></li></ul></section>
          </div>
        </>}

        {tab === "products" && <>
          <div className="admin-title"><div><p>商品中心</p><h1>假发款式与价格</h1><span>管理款式、不同等级价格和查看权限</span></div><button className="admin-primary" onClick={openCreate}>＋ 添加假发款式</button></div>
          <section className="stat-grid">
            <article><span>商品款式</span><strong>{products.length}</strong><small>已上架 {activeCount} 款</small></article>
            <article><span>总库存</span><strong>{stockCount}</strong><small>山东仓现有件数</small></article>
            <article><span>低库存</span><strong>{lowStock}</strong><small>库存少于 25 件</small></article>
            <article><span>批发专属</span><strong>{products.filter((p) => p.minLevel !== "retail").length}</strong><small>限制等级查看</small></article>
          </section>
          <section className="admin-panel">
            <div className="panel-head"><div><strong>全部商品</strong><span>价格修改后只影响新订单</span></div><label className="admin-search">⌕ <input aria-label="搜索商品" placeholder="搜索款式（演示）" /></label></div>
            <div className="product-table-wrap"><table className="product-table"><thead><tr><th>款式</th><th>分类</th><th>零售价</th><th>批发A</th><th>批发B</th><th>查看权限</th><th>库存</th><th>状态</th><th>操作</th></tr></thead><tbody>
              {products.map((product) => <tr key={product.id}>
                <td><div className={`table-art ${product.tone}`}>{product.images[0] ? <img src={product.images[0]} alt="" /> : <div className="tiny-hair" />}</div><div><strong>{product.name}</strong><small>{product.sku || "未设置货号"} · {product.material} · {product.length} · {product.color}</small></div></td>
                <td>{product.category}</td><td>¥{product.retailPrice}</td><td>¥{product.priceA}</td><td>¥{product.priceB}</td>
                <td><span className={`access-pill ${product.minLevel}`}>{levelName[product.minLevel]}</span></td><td className={product.stock < 25 ? "stock-low" : ""}>{product.stock} 件</td>
                <td><button className={`status-toggle ${product.status}`} onClick={() => toggleStatus(product)}><i />{product.status === "active" ? "已上架" : "已下架"}</button></td>
                <td><button className="text-action" onClick={() => openEdit(product)}>编辑</button></td>
              </tr>)}</tbody></table></div>
          </section>
        </>}

        {tab === "levels" && <>
          <div className="admin-title"><div><p>会员体系</p><h1>批发等级要求</h1><span>客户累计净采购额达到门槛后自动升级</span></div></div>
          <form className="admin-panel level-editor" onSubmit={saveLevels}>
            <div className="level-rule"><strong>升级计算规则</strong><p>只统计已完成订单，取消订单不计入；退款金额自动从累计采购额中扣除；升级后的价格从下一笔订单生效。</p></div>
            <div className="editable-level-grid">{levels.map((level, index) => <article key={level.code}>
              <span className="level-index">等级 0{index + 1}</span><label>等级名称<input name={`${level.code}-name`} defaultValue={level.name} /></label>
              <label>累计净采购门槛<div className="money-input"><span>¥</span><input name={`${level.code}-threshold`} type="number" min="0" defaultValue={level.threshold} disabled={level.code === "retail"} /></div></label>
              <small>{level.code === "retail" ? "新注册客户默认等级" : `达到门槛后解锁${level.name}价格和限定商品`}</small>
            </article>)}</div>
            <div className="form-footer"><span>门槛金额后续可以随时调整</span><button className="admin-primary" type="submit">保存等级设置</button></div>
          </form>
        </>}

        {tab === "customers" && <>
          <div className="admin-title"><div><p>客户管理</p><h1>批发商手机号账户</h1><span>只有后台已添加的手机号，验证后才可进入批发商城</span></div></div>
          <form className="admin-panel account-create" onSubmit={addWholesaleAccount}><div className="panel-head"><div><strong>添加批发商账户</strong><span>建立账户时指定批发等级和来源销售员</span></div><button className="admin-primary">＋ 添加账户</button></div><div className="account-create-grid"><label>批发商/门店名称<input required value={accountForm.companyName} onChange={(e) => setAccountForm({ ...accountForm, companyName: e.target.value })} placeholder="例如：青岛尚美发制品" /></label><label>登录手机号<input required value={accountForm.phone} onChange={(e) => setAccountForm({ ...accountForm, phone: e.target.value.replace(/\D/g, "").slice(0, 11) })} placeholder="11位手机号" /></label><label>账户等级<select value={accountForm.level} onChange={(e) => setAccountForm({ ...accountForm, level: e.target.value })}><option value="a">批发A</option><option value="b">批发B</option></select></label><label>来源销售员<input value={accountForm.salesPerson} onChange={(e) => setAccountForm({ ...accountForm, salesPerson: e.target.value })} placeholder="业务员姓名" /></label><label>备注<input value={accountForm.note} onChange={(e) => setAccountForm({ ...accountForm, note: e.target.value })} placeholder="客户备注" /></label></div></form>
          <section className="admin-panel account-list-panel"><div className="panel-head"><div><strong>已开通批发商账户</strong><span>共 {wholesaleAccounts.length} 个手机号账户</span></div></div>
            <div className="product-table-wrap"><table className="product-table customer-table"><thead><tr><th>批发商</th><th>登录手机号</th><th>当前等级</th><th>来源销售员</th><th>备注</th></tr></thead><tbody>
              {wholesaleAccounts.map((account) => <tr key={account.id}><td><strong>{account.companyName}</strong></td><td>{account.phone}</td><td><span className={`access-pill ${account.level}`}>批发{account.level.toUpperCase()}</span></td><td>{account.salesPerson}</td><td>{account.note || "—"}</td></tr>)}
            </tbody></table></div>
          </section>
          <section className="admin-panel customer-control"><div className="panel-head"><div><strong>客户权限与店面资料</strong><span>可修改等级、店面名称、来源销售、客服和后台备注</span></div></div>
            <div className="customer-card-grid">{customers.map((customer) => <article key={customer.id}><header><div><small>{customer.channel === "wholesale" ? "批发账户" : "零售账户"}</small><strong>{customer.storeName || customer.displayName}</strong><span>{customer.phone}</span></div><select value={customer.level} onChange={(e) => updateCustomer(customer, { level: e.target.value as LevelCode })}><option value="retail">零售</option><option value="a">批发A</option><option value="b">批发B</option></select></header><div className="customer-fields"><label>店面名称<input defaultValue={customer.storeName} onBlur={(e) => e.target.value !== customer.storeName && updateCustomer(customer, { storeName: e.target.value })} /></label><label>来源销售员<input defaultValue={customer.salesPerson} onBlur={(e) => e.target.value !== customer.salesPerson && updateCustomer(customer, { salesPerson: e.target.value })} /></label><label>专属客服<input defaultValue={customer.customerService} onBlur={(e) => e.target.value !== customer.customerService && updateCustomer(customer, { customerService: e.target.value })} /></label><label>后台备注<input defaultValue={customer.note} onBlur={(e) => e.target.value !== customer.note && updateCustomer(customer, { note: e.target.value })} /></label></div><footer><span>推广码 {customer.referralCode}</span><button onClick={() => updateCustomer(customer, { status: customer.status === "active" ? "disabled" : "active" })}>{customer.status === "active" ? "停用账户" : "启用账户"}</button></footer></article>)}</div>
          </section>
        </>}

        {tab === "orders" && <>
          <div className="admin-title"><div><p>订单履约</p><h1>订单、发货与物流</h1><span>客户提交订单后，仓库可录入物流公司和单号</span></div><button className="admin-primary" onClick={load}>刷新订单</button></div>
          <section className="stat-grid"><article><span>全部订单</span><strong>{orders.length}</strong><small>零售与批发合计</small></article><article><span>待发货</span><strong>{orders.filter((item) => item.status === "待发货").length}</strong><small>仓库待处理</small></article><article><span>运输中</span><strong>{orders.filter((item) => ["已发货", "运输中"].includes(item.status)).length}</strong><small>客户可查轨迹</small></article><article><span>商品数量</span><strong>{orders.reduce((sum, item) => sum + item.itemCount, 0)}</strong><small>订单总件数</small></article></section>
          <section className="admin-panel"><div className="panel-head"><div><strong>全部订单</strong><span>发货后客户个人中心即时显示物流信息</span></div></div><div className="product-table-wrap"><table className="product-table order-table"><thead><tr><th>订单/客户</th><th>类型</th><th>商品</th><th>金额</th><th>销售归属</th><th>物流</th><th>状态</th><th>操作</th></tr></thead><tbody>{orders.map((order) => <tr key={order.id}><td><strong>{order.orderNo}</strong><small>{order.customerName} · {order.customerPhone}</small></td><td><span className={`channel-pill ${order.channel}`}>{order.channel === "retail" ? "零售" : `批发${order.level.toUpperCase()}`}</span></td><td>{order.itemCount} 件</td><td>¥{order.amount.toLocaleString()}</td><td>{order.salesPerson}</td><td><strong>{order.logisticsCompany || "待录入"}</strong><small>{order.trackingNo || order.logisticsStatus}</small></td><td><span className={`order-status ${order.status === "待发货" ? "pending" : "shipped"}`}>{order.status}</span></td><td><button className="text-action" onClick={() => shipOrder(order)}>{order.trackingNo ? "更新物流" : "立即发货"}</button></td></tr>)}</tbody></table></div></section>
        </>}

        {tab === "sales" && <>
          <div className="admin-title"><div><p>渠道增长</p><h1>销售员、推广码与店面宣传码</h1><span>为每位销售自动生成唯一推广归属</span></div></div>
          <form className="admin-panel sales-create" onSubmit={addSalesPerson}><div className="panel-head"><div><strong>添加销售员</strong><span>系统自动生成销售推广码和店面宣传码</span></div><button className="admin-primary">生成推广身份</button></div><div className="account-create-grid"><label>销售姓名<input required value={salesForm.name} onChange={(e) => setSalesForm({ ...salesForm, name: e.target.value })} /></label><label>手机号<input required value={salesForm.phone} onChange={(e) => setSalesForm({ ...salesForm, phone: e.target.value.replace(/\D/g, "").slice(0, 11) })} /></label><label>岗位<input value={salesForm.role} onChange={(e) => setSalesForm({ ...salesForm, role: e.target.value })} /></label><label>配合客服<input value={salesForm.customerService} onChange={(e) => setSalesForm({ ...salesForm, customerService: e.target.value })} /></label></div></form>
          <div className="sales-card-grid">{sales.map((person) => <article key={person.id}><header><span>{person.name.slice(0, 1)}</span><div><strong>{person.name}</strong><small>{person.role} · {person.phone}</small></div></header><dl><div><dt>销售推广码</dt><dd>{person.promoCode}</dd></div><div><dt>店面宣传码</dt><dd>{person.storeCode}</dd></div></dl><footer><span>客户 {person.customerCount ?? 0} 人</span><b>成交 ¥{Number(person.orderAmount ?? 0).toLocaleString()}</b></footer></article>)}</div>
          <section className="admin-panel"><div className="panel-head"><div><strong>推广成交记录</strong><span>追踪推广码、订单和佣金归属</span></div></div><div className="product-table-wrap"><table className="product-table"><thead><tr><th>时间</th><th>推广码</th><th>归属人员</th><th>客户</th><th>订单</th><th>成交金额</th><th>佣金</th><th>状态</th></tr></thead><tbody>{referrals.length ? referrals.map((item) => <tr key={item.id}><td>{new Date(item.createdAt).toLocaleDateString("zh-CN")}</td><td><strong>{item.code}</strong></td><td>{item.ownerName}</td><td>{item.visitorPhone}</td><td>{item.orderNo}</td><td>¥{item.amount}</td><td>¥{item.commission}</td><td>{item.status}</td></tr>) : <tr><td colSpan={8} className="empty-records">暂无推广成交记录</td></tr>}</tbody></table></div></section>
        </>}

        {tab === "finance" && <>
          <div className="admin-title"><div><p>财务中心</p><h1>收入、佣金与结算</h1><span>按订单和销售推广归属核对经营账目</span></div></div>
          <section className="stat-grid finance-stats"><article><span>订单收入</span><strong>¥{orders.reduce((sum, item) => sum + item.amount, 0).toLocaleString()}</strong><small>已支付订单</small></article><article><span>待结算佣金</span><strong>¥{referrals.filter((item) => item.status === "待结算").reduce((sum, item) => sum + item.commission, 0).toLocaleString()}</strong><small>{referrals.filter((item) => item.status === "待结算").length} 笔推广</small></article><article><span>销售绩效佣金</span><strong>¥{orders.reduce((sum, item) => sum + item.commissionAmount, 0).toLocaleString()}</strong><small>按3%演示计算</small></article><article><span>客单价</span><strong>¥{orders.length ? Math.round(orders.reduce((sum, item) => sum + item.amount, 0) / orders.length).toLocaleString() : 0}</strong><small>零售批发综合</small></article></section>
          <section className="admin-panel"><div className="panel-head"><div><strong>订单财务明细</strong><span>每笔订单保留成交价格，不受后续改价影响</span></div></div><div className="product-table-wrap"><table className="product-table"><thead><tr><th>订单号</th><th>客户</th><th>付款状态</th><th>订单金额</th><th>来源销售</th><th>销售绩效</th><th>订单状态</th></tr></thead><tbody>{orders.map((order) => <tr key={order.id}><td><strong>{order.orderNo}</strong></td><td>{order.customerName}</td><td>{order.paymentStatus}</td><td>¥{order.amount.toLocaleString()}</td><td>{order.salesPerson}</td><td>¥{order.commissionAmount}</td><td>{order.status}</td></tr>)}</tbody></table></div></section>
        </>}

        {tab === "analytics" && <>
          <div className="admin-title"><div><p>运营分析</p><h1>销量、客户与渠道数据</h1><span>查看不同身份、产品库存和销售推广表现</span></div></div>
          <section className="analytics-grid"><article className="admin-panel"><div className="panel-head"><div><strong>近期开单趋势</strong><span>订单金额按日期汇总</span></div></div><div className="bar-chart">{(dashboard.daily ?? []).map((item) => { const max = Math.max(...(dashboard.daily ?? []).map((day) => Number(day.revenue)), 1); return <div key={item.day}><span style={{ height: `${Math.max(12, Number(item.revenue) / max * 100)}%` }}><b>¥{Number(item.revenue).toLocaleString()}</b></span><small>{item.day.slice(5)}</small></div>; })}</div></article><article className="admin-panel channel-breakdown"><div className="panel-head"><div><strong>客户结构</strong><span>按账户身份统计</span></div></div><div className="donut-wrap"><div className="donut"><strong>{customers.length}</strong><span>客户总数</span></div><ul><li><i className="retail-dot" />零售客户 <b>{customers.filter((item) => item.channel === "retail").length}</b></li><li><i className="a-dot" />批发A <b>{customers.filter((item) => item.level === "a").length}</b></li><li><i className="b-dot" />批发B <b>{customers.filter((item) => item.level === "b").length}</b></li></ul></div></article></section>
          <section className="admin-panel"><div className="panel-head"><div><strong>商品经营情况</strong><span>实时库存、价格和销售权限</span></div></div><div className="product-table-wrap"><table className="product-table"><thead><tr><th>款式</th><th>分类</th><th>库存</th><th>零售价</th><th>批发A</th><th>批发B</th><th>可见等级</th><th>状态</th></tr></thead><tbody>{products.map((item) => <tr key={item.id}><td><strong>{item.name}</strong><small>{item.sku || "未设置货号"}</small></td><td>{item.category}</td><td className={item.stock < 25 ? "stock-low" : ""}>{item.stock}</td><td>¥{item.retailPrice}</td><td>¥{item.priceA}</td><td>¥{item.priceB}</td><td>{levelName[item.minLevel]}</td><td>{item.status === "active" ? "已上架" : "已下架"}</td></tr>)}</tbody></table></div></section>
        </>}

        {tab === "access" && <>
          <div className="admin-title"><div><p>安全记录</p><h1>商城登录与进入记录</h1><span>分别记录零售登录和批发商账户验证结果</span></div><button className="admin-primary" onClick={load}>刷新记录</button></div>
          <section className="stat-grid access-stats">
            <article><span>全部验证</span><strong>{accessLogs.length}</strong><small>最近100条记录</small></article>
            <article><span>零售登录</span><strong>{accessLogs.filter((item) => item.channel === "retail" && item.result === "success").length}</strong><small>手机号验证通过</small></article>
            <article><span>批发进入</span><strong>{accessLogs.filter((item) => item.channel === "wholesale" && item.result === "success").length}</strong><small>后台登记账户</small></article>
            <article><span>验证码失败</span><strong>{accessLogs.filter((item) => item.result === "failed").length}</strong><small>验证码不正确</small></article>
          </section>
          <section className="admin-panel"><div className="panel-head"><div><strong>手机号验证记录</strong><span>新记录按时间倒序显示</span></div></div>
            <div className="product-table-wrap"><table className="product-table access-table"><thead><tr><th>进入时间</th><th>商城类型</th><th>手机号码</th><th>客户/批发商</th><th>账户等级</th><th>来源销售员</th><th>验证结果</th></tr></thead><tbody>
              {accessLogs.length ? accessLogs.map((log) => <tr key={`${log.channel}-${log.id}`}><td>{new Date(log.accessAt).toLocaleString("zh-CN", { hour12: false })}</td><td><span className={`channel-pill ${log.channel}`}>{log.channel === "retail" ? "零售商城" : "批发商城"}</span></td><td>{log.phone}</td><td>{log.channel === "retail" ? "零售客户" : log.companyName ?? "未登记账户"}</td><td>{log.level ? <span className={`access-pill ${log.level}`}>批发{log.level.toUpperCase()}</span> : "—"}</td><td>{log.salesPerson ?? "—"}</td><td><span className={`verify-result ${log.result}`}>{log.result === "success" ? "验证成功" : log.result === "failed" ? "验证码错误" : "未登记号码"}</span></td></tr>) : <tr><td colSpan={7} className="empty-records">暂无登录记录</td></tr>}
            </tbody></table></div>
          </section>
        </>}
      </main>

      {modalOpen && <div className="modal-backdrop" onMouseDown={() => setModalOpen(false)}>
        <form className="product-modal" onSubmit={saveProduct} onMouseDown={(event) => event.stopPropagation()}>
          <div className="modal-head"><div><small>{editing ? "编辑商品" : "新增商品"}</small><h2>{editing ? editing.name : "添加假发款式"}</h2></div><button type="button" onClick={() => setModalOpen(false)} aria-label="关闭">×</button></div>
          <div className="form-grid">
            <label className="wide">款式名称<input required value={form.name} onChange={(e) => updateForm("name", e.target.value)} placeholder="例如：自然头皮直发" /></label>
            <label>货号 SKU<input value={form.sku} onChange={(e) => updateForm("sku", e.target.value)} placeholder="例如：LS-016" /></label>
            <label>产品分类<select value={form.category} onChange={(e) => updateForm("category", e.target.value)}><option>安心系列</option><option>气质系列</option><option>高光系列</option><option>臻藏系列</option></select></label>
            <label>材质<input value={form.material} onChange={(e) => updateForm("material", e.target.value)} placeholder="例如：保鳞发" /></label>
            <label>长度<input value={form.length} onChange={(e) => updateForm("length", e.target.value)} placeholder="45cm" /></label>
            <label>颜色<input value={form.color} onChange={(e) => updateForm("color", e.target.value)} placeholder="自然黑" /></label>
            <label>库存数量<input type="number" min="0" value={form.stock} onChange={(e) => updateForm("stock", Number(e.target.value))} /></label>
            <label>零售价（元）<input type="number" min="0" required value={form.retailPrice} onChange={(e) => updateForm("retailPrice", Number(e.target.value))} /></label>
            <label>批发A价（元）<input type="number" min="0" required value={form.priceA} onChange={(e) => updateForm("priceA", Number(e.target.value))} /></label>
            <label>批发B价（元）<input type="number" min="0" required value={form.priceB} onChange={(e) => updateForm("priceB", Number(e.target.value))} /></label>
            <label>展示色调<select value={form.tone} onChange={(e) => updateForm("tone", e.target.value)}><option value="espresso">自然黑</option><option value="honey">蜜茶棕</option><option value="chestnut">栗棕色</option><option value="charcoal">灰黑色</option></select></label>
            <label>发网结构<input value={form.construction} onChange={(e) => updateForm("construction", e.target.value)} placeholder="递针顶 / 递针旋" /></label>
            <label>发量要求<input value={form.hairVolume} onChange={(e) => updateForm("hairVolume", e.target.value)} placeholder="常规款 / 轻薄款" /></label>
            <label className="wide">分缝方式<input value={form.parting} onChange={(e) => updateForm("parting", e.target.value)} placeholder="例如：左分，可调整中分/侧分" /></label>
            <label className="wide">产品简介<textarea value={form.description} onChange={(e) => updateForm("description", e.target.value)} placeholder="介绍整体轮廓、风格与佩戴感受" /></label>
            <label className="wide">工艺特点<textarea value={form.craft} onChange={(e) => updateForm("craft", e.target.value)} placeholder="介绍发网与制作工艺" /></label>
            <label className="wide">核心卖点<textarea value={form.highlights.join("；")} onChange={(e) => setForm({ ...form, highlights: e.target.value.split(/[；;\n]+/).map((item) => item.trim()).filter(Boolean) })} placeholder="每条卖点用分号隔开" /></label>
            <label className="wide">适用人群<textarea value={form.audience.join("；")} onChange={(e) => setForm({ ...form, audience: e.target.value.split(/[；;\n]+/).map((item) => item.trim()).filter(Boolean) })} placeholder="每类人群用分号隔开" /></label>
            <label className="wide">适用场景<input value={form.scenarios.join("；")} onChange={(e) => setForm({ ...form, scenarios: e.target.value.split(/[；;\n]+/).map((item) => item.trim()).filter(Boolean) })} placeholder="通勤；聚会；旅行" /></label>
            <div className="wide media-upload-box"><div><strong>产品实拍图片</strong><span>最多8张，第一张作为封面；也可以粘贴已公开的图片网址</span></div><label className="upload-button">{uploading ? "上传中…" : "选择图片"}<input type="file" accept="image/jpeg,image/png,image/webp" multiple disabled={uploading} onChange={(e) => uploadFiles(e.target.files, "images")} /></label><input className="media-url-input" placeholder="粘贴图片网址后按回车添加" onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); const url = event.currentTarget.value.trim(); if (url) { setForm({ ...form, images: [...form.images, url].slice(0, 8) }); event.currentTarget.value = ""; } } }} />{form.images.length > 0 && <div className="upload-preview">{form.images.map((url, index) => <span key={url}><img src={url} alt={`产品图${index + 1}`} /><button type="button" onClick={() => setForm({ ...form, images: form.images.filter((item) => item !== url) })}>×</button></span>)}</div>}</div>
            <div className="wide media-upload-box"><div><strong>产品视频</strong><span>支持MP4或MOV，单个不超过20MB；也可以粘贴已公开的视频网址</span></div><label className="upload-button">{uploading ? "上传中…" : "选择视频"}<input type="file" accept="video/mp4,video/quicktime" disabled={uploading} onChange={(e) => uploadFiles(e.target.files, "video")} /></label><input className="media-url-input" value={form.videoUrl} onChange={(event) => setForm({ ...form, videoUrl: event.target.value })} placeholder="视频网址（https://…）" />{form.videoUrl && <div className="uploaded-video"><span>视频已就绪</span><button type="button" onClick={() => setForm({ ...form, videoUrl: "" })}>移除</button></div>}</div>
            <label className="wide">最低查看等级<select value={form.minLevel} onChange={(e) => updateForm("minLevel", e.target.value)}><option value="retail">所有客户可见</option><option value="a">批发A及以上可见</option><option value="b">仅批发B可见</option></select><small>低于该等级的客户只能看到“批发专属款式”，无法看到名称和价格。</small></label>
          </div>
          {notice && <p className="form-error">{notice}</p>}
          <div className="modal-actions"><button type="button" className="cancel" onClick={() => setModalOpen(false)}>取消</button><button className="admin-primary" disabled={saving}>{saving ? "保存中…" : "保存款式"}</button></div>
        </form>
      </div>}
    </div>
  );
}
