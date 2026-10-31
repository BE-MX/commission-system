<template>
  <el-drawer
    v-model="c.visible.value"
    :direction="isMobile ? 'btt' : 'rtl'"
    :size="isMobile ? '92%' : '640px'"
    :title="c.step.value === 'review' ? '核对跟进记录' : '记一条跟进'"
    class="followup-composer"
    append-to-body
    destroy-on-close
    :before-close="beforeClose"
    @closed="c.close()"
  >
    <!-- 第一步：输入 -->
    <section v-if="c.step.value === 'input'" class="composer-body" @paste="c.onPaste">
      <el-form label-position="top">
        <el-form-item label="客户（可留空，AI 会从截图认）">
          <el-select
            v-model="c.form.value.customer_id" filterable remote clearable reserve-keyword
            :remote-method="c.searchCustomers" :loading="c.searching.value" placeholder="店名 / 编号 / 微信备注"
            class="full" @change="c.loadCustomerContext"
          >
            <el-option v-for="opt in c.customerOptions.value" :key="opt.id" :value="opt.id" :label="opt.shop_name"
                       :disabled="!opt.writable">
              <span>{{ opt.shop_name }}</span>
              <span class="option-meta">{{ !opt.writable ? `归属 ${opt.owner_name}，不能记录` : (opt.matched_alias ? `别名：${opt.matched_alias}` : opt.owner_name) }}</span>
            </el-option>
          </el-select>
          <GlassButton variant="link" left-icon="Plus" class="prospect-btn" @click="promptProspect">新客户，快速建档</GlassButton>
        </el-form-item>
        <div class="row-2">
          <el-form-item label="跟进日期">
            <el-date-picker v-model="c.form.value.followup_date" type="date" value-format="YYYY-MM-DD"
                            :disabled-date="isFuture" class="full" />
          </el-form-item>
          <el-form-item label="沟通方式">
            <el-select v-model="c.form.value.channel" clearable placeholder="可留空" class="full">
              <el-option v-for="v in c.dicts.domestic_followup_channel" :key="v" :value="v" :label="v" />
            </el-select>
          </el-form-item>
        </div>
        <el-form-item label="跟进内容">
          <el-input v-model="c.form.value.raw_text" type="textarea" :autosize="{ minRows: 5, maxRows: 12 }"
                    placeholder="随手写，或直接 Ctrl+V 粘贴微信截图" />
        </el-form-item>
        <div class="shots">
          <div v-for="a in c.attachments.value" :key="a.id || a.previewUrl" class="shot">
            <img v-if="a.previewUrl" :src="a.previewUrl" :alt="a.file_name">
            <span v-else class="shot-name">{{ a.file_name }}</span>
            <span v-if="a.uploading" class="shot-state">上传中</span>
            <button type="button" class="shot-remove" aria-label="移除截图" @click="c.removeAttachment(a)">×</button>
          </div>
          <label v-if="c.attachments.value.length < 9" class="shot shot-add">
            <input type="file" accept="image/*" multiple hidden @change="onPick">
            <span>＋ 截图</span>
          </label>
        </div>
        <div class="row-2">
          <el-form-item label="下次跟进（可选，填了就生成待办）">
            <el-date-picker v-model="c.form.value.next_date" type="date" value-format="YYYY-MM-DD" clearable class="full" />
          </el-form-item>
          <el-form-item label="方式">
            <el-select v-model="c.form.value.next_method" clearable class="full">
              <el-option v-for="v in c.dicts.domestic_followup_channel" :key="v" :value="v" :label="v" />
            </el-select>
          </el-form-item>
        </div>
        <el-form-item v-if="c.form.value.next_date" label="下次跟进内容">
          <el-input v-model="c.form.value.next_plan" maxlength="500" />
        </el-form-item>
      </el-form>
    </section>

    <!-- AI 整理中 -->
    <section v-else-if="c.step.value === 'parsing'" class="composer-body">
      <p class="parsing-tip">AI 正在读截图、拆要点，通常 10~30 秒。可以先关掉，草稿会保留在「我的草稿」里。</p>
      <el-skeleton :rows="8" animated />
    </section>

    <!-- 第二步：核对 -->
    <section v-else class="composer-body">
      <el-alert v-if="c.aiFailed.value" type="warning" :closable="false" show-icon
                title="AI 没整理成功，请对照下方截图文字手动填写，原文已保留" />
      <details v-if="c.form.value.raw_text" class="ocr-box" open>
        <summary>原文</summary>
        <pre>{{ c.form.value.raw_text }}</pre>
      </details>
      <el-form label-position="top">
        <el-form-item label="客户">
          <el-select v-model="c.form.value.customer_id" filterable remote clearable :remote-method="c.searchCustomers"
                     :loading="c.searching.value" class="full" @change="c.loadCustomerContext">
            <el-option v-for="opt in c.customerOptions.value" :key="opt.id" :value="opt.id" :label="opt.shop_name"
                       :disabled="!opt.writable" />
          </el-select>
          <p v-if="c.form.value.customerConfidence" class="hint">AI 匹配，置信度 {{ Math.round(c.form.value.customerConfidence * 100) }}%，请确认</p>
        </el-form-item>
        <div class="row-2">
          <el-form-item label="跟进日期">
            <el-date-picker v-model="c.form.value.followup_date" type="date" value-format="YYYY-MM-DD"
                            :disabled-date="isFuture" class="full" />
          </el-form-item>
          <el-form-item label="沟通方式">
            <el-select v-model="c.form.value.channel" clearable class="full">
              <el-option v-for="v in c.dicts.domestic_followup_channel" :key="v" :value="v" :label="v" />
            </el-select>
          </el-form-item>
        </div>
        <el-form-item label="一句话摘要">
          <el-input v-model="c.form.value.summary" maxlength="500" />
        </el-form-item>

        <FollowupItemList title="跟进要点" kind="content" :rows="c.form.value.contents" :categories="[]"
                          @add="c.addRow('contents', 'content')" />
        <FollowupItemList title="异常" kind="issue" :rows="c.form.value.issues"
                          :categories="c.dicts.domestic_followup_category" @add="c.addRow('issues', 'issue')" />
        <FollowupItemList title="意见建议" kind="suggestion" :rows="c.form.value.suggestions"
                          :categories="c.dicts.domestic_followup_category" @add="c.addRow('suggestions', 'suggestion')" />

        <el-form-item label="客户状态变化">
          <el-check-tag v-for="v in c.dicts.domestic_followup_state_change" :key="v" class="state-tag"
                        :checked="c.form.value.state_changes.includes(v)" @change="toggleState(v)">{{ v }}</el-check-tag>
        </el-form-item>

        <div class="row-2">
          <el-form-item label="下次跟进日期">
            <el-date-picker v-model="c.form.value.next_date" type="date" value-format="YYYY-MM-DD" clearable class="full" />
          </el-form-item>
          <el-form-item label="方式">
            <el-select v-model="c.form.value.next_method" clearable class="full">
              <el-option v-for="v in c.dicts.domestic_followup_channel" :key="v" :value="v" :label="v" />
            </el-select>
          </el-form-item>
        </div>
        <p v-if="c.form.value.next_date" class="hint">
          {{ weekdayLabel(c.form.value.next_date) }}<template v-if="c.form.value.nextExpression"> · 依据：原话「{{ c.form.value.nextExpression }}」</template>
        </p>
        <p v-if="basisHint" class="hint hint-warn">{{ basisHint }}</p>
        <el-form-item label="下次跟进内容">
          <el-input v-model="c.form.value.next_plan" maxlength="500" placeholder="留空则不生成待办" />
        </el-form-item>

        <el-form-item v-if="c.openTasks.value.length" label="本客户未完成的待办（勾选＝本次一并完成）">
          <el-checkbox-group v-model="c.form.value.closeTaskIds" class="stack">
            <el-checkbox v-for="t in c.openTasks.value" :key="t.id" :value="t.id">{{ t.title }}（{{ dueLabel(t) }}）</el-checkbox>
          </el-checkbox-group>
        </el-form-item>
        <el-form-item v-if="c.openItems.value.length" label="未结的异常 / 意见">
          <div v-for="item in c.openItems.value" :key="item.id" class="open-item">
            <el-checkbox :model-value="isResolved(item)" @change="v => c.toggleResolved(item, v)">
              {{ item.category }}：{{ item.text }}
            </el-checkbox>
            <el-input v-if="isResolved(item)" v-model="resolvedRow(item).resolution" placeholder="怎么解决的（可选）" />
          </div>
        </el-form-item>

        <el-alert v-if="c.form.value.unreadable.length" type="warning" :closable="false" title="AI 没读到的内容">
          <ul class="plain-list"><li v-for="u in c.form.value.unreadable" :key="u">{{ u }}</li></ul>
        </el-alert>
        <details v-if="ocrTexts.length" class="ocr-box">
          <summary>截图文字（{{ ocrTexts.length }} 张）</summary>
          <pre v-for="(t, i) in ocrTexts" :key="i">{{ t }}</pre>
        </details>
      </el-form>
    </section>

    <template #footer>
      <div class="composer-footer">
        <template v-if="c.step.value === 'input'">
          <GlassButton :disabled="!c.canSubmit.value" :loading="c.saving.value" @click="c.saveDirect">直接保存</GlassButton>
          <GlassButton variant="primary" left-icon="MagicStick" :disabled="!c.canSubmit.value" :loading="c.saving.value" @click="c.startAi">AI 整理</GlassButton>
        </template>
        <template v-else-if="c.step.value === 'review'">
          <GlassButton variant="link" @click="discardWithConfirm">作废草稿</GlassButton>
          <GlassButton variant="primary" :loading="c.saving.value" @click="c.confirm">确认保存</GlassButton>
        </template>
        <GlassButton v-else @click="c.close()">稍后再看</GlassButton>
      </div>
    </template>
  </el-drawer>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import GlassButton from '@/components/GlassButton.vue'
