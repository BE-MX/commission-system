"use client";

import { useEffect, useMemo, useState } from "react";
import type { LevelCode, Product, WholesaleLevel } from "./lib/types";

const rank: Record<LevelCode, number> = { retail: 0, a: 1, b: 2 };
const roleLabel: Record<LevelCode, string> = { retail: "零售", a: "批发A", b: "批发B" };

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
    <main>
      <header className="site-header">
        <a className="brand" href="#top" aria-label="莱莎健康假发首页"><span className="brand-mark">莱</span><span><b>LESHINE</b>莱莎健康假发</span></a>
        <nav aria-label="主导航"><a href="#products">全部款式</a><a href="#levels">批发权益</a><a href="/admin" className="admin-link">管理后台</a></nav>
      </header>

      <section className="hero" id="top">
        <div className="hero-copy">
          <p className="eyebrow">LESHINE HEALTH HAIR</p>
          <h1>34年，<br />专注健康假发。</h1>
          <p className="hero-text">从舒适佩戴到自然造型，莱莎坚持为每一位顾客提供更安心的健康假发。零售与专业批发价格，按账户等级清晰可见。</p>
          <div className="hero-actions"><a className="button primary" href="#products">浏览本季款式</a><a className="button secondary" href="#levels">了解批发等级</a></div>
          <div className="trust-row"><span>山东自有仓发货</span><span>专业客服选款</span><span>物流轨迹可查</span></div>
        </div>
        <div className="hero-visual" aria-label="莱莎健康假发品牌标识"><img src="/leshine-brand.jpg" alt="LESHINE 莱莎健康假发，34年健康假发的坚守者" /><div className="hero-note"><strong>LESHINE</strong><span>34年健康假发的坚守者</span></div></div>
      </section>

      <section className="catalog" id="products">
        <div className="section-heading">
          <div><p className="eyebrow">SELECTED STYLES</p><h2>本季精选款式</h2></div>
          <div className="level-switch" role="group" aria-label="模拟查看等级"><span>预览身份</span>{(["retail", "a", "b"] as LevelCode[]).map((item) => <button key={item} onClick={() => setLevel(item)} className={level === item ? "active" : ""}>{roleLabel[item]}</button>)}</div>
        </div>

        {loading ? <div className="loading-state">正在准备款式…</div> : (
          <div className="product-grid">
            {activeProducts.map((product, index) => {
              const canView = rank[level] >= rank[product.minLevel];
              return (
                <article className={`product-card ${!canView ? "locked" : ""}`} key={product.id}>
                  <div className={`product-art ${product.tone}`}><span className="number">{String(index + 1).padStart(2, "0")}</span><div className="mini-hair" />{!canView && <div className="lock-panel"><span>仅{roleLabel[product.minLevel]}可见</span><small>升级后解锁款式与价格</small></div>}</div>
                  <div className="product-info"><div><h3>{canView ? product.name : "批发专属款式"}</h3><p>{canView ? `${product.material} · ${product.length} · ${product.color}` : "登录对应等级账户查看"}</p></div><strong>{canView ? `¥${getPrice(product)}` : "—"}</strong></div>
                </article>
              );
            })}
          </div>
        )}
      </section>

      <section className="level-band" id="levels">
        <div><p className="eyebrow">WHOLESALE LEVELS</p><h2>采购越稳定，价格越有优势</h2></div>
        <div className="level-cards">{levels.map((item, index) => <article key={item.code}><span>0{index + 1}</span><h3>{item.name}</h3><p>{item.code === "retail" ? "享受零售价与新人专享福利" : `累计净采购满 ¥${item.threshold.toLocaleString()}，自动解锁对应价格与款式`}</p></article>)}</div>
      </section>
    </main>
  );
}
