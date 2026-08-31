# 展会 AI 试戴 APP 自动更新设计

日期：2026-08-31
状态：代码与自动验证已完成，尚未部署，尚未完成平板实机验收

## 目标

展会试戴 APP 每次冷启动时自动检查新版本。发现新版本后暂停进入试戴，自动下载并发起安装：设备所有者模式静默完成，普通模式自动进入 Android 系统安装确认。任何检查、下载或安装失败都必须放行当前版本继续试戴，不能让展位因更新服务故障停摆。

首个具备该能力的正式版本固定为 `versionCode 10`、`versionName 1.9`。现有平板全部卸载旧包并重新安装一次使用固定 keystore 签名的 1.9 正式版，此后所有版本必须沿用同一签名。

## 不做的范围

- 不做设备列表、灰度发布、强制最低版本、远程停用或更新统计。
- 不增加数据库、方舟后台管理页或需要登录的更新 API。
- 不通过 Google Play、MDM 或第三方应用市场分发。
- 不允许更新清单指定任意 APK URL，也不允许跨当前 kiosk 服务器下载。
- 不把 keystore、密码或其他签名凭据提交到 Git。

## 更新通道

更新文件由当前 kiosk 服务器同源静态提供：

- 清单：`/expo-app/latest.json`
- APK：`/expo-app/leshine-expo-kiosk.apk`

APP 只从编译期 `R.string.start_url` 读取唯一 HTTPS kiosk 地址，并由该地址推导固定 origin。运行时没有 SharedPreferences 切源、三指配置、URL 输入、HTTP 兜底或第二套更新地址；资源非法时直接 fail closed。更换服务器必须重新构建并全量安装。

`latest.json` 使用固定结构：

```json
{
  "version_code": 10,
  "version_name": "1.9",
  "apk_size": 2543280,
  "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
}
```

示例中的摘要仅用于展示格式，不是发布值。清单不包含下载地址。字段缺失、类型错误、非正版本号、非正文件大小或非法 SHA-256 均视为检查失败，直接使用当前版本。

APK 与清单放在服务器独立目录 `/var/www/ark-updates/expo-kiosk/`，Nginx 将 `/expo-app/` 映射到该目录并设置 `Cache-Control: no-store`。不得放进 `/var/www/ark-dist`，因为前端部署的 `rsync --delete` 会删除不属于构建产物的 APK。

## 启动交互

APP 冷启动后显示原生黑金启动层，WebView 可以在其下初始化但不能向用户展示。单个 Activity 进程只启动一次更新检查，从相机、打印 App、系统安装页或权限设置返回时不重复触发。

检查流程如下：

1. 进入 APP 立即用原生启动层阻断试戴并请求同源 `latest.json`；连接超时 3 秒、读取超时 5 秒、单调总时限 10 秒。
2. 清单不可用、远端版本等于或低于本地版本：移除启动层，进入当前试戴页。
3. 远端版本更高：启动层切换为“发现新版本，正在升级”，展示版本号和下载进度，暂停进入试戴。
4. APK 下载到 APP 私有缓存的 `.part` 临时文件。连接超时 5 秒、读取超时 60 秒、单调总时限 120 秒，最大允许 100 MiB。
5. 校验全部通过后创建 `PackageInstaller` 会话并提交安装。
6. 安装成功后 Android 会替换并终止旧进程。`ACTION_MY_PACKAGE_REPLACED` 接收器尽力重新打开 APP；设备所有者/默认主屏场景应自动回到 kiosk，普通模式受 Android 后台拉起限制时允许停留在系统安装完成页，由系统提供“打开”入口。

启动层不提供取消按钮。更新已经开始但失败时，提示“升级未完成，继续使用当前版本，下次启动重试”，删除临时文件并立即进入旧版。

