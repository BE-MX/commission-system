import { statusDictionary } from '@/utils/status'

// 员工端门户列表状态字典：标签与语义色单点维护（DESIGN.md Status Badge & 状态字典）
export const ORDER_STATUS = statusDictionary([
  ['submitted', '待业务员审核', 'warning'],
  ['awaiting_customer', '待客户确认', 'primary'],
  ['ready_for_review', '待最终审核', 'warning'],
  ['invoice_created', '已生成 PI', 'success'],
  ['rejected', '已拒绝', 'danger'],
  ['cancelled', '已取消', 'info'],
])

export const ACCESS_STATUS = statusDictionary([
  ['draft', '待开通', 'info'],
  ['enabled', '已启用', 'success'],
  ['suspended', '已暂停', 'warning'],
  ['review_required', '身份待复核', 'danger'],
])

export const ACCESS_REQUEST_STATUS = statusDictionary([
  ['pending', '待审核', 'warning'],
  ['approved', '已批准', 'success'],
  ['rejected', '已拒绝', 'danger'],
  ['cancelled', '已取消', 'info'],
])

export const CATALOG_STATUS = statusDictionary([
  ['draft', '草稿', 'info'],
  ['published', '已发布', 'success'],
  ['disabled', '已下架', 'warning'],
])
