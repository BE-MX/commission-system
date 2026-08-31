# Email outreach tools

客户事实只允许通过方舟统一客户只读工具获取；邮件操作只允许使用下列待发队列命令：

技能正文按 OpenClaw 的要求先读取，但只能通过只读、realpath 校验的 reader 使用下列标识。每次草拟读取主 Skill、course-methods 与 localization-and-timing；只有价格回复才读 negotiation，只有进入邮件操作时才读 agently-mail：

```text
{{OUTREACH_SKILL_READER_BIN}} outreach
{{OUTREACH_SKILL_READER_BIN}} course
{{OUTREACH_SKILL_READER_BIN}} localization
{{OUTREACH_SKILL_READER_BIN}} negotiation
{{OUTREACH_SKILL_READER_BIN}} agent-mail
```

```text
{{OUTREACH_QUEUE_BIN}} preview --customer-id <id> --contact-id <id> --contact-point-id <id> --profile-version-id <id> --fact-ids <id,id> --evidence-ids <id,id> --email-status valid --language-evidence-url <Ark source URL> --to <email> --subject <subject> --body <body> --country <ISO2> --timezone <IANA> --language <BCP47> --language-source <recipient|company|country> --language-basis <evidence> [--state <subdivision>] [--office-start HH:MM]
{{OUTREACH_QUEUE_BIN}} schedule --country <ISO2> --timezone <IANA> --language <BCP47> --language-source <recipient|company|country> --language-basis <evidence> [--state <subdivision>] [--office-start HH:MM]
{{OUTREACH_QUEUE_BIN}} list
```

`schedule` 只计算时间，不写入队列。`preview` 返回供人工审核的完整摘要和短期令牌。展示后必须停止本轮。`confirm` 在本 Agent 内硬拒绝且不会弹出可持久授权的 exec 审批；用户下一轮明确批准后，只展示 `{{OUTREACH_QUEUE_BIN}} confirm --token <原令牌>`，由用户或其他可信本机操作者在 Agent 之外运行。命令会重新读取 Ark 并核对客户、档案版本、联系人、抑制状态、邮箱有效状态、事实与信源证据及语言证据。单独的 dispatcher 也不提供给本 Agent。
