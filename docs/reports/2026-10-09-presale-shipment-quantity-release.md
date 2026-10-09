# 预售出库数量提示修复发布记录

## 范围与版本

- 亮哥授权合并、推送、部署。应用候选 `526eee6c95abbc20c4cfee49f4a7ce6531e1e2e0`，仅修改出库弹窗、回归脚本与相关交接文档；主目录原 24 项未提交内容已逐项核验保留。
- 本地复现空批次核算后的数量提示未随有效输入清除。现在仅清除此特定过期提示；已有授权、报价、原提交恢复错误保持原语义。数量和运费变化继续使旧报价失效。
- “核算本批金额”移到弹窗底部，长订单能直接找到必要步骤。未改变后端数量、资金、实际出库确认或幂等契约，无新数据库迁移。

## 验证

- 真实 Vue / Element Plus 与主站全局表格配置；旧代码的“填写后清提示”断言实际失败。修复后 1440×900、390×900 六行模拟订单通过，覆盖空批次、运费修改、正数输入、排序后编辑、加减按钮、报价失效、全归零与最终提交商品 ID/数量；无真实出库或回款写入。
- 相关 Node 回归 37 passed；前端生产构建、覆盖提交范围的 `check_conventions.py --base aa598924` 与差异检查通过。独立 agent 最终审查无新增 P1/P2。
- 构建保留已有大 chunk、auth 混合导入警告；生产预检已有 colour 缺可选 Matplotlib 提示，不影响本次通过。

## 发布结果

- 通过办公室 `D:/commission-system/deploy/deploy.bat --revision 526eee6c95abbc20c4cfee49f4a7ce6531e1e2e0 --no-pull`，先加 `--prepare-only` 预检后正式发布，两阶段退出 0。正式输出 `MANAGED APPLICATION RELEASE COMPLETED`。
- Release ID `7bbd402bff7a4d0180c49e96ed61a81e`；scope `office-and-cloud`，deferred 为空；数据库保持 `178_account_unlock`，无 DDL。
- 办公室 HEAD 为候选、工作区干净，健康 ok/connected。北京后端按无 backend/config 差异规则保留实际 `cf25fc1f315dede61ca7ab4e3f1ec9dcc2702d61`，已现场核验这两个目录与候选无差异，健康 ok/connected；未为了对齐提交号强制更新未变化服务。
- `leshine.work`、`leshine.cloud` 共 10 项公网入口、主资源及 `InvoiceManage` JS/CSS SHA-256 均与办公室候选一致，订单页面制品包含数量提示与底部核算入口。验证没有创建真实业务单据。
- 两地主站静态制品为 `8de37678ac46a5d968d771d7821719784314f214f81f0b1a6d971d824cda4c28`；PM 与客户素材未变化并通过核验。正式阶段复用预检上传制品，新增传输 0 字节。
- 北京出库轮询器回执 verified、legacy 模式，原 active/enabled timer 基线恢复；邮件 Worker 原 inactive/disabled、MainPID=0 保留。未登记活跃目标和其他独立服务依发布清单保留原边界。
- 原主目录快照、原 handoff、两阶段发布日志、健康回执及公网摘要证据保存在主目录 `.deploy_state/presale-shipment-release/`。Git 巡检使用 `--no-fetch`，仅本地快照；未清理他人的分支或改动。
