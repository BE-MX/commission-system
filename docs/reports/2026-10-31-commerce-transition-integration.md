# 双路线过渡主线集成记录

日期：2026-10-31。用户授权范围：提交本次开发、合并main并推送origin，保留其他未提交改动，不部署。开发提交为 `65ff00d0`；在 `codex/commerce-transition` 整合主线 `a77f50ac`，随后在主worktree快进main。原开发证据见[开发验收报告](2026-10-28-commerce-dual-route-implementation.md)。本记录与隔离验证不代表生产已切换。

## 合并结果与必要修复

- 保留主线验货要求、订单分组、出库筛选/物流、退货退款，以及双路线的持久phase、原单办理权、资金和物理范围隔离。
- 主线已发布迁移208–214保持原文件。未发布候选208–226整体重编号为227–245，首项下接214_sales_return_ledger；唯一head为245_commerce_transition。候选DDL除revision/parent和安装审计编号外不变，没有重新生成历史DDL或stamp跳过。
- 统一编辑器的分组/验货字段落入真实本地命令；分组更新校验实时权限、客户范围、authority epoch及订单/分组版本。本地空占位行不再误触发缺SKU拦截，新行保留group_key。
- 旧退货入口增加旧路线办理权门禁；draft/effective旧退货责任阻止原单承接。当前无净退货责任承接协议；新增的旧退款银行身份也不伪造settled_evidence，仍会阻止最终退役到local_only，保守保留原路线处理，不伪造结清。native和旧退货提成在同批正确消费，保留原冻结依据。
- 旧退货实际支付和收回的银行身份补入统一核验：逐笔按真实cash_evidence登记，不能把负数回款意图当成支付事实。缺身份阻断独立资金，已核验流水不能复用为另一退款或本地本金；历史身份补录不授权重新开放旧交易。
- 统一经营投影补入按生效日记账的退货调整，独立于销售/新客/复购计数。冻结旧业务员经已核验名册映射；未知外部ID不猜同号方舟ID。订单后来取消/转归属时，原团队的跨期调整仍保留。大单阈值使用扣减后金额。
- 日报以数据库phase选择配置。旧部门与本地部门缺少可信映射时保留金额并阻止最终发送，不能按相同数字自动归属；双来源水位不足同样阻止最终发送。
- 独立前端及后端审查发现并修复上述交叉问题；最终复核没有剩余P1/P2。原方案的writer、银行、库存现场核验要求继续适用。

## 本轮实测证据

日志在任务worktree的 `tmp/merge-main-20261031/`，各组可能重叠，不合计通过数。

| 范围 | 实际结果 |
| --- | --- |
| 完整空库迁移链及MySQL并发 | 19 passed；mysql-chain-v3.log。旧资金字段、source=okki、验货默认/订单分组读回，真实出库/资金/承接/物料竞争验证；随机schema和测试writer清理后确认不存在 |
| 真实库存、预占和资金迁移竞争 | 19 passed；mysql-direct-migrations-v2.log。测试同步点移至外层策略锁前，保留数量、资金及幂等结果断言 |
| 原生业务41文件组合 | 437 passed、2项自建fixture缺退货表；补齐表后同authority文件25项全部通过。native-aggregate.log及backend-authority-final.log，失败原因与复验分开保留 |
| 履约/检验/办理权组合 | 144 passed、同2项fixture问题已由authority25项复验闭合；backend-shipping-final.log |
| 旧路线4文件完整组合 | 251 passed；backend-legacy-full.log |
| 后端主线重叠业务 | 195 passed；backend-overlap-final.log，含订单分组/验货、旧退货/native提成及8项交叉边界 |
| 主线验货/分组及部分冲回DDL | 10 passed，迁移代理专项 |
| 经营统计、日报、战报、采购节与订单洞察 | 212 passed；consumer-tests-final-v2.log |
| 补充取消/转归属后的团队与维度筛选 | 86 passed；consumer-scope-final.log，含真实get_overview消费者回归 |
| 旧退款银行身份及权限/原生门禁组合 | 84 passed；backend-return-bank-final.log。实际退货服务、重复流水、双现金动作、历史身份及API实时权限分别验证；最后GET/写入锁序修改后29项通过（backend-return-bank-lock-final.log） |
| 扩展MySQL依赖及最终锁序 | 受影响模块复验31 passed；2项fixture门户表名前缀修正后，与最新银行锁序finance4一起最终6 passed（mysql-final-six.log）。原失败全部定向闭合；独立直接库存/资金19项和全链19项另列，不混称全库测试 |
| 银行核验UI | 10 passed；frontend-return-bank-final.log；最终构建36.44s、138导航，frontend-return-bank-build-final.log |
| 前端合并专项 | 135 passed；frontend-targeted-complete.log |
| 前端构建 | 通过，138导航；frontend-build-complete.log，930个源码文件与构建快照SHA一致 |
| 前端全量基线比较 | 合并候选1844项：1732 passed /112 failed；最新main1791项：1676 passed /115 failed。同依赖和VM参数，新增失败0、解决3项；frontend-merge-comparison.json。不宣称全量测试全绿 |

编译、以a77f50ac为明确基点的严格约定检查、暂存区空白检查通过，所有冲突标记已清除。

最初测试中曾遇到本机测试MySQL未启动、旧fixture缺持久策略表/银行身份、错误镜像schema环境变量、合法新增列被旧整dict断言误判，均按实证修复或更正测试前置后重跑；没有放宽金额/幂等断言、跳迁移或连接生产。

## 其他工作区保护与发布边界

合并前对主目录每个未提交/未跟踪文件保存内容及SHA256清单，并保存index/worktree二进制patch。备份位于任务worktree `tmp/merge-main-20261031/main/` 和 `main-manifest.json`。主目录原有文档、登录页等不纳入本次提交；110个文件中仅4份重叠文档在主目录更新时短暂封存并恢复，最终核对原差异内容。

本次只推送GitHub origin/main，不推送cloud、不运行部署入口、不迁移生产、不切换writer或发送业务通知。安装默认仍为legacy_only，独立对比关闭。任务worktree中的验证证据和恢复备份具有审计价值，保留供核对；旧候选worktree也不清理。
