<template>
  <div class="quick-actions" :class="{ 'nav-open': open }" aria-label="出库单快捷操作">
    <button type="button" class="quick-action" aria-label="返回顶部" :disabled="open" @click="emit('top')"><Top /><span>顶部</span></button>
    <button type="button" class="quick-action" aria-label="刷新并保留当前位置" :disabled="open || refreshDisabled" @click="emit('refresh')"><Refresh /><span>刷新</span></button>
    <button ref="trigger" type="button" class="quick-action quick-action-primary" :class="{ active: open }" aria-label="明细导航" aria-haspopup="dialog" :aria-expanded="open" :disabled="!items.length" @click="toggle"><Grid /><span>明细</span></button>
  </div>
  <Transition name="quick-nav">
    <div v-if="open" class="quick-nav-layer">
      <button type="button" class="quick-nav-scrim" aria-label="关闭明细导航" tabindex="-1" @click="close" />
      <section ref="dialog" class="quick-nav-panel" role="dialog" aria-modal="true" aria-labelledby="quick-nav-title" @keydown="onDialogKeydown">
        <div class="quick-nav-head">
          <div><span class="quick-nav-eyebrow">本单产品</span><h2 id="quick-nav-title">明细导航 <small>{{ items.length }} 项</small></h2></div>
          <button ref="closeButton" type="button" class="quick-nav-close" aria-label="关闭明细导航" @click="close"><Close /></button>
        </div>
        <p class="quick-nav-hint">点击序号，直达对应产品明细</p>
        <div class="quick-nav-grid">
          <button v-for="(item, index) in items" :key="item.item_id" :ref="el => setNumberButton(el, index)" type="button" :class="{ current: index === activeIndex }" :aria-label="`跳转到第 ${index + 1} 项产品`" :aria-current="index === activeIndex ? 'location' : undefined" @click="select(index)">{{ String(index + 1).padStart(2, '0') }}</button>
        </div>
        <div class="quick-nav-foot"><span><i />当前浏览</span><span>序号与发货明细一致</span></div>
      </section>
    </div>
  </Transition>
</template>

<script setup>
import { nextTick, onBeforeUnmount, ref } from 'vue'
import { Top, Refresh, Grid, Close } from '@element-plus/icons-vue'

const props = defineProps({ items: { type: Array, required: true }, activeIndex: { type: Number, default: 0 }, refreshDisabled: Boolean })
const emit = defineEmits(['top', 'refresh', 'jump'])
const open = ref(false)
const trigger = ref(null)
const dialog = ref(null)
const closeButton = ref(null)
const numberButtons = []

function setNumberButton(element, index) { numberButtons[index] = element }
function close(restoreFocus = true) {
  open.value = false
  if (restoreFocus) nextTick(() => trigger.value?.focus({ preventScroll: true }))
}
async function toggle() {
  if (open.value) { close(); return }
  open.value = true
  await nextTick()
  const focusedButton = numberButtons[props.activeIndex] || closeButton.value
  focusedButton?.focus({ preventScroll: true })
}
function select(index) {
  close(false)
  emit('jump', index)
}
function onDialogKeydown(event) {
  if (event.key === 'Escape') { event.preventDefault(); close(); return }
  if (event.key !== 'Tab') return
  const controls = [...dialog.value.querySelectorAll('button')]
  const current = controls.indexOf(document.activeElement)
  const next = current + (event.shiftKey ? -1 : 1)
  if (next >= 0 && next < controls.length) return
  event.preventDefault()
  controls[next < 0 ? controls.length - 1 : 0].focus()
}
onBeforeUnmount(() => { open.value = false })
</script>

