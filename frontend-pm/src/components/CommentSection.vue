<template>
  <section class="cmt" aria-label="资料评论">
    <h2 class="cmt-title">评论<span v-if="flatCount" class="cmt-count mono">{{ flatCount }}</span></h2>

    <!-- 发布框 -->
    <div class="cmt-composer">
      <textarea
        v-model="draft"
        class="textarea"
        rows="3"
        maxlength="2000"
        placeholder="针对这份资料的意见、缺口或补充说明…"
        @keydown.ctrl.enter="submit()"
        @keydown.meta.enter="submit()"
      ></textarea>
      <div class="cmt-composer-foot">
        <span class="cmt-hint">Ctrl + Enter 发布 · 支持单层回复</span>
        <button class="btn btn-accent btn-sm" type="button" :disabled="!draft.trim() || posting" @click="submit()">
          {{ posting ? '发布中…' : '发布评论' }}
        </button>
      </div>
    </div>

    <div v-if="loading" class="cmt-loading"><span class="spinner"></span></div>

    <p v-else-if="loadFailed" class="cmt-empty">
      评论加载失败。<button class="btn-bare retry" type="button" @click="reload">重试</button>
    </p>

    <p v-else-if="!comments.length" class="cmt-empty">还没有评论——第一条意见从这里开始。</p>

    <TransitionGroup v-else name="fade" tag="div" class="cmt-list">
      <article v-for="c in comments" :key="c.id" class="cmt-item">
        <p v-if="c.is_deleted" class="cmt-deleted">该评论已被作者删除</p>
        <template v-else>
          <header class="cmt-head">
            <span class="cmt-author">{{ nameOf(c.author) }}</span>
            <span v-if="c.version_no" class="cmt-ver mono">v{{ c.version_no }} 时</span>
            <time class="cmt-time mono">{{ relTime(c.created_at) }}</time>
            <span class="cmt-spacer"></span>
            <button class="btn-bare" type="button" @click="startReply(c.id)">回复</button>
            <button v-if="c.author === identity.username" class="btn-bare danger" type="button" @click="deleting = c">删除</button>
          </header>
          <p class="cmt-body">{{ c.body }}</p>
        </template>

        <!-- 回复（单层） -->
        <div v-if="c.replies.length" class="cmt-replies">
          <article v-for="r in c.replies" :key="r.id" class="cmt-reply">
            <header class="cmt-head">
              <span class="cmt-author">{{ nameOf(r.author) }}</span>
              <time class="cmt-time mono">{{ relTime(r.created_at) }}</time>
              <span class="cmt-spacer"></span>
              <button class="btn-bare" type="button" @click="startReply(c.id)">回复</button>
              <button v-if="r.author === identity.username" class="btn-bare danger" type="button" @click="deleting = r">删除</button>
            </header>
            <p class="cmt-body">{{ r.body }}</p>
          </article>
        </div>

        <!-- 行内回复框（同时只开一个） -->
        <div v-if="replyingTo === c.id" class="cmt-reply-box">
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
          <div class="cmt-composer-foot">
            <button class="btn btn-sm btn-ghost" type="button" @click="cancelReply">取消</button>
            <button class="btn btn-sm btn-accent" type="button" :disabled="!replyDraft.trim() || posting" @click="submit(c.id)">回复</button>
          </div>
        </div>
      </article>
    </TransitionGroup>

    <UiModal
      :model-value="!!deleting"
      title="删除评论"
      message="确定删除这条评论？删除后不再显示，操作留痕。"
      confirm-text="删除"
      danger
      @update:model-value="deleting = null"
      @confirm="onDelete"
    />
  </section>
</template>

<script setup>
import { computed, nextTick, onMounted, ref } from 'vue'
import { createComment, deleteComment, fetchComments } from '../api/index.js'
import { identity } from '../stores/identity.js'
import { toast } from '../stores/toast.js'
import { relTime } from '../utils/labels.js'
import UiModal from './UiModal.vue'

const props = defineProps({
  materialId: { type: [Number, String], required: true },
  nameOf: { type: Function, default: (u) => u },
})

