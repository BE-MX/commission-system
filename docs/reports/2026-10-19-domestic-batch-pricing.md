# 内贸发货批次独立单价

创建发货批次可按订单明细调整「本批单价」，默认沿用订单单价。修改仅保存到本批价格快照，用于本批货款、未结款和收款核销；原订单单价、订单总额、账户扣款及后续批次默认单价保持原值。界面并列显示订单单价和可编辑的本批单价，金额实时更新，批次详情与 CSV 使用保存的本批价格。

批次调价不会另建账户调价账本。未发货金额和订单终止退款按原订单价乘未发数量计算；实际收款仍经原审核流程入账。保存后的批次不提供改价入口。本次无数据库迁移。

## 验证

- 隔离 SQLite：`backend/.venv/Scripts/python.exe -m pytest tests/test_domestic_delivery.py -q`，28 项通过。覆盖降价、加价、零价、混合价格跨订单批次、后续批次不继承价格、原订单金额/扣款不变、终止退款、收款核销上限、重复请求与非法价格；超限金额在行写入前拦截。
- 扩大回归：交付、订单类型、财务导出、审核、撤回五组测试当时为 72 通过 / 1 个既有失败；后增加 3 项交付测试已在上述 28 项专项中通过。失败为 `test_domestic_withdraw.py::test_review_migration_compiles_for_mysql_and_has_one_head`，HEAD 原有断言仍为 `196_domestic_commission`，实际迁移 head 是 `197_battle_awards`。本次未修改迁移或该测试。
- `node --test tests/domesticDeliverySelection.test.mjs tests/domesticDeliveryState.test.mjs`：5 项通过；覆盖跨页汇总、分精度、零价、非法输入、数量与具体件号编辑保留调价及取消选择后重置。
- `npm run build`：通过，保留既有大 chunk 和动态/静态混合导入提示。
- 实际 Vue 组件 + Edge 无头浏览器，API 全拦截为模拟数据：1440px、390px 均通过。验证改价、金额实时变化、非法输入阻止提交、翻页、件号选择、提交载荷、保存后单价及快捷收款/核销金额为 80.25，无页面异常。没有真实生产写入。
- 独立 agent 资金风险审查通过；审查发现单价乘数量可能超出数据库金额精度，已前移上限校验并补 flush 前回归。
- `scripts/check_conventions.py --strict`、`git diff --check` 通过；`scripts/git_sweep.py --no-fetch` 完成，仅为本地 Git 快照，不代表已同步远端。

本地浏览器证据位于 `tmp/batch-pricing/`，含桌面/手机创建及已保存截图。恢复用测试壳 `preview.html` 与执行脚本 `tmp/batch-pricing-browser.cjs` 保留在 tmp，均未包含凭据；需要重跑时将壳复制至脚本指定的前端 tests 路径并启动隔离 Vite :3094。所有 `/api/` 请求被脚本拦截，脚本不连接业务后端。

## 交付状态

实现分支为 `codex/domestic-batch-pricing`，开发基点 `bca7b607`。用户已授权本次提交、合并 main 并推送；集成只包含本任务代码及文档。主目录原有改动采用文件副本、binary patch、index 快照和 SHA256 清单保护；重叠文档保留原有内容并补入本次说明。验证证据及恢复材料移至主目录 `tmp/domestic-batch-main-integration-20261019/`，Git 核验及集成结果另保留其中。无部署、共享数据库迁移或生产业务数据写入。
