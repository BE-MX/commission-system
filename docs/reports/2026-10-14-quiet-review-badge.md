# 内贸待审核角标静默刷新

侧边栏的待审核数量原先每 30 秒查询一次，请求只关闭错误提示，没有关闭共享请求拦截器的全屏加载。因此停留在其他业务标签页时，也会周期性出现全屏「正在加载」。这是后台角标查询触发的遮罩；本轮未对线上网络进行抓包。

## 修改行为

- `getCustomerRequestPendingCount` 强制使用 `showLoading: false`、`suppressToast: true`，并传递取消信号；普通查询、保存等操作的全局加载规则不变。
- 兜底轮询改为 60 秒。隐藏的浏览器页面不查询；恢复可见和窗口 focus 事件在 100 毫秒内合并；同一时刻只保留一个查询。
- 审核等成功操作仍立即刷新；若旧查询未完成，则合并为结束后的一次补查，避免丢掉操作后的更新。
- 网络失败或无效返回保留上一次确认的数量，记录控制台诊断，不清零。首次尚无结果使用 `null`，隐藏数字角标，并提供「待审核数量暂未获取」的无障碍标签。确认数量为 0 时正常隐藏角标。
- 退出组件、切换账号、权限变化时取消旧请求，并用版本号防止迟到结果覆盖新身份。

本次只调整内贸待审核角标；单据异常角标及公告轮询没有改动。没有改变审核、资金或权限业务规则。

## 验证

在 `frontend` 执行：

```text
node --experimental-vm-modules --test tests/domesticReviewBadge.test.mjs tests/requestResponse.test.mjs tests/navigationLayout.test.mjs tests/domesticCustomerControls.test.mjs
npm run build
```

- 34 项 Node 回归通过。修复前角标测试 10 项失败、1 项通过，覆盖频率、静默配置、失败保留数量、并发去重及取消缺失；新增权限撤回与隐藏页面的边界测试也通过。
- 完整生产构建通过，仍有现有体积及混合导入提示。构建生成的后端导航清单仅有换行差异，已恢复，不纳入本次修改。
- 本地真实 Edge 验证 8 个场景通过：模拟两分钟轮询不出现遮罩、focus/visibility 合并、慢查询无重叠、成功操作触发补查、失败及无效结果保留数量、零值隐藏、手动请求保留加载反馈、组件退出取消传输与轮询。使用真实 composable/API/拦截器/GlobalLoading 和生产侧栏角标模板，身份为本地替身，业务接口全部拦截，共 10 次待审核查询、0 次真实业务 API 请求。本地脚本及结果保留在 `frontend/tmp/review-badge-validation/`。
- `python scripts/check_conventions.py` 与 `git diff --check` 通过。Git 巡检使用 `--no-fetch`，仅代表本地快照。
- 扩大检查发现 `requestAuthRace.test.mjs` 的旧测试替身缺少 `@/utils/feedback` 导入。对未经修改的 `HEAD` 源码运行同一鉴权用例，也在导入阶段失败；该文件及其被测鉴权实现没有修改。没有把这组检查报告为通过。

用户已追加授权提交、合并 main 并推送 origin，Git 交付以远端回读为准。未部署，没有修改生产业务数据。合并时保留主目录已有未提交工作，交接文档备份与内容校验记录保存在主目录 `tmp/quiet-review-badge-integration-20261014/`。
