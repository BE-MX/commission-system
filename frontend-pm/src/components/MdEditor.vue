<template>
  <Teleport to="body">
    <transition name="ed" appear>
      <div class="ed-root" role="dialog" aria-label="在线编辑">
        <header class="ed-head">
          <div class="ed-title-wrap">
            <span class="ed-eyebrow mono">EDIT · 基于 v{{ baseVersion.version_no }}</span>
            <h2 class="ed-title">{{ material.name }}</h2>
          </div>
          <div class="ed-toggle" role="tablist" aria-label="视图切换">
            <button
              v-for="[key, label] in [['edit', '编辑'], ['preview', '预览']]"
              :key="key"
              class="ed-toggle-btn"
              :class="{ on: pane === key }"
              type="button"
              @click="pane = key"
            >{{ label }}</button>
          </div>
          <div class="ed-actions">
            <input
              v-model.trim="note"
              class="input ed-note"
              type="text"
              placeholder="修改说明（选填，一句话）"
              maxlength="200"
            />
            <button class="btn" type="button" :disabled="busy" @click="requestClose">取消</button>
            <button class="btn btn-accent" type="button" :disabled="busy || !canSave" @click="requestSave">
              <span v-if="busy" class="spinner"></span>{{ busy ? '保存中…' : '保存为新版本' }}
            </button>
          </div>
        </header>

        <div v-if="loading" class="ed-loading"><span class="spinner"></span></div>
        <div v-else-if="!loaded" class="ed-loading"><p class="ed-load-fail">原文加载失败——关闭后重试</p></div>
        <div v-else class="ed-body" :class="`show-${pane}`">
          <textarea
            ref="srcEl"
            v-model="content"
            class="ed-src mono"
            spellcheck="false"
            @keydown="onKeydown"
          ></textarea>
          <div class="ed-preview">
            <MarkdownView v-if="isMd" :source="content" />
            <pre v-else class="ed-plain mono">{{ content }}</pre>
          </div>
        </div>

        <footer class="ed-foot">
          <span class="ed-hint">保存即另存为新版本（自动 +1，永不覆盖），AI 将自动对比生成差异概要。</span>
          <span class="ed-state num">{{ content.length }} 字符<template v-if="dirty"> · 未保存</template></span>
        </footer>
      </div>
    </transition>

    <UiModal
      :model-value="conflictHead !== null"
      title="有更新的版本"
      :message="`你编辑期间，已有人保存了 v${conflictHead}。继续保存会把你基于 v${baseVersion.version_no} 的修改另存为更新的版本，不会覆盖任何人的内容。`"
      confirm-text="继续保存"
      cancel-text="返回编辑"
      @update:model-value="conflictHead = null"
      @confirm="confirmConflictSave"
    />
    <UiModal
      v-model="discardConfirm"
      title="放弃修改"
      message="编辑内容尚未保存，关闭后将丢失。"
      confirm-text="放弃并关闭"
      cancel-text="继续编辑"
      danger
      @confirm="emit('close')"
    />
  </Teleport>
</template>

<script setup>
import { computed, nextTick, onMounted, ref } from 'vue'
import MarkdownView from './MarkdownView.vue'
import UiModal from './UiModal.vue'
import { fetchFileLink, fetchMaterial, saveTextVersion } from '../api/index.js'
import { toast } from '../stores/toast.js'

const props = defineProps({
  material: { type: Object, required: true },
  baseVersion: { type: Object, required: true },
  headVersionNo: { type: Number, default: null }, // 打开编辑器时的当前版本号（冲突判定基线）
})
const emit = defineEmits(['close', 'saved'])

const loading = ref(true)
const loaded = ref(false)
const busy = ref(false)
const content = ref('')
const originalContent = ref('')
const note = ref('')
const pane = ref('edit') // 窄屏用；宽屏 CSS 恒双栏
const conflictHead = ref(null)
const discardConfirm = ref(false)
const srcEl = ref(null)

const isMd = computed(() => ['.md', '.markdown'].includes(props.baseVersion.ext))
const dirty = computed(() => content.value !== originalContent.value)
const canSave = computed(() => loaded.value && dirty.value && !!content.value.trim())

onMounted(async () => {
  try {
    // 签名 URL 直取原文（与 PreviewModal 同款路径）；原生 fetch 无拦截器，这里自己兜错
    const link = await fetchFileLink(props.baseVersion.id, 'inline')
    const resp = await fetch(link.url)
    if (!resp.ok) throw new Error(`load ${resp.status}`)
    originalContent.value = await resp.text()
    content.value = originalContent.value
    loaded.value = true
    await nextTick()
    srcEl.value?.focus()
  } catch {
    toast.error('原文加载失败，请关闭后重试')
  } finally {
    loading.value = false
  }
})

function latestNo(materialDetail) {
  const alive = (materialDetail?.versions || []).filter((v) => !v.is_deleted)
  return alive.length ? Math.max(...alive.map((v) => v.version_no)) : null
}

