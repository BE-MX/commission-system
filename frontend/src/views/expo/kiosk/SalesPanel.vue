<template>
  <div class="sales">
    <div class="head">
      <span class="title">销售接力</span>
      <span class="pill" :class="{ ok: strategy || isScene }">{{ pillText }}</span>
    </div>

    <div class="cust">
      <div class="avatar" />
      <div class="cust-info">
        <div class="nm">{{ customerName }}</div>
        <div class="meta">
          {{ needLabel }} · {{ stylePref }}
          <template v-if="lovedNames.length"><br />心动：{{ lovedNames.join(' ♥ · ') }} ♥</template>
          <template v-if="internalNote"><br /><span class="internal">发况备注（仅您可见）：{{ internalNote }}</span></template>
        </div>
      </div>
    </div>

    <div v-if="strategy" class="strategy">
      <div class="k">开场 · 情感线</div>
      <p>{{ strategy.opener }}</p>
      <div class="k">跟进 · 理性线</div>
      <p>{{ strategy.followup }}</p>
      <template v-if="strategy.objections?.length">
        <div class="k">异议应对</div>
        <p v-for="(item, i) in strategy.objections" :key="i" class="qa">
          <em>{{ item.q }}</em> —— {{ item.a }}
        </p>
      </template>
    </div>

    <div class="forbid">话术规范：不说「便宜 / 划算 / 性价比 / 打折」</div>

    <div class="intent">
      <button
        v-for="level in LEVELS" :key="level.value"
        class="lv" :class="{ sel: form.intent_level === level.value }"
        @click="form.intent_level = level.value"
      ><b>{{ level.value }}</b><small>{{ level.label }}</small></button>
    </div>

    <div class="next-actions">
      <button
        v-for="action in NEXT_ACTIONS" :key="action"
        class="na" :class="{ sel: form.next_action === action }"
        @click="form.next_action = form.next_action === action ? '' : action"
      >{{ action }}</button>
    </div>

    <textarea v-model="form.notes" class="note" placeholder="备注：沟通要点、试戴实物款、约定事项…" />

    <div class="actions">
      <button class="xk-btn ghost" @click="backToResult">返回效果页</button>
      <button class="xk-btn" :disabled="!form.intent_level || submitting" @click="submit">
        {{ submitting ? '提交中…' : '提交反馈并结束本单' }}
      </button>
    </div>
  </div>
</template>

<script setup>
import { computed, inject, reactive, ref } from 'vue'

const flow = inject('tryonFlow')

const LEVELS = [
  { value: 'A', label: '强意向' },
  { value: 'B', label: '有兴趣' },
  { value: 'C', label: '观望' },
  { value: 'D', label: '无意向' },
]
const NEXT_ACTIONS = ['约到店复试', '加微信跟进', '当场成交', '发效果图回访']
const NEED_LABELS = { volume: '关注发量丰盈', gray_cover: '关注白发遮盖', style_change: '关注造型变换' }

const internal = computed(() => flow.internalSession.value)
const strategy = computed(() => internal.value?.strategy || null)
// scene 模式后端不生成话术（无面容分析依据），不能让销售等一个永不到来的状态
const isScene = computed(() => flow.mode.value === 'scene')
const pillText = computed(() => {
  if (isScene.value) return '场景大片模式 · 无 AI 话术'
  return strategy.value ? '双轨话术已就绪' : '话术生成中…'
})
const customerName = computed(() => flow.regForm.name || '本单客户')
const needLabel = computed(() => NEED_LABELS[flow.regForm.primary_need] || '')
const stylePref = computed(() => flow.regForm.style_pref || '')
const internalNote = computed(() => {
  const info = internal.value?.analysis_internal
  if (!info) return ''
  return [info.hair_condition, info.sales_note].filter(Boolean).join(' · ')
})
const lovedNames = computed(() =>
  (flow.results.value || []).filter(r => r.reaction === 'loved').map(r => r.wig_name).filter(Boolean),
)

const form = reactive({ intent_level: '', notes: '', next_action: '' })
const submitting = ref(false)

