# 展会样品销售 · 库存同步服务

多人同时下单时库存实时同步、不超卖。价格以服务端 `items.json` 为准，客户端只传商品 id 和数量。

## 文件

- `server.py` — FastAPI 服务（单文件）
- `items.json` — 商品与初始库存数据（57 款）
- `expo.db` — SQLite 数据库，首次启动自动创建
- `start.bat` — Windows 一键启动
- 上级目录的 `*.html` — 销售页面，由服务直接托管（`GET /`）

## 启动

```bash
pip install -r requirements.txt   # 或复用 backend/.venv（已含 fastapi+uvicorn）
uvicorn server:app --host 0.0.0.0 --port 8010
```

浏览器访问 `http://服务器IP:8010` 即可。挂公网时建议用 nginx 反代：

```nginx
location /expo/ {
    proxy_pass http://127.0.0.1:8010/;
    proxy_set_header Host $host;
}
```

## 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/state` | 当前库存 `{stock: {id: qty}}` |
| POST | `/api/orders` | 下单 `{cust, lines:[{id, qty}]}`，事务内原子扣减，库存不足返回 409 |
| GET | `/api/orders` | 订单列表（新到旧） |
| POST | `/api/orders/{no}/cancel` | 撤销订单并恢复库存 |
| POST | `/api/orders/clear` | 清空订单（重置单号） |
| POST | `/api/reset` | 库存恢复为 items.json 初始值（保留订单） |

## 调整库存

改 `items.json` 里对应商品的 `n`，并把 `server.py` 顶部 `STOCK_VER` 加 1，重启服务即自动重播种（订单记录保留）。
