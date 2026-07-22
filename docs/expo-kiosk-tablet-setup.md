# 展会 AI 试戴 — Android 平板 Kiosk 上机指南（2026-07-15；入口地址 2026-07-22 更新）

目标：展位平板全天锁定在展会实例的 kiosk 页，全屏无浏览器痕迹、客户跑不出去、
崩溃自恢复、始终登录态。方案 = **专用 kiosk 浏览器（Fully Kiosk Browser）**，零开发、纯配置。

> **Start URL 按当时链路状态三选一**（2026-07-22 起北京云展会实例上线，见 runbook「云端展会实例」节）：
> ① leshine.work 备案批复后：`https://<正式域名>/expo/kiosk`（首选，相机原生可用）；
> ② 备案前公网：`http://154.8.205.162/expo/kiosk`（北京实例 IP，无 HTTPS——拍照走「调用系统相机」兜底）；
> ③ 现场局域网直连：现场笔记本跑方舟 + 平板同 WiFi 访问其 IP（无公网依赖，速度最优）。
> 旧地址 `https://leshine.work/expo/kiosk`（走新加坡隧道回办公室）仍可用但延迟大，不推荐展会现场使用。

登录已由前端守卫强制：未登录进不了 kiosk（`router/index.js` 校验 `expo:write`），
合成端点后端再校验一道。本指南只解决"怎么把它锁在平板上全天跑"。

---

## 一、先建一个专用「展会设备」账号（后台，5 分钟）

**为什么**：别用管理员号登平板。万一平板被人乱点/丢失，设备账号只能试戴，碰不到后台与客户数据；
丢了在后台停用该账号即可，秒级止损。

1. 角色管理 → 新建角色「展会设备」，**只勾 `expo:write` 这一个权限**（它覆盖 register/建会话/
   合成/发色/场景/发型选择/销售面板/反馈全部 kiosk 端点，已逐一核对）。
2. 用户管理 → 新建用户，如 `expo-booth`，分配「展会设备」角色，设一个只你知道的强密码。
3. 记下账号密码，装机时用它登录一次即可（下文第四步）。

## 二、平板准备

- Android 8+ 平板，建议 10 寸、内存 ≥3G；固定电源供电（展位全天开机）。
- 系统设置里先关掉会打断的东西：**自动系统更新、自动亮度、屏幕自动旋转、勿扰/通知横幅、
  自动锁屏（超时设为"永不"）**、音量键锁定到合适档。
- 连展位网络（优先自带 4G/5G 热点，别用展馆公共 WiFi——现场拥堵是合成 network error 的主因）。
- 应用商店安装 **Fully Kiosk Browser**（免费版够用；Plus 一次性解锁更强锁定，单台几欧元，展会值得）。

## 三、Fully Kiosk 逐项配置

打开 Fully Kiosk → 右上角设置（或从边缘划出菜单）。按域逐项设：

**Web Content Settings**
- Start URL：`https://leshine.work/expo/kiosk`
- Enable JavaScript / Cookies / DOM Storage(localStorage)：全开（登录态与流程都依赖它）

**Web Zoom and Scaling / Web Overscroll**
- Disable Pull to Refresh：开（防客户下拉刷新把流程刷没）
- Pinch to Zoom：关（防误缩放）

**Kiosk Mode（Plus）**
- Enable Kiosk Mode：开
- Disable Status Bar / Navigation Bar（沉浸式全屏，藏掉顶栏与三大金刚键）：开
- Disable Home/Recents/Back（禁系统退出手势）：开
- Kiosk Exit Gesture + PIN：设一个退出 PIN（工作人员长按角落 N 下 + PIN 才能退出配置）

**Device Management**
- Keep Screen On：开（别让屏幕休眠）
- Screen Orientation：锁成展位实际方向（竖屏/横屏）
- Screen Brightness：调到展厅够亮的固定值，关自动亮度

**Advanced Web Settings**
- Disable Context Menu / Text Selection / Long Press：开（防长按弹出菜单/选中文本）
- Disable File Downloads：开
- Error URL / Retry：设为 Start URL，加载失败自动回首页

**Power Settings**
- Start on Boot：开（开机/断电重来后自动进 kiosk）
- Restart App on Crash / Reload on Crash：开（崩溃自恢复）

**Web Automation（关键：防全天掉登录 + 客户间自动回首页）**
- Reload on Screensaver Stop / Load Start URL on Screen On：开
- Auto Reload on Idle：设 **每 1~2 小时**（或每晚一次）——重载会触发前端用 refresh cookie
  换新的 access token，令 12 小时 access token 全天不过期、7 天内跨天免重登
- Screensaver / Motion Detection（可选）：无人时显示品牌待机图，有人靠近唤醒回首页

**锁定 / 多应用白名单（关键：既锁死又能切去打印）**