async function requestSave() {
  if (busy.value || !canSave.value) return
  busy.value = true
  try {
    const fresh = await fetchMaterial(props.material.id)
    const freshHead = latestNo(fresh)
    if (freshHead !== props.headVersionNo) {
      conflictHead.value = freshHead // 交由冲突弹窗决定（§6.1：提示后用户自行选择）
      return
    }
    await doSave()
  } catch { /* 拦截器已统一提示 */ }
  finally {
    busy.value = false
  }
}

async function confirmConflictSave() {
  conflictHead.value = null
  busy.value = true
  try {
    await doSave()
  } catch { /* 拦截器已统一提示 */ }
  finally {
    busy.value = false
  }
}

async function doSave() {
  const v = await saveTextVersion(props.material.id, {
    content: content.value,
    change_note: note.value || undefined,
    base_version_no: props.baseVersion.version_no,
  })
  toast.success(`已保存 v${v.version_no}，AI 差异概要生成中`)
  emit('saved')
  emit('close')
}

function requestClose() {
  if (busy.value) return
  if (dirty.value) {
    discardConfirm.value = true
    return
  }
  emit('close')
}

function onKeydown(e) {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
    e.preventDefault()
    requestSave()
    return
  }
  if (e.key === 'Tab' && !e.shiftKey) {
    e.preventDefault()
    const el = e.target
    const start = el.selectionStart
    content.value = `${content.value.slice(0, start)}  ${content.value.slice(el.selectionEnd)}`
    nextTick(() => { el.selectionStart = el.selectionEnd = start + 2 })
  }
}
</script>

<style scoped>
.ed-root {
  position: fixed;
  inset: 0;
  z-index: 830; /* 压过抽屉(800)，让位确认弹窗(850) */
  display: flex;
  flex-direction: column;
  background: var(--paper);
}

/* ── 头部 ── */
.ed-head {
  display: flex;
  align-items: center;
  gap: 18px;
  padding: 14px 22px;
  border-bottom: 1px solid var(--hairline-strong);
}
.ed-eyebrow { display: block; font-size: 11px; letter-spacing: 0.08em; color: var(--ink-4); }
.ed-title {
  font-family: var(--font-serif);
  font-size: 17px;
  line-height: 1.3;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 32vw;
}
.ed-actions { display: flex; align-items: center; gap: 10px; margin-left: auto; }
.ed-note { width: 240px; }

/* ── 编辑/预览 双栏 ── */
.ed-body {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: 1fr 1fr;
}
.ed-src {
  border: none;
  border-right: 1px solid var(--hairline);
  outline: none;
  resize: none;
  padding: 26px 30px;
  background: var(--paper-sunken);
  color: var(--ink);
  font-size: 13.5px;
  line-height: 1.8;
  tab-size: 2;
}
.ed-preview { overflow-y: auto; padding: 26px 34px; }
.ed-plain { white-space: pre-wrap; word-break: break-word; font-size: 13px; line-height: 1.8; color: var(--ink-2); }

/* ── 底栏 ── */
.ed-foot {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  padding: 9px 22px;
  border-top: 1px solid var(--hairline);
  font-size: 12px;
  color: var(--ink-4);
}
.ed-state { flex-shrink: 0; }

.ed-loading { flex: 1; display: flex; align-items: center; justify-content: center; }
.ed-load-fail { font-size: 13px; color: var(--ink-3); }

/* ── 窄屏：单栏 + 切换 ── */
.ed-toggle { display: none; }
@media (max-width: 880px) {
  .ed-head { flex-wrap: wrap; gap: 10px; padding: 12px 16px; }
  .ed-title { max-width: 60vw; }
  .ed-note { display: none; } /* 窄屏收掉说明输入，聚焦编辑本身 */
  .ed-toggle {
    display: inline-flex;
    border: 1px solid var(--hairline-strong);
    border-radius: var(--radius);
    overflow: hidden;
  }
  .ed-toggle-btn {
    border: none;
    background: transparent;
    padding: 5px 14px;
    font-size: 12px;
    color: var(--ink-3);
    cursor: pointer;
    transition: background var(--dur-fast) var(--ease-out), color var(--dur-fast) var(--ease-out);
  }
  .ed-toggle-btn.on { background: var(--ink); color: var(--paper); }
  .ed-body { grid-template-columns: 1fr; }
  .ed-body.show-edit .ed-preview { display: none; }
  .ed-body.show-preview .ed-src { display: none; }
  .ed-src { border-right: none; }
}

/* ── 进出场：整页接管，入场稳重、退场干脆 ── */
.ed-enter-active { transition: opacity var(--dur-med) var(--ease-out), transform var(--dur-med) var(--ease-out); }
.ed-leave-active { transition: opacity var(--dur-fast) ease; }
.ed-enter-from { opacity: 0; transform: translateY(10px); }
.ed-leave-to { opacity: 0; }

@media (prefers-reduced-motion: reduce) {
  .ed-enter-from { transform: none; }
}
</style>
