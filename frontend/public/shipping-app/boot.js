/* Install metadata must exist even before authentication redirects finish. */
(() => {
  const isScan = path => path.split(/[?#]/)[0].replace(/\/+$/, '') === '/shipping/scan'
  const selector = '[data-shipping-app]'
  let originalViewport
  function sync() {
    const url = new URL(window.location.href)
    const enabled = isScan(url.pathname) || (url.pathname === '/login' && isScan(url.searchParams.get('redirect') || ''))
    const viewport = document.querySelector('meta[name="viewport"]')
    if (!enabled) {
      document.querySelectorAll(selector).forEach(node => node.remove())
      if (originalViewport !== undefined && viewport) viewport.content = originalViewport
      return
    }
    document.title = '莱莎出库检验'
    if (viewport) {
      if (originalViewport === undefined) originalViewport = viewport.content
      viewport.content = originalViewport + ', viewport-fit=cover'
    }
    if (document.querySelector(selector)) return
    const entries = [
      ['link', { rel: 'manifest', href: '/shipping-app/manifest.webmanifest' }],
      ['link', { rel: 'apple-touch-icon', sizes: '180x180', href: '/shipping-app/icon-180.png' }],
      ['meta', { name: 'apple-mobile-web-app-capable', content: 'yes' }],
      ['meta', { name: 'mobile-web-app-capable', content: 'yes' }],
      ['meta', { name: 'apple-mobile-web-app-title', content: '莱莎出库检验' }],
      ['meta', { name: 'apple-mobile-web-app-status-bar-style', content: 'default' }],
      ['meta', { name: 'theme-color', content: '#f0f2f7' }],
    ]
    entries.forEach(([tag, attributes]) => {
      const node = document.createElement(tag)
      node.setAttribute('data-shipping-app', '')
      Object.entries(attributes).forEach(([key, value]) => node.setAttribute(key, value))
      document.head.appendChild(node)
    })
  }
  sync()
  window.addEventListener('ark:route-ready', sync)
  window.addEventListener('popstate', sync)
})()
