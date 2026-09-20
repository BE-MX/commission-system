# 办公室内网 HTTPS 换址

当前入口为 `https://lan.leshine.cloud`，办公室地址为 `192.168.100.3/23`。公共 DNS 与办公室网关 DNS 都须将该域名解析为新地址；仅修改公共 DNS 不会覆盖网关的本地记录。

在办公室服务器通过统一入口执行：

```bat
deploy\deploy.bat --office-lan-https PLAN_JSON --prepare-only
deploy\deploy.bat --office-lan-https PLAN_JSON
```

计划示例（放受限 `.deploy_state`，不含密钥）：

```json
{
  "live_root": "D:/commission-system",
  "address": "192.168.100.3",
  "previous_address": "192.168.101.193",
  "subnet": "192.168.100.0/23",
  "backend_port": 8001
}
```

`previous_address` 仅用于已有受管安装换址。预检验证服务归属、原配置、原防火墙、证书与新网卡地址；正式执行先备份 Caddyfile 与安装记录，再更新 HTTPS 监听及防火墙本地地址，仅重启 ArkOfficeHttps。后端仍代理至 `127.0.0.1:8001`，不发布应用或执行数据库迁移。

通过真实 SNI、系统 CA、线上证书一致性、健康接口及扫码页面检查后，才原子更新安装记录。异常时恢复旧配置和防火墙；旧 IP 已从网卡移除时，恢复配置不保证旧地址可访问。备份保留在受限目录 `readdress-backup-*`，重复执行将核验新配置。

验收还须从办公室系统默认解析访问 `/health`、`/shipping/scan`、`/pm/`，不能只测指定 IP。PM 前端上传提示共用 `frontend-pm/src/utils/uploadLimit.js` 中的内网地址，改动需随 PM 前端发布。HTTPS 换址成功不等于 COS 存储迁移或真实手机上传已完成。
