<template>
  <div class="sales">
    <!-- ── 视图一：线索列表（对应 web 线索台，手机号脱敏） ── -->
    <template v-if="view === 'list'">
      <div class="head">
        <span class="title">销售模式 · 线索台</span>
        <span class="pill ok">{{ total }} 位客户</span>
      </div>

      <input
        v-model="keyword" class="search" placeholder="搜索姓名 / 手机号"
        @input="onSearch"
      />

      <div v-loading="loading" class="rows">
        <button
          v-for="lead in sortedLeads" :key="lead.customer_id"
          class="row" :class="{ mine: lead.customer_id === flow.customerId.value }"
          @click="openDetail(lead)"
        >
          <span v-if="lead.customer_id === flow.customerId.value" class="row-badge">本单</span>
          <div class="row-main">
            <b>{{ lead.name }}</b>
            <span>{{ lead.phone_masked }}</span>
          </div>
          <div class="row-meta">
            <i v-if="lead.intent_level" class="intent-badge">{{ lead.intent_level }}</i>
            <small>{{ lead.result_count }} 张效果图</small>
          </div>
        </button>
        <div v-if="!loading && !leads.length" class="empty">
          {{ keyword ? '没有匹配的客户' : '还没有登记客户' }}
        </div>
        <div v-if="total > leads.length" class="cap-hint">共 {{ total }} 位，仅显示最近 {{ leads.length }} 位 · 可用搜索定位</div>
      </div>
    </template>

    <!-- ── 视图二：话术详情（只出话术与试戴款，internal 发况不落 kiosk） ── -->
    <template v-else-if="view === 'detail'">
      <div class="head">
        <button class="back" @click="toList">‹ 线索列表</button>
        <span v-if="isMine" class="pill ok">本单客户</span>
      </div>

      <div class="cust">
        <div class="avatar" />
        <div class="cust-info">
          <div class="nm">{{ detail?.customer?.name || '…' }}<small class="ph">{{ detail?.customer?.phone_masked }}</small></div>
          <div class="meta">{{ needLabelOf(detail?.customer?.primary_need) }} · {{ detail?.customer?.style_pref || '—' }}</div>
        </div>
      </div>

      <!-- 原图 + 效果图（横滑图集，轻触看大图） -->
      <div v-if="galleryItems.length" class="gallery">
        <button v-for="(g, i) in galleryItems" :key="i" class="g-item" @click="lightbox = g">
          <img :src="g.url" alt="" />
          <span class="g-cap">{{ g.label }}</span>
        </button>
      </div>

      <div class="forbid">话术规范：不说「便宜 / 划算 / 性价比 / 打折」</div>

      <div v-if="detail?.strategy" class="strategy">
        <div v-if="detail.strategy.opener" class="s-row"><span class="s-label">开场</span><p>{{ detail.strategy.opener }}</p></div>
        <div v-if="detail.strategy.followup" class="s-row"><span class="s-label">跟进</span><p>{{ detail.strategy.followup }}</p></div>
        <div v-for="(ob, i) in detail.strategy.objections || []" :key="i" class="s-row">
          <span class="s-label">异议</span>
          <p><b>{{ ob.q }}</b>{{ ob.a }}</p>
        </div>
      </div>
      <div v-else class="s-empty">
        {{ detail?.strategy_pending ? '话术生成中，稍候自动刷新 …' : '该客户暂无话术（未完成试戴分析）' }}
      </div>

      <div v-if="detail?.tried_wigs?.length" class="tried">
        <span class="s-label">试戴过</span>
        <span v-for="w in detail.tried_wigs" :key="w" class="tried-chip">{{ w }}</span>
      </div>

      <div v-if="isMine" class="actions">
        <button class="xk-btn" @click="view = 'feedback'">录入反馈并结束本单</button>
      </div>

      <!-- 大图灯箱：contain 不裁切，轻触任意处关闭 -->
      <Transition name="glb">
        <div v-if="lightbox" class="g-lightbox" @click="lightbox = null">
          <img :src="lightbox.url" alt="" />
          <span class="g-lb-cap">{{ lightbox.label }} · 轻触任意处返回</span>
        </div>
      </Transition>
    </template>

    <!-- ── 视图三：本单反馈（原销售接力表单，仅本单客户） ── -->
    <template v-else>
      <div class="head">
        <button class="back" @click="view = 'detail'">‹ 返回话术</button>
        <span class="title">销售接力</span>
      </div>

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
        <button class="xk-btn" :disabled="!form.intent_level || submitting" @click="submit">
          {{ submitting ? '提交中…' : '提交反馈并结束本单' }}
        </button>
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed, inject, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { getKioskLeads, getKioskStrategy } from '@/api/expo'