APP 的外部边界同时固定：WebView 摄像头只允许唯一 origin 的 `/expo/kiosk` 当前主框架申请单一 `VIDEO_CAPTURE`；登录页、后台页、音频或混合资源全部拒绝。通用选图和系统相机 fallback 不存在。设备所有者的 Lock Task allowlist 严格只有 APP 自身与编译期 `printer_package`，打印包为空或未安装时只提示，不启动隐式 Intent 或选择器。

## 下载与安全校验

清单和 APK 均使用唯一编译期 HTTPS origin 的固定相对路径，禁止重定向。HTTPS 连接复用现有 `PinnedTls`：自签 IP 证书必须命中内置指纹，正规证书走系统信任链。检查与下载除连接/读取超时外还有独立总时限；到期主动关闭输入流和连接，更新失败后放行旧版。

下载完成后按顺序检查：

1. 实际字节数等于 `apk_size`，且未超过 100 MiB。
2. 文件 SHA-256 等于清单中的 `sha256`。
3. Android 可以解析 APK，包名严格等于 `com.leshine.expokiosk`。
4. APK 的 `versionCode`、`versionName` 分别等于清单声明值，且 `versionCode` 严格大于当前安装版本，防止清单与 APK 错配、重放、重复安装和降级。
5. APK 签名证书与当前 APP 签名证书完全一致；Android 8–8.1 使用兼容的旧签名读取接口，Android 9+ 使用 `SigningInfo`。
6. 最终仍交由 Android `PackageInstaller` 进行系统级签名和包完整性校验。

任何一步不通过都关闭连接/安装会话、删除临时文件并进入旧版。日志记录失败阶段和系统状态码，但不记录签名密码或其他敏感信息。

## 两种安装模式

所有安装统一通过 `PackageInstaller.Session`，不向外部文件管理器暴露 APK。

### 设备所有者模式

当 `DevicePolicyManager.isDeviceOwnerApp(packageName)` 为真时提交安装会话。Android 对 fully managed device 的设备所有者允许无用户交互安装，更新完成后由系统通知用户“管理员已更新应用”。

### 普通模式

APP 声明 `REQUEST_INSTALL_PACKAGES`。提交会话后若收到 `STATUS_PENDING_USER_ACTION`，立即打开系统返回的确认 Intent。首次使用时系统可能要求工作人员开启“允许来自此来源安装应用”；从设置返回后继续当前待安装流程，不重复下载。

普通模式无法绕过 Android 的系统确认，这是平台安全边界，不伪装成真正静默安装。若工作人员取消、权限未开或安装失败，则放行旧版并在下次冷启动重新尝试。

## 组件边界

- `UpdateManifest`：只负责清单数据与严格解析。
- `UpdatePolicy`：纯 Kotlin 决策，判断版本、URL、大小、哈希、包名和签名是否可接受。
- `AppUpdateManager`：编排检查、下载、校验、安装和单进程幂等，不包含 Activity 视图代码。
- `UpdateInstallReceiver`：接收 `PackageInstaller` 状态；处理等待用户确认、失败和成功。
- `PackageReplacedReceiver`：收到自身更新完成广播后尽力重新打开 `MainActivity`。
- `MainActivity`：只负责显示启动/升级状态和在失败时放行 WebView，不直接实现网络或安装细节。
- `publish-update.ps1`：只接受已签名 release APK，提取元数据、计算摘要并按原子顺序发布。

这些组件通过小型状态回调通信：`Checking`、`Downloading(version, progress)`、`AwaitingUserAction`、`Installing`、`NoUpdate`、`Failed(message)`。`Checking`、`Downloading`、`AwaitingUserAction` 和 `Installing` 都阻挡试戴；`NoUpdate` 与 `Failed` 立即放行。

每个 `PackageInstaller` 会话在提交前把 `sessionId + 256-bit token` 同步写入 APP 私有存储，回调必须同时匹配 action、status、sessionId 和 token。等待用户确认只校验，成功/失败才一次性消费；旧会话、错 token 和重放回调全部忽略。下一次冷启动先失效旧 marker，再仅清理本包遗留会话，清理异常则本次检查 fail open 且不创建新会话。

