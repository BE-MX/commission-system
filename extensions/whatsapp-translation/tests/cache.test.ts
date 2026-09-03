import { describe, expect, it, vi } from 'vitest'

import { TranslationCache } from '@/background/cache'

describe('translation cache', () => {
  it('expires entries after five minutes and evicts the oldest entry when full', () => {
    const now = vi.fn(() => 0)
    const cache = new TranslationCache({ maxEntries: 2, now: () => now() })

    cache.set('first', 'first')
    cache.set('second', 'second')
    cache.set('third', 'third')

    expect(cache.get('first')).toBeUndefined()
    expect(cache.get('second')).toBe('second')

    now.mockReturnValue(5 * 60 * 1000 + 1)
    expect(cache.get('second')).toBeUndefined()
  })
})
