# -*- coding: utf-8 -*-
"""leShine 展会样品销售 · 库存同步服务

单文件 FastAPI + SQLite：
- 库存查询、下单原子扣减（多人同时下单不超卖）
- 订单列表 / 撤销（恢复库存）/ 清空
- 库存重置
- 价格以服务端 items.json 为准，客户端只传 id 和数量

运行：uvicorn server:app --host 0.0.0.0 --port 8010
页面：GET / 自动返回上级目录中的 html 文件
"""
import datetime
import glob
import json
import os
import sqlite3
import threading

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "expo.db")
STOCK_VER = 3  # 初始库存调整时 +1，启动时自动重播种（保留订单）

with open(os.path.join(BASE, "items.json"), encoding="utf-8") as f:
    ITEMS = json.load(f)
BY_ID = {it["id"]: it for it in ITEMS}

app = FastAPI(title="展会样品销售库存服务")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_lock = threading.Lock()  # 串行化写操作，配合 BEGIN IMMEDIATE 保证不超卖
BEIJING_TZ = datetime.timezone(datetime.timedelta(hours=8))


def beijing_now():
    return datetime.datetime.now(BEIJING_TZ).replace(tzinfo=None)


def db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = db()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS stock(item_id INTEGER PRIMARY KEY, qty INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS orders(
      no TEXT PRIMARY KEY, time TEXT NOT NULL, cust TEXT NOT NULL,
      lines TEXT NOT NULL, total_cents INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'done');
    CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
    """)
    conn.execute("INSERT OR IGNORE INTO meta(k,v) VALUES('seq','1')")
    ver = conn.execute("SELECT v FROM meta WHERE k='stock_ver'").fetchone()
    if not ver or int(ver["v"]) != STOCK_VER:
        conn.execute("DELETE FROM stock")
        conn.executemany("INSERT INTO stock(item_id, qty) VALUES(?,?)",
                         [(it["id"], it["n"]) for it in ITEMS])
        conn.execute("INSERT OR REPLACE INTO meta(k,v) VALUES('stock_ver',?)", (str(STOCK_VER),))
        conn.commit()
    conn.close()


init_db()


def stock_map(conn):
    return {r["item_id"]: r["qty"] for r in conn.execute("SELECT item_id, qty FROM stock")}


def row_to_order(r):
    return {"no": r["no"], "time": r["time"], "cust": r["cust"],
            "lines": json.loads(r["lines"]), "total": r["total_cents"], "status": r["status"]}


class LineIn(BaseModel):
    id: int
    qty: int


class OrderIn(BaseModel):
    cust: str
    lines: list[LineIn]


@app.get("/api/state")
def get_state():
    conn = db()
    stock = stock_map(conn)
    conn.close()
    return {"stock": stock, "ver": STOCK_VER}


@app.get("/api/orders")
def get_orders():
    conn = db()
    rows = conn.execute("SELECT * FROM orders ORDER BY time DESC, no DESC").fetchall()
    conn.close()
    return {"orders": [row_to_order(r) for r in rows]}


@app.post("/api/orders", status_code=201)
def create_order(o: OrderIn):
    cust = o.cust.strip()
    if not cust:
        raise HTTPException(400, "客户名称不能为空")
    merged = {}
    for l in o.lines:
        if l.id not in BY_ID:
            raise HTTPException(400, "商品不存在")
        if l.qty <= 0:
            raise HTTPException(400, "数量必须大于 0")
        merged[l.id] = merged.get(l.id, 0) + l.qty
    if not merged:
        raise HTTPException(400, "订单不能为空")

    with _lock:
        conn = db()
        try:
            conn.execute("BEGIN IMMEDIATE")
            stock = stock_map(conn)
            for _id, q in merged.items():
                if q > stock.get(_id, 0):
                    it = BY_ID[_id]
                    raise HTTPException(409, "「%s」库存不足，仅剩 %d %s" % (it["p"], stock.get(_id, 0), it["u"]))
            lines = []
            total = 0
            for _id, q in merged.items():
                it = BY_ID[_id]
                uc = round(it["pr"] * 100)
                lines.append({"id": _id, "p": it["p"], "g": it["g"], "s": it["s"], "z": it["z"],
                              "c": it["c"], "u": it["u"], "qty": q, "unitCents": uc})
                total += uc * q
                conn.execute("UPDATE stock SET qty = qty - ? WHERE item_id = ?", (q, _id))
            seq = int(conn.execute("SELECT v FROM meta WHERE k='seq'").fetchone()["v"])
            no = "GZ" + str(seq).zfill(4)
            now = beijing_now().isoformat(timespec="seconds")
            conn.execute("UPDATE meta SET v=? WHERE k='seq'", (str(seq + 1),))
            conn.execute("INSERT INTO orders VALUES(?,?,?,?,?,'done')",
                         (no, now, cust, json.dumps(lines, ensure_ascii=False), total))
            conn.commit()
            order = {"no": no, "time": now, "cust": cust, "lines": lines,
                     "total": total, "status": "done"}
            return {"order": order, "stock": stock_map(conn)}
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


@app.post("/api/orders/{no}/cancel")
def cancel_order(no: str):
    with _lock:
        conn = db()
        try:
            conn.execute("BEGIN IMMEDIATE")
            r = conn.execute("SELECT * FROM orders WHERE no=?", (no,)).fetchone()
            if not r:
                raise HTTPException(404, "订单不存在")
            if r["status"] != "done":
                raise HTTPException(409, "订单已撤销")
            for l in json.loads(r["lines"]):
                if l["id"] in BY_ID:
                    conn.execute("UPDATE stock SET qty = qty + ? WHERE item_id = ?", (l["qty"], l["id"]))
            conn.execute("UPDATE orders SET status='cancelled' WHERE no=?", (no,))
            conn.commit()
            return {"ok": True, "stock": stock_map(conn)}
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


@app.post("/api/orders/clear")
def clear_orders():
    with _lock:
        conn = db()
        conn.execute("DELETE FROM orders")
        conn.execute("UPDATE meta SET v='1' WHERE k='seq'")
        conn.commit()
        conn.close()
    return {"ok": True}


@app.post("/api/reset")
def reset_stock():
    with _lock:
        conn = db()
        conn.execute("DELETE FROM stock")
        conn.executemany("INSERT INTO stock(item_id, qty) VALUES(?,?)",
                         [(it["id"], it["n"]) for it in ITEMS])
        conn.commit()
        stock = stock_map(conn)
        conn.close()
    return {"ok": True, "stock": stock}


@app.get("/")
def index():
    pages = sorted(glob.glob(os.path.join(os.path.dirname(BASE), "*.html")))
    if not pages:
        raise HTTPException(404, "页面文件不存在")
    return FileResponse(pages[0])


@app.get("/health")
def health():
    return {"ok": True}
