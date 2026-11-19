"use client";

import { useEffect, useMemo, useState } from "react";
import { ProductOptions } from "./components/product-options";
import { cartKey, minimumPrice, normalizeCart, sellable, type CartLine, type ProductVariant } from "./lib/product-options";
import { OrderTrackingDetails } from "./components/order-logistics";
import type { CustomerProfile, LevelCode, Order, Product, Promotion, SalesPerson, WholesaleAccount, WholesaleLevel } from "./lib/types";

type Mode = "retail" | "wholesale";
type View = "home" | "category" | "marketing" | "cart" | "profile";
type CartRow = { line: CartLine; product: Product; variant: ProductVariant };
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
      try { setCart(normalizeCart(JSON.parse(savedCart))); } catch { setCart([]); setNotice("购物车已升级，请重新选择网底和长度。"); }
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
  const getPrice = (p: Product) => minimumPrice(p.variants) ?? 0;
  const saveCart = (next: CartLine[]) => {
    setCart(next);
    window.localStorage.setItem(`leshine-cart-${mode}`, JSON.stringify(next));
  };
  const addCart = (id: number) => setSelectedProduct(products.find((item) => item.id === id) ?? null);
  const addVariant = (product: Product, variant: ProductVariant) => {
    const key = cartKey({ id: product.id, variantKey: variant.key });
    const exists = cart.some((line) => cartKey(line) === key);
    saveCart(exists ? cart.map((line) => cartKey(line) === key ? { ...line, quantity: Math.min(100, line.quantity + 1) } : line) : [...cart, { id: product.id, variantKey: variant.key, quantity: 1 }]);
    setNotice(`已加入：${product.name} · ${variant.cap} · ${variant.length}厘米`);
    setSelectedProduct(null);
  };
  const updateQuantity = (key: string, delta: number) => saveCart(cart.map((line) => cartKey(line) === key ? { ...line, quantity: Math.min(100, line.quantity + delta) } : line).filter((line) => line.quantity > 0));
  const cartProducts: CartRow[] = cart.flatMap((line) => {
    const product = products.find((item) => item.id === line.id);
    const variant = product?.variants?.find((item) => item.key === line.variantKey && sellable(item));
    return product && variant ? [{ line, product, variant }] : [];
  });
  const cartTotal = cartProducts.reduce((sum, item) => sum + item.variant.price! * item.line.quantity, 0);
  const logout = async () => {
    await fetch(mode === "wholesale" ? "/api/wholesale-auth" : "/api/retail-auth", { method: "DELETE" });
    window.location.href = mode === "wholesale" ? "/wholesale/login" : "/retail/login";
  };
  const checkout = async () => {
    setCheckingOut(true);
    const signature = JSON.stringify({ cart, promoCode });
    const storageKey = `leshine-checkout-${mode}`;
    let pending: { signature: string; key: string } | null = null;
    try { pending = JSON.parse(window.localStorage.getItem(storageKey) ?? "null"); } catch { /* Start a new checkout key. */ }
    const requestId = pending?.signature === signature ? pending.key : crypto.randomUUID();
    window.localStorage.setItem(storageKey, JSON.stringify({ signature, key: requestId }));
    try {
    const response = await fetch("/api/orders", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ mode, lines: cart, promoCode, requestId }) });
    const data = await response.json();
    if (!response.ok) setNotice(data.error ?? "提交订单失败");
    else {
      window.localStorage.removeItem(storageKey);
      saveCart([]);
      setNotice(`订单 ${data.orderNo} 已提交，山东仓正在配货`);
      await loadCenter();
    }
    } catch { setNotice("连接中断，请重试；同一订单不会重复创建。"); } finally { setCheckingOut(false); }
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
          {view === "cart" && <CartView mode={mode} rows={cartProducts} total={cartTotal} invalid={cartProducts.length !== cart.length} clearInvalid={() => saveCart(cartProducts.map((item) => item.line))} updateQuantity={updateQuantity} prefix={prefix} promoCode={promoCode} setPromoCode={setPromoCode} checkout={checkout} checkingOut={checkingOut} />}
          {view === "profile" && <ProfileView mode={mode} level={level} account={account} retailPhone={retailPhone} levels={levels} center={center} />}
        </div>
        {selectedProduct && <ProductDetail key={selectedProduct.id} product={selectedProduct} onClose={() => setSelectedProduct(null)} onAdd={(variant) => addVariant(selectedProduct, variant)} />}
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
    {mode === "retail" && <section className="ai-tryon-banner"><div><small>AI HAIRSTYLE TRY-ON</small><strong>不知道自己适合什么发型？</strong><span>使用当前商城账号进入 AI 试戴，每个账号仅有一次免费生成机会。</span></div><a href="/retail/tryon">AI 试戴</a></section>}
    {mode === "retail" && center.promotions[0] && <section className="newcomer-banner"><div><small>NEW MEMBER BENEFIT</small><strong>{center.promotions[0].title}</strong><span>{center.promotions[0].description}</span></div><a href={`${prefix}/marketing`}>立即查看</a></section>}
    <section className="series-intro"><article><b>安心</b><span>自然日常，第一次佩戴也容易接受</span></article><article><b>气质</b><span>时尚升级，修饰脸型更显精神</span></article><article><b>高光</b><span>重要场合，体面有气场更上镜</span></article><article><b>臻藏</b><span>专属设计，精工质感与纪念价值</span></article></section>
    <section className="app-section product-section"><div className="app-section-title"><div><span>{mode === "retail" ? "RETAIL PRICE" : `LEVEL ${level.toUpperCase()} PRICE`}</span><h2>{mode === "retail" ? "16款主推发型" : "本账户可采购款式"}</h2></div><a href={`${prefix}/category`}>全部款式 ›</a></div><ProductGrid products={products.slice(0, 4)} getPrice={getPrice} addCart={addCart} openProduct={openProduct} /></section>
    {mode === "wholesale" && <section className="app-section wholesale-card"><div className="app-section-title light"><div><span>ACCOUNT LEVEL</span><h2>账户等级与采购权益</h2></div><small>后台可随时调整</small></div><div className="app-level-list">{levels.filter((item) => item.code !== "retail").map((item, index) => <article key={item.code}><i>0{index + 1}</i><div><strong>{item.name}</strong><span>等级由后台指定，调整请联系专属销售</span></div><b>{rank[level] >= rank[item.code] ? "✓" : "›"}</b></article>)}</div></section>}
    <section className="service-strip"><div><b>✓</b><span>山东自有仓</span></div><div><b>✓</b><span>专业客服</span></div><div><b>✓</b><span>物流轨迹可查</span></div></section>
  </>;
}

