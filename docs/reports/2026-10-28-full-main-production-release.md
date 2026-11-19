# 2026-10-28 最新 main 全局生产部署完成

版本：`c66daee69967332e91817025630e4d585acf2a18`。发布 ID：`53b0d551ab00405c968e2853ac51a130`。执行范围：office-and-cloud，统一入口 `D:/commission-system/deploy/deploy.bat`。生产部署已完成，本地主目录原有改动保留；发布记录未额外提交或推送。

## 已部署与运行验证

- 办公室、北京后端实际 Git HEAD 独立读回均为上述版本，部署器 publish-current=succeeded，受管目标 deferred为空。
- 办公室静态、内网PM、北京色块服务及两处色块路由完成核验。五个受管静态目标：leshine.work、leshine.cloud、pm.leshine.work、media.leshine.cloud、shop.leshine.cloud均完成发布；无变化制品仍核验，不冒充新内容。
- 共享数据库从 `210_color_swatch_library` 统一执行211→212，schema-writers最终completed。独立SELECT实读唯一revision=`212_portal_customer_settings`；客户地址两列、授权商品单价、验货物流关联与独立版本五列均存在。无stamp/downgrade、复制数据库或生产业务测试写入。
- 库存门槛实读：butterfly=5，genius20g/50g=30，tape hair/invisible tape hair=200，k tip/nano tip按其它=30。
- 独立部署后检查26项必需项全部通过，包括办公室后端/数据库、连接器、北京后端/数据库、两处Nginx、色块服务、跨站API鉴权、业务隧道及五个HTTPS入口。
- 客户站 `/`、`/checkout`、`/orders`、`/favicon.webp` GET均200；favicon与方舟黄色原图SHA256一致。这些是匿名静态与服务验收，没有创建客户订单或修改真实客户资料，登录态业务验收未执行。

## 服务基线与发布边界

北京出库轮询器、PM2 shipment-tracking-mcp与办公室原运行服务由部署器恢复并验证。邮件Worker更新固定版本并保持原有inactive/disabled状态；新加坡历史okki-sync仍inactive/masked，不启用旧writer。静态/候选清理按部署器默认登记deferred维护任务，不影响应用成功，也没有额外执行维护删除。

全局范围是platforms.json中的受管发布目标。OpenClaw、n8n、frps、独立cron/镜像和外部资源并非本仓库版本制品，不拉取其latest或宣称全部升级。独立检查对okki-inventory、n8n、okki-shopify-cron及ark-okki-outbound-mirror缺少探针的项目标unknown，未伪报健康；详细结果见postcheck.json。

## 本轮处理与验证证据

- 先fetch并固定最新origin/main。首次办公室SSH连接阻断，亮哥恢复后重新核验实际身份、干净工作区、旧版本e565c40f及无未完成锁/恢复记录，未沿用旧推断。
- 首次prepare因pnpm不在PATH失败，尚无服务切换/DDL。找到服务器已有受管pnpm10.33.2，仅补本次进程PATH，不安装新版或更改系统PATH；保留首轮失败证据后同候选重试成功。
- prepare约314.89秒，完整activate约227.66秒。主站、PM与门户使用受管缓存/冻结锁文件；静态切换前后验证摘要，旧资源保留。
- 发布前本地隔离部署检查69 passed。应用此前886 passed、2 skipped及补充专项/双端构建/浏览器验收见客户门户实现报告。没有把隔离测试称为生产业务验收。
- 本轮证据位于 `.deploy_state/full-main-release-20261028-c66daee6/`：final-receipt.json、postcheck.json、schema-readback.json、portal-http-readback.json、prepare-success.json、activate-readback.json、deploy-checks.log；完整部署日志留在办公室对应retry-pnpm10332目录。
