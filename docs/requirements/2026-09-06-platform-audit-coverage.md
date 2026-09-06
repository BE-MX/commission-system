# 方舟平台审查覆盖清单（2026-09-06）

本清单记录源码盘点和本地浏览器实际到访，不表示每个业务功能均已在生产验收。主站使用模拟 super_admin 和明确的 503 响应检查错误态；业务成功交互另见主报告。所有浏览器外部网络在独立入口检查时拦截，不使用真实客户数据。

## 后端源码范围

AST 读取全部领域/共享层 Python 文件并识别 HTTP 路由装饰器；权限候选只是扫描线索，不能据此认定接口缺少鉴权。运行时另外注册 router、导出 OpenAPI，不执行 lifespan 或 Scheduler。

| 目录 | Python 文件 | 路由装饰器 |
|---|---:|---:|
| `__init__.py` | 1 | 0 |
| `aftersales` | 11 | 31 |
| `agent_runtime` | 24 | 25 |
| `ai` | 16 | 16 |
| `ai_chat` | 8 | 12 |
| `api` | 9 | 37 |
| `asset` | 13 | 47 |
| `auth` | 10 | 29 |
| `bootstrap` | 10 | 3 |
| `card` | 7 | 14 |
| `color` | 11 | 27 |
| `core` | 6 | 0 |
| `customer` | 43 | 37 |
| `customer_image` | 11 | 30 |
| `customer_media` | 7 | 20 |
| `dashboard` | 6 | 4 |
| `design` | 15 | 32 |
| `design_image` | 11 | 24 |
| `dingtalk` | 15 | 10 |
| `domestic` | 19 | 51 |
| `expo` | 13 | 54 |
| `festival` | 8 | 10 |
| `governance` | 9 | 16 |
| `insight` | 23 | 45 |
| `integration` | 7 | 10 |
| `invoice` | 21 | 54 |
| `knowledge` | 14 | 35 |
| `main.py` | 1 | 1 |
| `mcp` | 11 | 5 |
| `mini` | 6 | 30 |
| `models` | 6 | 0 |
| `operations` | 7 | 4 |
| `order_intelligence` | 8 | 10 |
| `pm` | 13 | 23 |
| `production` | 10 | 26 |
| `report` | 7 | 12 |
| `routers.py` | 1 | 0 |
| `salary` | 14 | 27 |
| `sales_automation` | 14 | 18 |
| `schedulers` | 2 | 0 |
| `schemas` | 8 | 0 |
| `semifinished` | 10 | 15 |
| `services` | 8 | 0 |
| `shipping_inspection` | 9 | 5 |
| `stock` | 18 | 33 |
| `system` | 6 | 5 |
| `tracking` | 15 | 14 |
| `training` | 8 | 13 |
| `utils` | 1 | 0 |
| `whatsapp` | 7 | 7 |
| `whatsapp_translation` | 12 | 16 |

## 主站导航页面

桌面 1440×900 与手机 390×844 均逐路由访问。动态 ID 使用本地占位值 1，详情页可能只显示错误/空态。页面组件与静态入口、WXML 合计 312 个源码表面，不能称为 312 个业务页面。