function CategoryView({ mode, level, products, getPrice, addCart, openProduct }: { mode: Mode; level: LevelCode; products: Product[]; getPrice: (p: Product) => number; addCart: (id: number) => void; openProduct: (product: Product) => void }) {
  const [category, setCategory] = useState("全部");
  const categories = ["全部", "安心系列", "气质系列", "高光系列", "臻藏系列"];
  const filtered = category === "全部" ? products : products.filter((item) => item.category === category || item.material === category);
  return <section className="inner-page"><div className="inner-title"><p>{mode === "retail" ? "零售商品分类" : `批发${level.toUpperCase()}等级商品`}</p><h1>四大主推系列</h1><span>{mode === "retail" ? "安心、气质、高光、臻藏，按佩戴需求快速选款" : "只显示当前账户有权限查看的商品和批发价"}</span></div><div className="category-layout"><aside className="category-sidebar"><div><small>COLLECTION</small><strong>系列切换</strong></div>{categories.map((item) => <button className={category === item ? "active" : ""} onClick={() => setCategory(item)} key={item}><span>{item === "全部" ? "全部款式" : item}</span><b>{item === "全部" ? products.length : products.filter((product) => product.category === item).length}</b></button>)}</aside><div className="category-results"><header><strong>{category === "全部" ? "全部主推款" : category}</strong><span>共 {filtered.length} 款 · 封面均为正面实拍</span></header><ProductGrid products={filtered} getPrice={getPrice} addCart={addCart} openProduct={openProduct} /></div></div></section>;
}

