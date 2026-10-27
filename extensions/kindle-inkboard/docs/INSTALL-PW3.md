# PW3 5.15.1.1 安装与验收

本包是看板应用与配套 Tinta，不包含越狱工具、原厂固件或 KOReader。当前已通过本地测试，尚未在这台 PW3 上验证。方舟服务也需要单独合并、迁移和发布后，设备才能连接真实账号。

## 1. 越狱与 KOReader

1. 设备已确认为 Paperwhite 3、固件 5.15.1.1。先备份书籍和 USB 可见文件；保持该版本，不为安装本看板先升级或降级。
2. 打开 [KindleModding 越狱向导](https://kindlemodding.org/jailbreaking/)，按 PW3 与实际固件选择入口。5.15.1.1 低于 WinterBreak2 的 5.16.4 上限；具体前后置步骤以向导为准。
3. [WinterBreak2 指引](https://kindlemodding.org/jailbreaking/WinterBreak2/)与[发布页](https://github.com/KindleModding/Winterbreak2/releases/latest)。按指引防止中途自动更新；解压后根目录应有 `winterbreak2` 文件夹。安全弹出后在设备实验浏览器操作，USB 复制本身不会完成越狱。
4. 完成向导的后置步骤、更新阻断并重启。当前 WinterBreak2 HDNEXT 指引预装 KPM，不额外按旧教程安装 KUAL。
5. PW3 5.15.1.1 使用 **kindlepw2** 家族安装包，不能选 `kindlehf`。可使用 [KOReader 2026.07.1](https://github.com/koreader/koreader/releases/tag/v2026.07.1) 的 `koreader-kindlepw2-v2026.07.1.zip`。官方 SHA256：`ea1f575c54492a2c679d128b7f3210fd7d6a87e5f5a1ff1f7a7fe2080ff68f86`。
6. 当前 HDNEXT 推荐按 [KindleModding KOReader 指引](https://kindlemodding.org/jailbreaking/whats-next/getting-koreader/)安装：在主屏幕搜索栏依次执行 `;kpm update`、`;kpm install koreader`，再打开出现的 KOReader Scriptlet，或执行 `;kpm launch koreader`。上面的官方 ZIP 留作核验架构和受控离线复制所用，不额外叠加旧启动器。退出 KOReader 后再接 USB；不要在 KOReader 正运行时切换 USB 大容量存储。

本台 PW3 于 2026-10-26 使用受控离线复制安装：官方 ZIP 中的 `koreader/` 主目录和已审查的 `client/launchers/KOReader.sh`（复制到 `documents/KOReader.sh`）均已设备端校验。直接从书库打开 KOReader；本次不依赖 KPM 的软件注册记录。KOReader 启动输出保存在 `koreader/ark-launch.log`，应用错误还可查看 `koreader/crash.log`。

## 2. 安装看板

1. 将 `ark-board-pw3-0.1.1.zip` 解压到电脑文件夹。确认 Kindle 已退出 KOReader，并通过 USB 挂载。
2. PowerShell 中进入解压目录，把下面的 `E:\` 替换成实际 Kindle 盘符，先预检再安装：

```powershell
.\install.ps1 -KindleRoot E:\ -DryRun
.\install.ps1 -KindleRoot E:\
```

安装器只复制 `koreader/plugins/tinta.koplugin` 和 `koreader/tinta-apps/ark_board`，会备份这两个目录已有的文件并校验安装结果。它不会执行越狱或改写系统分区。

3. 方舟发布后，进入“个人效率 → Kindle 看板”，管理员先赋予 `inkboard:read/write`。待办还需要已有的 `task:read` 或 `task:write`。绑定个人设备并下载一次性配置。
4. 将 `ark-board.local.json` 放在 Kindle 的 `koreader/` 目录。配置含凭证，不要分享或放入 Git。
5. 安全弹出、拔掉 USB，启动 KOReader，在“工具 / More tools”中打开 Tinta。找到“方舟看板”，点击“导入设备配置”。导入成功会删除导入文件，凭证保存在 Tinta 的本地设置中；Tinta 数据库仍属于敏感文件。
6. 将方舟组件放入首页和休眠页，设备时钟保持准确。应用通过 `wake_at` 请求约 5 分钟一次的同步。0.1.1 提供完整的 Tinta 简体中文文本，进入“系统设置 → 屏幕与导航 → 语言”可选择“简体中文”；KOReader 自身的语言在其设置中单独选择简体中文。本台 PW3 的显示修复同时保留既有设置并切换这两处界面语言。

0.1.1 在 Tinta 调用字体接口时抵消 KOReader 的额外缩放，避免 PW3 上字号放大两次而行框只放大一次。不更改 KOReader 全局 DPI 或阅读字号。更新后需完全退出并重新打开 KOReader，使缓存的 Lua 模块重新加载。

配套 Tinta 包含必要适配。不要直接用上游自动更新覆盖：上游版本尚不包含本包使用的 `after_commit` 等接口；覆盖后方舟应用会提示更新配套包并停止确认消息。

## 3. 第一轮真机验收

- 新建一个本人待办、一个备忘、一条消息：下一次同步应显示三类内容。
- 短消息弹窗可明确确认已读；长消息先查看全文，再在详情确认。关闭或取消不代表已读。
- 拔 USB 后按电源键进入 Tinta 休眠，记录至少 12 次周期的唤醒、联网与更新情况。网络正常时目标约 5 分钟；失败时不承诺仍满足该延迟。
- 断开 Wi-Fi 后发送消息，恢复网络后应补收；退出并重开应用不应重复弹出同一条消息。
- 撤回消息后下一次同步应移除内容及已经打开的弹窗。
- 在方舟撤销设备，下一次请求应被拒绝并清掉当前私密内容。
- 不插 USB 连续运行至少 24 小时记录耗电。USB 会改变休眠行为，不能用插线结果代替电池验收。

## 显示范围与恢复

首期只在 Tinta 看板模式里同步、提醒。退出到 Kindle 原生阅读界面后不承诺全局弹窗。界面显示最多前 20 项开放任务和 10 条备忘；更多任务到方舟查看。

同步失败保留最后成功数据并显示失败状态。出现凭证失效后在方舟重新绑定、导入新配置；证书失败先核对时间、域名和 CA，不能关闭校验。

需要退出时，从 Tinta 菜单关闭看板再退出 KOReader。需要恢复旧版本时，退出应用、接 USB，把安装目录 `backups/` 中对应软件文件复制回原位置；保留 Tinta 数据库与书籍，不执行恢复出厂设置。
