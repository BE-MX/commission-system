"use client";

import { useEffect, useMemo, useState } from "react";
import type { CustomerProfile, LevelCode, Order, Product, Promotion, SalesPerson, WholesaleAccount, WholesaleLevel } from "./lib/types";

type Mode = "retail" | "wholesale";
type View = "home" | "category" | "marketing" | "cart" | "profile";
type CartLine = { id: number; quantity: number };
type CenterData = {
  profile?: CustomerProfile;
  orders: Order[];
  promotions: Promotion[];
  salesperson?: SalesPerson;
  distributor: { eligible: boolean; referralCode: string; commissionRate: number };
};

const rank: Record<LevelCode, number> = { retail: 0, a: 1, b: 2 };

export default function ShopApp({ mode, view, account, retailPhone }: { mode: Mode; view: View; account?: WholesaleAccount; retailPhone?: string }) {
  const level: LevelCode = mode === "wholesale" ? account?.level ?? "a" : "retail";
  const [products, setProducts] = useState<Product[]>([]);
  const [levels, setLevels] = useState<WholesaleLevel[]>([]);
  const [center, setCenter] = useState<CenterData>({ orders: [], promotions: [], distributor: { eligible: false, referralCode: "", commissionRate: 3 } });
  const [cart, setCart] = useState<CartLine[]>([]);
  const [notice, setNotice] = useState("");
  const [promoCode, setPromoCode] = useState("");
  const [checkingOut, setCheckingOut] = useState(false);
  const [selectedProduct, setSelectedProduct] = useState<Product | null>(null);
  const prefix = mode === "retail" ? "/retail" : "/wholesale";

  const loadCenter = () => fetch(`/api/customer-center?mode=${mode}`).then((r) => r.json()).then((data) => {
    if (!data.error) setCenter(data);
  });

  useEffect(() => {
    const savedCart = window.localStorage.getItem(`leshine-cart-${mode}`);
    if (savedCart) {
      try { setCart(JSON.parse(savedCart)); } catch { setCart([]); }
    }
    Promise.all([
      fetch("/api/products").then((r) => r.json()),
      fetch("/api/levels").then((r) => r.json()),
      fetch(`/api/customer-center?mode=${mode}`).then((r) => r.json()),
    ]).then(([productData, levelData, centerData]) => {
      setProducts(productData.products ?? []);
      setLevels(levelData.levels ?? []);
      if (!centerData.error) setCenter(centerData);
    });
  }, [mode]);

  const allowedProducts = useMemo(() => products.filter((p) => p.status === "active" && rank[level] >= rank[p.minLevel]), [products, level]);
  const getPrice = (p: Product) => mode === "retail" ? p.retailPrice : level === "b" ? p.priceB : p.priceA;
  const saveCart = (next: CartLine[]) => {
    setCart(next);
    window.localStorage.setItem(`leshine-cart-${mode}`, JSON.stringify(next));
  };
  const addCart = (id: number) => {
    const next = cart.some((line) => line.id === id) ? cart.map((line) => line.id === id ? { ...line, quantity: line.quantity + 1 } : line) : [...cart, { id, quantity: 1 }];
    saveCart(next);
    setNotice("已加入购物车");
  };
  const updateQuantity = (id: number, delta: number) => saveCart(cart.map((line) => line.id === id ? { ...line, quantity: Math.max(0, line.quantity + delta) } : line).filter((line) => line.quantity > 0));
  const cartProducts = cart.map((line) => ({ line, product: products.find((p) => p.id === line.id) })).filter((item): item is { line: CartLine; product: Product } => Boolean(item.product));
  const cartTotal = cartProducts.reduce((sum, item) => sum + getPrice(item.product) * item.line.quantity, 0);
  const logout = async () => {
    await fetch(mode === "wholesale" ? "/api/wholesale-auth" : "/api/retail-auth", { method: "DELETE" });
    window.location.href = mode === "wholesale" ? "/wholesale/login" : "/retail/login";
  };
  const checkout = async () => {
    setCheckingOut(true);
    const response = await fetch("/api/orders", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ mode, lines: cart, promoCode }) });
    const data = await response.json();
    if (!response.ok) setNotice(data.error ?? "提交订单失败");
    else {
      saveCart([]);
      setNotice(`订单 ${data.orderNo} 已提交，山东仓正在配货`);
      await loadCenter();
    }
    setCheckingOut(false);
  };

  return (
    <main className={`app-store separated ${mode}`}>
      <div className="app-frame">
        <header className="app-topbar">
          <a className="app-brand" href={prefix}><span className="app-brand-mark">莱</span><span><b>LESHINE</b><small>{mode === "retail" ? "莱莎零售商城" : "莱莎批发商城"}</small></span></a>
          <div className="account-chip"><span>{mode === "retail" ? `${retailPhone?.replace(/(\d{3})\d{4}(\d{4})/, "$1****$2")} · 零售客户` : `${account?.companyName} · 批发${level.toUpperCase()}`}</span><button onClick={logout}>退出</button></div>
        </header>
        {notice && <button className="shop-notice" onClick={() => setNotice("")}>{notice} ×</button>}
        <div className="app-content">
          {view === "home" && <HomeView mode={mode} level={level} account={account} levels={levels} products={allowedProducts} getPrice={getPrice} addCart={addCart} openProduct={setSelectedProduct} prefix={prefix} center={center} />}
          {view === "category" && <CategoryView mode={mode} level={level} products={allowedProducts} getPrice={getPrice} addCart={addCart} openProduct={setSelectedProduct} />}
          {view === "marketing" && <MarketingView mode={mode} center={center} prefix={prefix} />}
          {view === "cart" && <CartView mode={mode} rows={cartProducts} total={cartTotal} getPrice={getPrice} updateQuantity={updateQuantity} prefix={prefix} promoCode={promoCode} setPromoCode={setPromoCode} checkout={checkout} checkingOut={checkingOut} />}
          {view === "profile" && <ProfileView mode={mode} level={level} account={account} retailPhone={retailPhone} levels={levels} center={center} />}
        </div>
        {selectedProduct && <ProductDetail product={selectedProduct} price={getPrice(selectedProduct)} onClose={() => setSelectedProduct(null)} onAdd={() => { addCart(selectedProduct.id); setSelectedProduct(null); }} />}
        <BottomNav prefix={prefix} active={view} cartCount={cart.reduce((sum, line) => sum + line.quantity, 0)} />
      </div>
    </main>
  );
}

