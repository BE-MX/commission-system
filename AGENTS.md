# AGENTS.md — 多智能体 Git 协作约定（codex / kimi / claude 通用）

本仓库由多个 AI 编码代理并行开发（Claude Code / Codex / Kimi Code），各自工作在独立 git worktree。完整项目规范见同目录 `CLAUDE.md`（宪法）与 `.claude/rules/checklists.md`；本文件只放跨代理必须共同遵守的 Git 约定，与 CLAUDE.md「多智能体并行 Git」条目同步维护。

## Worktree 与分支

- 每个代理固定在自己的 worktree 工作，**禁止在别的代理的目录里 commit**；worktree 归属以其检出分支的 `<tool>/` 前缀为准，目录名不作准：
  - `commission-system`（主目录）= Claude Code，**merge 回 main 只能在这里做**
  - `commission-system-kimi` = Kimi Code
  - 其余 `commission-system-*` = 按任务临时创建，用完 `git worktree remove` 清理
- 分支命名 `<tool>/<topic>`：`claude/...`、`codex/...`、`kimi/...`
- commit 前先 `git branch --show-current` 确认当前分支——`.git/HEAD` 等引用是全 worktree 共享的，别的代理可能刚动过（2026-07-14 提交落错分支实翻车，见 .wolf/cerebrum.md）

## 推送与合并

- 分支创建当天 `git push -u origin <branch>`，此后有提交随时 push——**feature 分支的 push 是备份，不是发布**，不需要等指令
- **main 的 push 只有亮哥明确说了才执行**
- 合并回 main 只在主 worktree 做；合并后立即删除本地与远端分支
- 零散小改动不开新分支，顺手带在当前任务分支里
- 同一模块同一时间只允许一个代理改；确需接力，后来者先 rebase 最新 main，且当天合并不过夜
- 存疑的旧分支不直接删：打 `archive/<name>-<date>` tag 推远端后再删分支

## Alembic 迁移

- 建迁移前先查**所有分支**的最新编号：`git log --all --oneline -- backend/alembic/versions/`——两个代理各建同号迁移，合并后 alembic multiple heads 直接报错（2026-07-17 实翻车）

## 巡检

- 收工前跑 `python scripts/git_sweep.py`（`--open` 打开 HTML 看板）；每日 18:00 定时任务自动巡检，有欠账推钉钉告警群
