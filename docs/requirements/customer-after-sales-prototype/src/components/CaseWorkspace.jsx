import { useMemo, useRef, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  BellRinging,
  Check,
  CheckCircle,
  ClipboardText,
  Clock,
  Copy,
  FilePdf,
  Info,
  MagicWand,
  NotePencil,
  Paperclip,
  Play,
  ShieldCheck,
  Sparkle,
  UploadSimple,
  UserCircleCheck,
  Warning,
  X,
} from "@phosphor-icons/react";
import { compensationAction, nonCompensationAction, stages } from "../data.js";

const statusLabels = {
  decision: "待业务选择",
  supervisor: "待直属主管初审",
  director: "待销售总监终审",
  approved: "审批完成",
  closed: "已关闭",
};

const compensationReply = `Thank you for sharing the photos and video. We understand your concern about the color fading after around three weeks of use. Since #2B can be more sensitive to fading, we will also review the care products, heat exposure, and batch details internally. Based on the information available, we are proposing to replace two affected packs and cover the resend freight, subject to final internal approval. Once approved, we will confirm the replacement delivery timeline with you.`;

const inspectionReply = `Thank you for sharing the photos and video. We understand your concern about the color fading after around three weeks of use. Since #2B can be more sensitive to fading, we would first like to review the care products, heat exposure, and batch details before confirming the cause. We suggest returning the affected hair for inspection. After the inspection, we will provide a clear responsibility assessment and the next solution.`;

function StageBar({ stage, hasCompensation }) {
  const indexMap = { decision: 2, supervisor: 3, director: 4, approved: 4, closed: 5 };
  const current = indexMap[stage] ?? 2;
  return (
    <div className="stage-bar" aria-label="售后处理进度">
      {stages.map((item, index) => {
        const skipped = item.code === "director" && !hasCompensation;
        const done = index < current || (stage === "approved" && index === 4) || stage === "closed";
        const active = index === current && stage !== "closed";
        return (
          <div className={`stage ${done ? "done" : ""} ${active ? "active" : ""}`} key={item.code}>
            <span className="stage-dot">{done ? <Check size={14} weight="bold" /> : index + 1}</span>
            <span><strong>{item.label}</strong><small>{skipped ? "无需终审" : done ? "已完成" : active ? "当前节点" : "待处理"}</small></span>
          </div>
        );
      })}
    </div>
  );
}

function EvidenceGallery({ uploads, onUpload, locked }) {
  const uploadRef = useRef(null);
  return (
    <section className="content-section evidence-section">
      <div className="section-title-row">
        <div><h2>证据材料</h2><p>系统已检查 6 项证据要求，当前完成 5 项</p></div>
        <button className="button tertiary" type="button" disabled={locked} title={locked ? "审核中不可修改证据" : "添加证据"} onClick={() => uploadRef.current?.click()}>
          <UploadSimple size={16} /> 添加证据
        </button>
        <input ref={uploadRef} className="visually-hidden" type="file" accept="image/*,video/*,.pdf" onChange={onUpload} />
      </div>
      <div className="evidence-tabs"><button className="active" type="button">图片 4</button><button type="button">视频 1</button><button type="button">文件 1</button></div>
      <div className="evidence-grid">
        <figure><img src="/evidence-color-fading.png" alt="问题近景：发色褪色" /><figcaption>问题近景.jpg <CheckCircle size={15} weight="fill" /></figcaption></figure>
        <figure><img className="crop-alt" src="/evidence-color-fading.png" alt="自然光色差对比" /><figcaption>自然光对比.jpg <CheckCircle size={15} weight="fill" /></figcaption></figure>
        <figure><img src="/evidence-batch-label.png" alt="产品批次标签" /><figcaption>批次标签.jpg <CheckCircle size={15} weight="fill" /></figcaption></figure>
        <figure className="video-thumb"><img className="crop-video" src="/evidence-color-fading.png" alt="褪色视频缩略图" /><span><Play size={22} weight="fill" /></span><figcaption>褪色视频.mp4 <CheckCircle size={15} weight="fill" /></figcaption></figure>
        <figure className="file-thumb"><div><FilePdf size={34} weight="duotone" /><span>PDF</span></div><figcaption>客户反馈附件.pdf <CheckCircle size={15} weight="fill" /></figcaption></figure>
        {uploads.map((item) => (
          <figure key={item.name}><img src={item.url} alt={`新增证据 ${item.name}`} /><figcaption>{item.name}<CheckCircle size={15} weight="fill" /></figcaption></figure>
        ))}
      </div>
    </section>
  );
}

