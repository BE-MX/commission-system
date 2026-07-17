<template>
  <div class="page">
    <nav class="crumb rise">
      <router-link to="/materials" class="crumb-back">← 资料库</router-link>
    </nav>

    <div v-if="loading" class="detail-loading"><span class="spinner"></span></div>
    <EmptyState v-else-if="notFound" title="资料不存在或已删除" hint="返回资料库看看其他条目" />

    <template v-else-if="material">
      <header class="m-head rise">
        <p class="page-eyebrow">
          {{ material.category }}<template v-if="material.list_no"> · #{{ String(material.list_no).padStart(2, '0') }}</template>
        </p>
        <div class="m-title-row">
          <h1 class="page-title">{{ material.name }}</h1>
          <div class="m-actions">
            <button class="btn" type="button" @click="editOpen = true">编辑</button>
            <button class="btn btn-ghost btn-danger" type="button" @click="deleteConfirm = true">删除</button>
          </div>
        </div>
        <p v-if="material.description" class="m-desc">{{ material.description }}</p>
        <div class="m-meta">
          <StatusBadge :label="IMPORTANCE[material.importance].label" :tone="IMPORTANCE[material.importance].tone" dot />
          <span v-if="material.phase" class="mono meta-chip">Phase {{ material.phase }}</span>
          <span class="meta-chip">{{ DELIVERY_TYPE[material.delivery_type].label }}</span>
          <span v-if="material.owner" class="meta-chip">负责：{{ nameOf(material.owner) }}</span>
          <a v-if="material.external_url" :href="material.external_url" target="_blank" rel="noopener" class="meta-link">打开外部链接 ↗</a>
        </div>

        <!-- 状态手动流转（无审批流） -->
        <div class="status-flow" role="group" aria-label="资料状态流转">
          <template v-for="(s, i) in MATERIAL_STATUS_FLOW" :key="s">
            <button
              class="flow-step"
              :class="{ current: material.status === s, done: flowIndex(material.status) > i }"
              type="button"
              @click="setStatus(s)"
            >{{ MATERIAL_STATUS[s].label }}</button>
            <span v-if="i < MATERIAL_STATUS_FLOW.length - 1" class="flow-arrow" aria-hidden="true">→</span>
          </template>
          <span class="flow-sep" aria-hidden="true"></span>
          <button
            class="flow-step muted"
            :class="{ current: material.status === 'not_required' }"
            type="button"
            @click="setStatus('not_required')"
          >无需提供</button>
        </div>
      </header>

      <!-- 上传区（线下交付禁传原文；外部链接只维护 URL） -->
      <section v-if="canUpload" class="upload-strip rise rise-1">
        <button class="btn btn-accent" type="button" @click="uploadOpen = true">↥ 上传新版本</button>
        <span class="upload-hint">版本号自动 +1 · AI 自动对比上一版 · 单文件 ≤ 50MB</span>
      </section>
      <section v-else-if="material.delivery_type === 'offline'" class="offline-strip rise rise-1">
        <span class="offline-mark" aria-hidden="true">⇄</span>
        <div>
          <p class="offline-title">凭据类材料 · 线下交付</p>
          <p class="offline-sub">禁止上传原文，本站只跟踪状态{{ material.delivery_remark ? ` · ${material.delivery_remark}` : '' }}</p>
        </div>
      </section>
      <section v-else-if="material.delivery_type === 'link'" class="offline-strip rise rise-1">
        <span class="offline-mark" aria-hidden="true">↗</span>
        <div>
          <p class="offline-title">外部链接类型</p>
          <p class="offline-sub">大体积媒体不进站，内容以链接指向的地址为准</p>
        </div>
      </section>

      <!-- 版本时间线 -->
      <section v-if="canUpload" class="timeline rise rise-2">
        <h2 class="tl-title">版本时间线</h2>
        <div v-if="visibleVersions.length" class="tl-list">
          <article
            v-for="v in visibleVersions"
            :key="v.id"
            class="tl-item"
            :class="{ deleted: v.is_deleted }"
          >
            <div class="tl-rail" aria-hidden="true">
              <span class="tl-dot" :class="{ current: v.is_current }"></span>
            </div>
            <div class="tl-card">
              <header class="tl-head">
                <span class="tl-ver mono">v{{ v.version_no }}</span>
                <StatusBadge v-if="v.is_current" label="当前版本" tone="cinnabar" />
                <span v-if="v.is_deleted" class="tl-deleted-tag">已删除</span>
                <time class="tl-time mono">{{ fmtTime(v.created_at) }}</time>
                <span class="tl-by">{{ nameOf(v.uploaded_by) }} 上传</span>
                <span class="tl-spacer"></span>
                <template v-if="!v.is_deleted">
                  <button class="btn btn-sm btn-ghost" type="button" @click="download(v)">下载</button>
                  <button v-if="v.previewable" class="btn btn-sm btn-ghost" type="button" @click="previewing = v">预览</button>
                  <button class="btn btn-sm btn-ghost btn-danger" type="button" @click="deletingVersion = v">删除</button>
                </template>
              </header>
              <p v-if="v.change_note" class="tl-note">「{{ v.change_note }}」</p>
              <p class="tl-file mono">{{ v.original_name }} · {{ fmtSize(v.file_size) }}</p>

              <!-- AI 差异概要 -->
              <div v-if="!v.is_deleted" class="diff" :class="`diff-${v.diff_status}`">
                <template v-if="v.diff_status === 'pending'">
                  <span class="spinner"></span>
                  <span class="diff-label">AI 差异概要生成中…</span>
                </template>
                <template v-else-if="v.diff_status === 'done'">
                  <p class="diff-label">✦ AI 差异概要<template v-if="prevNo(v)">（对比 v{{ prevNo(v) }}）</template></p>
                  <p class="diff-body">{{ v.diff_summary }}</p>
                </template>
                <template v-else-if="v.diff_status === 'failed'">
                  <span class="diff-label failed">差异概要生成失败{{ v.diff_error ? `：${v.diff_error}` : '' }}</span>
                  <button class="btn btn-sm" type="button" @click="retryDiff(v)">重试</button>
                </template>
                <template v-else>
                  <span class="diff-na">{{ diffNaText(v) }}</span>
                </template>
              </div>
            </div>
          </article>
        </div>
        <EmptyState v-else title="还没有版本" hint="上传第一份文件，版本从 v1 开始" />
      </section>
    </template>

    <UploadDialog v-model="uploadOpen" @upload="upload" />
    <MaterialDrawer v-model="editOpen" :material="material" :members="members" @save="saveEdit" />
    <PreviewModal v-if="previewing" :version="previewing" :title="material?.name" @close="previewing = null" />
    <UiModal
      v-model="deleteConfirm"
      title="删除资料"
      :message="`确定删除「${material?.name}」？条目与全部版本将软删除、下载立即停止，操作留痕。`"
      confirm-text="删除"
      danger
      @confirm="onDeleteMaterial"
    />
    <UiModal
      :model-value="!!deletingVersion"
      title="删除版本"
      :message="`确定删除 v${deletingVersion?.version_no}？删除后当前版本将回落到上一版，版本号不复用。`"
      confirm-text="删除"
      danger
      @update:model-value="deletingVersion = null"
      @confirm="onDeleteVersion"
    />
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import EmptyState from '../components/EmptyState.vue'
import MaterialDrawer from '../components/MaterialDrawer.vue'
import PreviewModal from '../components/PreviewModal.vue'
import StatusBadge from '../components/StatusBadge.vue'
import UiModal from '../components/UiModal.vue'
import UploadDialog from '../components/UploadDialog.vue'
import { useMaterialDetail } from '../composables/useMaterialDetail.js'
import { DELIVERY_TYPE, fmtSize, fmtTime, IMPORTANCE, MATERIAL_STATUS, MATERIAL_STATUS_FLOW } from '../utils/labels.js'

