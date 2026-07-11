import {
  ArrowRight,
  Clock,
  FunnelSimple,
  MagnifyingGlass,
  Plus,
} from "@phosphor-icons/react";
import { cases } from "../data.js";

function statusTone(status) {
  if (status.includes("退回")) return "danger";
  if (status.includes("处理")) return "success";
  if (status.includes("主管")) return "warning";
  return "neutral";
}
export function CaseList({ reviewOnly = false, onOpenCase }) {
  const rows = reviewOnly ? cases.filter((item) => item.status.includes("主管")) : cases;
  return (
    <section className="list-page">
      <header className="page-heading list-heading">
        <div>
          <p className="eyebrow">售后管理</p>
          <h1>{reviewOnly ? "待我审核" : "客户售后单"}</h1>
          <p>{reviewOnly ? "聚焦需要你判断的事实、SOP依据和赔偿风险" : "统一登记、判断、审批和跟进客户售后问题"}</p>
        </div>
        {!reviewOnly ? (
          <button className="button primary" type="button" onClick={() => onOpenCase(cases[0])}>
            <Plus size={17} weight="bold" /> 新建售后单
          </button>
        ) : null}
      </header>

      <div className="filter-bar">
        <label className="search-box">
          <MagnifyingGlass size={17} />
          <input aria-label="搜索售后单" defaultValue="" placeholder="搜索单号 / 客户 / 订单" />
        </label>
        <select aria-label="状态"><option>全部状态</option><option>待业务选择</option><option>待主管审核</option></select>
        <select aria-label="问题类型"><option>全部问题</option><option>褪色</option><option>断发</option></select>
        <select aria-label="是否赔偿"><option>是否赔偿</option><option>涉及赔偿</option><option>不涉及赔偿</option></select>
        <button className="button secondary" type="button"><FunnelSimple size={16} /> 筛选</button>
      </div>

      <div className="table-card">
        <table className="case-table">
          <thead>
            <tr>
              <th>售后单号</th><th>客户</th><th>问题</th><th>证据</th><th>责任判定</th><th>处理措施</th><th>赔偿成本</th><th>状态</th><th>等待</th><th>操作</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((item) => (
              <tr key={item.id}>
                <td><button className="table-link" type="button" onClick={() => onOpenCase(item)}>{item.id}</button></td>
                <td><strong>{item.customer}</strong><span className="cell-sub">{item.orderNo}</span></td>
                <td>{item.issue}<span className="cell-sub">{item.product}</span></td>
                <td><span className={`score ${item.evidenceScore === 100 ? "complete" : "partial"}`}>{item.evidenceScore}%</span></td>
                <td><span className="responsibility-tag">{item.responsibility}</span></td>
                <td>{item.action}</td>
                <td>{item.compensation ? `USD ${item.compensation.toFixed(2)}` : "—"}</td>
                <td><span className={`status ${statusTone(item.status)}`}>{item.status}</span></td>
                <td><span className="wait-time"><Clock size={14} />{item.wait}</span></td>
                <td><button className="table-action" type="button" onClick={() => onOpenCase(item)}>查看 <ArrowRight size={14} /></button></td>
              </tr>
            ))}
          </tbody>
        </table>
        <footer className="table-footer">共 {rows.length} 条 <span>1 / 1 页</span></footer>
      </div>
    </section>
  );
}