function AiRecommendation({ action, setAction, analyzing, onAnalyze, stage, locked, reply, setReply, onNotify }) {
  const canCopy = stage === "approved" || stage === "closed";

  async function copyReply() {
    await navigator.clipboard.writeText(reply);
    onNotify("英文话术已复制", "可粘贴到邮件或 WhatsApp；请按实际执行结果发送");
  }

  return (
    <aside className="decision-panel">
      <div className="panel-heading">
        <div><p className="eyebrow">基于售后 SOP V1.0</p><h2><Sparkle size={21} weight="fill" /> AI 分析与建议</h2></div>
        <button className="button tertiary" type="button" disabled={analyzing || locked} title={locked ? "审核中不可重新分析" : "重新分析"} onClick={onAnalyze}><MagicWand size={16} />{analyzing ? "分析中" : "重新分析"}</button>
      </div>
      {analyzing ? (
        <div className="analysis-loading" role="status">
          <span className="spinner" />
          <strong>正在对照 SOP 生成建议</strong>
          <p>检查证据 → 匹配条款 → 生成处理措施</p>
        </div>
      ) : (
        <>
          <div className="analysis-summary">
            <div><span>证据完整度</span><strong>80%</strong><progress max="100" value="80">80%</progress><small>已满足最低要求 · 建议补充洗护产品</small></div>
            <div><span>初步责任判定</span><strong className="class-d">D类</strong><small>责任暂不明确 · 置信度 72%</small></div>
          </div>
          <div className="risk-block"><Warning size={19} weight="fill" /><div><strong>中风险</strong><p>#2B 为高风险色号，尚未排除洗护产品、高温或长期使用导致的褪色。</p></div></div>
          <div className="sop-block">
            <div className="block-title"><BookMarkIcon /> SOP 引用依据</div>
            <button type="button"><span>《售后问题解决 SOP》</span><strong>褪色 / 变色问题 §2</strong><ArrowRight size={15} /></button>
            <p>应先区分 fading 与 color changing；证据不足时不做赔付承诺。</p>
          </div>
          <div className="actions-block">
            <div className="block-title"><ClipboardText size={18} /> 推荐处理措施 <small>业务员最终决定</small></div>
            {[nonCompensationAction, compensationAction].map((item) => (
              <label className={`action-option ${action.code === item.code ? "selected" : ""}`} key={item.code}>
                <input type="radio" name="action" disabled={locked} checked={action.code === item.code} onChange={() => setAction(item)} />
                <span><strong>{item.title}</strong><small>{item.description}</small></span>
                <em className={item.hasCompensation ? "comp" : "no-comp"}>{item.hasCompensation ? `预计 USD ${item.amount}` : "不涉及赔偿"}</em>
              </label>
            ))}
          </div>
          <div className="customer-reply-block">
            <div className="reply-heading">
              <div className="block-title"><NotePencil size={18} /> 英文客户回复话术 <span className="language-badge">AI 基于 SOP 生成</span></div>
              <button className="copy-reply" type="button" disabled={!canCopy} title={canCopy ? "复制英文话术" : "最终审批通过后才可复制"} onClick={copyReply}>
                <Copy size={15} />{canCopy ? "复制话术" : "审批后可复制"}
              </button>
            </div>
            <textarea aria-label="英文客户回复话术" disabled={locked} value={reply} onChange={(event) => setReply(event.target.value)} />
            <p>{locked ? "审核中已锁定；退回业务员后才能修改。" : "当前为客户回复草稿，可在提交审批前修改；赔偿承诺以最终审批为准。"}</p>
          </div>
          <div className="inline-route">
            <div className="block-title"><ShieldCheck size={18} /> 审批路线 <small>{action.hasCompensation ? `预计赔偿 USD ${action.amount}` : "不涉及赔偿"}</small></div>
            {action.hasCompensation ? <div className="compensation-breakdown"><span><small>补偿构成</small><strong>换货成本 360 + 运费 60</strong></span><span><small>问题产品货值</small><strong>USD 1,150 · 赔偿比例 36.5%</strong></span></div> : null}
            <div className="inline-route-nodes">
              <span className={stage === "supervisor" ? "current" : ""}><UserCircleCheck size={18} /><strong>直属主管 Lisa</strong><small>{stage === "supervisor" ? "当前待审核" : stage === "decision" ? "提交后初审" : "已通过"}</small></span>
              <ArrowRight size={17} />
              <span className={`${!action.hasCompensation ? "skipped" : ""} ${stage === "director" ? "current" : ""}`}><ShieldCheck size={18} /><strong>销售总监 Olivia</strong><small>{!action.hasCompensation ? "无需终审" : stage === "director" ? "当前待终审" : stage === "decision" || stage === "supervisor" ? "主管通过后终审" : "已通过"}</small></span>
            </div>
          </div>
          <div className="ai-disclaimer"><Info size={16} />AI 建议仅供决策；提交前由业务员确认，客户承诺以最终审批为准。</div>
        </>
      )}
    </aside>
  );
}

