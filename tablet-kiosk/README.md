# 莱莎展会 AI 试戴 — 平板 Kiosk APK

一个精简的 Android WebView 壳，把 `leshine.work/expo/kiosk` 封装成全屏、可锁定的展会平板应用，
并提供**原生一键打印**：网页「打印这张」→ 下载合成原图 → 写进系统相册 → 查回确认存好 → 打开打印 App。

> 页面逻辑全在网站里，这个壳只是容器：网站更新后 APK 无需重打，重启即加载最新页面。

## 上机前只改两处（`app/src/main/res/values/strings.xml`）

1. `start_url`：默认 `https://leshine.work/expo/kiosk`，一般不用改。
2. `printer_package`：**你打印机 App 的包名**。留空则「打印」按钮会弹系统「打开方式」让工作人员选 App。
   - 查包名：平板 设置 → 应用 → 打开打印 App → 详情里的包名；或电脑连平板
     `adb shell pm list packages | grep <打印机品牌关键词>`。

## 构建 APK

**方式一（推荐，最省事）**：用 Android Studio 打开本目录 `tablet-kiosk/`，等 Gradle 同步完，
菜单 Build → Build Bundle(s)/APK(s) → Build APK(s)。产物在 `app/build/outputs/apk/`。

**方式二（命令行）**：装好 JDK 17+ 与 Android SDK（本仓库开发机已具备），在本目录执行
`./gradlew assembleDebug`。若 `./gradlew` 因网络取不到 Gradle 发行包，直接用已缓存的 gradle：
`~/.gradle/wrapper/dists/gradle-8.7-bin/*/gradle-8.7/bin/gradle assembleDebug`。

> 已在开发机验证可构建（2026-07-16）：产物 `app/build/outputs/apk/debug/app-debug.apk`（约 2.1MB），
> compileSdk 35 / AGP 8.5.2 / Gradle 8.7 / JDK 21(JBR)。debug 版可直接装测试；正式展位用签名 release。

**签名**：展位内部使用，用一个自签名 keystore 即可（Android Studio: Build → Generate Signed
Bundle/APK，一路新建 keystore）。debug 版也能装，但每次重装会清数据（含登录态），正式用签名 release。

## 装到平板 + 首次配置

1. 允许「安装未知来源应用」，把 APK 拷进平板安装（或 `adb install app-release.apk`）。
2. 打开一次，授予**摄像头**权限（拍照合成要用）。
3. 用**专用「展会设备」账号**（仅 `expo:write`，见 `docs/expo-kiosk-tablet-setup.md`）登录一次。
4. 设为默认主屏（可选，软锁）：设置 → 默认应用 → 主屏幕应用 → 选「莱莎AI试戴」。
   之后在打印 App 里按 Home 键即回 kiosk。

## 真锁定（Lock Task，可选但展位推荐）

让客户完全退不出、又允许切到打印 App：把本应用设为**设备所有者**（平板需处于未添加任何账号的
初始/恢复出厂状态）：

```
adb shell dpm set-device-owner com.leshine.expokiosk/.AdminReceiver
```

设成功后 App 会自动 `startLockTask()`，并把「自身 + strings.xml 里的打印 App 包名」加进白名单，
其余一律锁死。撤销：`adb shell dpm remove-active-admin com.leshine.expokiosk/.AdminReceiver`。

> **未设为设备所有者时，App 不会强制固定屏幕**（只全屏沉浸），可自由切出去——方便测试/调试。
> 只有设为设备所有者后才真锁定。不想动 ADB 的软锁方案：用系统自带「屏幕固定」手动固定（较弱、可退出）。

## 行为要点

- 全屏沉浸（隐藏状态栏/导航栏）、屏幕常亮、吞掉返回键。
- 摄像头/麦克风权限自动授给网页；文件选择兜底可用。
- 登录态（access token + refresh cookie）持久在 WebView 存储，配合每日重载续期（见 setup 文档）。
- 「打印这张」严格顺序：**存相册成功并查回确认后**才启动打印 App；失败弹「保存到相册失败，请重试」。
- 打印用的是合成**原图**（1024×1536 原清晰度），非压缩展示版。

## 相关

- 平板锁定/账号/网络等现场配置：`../docs/expo-kiosk-tablet-setup.md`
- 前端按钮：`frontend/src/views/expo/kiosk/ResultScreen.vue` 的 `printCurrent()` → `window.Android.printPhoto(url)`
