"use client";

import { useEffect, useMemo, useState } from "react";
import type { LevelCode, Product, WholesaleAccount, WholesaleLevel } from "./lib/types";

type Mode = "retail" | "wholesale";
type View = "home" | "category" | "cart" | "profile";
type CartLine = { id: number; quantity: number };

const rank: Record<LevelCode, number> = { retail: 0, a: 1, b: 2 };

export default function ShopApp({ mode, view, account, retailPhone }: { mode: Mode; view: View; account?: WholesaleAccount; retailPhone?: string }) {
  const level: LevelCode = mode === "wholesale" ? account?.level ?? "a" : "retail";
  const [products, setProducts] = useState<Product[]>([]);
  const [levels, setLevels] = useState<WholesaleLevel[]>([]);
  const [cart, setCart] = useState<CartLine[]>([]);
  const [notice, setNotice] = useState("");
  const prefix = mode === "retail" ? "/retail" : "/wholesale";

  useEffect(() => {
    const savedCart = window.localStorage.getItem(`leshine-cart-${mode}`);
    if (savedCart) {
      try { setCart(JSON.parse(savedCart)); } catch { setCart([]); }
    }
    Promise.all([fetch("/api/products").then((r) => r.json()), fetch("/api/levels").then((r) => r.json())])
      .then(([productData, levelData]) => { setProducts(productData.products ?? []); setLevels(levelData.levels ?? []); });
  }, [mode]);

  const allowedProducts = useMemo(() => products.filter((p) => p.status === "active" && rank[level] >= rank[p.minLevel]), [products, level]);
  const getPrice = (p: Product) => mode === "retail" ? p.retailPrice : level === "b" ? p.priceB : p.priceA;
  const addCart = (id: number) => {
    const next = cart.some((line) => line.id === id) ? cart.map((line) => line.id === id ? { ...line, quantity: line.quantity + 1 } : line) : [...cart, { id, quantity: 1 }];
    setCart(next); window.localStorage.setItem(`leshine-cart-${mode}`, JSON.stringify(next)); setNotice("已加入购物车");
  };
  const updateQuantity = (id: number, delta: number) => {
    const next = cart.map((line) => line.id === id ? { ...line, quantity: Math.max(0, line.quantity + delta) } : line).filter((line) => line.quantity > 0);
    setCart(next); window.localStorage.setItem(`leshine-cart-${mode}`, JSON.stringify(next));
  };
  const cartProducts = cart.map((line) => ({ line, product: products.find((p) => p.id === line.id) })).filter((item): item is { line: CartLine; product: Product } => Boolean(item.product));
  const cartTotal = cartProducts.reduce((sum, item) => sum + getPrice(item.product) * item.line.quantity, 0);
  const logout = async () => { await fetch(mode === "wholesale" ? "/api/wholesale-auth" : "/api/retail-auth", { method: "DELETE" }); window.location.href = mode === "wholesale" ? "/wholesale/login" : "/retail/login"; };

  return (
    <main className={`app-store separated ${mode}`}>
      <div className="app-frame">
        <header className="app-topbar">
          <a className="app-brand" href={prefix}><span className="app-brand-mark">莱</span><span><b>LESHINE</b><small>{mode === "retail" ? "莱莎零售商城" : "莱莎批发商城"}</small></span></a>
          <div className="account-chip"><span>{mode === "retail" ? `${retailPhone?.replace(/(\d{3})\d{4}(\d{4})/, "$1****$2")} · 零售客户` : `${account?.companyName} · 批发${level.toUpperCase()}`}</span><button onClick={logout}>退出</button></div>
        </header>
        {notice && <button className="shop-notice" onClick={() => setNotice("")}>{notice} ×</button>}
        <div className="app-content">
          {view === "home" && <HomeView mode={mode} level={level} account={account} levels={levels} products={allowedProducts} getPrice={getPrice} addCart={addCart} prefix={prefix} />}
          {view === "category" && <CategoryView mode={mode} level={level} products={allowedProducts} getPrice={getPrice} addCart={addCart} />}
          {view === "cart" && <CartView mode={mode} rows={cartProducts} total={cartTotal} getPrice={getPrice} updateQuantity={updateQuantity} prefix={prefix} />}
          {view === "profile" && <ProfileView mode={mode} level={level} account={account} retailPhone={retailPhone} levels={levels} />}
        </div>
        <BottomNav prefix={prefix} active={view} cartCount={cart.reduce((sum, line) => sum + line.quantity, 0)} />
      </div>
    </main>
  );
}

