# 日常订单钉钉喜报发布记录

## 范围与版本

- 亮哥授权合并、推送、部署；功能提交 `362cec1a`，发布候选 `8651822fb764eb5ee33733d8c7623aecba9bcc6a`。
- 新签、下单、大单来袭、超级大单全年日常推送；首次启动建立历史基线，避免补发旧订单。保留成功同步、扣手续费、取消排除和幂等规则。
- 动态浅香槟金磨砂玻璃卡片包含采购节真实头像、国家·客户名称、宽渐变光晕和右侧星光。模板与动态文字分离，不把样例数据写进底板。
- 本功能无新迁移；统一全量发布包含 main 相对旧生产 `9bdbc5f3` 的已合并内容，候选迁移头为 `178_account_unlock`。
- 主目录既有24项未提交内容原样保留；未提交内容不作为部署制品。

## 验证

- 通知、采购节、运行中心与调度相关 pytest：162 passed。既有调度测试结束后的本机数据库不可连接观测日志不改变 exit 0；测试未执行生产迁移或真实群消息。
- 最终部署修复针对性 pytest：95 passed；Node模式边界：39 passed。独立 agent 审查未发现 P1/P2。
- 部署目录扩大回归：647 passed、13 skipped、1 failed。失败为 `test_storage_routing.py::test_bad_public_route_rolls_back` 的旧 mock side_effect 耗尽；单项重跑同样失败，该测试及产品文件相对任务基点 `7c233166` 均无变化，记录为无关基线问题。
- `check_conventions.py --base 7c233166`、`git diff --check` 通过；Git巡检 `--no-fetch` 为本地快照。

## 部署预检修复

1. 候选Python环境复制旧 `.ark-ready` 后，安装失败重试可能误跳过依赖；现核对标记内容必须等于候选依赖摘要，失败时清除旧标记。
2. 门户合并重编号后176接在175后创建模式表；生产只读确认唯一 `175_receipt_recovery` 且模式表缺失。三个reader补充精确175，未知、多head、权限失败和176以后缺表继续拒绝。
3. 上一部署器的completed回执无mode/fingerprint；仅精确五字段旧格式在实际legacy模式、永久mode-floor、timer基线与四个已安装文件组合摘要全部核验后接续。prepare不重写旧回执，后续freeze生成本次规范回执；activate/verify保留ModeFence。

上述失败均发生在服务切换与DDL之前。日志、原主目录快照及动态样图保存在主目录 `.deploy_state/daily-order-release/`。

## 发布结果

- `deploy/deploy.bat --live-root D:/commission-system --no-pull --revision 8651822fb764eb5ee33733d8c7623aecba9bcc6a` 经办公室 SSH 执行，exit 0，输出 `MANAGED APPLICATION RELEASE COMPLETED`。
- 发布scope为 `office-and-cloud`，release ID `8bb46dda264643af893ed6c6736e05e4`；共享schema为 `178_account_unlock`。
- 办公室和北京HEAD均为固定候选，`/health` 返回 `ok`、数据库 `connected`；玻璃模板文件均存在。
- 办公室Scheduler开启、群机器人已配置；北京Scheduler关闭，保持单活。只读确认日常基线 `baseline:daily:ark:invoice_orders` 已在 `2026-10-09 13:24:16` 建立，办公室订单监控任务成功，无error_digest。未人工调用任务或发送样例群消息。
- 主站两个目标激活同一制品 `32f152e87d6068724f86e5f0fa4244c3c29433879cc4be8f1b660c8d07875cad`；PM与客户素材未变化，均通过部署器核验。正式阶段复用预检已上传制品，新增传输0字节。
- 北京出库轮询器回执 `verified`，mode `legacy`，原timer active/enabled基线完整恢复；mode-floor与执行围栏继续生效。邮件Worker完成版本核验，原running=false基线保留。
- 未登记活跃目标的PM.cloud、hair、video和客户门户按现有发布清单保留待接入；独立OpenClaw/MCP等服务本轮未发布，不计入受管应用完成范围。
- Git巡检只报告本地状态；主目录既有24项内容逐项核验保留，不清理他人分支与旧stash。
