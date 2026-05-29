# jimureport 数据库初始化

> 在腾讯云 MySQL 上首次部署 jimureport 服务前必跑。建库 `jimureport` + 灌 24 张核心表。

## 用法

```bash
cd jmreport-service

# 1. 拉 v2.3.4 的全量 dump（9MB；不入仓库，避免冲胀）
curl -fsSL -o sql/jimureport-init.sql \
  "https://raw.githubusercontent.com/jeecgboot/jimureport/v2.3.4/db/jimureport.mysql5.7.create.sql"

# 2. 切出核心 24 张表（jimu_* + onl_drag_*），丢弃 huiyuan_/rep_demo_/test_/tmp_ 演示数据
python sql/filter_init.py

# 3. 导入腾讯云（凭证从 backend/.env 自动读取）
python sql/import.py
# 期望: executed 158 statements, 0 errors，24 张表
```

## 为什么不直接全量导入

jimureport 官方 dump 里夹带 28 张演示业务表（会员系统/销售/简历），导进生产实例会污染数据库；core 版本只保留设计器自身需要的字典 / 报表元数据 / 仪表盘元数据。

## 文件

- `filter_init.py` — 切核心脚本（接受 `jimureport-init.sql`，吐 `jimureport-core.sql`）
- `import.py` — 导入脚本（pymysql + 自动从 backend/.env 读 host/port/user/pass）
- `jimureport-init.sql` — 不入仓库（运行时下载）
- `jimureport-core.sql` — 不入仓库（filter_init.py 现场生成）
