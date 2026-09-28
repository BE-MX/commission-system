# 方舟 Windows 更新中心

`ArkDeploy.exe` 在操作者的 Windows 电脑运行，通过已配置的 SSH 连接办公室，由办公室原有 `deploy/deploy.bat` 完成全环境发布。界面使用 Windows 原生窗体，无需在操作者电脑安装 Python、Node 或浏览器运行时。需要 Windows .NET Framework 4.5+ 与 OpenSSH 客户端（或 Git for Windows）。不新增公网管理端口，不在客户端保存服务器密码、数据库凭据或私钥副本。

## 使用

1. 解压构建包，双击 `ArkDeploy.exe`。可先运行 `ArkDeploy.exe --demo` 查看明确标记为演示的数据。
2. 已按已验证的连接预填 `acciowork@127.0.0.1`、端口 `2233`（转发至办公室 22），私钥默认当前 Windows 用户的 `.ssh/ark_office`。也可填写已配置的 SSH 别名；别名有端口配置时清空端口框以沿用配置。**服务器上**的安装目录默认 `D:/commission-system`。私钥文件路径可选填，留空沿用 SSH 配置、密钥/agent。只引用本机私钥，不复制或上传私钥；加密私钥需提前加入 SSH agent。沿用已人工核验的 known_hosts；连接中的主机密钥和身份认证错误必须处理，不自动放宽校验。
3. 点击「只读自检」：逐项显示办公室服务及数据库、发布锁/恢复记录、工具、北京服务与数据库、两站及 PM/素材 HTTPS、关联服务真实状态。绿色只表示该检查通过；未知/未纳管服务不会假报启动。
4. 点击「准备候选版本」：通过正常部署入口 fetch、候选构建、依赖/schema 检查、增量上传和候选验证；会写服务器候选目录和云端 staging，但不切换生产服务、不执行迁移。准备完成后查看固定 SHA、办公室源码文件差异、待执行迁移、云端 changed files/transfer bytes 日志。
5. 点击「确认并更新」并确认具体版本及范围。同一准备记录只提供固定 SHA，实际执行 `deploy.bat --no-pull --revision <SHA>`；办公室重新自检，原入口重新核验，按原规则迁移和切换。准备失败不能继续，连接配置变化会使准备结果失效。
6. 观察更新进度。每一行是部署器真实的开始/完成/失败事件，按主站、PM、办公室、北京、色块、出库服务区分。完成数是步骤计数，不是假定时间百分比。发布结束自动再次自检；部署回执成功但服务检查失败会显示异常。
7. 报错查看「错误诊断」与「运行日志」，可导出文本报告。诊断区分已确认失败步骤、日志线索、尚不能确定的原因。程序不自动修复迁移、删除锁、启动旧代码或循环重试。

## 首次接入要求

- 操作者电脑的 `ssh -p 2233 -o BatchMode=yes -o StrictHostKeyChecking=yes <用户名>@127.0.0.1`（或已配置别名）能连接正确的办公室账号；隧道、密钥和主机指纹由 SSH 运维配置管理。端口映射只提供网络通路，不替代账号认证；办公室可运行 `whoami` 确认登录账号，不要在聊天中发送密码或私钥。
- 办公室需要已有 Git、Node/npm、NSSM、后端 `.venv`、云端 SSH 授权和原部署权限。SSH 账号必须具备与原 deploy 相同的服务控制权限；不在程序里自动提权。
- **服务器安装目录的 `deploy/publish.py` 必须包含此次进度事件改动，且有 `deploy/desktop_events.py`。** 必须按项目正常 Git 集成/服务器安装流程更新部署器后使用；客户端不会覆盖受管理源码或把自己的开发代码上传生产。缺少协议会在只读自检阶段明确阻断。
- 无需先安装桌面常驻服务。首次发起任务时仅将两个辅助 Python 文件写入服务器 `.deploy_state/desktop/tools/<sha256>/` 并启动独立后台进程；实际发布始终调用原 `deploy.bat`，使用原锁、迁移保护和恢复流程。

## 断线、退出与证据

服务器任务以 `DETACHED_PROCESS + CREATE_BREAKAWAY_FROM_JOB` 脱离 SSH 查询进程运行；服务器策略不允许 breakaway 时拒绝启动，不降级到可能随断线终止的模式。正常关闭客户端后可重新打开点击「恢复任务」读取原 run id，客户端未保存编号时读取服务器最新任务。整机重启、后台进程异常或回执缺失标为「待核实」，保留锁；不能根据窗口关闭或旧 `publish-success.json` 判断成功。实际 SSH 断线保活仍需在目标办公室环境做无害任务接入验证。

服务器 `.deploy_state/desktop/runs/<run-id>/` 保存 `operation.json`、`events.jsonl`、脱敏 `output.log`、`worker.log` 及激活前复核。`active.lock` 避免多个桌面客户端并发；原 `publish.lock` 仍是实际发布互斥。重复提交同一 run id 只返回原任务，不重新发布。未知状态保留锁，按原部署恢复说明人工检查进程、数据库和 writer 状态后处理。

客户端只在 `%LOCALAPPDATA%/LeShine/DeployConsole/session.json` 保存主机、端口、私钥路径、安装目录与任务编号，不保存私钥内容。没有自动删除历史记录/制品，不清理服务器业务数据。报告包括文件名、环境状态和脱敏日志，完整运行证据留在办公室；无密码输入框。

自检的公网 HTTP 200 仅证明网页/证书可达；后端通过本机 `/health` 校验数据库。部署器自身另行校验版本、静态摘要、出库摘要与调度基线。自检不冒充登录态业务验收，未纳管服务、平板 APK、小程序审核发布不计入应用更新。

PM2 按服务器清单中同一主机已登记的 root 执行路径检查正 PID；SSH 用户为 ubuntu 时使用现有部署规则的 `sudo -n -H -u root` 和固定 `HOME/PM2_HOME/PATH`，不查询或导出服务环境变量。已登记 root systemd 用户服务查询其用户总线状态。停止、缺失或无探针的独立服务不计作通过，不自动启动。

## 构建与隔离验收

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File deploy/desktop/build.ps1
.deploy_state/desktop-package/ArkDeploy.exe --demo
.deploy_state/desktop-package/ArkDeploy.exe --self-test .deploy_state/desktop-self-test.txt
python -m pytest deploy/tests/test_desktop_console.py deploy/tests/test_pipeline_contract.py -q
```

构建读取项目 `frontend/src/styles/tokens.css` 的颜色令牌并嵌入 EXE；C# 源码无需外部 NuGet 包。输出在 `.deploy_state/desktop-package/`。`--demo`、`--self-test`、`--screenshot <png>` 均不连接生产、不执行更新。测试使用临时仓库、模拟进程及本机无害假部署器。真实服务切换和网络中断演练需在授权维护窗口进行。
