"""PM Hub 项目资料协作站领域模块（设计稿 docs/requirements/2026-07-17-pm-material-hub.md）。

独立于平台 RBAC：入口是白名单用户名换 HMAC token（auth.py），所有端点走
require_pm_member（验签 + 每请求回查白名单）。文件存 backend/data/pm/，
绝不放 uploads 公开静态目录；下载/预览一律短时效签名 URL。
"""