function HomeView({ mode, level, account, levels, products, getPrice, addCart, prefix }: { mode: Mode; level: LevelCode; account?: WholesaleAccount; levels: WholesaleLevel[]; products: Product[]; getPrice: (p: Product) => number; addCart: (id: number) => void; prefix: string }) {
  return <>
    <label className="app-search"><span>⌕</span><input aria-label="搜索假发款式" placeholder="搜索款式、长度、颜色" /><button>搜索</button></label>
    <section className="app-hero-card"><div className="app-hero-copy"><p>{mode === "retail" ? "RETAIL STORE" : "WHOLESALE STORE"}</p><h1>{mode === "retail" ? <>零售精选<br />舒适自然</> : <>批发专供<br />等级价格</>}</h1><span>{mode === "retail" ? "新人专享 · 专业客服选款" : `当前批发${level.toUpperCase()}等级 · 山东自有仓发货`}</span><a href={`${prefix}/category`}>进入分类</a></div><div className="app-hero-logo"><img src="/leshine-brand.jpg" alt="莱莎健康假发品牌标识" /></div></section>
    {mode === "retail" ? <section className="quick-grid"><a href={`${prefix}/category`}><i>短</i><strong>短发系列</strong><span>轻盈日常造型</span></a><a href={`${prefix}/category`}><i>真</i><strong>真人发</strong><span>自然舒适质感</span></a><a href={`${prefix}/category`}><i>新</i><strong>新用户福利</strong><span>首单专享权益</span></a><a href={`${prefix}/profile`}><i>客</i><strong>选款客服</strong><span>专业顾问服务</span></a></section> : <section className="wholesale-account-card"><div><span>已通过手机验证</span><strong>{account?.companyName}</strong><small>批发{level.toUpperCase()}等级 · 专属销售员 {account?.salesPerson}</small></div><div className="verified-badge"><b>✓</b><span>{account?.phone.replace(/(\d{3})\d{4}(\d{4})/, "$1****$2")}</span></div></section>}
    <section className="app-section product-section"><div className="app-section-title"><div><span>{mode === "retail" ? "RETAIL PRICE" : `LEVEL ${level.toUpperCase()} PRICE`}</span><h2>{mode === "retail" ? "零售热卖款式" : "本账户可采购款式"}</h2></div><a href={`${prefix}/category`}>全部款式 ›</a></div><ProductGrid products={products.slice(0, 4)} getPrice={getPrice} addCart={addCart} /></section>
    {mode === "wholesale" && <section className="app-section wholesale-card"><div className="app-section-title light"><div><span>ACCOUNT LEVEL</span><h2>账户等级与采购权益</h2></div><small>由后台按采购金额自动升级</small></div><div className="app-level-list">{levels.filter((item) => item.code !== "retail").map((item, index) => <article key={item.code}><i>0{index + 1}</i><div><strong>{item.name}</strong><span>累计净采购满 ¥{item.threshold.toLocaleString()} 解锁对应价格与款式</span></div><b>{rank[level] >= rank[item.code] ? "✓" : "›"}</b></article>)}</div></section>}
    <section className="service-strip"><div><b>✓</b><span>山东自有仓</span></div><div><b>✓</b><span>专业客服</span></div><div><b>✓</b><span>物流轨迹可查</span></div></section>
  </>;
}

function CategoryView({ mode, level, products, getPrice, addCart }: { mode: Mode; level: LevelCode; products: Product[]; getPrice: (p: Product) => number; addCart: (id: number) => void }) {
  const [category, setCategory] = useState("全部");
  const categories = ["全部", "真人发", "短发", "中长发", "男士系列"];
  return <section className="inner-page"><div className="inner-title"><p>{mode === "retail" ? "零售商品分类" : `批发${level.toUpperCase()}等级商品`}</p><h1>商品分类</h1><span>{mode === "retail" ? "页面仅显示零售价" : "只显示当前账户有权限查看的商品和批发价"}</span></div><div className="category-tabs">{categories.map((item) => <button className={category === item ? "active" : ""} onClick={() => setCategory(item)} key={item}>{item}</button>)}</div><ProductGrid products={products} getPrice={getPrice} addCart={addCart} /></section>;
}

