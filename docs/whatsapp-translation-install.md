# WhatsApp 实时翻译安装指南

## 使用范围

只支持 WhatsApp Web 的**一对一文字消息**：收件自动翻译，发件先翻译预览再替换内容；群组、社区、媒体、语音、文件、贴纸和系统消息不翻译。扩展不会替你发送消息，发送动作仍由你在 WhatsApp 完成。

## 前置条件

- 莱莎 Ark 账号且有 `whatsapp_translation:write` 权限。
- Windows Chrome、Windows Edge 或 macOS Chrome。
- 设备总数不超过 5 台。

ZIP 是公开下载的编译代码包，不含密钥或聊天数据；没有 Ark 授权时它不能翻译。

## 安装

1. 登录 Ark，进入「系统管理 → WhatsApp 实时翻译」。
2. 记录/核对页面显示的 ZIP SHA-256，再点击下载 ZIP。
3. 解压 ZIP 到一个稳定目录，例如 Windows 用 `C:\Tools\whatsapp-translation`，macOS 用 `~/Tools/whatsapp-translation`。不要把解压目录直接放在临时目录。
4. 打开 `chrome://extensions`（Edge 是 `edge://extensions`），开启「开发者模式」。
5. 点击「加载已解压的扩展程序」，选择解压后包含 `manifest.json` 的目录。
6. 在浏览器扩展栏固定「莱莎 WhatsApp 实时翻译」。
7. 点击扩展图标，按提示打开 Ark 授权页并完成配对；批准后扩展应显示已授权。

## 更新

1. 从 Ark 下载新 ZIP，核对新的 SHA-256。
2. 清空原安装目录内容，再解压新 ZIP。
3. 回到扩展管理页点击刷新，并确认版本号已更新。
4. 刷新所有已打开的 WhatsApp Web 页面，重新载入新版页面脚本（只刷新扩展不会替换已打开页面里的旧脚本）。设备授权会继续生效，除非版本被强制阻断。

## 授权管理

- 查看和自撤销设备：扩展弹窗或 Ark 授权页。
- 管理员撤销设备：「系统管理 → WhatsApp 实时翻译 → 设备管理」。
- 卸载：在扩展管理页移除扩展，并撤销当前设备。设备数据只保留哈希、状态和用量元数据。
