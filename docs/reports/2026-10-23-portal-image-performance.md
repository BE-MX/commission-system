# 客户门户商品大图与详情加载修复

日期：2026-10-23。分支：`codex/portal-image-performance`。状态：用户已授权 Git 集成与推送，未部署。

## 根因与修改

- `FamilyDetailView` 将 `swatch_url` 优先用于主图，`FamilyGrid` 也可能以色卡作为封面。服务端色卡默认/显式 thumb 只有 96 像素，放进大图容器后模糊。ProductImage 在这些大图位置显式请求 full（最长边 1200）；色号按钮仍取 96 像素。详情主图 eager，沿用相同来源白名单、失败占位与服务端权限复查。低分辨率原始素材不会被凭空放大。
- `family_detail` 每个规格通过原定价服务重复查询颜色、标准价和客户规则；两个规格的隔离回归实测 10 次定价 SQL。新增仅活在该请求内的 BrowsePrices，唯一颜色/标准组合每批最多 200 个，以 SQL 标量子查询和 JOIN 保留数据库 collation、颜色别名选择以及系列匹配歧义处理。客户规则每请求读一次。两个以及重复扩展的 200 个规格夹具均为 3 次定价 SQL；大于 200 个唯一组合时按批增长。
- 下单/提交不传浏览快照，继续实时权威解析；库存验证、缺价不可下单、授权及 namespace 校验沿用原逻辑。没有数据库迁移或配置变更。

## 验证

- 后端：`python -m pytest tests/portal/test_family_catalog.py tests/portal/test_catalog.py tests/portal/test_product_images.py tests/portal/test_managed_images.py tests/test_invoice_pricing.py -q`，**86 passed**，隔离 SQLite。覆盖批量查询数量、正常/固定规则/缺价/歧义系列/显式颜色/颜色别名/未识别颜色/负价/币种/namespace/非法规则与价格刷新。
- 实际图片渲染：1600×1200 本地素材，full 输出 1200×900、thumb 输出 96×72。
- 门户 `npm test`：142 passed；`npm run build` 通过。
- `tests/family.browser.mjs`：构建产物 + 内存 API，1440 与 375 宽度验证封面和主图 naturalWidth=1200、主图 eager、按钮 thumb、规格切换、缺货、加选与进入结算，无横向溢出或页面错误。截图保存在该 worktree 的 `tmp/portal-image-performance/`。
- `check_conventions.py` 与 `git diff --check` 通过；`git_sweep.py --no-fetch` 已运行，仅本地远端快照，不操作其他分支。
- 原有 family 测试期望旧无 size URL，但基线服务已经返回 `&size=thumb`，本次同步为明确缩略图 URL 断言。

- 独立审查通过：初轮颜色别名优先级、未知颜色匹配 NULL 价格问题已修复并复验；批量查询保留数据库匹配，MySQL 方言编译通过。尚无真实 MySQL 运行证据。

## 证据边界

线上首页与当前 JS bundle 可以只读访问，bundle 中详情仍直接优先 swatch_url；没有可用的客户认证上下文，本次未完成线上登录态图片像素/接口耗时测量。修复效果以本地回归及浏览器验证为依据，线上改善时间不作估算。本次按用户授权集成 main 并推送，最终 refs 回读为交付证据；无部署或生产数据库/配置/素材写入。