function HomeView({ mode, level, account, levels, products, getPrice, addCart, openProduct, prefix, center }: { mode: Mode; level: LevelCode; account?: WholesaleAccount; levels: WholesaleLevel[]; products: Product[]; getPrice: (p: Product) => number; addCart: (id: number) => void; openProduct: (product: Product) => void; prefix: string; center: CenterData }) {
  return <>
    <label className="app-search"><span>⌕</span><input aria-label="搜索假发款式" placeholder="搜索款式、长度、颜色" /><button>搜索</button></label>
    <section className="app-hero-card"><div className="app-hero-copy"><p>{mode === "retail" ? "RETAIL STORE" : "WHOLESALE STORE"}</p><h1>{mode === "retail" ? <>零售精选<br />舒适自然</> : <>批发专供<br />等级价格</>}</h1><span>{mode === "retail" ? "新人首单礼 · 专业客服选款" : `当前批发${level.toUpperCase()}等级 · 山东自有仓发货`}</span><a href={`${prefix}/category`}>进入分类</a></div><div className="app-hero-logo"><img src="/leshine-brand.jpg" alt="莱莎健康假发品牌标识" /></div></section>
    <section className="quick-grid"><a href={`${prefix}/category`}><i>款</i><strong>产品分类</strong><span>按系列快速选款</span></a><a href={`${prefix}/marketing`}><i>销</i><strong>营销工具</strong><span>推广码与宣传素材</span></a><a href={`${prefix}/profile#orders`}><i>单</i><strong>订单物流</strong><span>{center.orders.length ? `${center.orders.length}笔订单可查` : "全程轨迹可查"}</span></a><a href={`${prefix}/profile`}><i>客</i><strong>销售客服</strong><span>{center.salesperson?.name ?? "专属顾问服务"}</span></a></section>
    {mode === "wholesale" && <section className="wholesale-account-card"><div><span>批发身份已验证</span><strong>{center.profile?.storeName || account?.companyName}</strong><small>批发{level.toUpperCase()}等级 · 专属销售员 {account?.salesPerson}</small></div><div className="verified-badge"><b>✓</b><span>{account?.phone.replace(/(\d{3})\d{4}(\d{4})/, "$1****$2")}</span></div></section>}
    {mode === "retail" && center.promotions[0] && <section className="newcomer-banner"><div><small>NEW MEMBER BENEFIT</small><strong>{center.promotions[0].title}</strong><span>{center.promotions[0].description}</span></div><a href={`${prefix}/marketing`}>立即查看</a></section>}
    <section className="series-intro"><article><b>安心</b><span>自然日常，第一次佩戴也容易接受</span></article><article><b>气质</b><span>时尚升级，修饰脸型更显精神</span></article><article><b>高光</b><span>重要场合，体面有气场更上镜</span></article><article><b>臻藏</b><span>专属设计，精工质感与纪念价值</span></article></section>
    <section className="app-section product-section"><div className="app-section-title"><div><span>{mode === "retail" ? "RETAIL PRICE" : `LEVEL ${level.toUpperCase()} PRICE`}</span><h2>{mode === "retail" ? "12款主推发型" : "本账户可采购款式"}</h2></div><a href={`${prefix}/category`}>全部款式 ›</a></div><ProductGrid products={products.slice(0, 4)} getPrice={getPrice} addCart={addCart} openProduct={openProduct} /></section>
    {mode === "wholesale" && <section className="app-section wholesale-card"><div className="app-section-title light"><div><span>ACCOUNT LEVEL</span><h2>账户等级与采购权益</h2></div><small>后台可随时调整</small></div><div className="app-level-list">{levels.filter((item) => item.code !== "retail").map((item, index) => <article key={item.code}><i>0{index + 1}</i><div><strong>{item.name}</strong><span>累计净采购满 ¥{item.threshold.toLocaleString()} 解锁对应价格与款式</span></div><b>{rank[level] >= rank[item.code] ? "✓" : "›"}</b></article>)}</div></section>}
    <section className="service-strip"><div><b>✓</b><span>山东自有仓</span></div><div><b>✓</b><span>专业客服</span></div><div><b>✓</b><span>物流轨迹可查</span></div></section>
  </>;
}

