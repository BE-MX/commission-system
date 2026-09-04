import { describe, expect, it } from 'vitest'

import { createLatestMountGuard } from '@/content/latestMountGuard'

describe('latest toolbar mount guard', () => {
  it('prevents a slower previous chat lookup from committing after a newer mount begins', () => {
    const guard = createLatestMountGuard()

    const firstChat = guard.begin()
    const secondChat = guard.begin()

    expect(guard.isCurrent(firstChat)).toBe(false)
    expect(guard.isCurrent(secondChat)).toBe(true)
  })
})
