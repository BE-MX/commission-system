# WhatsApp 话术真实模型基线（2026-09-07）

结论：发现并修复 JSON 输出模式遗漏；当前尚未通过完整上线验收。修复后定向复测 14 条，11 条返回建议、3 条被安全规则拦截；耗时高于目标。不能宣称 30 条语义质量已通过。

## 授权与执行边界

亮哥明确授权 30 条合成对话、最多 60 次付费模型调用。本轮实际 **59 次、103,410 tokens**（API 用量），未追加调用。使用当前 `deepseek-v4-flash`、OpenAI 协议、`thinking.type=disabled`、`temperature=0.1`，planner/generator 分别限制 1,400/1,800 输出 token。

所有对话及知识均为原创合成数据。只读获取现有 provider 配置，所有测试设备、知识、请求占位和 AI 日志均在内存 SQLite；实际请求经过 `reply_service → app.ai.service.chat`。未保存模型正文、草稿或原始响应，未写生产知识/权限/模型配置，未迁移、推送或部署。

| 批次 | 场景数 | 调用数 | tokens | 结果 |
| --- | ---: | ---: | ---: | --- |
| 初始完整基线 | 30 | 30 | 50,905 | 全部在 planner 结构校验失败，未进入生成，不能算完整回复耗时 |
| 最小结构诊断 | 1 | 1 | 1,659 | ReplyPlan 为 935 字符、非纯 JSON、带 Markdown 围栏；未输出正文 |
| JSON mode 修复后产品咨询 | 2 | 4 | 7,333 | 英语、德语均 ready |
| 修复后风险与策略场景 | 12 | 24 | 43,513 | 9 条返回建议、3 条安全拦截，无自动重试 |

原预设只通过提示词要求 JSON，未启用 API JSON mode。现独立话术 OpenAI 预设默认增加 `response_format={"type":"json_object"}`，测试和正式 bootstrap 共用参数构造；不继承翻译专用 schema，不覆盖已有管理员配置，Anthropic 不注入 OpenAI 参数。严格 JSON/schema/安全校验均未放宽。[DeepSeek 官方说明](https://api-docs.deepseek.com/guides/json_mode/)要求设置输出模式并在提示词中要求 JSON。新增 seed 回归先在旧实现失败，修复后通过；独立审查通过。

## 修复后的端到端结果

| 合成用例 | 状态 | 耗时（秒） |
| --- | --- | ---: |
| en-product | ready | 7.781 |
| de-product | ready | 10.687 |
| de-price_comparison | needs_confirmation | 11.079 |
| en-sample_fee | reply_unsafe_response | 8.718 |
| de-sample_fee | needs_confirmation | 9.125 |
| en-sample_conflict | reply_unsafe_response | 8.063 |
| de-sample_conflict | needs_confirmation | 9.062 |
| en-old_delivery | needs_confirmation | 11.969 |
| de-old_delivery | reply_unsafe_response | 12.563 |
| en-aftersales | needs_confirmation | 8.765 |
| de-aftersales | needs_confirmation | 18.688 |
| en-alternative | ready | 16.687 |
| en-refusal | ready | 7.266 |
| de-refusal | ready | 6.172 |

合计 5 ready、6 needs_confirmation、3 拦截；返回建议比例 **11/14（78.6%）**，不是业务“直接可用率”或原 30 条完整通过率。安全拦截不会返回可填入草稿；因未保存正文，不能判断三个拦截各自是真正不安全还是措辞误拦，不能当作“严重语义错误为 0”的证明。

全 14 条中位数 **9.094 秒**、P95 **18.688 秒**（nearest-rank，小样本），高于 ≤8 秒/≤15 秒目标。11 条返回建议样本中位数 9.125 秒、P95 18.688 秒；未剔除慢例美化结果。

## 未通过项与后续边界

- 修复后余下 16 条尚未复测；修复前的 planner 失败不是完整回复验收。
- 三类拦截需区分正确拒绝与误拦。已补测试专用规则类别诊断（contact/link/商业内部词/动态时间/财务承诺），不打印命中文本，本轮未为此追加调用。
- 性能目标未达到，应根据阶段耗时和输出长度优化，不能取消知识/权限/安全校验。
- 业务负责人语义盲评、真实 WhatsApp 1.3.0 冒烟、已批准真实知识召回和供应商保留策略核验仍待完成。

本轮修复后的相关离线回归为 **271 passed, 1 skipped**（29.10 秒；常规测试默认跳过付费项），增量约定检查无违规。这些绿色结果不抵消上述真实模型未通过项。

新增实际模型复测需另行取得额度授权。本轮剩余 1 次不足一条正常两阶段验证，未使用。当前不建议开放试用或上线。
