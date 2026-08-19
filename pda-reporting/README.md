# 莱莎内贸报工 PDA Android APP

这是内贸订单微信小程序报工功能的 PDA 专用 Android 客户端。APP 不调用摄像头，直接接收 PDA
扫描头输出；报工校验、工序分配、数量守恒、逐件流转、幂等和撤销仍复用方舟现有后端。

## 功能

- 方舟账号密码登录，报工记录归入当前工人
- 明细流转码 `ARK-D`：扫描后确认报工数量，默认全部，也可改小拆批
- 单件码 `ARK-DU`：按账号权限进入逐件模式，默认识别后自动报 1 件
- 扫描时展示产品、客户、订单、当前工序、图文要求和全工序进度
- 今日报工次数 / 件数 / 明细记录，支持撤销本人记录
- 弱网提交使用稳定的 `request_id` 重试，避免响应丢失后重复累计
- 成功 / 失败声音和振动反馈，屏幕常亮
- 服务器地址可在 APP 内修改；默认 `https://leshine.work`

## 扫描头配置

### 方案一：键盘输出（推荐）

在 PDA 扫描设置中选择：

1. 输出方式：键盘模拟 / Keyboard Wedge
2. 结束符：回车（Enter）
3. 编码：UTF-8 或默认文本

APP 在报工页全局接收扫描按键，不要求光标停在输入框中；没有回车后缀时，连续输入停止 180ms
也会自动识别。软键盘编辑报工数量不受影响。

### 方案二：广播输出

通用自定义配置（Zebra DataWedge 等）：

- Intent action：`com.leshine.pdareporting.SCAN`
- Category：`android.intent.category.DEFAULT`
- Delivery：Broadcast Intent
- 数据 Extra：DataWedge 默认 `com.symbol.datawedge.data_string`，或 `data`

APP 也内置了 Sunmi、Newland、Honeywell、Urovo/常见 ScannerService 的常用 action / extra。
实际 PDA 型号若使用其他广播字段，优先改成键盘输出；也可在 `ScannerInput.kt` 增补该厂商协议。

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
4. 逐件工人建议保留“逐件二维码识别后自动报 1 件”；数量报工始终需要确认数量。

APP 不申请相机、相册、定位或存储权限。生产发布建议生成固定 release keystore；后续版本沿用同一
keystore，PDA 才能覆盖升级而不丢登录配置。