function CategoryView({ mode, level, products, getPrice, addCart, openProduct }: { mode: Mode; level: LevelCode; products: Product[]; getPrice: (p: Product) => number; addCart: (id: number) => void; openProduct: (product: Product) => void }) {
  const [category, setCategory] = useState("全部");
  const categories = ["全部", ...Array.from(new Set(products.map((item) => item.category || item.material)))];
  const filtered = category === "全部" ? products : products.filter((item) => item.category === category || item.material === category);
  return <section className="inner-page"><div className="inner-title"><p>{mode === "retail" ? "零售商品分类" : `批发${level.toUpperCase()}等级商品`}</p><h1>四大主推系列</h1><span>{mode === "retail" ? "安心、气质、高光、臻藏，按佩戴需求快速选款" : "只显示当前账户有权限查看的商品和批发价"}</span></div><div className="category-tabs">{categories.map((item) => <button className={category === item ? "active" : ""} onClick={() => setCategory(item)} key={item}>{item}</button>)}</div><ProductGrid products={filtered} getPrice={getPrice} addCart={addCart} openProduct={openProduct} /></section>;
}

function ProductGrid({ products, getPrice, addCart, openProduct }: { products: Product[]; getPrice: (p: Product) => number; addCart: (id: number) => void; openProduct: (product: Product) => void }) {
  return <div className="product-grid app-product-grid">{products.map((product, index) => <article className="product-card app-product-card" key={product.id}><button className={`product-art ${product.tone}`} onClick={() => openProduct(product)} aria-label={`查看${product.name}详情`}><span className="number">{String(index + 1).padStart(2, "0")}</span>{product.images[0] ? <img src={product.images[0]} alt={`${product.name}实拍`} /> : <div className="mini-hair" />}</button><div className="app-product-info"><span className="product-tag">{product.category || product.material}</span><button className="product-name-button" onClick={() => openProduct(product)}><h3>{product.name}</h3></button><p>{product.sku ? `${product.sku} · ` : ""}{product.length} · {product.color}</p><div><strong>¥{getPrice(product)}</strong><button onClick={() => addCart(product.id)} aria-label={`添加${product.name}到购物车`}>＋</button></div></div></article>)}</div>;
}

