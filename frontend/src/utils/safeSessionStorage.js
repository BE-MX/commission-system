function defaultStorage() {
  try {
    return globalThis.sessionStorage ?? null
  } catch {
    return null
  }
}

export function readSessionItem(key, storage = defaultStorage()) {
  try {
    return storage?.getItem(key) ?? null
  } catch {
    return null
  }
}

export function writeSessionItem(key, value, storage = defaultStorage()) {
  try {
    storage?.setItem(key, String(value))
  } catch {
    // 浏览器策略禁用存储时保持内存态，不阻断当前页面。
  }
}

export function removeSessionItem(key, storage = defaultStorage()) {
  try {
    storage?.removeItem(key)
  } catch {
    // 注销流程不能因为浏览器存储不可用而中断。
  }
}