<style scoped>
.quick-actions{position:fixed;z-index:20;right:max(16px,calc((100vw - 580px)/2 + 16px));bottom:calc(24px + env(safe-area-inset-bottom));display:flex;flex-direction:column;gap:10px}
.quick-actions.nav-open{z-index:22}
.quick-actions.nav-open .quick-action:not(.active){visibility:hidden}
.quick-action{width:54px;height:58px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:3px;border:1px solid var(--border-color);border-radius:17px;background:color-mix(in srgb,var(--card-bg) 90%,transparent);color:var(--text-secondary);box-shadow:0 5px 18px color-mix(in srgb,var(--text-primary) 14%,transparent);backdrop-filter:blur(12px);font:inherit;cursor:pointer;transition:transform 120ms cubic-bezier(.23,1,.32,1)}
.quick-action svg{width:22px;height:22px}
.quick-action span{font-size:10px;font-weight:650;line-height:1.3}
.quick-action-primary{background:var(--text-primary);border-color:var(--text-primary);color:var(--color-gold)}
.quick-action-primary.active{background:var(--color-primary);border-color:var(--color-primary);color:var(--card-bg)}
.quick-action:active{transform:scale(.96)}
.quick-action:disabled{opacity:.5;cursor:not-allowed}
.quick-nav-layer{position:fixed;inset:0;z-index:21}
.quick-nav-scrim{position:absolute;inset:0;width:100%;border:0;background:color-mix(in srgb,var(--text-primary) 12%,transparent);cursor:default}
.quick-nav-panel{box-sizing:border-box;position:absolute;right:max(16px,calc((100vw - 580px)/2 + 16px));bottom:calc(104px + env(safe-area-inset-bottom));width:min(350px,calc(100vw - 32px));max-height:calc(100dvh - 165px - env(safe-area-inset-top));overflow-y:auto;padding:20px;border:1px solid var(--card-bg);border-radius:24px;background:color-mix(in srgb,var(--card-bg) 90%,transparent);backdrop-filter:blur(16px);box-shadow:0 16px 45px color-mix(in srgb,var(--text-primary) 16%,transparent);transform-origin:bottom right;transition:transform 180ms cubic-bezier(.23,1,.32,1)}
.quick-nav-head{display:flex;justify-content:space-between;align-items:center}
.quick-nav-eyebrow{display:block;margin-bottom:6px;color:var(--color-primary-hover);font-size:10px;font-weight:700;letter-spacing:2px}
.quick-nav-head h2{margin:0;font-size:20px;font-weight:750}
.quick-nav-head small{margin-left:5px;color:var(--text-secondary);font-size:11px;font-weight:400}
.quick-nav-close{width:44px;height:44px;display:grid;place-items:center;border:1px solid var(--border-color);border-radius:50%;background:var(--page-bg);color:var(--text-secondary);cursor:pointer}
.quick-nav-close svg{width:18px;height:18px}
.quick-nav-hint{margin:14px 0 18px;color:var(--text-secondary);font-size:12px}
.quick-nav-grid{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:8px}
.quick-nav-grid button{min-height:46px;border:1px solid var(--border-color);border-radius:11px;background:color-mix(in srgb,var(--card-bg) 85%,transparent);color:var(--text-primary);font-size:16px;font-weight:650;font-variant-numeric:tabular-nums;cursor:pointer}
.quick-nav-grid button.current{background:var(--color-primary);border-color:var(--color-primary);color:var(--card-bg);box-shadow:0 3px 8px var(--color-primary-glow)}
.quick-nav-foot{display:flex;align-items:center;justify-content:space-between;margin-top:18px;padding-top:14px;border-top:1px solid var(--border-color);color:var(--text-secondary);font-size:10px}
.quick-nav-foot span:first-child{display:flex;align-items:center;gap:6px}
.quick-nav-foot i{width:7px;height:7px;border-radius:50%;background:var(--color-primary)}
.quick-nav-enter-active{transition:opacity 180ms cubic-bezier(.23,1,.32,1)}
.quick-nav-leave-active{transition:opacity 120ms cubic-bezier(.23,1,.32,1)}
.quick-nav-enter-from,.quick-nav-leave-to{opacity:0}
.quick-nav-enter-from .quick-nav-panel,.quick-nav-leave-to .quick-nav-panel{transform:translateY(6px) scale(.97)}
@media(max-width:360px){.quick-nav-panel{padding:16px}
.quick-nav-grid{gap:6px}}
@media(prefers-reduced-motion:reduce){.quick-action,.quick-nav-panel,.quick-nav-enter-active,.quick-nav-leave-active{transition:none}
.quick-action:active{transform:none}}
</style>