function ProductDetail({ product, price, onClose, onAdd }: { product: Product; price: number; onClose: () => void; onAdd: () => void }) {
  const [activeImage, setActiveImage] = useState(product.images[0] ?? "");
  return <div className="product-detail-backdrop" onMouseDown={onClose}>
    <section className="product-detail" onMouseDown={(event) => event.stopPropagation()}>
      <button className="detail-close" onClick={onClose} aria-label="关闭详情">×</button>
      <div className="detail-gallery">
        <div className="detail-main-image">{activeImage ? <img src={activeImage} alt={`${product.name}实拍`} /> : <div className={`product-art ${product.tone}`}><div className="mini-hair" /></div>}</div>
        <div className="detail-thumbs">{product.images.map((url, index) => <button className={activeImage === url ? "active" : ""} key={url} onClick={() => setActiveImage(url)}><img src={url} alt={`${product.name}角度${index + 1}`} /></button>)}</div>
      </div>
      <div className="detail-copy">
        <span className="detail-series">{product.category}</span><h2>{product.name}</h2><p className="detail-summary">{product.description}</p>
        <div className="detail-specs"><span><small>材质</small>{product.material}</span><span><small>长度</small>{product.length}</span><span><small>颜色</small>{product.color}</span><span><small>发网</small>{product.construction || "—"}</span><span><small>发量</small>{product.hairVolume || "—"}</span><span><small>分缝</small>{product.parting || "—"}</span></div>
        {product.highlights.length > 0 && <div className="detail-block"><h3>核心卖点</h3><ul>{product.highlights.map((item) => <li key={item}>{item}</li>)}</ul></div>}
        {product.audience.length > 0 && <div className="detail-block"><h3>适合人群</h3><p>{product.audience.join("；")}</p></div>}
        {product.scenarios.length > 0 && <div className="scenario-chips">{product.scenarios.map((item) => <span key={item}>{item}</span>)}</div>}
        {product.craft && <details><summary>查看工艺特点</summary><p>{product.craft}</p></details>}
        <div className="download-row">{product.images.map((url, index) => <a href={url} download key={url}>下载图{index + 1}</a>)}{product.videoUrl && <a href={product.videoUrl} download>下载视频</a>}</div>
        {product.videoUrl && <video className="product-video" src={product.videoUrl} poster={product.images[0]} controls playsInline preload="metadata" />}
        <div className="detail-buy"><div><small>当前价格</small><strong>¥{price.toLocaleString()}</strong></div><button onClick={onAdd}>加入购物车</button></div>
      </div>
    </section>
  </div>;
}

