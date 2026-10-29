import { getCurrentInstance, onBeforeUnmount, onMounted, watch } from 'vue'
import { msgError } from '../../../utils/feedback.js'
import { emptyOutboundFilters, outboundListQuery, querySignature, readOutboundListState } from './outboundListState.js'

export function useOutboundListView(list, route, router) {
  const path = '/shipping/outbound'
  const snapshot = () => ({ searchForm: list.appliedSearchForm.value, sortParams: list.appliedSort.value, page: list.page.value, pageSize: list.pageSize.value })
  const sameView = (left, right) => querySignature(outboundListQuery(left)) === querySignature(outboundListQuery(right))
  let disposed = false
  async function publish(replace = false) {
    if (disposed || route.path !== path) return
    const query = outboundListQuery(snapshot(), route.query)
    if (querySignature(query) === querySignature(route.query)) return
    try { await router[replace ? 'replace' : 'push']({ path, query, hash: route.hash }) }
    catch (error) { msgError('筛选地址更新失败，请重新查询', error) }
  }
  list.restoreViewState(readOutboundListState(route.query), { fetch: false })
  const stopRoute = watch(() => [route.path, route.query], ([nextPath, query], [previousPath, previousQuery]) => {
    if (nextPath !== path) return
    const next = readOutboundListState(query)
    if (!sameView(snapshot(), next)) list.restoreViewState(next)
    else if (query.problem !== previousQuery.problem || query.problem_focus !== previousQuery.problem_focus) list.fetchList()
  })
  const stopState = watch(() => JSON.stringify(snapshot()), () => { publish() })
  if (getCurrentInstance()) onMounted(() => publish(true))
  function removeFilter(key) {
    if (!Object.hasOwn(emptyOutboundFilters(), key)) return
    const view = snapshot()
    const draft = JSON.parse(JSON.stringify(list.searchForm))
    const cleared = emptyOutboundFilters()[key]
    list.restoreViewState({ ...view, searchForm: { ...view.searchForm, [key]: cleared }, page: 1 }, { fetch: false })
    Object.assign(list.searchForm, draft, { [key]: cleared })
    return list.fetchList()
  }
  // Exposed for isolated tests; component-scoped watchers are disposed by Vue.
  function stop() { disposed = true; stopRoute(); stopState() }
  if (getCurrentInstance()) onBeforeUnmount(stop)
  return { removeFilter, stop }
}
