/**
 * 内贸域列表页列显隐配置（TableTools 数据源，List Page Spec 第 9 节）。
 * fixed 左列与操作列不进配置；key 与表格列上的 visibleKeys.includes('<key>') 一一对应。
 */
export const ordersColumnDefs = [
  { key: 'customer_source', label: '客户来源' },
  { key: 'order_kind', label: '订单大类' },
  { key: 'order_date', label: '下单日期' },
  { key: 'owner', label: '归属销售' },
  { key: 'order_type', label: '订单类型' },
  { key: 'order_channel', label: '订单渠道' },
  { key: 'total_qty', label: '产品总数' },
  { key: 'status', label: '订单状态' },
  { key: 'required_ship_date', label: '要求交付日期' },
  { key: 'actual_ship_date', label: '实际交付日期' },
  { key: 'last_order_date', label: '上次下单日期' },
  { key: 'repurchase_cycle', label: '复购周期/天' },
  { key: 'remark', label: '订单备注' },
]

export const customersColumnDefs = [
  { key: 'custom_code', label: '客户编码' },
  { key: 'customer_level', label: '客户等级' },
  { key: 'lifecycle_status', label: '客户状态' },
  { key: 'owner', label: '归属销售' },
  { key: 'customer_source', label: '客户来源' },
  { key: 'store_type', label: '门店类型' },
  { key: 'membership', label: '会员等级' },
  { key: 'last_recharge', label: '最近充值' },
  { key: 'last_recharged_at', label: '最近充值时间' },
  { key: 'region', label: '省 / 市' },
  { key: 'contact', label: '联系人' },
  { key: 'phone', label: '电话' },
  { key: 'totals', label: '累计订单 / 销售额' },
  { key: 'order_count', label: '订单数' },
  { key: 'settle_mode', label: '结算方式' },
  { key: 'balance', label: '充值余额' },
  { key: 'status', label: '状态' },
]

export const customerRequestsColumnDefs = [
  { key: 'created_at', label: '申请时间' },
  { key: 'type', label: '类型' },
  { key: 'customer', label: '客户' },
  { key: 'amount', label: '金额/调整' },
  { key: 'membership', label: '会员等级' },
  { key: 'remark', label: '申请说明' },
  { key: 'voucher', label: '凭证' },
  { key: 'created_by', label: '申请人' },
  { key: 'status', label: '状态' },
  { key: 'review', label: '审核信息' },
]

export const productsColumnDefs = [
  { key: 'name', label: '产品' },
  { key: 'product_type', label: '类型' },
  { key: 'craft', label: '工艺/尺寸' },
  { key: 'length', label: '发长' },
  { key: 'net_color', label: '网帽颜色' },
  { key: 'size', label: '头套尺码' },
  { key: 'density', label: '发量' },
  { key: 'hair_style_series', label: '发型系列' },
  { key: 'original_price', label: '原始价' },
  { key: 'price_status', label: '价格状态' },
  { key: 'route', label: '工艺路线' },
  { key: 'use_count', label: '下单次数' },
]
