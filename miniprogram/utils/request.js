// utils/request.js — 统一请求封装

const app = getApp()

/**
 * 统一请求
 * @param {object} options
 * @param {string} options.url        - 接口路径（不含 baseUrl）
 * @param {'GET'|'POST'|'PUT'|'DELETE'} [options.method='GET']
 * @param {object} [options.data]     - 请求体
 * @param {boolean} [options.noAuth]  - 跳过鉴权 header
 * @returns {Promise<any>}
 */
function request(options) {
  return new Promise((resolve, reject) => {
    const header = { 'Content-Type': 'application/json' }

    if (!options.noAuth && app.globalData.token) {
      header['Authorization'] = 'Bearer ' + app.globalData.token
    }

    wx.request({
      url: app.globalData.baseUrl + options.url,
      method: options.method || 'GET',
      data: options.data,
      header,
      timeout: options.timeout || 30000,
      success(res) {
        if (res.statusCode === 401) {
          app.logout()
          reject({ statusCode: 401, detail: { code: 'TOKEN_EXPIRED', message: '登录已过期' } })
          return
        }
        if (res.statusCode >= 400) {
          reject({
            statusCode: res.statusCode,
            detail: res.data?.detail || { code: 'UNKNOWN_ERROR', message: '请求失败' }
          })
          return
        }
        resolve(res.data)
      },
      fail(err) {
        wx.showToast({ title: '网络连接失败', icon: 'error' })
        reject(err)
      }
    })
  })
}

export default request