function backToResult() {
  flow.step.value = 'result'
  flow.touch()
}

async function submit() {
  if (submitting.value) return
  submitting.value = true
  try {
    await flow.submitSales({ ...form })
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.sales {
  flex: 1; display: flex; flex-direction: column;
  width: min(92vw, 620px); margin: 0 auto; padding: 1vh 0 2.5vh; overflow-y: auto;
}
.head { display: flex; justify-content: space-between; align-items: center; }
.title { font-family: 'Noto Serif SC', serif; font-size: 22px; font-weight: 600; }
.pill {
  font-size: 11px; letter-spacing: 0.16em; padding: 5px 14px; border-radius: 20px;
  color: var(--xk-mut); border: 1px solid var(--xk-gold-line);
}
.pill.ok { color: #7fc79a; border-color: rgba(127, 199, 154, 0.4); }
.cust {
  display: flex; gap: 14px; align-items: center; margin-top: 14px;
  padding: 14px 16px; border-radius: 16px;
  border: 1px solid var(--xk-gold-line); background: rgba(232, 196, 121, 0.04);
}
.avatar {
  width: 46px; height: 46px; border-radius: 50%; flex: none;
  border: 1px solid var(--xk-gold-line);
  background: radial-gradient(circle at 35% 30%, #5d4e3a, #2c241a);
}
.cust-info .nm { font-size: 16px; color: var(--xk-gold-hi); }
.cust-info .meta { font-size: 12px; color: var(--xk-mut); margin-top: 4px; line-height: 1.8; }
.internal { color: #e0906b; }
.strategy {
  margin-top: 12px; padding: 15px 17px; border-radius: 16px;
  border: 1px solid rgba(232, 196, 121, 0.35);
  background: linear-gradient(130deg, rgba(232, 196, 121, 0.1), rgba(232, 196, 121, 0.02));
}
.strategy .k {
  font-size: 10px; letter-spacing: 0.26em; color: var(--xk-gold);
  display: flex; align-items: center; gap: 8px; margin-top: 10px;
}
.strategy .k:first-child { margin-top: 0; }
.strategy .k::before { content: ''; width: 14px; height: 1px; background: var(--xk-gold); }
.strategy p { font-size: 13px; line-height: 1.9; margin: 6px 0 0; }
.strategy .qa em { font-style: normal; color: var(--xk-gold-hi); }
.forbid { margin-top: 10px; font-size: 11px; color: #e0906b; letter-spacing: 0.08em; }
.forbid::before { content: '⛔ '; }
.intent { display: flex; gap: 10px; margin-top: 14px; }
.lv {
  flex: 1; height: 48px; border-radius: 12px; cursor: pointer;
  border: 1px solid var(--xk-gold-line); background: transparent; color: var(--xk-mut);
  display: flex; flex-direction: column; align-items: center; justify-content: center;
}
.lv b { font-family: 'Noto Serif SC', serif; font-size: 17px; }
.lv small { font-size: 9px; letter-spacing: 0.14em; }
.lv.sel { color: var(--xk-ink); border: none; background: linear-gradient(110deg, var(--xk-gold), var(--xk-gold-hi)); }
.next-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
.na {
  padding: 8px 16px; border-radius: 20px; cursor: pointer; font-size: 12px;
  border: 1px solid var(--xk-gold-line); background: transparent; color: var(--xk-mut);
}
.na.sel { color: var(--xk-gold-hi); border-color: var(--xk-gold); background: rgba(232, 196, 121, 0.12); }
.note {
  margin-top: 12px; min-height: 84px; border-radius: 14px; resize: none;
  border: 1px solid var(--xk-gold-line); background: rgba(232, 196, 121, 0.035);
  color: var(--xk-paper); font-size: 13px; line-height: 1.8; padding: 12px 14px; outline: none;
  font-family: inherit;
}
.note::placeholder { color: #5d5647; }
.actions { display: flex; gap: 12px; margin-top: 16px; }
.actions .xk-btn { flex: 1; padding: 0; height: 50px; font-size: 13px; }
.actions .xk-btn:disabled { opacity: 0.4; }
</style>
