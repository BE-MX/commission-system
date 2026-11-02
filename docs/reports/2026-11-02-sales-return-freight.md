# 2026-11-02 退货单运费退款验证

本次用户要求补齐运费退款，并验证商品 USD 286.50 + 运费 USD 11.18 = 现金 USD 297.68。工作区 `D:/MyProgram/commission-system-codex-return-freight`，分支 `codex/return-freight`，基点 `a5b144a8`。本批仅本地实现与验证，未合并、推送、部署或创建生产退货单。

## 业务结果

- 新建、编辑、预览、列表和详情均保留独立运费；现金退款字段为商品加运费合计，可留空自动计算。
- 商品与运费各自校验原已收本金、历史有效退款和剩余额度。生效加锁后重新核验；重复请求幂等；反向更正恢复额度。
- 现金凭证为 -297.68，商品/GMV -286.50，运费应收 -11.18。冲销对应 +297.68、+286.50、+11.18；余额不会把已退运费重新当成欠款。
- 提成扣回仍取原人员与原比例，以实际现金退款合计为依据；兼容旧商品退款与新运费退款混合以及不同反冲顺序。原依据缺失仍待补核。
- 只接受证据完整的 USD 现货单笔全额回款运费；附加费不退，分笔/部分/非 USD/预售费用分摊不猜测。
- 迁移 247 增加五个非空零默认金额列。旧记录不改金额；重复升级检查既有列契约；存在非零运费时禁止降级删除财务事实。

## 实际验证

- 退货域扩大回归初跑 219 通过、1 失败：既有预售资金保护测试手工 mock quote 缺少新增的两个零运费字段。补齐 mock 后，原资金保护与事务回滚断言不变，对应套件 17 项全部通过。未把该次初跑称为全绿；两轮覆盖的 220 项均取得通过结果。
- 真实独占本机 MySQL 8.4.6 套件 8 项通过，覆盖迁移、重复退款、并发占用运费及既有提成确认与退款事务排序。早期尝试的测试建表未覆盖主线 commerce-transition 锁依赖，已完善隔离夹具再通过；未改生产锁逻辑或弱化断言。
- 前端 29 项通过；生产构建通过（保留原包体积及 auth 混合导入提示）。
- MySQL 强制 READ ONLY 与小满 GET 对 26008 / 翟 #260960 取实时证据；生产尚无有效退货。候选纯计算的退货退款、仅退款均为 286.50 + 11.18 = 297.68，未收减免 0，剩余运费 36.93；未执行候选生产写接口。证据 `tmp/26008-freight-readonly.json`。
- Chrome 本机隔离页面使用内存 SQLite 与真实候选 router/service，完成超额 48.12 拦截、合法预览、保存、编辑回显、生效及冲销。回读原款分摊含运费 11.18，现金凭证 ±297.68，商品 GMV ±286.50，运费事实 ±11.18。详情六列表头及数值在 1427×718 视口完整可见。证据 `tmp/browser-freight-evidence.json`；此项不代表生产实单执行或窄屏验收。
- 独立代码终审无阻断，确认商品/运费额度、余额、提成、旧请求幂等、迁移及展示闭环。
- `python scripts/check_conventions.py` 增量检查和 `git diff --check` 通过；`python scripts/git_sweep.py --no-fetch` 完成，仅代表本地缓存远端引用。构建生成的无关导航清单已恢复，其他工作区未修改。

主要复验命令：后端 `python -m pytest tests -q --disable-warnings --tb=short --ignore=tests/portal_mysql -k sales_return`；修正 mock 后 `python -m pytest tests/test_sales_return_presale_adjustments.py -q`；前端 `node --experimental-vm-modules --test frontend/tests/salesReturn.test.mjs frontend/tests/salesReturnReceipt.test.mjs` 与 `npm run build`。MySQL 使用 `tests/portal_mysql/test_mysql_sales_returns.py --confcutdir=tests/portal_mysql` 和显式独占本机 mysqld/workspace 参数，环境身份见 `tmp/freight-mysql-04/runtime.json`。

生产迁移和真实业务写入仍未执行；本次未获得本批合并、推送或部署授权。证据保留于本工作区 `tmp/`。自动审批拒绝收尾清理命令，仅返回 `blocked by policy`，因此未停止验收进程（当时 PID 61008/11812，端口 8127/5932），也未移动 `frontend/__freight_verify/`、`frontend/__freight-verify.config.mjs` 或删除 `tmp/freight-mysql-01..04`。这些本次临时材料保持原样，不进入产品标准构建入口，后续提交应排除验收页面和配置；未改用其他工具绕过清理拦截。

## 后续发布授权

用户已明确授权本批合并、推送与部署，并要求上线后验证商品 286.50、运费 11.18、合计 297.68 美元，先不实际生效退款。发布后仅做真实页面预览并放弃输入，不保存或生效业务单据；正式发布证据另行记录。
