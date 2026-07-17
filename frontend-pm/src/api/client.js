// PM Hub 独立轻量 API 层：原生 fetch（不共用方舟 clients.js——两站两套鉴权，共用反而耦合）。
// 信封 {code,message,data} 在此统一解包；401 统一清身份回门牌；错误统一 toast。

import { identity } from '../stores/identity.js'
import { toast } from '../stores/toast.js'
import { router } from '../router/index.js'

async function request(path, { method = 'GET', body, formData, silent } = {}) {
  const headers = {}
  if (identity.token) headers.Authorization = `Bearer ${identity.token}`
  if (body !== undefined) headers['Content-Type'] = 'application/json'

  let resp
  try {
    resp = await fetch(path, {
      method,
      headers,
      body: formData ?? (body !== undefined ? JSON.stringify(body) : undefined),
    })
  } catch (err) {
    if (!silent) toast.error('网络异常，请检查连接后重试')
    throw err
  }

  if (resp.status === 401) {
    identity.signOut()
    if (router.currentRoute.value.name !== 'gate') {
      toast.error('验证已失效，请重新进入')
      router.push({ name: 'gate' })
    }
    const err = new Error('unauthorized')
    err.unauthorized = true
    throw err
  }

  let payload = null
  try {
    payload = await resp.json()
  } catch {
    // 非 JSON 响应（如 502 网关页）
  }

  if (!resp.ok) {
    const message = payload?.detail || payload?.message || `请求失败（${resp.status}）`
    if (!silent) toast.error(typeof message === 'string' ? message : '请求失败')
    const err = new Error(message)
    err.status = resp.status
    throw err
  }
  return payload?.data
}

export const api = {
  get: (path, opts) => request(path, opts),
  post: (path, body, opts) => request(path, { ...opts, method: 'POST', body }),
  put: (path, body, opts) => request(path, { ...opts, method: 'PUT', body }),
  del: (path, opts) => request(path, { ...opts, method: 'DELETE' }),
  postForm: (path, formData, opts) => request(path, { ...opts, method: 'POST', formData }),
}
