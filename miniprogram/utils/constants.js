// utils/constants.js — 常量定义

// 二维码数据格式: ARK-P:{order_product_id}:{sign}
export const QR_PREFIX = 'ARK-P:'

// block_reason → 用户提示映射
export const BLOCK_MESSAGES = {
  SIGN_INVALID: '二维码无效，请重新扫描',
  ORDER_PRODUCT_NOT_FOUND: '找不到该产品记录，请联系管理员',
  PROCESS_ALREADY_DONE: '该工序已完成',
  NOT_YOUR_PROCESS: '您负责的不是该工序',
  NOT_ASSIGNED: '您未被分配此工序，请联系管理员'
}

// 页面状态
export const STATE = {
  IDLE: 'idle',
  SCANNING: 'scanning',
  VALIDATING: 'validating',
  SHOWING_CONFIRM: 'showing-confirm',
  SUBMITTING: 'submitting'
}
