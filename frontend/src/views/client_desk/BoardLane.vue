<template>
  <section class="lane" :class="{ open }" :data-key="lane.key">
    <button ref="headEl" class="lane-head board-focus" type="button" :aria-expanded="open" :aria-controls="bodyId" @click="toggle">
      <span class="dot" :class="'tone-' + tone" aria-hidden="true" />
      <b>{{ lane.label }}</b>
      <span class="count">{{ lane.items.length }}</span>
      <span class="sum">S/A {{ lane.priority }} 位 · 今日待处理 {{ lane.todo }} 位</span>
      <span class="chev" aria-hidden="true">▾</span>
    </button>
    <div :id="bodyId" ref="bodyEl" class="lane-body">
      <div v-if="!open" class="fan" role="presentation" @click="toggle">
        <div v-for="(card, index) in fanCards" :key="card.company_id" class="slot" :data-cid="card.company_id" :style="{ '--a': seats[index].angle, zIndex: seats[index].z }">
          <BoardCard :card="card" compact />
        </div>
        <span v-if="lane.items.length > fanCards.length" class="extra">另有 {{ lane.items.length - fanCards.length }} 位</span>
      </div>
      <template v-else>
        <template v-for="group in groups" :key="group.key">
          <div v-if="group.label" class="sub-title"><span class="tag" :class="'tone-' + subTone">{{ group.label }}</span><span class="muted">{{ group.items.length }} 位</span></div>
          <div class="grid">
            <button v-for="card in group.items" :key="card.company_id" type="button" class="slot-button board-focus" :data-cid="card.company_id" :aria-label="`打开 ${card.name}`" @click="$emit('open', card)">
              <BoardCard :card="card" :selected="String(selectedId) === String(card.company_id)" />
            </button>
          </div>
        </template>
      </template>
    </div>
  </section>
</template>

<script setup>
import { computed, nextTick, ref } from 'vue'
import BoardCard from './BoardCard.vue'
import { DIMENSIONS, fanSeats, groupLanes } from './boardModel'

const props = defineProps({
  lane: { type: Object, required: true },
  dimension: { type: String, required: true },
  subDimension: { type: String, default: '' },
  open: { type: Boolean, default: false },
  selectedId: { type: [String, Number], default: null },
  options: { type: Object, default: () => ({}) },
})
const emit = defineEmits(['toggle', 'open'])
const headEl = ref(null), bodyEl = ref(null)
const bodyId = computed(() => `lane-${props.dimension}-${props.lane.key || 'none'}`)
const tone = computed(() => DIMENSIONS[props.dimension]?.tone || 'neutral')
const subTone = computed(() => DIMENSIONS[props.subDimension]?.tone || 'neutral')
const fanCards = computed(() => props.lane.items.slice(0, 5))
const seats = computed(() => fanSeats(fanCards.value.length))
const groups = computed(() => props.subDimension && props.subDimension !== props.dimension
  ? groupLanes(props.lane.items, props.subDimension, props.options)
  : [{ key: 'all', label: '', items: props.lane.items }])

const reducedMotion = () => typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

async function toggle() {
  const opening = !props.open
  // FLIP: record where each fanned card sits, then let the grid cards fly in from there.
  const first = {}
  let origin = null
  if (opening && bodyEl.value && !reducedMotion()) {
    for (const slot of bodyEl.value.querySelectorAll('.slot')) {
      const box = slot.getBoundingClientRect()
      first[slot.dataset.cid] = { x: box.left + box.width / 2, y: box.top + box.height / 2, a: Number(slot.style.getPropertyValue('--a')) || 0 }
    }
    const box = bodyEl.value.getBoundingClientRect()
    origin = { x: box.left + box.width / 2, y: box.top + 110, a: 0 }
  }
  emit('toggle', props.lane.key)
  await nextTick()
  if (!opening || !origin || !bodyEl.value) return
  bodyEl.value.querySelectorAll('.slot-button').forEach((slot, index) => {
    const box = slot.getBoundingClientRect(), from = first[slot.dataset.cid] || origin
    slot.style.setProperty('--dx', `${from.x - (box.left + box.width / 2)}px`)
    slot.style.setProperty('--dy', `${from.y - (box.top + box.height / 2)}px`)
    slot.style.setProperty('--dr', `${from.a}deg`)
    slot.style.animationDelay = `${Math.min(index * 22, 280)}ms`
    slot.classList.add('slot-in')
    slot.addEventListener('animationend', () => slot.classList.remove('slot-in'), { once: true })
  })
}

