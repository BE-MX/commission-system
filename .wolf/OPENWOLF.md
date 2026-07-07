# OpenWolf Operating Protocol（2026-07-03 精简版）

> 原全量协议（anatomy 查表 / memory 流水 / buglog 记录 / designqc / reframe）已于
> 2026-07-03 治理收敛（依据 docs/2026-07-03-architecture-assessment.md G-2）：
> anatomy.md 覆盖失效（59/300+ 文件，hits: 0）、memory.md 1800+ 行流水无人回读、
> buglog.json 与 cerebrum Do-Not-Repeat 重复。三者停用，保留唯一有效资产 cerebrum。

本项目现行的记忆规则只有两条：

1. **生成代码前读 `.wolf/cerebrum.md`**，遵守其中 User Preferences / Key Learnings / Do-Not-Repeat / Decision Log 的每一条。
2. **被用户纠正、踩到新坑、做出重要技术决策时，立即更新 cerebrum**（条目带日期 YYYY-MM-DD）。门槛放低：疑似有用就记。

模块级知识（"某模块怎么回事"）写 auto-memory（`~/.claude/projects/.../memory/project_*.md`），不进 cerebrum——cerebrum 只放教训与决策。

停用文件的处置：`anatomy.md` / `memory.md` / `buglog.json` 保留在仓库作历史存档，不再读写；有价值的 buglog 条目已并入 cerebrum Do-Not-Repeat。