function BookMarkIcon() {
  return <Paperclip size={18} />;
}

export function CaseWorkspace({ caseItem, onBack }) {
  const [action, setAction] = useState(compensationAction);
  const [stage, setStage] = useState("decision");
  const [role, setRole] = useState("sales");
  const [analyzing, setAnalyzing] = useState(false);
  const [editing, setEditing] = useState(false);
  const [uploads, setUploads] = useState([]);
  const [reply, setReply] = useState(compensationReply);
  const [toast, setToast] = useState(null);

  const stageLabel = statusLabels[stage];
  const primary = useMemo(() => {
    if (stage === "decision") return { label: "提交直属主管审核", role: "sales" };
    if (stage === "supervisor") return { label: "主管审核通过", role: "supervisor" };
    if (stage === "director") return { label: "销售总监终审通过", role: "director" };
    if (stage === "approved") return { label: "登记执行结果并关闭", role: "sales" };
    return null;
  }, [stage]);

  function notify(message, detail) {
    setToast({ message, detail });
    window.setTimeout(() => setToast(null), 4200);
  }

  function handlePrimary() {
    if (!primary || role !== primary.role) return;
    if (stage === "decision") {
      setEditing(false);
      setStage("supervisor");
      setRole("supervisor");
      notify("已提交直属主管初审", "钉钉工作通知已发送给 Lisa");
    } else if (stage === "supervisor") {
      if (action.hasCompensation) {
        setStage("director");
        setRole("director");
        notify("主管审核已通过", "涉及赔偿，已通知销售总监 Olivia 终审");
      } else {
        setStage("approved");
        setRole("sales");
        notify("最终审批已通过", "不涉及赔偿，主管审核即完成；已通知 Derek");
      }
    } else if (stage === "director") {
      setStage("approved");
      setRole("sales");
      notify("销售总监终审已通过", `批准赔偿 USD ${action.amount.toFixed(2)}，已通知 Derek`);
    } else if (stage === "approved") {
      setStage("closed");
      notify("售后单已关闭", "执行结果与客户反馈已进入复盘数据");
    }
  }

  function handleActionChange(next) {
    if (stage !== "decision") return;
    setAction(next);
    setReply(next.hasCompensation ? compensationReply : inspectionReply);
  }

  function handleAnalyze() {
    setAnalyzing(true);
    window.setTimeout(() => {
      setAnalyzing(false);
      notify("AI 建议已更新", "已引用售后 SOP V1.0：褪色 / 变色问题 §2");
    }, 1400);
  }

  function handleUpload(event) {
    const file = event.target.files?.[0];
    if (!file) return;
    if (file.type.startsWith("image/")) {
      setUploads((current) => [...current, { name: file.name, url: URL.createObjectURL(file) }]);
      notify("证据已添加", `${file.name} 已加入当前售后单`);
    } else {
      notify("文件已添加", `${file.name} 已加入附件列表`);
    }
    event.target.value = "";
  }

  return (
    <section className="workspace">
      {toast ? <div className="toast" role="status"><BellRinging size={21} weight="fill" /><div><strong>{toast.message}</strong><span>{toast.detail}</span></div><button type="button" onClick={() => setToast(null)} aria-label="关闭提示"><X size={16} /></button></div> : null}
      <header className="workspace-header">
        <div><button className="back-button" type="button" onClick={onBack}><ArrowLeft size={16} /> 返回售后单</button><div className="case-title"><h1>售后案例 {caseItem.id}</h1><span className={`status ${stage === "closed" ? "success" : "warning"}`}>{stageLabel}</span></div><p>登记事实、对照 SOP、确认处理措施并完成分级审批</p></div>
        <div className="header-actions">
          <label className="role-switch"><span>演示身份</span><select value={role} onChange={(event) => setRole(event.target.value)}><option value="sales">业务员 Derek</option><option value="supervisor">直属主管 Lisa</option><option value="director">销售总监 Olivia</option></select></label>
          <button className="button secondary" type="button" disabled={stage !== "decision"} title={stage !== "decision" ? "审核中不可修改登记信息" : "编辑登记信息"} onClick={() => setEditing((value) => !value)}><NotePencil size={16} />{editing ? "完成编辑" : "编辑登记信息"}</button>
        </div>
      </header>

      <StageBar stage={stage} hasCompensation={action.hasCompensation} />

      <div className="workspace-grid">
        <main className="case-content">
          <section className="content-section facts-section">
            <div className="section-title-row"><div><h2>客户与订单信息</h2><p>数据来自业务库，提交时保存快照</p></div><span className="grade-badge">A 级客户</span></div>
            <div className="facts-grid">
              <label><span>客户名称</span>{editing ? <input defaultValue="Samantha Harrison" /> : <strong>Samantha Harrison</strong>}</label>
              <label><span>订单号</span>{editing ? <input defaultValue="XM-250618-1842" /> : <strong>XM-250618-1842</strong>}</label>
              <label><span>购买日期</span>{editing ? <input type="date" defaultValue="2026-06-18" /> : <strong>2026-06-18</strong>}</label>
              <label><span>反馈日期</span>{editing ? <input type="date" defaultValue="2026-07-10" /> : <strong>2026-07-10</strong>}</label>
            </div>
          </section>

          <section className="content-section product-section">
            <div className="section-title-row"><div><h2>产品与问题信息</h2><p>标准产品已匹配，批次号由业务员确认</p></div><span className="matched"><CheckCircle size={16} weight="fill" /> 已匹配订单产品</span></div>
            <div className="product-card">
              <img src="/product-invisible-weft.png" alt="Invisible Weft #2B 产品" />
              <div className="product-facts">
                <label><span>产品型号</span>{editing ? <input defaultValue="Invisible Weft" /> : <strong>Invisible Weft</strong>}</label>
                <label><span>库存批次号</span>{editing ? <input defaultValue="LSA-260618-02" /> : <strong>LSA-260618-02</strong>}</label>
                <label><span>颜色</span>{editing ? <input defaultValue="#2B" /> : <strong>#2B</strong>}</label>
                <label><span>长度 / 克重</span>{editing ? <input defaultValue="22英寸 / 100g" /> : <strong>22英寸 / 100g</strong>}</label>
                <label><span>数量</span>{editing ? <input type="number" defaultValue="5" /> : <strong>5 包</strong>}</label>
                <label><span>涉及产品货值</span>{editing ? <input defaultValue="USD 1,150.00" /> : <strong>USD 1,150.00</strong>}</label>
              </div>
            </div>
            <div className="issue-description"><span>问题类型</span><strong>褪色</strong><p>客户反馈使用约 3 周后出现明显褪色，#2B 颜色变浅且局部发黄，影响终端客户继续佩戴。</p></div>
          </section>

          <EvidenceGallery uploads={uploads} onUpload={handleUpload} locked={stage !== "decision"} />
        </main>

        <AiRecommendation action={action} setAction={handleActionChange} analyzing={analyzing} onAnalyze={handleAnalyze} stage={stage} locked={stage !== "decision"} reply={reply} setReply={setReply} onNotify={notify} />
      </div>

      <footer className="sticky-actions">
        <div><Clock size={18} /><span>{stage === "decision" ? "保存于 2026-07-10 14:32" : `当前状态：${stageLabel}`}</span></div>
        <div>
          {stage === "supervisor" || stage === "director" ? <button className="button secondary" type="button" onClick={() => { setStage("decision"); setRole("sales"); notify("已退回业务员补充", "已通知 Derek 补充证据和处理说明"); }}>退回补充</button> : stage === "decision" ? <button className="button secondary" type="button">保存草稿</button> : <button className="button secondary" type="button">查看审计记录</button>}
          {primary ? <button className="button primary" type="button" disabled={role !== primary.role || analyzing} onClick={handlePrimary}>{primary.label}<ArrowRight size={17} weight="bold" /></button> : <span className="closed-state"><CheckCircle size={20} weight="fill" /> 单据已完成闭环</span>}
        </div>
      </footer>
    </section>
  );
}
