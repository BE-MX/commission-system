import { reactive } from 'vue'

// 身份即 token：无密码机制下「谁的浏览器 = 谁的身份」。
// 顶栏常显 + 一键切换是防呆设计（共用电脑会把操作记到错误的人头上）。
const TOKEN_KEY = 'pm_hub_token'
const NAME_KEY = 'pm_hub_display_name'
const USERNAME_KEY = 'pm_hub_username'

export const identity = reactive({
  token: localStorage.getItem(TOKEN_KEY) || '',
  displayName: localStorage.getItem(NAME_KEY) || '',
  username: localStorage.getItem(USERNAME_KEY) || '',

  signIn({ token, display_name, username }) {
    this.token = token
    this.displayName = display_name
    this.username = username
    localStorage.setItem(TOKEN_KEY, token)
    localStorage.setItem(NAME_KEY, display_name)
    localStorage.setItem(USERNAME_KEY, username)
  },

  signOut() {
    this.token = ''
    this.displayName = ''
    this.username = ''
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(NAME_KEY)
    localStorage.removeItem(USERNAME_KEY)
  },
})