function MarketingView({ mode, center, prefix }: { mode: Mode; center: CenterData; prefix: string }) {
  const copy = async (value: string) => { await navigator.clipboard?.writeText(value); };
  return <section className="inner-page marketing-page"><div className="inner-title"><p>MARKETING CENTER</p><h1>营销与分销工具</h1><span>推广码、店面宣传码和产品素材统一管理</span></div>
    <div className="marketing-grid">
      <article className="promo-identity"><span>我的推广身份</span><h2>{center.distributor.eligible ? "分销权益已开通" : "完成首笔购买即可开通"}</h2><p>{center.distributor.eligible ? `每笔有效推广订单按${center.distributor.commissionRate}%进入待结算佣金` : "购买任意一款产品后，可分享产品并生成个人推广码。"}</p><div><strong>{center.distributor.referralCode || "待开通"}</strong><button disabled={!center.distributor.eligible} onClick={() => copy(center.distributor.referralCode)}>复制推广码</button></div></article>
      <article className="sales-contact"><span>专属销售与客服</span><h2>{center.salesperson?.name ?? "林青"} · {center.salesperson?.role ?? "销售顾问"}</h2><p>销售电话 {center.salesperson?.phone ?? "18900003821"}<br />客服：{center.salesperson?.customerService ?? "小莱客服"}</p><div className="code-pair"><button onClick={() => copy(center.salesperson?.promoCode ?? "LINQING")}><small>销售推广码</small><b>{center.salesperson?.promoCode ?? "LINQING"}</b></button><button onClick={() => copy(center.salesperson?.storeCode ?? "STORE-LQ")}><small>店面宣传码</small><b>{center.salesperson?.storeCode ?? "STORE-LQ"}</b></button></div></article>
    </div>
    <div className="benefit-list"><div className="app-section-title"><div><span>NEW USER</span><h2>新用户专享福利</h2></div></div>{center.promotions.map((item) => <article key={item.id}><i>{item.benefitType === "shipping" ? "邮" : "礼"}</i><div><strong>{item.title}</strong><span>{item.description}</span></div><b>{item.benefitType === "coupon" ? `¥${item.benefitValue}` : "专享"}</b></article>)}</div>
    <div className="material-library"><div className="app-section-title"><div><span>CONTENT LIBRARY</span><h2>产品宣传素材</h2></div><a href={`${prefix}/category`}>查看产品 ›</a></div><div><button><i>图</i><strong>产品实拍</strong><span>正侧背与细节图</span></button><button><i>报</i><strong>宣传海报</strong><span>门店及社媒尺寸</span></button><button><i>视</i><strong>短视频素材</strong><span>佩戴、场景与教程</span></button><button><i>文</i><strong>销售话术</strong><span>卖点与推广文案</span></button></div><p>{mode === "wholesale" ? "素材权限已按当前批发等级开放。" : "购买后可解锁对应产品的分销素材。"}</p></div>
  </section>;
}

function CartView({ mode, rows, total, getPrice, updateQuantity, prefix, promoCode, setPromoCode, checkout, checkingOut }: { mode: Mode; rows: { line: CartLine; product: Product }[]; total: number; getPrice: (p: Product) => number; updateQuantity: (id: number, d: number) => void; prefix: string; promoCode: string; setPromoCode: (value: string) => void; checkout: () => void; checkingOut: boolean }) {
  return <section className="inner-page"><div className="inner-title"><p>{mode === "retail" ? "零售订单" : "批发采购单"}</p><h1>购物车</h1><span>{mode === "retail" ? "按零售价结算" : "价格已按当前批发账户等级计算"}</span></div>{rows.length === 0 ? <div className="empty-cart"><i>袋</i><h2>购物车还是空的</h2><p>去分类页面挑选喜欢的假发款式</p><a href={`${prefix}/category`}>去选购</a></div> : <><div className="cart-list">{rows.map(({ line, product }) => <article key={product.id}><div className={`cart-art ${product.tone}`}>{product.images[0] ? <img src={product.images[0]} alt="" /> : <div className="tiny-hair" />}</div><div><strong>{product.name}</strong><span>{product.material} · {product.length} · {product.color}</span><b>¥{getPrice(product)}</b></div><div className="quantity"><button onClick={() => updateQuantity(product.id, -1)}>−</button><span>{line.quantity}</span><button onClick={() => updateQuantity(product.id, 1)}>＋</button></div></article>)}</div><label className="promo-input"><span>推广码 / 店面宣传码</span><input value={promoCode} onChange={(e) => setPromoCode(e.target.value.toUpperCase())} placeholder="选填，自动归属推广业务员" /></label><div className="checkout-bar"><span>共 {rows.reduce((sum, row) => sum + row.line.quantity, 0)} 件</span><div><small>合计</small><strong>¥{total}</strong><button disabled={checkingOut} onClick={checkout}>{checkingOut ? "提交中…" : "提交订单"}</button></div></div></>}</section>;
}

