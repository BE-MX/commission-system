# 员工 PI 按指定模板导出

状态：Git 交付，用户已授权提交、合入 main 并推送；最终状态以 Git refs 回读为准，未部署。分支 `codex/portal-purchase-dock`，与商品操作区、结算滚动及 PI 详情优化一起交付。原实现 worktree 的证据已保留到主目录 `tmp/portal-pi-main-integration-20261023-190956/evidence/`。

## 行为与实现

入口：**客户门户 → 下单请求 → 详情 → 处理原 PI → 页头「导出当前 PI」Excel / PDF**。

两种导出显式请求既有发票端点并携带 `template=leshine_pi`；实时 `invoice:read` 和单据可见范围守卫先于渲染。无权限时不显示空导出区，历史/提案页禁止将其误导出为当前 PI。原发票页默认导出、打印以及客户门户的已发布快照 PDF 未改变。

原始 `发票模板.xlsx` 原样纳入 `backend/app/invoice/assets/portal_pi_template.xlsx`（SHA256 及资源约定见该目录 README）。采用模板的 Logo、公司抬头、Proforma Invoice 标题、To/From 联系区、八列商品明细及费用区。Excel 保留原绘图部件，包括 openpyxl 不支持的浮动文本框；清除示例业务员及旧 mailto。多商品自动扩展行数，设置 A4 一页宽、不压成单页高，打印重复表头。

PDF 使用原 Logo 和模板中的抬头文字、列比例，以现有 ReportLab 生成可检索文本、中文字体、自动换行、续页重复表头与页码；不依赖生产服务器安装 Office/LibreOffice。PDF 与 Excel 共享字段映射，但分别分页，打印结果不是逐像素一致。

金额读取单据已存成交价、行折扣、净行金额、净商品额、运费、包装、附加费和总额，不重算模板中的固定 5% 手续费。折扣写在商品描述中，保留原八列布局；包装存在时增加费用行，明确币种，付款条件、运输方式和备注完整导出。不导出内部已收款、余额或价格规则。

## 验证

- 新模板、接口权限/范围、原发票金额/导出回归共 **61 passed**，只用内存对象及隔离 SQLite。覆盖 0/1/4/5/6/65 行、混合配件、成交价四位小数、中文/长地址/长色号/备注、公式注入、抬头图像及绘图关系、旧示例邮箱清除、缺失联系人、实际 API Excel/PDF 响应、JWT 权限过期、跨负责人拒绝与未知模板 422。
- 初版长色号断言发现 PDF 在窄格内正常断行；改为消除排版空白后逐字符检查，所有 END 标记均保留，不删除内容断言。
- 独立风险审查通过：无权限或财务边界阻断项；确认绘图关系完整、费用不重算、65 行完整且汇总一次。
- 员工前端构建通过，保留原有 chunk/import 提示；本地 venv 原先缺少 requirements 中已声明的 ReportLab，补装 4.5.1 后 PDF 测试通过，没有改动依赖清单。
- 构建页面浏览回归连续 **3 次通过，每次 5 场景**：Excel/PDF 均携带指定模板参数，保持防重、403 局部反馈、关闭后迟到响应丢弃及 PI 命令幂等。浏览 API 被截获；后端 TestClient 则实际返回模板 XLSX/PDF。新增 query 参数后，原慢下载测试的 URL 后缀匹配已改为解析 pathname，避免把合法参数误判为没有请求。
- 增量约定与 `git diff --check` 通过；`git_sweep.py --no-fetch` 完成，只读本地 refs，不操作其他工作区。

可复跑：backend 中执行 `python -m pytest tests/test_pi_template_export.py tests/test_invoice_scope.py tests/test_invoice_module.py tests/test_invoice_amounts.py -q`。前端按原 `frontend/tests/portalPiReview.browser.mjs` 本地构建预览流程运行。

工作区证据 `tmp/pi-template-qa/`：`preview-1.xlsx/pdf/png`、`preview-65.xlsx/pdf`、首末页 PNG、`preview-long.pdf`、`build.log`、`browser/`。这些是合成单据验证文件，非真实客户 PI。已查看正常、长字段和多页末页画面，未做真实业务单据导出或生产写入。