const router = useRouter()
const {
  material, members, loading, notFound,
  nameOf, canUpload, setStatus, saveEdit, upload, removeVersion, retryDiff, removeMaterial, download,
} = useMaterialDetail()

const uploadOpen = ref(false)
const editOpen = ref(false)
const previewing = ref(null)
const deleteConfirm = ref(false)
const deletingVersion = ref(null)

const visibleVersions = computed(() => material.value?.versions || [])

const flowIndex = (status) => MATERIAL_STATUS_FLOW.indexOf(status)

// 「上一版」统一口径：未删除的最大前一版（与后端 previous_version 同规则）
function prevNo(v) {
  const versions = material.value?.versions || []
  const prev = versions
    .filter((x) => !x.is_deleted && x.version_no < v.version_no)
    .map((x) => x.version_no)
  return prev.length ? Math.max(...prev) : null
}

function diffNaText(v) {
  if (v.version_no === 1) return '首个版本，无上一版可对比'
  return v.diff_error || '该类型不支持差异对比'
}

async function onDeleteMaterial() {
  await removeMaterial()
  router.replace('/materials')
}

async function onDeleteVersion() {
  await removeVersion(deletingVersion.value)
  deletingVersion.value = null
}
</script>

<style scoped>
.crumb { margin-bottom: 18px; }
.crumb-back {
  font-size: 12.5px;
  color: var(--ink-3);
  transition: color var(--dur-fast) var(--ease-out);
}
@media (hover: hover) and (pointer: fine) {
  .crumb-back:hover { color: var(--cinnabar); }
}

.detail-loading { display: flex; justify-content: center; padding: 120px 0; }

.m-head { margin-bottom: 26px; }
.m-title-row { display: flex; align-items: flex-start; justify-content: space-between; gap: 18px; }
.m-actions { display: flex; gap: 8px; flex-shrink: 0; margin-top: 6px; }
.m-desc { margin-top: 12px; color: var(--ink-2); font-size: 13.5px; max-width: 720px; }
.m-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 14px;
  flex-wrap: wrap;
}
.meta-chip {
  font-size: 11.5px;
  color: var(--ink-3);
  border: 1px solid var(--hairline);
  background: var(--paper-raised);
  border-radius: 2px;
  padding: 1px 8px;
  line-height: 1.8;
}
.meta-link {
  font-size: 12px;
  color: var(--cinnabar);
  text-decoration: underline;
  text-underline-offset: 3px;
}

