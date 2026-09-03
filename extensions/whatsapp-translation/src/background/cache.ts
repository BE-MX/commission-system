type CacheEntry<TValue> = {
  expiresAt: number
  value: TValue
}

export class TranslationCache<TValue> {
  private readonly entries = new Map<string, CacheEntry<TValue>>()

  constructor(
    private readonly options: {
      maxEntries?: number
      now?: () => number
      ttlMs?: number
    } = {},
  ) {}

  get(key: string): TValue | undefined {
    const entry = this.entries.get(key)
    if (!entry) return undefined
    if (entry.expiresAt <= this.now()) {
      this.entries.delete(key)
      return undefined
    }
    this.entries.delete(key)
    this.entries.set(key, entry)
    return entry.value
  }

  set(key: string, value: TValue): void {
    this.entries.delete(key)
    this.entries.set(key, { expiresAt: this.now() + this.ttlMs, value })
    while (this.entries.size > this.maxEntries) {
      const oldestKey = this.entries.keys().next().value
      if (oldestKey === undefined) break
      this.entries.delete(oldestKey)
    }
  }

  private get maxEntries(): number {
    return this.options.maxEntries ?? 200
  }

  private get now(): () => number {
    return this.options.now ?? Date.now
  }

  private get ttlMs(): number {
    return this.options.ttlMs ?? 5 * 60 * 1000
  }
}
