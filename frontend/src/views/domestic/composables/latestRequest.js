/**
 * Run async requests in invocation order while only letting the latest one
 * publish state. Each composable instance owns its own monotonically
 * increasing request id through this closure.
 */
export function createLatestRequestRunner() {
  let latestRequestId = 0

  return async function runLatest(request, publish, finish) {
    const requestId = ++latestRequestId
    try {
      const result = await request()
      if (requestId === latestRequestId) publish(result)
      return result
    } finally {
      if (requestId === latestRequestId) finish()
    }
  }
}