import { currentBeijingDate, formatCalendarDate } from '@/utils/datetime'
import { confirmAction, isFeedbackCancelled, promptAction } from '@/utils/feedback'
import { nextBasisHint, taskDueLabel, weekdayLabel } from '../followupDraft'
import FollowupItemList from './FollowupItemList.vue'

const props = defineProps({ composer: { type: Object, required: true } })
const c = props.composer

const media = window.matchMedia('(max-width: 768px)')
const isMobile = ref(media.matches)
const syncMedia = e => { isMobile.value = e.matches }
onMounted(() => media.addEventListener('change', syncMedia))
onBeforeUnmount(() => media.removeEventListener('change', syncMedia))

// 日期选择器的 Date 是日历标签，不做时区换算（utils/datetime.js 的约定）；「今天」每次现取，页面开过午夜也对
const isFuture = d => formatCalendarDate(d) > currentBeijingDate()
const basisHint = computed(() => nextBasisHint(c.form.value))
const ocrTexts = computed(() => c.attachments.value.map(a => a.ocr_text).filter(Boolean))
const dueLabel = t => taskDueLabel(t, currentBeijingDate())
const isResolved = item => c.form.value.resolvedItems.some(r => r.item_id === item.id)
const resolvedRow = item => c.form.value.resolvedItems.find(r => r.item_id === item.id)

