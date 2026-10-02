# 操作列与按钮统一修复生产发布

2026-10-02发布完成。应用提交 `b807fdcde6fe70267e74ad8f3082ed5ca1a2f8cd`，发布批次 `b1c3804f154d443bab2aadc4fdde5ff5`。实现范围及本地验收见[修复报告](2026-10-02-action-button-consistency.md)，规范见[按钮设计契约](../requirements/2026-10-02-action-button-design.md)。

## 发布结果

- 本次62文件修复已在独立Codex工作树提交，在主工作树快进合入main并推送origin。主目录原22个未提交文件完整保留，未夹带进入提交。
- 从办公室已安装仓库调用统一 `deploy/deploy.bat --revision b807fdcde6fe70267e74ad8f3082ed5ca1a2f8cd`，先 `--prepare-only` 后正式发布，两阶段退出0。发布范围 `office-and-cloud`，成功回执 `succeeded`，`deferred=[]`。
- 主站及PM候选生产构建通过；正式阶段复用已准备制品。两地主站、`pm.leshine.work`、办公室主站/内网PM均由统一入口完成。北京后端与客户素材内容未变，由入口核验。
- 共享数据库实际revision为 `173_task_center`，无pending迁移、未执行DDL。出库回执 `verified`，原调度状态 `active=true/enabled=true` 已恢复。

## 实际验证

- 合并后Node定向测试7/7、严格约定检查（基点 `6d815065`）和提交diff检查通过。已有139项浏览器组件状态/对比度及触屏交互回归证据保留；本次发布不冒用它作为生产逐页业务写入验证。
- 办公室源码HEAD、当前发布标记和成功摘要一致，服务器工作区干净；健康为 `ok/connected`。
- 34项公网HTTPS读取覆盖 `leshine.work`、`leshine.cloud`、`pm.leshine.work` 的入口、主脚本/CSS、导航、登录以及物流、提成批次、PM任务页面资源；各资源SHA256逐项匹配办公室候选制品，两地主站健康为 `ok/connected`。
- 实際CSS核验两地主站及PM按钮深金/青碧/杏橙/绯红文字token、亮金实心深墨字、warning接口；PM link规则与44px触屏目标已存在。没有触发生产数据写入来验证按钮。

## 证据与边界

原文件备份、指纹、合并记录、`prepare.txt`、`deploy.txt`、`server-verification.json`、`public-verification.json`、`postchecks.txt`及本地UI证据保留于主目录 `.deploy_state/action-button-release/`。

`pm.leshine.cloud`的DNS/TLS尚未配置；hair/video及清单中的独立服务未纳管，本次不计作已发布。应用运行版本固定上述SHA；后续提交只同步这次发布文档，不改变应用制品。