const flow = inject('tryonFlow')

const LEVELS = [
  { value: 'A', label: '强意向' },
  { value: 'B', label: '有兴趣' },
  { value: 'C', label: '观望' },
  { value: 'D', label: '无意向' },
]
const NEXT_ACTIONS = ['约到店复试', '加微信跟进', '当场成交', '发效果图回访']
const NEED_LABELS = { volume: '关注发量丰盈', gray_cover: '关注白发遮盖', style_change: '关注造型变换' }
function needLabelOf(need) { return NEED_LABELS[need] || '—' }

const view = ref('list')

// ── 线索列表 ──
const keyword = ref('')
const leads = ref([])
const total = ref(0)
const loading = ref(false)
let searchTimer = null

async function loadLeads() {
  loading.value = true
  try {
    const res = await getKioskLeads({
      keyword: keyword.value.trim() || undefined,
      expo_code: flow.regForm.expo_code || undefined, // 只看本届次，跨届客户不混排
      page: 1, page_size: 50,
    })
    const payload = res.data ?? res
    leads.value = payload.items || []
    total.value = payload.total ?? leads.value.length
  } catch (e) { /* 弱网失败拦截器已提示，列表留空态 */ } finally {
    loading.value = false
  }
}

function onSearch() {
  flow.touch()
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(loadLeads, 350)
}

// 本单客户置顶：正在体验的客户永远排第一
const sortedLeads = computed(() => {
  const mine = flow.customerId.value
  if (!mine) return leads.value
  return [...leads.value].sort((a, b) => (b.customer_id === mine) - (a.customer_id === mine))
})

// ── 话术详情 ──
const detail = ref(null)
const detailId = ref(null)
const isMine = computed(() => !!detailId.value && detailId.value === flow.customerId.value)
let detailTimer = null

async function openDetail(lead) {
  detailId.value = lead.customer_id
  detail.value = null
  view.value = 'detail'
  flow.touch()
  await fetchDetail()
  armDetailPoll()
}

async function fetchDetail() {
  const id = detailId.value // 代际守卫：快速 A→返回→B 时丢弃 A 的迟到响应（同 poll S1 教训）
  try {
    const res = await getKioskStrategy(id)
    if (id !== detailId.value) return
    detail.value = res.data ?? res
  } catch (e) { /* 拦截器已提示 */ }
}

// 话术随合成并行生成：pending 时 5s 静默刷新（同线索台模式），出话术/离开详情即停
function armDetailPoll() {
  clearDetailPoll()
  detailTimer = setInterval(async () => {
    if (view.value !== 'detail' || !detail.value?.strategy_pending) {
      clearDetailPoll()
      return
    }
    await fetchDetail()
    if (detail.value?.strategy) clearDetailPoll()
  }, 5000)
}

function clearDetailPoll() {
  if (detailTimer) clearInterval(detailTimer)
  detailTimer = null
}

// 图集：每个会话的原图在前，随后是该次已完成的效果图（后端已按最新会话在前排序）
const lightbox = ref(null)
const galleryItems = computed(() => {
  const items = []
  for (const s of detail.value?.sessions || []) {
    if (s.photo_url) items.push({ url: s.photo_url, label: s.mode === 'scene' ? '佩戴实拍' : '原图' })
    for (const r of s.results || []) {
      if (r.image_url) items.push({ url: r.image_url, label: r.wig_name || '效果图' })
    }
  }
  return items
})

function toList() {
  clearDetailPoll()
  view.value = 'list'
  lightbox.value = null
  flow.touch()
  loadLeads() // 反馈可能刚提交过，回列表刷新意向徽标
}

// ── 本单反馈 ──
const form = reactive({ intent_level: '', notes: '', next_action: '' })
const submitting = ref(false)

