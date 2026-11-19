# 北京内贸订单进度码微信配置修复（2026-10-17）

北京后端缺少 `WX_MINI_APPID`、`WX_MINI_SECRET`，内贸订单进度码接口在请求微信之前即报配置缺失。办公室生产配置含这两项。用户确认仅同步微信配置并重载北京后端，不整份覆盖 `.env`。

## 实际变更

- 北京 `/home/ubuntu/commission-system/backend/.env` 仅补充 `WX_MINI_APPID`、`WX_MINI_SECRET` 和显式 `WX_MINI_ENV_VERSION=release`。其余解析后的配置逐项一致，文件权限与属主保留。
- 办公室 SSH 后续出现握手超时；使用本机已有副本，两项凭据分别与本次此前从办公室生产配置读取的 SHA256 指纹严格匹配，正式版模式也与办公室已核对值一致。密钥仅通过 SSH 子进程管道传输，未写入本机修复脚本、Git 或日志。
- 原北京完整配置留在该服务器 `.deploy_state/wx-mini-config-repair-20261017/before.env`，目录权限 0700、备份 0600；回执同目录 `receipt.json`。不得将此备份复制进仓库或输出内容。
- 取得既有 `backend.lock` 后，通过 systemd 重启 `ark-backend`。进程由 1234240 变为 1723725；没有发布源码、执行迁移或修改办公室配置。北京源码保持 `1eef7a2e7472588553ed8f7fb011105b9a7b3d32`。

## 验证证据

- 写入前后文件 SHA256 分别为 `e8c429468a1d008d891e903166934780e505c144bbda28e2c9bd70c9996a353b`、`9394fd67c81d0136d36834e6ad0ac2c795359374cda421db4d066e74f6b64342`，原子替换后逐字节回读一致。
- 重载后 Settings 与已核对办公室来源一致。北京 `SCHEDULER_ENABLED=false`、`WHATSAPP_AUTO_SYNC_ENABLED=false`、门户写入/发票/邮件/通知/自动出库开关均保持原值。
- 北京回环及 `https://leshine.cloud/health` 均返回 `status=ok`、`database=connected`。
- 使用只读数据库事务选择生产中且未删除订单的明细 536，沿现有签名和微信客户端生成正式版进度码，微信返回 `image/jpeg`，102242 字节，SHA256 为 `4568885f23681e1d32576b56e1cbc10dc0fb5cd9ee78109cf2def78888c75359`。未修改订单，也未输出签名 scene 或图片中的客户访问凭据。
- 此结果证明服务器实际微信取码成功；尚未进行浏览器打印、实物标签输出或手机扫码验收。

本机非敏感操作脚本与回执位于 `.deploy_state/wx-mini-config-repair-20261017/`。预检期间的脚本语法、跨平台编码及配置验证问题均在生产写入前修正；失败后复核原配置摘要与进程未变，配置实际写入一次、服务实际重载一次。

恢复时先核对当前文件仍匹配修复后 SHA256 与保存回执，再只恢复上述微信三项原值/原存在性，保留其他配置；随后受管重载并复核健康。本轮未执行回退。
