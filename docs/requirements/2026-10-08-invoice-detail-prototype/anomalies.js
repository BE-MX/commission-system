// Read-only status projection shared by invoice labels and the navigation overview.
// Normal waiting states and missing read access are not business exceptions.
const anomalyDomains = [
  {key:'order',label:'订单异常'},
  {key:'outbound',label:'出库单异常'},
  {key:'receipt',label:'回款异常'},
];
const abnormalStates = new Set([
  'sync_failed','sync_uncertain','failed','uncertain','review_required','outbound_uncertain',
  '同步失败','同步结果待核对','待核对','生成失败','结果待核对','待人工核对',
]);
function documentAnomalies(order) {
  const result = [];
  const add = (domain, messages) => { if(messages.length) result.push({...domain,messages}); };
  const issue = (row, fields) => fields.map(field=>row[field]).filter(value=>abnormalStates.has(value));
  if(order.permissions?.order !== false) add(anomalyDomains[0],issue(order,['sync','sync_status','status']));
  if(!order.restricted && order.permissions?.outbound !== false) {
    add(anomalyDomains[1],order.outbounds.flatMap(row=>issue(row,['state','status','sync_status','outbound_state']).map(state=>`${row.number||row.settlement||row.batch}：${state}`)));
  }
  if(!order.restricted && order.permissions?.receipt !== false) {
    add(anomalyDomains[2],order.receipts.filter(row=>!row.status||row.status==='active').flatMap(row=>issue(row,['sync','sync_status']).map(state=>`${row.number}：${state}`)));
  }
  return result;
}
