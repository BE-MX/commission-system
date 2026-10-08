import { resolveStatus } from '@/utils/status'
const statuses = {
  synced: {label:'已同步',type:'success'}, sync_failed:{label:'同步失败',type:'danger'}, sync_uncertain:{label:'同步结果待核对',type:'warning'},
  not_synced:{label:'未同步'}, pending:{label:'等待处理'}, running:{label:'正在处理'}, done:{label:'生成任务已完成'},
  failed:{label:'失败',type:'danger'}, uncertain:{label:'待核对',type:'warning'}, retrying:{label:'等待自动重试'}, skipped:{label:'已跳过'},
  waiting_target:{label:'等待目标'}, waiting_stock:{label:'库存不足',type:'warning'}, shipped:{label:'已确认出库',type:'success'}, generated:{label:'已生成 · 待出库'},
  awaiting_payment:{label:'等待回款'}, awaiting_verification:{label:'等待核验'}, outbound_uncertain:{label:'出库待核对',type:'warning'},
  review_required:{label:'待人工核对',type:'warning'}, recheck_required:{label:'待重新验货',type:'warning'},
  cancelled:{label:'已取消'}, cancel_pending:{label:'取消处理中',type:'warning'}, paused:{label:'已暂停'},
  draft:{label:'草稿'}, ready:{label:'待出库'}, outbound_pending:{label:'出库处理中'}, completed:{label:'已完成',type:'success'}, active:{label:'活动记录'}, voided:{label:'已作废'},
  syncing:{label:'同步中'}, remote_deleted:{label:'远端删除已核实'}, sync_pending:{label:'待同步'}, sync_sending:{label:'同步中'},
  delete_pending:{label:'删除核验中'}, delete_uncertain:{label:'删除结果待核对',type:'warning'}, delete_failed:{label:'删除失败',type:'danger'}, deleted:{label:'已删除'},
}
export const detailStatus = value => resolveStatus(value, statuses)
export const orderTypeLabel = value => ({stock:'库存单',production:'生产单',presale:'预售单'}[value] || value || '—')
export const purposeLabel = value => ({ordinary:'订单款',presale_deposit:'预付款',presale_goods:'批次商品款',freight:'独立运费'}[value] || value || '订单款')