## 签名与首装

Gradle release 签名从未提交的 `keystore.properties` 或等价环境变量读取。仓库只提交示例字段和 `.gitignore` 规则，不提供默认密码，也不在缺少签名配置时悄悄回退到 debug 签名。

首次上线步骤：

1. 生成并离线备份唯一正式 keystore，记录证书 SHA-256。
2. 构建并核验 1.9 release APK。
3. 如果旧 APP 是设备所有者，先执行 `dpm remove-active-admin`；无法解除时恢复出厂。
4. 卸载旧 debug/旧签名 APP，安装 1.9 release APK。
5. 需要真锁定的平板重新设置设备所有者并恢复 kiosk/打印 App 白名单。
6. 在一台设备所有者平板和一台普通模式平板分别完成首次更新验收后，再铺开其他设备。

## 原子发布

`tablet-kiosk/scripts/publish-update.ps1` 的发布顺序固定：

1. 解析 release APK，确认包名、版本号和签名证书；拒绝 debug 或低版本包。
2. 生成 SHA-256 和清单，所有产物先写本地临时目录。
3. 上传 APK 临时文件到北京云更新目录，在服务器复算 SHA-256。
4. 服务器使用同目录 `mv` 原子替换正式 APK。
5. 最后上传并原子替换 `latest.json`。
6. 用 HTTPS 自签证书指纹验证线上清单和 APK 摘要一致后才报告发布成功。

清单最后发布可以缩短错配窗口，但清单与 APK 是两次独立 HTTP 请求，发布瞬间仍可能读到不同代文件，不能宣称跨请求原子。APP 会用精确大小和 SHA-256 拒绝错配并 fail open；服务器事务保证切换失败后不会永久留下错误正式配对。

## 测试与验收

开发采用测试先行，至少覆盖：

- 清单合法/缺字段/类型错误/非法 SHA-256/超大文件。
- 远端版本更高、相同、较低以及下载后版本与清单不一致。
- origin 推导、相对路径固定、跨 origin 重定向拒绝。
- 文件大小、SHA-256、包名和 Android 8/9+ 签名比较。
- 单进程只检查一次，从权限页或安装页返回不重复下载。
- `PackageInstaller` 的成功、等待用户确认、用户取消、存储不足、签名冲突和通用失败状态。
- 更新检查/下载失败放行 WebView；发现有效新版时 WebView 始终被启动层遮挡。
- 原有 kiosk 导航白名单测试继续通过，更新机制不得成为打开方舟后台或外部页面的新入口。

自动验证命令：

```powershell
npm run test:expo-kiosk
npm run build
gradle testDebugUnitTest assembleDebug
python scripts/check_conventions.py --base main
```

实机验收矩阵：

1. 设备所有者：1.9 → 1.10 静默下载、安装、回到 kiosk。
2. 普通模式：自动下载、打开系统确认、安装后可回到 kiosk。
3. 断网、404、超时：manifest 检查总预算 10 秒，APK 下载总预算 120 秒；连接或读取先失败时会更快放行旧版。
4. 损坏 APK、错误摘要、错误包名、错误签名、低版本：拒绝安装并进入旧版。
5. 下载中返回、旋转、切到打印 App再回来：不并发启动第二次更新。

## 完成标准

- 每次冷启动都检查更新，正常无新版时不影响试戴登录和页面加载。
- 有合法新版时自动下载；设备所有者静默安装，普通模式自动进入系统确认。
- 更新服务或安装失败时旧版仍可用，下次冷启动重试。
- 更新文件只能来自当前 kiosk origin 的固定路径，并通过大小、摘要、包名、版本和签名五重校验。
- 发布流程可重复、原子、不会把 keystore 或密码写入仓库。
- 自动测试、Android 构建、前端构建和项目约定检查通过；两种实机模式、失败矩阵和正式部署仍是上线门禁，完成前不得宣称已铺开。
