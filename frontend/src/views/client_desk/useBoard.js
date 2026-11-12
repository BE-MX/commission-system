import { computed, ref, watch, onBeforeUnmount } from 'vue'
import { clientDeskApi as api } from '@/api/clientDesk'
import { errorText, latestRequestGate } from './deskController'
import { DIMENSIONS, filterCards, groupLanes, tagOptions } from './boardModel'

const STORAGE_KEY = 'client-desk-board-v1'

function readPrefs() {
  try { return JSON.parse(globalThis.localStorage?.getItem(STORAGE_KEY) || '{}') } catch { return {} }
}

export function useBoard() {
  const prefs = readPrefs()
  const data = ref(null), loading = ref(false), error = ref('')
  const groupBy = ref(DIMENSIONS[prefs.groupBy] ? prefs.groupBy : 'stage')
  const subBy = ref(prefs.subBy === '' || DIMENSIONS[prefs.subBy] ? prefs.subBy ?? 'type' : 'type')
  const tagCodes = ref([]), todoOnly = ref(false), keyword = ref('')
  const openLanes = ref(new Set())
  const gate = latestRequestGate()
  let aborter

  const cards = computed(() => data.value?.items || [])
  const visible = computed(() => filterCards(cards.value, { tagCodes: tagCodes.value, todoOnly: todoOnly.value, keyword: keyword.value }))
  const options = computed(() => ({ grades: data.value?.grade_options || [], vocabulary: data.value?.tag_vocabulary || {} }))
  const lanes = computed(() => groupLanes(visible.value, groupBy.value, options.value))
  const filters = computed(() => tagOptions(cards.value))
  const todoCount = computed(() => cards.value.filter(c => c.todo).length)

  async function load() {
    aborter?.abort(); aborter = new AbortController()
    const token = gate.next(); loading.value = !data.value; error.value = ''
    try {
      const result = await api.board({}, aborter.signal)
      if (gate.current(token)) data.value = result
    } catch (e) { if (gate.current(token) && e.code !== 'ERR_CANCELED') error.value = errorText(e) }
    finally { if (gate.current(token)) loading.value = false }
  }
  function toggleLane(key) {
    const next = new Set(openLanes.value)
    next.has(key) ? next.delete(key) : next.add(key)
    openLanes.value = next
  }
  function setAll(open) { openLanes.value = open ? new Set(lanes.value.map(l => l.key)) : new Set() }
  function toggleTag(code) {
    tagCodes.value = tagCodes.value.includes(code) ? tagCodes.value.filter(c => c !== code) : [...tagCodes.value, code]
  }

  watch(groupBy, () => { openLanes.value = new Set(); if (subBy.value === groupBy.value) subBy.value = '' })
  watch([groupBy, subBy], () => {
    try { globalThis.localStorage?.setItem(STORAGE_KEY, JSON.stringify({ groupBy: groupBy.value, subBy: subBy.value })) } catch { /* private mode */ }
  })
  onBeforeUnmount(() => { aborter?.abort(); gate.invalidate() })

  return { data, loading, error, groupBy, subBy, tagCodes, todoOnly, keyword, openLanes, cards, visible, options, lanes, filters, todoCount, load, toggleLane, setAll, toggleTag }
}
