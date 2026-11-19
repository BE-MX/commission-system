# 2026-10-19 年度新签复购金额发布与启动恢复

已按用户授权合并、推送，并通过 deploy/deploy.bat 完整部署 `15d86b3505963f3ecb01cc6c931fd607b1eb6046`。办公室与北京后端匹配，11个受管目标完成；任务退出码0、发布锁释放，共享库197_battle_awards无DDL。北京unchanged分支已补固定SHA检出和backend-success更新；无须重启也能确保实际Git和回执一致。

新金额=全部2026新签客户的新签订单金额＋首签后2026有效复购订单金额；仅新签未复购客户也计新签金额。客户转移后仍归原新签业务员；复购人数/笔数仍只计实际复购。GMV、美元目标、资格、11月PK及原订单裁定不改。已发送历史快照不回算。

生产只读同源核验：翟佳盟新签76客户，实际复购36客户/128笔；新签复购金额USD99190.47、积分34.3028564。镜像同步2026-10-19T14:00:07，计算2026-10-19T14:10:30.432279。17人GMV、目标、进度及新签/复购人数笔数与旧算法同一镜像对比一致。

年度战报2保持published/version6/推送开关1，规则摘要与发布前一致；未手动触发群推送。Office Scheduler单活、北京关闭；CommissionSystem、WhatsAppConnector、ArkOfficeHttps正常。三地BattleReports当前制品摘要相同，内网8001与leshine.work、leshine.cloud的实际JS均200并匹配，包含新口径文案。

初次b59发布因既有30秒启动预算及回滚立即探活失败，旧代码已恢复但服务被保护性停用。修复后正常激活和回滚均等待最长300秒。受管恢复入口按固定失败journal SHA、旧代码/静态/NSSM参数、schema无pending与legacy数据库指纹核对，在发布锁/DB锁/rollback fence内恢复旧服务，再通过原b59/release_id接续完整发布，保留outbound原active/enabled=true和mail原false基线；原发布成功后e4仅发布工具变更遇间歇性8秒HTTP探测超时，确认运行服务未切换、未停机后，扩展预检和unchanged分支为同一有界等待策略。受管入口按SERVICE_RUNNING计划仅核验不启停，以原9fe发布绑定和冻结基线完成e4后，再正常发布包含全部修复的15d86b35。e4接续在Office/北京完成后曾遇Windows发布journal替换WinError5；查询实际检查点后增加同次原子rename有界重试，并保留旧、新hash的恢复去重，再接续原9fe绑定完成。其后13e33131仅在北京准备阶段因短暂维护锁占用而失败，无冻结/激活；锁自然释放并确认原e4完成后，按固定15d86b35完整发布。该修复提高发布对间歇迟滞的容忍，不代表响应迟滞根因已消除。原失败日志、独立恢复回执及完整成功回执全部保留。

验证：213项后端业务回归、4项前端测试、前端构建；194项部署相关回归和独立审查通过，增量约定检查通过。全量部署测试另发现现有test_merge_migration_plan断言仍期待schema195而当前head197，未改动该历史断言。Git巡检--no-fetch通过main同步检查，其余代理工作保留。

证据目录：`.deploy_state/annual-amount-release-20261019/`（原失败、金额重算、两轮63文件保护备份）及`.deploy_state/annual-readiness-release-20261019/`（恢复与瞬时探测失败）及`.deploy_state/annual-final-release-20261019/`（只读健康预检失败）及`.deploy_state/annual-health-release-20261019/`（Windows状态文件替换失败）及`.deploy_state/annual-journal-release-20261019/`（检查点恢复闭合）及`.deploy_state/annual-main-release-20261019/`（最终部署与独立读回）。主目录原63个dirty路径完整保留；交接文档添加发布证据，部署README保留原字节并追加本次最新恢复操作段落。
