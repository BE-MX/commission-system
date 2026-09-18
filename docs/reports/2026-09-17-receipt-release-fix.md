# 回款与公告生产菜单缺失排查

- `leshine.cloud`实际北京HEAD为2609626f，静态入口main-To7MRazF.js，制品没有ReceiptManage/AnnouncementList。办公室HEAD同为2609626f；新功能所在main为9e5cd2dd。
- 办公室9e5cd2dd受管候选已存在；通过统一deploy.bat指定版本prepare-only复现：Database migration pending: verify every office/cloud writer。无服务停止、无DDL。
- 新加坡出库轮询器已启用，但platforms.json曾将migration_writers_verified置false，部署器不支持timer排空。不是菜单缓存或用户权限问题。
- 新增固定systemd_timer控制：暂停timer、最多120秒等待oneshot inactive/MainPID=0，不kill；恢复沿用原始writer基线。已只读复核办公室两个服务running，北京active，新加坡PM2存活、timeractive且oneshotinactive。
- 本地deploy/tests：212 passed、11 skipped。生产补发须使用修复后的完整受管候选、独立DBA凭据及155→156迁移链；尚未授权/执行本次生产切换，不开启真实回款同步或公告推送。
