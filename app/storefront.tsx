"use client";

import { useEffect, useMemo, useState } from "react";
import type { LevelCode, Product, WholesaleLevel } from "./lib/types";

const rank: Record<LevelCode, number> = { retail: 0, a: 1, b: 2 };
const roleLabel: Record<LevelCode, string> = { retail: "零售会员", a: "批发 A", b: "批发 B" };

export default function Storefront() {
  const [level, setLevel] = useState<LevelCode>("retail");
  const [products, setProducts] = useState<Product[]>([]);
  const [levels, setLevels] = useState<WholesaleLevel[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([fetch("/api/products").then((r) => r.json()), fetch("/api/levels").then((r) => r.json())])
      .then(([productData, levelData]) => { setProducts(productData.products ?? []); setLevels(levelData.levels ?? []); })
      .finally(() => setLoading(false));
  }, []);

  const activeProducts = useMemo(() => products.filter((product) => product.status === "active"), [products]);
  const getPrice = (product: Product) => level === "retail" ? product.retailPrice : level === "a" ? product.priceA : product.priceB;

  return (
    <main className="app-store">
      <div className="app-frame">
        <header className="app-topbar">
          <a className="app-brand" href="#home" aria-label="莱莎健康假发首页">
            <span className="app-brand-mark">莱</span>
            <span><b>LESHINE</b><small>莱莎健康假发</small></span>
          </a>
          <div className="app-actions"><button aria-label="消息">消息</button><a href="/admin">管理</a></div>
        </header>

        <div className="app-content" id="home">
          <label className="app-search"><span>⌕</span><input aria-label="搜索假发款式" placeholder="搜索款式、长度、颜色" /><button>搜索</button></label>

          <section className="app-hero-card">
            <div className="app-hero-copy">
              <p>34 YEARS OF CARE</p>
              <h1>34年健康假发<br />的坚守者</h1>
              <span>舒适佩戴 · 自然造型 · 山东自有仓</span>
              <a href="#products">立即选款</a>
            </div>
            <div className="app-hero-logo"><img src="/leshine-brand.jpg" alt="LESHINE 莱莎健康假发品牌标识" /></div>
          </section>

          <section className="quick-grid" aria-label="快捷分类">
            <a href="#products"><i>安</i><strong>安心系列</strong><span>自然日常好打理</span></a>
            <a href="#products"><i>气</i><strong>气质系列</strong><span>时尚升级显精神</span></a>
            <a href="#products"><i>光</i><strong>高光系列</strong><span>重要时刻更上镜</span></a>
            <a href="#products"><i>藏</i><strong>臻藏系列</strong><span>专属设计与质感</span></a>
          </section>

          <section className="app-section role-card">
            <div className="app-section-title"><div><span>账户价格</span><h2>切换身份预览</h2></div><small>实际价格按登录账户显示</small></div>
            <div className="app-role-switch" role="group" aria-label="模拟查看等级">
              {(["retail", "a", "b"] as LevelCode[]).map((item) => <button key={item} onClick={() => setLevel(item)} className={level === item ? "active" : ""}><span>{roleLabel[item]}</span><small>{item === "retail" ? "日常购买" : "专属批发价"}</small></button>)}
            </div>
          </section>

          <section className="app-section product-section" id="products">
            <div className="app-section-title"><div><span>RECOMMENDED</span><h2>12款主推发型</h2></div><a href="/retail/category">进入商城</a></div>
            {loading ? <div className="loading-state">正在准备款式…</div> : <div className="product-grid app-product-grid">
              {activeProducts.map((product, index) => {
                const canView = rank[level] >= rank[product.minLevel];
                return <article className={`product-card app-product-card ${!canView ? "locked" : ""}`} key={product.id}>
                  <div className={`product-art ${product.tone}`}><span className="number">{String(index + 1).padStart(2, "0")}</span>{product.images[0] ? <img src={product.images[0]} alt={`${product.name}实拍`} /> : <div className="mini-hair" />}{!canView && <div className="lock-panel"><span>仅{roleLabel[product.minLevel]}可见</span><small>升级后解锁款式与价格</small></div>}</div>
                  <div className="app-product-info"><span className="product-tag">{canView ? product.category : "等级专属"}</span><h3>{canView ? product.name : "批发专属款式"}</h3><p>{canView ? `${product.length} · ${product.color}` : "登录对应等级查看"}</p><div><strong>{canView ? `¥${getPrice(product)}` : "—"}</strong><a className="product-enter" href="/retail/category">›</a></div></div>
                </article>;
              })}
            </div>}
          </section>

          <section className="app-section wholesale-card" id="wholesale">
            <div className="app-section-title light"><div><span>WHOLESALE</span><h2>批发等级权益</h2></div><small>累计净采购自动升级</small></div>
            <div className="app-level-list">{levels.map((item, index) => <article key={item.code}><i>0{index + 1}</i><div><strong>{item.name}</strong><span>{item.code === "retail" ? "新人默认等级，享受零售权益" : `累计采购满 ¥${item.threshold.toLocaleString()} 自动升级`}</span></div><b>›</b></article>)}</div>
          </section>

          <section className="service-strip"><div><b>✓</b><span>山东自有仓</span></div><div><b>✓</b><span>专业客服选款</span></div><div><b>✓</b><span>物流轨迹可查</span></div></section>
        </div>

        <nav className="app-bottom-nav" aria-label="底部导航">
          <a className="active" href="#home"><i>⌂</i><span>首页</span></a>
          <a href="#products"><i>▦</i><span>分类</span></a>
          <a href="#wholesale"><i>◇</i><span>批发</span></a>
          <a href="#products"><i>▢</i><span>购物车</span></a>
          <a href="/admin"><i>○</i><span>我的</span></a>
        </nav>
      </div>
    </main>
  );
}