| 页面 | 路径 | 桌面/手机 |
|---|---|---|
| Dashboard | `/dashboard` | 已到访 / 已到访 |
| AgentTaskCenter | `/agent-runtime/tasks` | 已到访 / 已到访 |
| AgentRunDetail | `/agent-runtime/tasks/:runId` | 已到访 / 已到访 |
| KnowledgeWorkbench | `/knowledge` | 已到访 / 已到访 |
| KnowledgeAiSettings | `/knowledge/ai-settings` | 已到访 / 已到访 |
| EmployeeAttribute | `/employee/attribute` | 已到访 / 已到访 |
| SupervisorRelation | `/supervisor/relation` | 已到访 / 已到访 |
| CustomerSnapshot | `/customer/snapshot` | 已到访 / 已到访 |
| CustomerHubProfiles | `/customer-hub/customers` | 已到访 / 已到访 |
| CustomerHubAcquisition | `/customer-hub/acquisition` | 已到访 / 已到访 |
| CustomerHubResearch | `/customer-hub/research` | 已到访 / 已到访 |
| CustomerHubOpportunities | `/customer-hub/opportunities` | 已到访 / 已到访 |
| CustomerHubRadar | `/customer-hub/radar` | 已到访 / 已到访 |
| InvoiceManage | `/invoice/manage` | 已到访 / 已到访 |
| InvoicePriceConfig | `/invoice/price-config` | 已到访 / 已到访 |
| OkkiSyncSettings | `/invoice/okki-settings` | 已到访 / 已到访 |
| ReceiptDateRepair | `/invoice/receipt-repair` | 已到访 / 已到访 |
| FestivalOrderDetail | `/invoice/festival-orders` | 已到访 / 已到访 |
| OrderIntelligence | `/invoice/order-intelligence` | 已到访 / 已到访 |
| AfterSalesList | `/aftersales/cases` | 已到访 / 已到访 |
| AfterSalesReviews | `/aftersales/reviews` | 已到访 / 已到访 |
| AfterSalesCreate | `/aftersales/cases/new` | 已到访 / 已到访 |
| AfterSalesWorkspace | `/aftersales/cases/:caseId` | 已到访 / 已到访 |
| AfterSalesSop | `/aftersales/sop` | 已到访 / 已到访 |
| AfterSalesAnalytics | `/aftersales/analytics` | 已到访 / 已到访 |
| ExpoWigLibrary | `/expo/wigs` | 已到访 / 已到访 |
| ExpoHairColorLibrary | `/expo/hair-colors` | 已到访 / 已到访 |
| ExpoSceneImages | `/expo/scene-images` | 已到访 / 已到访 |
| ExpoScriptLibrary | `/expo/scripts` | 已到访 / 已到访 |
| ExpoLeads | `/expo/leads` | 已到访 / 已到访 |
| ExpoStoreManagement | `/expo/stores` | 已到访 / 已到访 |
| CardButler | `/expo/card-butler` | 已到访 / 已到访 |
| PaymentSync | `/payment/sync` | 已到访 / 已到访 |
| SalesCommission | `/commission/my` | 已到访 / 已到访 |
| SalesCommissionDetail | `/commission/my/:batchId/details` | 已到访 / 已到访 |
| CommissionBatch | `/commission/batch` | 已到访 / 已到访 |
| CommissionDetail | `/commission/batch/:batchId/details` | 已到访 / 已到访 |
| TrackingList | `/tracking` | 已到访 / 已到访 |
| TrackingDetail | `/tracking/:waybillNo` | 已到访 / 已到访 |
| WaybillUpload | `/tracking/upload` | 已到访 / 已到访 |
| ShippingDailyReport | `/tracking/daily-report` | 已到访 / 已到访 |
| StockOverview | `/stock/overview` | 已到访 / 已到访 |
| SafetyConfig | `/stock/safety-config` | 已到访 / 已到访 |
| StockDailyReport | `/stock/daily-report` | 已到访 / 已到访 |
| ProductionOrderManage | `/stock/production-orders` | 已到访 / 已到访 |
| ProductionOrderPrint | `/stock/production-order-print` | 已到访 / 已到访 |
| SemifinishedMaterials | `/stock/semifinished-materials` | 已到访 / 已到访 |
| SemifinishedOrders | `/stock/semifinished-orders` | 已到访 / 已到访 |
| SemifinishedInventory | `/stock/semifinished-inventory` | 已到访 / 已到访 |
| ProductManage | `/production/products` | 已到访 / 已到访 |
| ProcessManage | `/production/processes` | 已到访 / 已到访 |
| ProcessRouteManage | `/production/process-routes` | 已到访 / 已到访 |
| ProductionDashboard | `/production/dashboard` | 已到访 / 已到访 |
| PrintCard | `/production/print-card/:id` | 已到访 / 已到访 |
| DomesticOrders | `/domestic/orders` | 已到访 / 已到访 |
| DomesticOrderCreate | `/domestic/orders/create` | 已到访 / 已到访 |
| DomesticProducts | `/domestic/products` | 已到访 / 已到访 |
| DomesticCustomers | `/domestic/customers` | 已到访 / 已到访 |
| ShippingOutbound | `/shipping/outbound` | 已到访 / 已到访 |
| ShippingInspections | `/shipping/inspections` | 已到访 / 已到访 |
| AssetLibrary | `/asset/library` | 已到访 / 已到访 |
| AssetUpload | `/asset/upload` | 已到访 / 已到访 |
| AssetFavorites | `/asset/favorites` | 已到访 / 已到访 |
| AssetStats | `/asset/stats` | 已到访 / 已到访 |
| TagDimensionManage | `/asset/tag-dimensions` | 已到访 / 已到访 |
| ColorPalette | `/color-management/palette` | 已到访 / 已到访 |
| ColorBlends | `/color-management/blends` | 已到访 / 已到访 |
| ColorTrends | `/color-management/trends` | 已到访 / 已到访 |
| ColorSwatchGenerator | `/color-management/swatch-generator` | 已到访 / 已到访 |
| TrainingList | `/training/digests` | 已到访 / 已到访 |
| TrainingEditorNew | `/training/digests/new` | 已到访 / 已到访 |
| TrainingDetail | `/training/digests/:id` | 已到访 / 已到访 |
| TrainingEditorEdit | `/training/digests/:id/edit` | 已到访 / 已到访 |
| InsightIntelligenceOverview | `/insight/intelligence` | 已到访 / 已到访 |
| InsightIntelligenceLibrary | `/insight/library` | 已到访 / 已到访 |
| InsightIndustryDaily | `/insight/industry-daily` | 已到访 / 已到访 |
| InsightAITools | `/insight/ai-tools` | 已到访 / 已到访 |
| InsightInternalReports | `/insight/reports` | 已到访 / 已到访 |
| InsightCaseLibrary | `/insight/cases` | 已到访 / 已到访 |
| InsightMeetingMinutes | `/insight/minutes` | 已到访 / 已到访 |
| InsightSources | `/insight/sources` | 已到访 / 已到访 |
| DesignImageStudio | `/design/image-studio` | 已到访 / 已到访 |
| CustomerImageAdmin | `/design/customer-image` | 已到访 / 已到访 |
| DesignAiChat | `/design/ai-chat` | 已到访 / 已到访 |
| DesignGantt | `/design/gantt` | 已到访 / 已到访 |
| DesignSubmit | `/design/submit` | 已到访 / 已到访 |
| MyRequests | `/design/my-requests` | 已到访 / 已到访 |
| CustomerMediaPortalPreview | `/design/media/portal` | 已到访 / 已到访 |
| CustomerMediaReview | `/design/media/review` | 已到访 / 已到访 |
| CustomerMediaAccounts | `/design/media/accounts` | 已到访 / 已到访 |
| CustomerMediaWorkspace | `/design/media/tasks/:taskId` | 已到访 / 已到访 |
| DesignAudit | `/design/audit` | 已到访 / 已到访 |
| DesignManage | `/design/manage` | 已到访 / 已到访 |
| DesignStats | `/design/stats` | 已到访 / 已到访 |
| SalaryProfiles | `/salary/profiles` | 已到访 / 已到访 |
| SalaryRules | `/salary/rules` | 已到访 / 已到访 |
| SalaryPeriods | `/salary/periods` | 已到访 / 已到访 |
| SalaryWorkbench | `/salary/periods/:id` | 已到访 / 已到访 |
| UserManagement | `/system/users` | 已到访 / 已到访 |
| RoleManagement | `/system/roles` | 已到访 / 已到访 |
| DictManagement | `/system/dicts` | 已到访 / 已到访 |
| AIManager | `/system/ai` | 已到访 / 已到访 |
| OperationsCenter | `/system/operations` | 已到访 / 已到访 |
| McpTokenManagement | `/system/mcp-tokens` | 已到访 / 已到访 |
| IntegrationAppManagement | `/system/integration-apps` | 已到访 / 已到访 |
| GmvDailyConfig | `/system/dingtalk-gmv-daily` | 已到访 / 已到访 |
| ExternalBindings | `/system/external-bindings` | 已到访 / 已到访 |
| WhatsAppConnector | `/system/whatsapp-connector` | 已到访 / 已到访 |
| WhatsAppTranslation | `/system/whatsapp-translation` | 已到访 / 已到访 |
| ReportCenter | `/report` | 已到访 / 已到访 |
| ReportView | `/report/view` | 已到访 / 已到访 |
| ConceptRegistry | `/governance/concepts` | 已到访 / 已到访 |
| ConceptEditor | `/governance/concepts/:conceptId` | 已到访 / 已到访 |
| ConceptGraph | `/governance/graph` | 已到访 / 已到访 |
| ChangeLog | `/governance/change-logs` | 已到访 / 已到访 |
| Profile | `/profile` | 已到访 / 已到访 |