.status-flow {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 20px;
  flex-wrap: wrap;
}
.flow-step {
  padding: 6px 14px;
  font-size: 12.5px;
  color: var(--ink-3);
  border: 1px solid var(--hairline-strong);
  background: var(--paper-raised);
  border-radius: 999px;
  transition: all var(--dur-fast) var(--ease-out);
}
.flow-step:active { transform: scale(0.96); }
@media (hover: hover) and (pointer: fine) {
  .flow-step:hover { border-color: var(--ink-3); color: var(--ink); }
}
.flow-step.done { color: var(--ink-2); border-color: var(--hairline); background: var(--paper-sunken); }
.flow-step.current {
  color: #fff;
  background: var(--ink);
  border-color: var(--ink);
  font-weight: 600;
}
.flow-step.muted.current { background: var(--paper-sunken); color: var(--ink-2); border-color: var(--hairline-strong); }
.flow-arrow { color: var(--ink-4); font-size: 11px; }
.flow-sep { width: 12px; }

.upload-strip {
  display: flex;
  align-items: center;
  gap: 14px;
  border: 1px solid var(--hairline-strong);
  background: var(--paper-raised);
  border-radius: var(--radius-lg);
  padding: 16px 20px;
  margin-bottom: 30px;
}
.upload-hint { font-size: 12px; color: var(--ink-4); }

.offline-strip {
  display: flex;
  gap: 14px;
  align-items: center;
  border: 1px solid var(--cinnabar-line);
  background: var(--cinnabar-wash);
  border-radius: var(--radius-lg);
  padding: 16px 20px;
  margin-bottom: 30px;
}
.offline-mark {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  border: 1.5px solid var(--cinnabar);
  border-radius: 50%;
  color: var(--cinnabar);
  font-size: 15px;
  flex-shrink: 0;
}
.offline-title { font-size: 13.5px; font-weight: 600; color: var(--cinnabar-deep); }
.offline-sub { font-size: 12px; color: var(--cinnabar-deep); opacity: 0.85; margin-top: 2px; }

.tl-title {
  font-family: var(--font-serif);
  font-size: 18px;
  margin-bottom: 18px;
}
.tl-list { display: flex; flex-direction: column; }
.tl-item { display: flex; gap: 16px; }
.tl-rail {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding-top: 22px;
}
.tl-dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  border: 2px solid var(--ink-4);
  background: var(--paper);
  flex-shrink: 0;
}
.tl-dot.current { border-color: var(--cinnabar); background: var(--cinnabar); }
.tl-rail::after {
  content: '';
  flex: 1;
  width: 1px;
  background: var(--hairline-strong);
  margin-top: 6px;
}
.tl-item:last-child .tl-rail::after { display: none; }
.tl-card {
  flex: 1;
  border: 1px solid var(--hairline-strong);
  background: var(--paper-raised);
  border-radius: var(--radius-lg);
  padding: 15px 18px;
  margin-bottom: 16px;
  min-width: 0;
}
.tl-item.deleted .tl-card { opacity: 0.55; }
.tl-head { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.tl-ver { font-size: 16px; font-weight: 600; color: var(--cinnabar); }
.tl-item.deleted .tl-ver { color: var(--ink-3); }
.tl-deleted-tag { font-size: 11px; color: var(--ink-4); border: 1px solid var(--hairline); border-radius: 2px; padding: 1px 6px; }
.tl-time { font-size: 12px; color: var(--ink-3); }
.tl-by { font-size: 12px; color: var(--ink-3); }
.tl-spacer { flex: 1; }
.tl-note {
  margin-top: 9px;
  font-family: var(--font-serif);
  font-size: 13.5px;
  color: var(--ink-2);
}
.tl-file { margin-top: 5px; font-size: 11.5px; color: var(--ink-4); }

.diff {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  margin-top: 12px;
  padding: 12px 14px;
  background: var(--paper);
  border: 1px solid var(--hairline);
  border-radius: var(--radius);
}
.diff-done { border-left: 2px solid var(--sage-line); }
.diff-failed { border-left: 2px solid var(--cinnabar-line); align-items: center; }
.diff-label { font-size: 12px; color: var(--ink-3); }
.diff-label.failed { color: var(--cinnabar); flex: 1; }
.diff-done .diff-label { color: var(--sage); font-weight: 600; margin-bottom: 6px; display: block; }
.diff-body {
  font-family: var(--font-serif);
  font-size: 13.5px;
  line-height: 1.8;
  color: var(--ink-2);
  white-space: pre-wrap;
}
.diff-done { display: block; }
.diff-na { font-size: 12px; color: var(--ink-4); }

@media (max-width: 640px) {
  .m-title-row { flex-direction: column; }
  .m-actions { margin-top: 0; }
}
</style>
