# Veronika 第三批撤销完成

用户于2026-10-26明确授权撤销 `2026.Veronika赊销1002-03`、释放39件与USD1,387.79商品款占用，保留原USD121.16运费及抵扣，供重新创建批次。本次未新建出库单、未修改原回款或部署新代码。

## 事实与执行范围

- 固定对象：invoice981、settlement8、outbound7、远端105885151780989、镜像93778。原单12:14:14生成，13:06:00经方舟PC端账号刘源删除；删除审计12800记录成功并核实。删除前10行39件与冻结任务完全一致；当前ID详情保留空行，编号查询无结果，两次完整有效列表均不含原ID。
- 商品毛额USD1,545.09，冻结报价扣除价差抵扣USD157.30后，实际占用商品回款USD1,387.79。本次仅释放应用13/14/15：receipt1062 USD412.00、receipt1086 USD38.00、receipt1385 USD937.79。
- 原运费归属已撤销的settlement7，目标freight7 / remote105878936774347，USD121.16及应用12继续保留。本批quote沿用settlement7，本批没有独立运费目标；取消本批后原运费可再次沿用。
- 办公室维护SSH不可达，北京后端核实HEAD为已发布d6e56d82、backend/app无差异、schema204。使用同部署器的backend.lock和共享库存执行器DB锁，先preview、再重新核验固定图后单次apply；system actor0，未模拟用户登录。写入前保留SHA256业务快照与独占apply-intent；无小满业务POST。
- 独立agent审查固定脚本和读回脚本未见具体阻断；实际preview与授权范围一致后执行，随后用新进程独立读取。

## 完成证据

- settlement8 state=`cancelled`，version41→42；outbound7 status=`cancelled`，原编号、远端ID、冻结payload、明细基线和历史错误保留。
- 应用13/14/15仅status改为released，合计USD1,387.79；10行39件的原明细与报价不改，终态解除数量占用。
- 四笔原回款1062/1086/1385/1405业务字段、第一批、原第二批及其运费和应用9–12均与执行前一致。
- active batch阻塞为空；replacement_freight_settlement_id=7；有效预付款池可用USD1,865.54；39件可重新选入新批，保留运费可继续沿用。未凭此结果推断后续新批的数量、价格或资金需求。
- cancel_deleted业务事件与shipment_create_cancelled不可变审计各一条，actor0。原删除审计保留。

原始证据：北京 `/home/ubuntu/commission-system/.deploy_state/veronika-03-cancel-20261026/`；本机 `D:/MyProgram/commission-system/tmp/veronika-03-diagnosis-20261026/operation-evidence/`。包含脚本、fresh-before及SHA256、fresh-preview、apply-intent、apply-receipt、independent-readback。维护已完成，禁止重跑apply；如需查询仅独立读回。
