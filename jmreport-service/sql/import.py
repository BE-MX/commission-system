"""
初始化 jimureport_db：从方舟 backend/.env 读取腾讯云 MySQL 凭证，
建库 + 灌核心表 DDL/INSERT。

只在开发机一次性运行；服务器部署时由 deploy/setup-jmreport.bat 之前手工跑一次：
    cd jmreport-service
    curl -fsSL -o sql/jimureport-init.sql \
      https://raw.githubusercontent.com/jeecgboot/jimureport/v2.3.4/db/jimureport.mysql5.7.create.sql
    python sql/filter_init.py
    python sql/import.py
"""
import os
import re
import sys
from pathlib import Path

import pymysql

ROOT = Path(__file__).resolve().parents[2]      # commission-system/
ENV = ROOT / "backend" / ".env"
SQL = Path(__file__).resolve().parent / "jimureport-core.sql"
DB_NAME = "jimureport"


def load_env(path: Path) -> dict:
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def main() -> None:
    if not ENV.exists():
        raise SystemExit(f"missing {ENV} — 方舟 backend/.env 必须存在")
    if not SQL.exists():
        raise SystemExit(f"missing {SQL} — 先跑 python sql/filter_init.py")

    env = load_env(ENV)
    host = env["COMMISSION_DB_HOST"]
    port = int(env["COMMISSION_DB_PORT"])
    user = env["COMMISSION_DB_USER"]
    pwd = env["COMMISSION_DB_PASSWORD"]

    print(f"connecting to {user}@{host}:{port} ...")
    conn = pymysql.connect(
        host=host, port=port, user=user, password=pwd,
        charset="utf8mb4", autocommit=True, local_infile=False,
        connect_timeout=15,
    )
    cur = conn.cursor()

    cur.execute(
        f"CREATE DATABASE IF NOT EXISTS `{DB_NAME}` "
        "DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
    )
    print(f"db {DB_NAME} ready")
    cur.execute(f"USE `{DB_NAME}`")

    print(f"executing {SQL} ({SQL.stat().st_size} bytes) ...")
    content = SQL.read_text(encoding="utf-8", errors="replace")

    # mysqldump 一行一句，分号结尾。跳掉 USE / CREATE DATABASE / lock-tables。
    buf, sql_count, err_count = [], 0, 0
    for raw_line in content.splitlines():
        stripped = raw_line.strip()
        if re.match(r"^\s*(USE|CREATE\s+DATABASE|LOCK\s+TABLES|UNLOCK\s+TABLES)", stripped, re.I):
            continue
        buf.append(raw_line)
        if stripped.endswith(";"):
            stmt = "\n".join(buf).strip()
            buf.clear()
            if not stmt or stmt.startswith("--"):
                continue
            try:
                cur.execute(stmt)
                sql_count += 1
            except Exception as exc:
                err_count += 1
                head = stmt[:120].replace("\n", " ")
                print(f"  ERR: {exc} | stmt: {head}", file=sys.stderr)
                if err_count > 10:
                    print("too many errors, abort", file=sys.stderr)
                    break

    print(f"executed {sql_count} statements, {err_count} errors")

    cur.execute(f"USE `{DB_NAME}`")
    cur.execute("SHOW TABLES")
    tables = sorted(t[0] for t in cur.fetchall())
    print(f"tables now in {DB_NAME}: {len(tables)}")
    for t in tables:
        print("  ", t)

    cur.close()
    conn.close()
    print("done")


if __name__ == "__main__":
    main()
