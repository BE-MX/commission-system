# 客户工作台 · 评审入口

这是一套基于当前客户经营代码核查、经 CWC 规划的开发文档和独立交互原型。最终审查状态见 `acceptance.md`。

## 阅读顺序

1. `index.html`：先体验六类能力及关键状态。
2. `development-spec.md`：需求、权限、规则、实现落点和分期。
3. `api-contracts.md`：现有/拟新增接口、请求响应、错误及幂等。
4. `schema-migrations.md`：数据对象、约束、回填和切换。
5. `product-plan.md`：完整功能复盘与产品论证。
6. `acceptance.md`：场景、真实测试结果与未验证边界。

## 运行与操作

无需安装依赖。推荐在本目录运行：

```powershell
python -m http.server 8766 --bind 127.0.0.1
```

打开 `http://127.0.0.1:8766`。页面仅本地运行，没有真实客户信息、生产 API、外部 CDN、自动发送或实际抓取。固定演示时点是 2026-09-24 09:00 北京时间。浏览器存储记录操作；“重置”恢复示例，存储不可用时提示内存模式。也可用系统浏览器打开本地 index.html（本轮自动化浏览器不允许 file 协议，未自动验证这条打开方式）。

建议体验：今日任务登记结果并安排后续 → 画像建议采纳 → 切换 Velvet Crown 体验修订冲突 → Solace 会话绑定和重新分析 → Aurelia 订单及新单覆盖 → 门店事件确认 → Novelle 样品改约 → 新品/优惠名单排除。

源码职责：`data.js` 为六类合成客户情境，`domain.js` 为可测试的本地状态与计算，`views.js` 为纯渲染，`app.js` 为交互控制，`tokens.css` 为项目设计令牌快照，`styles.css` 为响应式样式。`review` 保留测试输出、截图、CWC 证据和独立审查记录。

```powershell
node --test tests/domain.test.cjs
node --check data.js
node --check domain.js
node --check views.js
node --check app.js
```

这是交互评审物，不是可直接上线的生产应用。账号鉴权、源系统连接、真实 AI 分析、调度、迁移、消息发送以及高风险治理操作均未实现；完整开发要求在上述规格中。
