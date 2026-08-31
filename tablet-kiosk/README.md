# 莱莎展会 AI 试戴 — 平板 Kiosk APK

一个精简的 Android WebView 壳，把 `leshine.work/expo/kiosk` 封装成全屏、可锁定的展会平板应用，
并提供**原生一键打印**：网页「打印这张」→ 下载合成原图 → 写进系统相册 → 查回确认存好 → 打开打印 App。

> 页面逻辑全在网站里，这个壳只是容器：网站更新后 APK 无需重打，重启即加载最新页面。

## 上机前只改两处（`app/src/main/res/values/strings.xml`）

1. `start_url`：**默认值**，当前 `https://154.8.205.162/expo/kiosk`（北京云端展会实例，自签证书见下）。
   平板上可长按右上角现改（见下「现场改地址」），改完存本地、优先于此默认值——换服务器不必重打包。
2. `printer_package`：**你打印机 App 的包名**。留空则「打印」按钮会弹系统「打开方式」让工作人员选 App。
   - 查包名：平板 设置 → 应用 → 打开打印 App → 详情里的包名；或电脑连平板
     `adb shell pm list packages | grep <打印机品牌关键词>`。

## 现场改地址（不用重装）

- **三根手指同时按住屏幕 2.5 秒** → 弹「服务器地址」输入框 → 保存并重载。
  只填 IP 或域名即可（可带 `:端口`），**路径固定 `/expo/kiosk` 由代码拼**；「恢复默认」回到 strings.xml 的值。
- 页面打不开时（IP 写错 / 服务器没起 / 断网）自动显示黑底兜底页，带「重试」「改地址」按钮，
  并按 5s→10s→…→60s 退避**自动重连**（展位无人值守时网络抖动能自愈）。
- 换了 host 等于换了浏览器源，**登录态不跟着走**，需重新用展会账号登录一次。

> **为什么是三指而不是长按某个角**：1.2 版用的「长按右上角 3 秒」与 kiosk 自己的「⌂ 主页」
> 「✕ 关闭」按钮完全重叠（`.xk-head` 高 52px、右边距 22px），客户长按主页键就能拿到 URL 输入框。
> 三指手势与页面布局无关，客户不可能误触。配合"只收 origin"，就算被摸到也只能换服务器、
> 不能把展位平板变成自由浏览器。

## HTTPS 与相机（1.4 起）

kiosk 的内嵌取景框依赖 `getUserMedia`，而浏览器只在 **secure context** 下开放它——http 页面拿不到。
IP 又申请不到 CA 证书，所以服务器挂了一张 10 年自签证书，客户端做**证书指纹 pinning**：

- 指纹在 `strings.xml` 的 `pinned_cert_sha256`，与 `openssl x509 -fingerprint -sha256` 口径一致
- `PinnedTls.kt` 同时服务两条链路：WebView 的 `onReceivedSslError`、以及「一键打印」下载原图用的
  裸 `HttpURLConnection`（**只给 WebView 放行的话打印会在 TLS 握手上断掉**）
- 指纹不匹配时**回落系统信任链**，两边都不过才拒绝 → 备案后换正规证书，这里自动走系统校验，代码不用改
- **换服务器证书必须同步更新指纹并重打 APK**，否则平板打不开（会显示「证书校验未通过」兜底页）

`usesCleartextTraffic` 仍保持 `true`：现场局域网兜底可能还要用 http 直连。

> **http 回退路径也还在**（万一现场只能用 http）：非 secure context 下 `CaptureScreen.vue` 会降级到
> 系统相机，而这条降级链在原生侧要自己接——`FileChooserParams.createIntent()` 只给
> `ACTION_GET_CONTENT`、完全忽略 `<input capture>`，所以 `onShowFileChooser` 手动把
> `ACTION_IMAGE_CAPTURE` 塞进 `EXTRA_INITIAL_INTENTS`，并在 `onActivityResult` 回退到自己占的
> `EXTRA_OUTPUT` Uri（相机成功时返回的 `data` 是 null，`parseResult` 什么也拿不到）。

> **分享二维码故意留在 http**：客户手机不认这张自签证书（微信内置浏览器多半白屏），
> `ResultScreen.vue` 在 host 为裸 IP 且无显式端口时把分享链接降回 http。

