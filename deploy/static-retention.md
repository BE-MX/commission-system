# 主站前端资源保留与清理

统一入口 `deploy/deploy.bat` 在应用发布成功后自动清理主站前端。范围仅为办公室 `frontend/dist` 和 `.deploy_state/office-previous-frontend-<数字>`，以及 `platforms.json` 中两个 `component=frontend` 的云主站。PM、媒体、上传、数据库、源码工作树和构建缓存不在此次清理范围。

## 保留策略

- 当前版本与最近两份回滚备份保留完整自有文件清单；办公室最近成功发布引用的恢复备份也保护。
- 当前站点及两份回滚版本的 `assets/` 额外保留最近 7 天退役版本的资源。退役时刻取发布记录，不读取资源 mtime；窗口按连续 604800 秒计算，与服务器时区无关。
- 历史清单在版本目录删除后继续保存至窗口结束；过期元数据随清理淘汰。未激活候选单独保护，包括复用旧制品准备回滚的候选；切换时重新补齐当前页面资源。
- 云端旧版本没有可信退役记录，首次持久化保守的 7 天过渡窗口。期间保留旧版本各自完整制品，清掉目录内重复继承的历史 assets；在线资源由所有这些自有清单保护。窗口不随维护重跑续期，之后按真实退役记录清理。
- 办公室旧备份名中的纳秒时间代表退役时刻，自有清单通过原构建缓存的 index SHA 匹配，再逐项核对备份 SHA。无法唯一重建受保护清单时阻断；不得把累计 assets 扫描结果当成自有清单。

## 独立维护入口

从干净、已审查的固定候选执行，沿用安装目录的发布锁：

```powershell
& "$releaseRoot\.deploy_state\sources\$releaseRevision\deploy\deploy.bat" --live-root $releaseRoot --revision $releaseRevision --no-pull --static-retention-only --prepare-only
# 核对清单后，同一命令去掉 --prepare-only 才删除。
```

云端大规模维护单目标允许 1800 秒，普通静态发布仍为 300 秒；首次累计数十万资源的核验与清理可能持续数分钟。

该入口不发布应用代码、不重启服务、不运行迁移；要求最近应用发布 `publish-current.json.status=succeeded` 且无未完成 schema 恢复。它与其他专项参数互斥。维护清单重新在锁内计算，所有受保护摘要、冲突和删除树中的链接/Windows junction 核验后才执行；Windows 使用原生 PowerShell `Remove-Item -LiteralPath`，目标须严格位于指定目录内部。失败保留已完成目标，重跑可接续，不把旧回执冒充本轮完成。

回执：安装目录 `.deploy_state/static-retention-current.json`、`office-frontend-retention.json`；云端受管静态状态目录 `retention-current.json`。历史清单：`office-frontend-history.json` 和云端 `retention-history.json`。普通应用发布已经成功而后续维护失败时，应用成功状态保留并附 `static_retention_error`，部署进程仍返回非零；修复后使用独立维护入口，不必重新发布业务应用。

此机制由正式发布或独立维护命令触发，没有新增定时任务。停留超过窗口的旧标签页可能需要刷新后加载当前资源；7 天窗口内页面及保留回滚版本的自有文件继续可用。