展位流程里工作人员中途要切到打印 App 打照片，所以不能用"单应用锁死"，要用
**多应用白名单锁定**：客户跑不出去，但白名单里的打印 App 允许切换，打完回 kiosk。

- 硬锁（推荐，最强）：用 ADB 把 Fully 设为设备所有者，开 Android Lock Task 真锁定：
  `adb shell dpm set-device-owner de.ozerov.fully/.MainDeviceAdmin`（平板需未加任何账号时执行）。
  然后在 Fully → Kiosk Mode → **Allowed Apps in Kiosk Mode / Whitelisted Apps** 里把
  **打印 App 的包名**加进去（如手机厂商相纸打印机自带 App）。Lock Task 会把 Fully + 打印 App
  两个包一起放进白名单，其余一律锁死。
- 软锁（不动 ADB）：把 **Fully 设为默认主屏/Home 应用**（系统设置→默认应用→主屏幕→Fully）。
  这样按 Home 键永远回到 kiosk。工作人员从 Fully 的一个隐藏入口（下方）打开打印 App，
  打完按 Home 回 kiosk。客户不知道入口、按 Home 也只回 kiosk。
- **工作人员怎么切到打印 App（对客户隐藏）**：任选其一——
  ① Fully 边缘划出菜单 → 需 PIN → 里面放一个打开打印 App 的书签/Intent；
  ② 用 Fully 的 "Universal Launcher"（Plus）配一个受 PIN 保护的应用抽屉，只列打印 App；
  ③ 若走 Intent，用 Fully 的 URL 方案 `intent://` 或 `startother` 指向打印 App 包名。
- **打完怎么回**：Fully 设为默认 Home → 打印 App 里按 Home 键即回 kiosk；
  或 Fully 开 "Bring to Foreground on Screen On / after idle"，离开一会儿自动被拉回前台。

> 更顺的替代（无需切 App，见正文末「附：页内直接打印」）：把"打印"做进 kiosk 页面本身，
> 尤其打印机若接在展位那台本地后端机器上，可做到一键直打、零切换——需要时找我做。

## 四、登录一次，锁定收工

1. 在 Fully 里打开 Start URL → 自动跳登录页 → 用第一步的 `expo-booth` 账号登录一次。
2. 登录成功进入 kiosk 首页后，token 与 refresh cookie 已存在 Fully 的浏览器存储里。
3. 回 Fully 设置开启 Kiosk Mode / 屏幕固定 / Lock Task。完成。

## 五、掉登录说明（心里有数）

- access token 12 小时、refresh token 7 天。**单个展位日不会掉**（营业时长 < 12h）。
- 靠上面「Auto Reload on Idle / 每晚重载」跨天续期，**≤7 天的展会全程免重登**。
- 展会超过 7 天：中途在平板上重登一次即可（或提前找我把设备账号的 refresh 时效单独放长）。
- 若现场看到跳回登录页：多半是超时未重载或网络断。手动重登一次，并确认 Auto Reload 已开。

## 六、现场每日开场 checklist

- [ ] 平板电源接好、亮度够、方向对、音量合适
- [ ] 网络已连（优先热点），随手开一次试戴走通"拍照→合成出图"
- [ ] 页面停在首页待机（非某个客户的结果页——隐私）
- [ ] Kiosk 锁定生效：试划返回/Home 出不去
- [ ] 相机权限已授予 Fully（合成要调前置摄像头）

## 七、安全红线

- 平板只登「展会设备」账号（仅 expo:write），绝不登管理员号。
- 平板丢失/被拿走：后台**停用该账号**（角色/用户管理），该设备立即失效，客户数据不受影响。
- 客户共享屏红线仍在：结果页不自动清场靠工作人员返回首页；internal 发况/话术不上客户屏（已在代码层保证）。

---

## 附：页内直接打印（可选，最"一体性"，需开发）

切去打印 App 再切回来始终有割裂感。三条把打印做进流程本身、减少/免去切换的路子，
按顺滑度排序：

1. **本地后端机直连打印机（最顺，零切换）**：展位后端就跑在本地那台 Windows 机器上
   （云 Nginx → frp → 本地 8002）。把相纸打印机接在这台机器上，加一个"打印"端点
   （拿 result 图 → 走 Windows 打印驱动出图）。kiosk 结果页加个「打印这张」按钮，点一下
   本地机直接吐照片，客户屏和打印全在一个流程里，完全不切 App。**推荐做法**。
2. **系统打印/分享 Intent**：结果页「打印」按钮触发 Android 打印框（Mopria/厂商打印服务）
   或"分享到打印 App"。少一次手动找图，但仍会弹系统 UI，锁定下体验一般。
3. **维持切 App**：即上文白名单方案，最省事、当天能上，但有切换割裂。

要做第 1 条，我需要知道：打印机型号 + 它是否已（或能）接到展位那台本地后端机器、
走 USB 还是网络。告诉我我就把打印端点 + 结果页按钮加上。
