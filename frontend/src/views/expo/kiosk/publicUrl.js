/**
 * 给**客户手机**扫的二维码用的 origin。
 *
 * 展位平板自己走 https 只是为了拿 secure context 开相机——IP 签不到 CA 证书，
 * 服务器挂的是自签证书，客户手机（尤其微信内置浏览器）根本不认，扫出来是白屏。
 * 所以 host 为裸 IP 时把链接降回 http；将来换成备案域名（正规证书）则保持 https。
 *
 * 抽成共享 helper 而非在各页复制：两份必然在换域名时漏改一份，而漏改的症状是
 * 「客户扫码白屏」，展位现场没人能定位。分享二维码与扫码上传两处共用。
 */
const IPV4_HOST = /^\d{1,3}(\.\d{1,3}){3}$/

export function publicOrigin() {
  // 只处理标准端口：带显式端口时无从推断对应的 http 端口，宁可原样不猜
  if (IPV4_HOST.test(location.hostname) && !location.port) {
    return `http://${location.hostname}`
  }
  return location.origin
}
