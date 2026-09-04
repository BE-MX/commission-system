export function createLatestMountGuard() {
  let generation = 0
  return {
    begin(): number {
      generation += 1
      return generation
    },
    isCurrent(candidate: number): boolean {
      return candidate === generation
    },
  }
}
