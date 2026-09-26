/* Install metadata must exist even before authentication redirects finish. */
(() => {
  const isScan = path => path.split(/[?#]/)[0].replace(/\/+$/, '') === '/shipping/scan'
  const isFx = path => path.split(/[?#]/)[0].replace(/\/+$/, '') === '/fx-settlement'
  const selector = '[data-standalone-app]'
  let activeApp
  let originalViewport
  function sync() {
    const url = new URL(window.location.href)
    const target = url.pathname === '/login' ? url.searchParams.get('redirect') || '' : url.pathname
    const app = isScan(target) ? { dir: 'shipping-app', title: '莱莎出库检验' } : isFx(target) ? { dir: 'fx-app', title: '结汇决策助手' } : null
    const enabled = !!app
    if (activeApp !== app?.dir) document.querySelectorAll(selector).forEach(node => node.remove())
    activeApp = app?.dir
    const viewport = document.querySelector('meta[name="viewport"]')
    if (!enabled) {
      document.querySelectorAll(selector).forEach(node => node.remove())
      if (originalViewport !== undefined && viewport) viewport.content = originalViewport
      return
    }
    document.title = app.title
    if (viewport) {
      if (originalViewport === undefined) originalViewport = viewport.content
      viewport.content = originalViewport + ', viewport-fit=cover'
    }
    if (document.querySelector(selector)) return
    const entries = [
      ['link', { rel: 'manifest', href: `/${app.dir}/manifest.webmanifest` }],
      ['link', { rel: 'apple-touch-icon', sizes: '180x180', href: `/${app.dir}/icon-180.png` }],
      ['meta', { name: 'apple-mobile-web-app-capable', content: 'yes' }],
      ['meta', { name: 'mobile-web-app-capable', content: 'yes' }],
      ['meta', { name: 'apple-mobile-web-app-title', content: app.title }],
      ['meta', { name: 'apple-mobile-web-app-status-bar-style', content: 'default' }],
      ['meta', { name: 'theme-color', content: '#f0f2f7' }],
    ]
    entries.forEach(([tag, attributes]) => {
      const node = document.createElement(tag)
      node.setAttribute('data-standalone-app', '')
      Object.entries(attributes).forEach(([key, value]) => node.setAttribute(key, value))
      document.head.appendChild(node)
    })
  }
  sync()
  window.addEventListener('ark:route-ready', sync)
  window.addEventListener('popstate', sync)
})()
