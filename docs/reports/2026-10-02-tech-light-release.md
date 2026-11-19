# 科技轻快按钮与标签配色发布记录

2026-10-02 生产部署完成，应用提交 `6d8150654714cee9973b19608fc4540ae809122b`，发布批次 `9fdf190e634c47738a6cbdff02e55934`。

## 部署结果

- 办公室统一 `deploy/deploy.bat --revision 6d8150654714cee9973b19608fc4540ae809122b`，先 `--prepare-only`，再正式发布，两阶段退出0。范围 `office-and-cloud`，`deferred=[]`。
- 主站按钮和标签更新为科技轻快配色：亮金主色、青碧成功色、杏橙警告色、绯红危险色及冷灰中性色。替代[上一版莫兰迪配色](2026-10-02-morandi-release.md)。本次仅发布已提交源码，没有修改应用代码。
- 主站生产构建通过，3364模块、113项导航；保留已有大chunk警告。两地主站静态制品已切换。PM、客户素材及北京后端内容未变，由统一入口核验。
- 数据库实际 revision 为 `173_task_center`，无需迁移。出库回执 `verified`，原调度状态 `active=true/enabled=true` 已恢复。

## 实际核验

- 办公室源码HEAD与成功标记同为上述提交，服务器工作区干净；办公室健康 `ok/connected`。
- 24项公网读取覆盖 `leshine.work`、`leshine.cloud` 和 `pm.leshine.work` 的入口、导航、入口CSS、主脚本及登录资源；各资源SHA256全部匹配办公室候选制品。两地主站健康均 `ok/connected`。
- 两地主站实际CSS核验主色 `#E0A50B`、主色深墨 `#3D2E03`、危险色 `#E5484D`、禁用文字 `#9CA3AF`，以及六组标签solid和金色标签深墨token。PM继续原有配色并通过摘要核验。
- 本次没有重新执行浏览器交互验收或业务写入测试；部署构建、资源摘要和服务健康是本次验证范围。

## 证据与边界

日志及回执保留于主目录 `.deploy_state/tech-light-release/`：`prepare.txt`、`deploy.txt`、`server-verification.json`、`public-verification.json`、`postchecks.txt` 与原工作区指纹/交接备份。

`pm.leshine.cloud` 尚未配置DNS/TLS，hair/video及独立Agent服务等未纳管目标不计作本次成功范围。原17个未提交文件在记录写入前指纹一致；仅给交接文档插入本条记录，其他16个文件及原交接内容完整保留。发布记录保留为本地文档diff，未新建代码提交。
