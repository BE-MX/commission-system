export function captureStationScroll(cards, scrollY, readingLine, viewportBottom) {
  if (scrollY <= 1) return { scrollY }
  const anchor = cards.find(card => {
    const rect = card.getBoundingClientRect()
    return rect.bottom > readingLine && rect.top < viewportBottom
  })
  return { scrollY, itemId: anchor?.dataset.itemId, itemTop: anchor?.getBoundingClientRect().top }
}

export function restoredStationScroll(snapshot, cards, currentScrollY) {
  const replacement = cards.find(card => card.dataset.itemId === snapshot.itemId)
  return replacement && snapshot.itemTop !== undefined
    ? currentScrollY + replacement.getBoundingClientRect().top - snapshot.itemTop
    : snapshot.scrollY
}