## 构建 APK

**方式一（推荐，最省事）**：用 Android Studio 打开本目录 `tablet-kiosk/`，等 Gradle 同步完，
菜单 Build → Build Bundle(s)/APK(s) → Build APK(s)。产物在 `app/build/outputs/apk/`。

**方式二（命令行）**：装好 JDK 17+ 与 Android SDK（本仓库开发机已具备），在本目录执行：

```bash
export JAVA_HOME="/c/Program Files/Android/Android Studio/jbr"
export ANDROID_HOME="/c/Users/windb/AppData/Local/Android/Sdk"
"/c/Users/windb/.gradle/wrapper/dists/gradle-8.7-bin/f06yd7m8w1d0inql2joytq4az/gradle-8.7/bin/gradle" \
  assembleDebug --offline --console=plain
```

> **别用 `./gradlew`**（2026-07-24 复现）：wrapper 会去 services.gradle.org 重下发行包，本机网络下必卡，
> 且卡住的进程会给 `gradle-8.7-bin.zip` 加独占锁，导致后续每次构建都在
> `Timeout of 120000 reached waiting for exclusive access` 上失败。撞上时先
> `Get-CimInstance Win32_Process -Filter "Name='java.exe'"` 找到 wrapper 进程杀掉，再按上面用**已解压的**
> gradle 二进制跑（注意有两个 hash 目录，带 `.ok` 标记、内含 `gradle-8.7/` 的那个才是完整的）。

> 已在开发机验证可构建（2026-07-16）：产物 `app/build/outputs/apk/debug/app-debug.apk`（约 2.1MB），
> compileSdk 35 / AGP 8.5.2 / Gradle 8.7 / JDK 21(JBR)。debug 版可直接装测试；正式展位用签名 release。

### 正式签名与自动更新（1.9 / code 10 起）

自动更新依赖 Android 的签名连续性。所有平板首次统一换装 1.9 后，后续 APK **必须使用同一个正式 keystore**；
密钥丢失后无法覆盖升级已安装的平板，只能再次全量卸载/恢复出厂并重装。

首次只做一次：用 JDK `keytool` 在仓库外生成 RSA 4096、SHA256withRSA 的长期证书，别名固定
`leshine-expo`，DN 不得是 Android Debug。生成时让 `keytool` 交互读取密码，避免密码进入命令历史。

```powershell
New-Item -ItemType Directory -Force C:\secure
& 'C:\Program Files\Android\Android Studio\jbr\bin\keytool.exe' -genkeypair `
  -keystore C:\secure\leshine-expo-release.jks -storetype PKCS12 -alias leshine-expo `
  -keyalg RSA -keysize 4096 -sigalg SHA256withRSA -validity 10000 `
  -dname 'CN=LeShine Expo Kiosk, OU=AI Technology Support, O=LeShine, L=Qingdao, ST=Shandong, C=CN'
Copy-Item .\keystore.properties.example .\keystore.properties
# 只在本机编辑 keystore.properties 的四个字段；不要把密码粘到命令或聊天中。
```

`C:\secure\leshine-expo-release.jks` 与 `keystore.properties` 必须做两份离线备份，分开保管并实际验证可恢复。
这是上线硬门禁；当前开发机生成文件不等于已经完成离线备份。仓库只跟踪示例，真实 properties、`*.jks`、
`*.keystore` 均被 `.gitignore` 排除。实际 task graph 只要包含 release 工作（包括 `build`、`assemble` 这类聚合任务），
配置缺失、字段为空或文件不存在时构建会在打包前直接失败，绝不回退为 debug/unsigned；纯 debug/test 不受影响。

在 `tablet-kiosk` 目录用本机已解压 Gradle 构建并核验：

```powershell
$gradle = 'C:\Users\windb\.gradle\wrapper\dists\gradle-8.7-bin\f06yd7m8w1d0inql2joytq4az\gradle-8.7\bin\gradle.bat'
& $gradle assembleRelease --offline --console=plain
$tools = "$env:LOCALAPPDATA\Android\Sdk\build-tools\37.0.0"
& "$tools\aapt.exe" dump badging .\app\build\outputs\apk\release\app-release.apk
& "$tools\apksigner.bat" verify --print-certs .\app\build\outputs\apk\release\app-release.apk
Get-FileHash .\app\build\outputs\apk\release\app-release.apk -Algorithm SHA256
```

发布器只接受 `com.leshine.expokiosk`、`versionCode > 9`、非空版本名且不是 Android Debug 证书的有效签名包。
先离线准备并核对清单，再显式提供 IP 自签 CA 发布；`-PrepareOnly` 不需要 CA，也不会调用 curl/ssh/scp。

```powershell
.\scripts\publish-update.ps1 -ApkPath .\app\build\outputs\apk\release\app-release.apk -PrepareOnly
# 仅首次创建空通道：线上清单必须 404、APK/清单必须都不存在，而且包必须是 code 10。
.\scripts\publish-update.ps1 -ApkPath .\app\build\outputs\apk\release\app-release.apk `
  -InitializeChannel -CaCertificatePath C:\secure\expo-ip.crt
# 以后发布禁止再带 -InitializeChannel。
.\scripts\publish-update.ps1 -ApkPath .\app\build\outputs\apk\release\app-release.apk `
  -CaCertificatePath C:\secure\expo-ip.crt
