/**
 * 悬浮横向滚动条指令（宽表规范，见 DESIGN.md「List Page Spec」第 1 节）。
 *
 *   <el-table v-sticky-scrollbar :data="rows">...</el-table>
 *
 * 表格底边滚出视口时，把与表体同步 scrollLeft 的横向滚动条固定在视口底部，
 * 消灭“先滚到底、拖滚动条、再滚回去”的宽表痛点。
 * 原生滚动条可见（表底在视口内）或无横向溢出时自动隐藏，小表格零影响。
 * 特殊表格可显式 v-sticky-scrollbar="false" 关闭，需在 code review 说明理由。
 */
const BAR_HEIGHT = 12
const REFRESH_MS = 300

function getScrollWrap(el) {
  return el.querySelector('.el-table__body-wrapper .el-scrollbar__wrap')
}

export const vStickyScrollbar = {
  mounted(el, binding) {
    if (binding.value === false) return

    const bar = document.createElement('div')
    bar.className = 'v-sticky-scrollbar'
    const inner = document.createElement('div')
    inner.style.height = '1px'
    bar.appendChild(inner)
    bar.style.display = 'none'
    document.body.appendChild(bar)

    const update = () => {
      const wrap = getScrollWrap(el)
      const rect = el.getBoundingClientRect()
      const visible =
        Boolean(wrap) &&
        el.isConnected &&
        wrap.scrollWidth > wrap.clientWidth + 1 && // 确实有横向溢出
        rect.top < window.innerHeight - BAR_HEIGHT && // 表格已进入视口
        rect.bottom > window.innerHeight // 原生滚动条（表格底边）在视口外
      if (!visible) {
        bar.style.display = 'none'
        return
      }
      inner.style.width = `${wrap.scrollWidth}px`
      bar.style.left = `${rect.left}px`
      bar.style.width = `${rect.width}px`
      bar.style.display = ''
      if (bar.scrollLeft !== wrap.scrollLeft) bar.scrollLeft = wrap.scrollLeft
    }

    let ticking = false
    const scheduleUpdate = () => {
      if (ticking) return
      ticking = true
      requestAnimationFrame(() => {
        ticking = false
        update()
      })
    }

    // 等值判断防循环：bar → wrap 赋值回触发 wrap scroll，值已相等即不再回写
    const syncFromBar = () => {
      const wrap = getScrollWrap(el)
      if (wrap && wrap.scrollLeft !== bar.scrollLeft) wrap.scrollLeft = bar.scrollLeft
    }

    bar.addEventListener('scroll', syncFromBar, { passive: true })
    // scroll 事件不冒泡，捕获阶段一次接住页面、布局容器与表体的滚动
    document.addEventListener('scroll', scheduleUpdate, true)
    window.addEventListener('resize', scheduleUpdate)
    // 列宽/数据变化只改内容宽度，不触发布局滚动，ResizeObserver 兜底
    const ro = new ResizeObserver(scheduleUpdate)
    ro.observe(el)
    const content = el.querySelector('.el-table__body-wrapper .el-scrollbar__view')
    if (content) ro.observe(content)
    // 纯位置变化（keep-alive 换页、上方插入元素）不产生任何事件，显示期间低频校正
    const timer = setInterval(() => {
      if (bar.style.display !== 'none' || !el.isConnected) update()
    }, REFRESH_MS)

    el.__vStickyScrollbar = { bar, syncFromBar, scheduleUpdate, ro, timer }
  },

  unmounted(el) {
    const ctx = el.__vStickyScrollbar
    if (!ctx) return
    clearInterval(ctx.timer)
    ctx.bar.removeEventListener('scroll', ctx.syncFromBar)
    document.removeEventListener('scroll', ctx.scheduleUpdate, true)
    window.removeEventListener('resize', ctx.scheduleUpdate)
    ctx.ro.disconnect()
    ctx.bar.remove()
    delete el.__vStickyScrollbar
  },
}

export function registerStickyScrollbarDirective(app) {
  app.directive('sticky-scrollbar', vStickyScrollbar)
}
