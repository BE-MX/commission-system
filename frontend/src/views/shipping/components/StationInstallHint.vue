<template>
  <details v-if="!standalone" class="install-hint">
    <summary><img src="/shipping-app/icon-180.png" alt="" width="32" height="32" /><span>添加「出库检验」到手机桌面</span><span class="install-action">安装指引</span></summary>
    <div class="install-body">
      <p v-if="embedded">请先在 Safari 或 Chrome 中打开本页，再添加到主屏幕。</p>
      <ol v-else-if="ios">
        <li>点浏览器的<strong>分享</strong>按钮（方框向上箭头）。</li>
        <li>选择<strong>添加到主屏幕</strong>；没看到时，向下滑动分享菜单查找。</li>
        <li>名称设为<strong>莱莎出库检验</strong>。如有“作为 Web App 打开”，请开启，再点“添加”。</li>
      </ol>
      <ol v-else>
        <li>打开浏览器菜单，选择<strong>安装应用</strong>或<strong>添加到主屏幕</strong>。</li>
        <li>确认名称，完成后从桌面的出库检验图标打开。</li>
      </ol>
      <p>首次从桌面打开可能需要重新登录专用账号；每单仍需选择实际操作人。上传时请保持页面打开。</p>
    </div>
  </details>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount } from 'vue'
const display = window.matchMedia('(display-mode: standalone)')
const standalone = ref(display.matches || navigator.standalone === true)
const ios = /iPhone|iPad|iPod/i.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1)
const embedded = /MicroMessenger|DingTalk/i.test(navigator.userAgent)
const update = () => { standalone.value = display.matches || navigator.standalone === true }
const installed = () => { standalone.value = true }
onMounted(() => {
  display.addEventListener('change', update)
  window.addEventListener('appinstalled', installed)
})
onBeforeUnmount(() => {
  display.removeEventListener('change', update)
  window.removeEventListener('appinstalled', installed)
})
</script>

<style scoped>
.install-hint{border:1px solid var(--border-color);border-radius:12px;background:var(--card-bg);margin-bottom:16px}
summary{display:flex;align-items:center;gap:8px;min-height:48px;padding:4px 10px;cursor:pointer;list-style:none;font-size:12px;font-weight:650}
summary::-webkit-details-marker{display:none}summary img{border-radius:7px;flex-shrink:0}.install-action{margin-left:auto;color:var(--color-primary-hover);white-space:nowrap;font-size:11px}
.install-body{border-top:1px solid var(--border-color);padding:0 14px 8px;font-size:13px;line-height:1.8;color:var(--text-secondary)}ol{padding-left:20px}li{margin:8px 0}strong{color:var(--text-primary)}
summary:focus-visible{outline:3px solid var(--color-primary);outline-offset:3px;border-radius:12px}
</style>