```

发布器固定写入同源 `/expo-app/latest.json` 与 `/expo-app/leshine-expo-kiosk.apk`。远端 owner token 锁会阻止并发发布，
切换前保存本事务私有旧配对，先替换 APK、最后替换清单；切换或 HTTPS 回读校验失败会恢复旧配对，首发失败则恢复空通道。
两个固定 URL 是两次独立 HTTP 请求，发布瞬间仍可能短暂读到清单/APK不匹配，**不能宣称跨请求事务原子**；APP 会在
大小或 SHA-256 校验处 fail-closed，继续使用旧版并在下次冷启动重试。更新源不能指定其他 URL，也不会进入方舟后台页面；断网、404、校验或安装失败时，
APP 会放行当前版本继续试戴，下次冷启动重试。APP 自动识别安装模式：设备所有者平板静默安装，普通平板下载完成后
只打开 Android 系统安装确认，不提供绕过系统确认的开关，也不需要工作人员切换模式。

## 装到平板 + 首次配置

1. 首次迁移到稳定签名时，设备所有者先运行
   `adb shell dpm remove-active-admin com.leshine.expokiosk/.AdminReceiver`；解除失败则恢复出厂。卸载所有旧
   debug/旧签名版本，再安装 1.9 release（不同签名不能覆盖安装）。
2. 允许「安装未知来源应用」，把 release APK 拷进平板安装（或 `adb install app-release.apk`）。
3. 打开一次，授予**摄像头**权限（拍照合成要用）。
4. 用**专用「展会设备」账号**（仅 `expo:write`，见 `docs/expo-kiosk-tablet-setup.md`）登录一次。
5. 设为默认主屏（可选，软锁）：设置 → 默认应用 → 主屏幕应用 → 选「莱莎AI试戴」。
   之后在打印 App 里按 Home 键即回 kiosk。

需要真锁定的平板在初始/恢复出厂状态重新设置设备所有者并恢复 kiosk、打印、相机和文档选择器白名单。
正式铺开前，必须至少用一台设备所有者平板验证静默更新、一台普通平板验证 Android 系统安装确认；同时验证
离线/404/损坏包会继续进入当前试戴。回滚不能降低 `versionCode`：必须用旧源码构建一个**更高 versionCode** 的新包，
仍使用同一正式 keystore 后重新发布。

## 真锁定（Lock Task，可选但展位推荐）

让客户完全退不出、又允许切到打印 App：把本应用设为**设备所有者**（平板需处于未添加任何账号的
初始/恢复出厂状态）：

```
adb shell dpm set-device-owner com.leshine.expokiosk/.AdminReceiver
```

设成功后 App 会自动 `startLockTask()`，白名单 = **自身 + 打印 App + 系统相机 + 文档选择器**
（后两个 1.3 起才加：漏掉的话锁定状态下 `startActivityForResult` 会被系统静默拒绝——不抛异常也不回
result——客户点「拍照/选图」毫无反应，且此后所有 file input 永久哑掉，直到重启 App）。
其余一律锁死。撤销：`adb shell dpm remove-active-admin com.leshine.expokiosk/.AdminReceiver`。

> **本机 adb 连不上荣耀平板**（2026-07-24 查明）：荣耀的 ADB 接口在注册表里注册的是自家
> `DeviceInterfaceGUID {8a4d20a8-a2fa-4495-bee2-e87ece4a5356}`，而 adb 只认 Google 的
> `{F72FE0D4-CBCB-407d-8814-9ED673D0DD6B}`，所以 `adb devices` 恒为空（**不是没开 USB 调试**）。
> 装 APK 可以走 MTP 拷进 `内部存储/Download` 手点安装；要用 adb（含上面的设备所有者命令）得先给
> `HKLM\SYSTEM\CurrentControlSet\Enum\USB\VID_339B&PID_107D&MI_02\<实例>\Device Parameters`
> 加一条 REG_MULTI_SZ `DeviceInterfaceGUIDs` 填 adb 的 GUID（需管理员），再禁用/启用该设备。

> **未设为设备所有者时，App 不会强制固定屏幕**（只全屏沉浸），可自由切出去——方便测试/调试。
> 只有设为设备所有者后才真锁定。不想动 ADB 的软锁方案：用系统自带「屏幕固定」手动固定（较弱、可退出）。

## 行为要点

- 全屏沉浸（隐藏状态栏/导航栏）、屏幕常亮、吞掉返回键。
- 原生 WebView 只放行 `/expo/kiosk` 与强制回到 kiosk 的 `/login`；方舟首页、后台路由、公开页、跨域和非 HTTP 主框架导航一律拦截并送回 kiosk。网页路由守卫同时锁定当前标签页，认证异常也不会使用方舟后台的通用跳转。
- 摄像头/麦克风权限自动授给网页；文件选择兜底可用。
- 登录态（access token + refresh cookie）持久在 WebView 存储，配合每日重载续期（见 setup 文档）。
- 「打印这张」严格顺序：**存相册成功并查回确认后**才启动打印 App；失败弹「保存到相册失败，请重试」。
- 打印用的是合成**原图**（1024×1536 原清晰度），非压缩展示版。

## APP 图标

品牌花体 S（自字标原尺抠出）+ 墨底金渐变，与 kiosk 页面同一套黑金语系。
源图、生成脚本与设计取舍记录在 `icon/`（一条命令可重新生成全套密度资源）。

## 排障：整屏纯黑（2026-07-24 实战）

现象是打开 App 一片纯黑、看不到任何内容，**但页面其实好好的**。判定与手段：

```bash
# 1. 先确认屏幕不是息屏（否则 screencap 拍到的黑毫无意义）
adb shell dumpsys power | grep mWakefulness   # Asleep 就先 input keyevent KEYCODE_WAKEUP

