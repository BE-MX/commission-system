# Kindle 方舟看板

Paperwhite 3（5.15.1.1）的 KOReader / Tinta 客户端，显示方舟个人待办、备忘和消息，并区分设备持久接收与用户明确已读。约每 5 分钟预约同步；网络、定时唤醒与电池耗电仍需实际环境验收。首期提醒在 Tinta 模式中生效，原生 Kindle 阅读界面没有全局消息弹窗。

设备端 0.1.1 已在 PW3 启动，用户确认中文和排版正常。修复 Tinta 与 KOReader 字号重复缩放，覆盖 562 条简体中文文本。方舟生产发布与真实账号绑定尚未执行。会员用量不在本期范围。

## 组成

- `client/ark_board/`：待办、备忘、消息及配置导入；固定校验证书链和域名。
- `client/locales/zh/`：Tinta 核心、设置和内置应用的中文文本。
- `client/launchers/KOReader.sh`：HDNEXT Scriptlet 离线启动入口，可复制到 Kindle `documents/`。
- `scripts/prepare_runtime.py`：对固定上游副本应用提交后回调、持久存储检查、撤回弹窗、联网唤醒与字号修复。
- [安装说明](docs/INSTALL-PW3.md)；[方舟接口与权限契约](../../docs/requirements/2026-10-25-kindle-dashboard.md)。

## 准备依赖与构建

在本目录创建 Python 虚拟环境，安装 `requirements-dev.txt`。下载依赖放在 `.deps/`，不要提交：

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
git clone https://github.com/henriquefps/tinta-koreader .deps/tinta
git -C .deps/tinta checkout 9c70aa08132ccb7a12d4eb1bf639809fa8740d74
.venv\Scripts\python.exe scripts/build_package.py
```

构建输出 `dist/ark-board-pw3-0.1.1.zip` 与 SHA256；ZIP 包含 Lua 源码、来源、许可证和逐文件校验清单。KOReader 与越狱工具从各自官方来源安装，不包含在看板包中。

## 验证

字体与宿主测试读取实际 KOReader 发布源码：将官方 `koreader-kindlepw2-v2026.07.1.zip` 解压到 `.deps/install-stage-pw3/`。官方包 SHA256 为 `ea1f575c54492a2c679d128b7f3210fd7d6a87e5f5a1ff1f7a7fe2080ff68f86`。

```powershell
.venv\Scripts\python.exe scripts/test_client.py
.venv\Scripts\python.exe scripts/test_font_scaling.py
.venv\Scripts\python.exe scripts/test_localization.py
.venv\Scripts\python.exe scripts/test_runtime.py
.venv\Scripts\python.exe scripts/test_runtime.py --scenario
$env:SMOKE_SCREEN = '1072x1448'
.venv\Scripts\python.exe scripts/test_runtime.py --chinese-ui
```

以上通过客户端 47 项、传输 15 项、字号与行框 780 项、562 条翻译检查、方舟宿主 33 项、事务场景 18 项和中文竖屏 117 项；中文横屏 `1448x1072` 为 113 项。字体测试加载真实 KOReader 字体接口，但原生 FreeType 和绘制使用桩，不等同真机像素测试。额外的上游全流程测试在 Windows 存在电池 CSV 同秒去重的已确认基线失败，未将其算作通过。

服务端测试位于根目录 `backend/tests/test_inkboard*.py`，使用隔离 SQLite；跨语言联调用 `scripts/integration_smoke.py --ark-backend <repo>/backend`。浏览器检查使用本地 Vue 页面和合成 HTTP 数据；不连接生产账号。

不要上传 `ark-board.local.json`、Tinta 数据库、设备日志或书籍。配套 Tinta 含必要接口适配，直接自动更新为未经适配的上游版本会失去这些接口。退出 Tinta：菜单 → 系统设置 → 第二页 → 返回 KOReader。
