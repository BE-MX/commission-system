import { reactive } from 'vue'

// 极简 toast：<UiToast/> 挂一次，任何模块 toast.success/error 调用（Sonner 原则：接入零摩擦）
let seq = 0

export const toastStore = reactive({ items: [] })

function push(kind, message, duration = 3200) {
  const id = ++seq
  toastStore.items.push({ id, kind, message })
  setTimeout(() => {
    const i = toastStore.items.findIndex((t) => t.id === id)
    if (i !== -1) toastStore.items.splice(i, 1)
  }, duration)
}

export const toast = {
  success: (msg) => push('success', msg),
  error: (msg) => push('error', msg, 4200),
  info: (msg) => push('info', msg),
}
