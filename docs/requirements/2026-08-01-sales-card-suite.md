# 业务员名片 + 电子主页 + 引流海报（2026-08-01）

> 8 月展会交付。今晚出印刷文件 + 电子主页关键功能；明早印刷名片/海报。

## 目标

1. **名片**：有质感、"扔掉可惜"。正面 = AI 头像 + 英文名 + 邮箱 + WhatsApp（占位）+ 大二维码；背面 = leShine Hair logo + 使用说明。
2. **电子主页**：客户微信/WhatsApp 扫码直达。业务员介绍 + 店铺/独立站链接（暂缓）+ 英文 FAQ + 客户口令解锁「本次展会沟通内容 + 照片」+ 客户提交需求。定位："我是你专属的业务管家"。
3. **海报**（普通 PDF，非易拉宝）：闸机引流，AI 试戴限时免费 + 赠 AI 写真照片和相框。

## 访谈锁定的决策

| 决策点 | 结论 |
|---|---|
| 客户口径 | **海外买家为主**：主页英文，口令 = 客户邮箱或 WhatsApp 号 |
| 口令解锁内容 | **仅业务员手工录入**（文字 + 图片附件），不挂试戴建档表 |
| 二维码 URL | **`https://leshine.work/card/<slug>/`** 烘焙静态页（后端挂了公开层照常打开）|

**URL 冲突结论（印刷前置检查，已核实）**：云端 nginx `location ~ ^/(api|uploads|s|health)` 是**前缀正则**，凡 `/s` 开头路径全代理给后端（短链 `GET /s/{code}` 在用）——`/s/<名>`、`/sales/`、`/shop/` 全不可用。`/card/` 三端干净：nginx 不截、FastAPI 无 `/card` 路由、与 `dist` 现有静态目录不撞。

## 架构

**公开层 = 烘焙静态页**（无后端依赖）：
- `frontend/public/card/<slug>/index.html`，每人一页，走既有静态托管模式（cloud nginx `try_files` 零改动；scp 即时上线）
- 内容：头像、英文名、职位、介绍、邮箱按钮、WhatsApp/店铺链接（数据未到，槽位隐藏）、FAQ（折叠+搜索样式壳，内容明早补）、口令输入框、需求提交表单
- 生成脚本 `scripts/card_pages/`：`salespersons.json` + 模板 → 静态页；数据到齐重跑秒级更新

**动态层 = 新领域模块 `app/card/`**（router/models/schemas/service 四件套）：
- 公开端点（无鉴权，机器对机器白名单注释）：
  - `POST /api/card/{slug}/unlock`：口令（邮箱小写 / WhatsApp 纯数字归一化）→ 该业务员名下客户的纪要+附件
  - `POST /api/card/{slug}/inquiries`：客户提交需求/问题（联系方式 + 正文）
- 管理端点：`card:read` / `card:write`（seed_role_permissions upsert，动作词在白名单内）
- 前端「名片管家」页：业务员档案、客户绑定（口令）、纪要录入、询盘查看；navigation.js 一条 entry

**表（1 个迁移，4 张表）**：
- `ark_card_salespersons`：slug(唯一)/english_name/email/whatsapp/avatar_path/title/intro/links_json/is_active
- `ark_card_customers`：salesperson_id FK / display_name / email_norm / whatsapp_norm / expo_code / 备注（email_norm、whatsapp_norm 建索引，口令查询口径）
- `ark_card_entries`：customer_id FK / entry_type(text|image) / title / content / attachment_path / created_by
- `ark_card_inquiries`：salesperson_id FK / customer_id 可空 FK / contact / message / status(new|handled)

**隐私注记**：口令 = 客户自己的邮箱/WhatsApp，存在被猜中风险 → 纪要里避免放敏感报价；v1 不做验证码，unlock 失败不提示存在性（统一"未找到"文案）。

## 印刷交付

- **名片**：90×54mm + 2mm 出血（成品 94×58）双面 PDF，300dpi，每人一份 ×4 人（Ginny/Janny/Katy/Sylvia，邮箱 = `<名>@leshinehair.com`）。视觉 = leShine 黑×黄（logo 黑字黄底手写体）。AI 头像用户已备好（3D 卡通风格白底 PNG ×4）。二维码 EC=H，印前逐张解码验证。
- **海报**：A1（594×841mm）竖版 + 3mm 出血 PDF。文案：FREE AI Hair Try-On（限时）+ 赠 AI 写真+相框 + 展位号占位（明早填）。
- 管线：HTML/CSS 精确排版 → Playwright（系统 Chrome）print-to-PDF。模板与脚本入库 `scripts/card_print/`。

## 范围裁剪（用户 2026-08-01 指定）

- WhatsApp 号、店铺/独立站链接：**暂缓**，模板留槽，数据到了重跑生成脚本即可（名片如需 WhatsApp 上版，重出 PDF 秒级）
- FAQ：今晚只出样式壳（含 SAMPLE 条目标注），内容明早补
- 海报做普通 PDF，不做易拉宝尺寸

## 今晚执行序

① 印刷管线（硬 deadline）→ ② 静态主页 + 上云 → ③ 后端模块 + 管理页 → ④ pytest / build / check_conventions → ⑤ 对抗性审查 → ⑥ 讲解 + 测验。
