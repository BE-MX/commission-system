/** Recover an expired kiosk access token once before repeating the rejected request. */
export function createKioskAuthRecovery({ refreshToken, getAccessToken, onExpired }) {
  let refreshInFlight = null
  let expiredNotified = false
  let expiredToken = null

  function notifyExpired() {
    if (expiredNotified) return
    expiredNotified = true
    expiredToken = getAccessToken()
    onExpired()
  }

  return async (error, retry) => {
    const config = error.config
    if (error.response?.status !== 401 || !config?.recoverKioskAuth) throw error
    if (config._kioskAuthRetried) {
      notifyExpired()
      throw error
    }
    if (expiredNotified) {
      if (getAccessToken() === expiredToken) throw error
      expiredNotified = false
      expiredToken = null
    }

    if (!refreshInFlight) {
      refreshInFlight = Promise.resolve().then(refreshToken).finally(() => { refreshInFlight = null })
    }
    try {
      await refreshInFlight
    } catch (refreshError) {
      if (refreshError.response?.status === 401) notifyExpired()
      throw error
    }

    expiredNotified = false
    config._kioskAuthRetried = true
    return retry(config)
  }
}
