# PDA 实体键广播扫码修复设计

## 目标

用户在内贸报工 APP 前台登录后，只需按 PDA 实体扫描键并对准二维码，APP 即自动接收二维码内容并进入现有校验、确认和报工流程。APP 不提供屏幕扫描按钮，也不主动发送扫描头出光广播。

## 厂家协议

- PDA 扫描设置使用“广播输出”。
- 广播动作：`android.intent.ACTION_DECODE_DATA`。
- 二维码字段：`barcode_string`。
- 厂家提供的 `com.rskj.android.F6_KEY_DOWN` 仅用于软件主动触发扫描头，本需求不使用。

## 实现方案

1. 厂家 action 由 AndroidManifest 中的专用导出 Receiver 接收，覆盖老 PDA 扫描服务只向清单接收器投递的情况。
2. 厂家 Receiver 的过滤器保留 `CATEGORY_DEFAULT`。Android 只要求 Intent 自带的 category 必须存在于 filter，因此它同时匹配带 category 和不带 category 的厂家广播。
3. 厂家 Receiver 通过进程内 Bridge 把结果交给前台 `ScannerInput`；内贸报工页停止后立即解绑，不在后台处理报工。
4. 其他厂家协议继续使用现有动态 Receiver，并保留 `CATEGORY_DEFAULT` 兼容性。
5. 收到厂家 action 后优先读取 `barcode_string`；只读取已知字段并捕获 Bundle 反序列化异常，避免导出 Receiver 被异常 extra 触发崩溃。
6. 成功取得内容后直接进入现有 `handleRawScan` 流程，不改变二维码格式、后端 API、数量确认、幂等提交或撤销逻辑。
7. 收到厂家广播但未取得有效内容时，不再静默失败；页面显示可执行提示，区分“已收到广播但没有二维码内容”和后端校验失败。
8. 页面扫描状态文案明确为“按 PDA 实体扫描键”，现有展示块保持非交互，不增加点击处理，也不发送 `F6_KEY_DOWN`。

## 测试与验收

- 先写厂家广播契约的失败测试，覆盖 Manifest/动态 action 分流、`CATEGORY_DEFAULT` 兼容、Bridge 前台生命周期、`barcode_string` 字符串、字节数组和空内容。
- 修改后运行 PDA 模块全部单元测试，并构建 Debug APK。
- 校验 APK 包名、版本、签名和 SHA-256。
- 真机验收：打开内贸报工页，按实体扫描键扫描 `ARK-D` 或 `ARK-DU`，页面立即显示已读取内容并进入原有报工流程；点击页面扫描状态区不会触发扫描头。

## 不在范围内

- 不支持屏幕按钮主动触发扫描头。
- 不修改 PDA 厂家扫描设置。
- 不修改后端报工接口或数据。
- 不处理输入法、物理键盘输出模式。
