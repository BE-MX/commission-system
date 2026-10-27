# 内贸发货批次取消

交付状态：用户已授权提交、合入 main 并推送 origin；分支 `codex/domestic-cancel-batch`，最终交付以 Git 引用回读为准。未部署，没有修改生产订单或客户余额。

## 行为

- 交付对账的未收货批次显示「取消批次」。本人创建且具备 domestic:write/admin 权限才能执行。
- 确认提示说明件号恢复可发、历史保留、订单仍有效和余额不变。取消返回后刷新候选、批次、汇总及父页面。
- 已取消批次仍能展开/导出，保留金额及件号快照，未结为零；原在途/已收货未结汇总排除取消批次。
- 已收货、关联任意收款核销记录、订单/明细已终止或订单失效时拒绝取消。取消幂等，失败通过路由统一回滚，未知结果刷新回读，不自动重发。
- 原订单「登记发货」入口使用取消次数区分发货周期，可取消后再次发货；倒序取消旧批次也会开启新周期。
- **确认收货不会扣余额**：扣款发生在正式下单/价格审核通过时。发货、收货、取消均不改订单扣款或客户资金账本。

## 数据与并发

迁移 `206_domestic_shipment_cancel` 接 `205_domestic_item_termination`；批次新增 cancelled_at、cancelled_by、cancelled_units，可空，无旧数据回填。具体件、批次和明细不删除，只释放具体件的发货占用关联；取消快照保存原件ID和件号，降级拒删审计。

独立审查发现并修复：取消与收款审核的批次/核销锁顺序冲突；退款统计的批次/客户锁顺序冲突；原单条入口固定幂等键无法重发；按最大已取消ID命名周期无法覆盖倒序取消。

最终取消及原单条发货使用 order → item → customer → batch 顺序，在客户行与收款写入串行；退款按当前有效单件关联计数，不提前锁批次。

## 验证

- 后端：`pytest tests/test_domestic_shipment_cancel.py tests/test_domestic_delivery.py tests/test_domestic_partial_termination.py tests/test_domestic_item_termination.py tests/test_domestic_conditional_routing.py tests/test_domestic_review_flow.py -q --disable-warnings --maxfail=2`：165 passed。全部使用测试 fixture 的内存 SQLite。
- 覆盖部分/全部取消、其他批次保留、跨订单取消、相同件重发、重复请求、原入口三轮取消重发与倒序取消、越权/收货/核销/终止拦截、失败原子回滚、确认收货不再扣款、UTC主机与北京时间零点两侧。
- 迁移测试验证旧批次号/金额保留且新增字段为空，模型列集合一致；`alembic heads` 为唯一 `206_domestic_shipment_cancel`。未运行共享或生产迁移。
- `node --test frontend/tests/domesticDeliverySelection.test.mjs`：4 passed；`npm run build` 通过，保留既有大 bundle 和静态/动态 import 警告。
- `check_conventions.py` 增量无违规；`git_sweep.py --no-fetch` 已执行，只反映本地 Git 引用快照，不代表远端实时状态。
- Headless Edge 真实组件与隔离 SQLite API 验收通过：保留批次不发送取消请求、确认取消、历史/汇总恢复、CSV 导出、同件重发、390px 操作可达，页面异常为0。见 [结果](assets/2026-10-27-domestic-shipment-cancel/cancel-result.json)、[取消确认](assets/2026-10-27-domestic-shipment-cancel/cancel-confirm.png)、[取消后清单](assets/2026-10-27-domestic-shipment-cancel/cancelled-desktop.png)、[窄屏操作](assets/2026-10-27-domestic-shipment-cancel/cancel-mobile.png)。

隔离浏览器验收使用 `scripts/qa_domestic_delivery.py`、`scripts/domestic-delivery-qa/` 和 `scripts/verify_domestic_cancel.mjs`；证据保存在本任务 `tmp/domestic-delivery-evidence/`。测试依赖应与 frontend/package-lock.json 保持一致，Playwright 单独放临时工具目录并通过 NODE_PATH 提供，避免安装工具时更新应用依赖。SQLite验证不等同于生产MySQL并发压测或业务验收。

本次临时 API/Vite 服务均已关闭。收尾清理临时工具目录、复制的浏览器测试入口和虚构SQLite样本时，被自动审批策略以 `blocked by policy` 拦截；这些文件继续保留于本任务 worktree 的 tmp 和 frontend/tmp，未绕过拦截。
