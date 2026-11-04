import { useListPage } from '../../../composables/useListPage.js'

export function useFollowupOverview(api, potentialOnly = () => false) {
  return useListPage((params, { signal }) => {
    const { author_user_id, keyword, date_from, date_to } = params
    if (date_from && date_to && date_from > date_to) {
      throw new Error('开始日期不能晚于结束日期')
    }
    return api.followups({
      ...params, potential_only: potentialOnly(), author_user_id: author_user_id || undefined,
      keyword: keyword.trim() || undefined, date_from: date_from || undefined, date_to: date_to || undefined,
    }, { signal })
  }, {
    immediate: false,
    searchForm: { author_user_id: '', keyword: '', date_from: '', date_to: '' },
  })
}
