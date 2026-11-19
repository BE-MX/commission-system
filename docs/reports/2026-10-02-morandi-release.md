# 莫兰迪按钮与标签配色发布记录

状态：2026-10-02 已完成生产部署并核验。应用版本 `e76752864119fe59ec29484b8b849f7c85ccca9e`，发布批次 `ec271e7fdede4b9b931f6d85b56c6751`。

## 本次结果

- 使用办公室服务器 `deploy/deploy.bat --revision e76752864119fe59ec29484b8b849f7c85ccca9e`，先 `--prepare-only`，再固定同版本正式发布；两阶段均退出 0。范围 `office-and-cloud`，`deferred=[]`。
- 主站按钮和 Element Plus 标签采用品牌金锚定的莫兰迪色系，两地主站已更新。该版本仅调整 `frontend/src/styles/tokens.css` 与 `frontend/src/styles/app.css`，替代此前主站蓝色按钮方案；[上一版记录](2026-10-02-button-colors.md)保留为历史证据。
- 主站生产构建通过，3364 模块、113 项导航；已有大 chunk 警告保留。PM 制品未变，继续原有配色；北京后端内容及客户素材制品未变，由统一入口核验。
- 数据库实际检查为 `173_task_center`，无需迁移。出库回执 `verified`，恢复原调度状态 `active=true/enabled=true`。

## 发布后验证

- 服务器 HEAD 与成功标记均为上述固定版本，工作区干净；办公室 `/health` 为 `ok/connected`。
- 额外 24 项 HTTPS 读取覆盖 `leshine.work`、`leshine.cloud`、`pm.leshine.work` 的入口、导航、入口 CSS、主脚本及登录页资源，以及两地主站健康入口。资源 SHA256 全部匹配办公室候选制品；两地主站健康为 `ok/connected`。
- 主站 CSS 实际核验主色 `#88713A`、危险色 `#A85F50`、禁用文字 `#B5AFA4` 及六组标签 solid token；PM CSS 核验原有主色 `#1668DC`。
- 正式发布首次 SSH 连接在 banner 阶段超时，命令未启动。重建现有 GameViewer 端口映射会话后，读取服务器确认 `prepared` 且 `completed=[]`，再继续同一候选发布。首次公网读取有资源超过30秒；延长读取时限后全部通过，没有重复发布。

## 边界与证据

- 此记录覆盖统一入口登记的应用目标。`pm.leshine.cloud` 尚未配置 DNS/TLS，独立 Agent 服务及 hair/video 等未纳管目标不计作本次部署成功。
- 日志、服务器成功标记、公网 SHA256 明细及原工作区指纹保留在主目录 `.deploy_state/morandi-release/`，含 `prepare.txt`、`deploy-retry.txt`、`server-verification.json`、`public-verification.json`、`postchecks-retry.txt`。
- 主目录原16个未提交文件在记录写入前指纹完全一致；交接文档仅插入本条发布记录，其余原内容保留。本次部署记录作为本地文档 diff 留存，未新建代码提交。