## 独立页面、静态入口及 PM

同样检查两种视口。采购节四个 1920×1080 舞台页面的 scrollWidth 大于视口，属于缩放舞台布局，截图中并非业务按钮不可达；手机仅核对展示可打开，不将电视大屏强行改为表单式手机布局。

| 类型 | 路径 | 桌面/手机 |
|---|---|---|
| main | `/login` | 已到访 / 已到访 |
| main | `/inventory` | 已到访 / 已到访 |
| main | `/expo/kiosk` | 已到访 / 已到访 |
| main | `/create` | 已到访 / 已到访 |
| main | `/whatsapp-translation/authorize` | 已到访 / 已到访 |
| static | `/6010/index.html` | 已到访 / 已到访 |
| static | `/caigoujie/index.html` | 已到访 / 已到访 |
| static | `/caigoujie/liuli.html` | 已到访 / 已到访 |
| static | `/caigoujie/xiangsu.html` | 已到访 / 已到访 |
| static | `/card/ginny/index.html` | 已到访 / 已到访 |
| static | `/card/janny/index.html` | 已到访 / 已到访 |
| static | `/card/katy/index.html` | 已到访 / 已到访 |
| static | `/card/sylvia/index.html` | 已到访 / 已到访 |
| static | `/customer-media/index.html` | 已到访 / 已到访 |
| static | `/expo-sales/index.html` | 已到访 / 已到访 |
| static | `/festival/fugou.html` | 已到访 / 已到访 |
| static | `/festival/index.html` | 已到访 / 已到访 |
| static | `/festival/tuandui.html` | 已到访 / 已到访 |
| static | `/festival/xinqian.html` | 已到访 / 已到访 |
| static | `/festival/zhaiyao.html` | 已到访 / 已到访 |
| static | `/festival/zhenying.html` | 已到访 / 已到访 |
| static | `/m/index.html` | 已到访 / 已到访 |
| static | `/m/login.html` | 已到访 / 已到访 |
| pm | `/` | 已到访 / 已到访 |
| pm | `/dashboard` | 已到访 / 已到访 |
| pm | `/tasks` | 已到访 / 已到访 |
| pm | `/materials` | 已到访 / 已到访 |
| pm | `/materials/1` | 已到访 / 已到访 |
| pm | `/activity` | 已到访 / 已到访 |

## 其他客户端与服务

- 微信小程序：所有 `miniprogram/pages/*.wxml` 纳入源码盘点；未启动微信开发者工具，扫码、相机与真机报工未验。
- 服务边界独立审查：WhatsApp Connector、OpenClaw Sales Agent、DSH Agent Worker、Social Customer MCP；后端 router/bootstrap/scheduler 与发布协调/迁移/静态同步。
- 主站资产、知识库等鉴权仍通过既有 API 与权限指令；PM 独立身份、公开/邀请门户、MCP 机器凭证保持现有边界。
- 外部已上线但没有本仓库权威源码的 hair/video 站、远端 Shopify/MCP 进程等，以 deploy/platforms.json 登记为边界，未改动远端。
