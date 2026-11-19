# 2026-11-16 北京 OpenClaw 私海背调 V2

北京专用销售研究 Agent `ark-sales-agent` 通过 `deploy.bat --sales-agent-stage` 从 `3c7448cca2bb9ab6c12c22e358f861e0243cd060` 切到 `origin/main@893c2e666091a155bfe8edfbcd52dc389f873e6f`。OpenClaw 依赖沿用仓库固定的 `2026.8.1`，模型为 `mimo/mimo-v2.6-flash`。更新前无进行中的搜索或研究任务，受限配置备份留在北京 `/var/backups/ark-sales-agent-v2-20261116`。

发布后 systemd active/enabled，Gateway RPC 和真实模型探针通过。V2 技能为 main 模型可见，技能文件摘要与固定候选一致。8 个所需 MCP 工具与 `private_research_v2` 报告契约可用，使用实装 sidecar 经鉴权读取了生产队列。队列 heartbeat 保持 `0m`。

隔离验证有 89 项 Agent 测试通过、1 项跳过，后端 V2 专项 27 项通过。真实 MCP stdio 到方舟 API 的合成用例完成了领取、租约上下文、事实和报告回读。北京用实装 OpenClaw 和相同模型运行合成样本，首次报告成功入库后 CLI 触及 135 秒预算。以 300 秒预算重跑的新样本正常退出，报告完成并含 1 个引用，等待人工复核。

北京扫描器与新加坡出口保持运行。三个认证扫描的站点连接失败数分别为 47/88、9/89 和 18/84，前者越过 30% 试点阈值，后两次通过，覆盖有波动。Monid 鉴权和余额只读接口均返回 HTTP 200。生产后端的异步工具 worker、Maigret 和 Monid 开关为关闭。

用户指定的生产验收使用私海客户 #1804，真实任务 #403。首轮 Run #419 通过行业门控，网页检索多次超时或失败，临近收尾时触及 15 分钟 CLI 上限。原会话续跑无法取得旧 MCP 内存租约。等原租约自然到期后，按正常领取契约重领同一任务，原 Run 已关闭，新 Run #420 沿用门控并聚焦两页可达信源。

#420 于 23:41:51 完成，CLI 退出 0，任务状态为 completed、复核状态为 pending，租约已清除。报告格式为 `private_research_v2`，共 2,856 字符、3 条事实记录、3 条同 Run 引用和 7 项资料缺口，归档未列为「已验证结论」的内容仍需人工核实。用当前负责人的权限经背调中心服务及私海助理服务回读同一份 Markdown，摘要为 `48e035ec630a78a9aa58e8fa5d2e750b1c6681091e7e19bac5d54fdfe72af05c`。

生产任务的 Maigret 请求回执为 `provider_disabled`，费用为零。该客户验收走了免费网页路径，未调用付费 Monid。浏览器渲染和批量自动消费不包含在本次验收证据中。发布与运行回执保留于 `.deploy_state/openclaw-private-research-v2-20261116/`。
