export const DOMESTIC_REVIEW_CHANGED = 'ark:domestic-review-changed'

export async function requestReviewsChanged(request) {
  const result = await request
  window.dispatchEvent(new Event(DOMESTIC_REVIEW_CHANGED))
  return result
}
