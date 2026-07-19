<template>
  <!-- 已删版本且无历史评论：整块隐藏，不给死入口 -->
  <div v-if="failed || canPost || flatCount" class="vc">
    <!-- 加载失败：不渲染「0 条评论」谎报空态，给重试入口 -->
    <button v-if="failed" class="vc-toggle failed" type="button" @click="emit('retry')">
      <span class="vc-mark" aria-hidden="true">❞</span>
      <span>评论加载失败 · 点击重试</span>
    </button>
    <button v-else class="vc-toggle" type="button" :aria-expanded="expanded" @click="expanded = !expanded">
      <span class="vc-mark" aria-hidden="true">❞</span>
      <span>{{ flatCount ? `${flatCount} 条评论` : '评论' }}</span>
      <svg class="vc-chevron" :class="{ open: expanded }" viewBox="0 0 12 12" width="10" height="10" aria-hidden="true">
        <path d="M3 4.5l3 3 3-3" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/>
      </svg>
    </button>

    <Transition name="fade">
      <div v-if="expanded && !failed" class="vc-body">
        <div v-if="threads.length" class="vc-list">
          <article v-for="c in threads" :key="c.id" class="vc-item">
            <p v-if="c.is_deleted" class="vc-deleted">该评论已被作者删除</p>
            <template v-else>
              <header class="vc-head">
                <span class="vc-author">{{ nameOf(c.author) }}</span>
                <time class="vc-time mono">{{ relTime(c.created_at) }}</time>
                <span class="vc-spacer"></span>
                <button v-if="canPost" class="btn-bare" type="button" @click="startReply(c.id)">回复</button>
                <button v-if="c.author === identity.username" class="btn-bare danger" type="button" @click="deleting = c">删除</button>
              </header>
              <p class="vc-text">{{ c.body }}</p>
            </template>

            <div v-if="c.replies.length" class="vc-replies">
              <article v-for="r in c.replies" :key="r.id" class="vc-reply">
                <header class="vc-head">
                  <span class="vc-author">{{ nameOf(r.author) }}</span>
                  <time class="vc-time mono">{{ relTime(r.created_at) }}</time>
                  <span class="vc-spacer"></span>
                  <button v-if="canPost" class="btn-bare" type="button" @click="startReply(c.id)">回复</button>
                  <button v-if="r.author === identity.username" class="btn-bare danger" type="button" @click="deleting = r">删除</button>
                </header>
                <p class="vc-text">{{ r.body }}</p>
              </article>
            </div>

            <div v-if="replyingTo === c.id" class="vc-composer">
              <textarea
                ref="replyInput"
                v-model="replyDraft"
                class="textarea"
                rows="2"
                maxlength="2000"
                placeholder="回复这条评论…"
                @keydown.ctrl.enter="submit(c.id)"
                @keydown.meta.enter="submit(c.id)"
                @keydown.esc="cancelReply"
              ></textarea>
              <div class="vc-composer-foot">
                <button class="btn btn-sm btn-ghost" type="button" @click="cancelReply">取消</button>
                <button class="btn btn-sm btn-accent" type="button" :disabled="!replyDraft.trim() || posting" @click="submit(c.id)">回复</button>
              </div>
            </div>
          </article>
        </div>

        <div v-if="canPost" class="vc-composer vc-composer-new">
          <textarea
            v-model="draft"
            class="textarea"
            rows="2"
            maxlength="2000"
            :placeholder="`针对 v${version.version_no} 的意见或说明…`"
            @keydown.ctrl.enter="submit()"
            @keydown.meta.enter="submit()"
          ></textarea>
          <div class="vc-composer-foot">
            <span class="vc-hint">Ctrl + Enter 发布</span>
            <button class="btn btn-sm btn-accent" type="button" :disabled="!draft.trim() || posting" @click="submit()">
              {{ posting ? '发布中…' : '发布评论' }}
            </button>
          </div>
        </div>
      </div>
    </Transition>

    <UiModal
      :model-value="!!deleting"
      title="删除评论"
      message="确定删除这条评论？删除后不再显示，操作留痕。"
      confirm-text="删除"
      danger
      @update:model-value="deleting = null"
      @confirm="onDelete"
    />
  </div>
</template>

<script setup>
import { computed, nextTick, ref } from 'vue'
import { createComment, deleteComment } from '../api/index.js'
import { identity } from '../stores/identity.js'
import { toast } from '../stores/toast.js'
import { relTime } from '../utils/labels.js'
import UiModal from './UiModal.vue'