function ProfileView({ mode, level, account, retailPhone, levels, center }: { mode: Mode; level: LevelCode; account?: WholesaleAccount; retailPhone?: string; levels: WholesaleLevel[]; center: CenterData }) {
  const threshold = levels.find((item) => item.code === "b")?.threshold ?? 20000;
  const displayPhone = (account?.phone ?? retailPhone)?.replace(/(\d{3})\d{4}(\d{4})/, "$1****$2");
  return <section className="inner-page"><div className="profile-card"><span className="profile-avatar">莱</span><div><p>{center.profile?.storeName || (mode === "retail" ? "莱莎零售会员" : account?.companyName)}</p><strong>{mode === "retail" ? `${displayPhone} · 零售客户` : `批发${level.toUpperCase()}等级账户 · 手机已验证`}</strong></div></div>
    <div className="account-detail"><div><span>验证手机号</span><strong>{displayPhone}</strong></div><div><span>来源销售员</span><strong>{center.profile?.salesPerson ?? account?.salesPerson ?? "林青"}</strong></div><div><span>{mode === "wholesale" ? "升级进度" : "分销权益"}</span><strong>{mode === "wholesale" ? (level === "b" ? "已达最高演示等级" : `距批发B还差 ¥${Math.max(0, threshold - 8920).toLocaleString()}`) : (center.distributor.eligible ? "已开通" : "首购后开通")}</strong></div></div>
    <div className="order-center" id="orders"><div className="app-section-title"><div><span>MY ORDERS</span><h2>订单与物流</h2></div><small>实时查看发货进度</small></div>{center.orders.length ? center.orders.map((order) => <article key={order.id}><header><strong>{order.orderNo}</strong><b>{order.status}</b></header><div><span>{new Date(order.createdAt).toLocaleDateString("zh-CN")} · {order.itemCount}件商品</span><strong>¥{order.amount}</strong></div><footer><i /> <span>{order.logisticsStatus || "等待仓库发货"}{order.trackingNo ? ` · ${order.logisticsCompany} ${order.trackingNo}` : ""}</span></footer></article>) : <div className="order-empty">还没有订单，购买后可在这里查看物流轨迹。</div>}</div>
    <div className="profile-menu"><a href={`${mode === "retail" ? "/retail" : "/wholesale"}/marketing`}><span>营销工具</span><b>推广码与宣传素材 ›</b></a><a href="#service"><span>销售员</span><b>{center.salesperson?.name ?? account?.salesPerson ?? "林青"} ›</b></a><a href="#service"><span>专属客服</span><b>{center.profile?.customerService ?? "小莱客服"} ›</b></a><a href="/admin"><span>演示后台</span><b>管理人员进入 ›</b></a></div>
  </section>;
}

function BottomNav({ prefix, active, cartCount }: { prefix: string; active: View; cartCount: number }) {
  const items: { key: View; href: string; icon: string; label: string }[] = [{ key: "home", href: prefix, icon: "⌂", label: "首页" }, { key: "category", href: `${prefix}/category`, icon: "▦", label: "分类" }, { key: "marketing", href: `${prefix}/marketing`, icon: "◇", label: "营销" }, { key: "cart", href: `${prefix}/cart`, icon: "▢", label: "购物车" }, { key: "profile", href: `${prefix}/profile`, icon: "○", label: "我的" }];
  return <nav className="app-bottom-nav separated-nav">{items.map((item) => <a className={active === item.key ? "active" : ""} href={item.href} key={item.key}><i>{item.icon}</i><span>{item.label}</span>{item.key === "cart" && cartCount > 0 && <b>{cartCount}</b>}</a>)}</nav>;
}