function ProductGrid({ products, getPrice, addCart }: { products: Product[]; getPrice: (p: Product) => number; addCart: (id: number) => void }) {
  return <div className="product-grid app-product-grid">{products.map((product, index) => <article className="product-card app-product-card" key={product.id}><div className={`product-art ${product.tone}`}><span className="number">{String(index + 1).padStart(2, "0")}</span><span className="favorite">♡</span><div className="mini-hair" /></div><div className="app-product-info"><span className="product-tag">{product.material}</span><h3>{product.name}</h3><p>{product.length} · {product.color}</p><div><strong>¥{getPrice(product)}</strong><button onClick={() => addCart(product.id)} aria-label={`添加${product.name}到购物车`}>＋</button></div></div></article>)}</div>;
}

function CartView({ mode, rows, total, getPrice, updateQuantity, prefix }: { mode: Mode; rows: { line: CartLine; product: Product }[]; total: number; getPrice: (p: Product) => number; updateQuantity: (id: number, d: number) => void; prefix: string }) {
  return <section className="inner-page"><div className="inner-title"><p>{mode === "retail" ? "零售订单" : "批发采购单"}</p><h1>购物车</h1><span>{mode === "retail" ? "按零售价结算" : "价格已按当前批发账户等级计算"}</span></div>{rows.length === 0 ? <div className="empty-cart"><i>袋</i><h2>购物车还是空的</h2><p>去分类页面挑选喜欢的假发款式</p><a href={`${prefix}/category`}>去选购</a></div> : <><div className="cart-list">{rows.map(({ line, product }) => <article key={product.id}><div className={`cart-art ${product.tone}`}><div className="tiny-hair" /></div><div><strong>{product.name}</strong><span>{product.material} · {product.length} · {product.color}</span><b>¥{getPrice(product)}</b></div><div className="quantity"><button onClick={() => updateQuantity(product.id, -1)}>−</button><span>{line.quantity}</span><button onClick={() => updateQuantity(product.id, 1)}>＋</button></div></article>)}</div><div className="checkout-bar"><span>共 {rows.reduce((sum, row) => sum + row.line.quantity, 0)} 件</span><div><small>合计</small><strong>¥{total}</strong><button>去结算</button></div></div></>}</section>;
}

function ProfileView({ mode, level, account, retailPhone, levels }: { mode: Mode; level: LevelCode; account?: WholesaleAccount; retailPhone?: string; levels: WholesaleLevel[] }) {
  const threshold = levels.find((item) => item.code === "b")?.threshold ?? 20000;
  return <section className="inner-page"><div className="profile-card"><span className="profile-avatar">莱</span><div><p>{mode === "retail" ? "莱莎零售会员" : account?.companyName}</p><strong>{mode === "retail" ? `${retailPhone?.replace(/(\d{3})\d{4}(\d{4})/, "$1****$2")} · 手机已验证` : `批发${level.toUpperCase()}等级账户 · 手机已验证`}</strong></div></div>{mode === "wholesale" && <div className="account-detail"><div><span>验证手机号</span><strong>{account?.phone.replace(/(\d{3})\d{4}(\d{4})/, "$1****$2")}</strong></div><div><span>来源销售员</span><strong>{account?.salesPerson}</strong></div><div><span>升级进度</span><strong>{level === "b" ? "已达最高演示等级" : `距批发B还差 ¥${Math.max(0, threshold - 8920).toLocaleString()}`}</strong></div></div>}
    <div className="profile-menu"><a href="#orders"><span>订单</span><b>查看全部订单 ›</b></a><a href="#logistics"><span>物流</span><b>查看物流轨迹 ›</b></a>{mode === "wholesale" && <a href="#sales"><span>专属销售</span><b>联系业务员 ›</b></a>}<a href="#service"><span>客服</span><b>联系莱莎客服 ›</b></a><a href="/admin"><span>演示后台</span><b>管理人员进入 ›</b></a></div>
  </section>;
}

function BottomNav({ prefix, active, cartCount }: { prefix: string; active: View; cartCount: number }) {
  const items: { key: View; href: string; icon: string; label: string }[] = [{ key: "home", href: prefix, icon: "⌂", label: "首页" }, { key: "category", href: `${prefix}/category`, icon: "▦", label: "分类" }, { key: "cart", href: `${prefix}/cart`, icon: "▢", label: "购物车" }, { key: "profile", href: `${prefix}/profile`, icon: "○", label: "我的" }];
  return <nav className="app-bottom-nav separated-nav">{items.map((item) => <a className={active === item.key ? "active" : ""} href={item.href} key={item.key}><i>{item.icon}</i><span>{item.label}</span>{item.key === "cart" && cartCount > 0 && <b>{cartCount}</b>}</a>)}</nav>;
}