# 2. debug 包的 WebView 自带 devtools，直接问它页面状态
adb forward tcp:9333 localabstract:webview_devtools_remote_$(adb shell pidof com.leshine.expokiosk)
curl http://127.0.0.1:9333/json/list        # 看 url / title 对不对
# 再用 CDP 的 Page.captureScreenshot 拿 WebView 自己渲染的那一帧
```

**若 CDP 截图正常、设备 screencap 纯黑 → 问题在"绘制"不在"加载"**，别再查网络和证书。
本次真凶：`showError` 里 `webView.onPause()` + `hideError` 里 `onResume()`，而 hideError 由
`onPageFinished` 调用——等于用页面回调驱动本该跟随 Activity 生命周期的开关，荣耀 WebView 上
合成器会丢掉首帧。**这两个方法只能在 Activity 的 onPause/onResume 里成对调用，或者干脆不用。**

顺带记两条 adb 实况：`adb install` 会被荣耀弹两层确认框挡住（「继续」→ 勾选风险知情 →「继续安装」，
不点就一直挂着）；`adb shell uiautomator dump` 在本机取不到内容，看界面直接用 `exec-out screencap`。

## 相关

- 平板锁定/账号/网络等现场配置：`../docs/expo-kiosk-tablet-setup.md`
- 前端按钮：`frontend/src/views/expo/kiosk/ResultScreen.vue` 的 `printCurrent()` → `window.Android.printPhoto(url)`
