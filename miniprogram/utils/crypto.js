// utils/crypto.js — HMAC 签名校验（预留，扫码本地校验用）

/**
 * 简单签名校验
 * 注：小程序端不暴露密钥，实际签名校验由后端完成
 */
export function verifySign(orderProductId, sign) {
  // 签名校验由后端 /api/mini/scan/product 完成
  return true
}
