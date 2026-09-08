# 莱莎内贸报工 PDA Android APP

这是内贸订单微信小程序报工功能的 PDA 专用 Android 客户端。APP 不调用摄像头，直接接收 PDA
扫描头输出；报工校验、工序分配、数量守恒、逐件流转、幂等和撤销仍复用方舟现有后端。
最低支持 Android 6.0（API 23），已覆盖 Android 6.0.1 PDA。

## 1.0.5：旧安卓 HTTPS 证书兼容

2026-09-05 服务器改用 Let's Encrypt 后，Android 6.0.1 的系统证书库缺少 ISRG Root X1，
登录可能显示“网络连接失败，请检查 Wi-Fi 和服务器地址”。1.0.5 为 Android 6/7（API 23–25）
访问 `leshine.cloud`、`www.leshine.cloud`、`leshine.work`、`www.leshine.work` 时补充该公开根证书，
保留系统已有根证书与默认域名校验。其他域名和 Android 8 及以上仍使用系统默认 HTTPS 配置。
证书、DNS、超时等连接失败分别显示对应处理提示。

根证书来自 [Let's Encrypt 官方](https://letsencrypt.org/certs/isrgrootx1.pem)，存放于
`app/src/main/res/raw/isrg_root_x1.pem`。DER SHA-256：
`96bcec06264976f37460779acf28c5a7cfe8a3c0aae11a8ffcee05c0bddf08c6`。
参考：[官方兼容说明](https://letsencrypt.org/docs/certificate-compatibility/)。

覆盖安装时沿用原签名，不卸载旧 APP，以保留服务器设置、登录配置和待确认报工。
服务器地址可继续使用 `https://www.leshine.cloud`，不需要添加 `/api`。
如仍提示 HTTPS 失败，先检查 PDA 日期时间，再提供完整错误提示。

单元测试包含证书指纹、根证书补充/保留、拒绝无关证书、旧系统与域名边界及错误分类。
设置环境变量 `PDA_TLS_SMOKE=1` 后运行 `testDebugUnitTest`，额外使用不含 ISRG 根证书的
JVM 信任库复现线上 TLS 握手失败，再验证补根后的三个线上入口（仅无凭据 GET，不写业务数据）。
这项检查不替代 Android 6.0.1 真机登录与扫码验收。

## 功能

- 方舟账号密码登录，报工记录归入当前工人
- 明细流转码 `ARK-D`：扫描后确认报工数量，默认全部，也可改小拆批
- 单件码 `ARK-DU`：只有逐件扫描报工权限的账号，实体键扫码后固定自动报 1 件，无需点击确认
- 逐件模式复用同一个结果弹框，可直接连续扫描下一件；绿色 `✓ 报工成功` 提示 3 秒后自动隐藏
- 扫描时醒目展示产品、客户、订单、单件编号、当前工序，并保留图文要求和全工序进度
- 今日报工次数 / 件数 / 明细记录，支持撤销本人记录
- 弱网提交使用稳定的 `request_id` 重试并在提交前落盘，APP 重启后仍可恢复同一笔
- 成功 / 失败声音和振动反馈，屏幕常亮
- HTTPS 服务器地址可在 APP 内修改；默认 `https://leshine.work`，不允许明文 HTTP 传输凭据

## 扫描头配置

### A4G / A88 / A133 / K62：实体键广播输出（推荐）

在 PDA 扫描设置中选择：

1. 输出方式：广播输出
2. 广播动作：`android.intent.ACTION_DECODE_DATA`
3. 广播数据标签：`barcode_string`

打开 APP 的内贸报工页后，直接按 PDA 实体扫描键。扫描头由设备服务触发出光，APP 被动接收二维码
广播并进入报工流程；APP 不提供屏幕扫描按钮，也不发送 `com.rskj.android.F6_KEY_DOWN`。

### 其他设备：键盘输出

在 PDA 扫描设置中选择：

1. 输出方式：键盘模拟 / Keyboard Wedge
2. 结束符：回车（Enter）
3. 编码：UTF-8 或默认文本

APP 在报工页全局接收扫描按键，不要求光标停在输入框中；没有回车后缀时，连续输入停止 180ms
也会自动识别。软键盘编辑报工数量不受影响。

### 其他设备：自定义广播输出

通用自定义配置（Zebra DataWedge 等）：

- Intent action：`com.leshine.pdareporting.SCAN`
- Category：`android.intent.category.DEFAULT`
- Delivery：Broadcast Intent
- 数据 Extra：DataWedge 默认 `com.symbol.datawedge.data_string`，或 `data`

APP 也内置了 Sunmi、Newland、Honeywell、Urovo/常见 ScannerService 的常用 action / extra。
实际 PDA 型号若使用其他广播字段，优先改成键盘输出；也可在 `ScannerInput.kt` 增补该厂商协议。
逐件模式是否自动报工只由账号权限决定，键盘和广播输入行为一致；按数量报工的账号仍需核对数量并手工确认。

## 构建

建议用 Android Studio（JDK 17+）打开 `pda-reporting/`，执行 Build → Build APK(s)。

仓库已有 Gradle 8.7 wrapper，可在命令行复用：

```bash
cd pda-reporting
sh ../tablet-kiosk/gradlew -p . clean test assembleDebug --console=plain
```

产物：`app/build/outputs/apk/debug/app-debug.apk`。

## 安装与首次使用

1. PDA 允许安装未知来源应用，将 APK 拷到设备并安装；或连接 ADB 后运行
   `adb install -r app-debug.apk`。
2. 打开 APP，使用方舟工号和密码登录。
3. 扫一张内贸流转卡验证扫描头；若没有响应，按上文切换为“键盘输出 + 回车”。
4. 逐件工人扫码后会自动报 1 件；看到绿色成功提示后可直接按实体键扫描下一件。数量报工始终需要确认数量。

APP 不申请相机、相册、定位或存储权限。生产发布建议生成固定 release keystore；后续版本沿用同一
keystore，PDA 才能覆盖升级而不丢登录配置。
