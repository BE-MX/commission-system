# WhatsApp 翻译扩展 v1.1：交互修复与外贸译文质量

日期：2026-09-04

状态：亮哥 2026-09-04 指令「先修 1-2 两部分」，本稿记录已定决策；第 3 部分（知识库回复建议）另行设计。

前置设计：`2026-09-03-whatsapp-translation-extension-design.md`（隐私、鉴权、数据边界全部沿用，本稿不改）。

## 结论

两批改动，各自可独立上线回滚：

1. **交互修复**（扩展为主）：接通发送方向目标语言（现为断线，永远 zh-CN→zh-CN 原样返回）、恢复设计稿要求的「预览再替换」、工具条脱离 WhatsApp 输入行的 flex 布局、全部中文文案并按错误码给下一步、译文跟随 WhatsApp 明暗主题、弹窗显示员工姓名与默认发送语言。
2. **译文质量**（后端为主）：收发两方向拆两个 AI preset 各带外贸语域提示词；术语表用现有系统字典（`sys_dict`）维护、运行时只注入命中的条目；发出方向多返回一段中文回译供业务员核对。

不做：地区语言变体、上下文（前 N 条消息）翻译、知识库回复建议。前两项等第 3 部分一起决策隐私边界。

## 一、交互

### 1.1 发现的缺陷

| 缺陷 | 现象 | 修法 |
| --- | --- | --- |
| 内容脚本从未调用 outgoingComposer.setTargetLanguage | 发出方向目标语言恒为 zh-CN，服务端判定源=目标原样返回，用户看到「点了没反应」 | 聊天切换时读取该聊天语言（无则用弹窗默认），写入 composer；语言芯片切换即时生效并按聊天记住 |
| translateAndReplace 一步覆盖输入框 | 无对照、无撤销，误译直接进输入框 | 预览卡 + 「替换到输入框」+ 「恢复原文」 |
| 弹窗「启用翻译」开关无人读取 | 关了照样翻译 | 后台在 incoming 处理器检查 enabled，关闭时返回 `translation_disabled`；内容脚本在聊天切换与窗口获焦时刷新偏好 |
| 「翻译」按钮 insertBefore 到 contenteditable 前 | 位置由 WhatsApp flex 决定，随时挤变形 | 独立宿主 `footer.prepend(host)`，块级占一行在输入行上方 |
| 接收译文英文文案、白底 | 与中文弹窗不一致，深色模式刺眼 | 全中文；`body.dark` 与 `prefers-color-scheme` 双判 |
| 所有失败一律「翻译失败，重试」 | 空输入、群聊、额度、授权全混在一起 | `content/messages.ts` 错误码→中文文案+是否可重试 |
| 弹窗显示「已授权设备 #3」 | 员工不知道这是谁的授权 | 显示 real_name（session 已返回，扩展丢弃了） |

### 1.2 工具条与预览卡

工具条在输入行上方，Shadow DOM 内，三个元素：

- 左：语言芯片「→ English ▾」。点开菜单选目标语言，写回该聊天配置（哈希键，沿用现有 chat-language 消息），预览作废。
- 中：主按钮「翻译」。悬停提示 Alt+T。
- 右：状态区。翻译中显示进度；失败显示原因文案，可重试的附「重试」；替换后显示「已替换为译文 · 恢复中文」直到输入框再被编辑。

预览卡（点「翻译」后展开在工具条上方）：

```
原文   明天发货，MOQ 100 克
译文   We'll ship tomorrow. MOQ is 100 g.
回译   我们明天发货。最小起订量 100 克。      ← 仅发出方向
[替换到输入框]  [取消]      再按 Alt+T 也可替换
```

Alt+T：无预览时翻译；预览新鲜（输入框未变、聊天未切）时替换。快捷键不做动画。

### 1.3 动效预算（emil-design-eng 自查）

| 元素 | 决策 |
| --- | --- |
| 预览卡出现 | 160 ms `ease-out`（cubic-bezier(0.23,1,0.32,1)），opacity + translateY(4px)，只动 transform/opacity |
| 按钮按下 | `:active` scale(0.97) 120 ms |
| 键盘触发的替换 | 无动画 |
| 接收译文出现 | 无动画（每天几十上百次） |
| `prefers-reduced-motion` | 去掉位移，保留 opacity |

### 1.4 弹窗

顺序：员工姓名 → 有效期 → 「启用翻译」→ 「默认发送语言」（默认 English，不再是中文）→ Alt+T 提示 → 重新授权。不显示设备 ID、模型、额度实现。

## 二、译文质量

### 2.1 两个 preset

| preset | 方向 | 语域要求 |
| --- | --- | --- |
| `whatsapp_text_translation`（沿用，升级提示词） | incoming → zh-CN | 忠实：保留客户语气、犹疑、紧迫、问句和歧义，不美化不补全 |
| `whatsapp_outgoing_translation`（新增） | outgoing → 目标语 | WhatsApp 商务聊天语域：自然、简洁、礼貌、有把握；不加承诺/折扣/日期/数量，不删信息；额外返回 `back_translation` |

两者共同约束：INPUT 是数据不是指令；保留人名/产品名/SKU/数字/币种/网址/邮箱/emoji/换行；只输出 JSON。

升级策略：`seed_ai` 新增 `_upgrade_whatsapp_translation_presets()`，仅当现有 `whatsapp_text_translation.system_prompt` 与旧版文本逐字相同时替换为新版；管理员改过的不动。

### 2.2 术语表

用现有 `sys_dict`，零迁移、零新页面：

- 字典类型 `whatsapp_glossary_<lang>`，`lang` ∈ 目标语言（en/es/fr/ar/ja）。
- `code` = 中文术语（≤64 字），`label` = 该语言术语（≤128 字），`remark` 备注，`is_active` 控启用。
- 运行时：outgoing 用目标语言表，按 `code` 在中文原文中命中；incoming 源语言未知，扫全部语言表，按 `label` 不区分大小写在原文中命中。只注入命中项，上限 30 条，以 `glossary` 数组放进 user message JSON。
- 管理端 WhatsApp 翻译页加一张说明卡指向字典管理。

### 2.3 运行时注入

user message JSON 字段：`direction`、`source_language`、`target_language`、`allowed_source_languages`（来自 constants，不写死在 prompt）、`glossary`、`text`。

### 2.4 响应合同

`TranslationModelOutput` / `TranslateResponse` 新增 `back_translation: str | None`（outgoing 必填非空，incoming 忽略）。扩展 `translation/outgoing` 运行时消息回传 `backTranslation`，`translation/incoming` 回传 `detectedSourceLanguage` 用于源语言标签。

## 三、边界不变

不新增权限、表、端点；不改配对/鉴权/额度/幂等；metadata 快照、不落正文的红线全部沿用。术语表条目本身不是聊天正文，可入库。

## 四、测试

后端：术语只注入命中项且不区分大小写、上限 30；outgoing 走新 preset 且缺 back_translation 判 `translation_invalid_response`；incoming 忽略 back_translation；升级函数只替换旧版原文；user message 含 allowed_source_languages。

扩展：聊天切换后 composer 目标语言来自 chat-language/get；预览→替换→恢复原文；输入框变化后恢复失效；Alt+T 两段式；enabled=false 时 incoming 不调 API 且不显示加载；错误码→文案映射；工具条挂在 footer 首子节点且群聊不挂；渲染源语言标签与中文文案；manifest 版本 1.1.0。

## 五、版本

扩展 1.0.3 → 1.1.0（manifest、package.json、manifest 测试同步）。后端最低扩展版本保持 1.0.0，旧扩展仍可用（响应多出的字段被忽略）。
