# 莱莎内贸报工 PDA Android APP

这是内贸订单微信小程序报工功能的 PDA 专用 Android 客户端。APP 不调用摄像头，直接接收 PDA
扫描头输出；报工校验、工序分配、数量守恒、逐件流转、幂等和撤销仍复用方舟现有后端。
最低支持 Android 6.0（API 23），已覆盖 Android 6.0.1 PDA。

## 功能

- 方舟账号密码登录，报工记录归入当前工人
- 明细流转码 `ARK-D`：扫描后确认报工数量，默认全部，也可改小拆批
- 单件码 `ARK-DU`：按账号权限进入逐件模式；键盘扫描默认自动报 1 件，广播输入始终确认
- 扫描时展示产品、客户、订单、当前工序、图文要求和全工序进度
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
广播 action 可被同设备其他 APP 模拟，因此逐件广播扫码不会自动提交，必须人工确认；自动报 1 件仅对
推荐的键盘模拟模式开放。

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
4. 逐件工人使用键盘模拟时建议保留“逐件二维码识别后自动报 1 件”；数量报工始终需要确认数量。

APP 不申请相机、相册、定位或存储权限。生产发布建议生成固定 release keystore；后续版本沿用同一
keystore，PDA 才能覆盖升级而不丢登录配置。
