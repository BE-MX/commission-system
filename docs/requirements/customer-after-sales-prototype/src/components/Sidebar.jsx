import {
  BellSimple,
  BookOpenText,
  CaretDown,
  ChartLineUp,
  ClipboardText,
  House,
  Invoice,
  ListChecks,
  Package,
  ShieldCheck,
} from "@phosphor-icons/react";

const nav = [
  { label: "工作台", icon: House },
  { label: "订单管理", icon: Invoice },
  { label: "订单发票", icon: Package },
  { label: "同步日志", icon: ListChecks },
];

const aftersales = [
  { label: "售后单", icon: ClipboardText, key: "cases" },
  { label: "待我审核", icon: ShieldCheck, key: "review", badge: 3 },
  { label: "SOP管理", icon: BookOpenText },
  { label: "售后分析", icon: ChartLineUp },
];

export function Sidebar({ activeView, onNavigate }) {
  return (
    <aside className="sidebar">
      <div className="brand">LeShine Ark</div>
      <nav aria-label="主导航">
        {nav.map(({ label, icon: Icon }) => (
          <button className="nav-item" type="button" key={label}>
            <Icon size={18} weight="duotone" />
            <span>{label}</span>
          </button>
        ))}
        <p className="nav-section">售后管理</p>
        {aftersales.map(({ label, icon: Icon, key, badge }) => (
          <button
            className={`nav-item ${key && activeView === key ? "active" : ""}`}
            type="button"
            key={label}
            onClick={() => key && onNavigate(key)}
          >
            <Icon size={18} weight={key && activeView === key ? "fill" : "duotone"} />
            <span>{label}</span>
            {badge ? <span className="nav-badge">{badge}</span> : null}
          </button>
        ))}
      </nav>
      <div className="sidebar-user">
        <div className="avatar">DE</div>
        <div>
          <strong>Derek</strong>
          <span>业务员</span>
        </div>
        <BellSimple size={17} />
        <CaretDown size={14} />
      </div>
    </aside>
  );
}
