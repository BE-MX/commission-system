# 办公室内存异常与系统不可用核验（2026-10-19）

已查明主要占用进程为本轮部署状态查询遗留的powershell.exe（PID10432）。通过解码启动参数的SHA256与本地查询脚本逐字一致进行归属核验；仅终止该已确认的无子进程只读查询，核验PID和创建时间，未重启或停止业务服务。

- 09:44:51启动，观察到实际工作集从14.1GiB增长到结束前21.9GiB，私有提交内存约32.0GiB。
- 结束后首次可用内存22.7GiB，最终复核22.87GiB；目标进程不存在。最高其他进程工作集不足0.5GiB，后端健康正常。
- 内网8001、lan.leshine.cloud、leshine.work、leshine.cloud的/health均200，数据库connected。用户恢复维护连接时，业务服务已重新启动；本任务没有执行服务重启。
- 原Windows PowerShell5.1查询将Get-Content日志对象传入ConvertTo-Json -Depth12；实测对象携带PSDrive/PSProvider等扩展元数据，而输入文件均仅1KB至114KB，高度指向深度序列化膨胀。未在生产重放危险序列化。已将本机旧查询入口替换为有限Python读回，原脚本保存为.disabled证据，新入口实际执行成功。
- 年度战报当前status=published、version=5、push=False；未自动重发发布、未修改业务数据。事故日志提取材料已脱敏。

证据：office-memory.json、powershell-attribution.json、powershell-cleanup-intent.json、powershell-cleanup-receipt.json、serialization-evidence.json、memory-final.json、health-after-memory-cleanup.json。
