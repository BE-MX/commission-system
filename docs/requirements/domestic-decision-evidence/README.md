# 内贸经营决策台真实页面验收

本目录的页面截图、图表PNG、CSV下载和 `verification.json` 来自真实决策API与构建后的Vue页面。数据为独立临时SQLite中的36家虚构门店、两个虚构权限角色和历史订单/账本；没有连接、修改生产数据库，没有调用外部AI。公共页面框架徽标使用空辅助响应，不替代任何决策业务接口。

运行方式（仓库根目录，需已构建 `frontend/dist`）：

```powershell
python docs/requirements/domestic-decision-evidence/qa_server.py
# 另一终端，需本机已安装 Playwright Chromium
python docs/requirements/domestic-decision-evidence/verify.py
```

预览入口为 `http://127.0.0.1:8791/domestic/decision`，首次打开默认进入虚构主管角色。`qa-full` 与 `qa-sales` 仅为本地虚构登录标记，预览页的角色引导只存在于此隔离服务器，不修改生产登录。服务每次启动创建新的隔离SQLite文件，放入忽略的 `tmp/`，避免并发HTTP及后台任务共享单一内存连接而相互回滚。

脚本检查：真实订单/明细金额核对与资金对账、七个专题、带口径的PNG下载、同明细AND与整单区分、完整快照远程升降序及表头状态、个人视图、完整历史画像、内部行动实际结果、刷新恢复简报、私有CSV、自然语言先预览后应用、质量及版本维护、390px布局、无资金权限的API及UI裁剪、无浏览器未捕获错误。每组结果以最终 `verification.json` 为准，`complete=true` 表示全部十五组通过。

主要截图：`overview-desktop.png`、`products-desktop.png`、`finance-desktop.png`、`customer-profile.png`、`overview-mobile.png`、`no-finance-permission.png`。`chart-export.png`、`filtered-export.csv` 为真实下载产物。

验收不能证明生产数据质量、真实MySQL并发或大规模性能。完整功能口径、后台中断边界、权限和发布步骤见[使用说明](../../domestic-decision.md)与[实施验收](../2026-10-08-domestic-decision-implementation.md)。