function onPick(event) {
  c.addFiles(Array.from(event.target.files || []))
  event.target.value = ''
}

function toggleState(value) {
  const list = c.form.value.state_changes
  c.form.value.state_changes = list.includes(value) ? list.filter(v => v !== value) : [...list, value]
}

async function promptProspect() {
  try {
    const { value } = await promptAction('输入店名，只建「潜在」档，其他资料以后再补', '新客户快速建档', {
      inputValidator: v => Boolean(String(v || '').trim()) || '请输入店名',
    })
    await c.createProspect(value.trim())
  } catch (e) { if (!isFeedbackCancelled(e)) throw e }
}

async function beforeClose(done) {
  const dirty = c.step.value === 'input' && (c.form.value.raw_text.trim() || c.attachments.value.length)
  if (!dirty) return done()
  try {
    await confirmAction('写的内容还没保存，关掉就没了。', '放弃这条跟进？')
    done()
  } catch (e) { if (!isFeedbackCancelled(e)) throw e }
}

async function discardWithConfirm() {
  try {
    await confirmAction('作废后这份草稿不会进入客户记录，原文和截图保留 7 天。', '作废草稿')
    await c.discard()
  } catch (e) { if (!isFeedbackCancelled(e)) throw e }
}
</script>

<style scoped>
.composer-body { display: flex; flex-direction: column; gap: 12px; }
.full { width: 100%; }
.row-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.option-meta { float: right; color: var(--text-secondary); font-size: 12px; }
.prospect-btn { margin-top: 4px; }
.hint { margin: 4px 0 0; font-size: 12px; color: var(--text-secondary); }
.hint-warn { color: var(--color-warning-text); }
.shots { display: flex; flex-wrap: wrap; gap: 8px; }
.shot { position: relative; width: 72px; height: 96px; border-radius: var(--radius-sm, 6px); overflow: hidden; border: 1px solid var(--border-color); background: var(--tag-neutral-bg); }
.shot img { width: 100%; height: 100%; object-fit: cover; }
.shot-state { position: absolute; inset: auto 0 0; padding: 2px; font-size: 11px; text-align: center; color: var(--text-on-dark); background: var(--overlay-scrim); }
.shot-remove { position: absolute; top: 2px; right: 2px; width: 20px; height: 20px; border: 0; border-radius: 50%; color: var(--text-on-dark); background: var(--overlay-scrim); cursor: pointer; transition: transform 160ms var(--ease-out-strong); }
.shot-remove:active { transform: scale(0.95); }
.shot-name { display: block; padding: 6px; font-size: 11px; word-break: break-all; color: var(--text-secondary); }
.shot-add { display: flex; align-items: center; justify-content: center; color: var(--text-secondary); cursor: pointer; border-style: dashed; }
.parsing-tip { margin: 0 0 12px; color: var(--text-secondary); }
.state-tag { margin: 0 6px 6px 0; }
.stack { display: flex; flex-direction: column; align-items: flex-start; }
.open-item { display: flex; flex-direction: column; gap: 4px; width: 100%; margin-bottom: 6px; }
.plain-list { margin: 4px 0 0; padding-left: 18px; }
.ocr-box pre { white-space: pre-wrap; font-size: 12px; background: var(--tag-neutral-bg); padding: 8px; border-radius: var(--radius-sm, 6px); }
.composer-footer { display: flex; justify-content: flex-end; gap: 8px; }
@media (max-width: 768px) {
  .row-2 { grid-template-columns: 1fr; }
  .composer-footer { position: sticky; bottom: 0; }
  .composer-footer :deep(button) { flex: 1; min-height: 44px; }
}
</style>
