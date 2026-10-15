import { HttpsProxyAgent } from 'https-proxy-agent'
import { ProxyAgent } from 'undici'

// Apply only to WhatsApp traffic. Ark authorization must remain a direct,
// independently authenticated callback, including on office loopback.
function proxyUrl(env) {
  const value = (env.WHATSAPP_PROXY_URL || '').trim()
  if (!value) return undefined
  let url
  try { url = new URL(value) } catch { throw new Error('invalid_whatsapp_proxy_url') }
  if (!['http:', 'https:'].includes(url.protocol) || !url.hostname
    || url.pathname !== '/' || url.search || url.hash) throw new Error('invalid_whatsapp_proxy_url')
  return url
}

export function whatsappProxyAgent(env) {
  const url = proxyUrl(env)
  return url ? new HttpsProxyAgent(url) : undefined
}

export function whatsappProxyDispatcher(env) {
  const url = proxyUrl(env)
  return url ? new ProxyAgent({ uri: url.href, proxyTunnel: true }) : undefined
}