const props = defineProps({
  version: { type: Object, required: true },
  threads: { type: Array, default: () => [] }, // 本版本的顶层评论（含 replies），父组件按版本分好
  nameOf: { type: Function, default: (u) => u },
  canPost: { type: Boolean, default: true }, // 已删版本 false：历史可看，不可新增
  failed: { type: Boolean, default: false }, // 评论拉取失败：显示重试入口，不谎报空态
})
const emit = defineEmits(['changed', 'retry'])

const expanded = ref(false)
const posting = ref(false)
const draft = ref('')
const replyDraft = ref('')
const replyingTo = ref(null)
const replyInput = ref(null)
const deleting = ref(null)

// 与后端 comment_count 同口径：活顶层 + 活回复，占位不计
const flatCount = computed(() =>
  props.threads.reduce((n, c) => n + (c.is_deleted ? 0 : 1) + c.replies.length, 0),
)

async function submit(parentId = null) {
  const body = (parentId ? replyDraft : draft).value.trim()
  if (!body || posting.value) return
  posting.value = true
  try {
    await createComment(props.version.id, { body, parent_id: parentId })
    if (parentId) cancelReply()
    else draft.value = ''
    toast.success(parentId ? '已回复' : '已发布评论')
    emit('changed')
  } catch {
    /* client.js 已统一 toast */
  } finally {
    posting.value = false
  }
}

function startReply(topId) {
  replyingTo.value = topId
  replyDraft.value = ''
  nextTick(() => {
    const el = Array.isArray(replyInput.value) ? replyInput.value[0] : replyInput.value
    el?.focus()
  })
}

function cancelReply() {
  replyingTo.value = null
  replyDraft.value = ''
}

async function onDelete() {
  const target = deleting.value
  deleting.value = null
  if (!target) return
  try {
    await deleteComment(target.id)
    toast.success('已删除评论')
    emit('changed')
  } catch {
    /* client.js 已统一 toast */
  }
}
</script>

<style scoped>
.vc {
  margin-top: 12px;
  border-top: 1px solid var(--hairline);
  padding-top: 10px;
}
.vc-toggle {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  font-size: 12px;
  color: var(--ink-3);
  padding: 2px 4px;
  transition: color var(--dur-fast) var(--ease-out);
}
.vc-toggle:active { transform: scale(0.97); }
@media (hover: hover) and (pointer: fine) {
  .vc-toggle:hover { color: var(--gold-deep); }
}
.vc-mark { color: var(--gold-deep); font-size: 13px; }
.vc-toggle.failed { color: var(--danger); }
.vc-chevron { transition: transform var(--dur-fast) var(--ease-out); }
.vc-chevron.open { transform: rotate(180deg); }

.vc-body { margin-top: 10px; }
.vc-list { display: flex; flex-direction: column; gap: 12px; margin-bottom: 12px; }
.vc-item {
  background: var(--paper);
  border: 1px solid var(--hairline);
  border-radius: var(--radius);
  padding: 10px 13px;
}
.vc-head { display: flex; align-items: center; gap: 9px; flex-wrap: wrap; }
.vc-author { font-size: 12.5px; font-weight: 600; color: var(--ink); }
.vc-time { font-size: 11px; color: var(--ink-4); }
.vc-spacer { flex: 1; }
.vc-text {
  margin-top: 5px;
  font-family: var(--font-serif);
  font-size: 13px;
  line-height: 1.75;
  color: var(--ink-2);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.vc-deleted { font-size: 12px; color: var(--ink-4); font-style: italic; }

.btn-bare {
  font-size: 11.5px;
  color: var(--ink-3);
  padding: 2px 4px;
  transition: color var(--dur-fast) var(--ease-out);
}
.btn-bare:active { transform: scale(0.96); }
@media (hover: hover) and (pointer: fine) {
  .btn-bare:hover { color: var(--gold-deep); }
  .btn-bare.danger:hover { color: var(--danger); }
}

.vc-replies {
  margin-top: 10px;
  border-left: 2px solid var(--hairline-strong);
  padding-left: 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.vc-composer { margin-top: 10px; }
.vc-composer .textarea { width: 100%; border-color: var(--hairline); background: var(--paper); font-size: 13px; }
.vc-composer-foot {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 8px;
}
.vc-hint { font-size: 11px; color: var(--ink-4); margin-right: auto; }
.vc-composer-new { margin-top: 0; }
</style>
