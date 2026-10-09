import { createApp } from 'vue'
import App from './App.vue'
import './styles/tokens.css'
import './styles/app.css'

// Invitation secrets never remain in browser history, referrers or UI links.
const url = new URL(window.location.href)
const invitation = url.pathname === '/activate'
  ? new URLSearchParams(url.hash.slice(1)).get('token') || url.searchParams.get('token') || '' : ''
if (url.pathname === '/activate') history.replaceState(null, '', '/activate')
createApp(App, { invitation }).mount('#app')