defineExpose({ focus: () => headEl.value?.focus({ preventScroll: true }) })
</script>

<style src="./board.css" scoped></style>
<style scoped>
.lane { position: relative; min-width: 0; border: 1px solid var(--border-color); border-radius: 16px; background: var(--dash-glass-bg); box-shadow: var(--dash-glass-shadow); }
.lane.open { grid-column: 1 / -1; background: var(--card-bg); }
.lane-head { display: flex; align-items: center; gap: 10px; width: 100%; padding: 13px 16px 11px; border: 0; border-radius: 16px; background: transparent; color: var(--text-primary); text-align: left; cursor: pointer; }
.lane-head:focus:not(:focus-visible) { outline: none; }
.dot { flex: none; width: 9px; height: 9px; border-radius: 50%; background: var(--tag-neutral-solid); }
.dot.tone-gold { background: var(--tag-gold-solid); }
.dot.tone-info { background: var(--tag-info-solid); }
.dot.tone-success { background: var(--tag-success-solid); }
.dot.tone-danger { background: var(--tag-danger-solid); }
.dot.tone-violet { background: var(--metric-violet-ink); }
.lane-head b { font: 700 15px var(--font-display); white-space: nowrap; }
.count { padding: 0 8px; border-radius: 999px; background: var(--tag-neutral-bg); color: var(--tag-neutral-text); font-size: 12px; font-variant-numeric: tabular-nums; }
.sum { min-width: 0; overflow: hidden; color: var(--text-secondary); font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.chev { margin-left: auto; color: var(--text-secondary); transition: transform 250ms ease; }
.open .chev { transform: rotate(180deg); }
.lane-body { position: relative; }
.lane:not(.open) .lane-body { height: 216px; overflow: hidden; border-radius: 0 0 16px 16px; }
.open .lane-body { padding: 4px 16px 18px; }
.fan { position: absolute; left: 50%; bottom: 34px; width: 66%; max-width: 280px; height: 132px; transform: translateX(-50%); cursor: pointer; }
.slot { position: absolute; inset: 0; transform: rotate(calc(var(--a) * var(--spread, 1) * 1deg)); transform-origin: 50% 340px; transition: transform 320ms cubic-bezier(0.2, 0.8, 0.2, 1); pointer-events: none; }
.extra { position: absolute; top: -26px; right: -40px; z-index: 11; padding: 0 8px; border: 1px solid var(--border-color); border-radius: 999px; background: var(--card-bg); color: var(--text-secondary); font-size: 11px; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(250px, 100%), 1fr)); gap: 12px; }
.sub-title { display: flex; align-items: center; gap: 8px; margin: 14px 0 8px; }
.slot-button { display: block; width: 100%; padding: 0; border: 0; border-radius: 13px; background: transparent; cursor: pointer; }
.slot-in { animation: slot-in 420ms cubic-bezier(0.2, 0.8, 0.2, 1) both; }
@keyframes slot-in { from { opacity: 0.2; transform: translate(var(--dx, 0), var(--dy, 0)) rotate(var(--dr, 0deg)) scale(0.94); } to { opacity: 1; transform: none; } }
@media (hover: hover) and (pointer: fine) {
  .lane:not(.open):hover .fan { --spread: 1.35; }
  .slot-button:hover :deep(.card) { transform: translateY(-2px); box-shadow: var(--dash-glass-shadow-hover); border-color: var(--tag-gold-border); }
}
@media (max-width: 720px) {
  .sum { display: none; }
  .fan { width: 78%; }
}
@media (prefers-reduced-motion: reduce) {
  .slot, .chev, .slot-button :deep(.card) { transition: none; }
  .slot-in { animation: none; }
  .lane:not(.open):hover .fan { --spread: 1; }
}
</style>