function ProductGrid({ products, getPrice, addCart, openProduct }: { products: Product[]; getPrice: (p: Product) => number; addCart: (id: number) => void; openProduct: (product: Product) => void }) {
  return <div className="product-grid app-product-grid">{products.map((product, index) => <article className="product-card app-product-card" key={product.id}><button className={`product-art ${product.tone}`} onClick={() => openProduct(product)} aria-label={`查看${product.name}详情`}><span className="number">{String(index + 1).padStart(2, "0")}</span>{product.images[0] ? <img src={product.images[0]} alt={`${product.name}实拍`} /> : <div className="mini-hair" />}</button><div className="app-product-info"><span className="product-tag">{product.category || product.material}</span><button className="product-name-button" onClick={() => openProduct(product)}><h3>{product.name}</h3></button><p>{product.sku ? `${product.sku} · ` : ""}{product.length} · {product.color}</p><div><strong>{getPrice(product) ? `¥${getPrice(product)}起` : "待定价"}</strong><button onClick={() => addCart(product.id)} aria-label={`选择${product.name}的网底和长度`}>＋</button></div></div></article>)}</div>;
}

function ProductDetail({ product, onClose, onAdd }: { product: Product; onClose: () => void; onAdd: (variant: ProductVariant) => void }) {
  const variants = product.variants ?? [];
  const [variantKey, setVariantKey] = useState((variants.find(sellable) ?? variants.find((item) => item.enabled))?.key ?? "");
  const selected = variants.find((item) => item.key === variantKey);
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
        <div className="detail-specs"><span><small>材质</small>{product.material}</span><span><small>长度</small>{selected ? `${selected.length}厘米` : product.length}</span><span><small>颜色</small>{product.color}</span><span><small>发网</small>{selected?.cap ?? product.construction ?? "—"}</span><span><small>发量</small>{product.hairVolume || "—"}</span><span><small>分缝</small>{product.parting || "—"}</span></div>
        <ProductOptions variants={variants} value={variantKey} onChange={setVariantKey} />
        {product.highlights.length > 0 && <div className="detail-block"><h3>核心卖点</h3><ul>{product.highlights.map((item) => <li key={item}>{item}</li>)}</ul></div>}
        {product.audience.length > 0 && <div className="detail-block"><h3>适合人群</h3><p>{product.audience.join("；")}</p></div>}
        {product.scenarios.length > 0 && <div className="scenario-chips">{product.scenarios.map((item) => <span key={item}>{item}</span>)}</div>}
        {product.craft && <details><summary>查看工艺特点</summary><p>{product.craft}</p></details>}
        <div className="download-row">{product.images.map((url, index) => <a href={url} download key={url}>下载图{index + 1}</a>)}{product.videoUrl && <a href={product.videoUrl} download>下载视频</a>}</div>
        {product.videoUrl && <video className="product-video" src={product.videoUrl} poster={product.images[0]} controls playsInline preload="metadata" />}
        <div className="detail-buy"><div><small>当前价格</small><strong>{selected?.price != null ? `¥${selected.price.toLocaleString()}` : "待定价"}</strong></div><button disabled={!selected || !sellable(selected) || product.stock <= 0} onClick={() => selected && onAdd(selected)}>{product.stock <= 0 ? "暂时缺货" : "加入购物车"}</button></div>
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

function CartView({ rows, total, updateQuantity, prefix, promoCode, setPromoCode, checkout, checkingOut, invalid, clearInvalid }: { mode: Mode; rows: CartRow[]; total: number; updateQuantity: (key: string, delta: number) => void; prefix: string; promoCode: string; setPromoCode: (value: string) => void; checkout: () => void; checkingOut: boolean; invalid: boolean; clearInvalid: () => void }) {
  return <section className="inner-page"><div className="inner-title"><p>已选规格</p><h1>购物车</h1><span>每个网底和长度组合单独计价</span></div>
    {invalid && <p role="alert">部分规格已下架或未定价，请重新选择。<button onClick={clearInvalid}>移除失效规格</button></p>}
    {!rows.length ? <div className="empty-cart"><h2>购物车还没有可购买的规格</h2><a href={`${prefix}/category`}>选择发型与规格</a></div> : <><div className="cart-list">{rows.map(({ line, product, variant }) => <article key={cartKey(line)}><div className={`cart-art ${product.tone}`}>{product.images[0] && <img src={product.images[0]} alt={product.name} />}</div><div><strong>{product.name}</strong><span>{variant.cap} · {variant.length}厘米 · {product.color}</span><b>¥{variant.price}</b></div><div className="quantity"><button onClick={() => updateQuantity(cartKey(line), -1)}>−</button><span>{line.quantity}</span><button onClick={() => updateQuantity(cartKey(line), 1)}>＋</button></div></article>)}</div><label className="promo-input"><span>推广码</span><input value={promoCode} onChange={(event) => setPromoCode(event.target.value.toUpperCase())} /></label><div className="checkout-bar"><span>共 {rows.reduce((sum,item) => sum+item.line.quantity,0)} 件</span><div><strong>¥{total.toLocaleString()}</strong><button disabled={checkingOut || invalid} onClick={checkout}>{checkingOut ? "提交中…" : "提交订单"}</button></div></div></>}
  </section>;
}

function ProfileView({ mode, level, account, retailPhone, center }: { mode: Mode; level: LevelCode; account?: WholesaleAccount; retailPhone?: string; levels: WholesaleLevel[]; center: CenterData }) {
  const displayPhone = (account?.phone ?? retailPhone)?.replace(/(\d{3})\d{4}(\d{4})/, "$1****$2");
  return <section className="inner-page"><div className="profile-card"><span className="profile-avatar">莱</span><div><p>{center.profile?.storeName || (mode === "retail" ? "莱莎零售会员" : account?.companyName)}</p><strong>{mode === "retail" ? `${displayPhone} · 零售客户` : `批发${level.toUpperCase()}等级账户 · 手机已验证`}</strong></div></div>
    <div className="account-detail"><div><span>验证手机号</span><strong>{displayPhone}</strong></div><div><span>来源销售员</span><strong>{center.profile?.salesPerson ?? account?.salesPerson ?? "林青"}</strong></div><div><span>{mode === "wholesale" ? "客户等级" : "分销权益"}</span><strong>{mode === "wholesale" ? (level === "b" ? "等级由后台指定" : "等级由后台指定") : (center.distributor.eligible ? "已开通" : "首购后开通")}</strong></div></div>
    <div className="order-center" id="orders"><div className="app-section-title"><div><span>MY ORDERS</span><h2>订单与物流</h2></div><small>实时查看发货进度</small></div>{center.orders.length ? center.orders.map((order) => <article key={order.id}><header><strong>{order.orderNo}</strong><b>{order.status}</b></header><div><span>{new Date(order.createdAt).toLocaleDateString("zh-CN")} · {order.itemCount}件商品</span><strong>¥{order.amount}</strong></div><footer><i /> <span>{order.logisticsStatus || "等待仓库发货"}{order.trackingNo ? ` · ${order.logisticsCompany} ${order.trackingNo}` : ""}</span></footer><div className="order-item-options">{order.items?.map((item, index) => <p key={index}>{item.productName} · {item.variantLabel || "原款规格"} × {item.quantity}</p>)}</div><OrderTrackingDetails orderId={order.id} mode={mode} /></article>) : <div className="order-empty">还没有订单，购买后可在这里查看物流轨迹。</div>}</div>
    <div className="profile-menu">{mode === "retail" && <a href="/retail/tryon"><span>AI 发型试戴</span><b>一次免费体验 ›</b></a>}<a href={`${mode === "retail" ? "/retail" : "/wholesale"}/marketing`}><span>营销工具</span><b>推广码与宣传素材 ›</b></a><a href="#service"><span>销售员</span><b>{center.salesperson?.name ?? account?.salesPerson ?? "林青"} ›</b></a><a href="#service"><span>专属客服</span><b>{center.profile?.customerService ?? "小莱客服"} ›</b></a><a href="/admin"><span>演示后台</span><b>管理人员进入 ›</b></a></div>
  </section>;
}

function BottomNav({ prefix, active, cartCount }: { prefix: string; active: View; cartCount: number }) {
  const items: { key: View; href: string; icon: string; label: string }[] = [{ key: "home", href: prefix, icon: "⌂", label: "首页" }, { key: "category", href: `${prefix}/category`, icon: "▦", label: "分类" }, { key: "marketing", href: `${prefix}/marketing`, icon: "◇", label: "营销" }, { key: "cart", href: `${prefix}/cart`, icon: "▢", label: "购物车" }, { key: "profile", href: `${prefix}/profile`, icon: "○", label: "我的" }];
  return <nav className="app-bottom-nav separated-nav">{items.map((item) => <a className={active === item.key ? "active" : ""} href={item.href} key={item.key}><i>{item.icon}</i><span>{item.label}</span>{item.key === "cart" && cartCount > 0 && <b>{cartCount}</b>}</a>)}</nav>;
}
