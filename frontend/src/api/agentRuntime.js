import { agentRuntimeClient } from './clients'

const quiet = { showLoading: false }

export const getAgentRuntimeConfig = () => agentRuntimeClient.get('/config', quiet)
export const getAgentProfiles = () => agentRuntimeClient.get('/profiles', quiet)
export const getAgentTasks = params => agentRuntimeClient.get('/tasks', { params, showLoading: false })
export const getAgentEvaluationReadiness = () => agentRuntimeClient.get('/evaluations/readiness', quiet)
export const getCopilotEvaluationCases = () => agentRuntimeClient.get('/evaluations/copilot/cases', quiet)
export const searchCopilotEvaluationCustomers = params => (
  agentRuntimeClient.get('/evaluations/copilot/customers', { params, showLoading: false })
)
export const startCopilotEvaluationCase = (caseId, data) => (
  agentRuntimeClient.post(`/evaluations/copilot/cases/${caseId}/runs`, data)
)
export const getAgentRun = runId => agentRuntimeClient.get(`/runs/${runId}`, quiet)
export const getAgentEvents = (runId, params = {}) => (
  agentRuntimeClient.get(`/runs/${runId}/events`, { params, showLoading: false })
)
export const createAgentSession = data => agentRuntimeClient.post('/sessions', data)
export const createAgentRun = (sessionId, data) => (
  agentRuntimeClient.post(`/sessions/${sessionId}/runs`, data)
)
export const cancelAgentRun = runId => agentRuntimeClient.post(`/runs/${runId}/cancel`)
export const acceptAgentArtifact = (artifactId, note = null) => (
  agentRuntimeClient.post(`/artifacts/${artifactId}/accept`, { note })
)
export const rejectAgentArtifact = (artifactId, note = null) => (
  agentRuntimeClient.post(`/artifacts/${artifactId}/reject`, { note })
)
export const submitAgentFeedback = (runId, data) => (
  agentRuntimeClient.post(`/runs/${runId}/feedback`, data)
)

export async function startCustomerCopilot({ profileId, customerName, question }) {
  const sessionResponse = await createAgentSession({
    profile_key: 'customer_order_copilot',
    title: `${customerName || `客户 #${profileId}`} · 经营副驾驶`,
    context_type: 'customer',
    context_id: String(profileId),
  })
  const session = sessionResponse.data
  const idempotencyKey = globalThis.crypto?.randomUUID?.()
    || `copilot-${Date.now()}-${Math.random().toString(16).slice(2)}`
  const runResponse = await createAgentRun(session.id, {
    idempotency_key: idempotencyKey,
    input: { question, customer_profile_id: profileId },
    trigger_type: 'user',
    business_ref_type: 'customer_profile',
    business_ref_id: String(profileId),
  })
  return runResponse.data
}
