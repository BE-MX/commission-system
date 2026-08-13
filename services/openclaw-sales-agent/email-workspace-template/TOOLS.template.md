# Email outreach tools

只允许使用只读的方舟 lead 工具，以及下列待发队列命令：

技能正文按 OpenClaw 的要求先读取，但只能通过只读、realpath 校验的 reader 使用下列标识。每次草拟读取主 Skill、course-methods 与 localization-and-timing；只有价格回复才读 negotiation，只有进入邮件操作时才读 agently-mail：

```text
{{OUTREACH_SKILL_READER_BIN}} outreach
{{OUTREACH_SKILL_READER_BIN}} course
{{OUTREACH_SKILL_READER_BIN}} localization
{{OUTREACH_SKILL_READER_BIN}} negotiation
{{OUTREACH_SKILL_READER_BIN}} agent-mail
```

```text
{{OUTREACH_QUEUE_BIN}} preview --company-id <id> --contact-id <id> --research-id <id> --lead-updated-at <lead updated_at> --email-status valid --language-evidence-url <Ark source URL> --to <email> --subject <subject> --body <body> --country <ISO2> --timezone <IANA> --language <BCP47> --language-source <recipient|company|country> --language-basis <evidence> [--state <subdivision>] [--office-start HH:MM]
{{OUTREACH_QUEUE_BIN}} schedule --country <ISO2> --timezone <IANA> --language <BCP47> --language-source <recipient|company|country> --language-basis <evidence> [--state <subdivision>] [--office-start HH:MM]
{{OUTREACH_QUEUE_BIN}} list
```

`schedule` 只计算时间，不写入队列。`preview` 返回供人工审核的完整摘要和短期令牌。展示后必须停止本轮。`confirm` 故意不在本 Agent 权限内；用户下一轮明确批准后，由 OpenClaw 的人工 exec 审批界面运行原令牌，队列还会重新读取 Ark 并核对公司、联系人、邮箱有效状态、研究版本和语言证据。单独的 dispatcher 也不提供给本 Agent。
