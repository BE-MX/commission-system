"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import type { LevelCode, Product, WholesaleLevel } from "../lib/types";

const emptyProduct: Omit<Product, "id" | "createdAt"> = {
  name: "", material: "真人发", length: "45cm", color: "自然黑", retailPrice: 0,
  priceA: 0, priceB: 0, minLevel: "retail", stock: 0, status: "active", tone: "espresso",
};
const levelName: Record<LevelCode, string> = { retail: "所有客户", a: "批发A及以上", b: "仅批发B" };

type Tab = "products" | "levels" | "customers";

export default function AdminPage() {
  const [tab, setTab] = useState<Tab>("products");
  const [products, setProducts] = useState<Product[]>([]);
  const [levels, setLevels] = useState<WholesaleLevel[]>([]);
  const [editing, setEditing] = useState<Product | null>(null);
  const [form, setForm] = useState<Omit<Product, "id" | "createdAt">>(emptyProduct);
  const [modalOpen, setModalOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState("");

  const load = async () => {
    const [p, l] = await Promise.all([fetch("/api/products").then((r) => r.json()), fetch("/api/levels").then((r) => r.json())]);
    setProducts(p.products ?? []); setLevels(l.levels ?? []);
  };
  useEffect(() => { load(); }, []);

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

  return (
    <div className="admin-shell">
      <aside className="admin-sidebar">
        <a className="brand admin-brand" href="/"><span className="brand-mark">云</span><span>云鬓管理台</span></a>
        <div className="admin-menu-label">经营管理</div>
        <button className={tab === "products" ? "selected" : ""} onClick={() => setTab("products")}><span>款</span>商品与款式</button>
        <button className={tab === "levels" ? "selected" : ""} onClick={() => setTab("levels")}><span>级</span>批发等级</button>
        <button className={tab === "customers" ? "selected" : ""} onClick={() => setTab("customers")}><span>客</span>批发商账户</button>
        <div className="admin-menu-label secondary-label">其他模块</div>
        <button disabled><span>单</span>订单发货 <i>规划中</i></button>
        <button disabled><span>销</span>销售推广 <i>规划中</i></button>
        <a className="back-store" href="/">← 返回店铺访问端</a>
      </aside>

      <main className="admin-main">
        <header className="admin-top"><div><small>山东自营仓 · 演示环境</small><strong>管理员</strong></div><span className="admin-avatar">管</span></header>
        {notice && <div className="notice" role="status">{notice}<button onClick={() => setNotice("")}>×</button></div>}

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
            <div className="product-table-wrap"><table className="product-table"><thead><tr><th>款式</th><th>零售价</th><th>批发A</th><th>批发B</th><th>查看权限</th><th>库存</th><th>状态</th><th>操作</th></tr></thead><tbody>
              {products.map((product) => <tr key={product.id}>
                <td><div className={`table-art ${product.tone}`}><div className="tiny-hair" /></div><div><strong>{product.name}</strong><small>{product.material} · {product.length} · {product.color}</small></div></td>
                <td>¥{product.retailPrice}</td><td>¥{product.priceA}</td><td>¥{product.priceB}</td>
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
          <div className="admin-title"><div><p>客户管理</p><h1>批发商账户与销售来源</h1><span>查看客户等级、累计采购和来源销售员</span></div></div>
          <section className="admin-panel"><div className="panel-head"><div><strong>演示账户</strong><span>正式版将从真实订单自动累计</span></div></div>
            <div className="product-table-wrap"><table className="product-table customer-table"><thead><tr><th>批发商</th><th>当前等级</th><th>累计净采购</th><th>来源销售员</th><th>首次进入</th><th>备注</th></tr></thead><tbody>
              <tr><td><strong>青岛尚美发制品</strong><small>138****2031</small></td><td><span className="access-pill b">批发B</span></td><td>¥28,650</td><td>销售员 · 李娜</td><td>2026-08-03</td><td>长期客户</td></tr>
              <tr><td><strong>济南悦己造型</strong><small>186****7712</small></td><td><span className="access-pill a">批发A</span></td><td>¥8,920</td><td>销售员 · 王海</td><td>2026-08-11</td><td>关注短发款</td></tr>
              <tr><td><strong>临沂优发门店</strong><small>152****4486</small></td><td><span className="access-pill retail">零售会员</span></td><td>¥2,180</td><td>销售员 · 李娜</td><td>2026-08-17</td><td>待跟进升级</td></tr>
            </tbody></table></div>
          </section>
        </>}
      </main>

      {modalOpen && <div className="modal-backdrop" onMouseDown={() => setModalOpen(false)}>
        <form className="product-modal" onSubmit={saveProduct} onMouseDown={(event) => event.stopPropagation()}>
          <div className="modal-head"><div><small>{editing ? "编辑商品" : "新增商品"}</small><h2>{editing ? editing.name : "添加假发款式"}</h2></div><button type="button" onClick={() => setModalOpen(false)} aria-label="关闭">×</button></div>
          <div className="form-grid">
            <label className="wide">款式名称<input required value={form.name} onChange={(e) => updateForm("name", e.target.value)} placeholder="例如：自然头皮直发" /></label>
            <label>材质<select value={form.material} onChange={(e) => updateForm("material", e.target.value)}><option>真人发</option><option>高温丝</option><option>真人发混合</option></select></label>
            <label>长度<input value={form.length} onChange={(e) => updateForm("length", e.target.value)} placeholder="45cm" /></label>
            <label>颜色<input value={form.color} onChange={(e) => updateForm("color", e.target.value)} placeholder="自然黑" /></label>
            <label>库存数量<input type="number" min="0" value={form.stock} onChange={(e) => updateForm("stock", Number(e.target.value))} /></label>
            <label>零售价（元）<input type="number" min="0" required value={form.retailPrice} onChange={(e) => updateForm("retailPrice", Number(e.target.value))} /></label>
            <label>批发A价（元）<input type="number" min="0" required value={form.priceA} onChange={(e) => updateForm("priceA", Number(e.target.value))} /></label>
            <label>批发B价（元）<input type="number" min="0" required value={form.priceB} onChange={(e) => updateForm("priceB", Number(e.target.value))} /></label>
            <label>展示色调<select value={form.tone} onChange={(e) => updateForm("tone", e.target.value)}><option value="espresso">自然黑</option><option value="honey">蜜茶棕</option><option value="chestnut">栗棕色</option><option value="charcoal">灰黑色</option></select></label>
            <label className="wide">最低查看等级<select value={form.minLevel} onChange={(e) => updateForm("minLevel", e.target.value)}><option value="retail">所有客户可见</option><option value="a">批发A及以上可见</option><option value="b">仅批发B可见</option></select><small>低于该等级的客户只能看到“批发专属款式”，无法看到名称和价格。</small></label>
          </div>
          {notice && <p className="form-error">{notice}</p>}
          <div className="modal-actions"><button type="button" className="cancel" onClick={() => setModalOpen(false)}>取消</button><button className="admin-primary" disabled={saving}>{saving ? "保存中…" : "保存款式"}</button></div>
        </form>
      </div>}
    </div>
  );
}
