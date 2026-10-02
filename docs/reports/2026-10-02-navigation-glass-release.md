# 顶栏与标签栏毛玻璃发布记录

## 已完成

- 应用版本 `1c6130853beda46b20390276c8e9bc323f906fc3` 已合入 main 并推送 origin；基于已合并的 `398a8e62` 整合本次 UI，不夹带主目录未提交内容。
- 办公室统一 `deploy/deploy.bat --revision 1c6130853beda46b20390276c8e9bc323f906fc3` 先 prepare-only 再正式发布，两个阶段退出 0。
- `release_id=5edd819e00754ae2964d00781b51389c`，范围 `office-and-cloud`，状态 `succeeded`，`deferred=[]`。
- 数据库 `173_task_center`，无新增迁移；出库发布状态 `verified`，调度状态 `{"active": true, "enabled": true}`。
- 办公室服务及两地主站 health 均 `ok/connected`。额外 50 次 HTTPS 检查核对入口、导航、主脚本 / 样式及涉及页面制品，与候选 SHA256 一致；公网 MainLayout CSS 包含真实 backdrop-filter 与导航高度滚动避让，导航玻璃令牌透明度已验证。
- 原有 22 个未提交文件的内容已完整保留；工作树合并与发布记录整合使用字节备份和 SHA256 核验。其他代理成果保留。

## 功能与验证

顶栏与标签栏共用 16px 真实背景模糊，正文从玻璃后方滚过，保留品牌金、移动导航及标签交互；根滚动吸顶 / 滚动定位 / fullscreen 边界已避让。10 项导航测试、浏览器桌面 / 390px / 320px、弹层与焦点、减少透明 / 动态、单滤镜与实际像素变化、独立滚动契约审查通过。主站构建、覆盖提交差异的约定检查与 diff 检查通过。

范围内生产目标以本轮发布回执为准；单独登记的未纳管服务、尚未开通的 PM 云域名及源库外 hair / video 不计作本次已更新目标。

## 证据

- [毛玻璃设计与验收截图](2026-10-02-navigation-glass.md)
- 本机 `.deploy_state/navigation-glass-release/`：prepare / deploy 日志、server-verification.json、public-verification.json、合并前字节备份、合并结果、浏览器与构建证据。
