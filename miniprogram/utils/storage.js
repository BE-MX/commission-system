// utils/storage.js — 本地存储封装

const TOKEN_KEY = 'ark_token'
const USER_KEY = 'ark_user'

export function getToken() {
  return wx.getStorageSync(TOKEN_KEY) || ''
}

export function setToken(token) {
  wx.setStorageSync(TOKEN_KEY, token)
}

export function getUser() {
  return wx.getStorageSync(USER_KEY) || null
}

export function setUser(user) {
  wx.setStorageSync(USER_KEY, user)
}

export function clearAuth() {
  wx.removeStorageSync(TOKEN_KEY)
  wx.removeStorageSync(USER_KEY)
}