const comments = ref([])
const loading = ref(true)
const loadFailed = ref(false)
const posting = ref(false)
const draft = ref('')
const replyDraft = ref('')
const replyingTo = ref(null)
const replyInput = ref(null)
const deleting = ref(null)

// 计数含回复、不含删除占位（与后端 comment_count 同口径）
const flatCount = computed(() =>
  comments.value.reduce((n, c) => n + (c.is_deleted ? 0 : 1) + c.replies.length, 0),
)

async function load() {
  try {
    comments.value = (await fetchComments(props.materialId)) || []
    loadFailed.value = false
  } catch {
    loadFailed.value = true // client.js 已 toast；空态文案不能谎报「还没有评论」
  } finally {
    loading.value = false
  }
}
onMounted(load)

function reload() {
  loading.value = true
  load()
}

async function submit(parentId = null) {
  const body = (parentId ? replyDraft : draft).value.trim()
  if (!body || posting.value) return
  posting.value = true
  try {
    await createComment(props.materialId, { body, parent_id: parentId })
    if (parentId) cancelReply()
    else draft.value = ''
    await load()
    toast.success(parentId ? '已回复' : '已发布评论')
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
    await load()
    toast.success('已删除评论')
  } catch {
    /* client.js 已统一 toast */
  }
}
</script>

<style scoped>
.cmt { margin-top: 34px; }
.cmt-title {
  font-family: var(--font-serif);
  font-size: 18px;
  margin-bottom: 14px;
  display: flex;
  align-items: baseline;
  gap: 8px;
}
.cmt-count { font-size: 12.5px; color: var(--ink-3); font-weight: 400; }

.cmt-composer {
  border: 1px solid var(--hairline-strong);
  background: var(--paper-raised);
  border-radius: var(--radius-lg);
  padding: 14px 16px;
  margin-bottom: 22px;
}
.cmt-composer .textarea { width: 100%; border-color: var(--hairline); background: var(--paper); }
.cmt-composer-foot {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 10px;
}
.cmt-hint { font-size: 11.5px; color: var(--ink-4); margin-right: auto; }

.cmt-loading { display: flex; justify-content: center; padding: 30px 0; }
.cmt-empty { font-size: 12.5px; color: var(--ink-4); padding: 6px 2px; }
.btn-bare.retry { color: var(--gold-deep); text-decoration: underline; text-underline-offset: 3px; }

.cmt-list { display: flex; flex-direction: column; gap: 14px; }
.cmt-item {
  border: 1px solid var(--hairline);
  background: var(--paper-raised);
  border-radius: var(--radius-lg);
  padding: 13px 16px;
}
.cmt-head { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.cmt-author { font-size: 13px; font-weight: 600; color: var(--ink); }
.cmt-ver {
  font-size: 11px;
  color: var(--gold-deep);
  border: 1px solid var(--gold-line);
  background: var(--gold-wash);
  border-radius: 2px;
  padding: 0 6px;
  line-height: 1.7;
}
.cmt-time { font-size: 11.5px; color: var(--ink-4); }
.cmt-spacer { flex: 1; }
.cmt-body {
  margin-top: 7px;
  font-family: var(--font-serif);
  font-size: 13.5px;
  line-height: 1.8;
  color: var(--ink-2);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.cmt-deleted { font-size: 12px; color: var(--ink-4); font-style: italic; }

.btn-bare {
  font-size: 12px;
  color: var(--ink-3);
  padding: 2px 4px;
  transition: color var(--dur-fast) var(--ease-out);
}
.btn-bare:active { transform: scale(0.96); }
@media (hover: hover) and (pointer: fine) {
  .btn-bare:hover { color: var(--gold-deep); }
  .btn-bare.danger:hover { color: var(--danger); }
}

.cmt-replies {
  margin-top: 12px;
  border-left: 2px solid var(--hairline-strong);
  padding-left: 14px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.cmt-reply-box { margin-top: 12px; }
.cmt-reply-box .textarea { width: 100%; border-color: var(--hairline); background: var(--paper); }
</style>
