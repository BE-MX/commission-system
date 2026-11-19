"use client";
import { CAP_TYPES, allowedLengths, initialVariants, option, type ProductVariant } from "../lib/product-options";

export function ProductOptions({ variants, value, onChange }: { variants: ProductVariant[]; value: string; onChange: (key: string) => void }) {
  const selected = variants.find((item) => item.key === value);
  const active = variants.filter((item) => item.enabled);
  const caps = [...new Set(active.map((item) => item.cap))];
  const lengths = [...new Set(active.filter((item) => item.cap === selected?.cap).map((item) => item.length))].sort((a,b) => a-b);
  return <div className="product-options">
    <fieldset><legend>选择网底</legend><div>{caps.map((cap) => <button type="button" key={cap} aria-pressed={selected?.cap === cap} onClick={() => { const match = active.find((item) => item.cap === cap && item.length === selected?.length) ?? active.find((item) => item.cap === cap); if (match) onChange(match.key); }}>{cap}</button>)}</div></fieldset>
    <fieldset><legend>选择长度</legend><div>{lengths.map((length) => { const variant = active.find((item) => item.cap === selected?.cap && item.length === length)!; return <button type="button" key={length} aria-pressed={selected?.length === length} onClick={() => onChange(variant.key)}>{length}厘米{variant.price === null ? " · 待定价" : ""}</button>; })}</div></fieldset>
    <p aria-live="polite">{selected ? `已选：${selected.cap} · ${selected.length}厘米` : "该款尚未开放可选规格，请联系客服。"}{selected?.price === null ? "，请等待该规格价格确认。" : ""}</p>
  </div>;
}

export function VariantEditor({ referenceLength, value = [], onChange }: { referenceLength: string; value?: ProductVariant[]; onChange: (variants: ProductVariant[]) => void }) {
  const lengths = allowedLengths(referenceLength);
  const update = (key: string, patch: Partial<ProductVariant>) => onChange(value.map((item) => item.key === key ? { ...item, ...patch } : item));
  return <section className="variant-editor wide"><h3>本款网底、长度及价格</h3>
    <p>只显示本款实际可售的组合。短发、中长发、长发不混用长度；未定价的组合不能下单。库存沿用本款总库存，不重复增加。</p>
    <button type="button" onClick={() => { if (!value.length || window.confirm("重新生成会覆盖当前规格和价格，确定继续？")) onChange(initialVariants(referenceLength)); }}>按本款参考长度生成规格</button>
    <div className="variant-add">{lengths.map((length) => <button type="button" key={length} onClick={() => onChange([...value, ...CAP_TYPES.filter((cap) => !value.some((item) => item.cap === cap && item.length === length)).map((cap) => option(cap,length))])}>添加 {length}厘米规格</button>)}</div>
    {value.map((item) => <div className="variant-row" key={item.key}><label><input type="checkbox" checked={item.enabled} onChange={(event) => update(item.key,{ enabled:event.target.checked })} />开放</label><strong>{item.cap} · {item.length}厘米</strong><label>价格（元）<input type="number" min="0.01" step="0.01" value={item.price ?? ""} placeholder="待定价" onChange={(event) => update(item.key,{ price:event.target.value === "" ? null : Number(event.target.value) })} /></label><button type="button" onClick={() => onChange(value.filter((entry) => entry.key !== item.key))}>移除</button></div>)}
  </section>;
}
