# 私海客户与冻结列生产发布

2026-10-07，用户授权“合并推送部署”并在恢复办公室转发后要求重试。通过办公室安装目录 `D:/commission-system` 的统一部署入口，固定候选 `e12cb42acd8afeb7c64711a05fa554e026828ab2` 完成准备和完整发布，两阶段均退出0。

## 用户可见结果

- 订单发票列表冻结发票号、客户；出库单打印列表移除订单ID列，冻结现有单号、客户。列设置同步移除订单ID键，原订单ID搜索保留。
- 业务员角色新增 `customer:read`，保留原权限，不增加读取所有客户权限；Derek 的126个私海客户已完成归属与档案/列表投影。已有登录令牌需刷新或重新登录以取得新权限。
- 2432个归属明确客户已回填并再次逐条只读核验，无异常；42个共享且无主负责人客户按用户决定待核对，既有170个主负责全部保留。此次未建立持续自动同步，未回填订单或触发研究/AI任务。

## 发布与线上证据

```bat
set DEPLOY_NO_PAUSE=1
deploy\deploy.bat --revision e12cb42acd8afeb7c64711a05fa554e026828ab2 --no-pull --prepare-only
deploy\deploy.bat --revision e12cb42acd8afeb7c64711a05fa554e026828ab2 --no-pull
```

- 回执 succeeded，release_id=`accce2153fc74dac919366034e4afd0c`，scope=`office-and-cloud`，deferred=[]。办公室应用与静态、北京后端与色块服务、两地主站、PM公网/内网站及客户素材完成更新或核验。
- 办公室与北京实际运行HEAD均为固定候选，办公室工作区干净，两地本机 `/health` 均 ok/database=connected。
- 三域 `leshine.work`、`leshine.cloud`、`pm.leshine.work` 共18项公网文件SHA256与候选清单一致，包含InvoiceManage、OutboundRecords的JS/CSS、主入口与主脚本。两地主站artifact=`5b1d05aba114900377b9b9bf7d10edd72c019055ad53cb45766f100a707867d6`。
- 两地主站使用Derek实时权限的新令牌执行只读GET，均HTTP200/code200，total=126、首页20行；令牌未输出或保存。
- 共享schema仍`173_task_center`，schema_changed=false，无DDL。PM/Pantone既有基础资料检查幂等跳过，未重灌。
- 出库回执verified，timer恢复active/enabled。日志完成项沿用singapore-outbound名称，实际服务归属北京。邮件Worker候选已核验，原停用状态保持inactive/disabled、MainPID=0。
- 本次候选主站生产构建19.78s，PM缓存摘要核验通过；构建只有既有大chunk、混合导入提示。既有缺Matplotlib提示未阻断应用预检。
- 既有PM云域名无DNS/TLS、仓库外hair/video及未纳管独立服务不计作已发布。

## Git、验证与保留材料

功能提交`e12cb42a`已在Codex工作树提交、主目录快进合并并推送，包含先前冻结列提交`1c839bbe`。后端隔离联合回归141通过、1项因缺可销毁MySQL隔离库跳过；前端25项检查、真实组件模拟、构建与独立审查已完成，严格增量约定及diff检查通过。此次重试无代码修改，不重复数据修复写入。

主目录原10项已跟踪改动、13项未跟踪文件逐文件SHA256验证保留，未夹带提交；其他代理分支、工作树和stash保留。发布证据、版本/健康/调度核验、公网摘要及原文件备份在主目录`.deploy_state/private-customer-release/`。客户原始计划、回执和待核对表在`backend/tmp/customer-private-visibility-repair/`，均为忽略文件，不提交客户原数据。

本报告和交接更新属于发布后文档提交，生产应用候选保持上述SHA。