async function submit() {
  if (submitting.value) return
  submitting.value = true
  try {
    await flow.submitSales({ ...form })
  } finally {
    submitting.value = false
  }
}

onMounted(loadLeads)
onBeforeUnmount(() => {
  clearDetailPoll()
  if (searchTimer) clearTimeout(searchTimer)
})
</script>

<style scoped>
.sales {
  flex: 1; display: flex; flex-direction: column;
  width: min(92vw, 620px); margin: 0 auto; padding: 1vh 0 2.5vh; overflow-y: auto;
}
.head { flex: none; display: flex; justify-content: space-between; align-items: center; }
.title { font-family: 'Noto Serif SC', serif; font-size: 22px; font-weight: 600; }
.pill {
  font-size: 11px; letter-spacing: 0.16em; padding: 5px 14px; border-radius: 20px;
  color: var(--xk-mut); border: 1px solid var(--xk-gold-line);
}
.pill.ok { color: #7fc79a; border-color: rgba(127, 199, 154, 0.4); }
.back {
  height: 36px; padding: 0 14px; border-radius: 18px; cursor: pointer;
  border: 1px solid var(--xk-gold-line); background: transparent;
  color: var(--xk-gold-hi); font-size: 13px; letter-spacing: 0.1em;
  transition: transform 160ms cubic-bezier(0.23, 1, 0.32, 1);
}
.back:active { transform: scale(0.96); }

/* ── 列表视图 ── */
.search {
  flex: none; height: 46px; margin-top: 14px; padding: 0 16px; border-radius: 14px;
  border: 1px solid var(--xk-gold-line); background: rgba(232, 196, 121, 0.045);
  color: var(--xk-paper); font-size: 14px; outline: none; box-sizing: border-box;
}
.search:focus { border-color: var(--xk-gold); }
.search::placeholder { color: #5d5647; }
.rows { display: flex; flex-direction: column; gap: 10px; margin-top: 12px; min-height: 120px; }
.row {
  position: relative; display: flex; justify-content: space-between; align-items: center;
  padding: 14px 16px; border-radius: 14px; cursor: pointer; text-align: left;
  border: 1px solid var(--xk-gold-line); background: rgba(232, 196, 121, 0.03);
  transition: transform 160ms cubic-bezier(0.23, 1, 0.32, 1), border-color 160ms ease;
}
.row:active { transform: scale(0.98); }
.row.mine { border-color: var(--xk-gold); background: rgba(232, 196, 121, 0.09); }
.row-badge {
  position: absolute; top: -9px; left: 14px;
  font-size: 10px; letter-spacing: 0.2em; color: var(--xk-ink);
  background: linear-gradient(110deg, var(--xk-gold), var(--xk-gold-hi));
  padding: 2px 10px; border-radius: 10px;
}
.row-main { display: flex; align-items: baseline; gap: 12px; min-width: 0; }
.row-main b { font-size: 15px; color: var(--xk-gold-hi); font-weight: 400; white-space: nowrap; }
.row-main span { font-size: 12px; color: var(--xk-mut); letter-spacing: 0.06em; }
.row-meta { display: flex; align-items: center; gap: 10px; flex: none; }
.row-meta small { font-size: 11px; color: var(--xk-mut); letter-spacing: 0.06em; }
.intent-badge {
  width: 24px; height: 24px; border-radius: 50%; font-style: normal;
  display: flex; align-items: center; justify-content: center;
  font-size: 12px; color: var(--xk-gold); border: 1px solid var(--xk-gold);
}
.empty { text-align: center; padding: 36px 0; font-size: 13px; color: var(--xk-mut); letter-spacing: 0.14em; }
.cap-hint { text-align: center; padding: 10px 0 2px; font-size: 11px; color: var(--xk-gold-dim); letter-spacing: 0.1em; }

/* ── 话术详情视图 ── */
.cust {
  flex: none; display: flex; gap: 14px; align-items: center; margin-top: 14px;
  padding: 14px 16px; border-radius: 16px;
  border: 1px solid var(--xk-gold-line); background: rgba(232, 196, 121, 0.04);
}
.avatar {
  width: 46px; height: 46px; border-radius: 50%; flex: none;
  border: 1px solid var(--xk-gold-line);
  background: radial-gradient(circle at 35% 30%, #5d4e3a, #2c241a);
}
.cust-info .nm { font-size: 16px; color: var(--xk-gold-hi); }
.cust-info .nm .ph { margin-left: 10px; font-size: 12px; color: var(--xk-mut); letter-spacing: 0.06em; }
.cust-info .meta { font-size: 12px; color: var(--xk-mut); margin-top: 4px; line-height: 1.8; }
.forbid { flex: none; margin-top: 10px; font-size: 11px; color: #e0906b; letter-spacing: 0.08em; }
.forbid::before { content: '⛔ '; }
.strategy {
  margin-top: 12px; padding: 4px 17px; border-radius: 16px;
  border: 1px solid var(--xk-gold-line); background: rgba(232, 196, 121, 0.05);
}
.s-row { display: flex; gap: 12px; padding: 11px 0; border-bottom: 1px dashed rgba(232, 196, 121, 0.14); }
.s-row:last-child { border-bottom: none; }
.s-row p { margin: 0; font-size: 13px; line-height: 1.9; color: var(--xk-paper); }
.s-row p b { display: block; color: var(--xk-gold-hi); font-weight: 400; }
.s-label {
  flex: none; align-self: flex-start; margin-top: 2px;
  font-size: 11px; letter-spacing: 0.14em; color: var(--xk-gold);
  border: 1px solid var(--xk-gold-line); border-radius: 11px; padding: 2px 10px;
}
.s-empty {
  margin-top: 12px; padding: 26px 17px; border-radius: 16px; text-align: center;
  border: 1px dashed var(--xk-gold-line);
  font-size: 12px; color: var(--xk-mut); letter-spacing: 0.1em;
}
/* ── 图集（原图+效果图，横滑；缩略 3:4 竖卡与发型库一致） ── */
.gallery {
  flex: none; display: flex; gap: 10px; margin-top: 12px; padding-bottom: 6px;
  overflow-x: auto; -webkit-overflow-scrolling: touch; scrollbar-width: none;
}
.gallery::-webkit-scrollbar { display: none; }
.g-item {
  flex: none; width: 96px; display: flex; flex-direction: column; gap: 6px;
  padding: 0; border: none; background: transparent; cursor: pointer;
  transition: transform 160ms cubic-bezier(0.23, 1, 0.32, 1);
}
.g-item:active { transform: scale(0.96); }
.g-item img {
  width: 100%; aspect-ratio: 3 / 4; object-fit: cover; border-radius: 12px;
  border: 1px solid var(--xk-gold-line); background: var(--xk-ink-2);
}
.g-cap {
  font-size: 10px; letter-spacing: 0.1em; color: var(--xk-mut); text-align: center;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.g-lightbox {
  position: fixed; inset: 0; z-index: 80;
  background: rgba(12, 10, 8, 0.92);
  -webkit-backdrop-filter: blur(10px); backdrop-filter: blur(10px);
  display: flex; align-items: center; justify-content: center;
}
.g-lightbox img {
  max-width: 94vw; max-height: 90vh; object-fit: contain; border-radius: 12px;
  box-shadow: 0 12px 60px rgba(0, 0, 0, 0.6);
}
.g-lb-cap {
  position: absolute; bottom: 24px; left: 50%; transform: translateX(-50%);
  font-size: 11px; letter-spacing: 0.2em; color: var(--xk-mut); white-space: nowrap;
}
/* 灯箱模态：入场 240ms 强 ease-out，出场更快（非对称）；origin 保持居中 */
.glb-enter-active { transition: opacity 240ms cubic-bezier(0.23, 1, 0.32, 1); }
.glb-enter-active img { transition: transform 240ms cubic-bezier(0.23, 1, 0.32, 1); }
.glb-leave-active { transition: opacity 160ms cubic-bezier(0.23, 1, 0.32, 1); }
.glb-enter-from, .glb-leave-to { opacity: 0; }
.glb-enter-from img { transform: scale(0.96); }
@media (prefers-reduced-motion: reduce) {
  .glb-enter-from img { transform: none; }
}

.tried { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
.tried-chip {
  font-size: 12px; color: var(--xk-gold-hi); letter-spacing: 0.06em;
  border: 1px solid var(--xk-gold-line); border-radius: 14px; padding: 4px 12px;
}

/* ── 反馈视图（原销售接力表单） ── */
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
