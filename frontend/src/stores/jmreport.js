/**
 * 积木报表 token Pinia store。
 * 缓存 token 与 jmreport_url，提前 5 分钟刷新避免 iframe 中途掉线。
 */
import { defineStore } from 'pinia'
import { getReportToken } from '@/api/jmreport'

export const useJmReportStore = defineStore('jmreport', {
  state: () => ({
    token: null,
    jmreportUrl: '',
    expireAt: null,
    loading: false,
    error: null,
  }),

  getters: {
    isTokenValid: (state) => {
      if (!state.token || !state.expireAt) return false
      return new Date() < new Date(state.expireAt)
    },
    // jimureport 2.3.4 的设计器/工作台入口是 /jmreport/list（不是 /index）
    designerUrl: (state) => {
      if (!state.token || !state.jmreportUrl) return ''
      return `${state.jmreportUrl}/list?token=${state.token}`
    },
    getReportUrl: (state) => (reportCode) => {
      if (!state.token || !state.jmreportUrl) return ''
      if (!reportCode) return `${state.jmreportUrl}/list?token=${state.token}`
      const code = encodeURIComponent(reportCode)
      // 单报表查看路径走 view（jimureport 内部 hash 路由）
      return `${state.jmreportUrl}/view/${code}?token=${state.token}`
    },
  },

  actions: {
    async fetchToken(force = false) {
      if (!force && this.isTokenValid) return this.token

      this.loading = true
      this.error = null
      try {
        const res = await getReportToken()
        this.token = res.token
        this.jmreportUrl = res.jmreport_url
        // expire_in 提前 5 分钟过期，避免 iframe 用着用着失效
        this.expireAt = new Date(Date.now() + (res.expire_in - 300) * 1000)
        return this.token
      } catch (err) {
        this.error = err?.message || '获取报表凭证失败'
        throw err
      } finally {
        this.loading = false
      }
    },
    clearToken() {
      this.token = null
      this.expireAt = null
      this.jmreportUrl = ''
    },
  },
})
