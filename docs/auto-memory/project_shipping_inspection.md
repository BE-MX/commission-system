# 发货检验领域记忆

- 数据源 `lsordertest.okki_outbound_records / okki_outbound_record_items` 是 OKKI 同步只读镜像。2026-09-01 已实库摸底（`scripts/show_okki_outbound_columns.py`）：单号=serial_id、出库时间=warehouse_invoice_time、客户=company_name、制单人=create_user_name；明细数量=outbound_count、单位=product_unit、规格=product_model、SKU=sku_code。**明细 join 单头必须走 outbound_invoice_id 桥**（items.outbound_record_id 与 records.id 完全不相交，踩过坑）；读取统一走 `app/shipping_inspection/outbound_service.py` 的列内省 + 候选映射，绝不写业务库。
- 检验数据落 commission_db：`ark_shipping_inspections`（outbound_record_id 唯一，draft 懒创建靠唯一键 + begin_nested 并发回退）+ `ark_shipping_inspection_photos`（item_id NULL=整单照片）。两库之间只存 id/单号字符串，不建跨库 FK。
- 出库单二维码前缀 `ARK-I`，内容 `ARK-I:{outbound_record_id}:{hmac8}`（QR_SIGN_SECRET 签名，与 ARK-D/ARK-DU/ARK-DT 不得混用）；小程序扫码原文直交后端验签，前端不解析。
- 提交校验"整单含明细照片总数 ≥1"收口在 `service.submit` 单点；如需收紧为"每条明细必拍"只改这一处。提交幂等靠状态机：已 submitted 的重复提交直接返回原单。
- 照片存储仿 domestic file_service：白名单 jpg/png/webp ≤20MB、uuid+散列子目录、相对路径入库、resolve_path 防穿越、鉴权端点读图不挂静态目录。小程序显示已传照片用 wx.downloadFile 带 Bearer 下载（<image> 直链不可带 header），PC 打印前一律 fetchImageDataUrl 转 data URL 再进 iframe srcdoc。
- PC 打印只走 iframe srcdoc 模式（views/shipping/print/printDocs.js），不新建独立路由打印页；打印时间用 utils/datetime 的 currentBeijingDateTime，且 printDocs.js 必须用相对路径 import 它（node --test 直接 import 该文件，'@/' 别名只在 Vite 下可解析）。
- 小程序端 mini token 无 RBAC，端点挂 /api/mini/shipping-inspection 用 get_current_mini_user；PC 端权限码 shipping_inspection:read/write/admin。
- submitted_by 是 BigInteger 无 FK（ark_users.id 实为 INT UNSIGNED，建 FK 会类型不匹配）。
