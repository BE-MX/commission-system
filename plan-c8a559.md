# 物流短链接功能

为每个物流运单生成短链接，点击后 302 跳转到对应物流商官网查询页面；短链接在前端页面展示（可复制）并可用于钉钉通知。

## 设计

- **短码格式**：8位随机字母数字（base62），存储在 `shipment_tracking.short_code` 列
- **跳转地址**：`GET /s/{code}` → 302 重定向到物流官网查询 URL
  - DHL: `https://www.dhl.com/cn-zh/home/tracking/tracking-parcel.html?submit=1&tracking-id={waybill_no}`
  - FedEx: `https://www.fedex.com/fedextrack/?trknbr={waybill_no}`
  - 其他物流商：回退到 Google 搜索 `{carrier} tracking {waybill_no}`
- **短链接完整 URL**：`{SHORT_LINK_BASE_URL}/s/{code}`，`SHORT_LINK_BASE_URL` 从环境变量读取

## 改动清单

| # | 文件 | 改动 |
|---|------|------|
| 1 | `backend/app/models/tracking.py` | `ShipmentTracking` 新增 `short_code` 列 (String(8), unique) |
| 2 | `backend/app/core/config.py` | 新增 `SHORT_LINK_BASE_URL` 配置项 |
| 3 | `backend/app/services/short_link.py` | **新文件**：生成短码 + 构建物流商查询 URL 的映射逻辑 |
| 4 | `backend/app/services/staging_service.py` | 创建 `ShipmentTracking` 时生成 `short_code` |
| 5 | `backend/app/schemas/tracking.py` | `ShipmentListItem` / `ShipmentDetailResponse` 新增 `short_link` 字段 |
| 6 | `backend/app/api/tracking.py` | 新增 `GET /s/{code}` 302 重定向端点；列表和详情返回 `short_link` |
| 7 | `backend/app/main.py` | 注册短链接路由（根路径 `/s/{code}`） |
| 8 | `backend/alembic/versions/005_add_short_code.py` | **新文件**：Alembic 迁移添加 `short_code` 列 |
| 9 | `frontend/src/views/tracking/TrackingList.vue` | 表格新增"短链接"列，带复制按钮 |
| 10 | `frontend/src/views/tracking/TrackingDetail.vue` | 信息卡片中展示短链接，带复制按钮 |
