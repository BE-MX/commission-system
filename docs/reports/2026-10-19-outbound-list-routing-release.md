# 出库单打印列表路由性能修复（2026-10-19）

## 发布结果

用户先要求排查列表加载缓慢，确认慢在进入页面后，再明确要求解决。本次通过项目入口执行 `deploy/deploy.bat --shipping-video-routing-only --prepare-only` 和正式 `--shipping-video-routing-only`，两站回执均为 activated，退出码 0。没有应用代码发布、数据库迁移、业务写入、Git commit 或 push。

北京两处 server 的 exact `/api/shipping-inspection/outbound-records` 已直达本机 `127.0.0.1:8001`，原北京→新加坡→办公室链路不再承接该列表。现有受管候选同时启用 print-data/word 的窄正则北京规则；同步、删除、验货资料、上传与媒体仍保持办公室归属。新加坡受管 shipping 块仅位置调整，块内容不变。Nginx 配置前后差异、准备回执、激活回执、运行前置检查和页面截图保留在 `.deploy_state/outbound-list-routing-20261019/`。

本轮不包含 main 上其它尚未发布代码；北京应用 checkout 为 `06b27d7df54a9b8ec67e5d49472c1dd7b0f418df`，查询优化源对应 `671006ce22`。此次交付的是独立 Nginx 路由发布，不能把本地 main HEAD 当作已部署应用版本。

## 实际验证

同一 Chrome 用户登录态、同域 `www.leshine.cloud`、每页 20 条：

| 场景 | 修复前 | 修复后 | 结果 |
|---|---:|---:|---|
| 第 331 页列表请求 | 6,605ms | 156ms | HTTP 200、总数 6,605、该页 5 张原单正常显示 |
| 首页列表请求 | 本轮未采集同账号浏览器前值 | 757ms | HTTP 200、首页 20 条正常显示 |

修复前用 CDP requestWillBeSent/loadingFinished 计算请求耗时；修复后用浏览器 Performance Resource Timing 读取真实已完成 XHR，TTFB 分别为首页 746ms、第331页150ms。原页面在观察工具重连时暂时不可读，因此修复后使用同浏览器、同登录态的独立验收页，未改变原页面的筛选与分页。以上是接口端到端样本，不含首次静态资源下载或全部页面渲染，不承诺所有网络条件下固定耗时。未提取或保存用户登录 token。

两站数据库实例/schema 与三份列表核心源文件摘要一致。只读事务内完整列表处理函数：办公室 3956.0/2334.8/2780.0ms；北京继承运行进程环境后 288.1/160.3/160.5ms，每次 16 条 SQL。修复前北京公共入口匿名响应 887.0/4730.8/1150.8ms，北京本机匿名响应 90.0/30.6/30.6ms；匿名响应只能证明传输成本，不能代替登录态结果。

上线前：

- `backend/.venv/Scripts/python.exe -m pytest deploy/tests/test_voucher_routing.py -q`：49 passed。
- 两站运行配置的共享数据库、JWT、当前/旧版二维码密钥、二维码挑战、小满配置和现有 token 摘要相同；代码与配置均早于运行进程。北京继承运行进程环境，办公室读取 NSSM 环境覆盖与 .env。
- 固定目标小满详情 GET 两端 HTTP 200，出库身份与负责人摘要一致；无 token 刷新或业务 POST。两端内存生成 Word 并读取到二维码图片成功。
- 两站隔离 Nginx 语法检查通过，候选 diff 已审阅；实际入口激活执行 nginx -t 与 reload。北京 nginx/ark-backend 均 active，live 配置读回确认两处 exact 列表规则指向 8001。
- 本次没有点击实际打印/下载或仓库扫码提交；打印/Word 的前置配置、依赖及小满 GET 已核验，不把这些证据写成真实打印机/扫码业务验收。

## 回滚材料

- 新加坡：`/etc/nginx/.ark-backups/shipping-video/office-4c0da7936f2649679307b47de2f2a58b.conf`
- 北京：`/etc/nginx/.ark-backups/shipping-video/cloud-4add8c2dcf5047068514fe0a8dbbbe51.conf`
- 正式回执：`.deploy_state/shipping-video-routing.json`；本次固定副本：`.deploy_state/outbound-list-routing-20261019/activated.json`。

原有 main 工作区文档及其它修改保留；仅新增本报告与 handoff 发布条目，不提交或推送。
