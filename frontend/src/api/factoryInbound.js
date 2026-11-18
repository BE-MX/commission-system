import { factoryInboundClient as client } from './clients'

const quiet = { showLoading: false }
const batchSyncRequest = { ...quiet, timeout: 240000 }
const notePath = id => '/notes/' + id
const batchesPath = id => notePath(id) + '/batches'

export const factoryInboundApi = {
  settings: config => client.get('/settings', { ...quiet, ...config }),
  list: (params, config) => client.get('/notes', { ...quiet, ...config, params }),
  detail: (id, config) => client.get(notePath(id), { ...quiet, ...config }),
  image: (id, original, signal) => client.get(notePath(id) + '/image', {
    ...quiet, params: { original }, responseType: 'blob', signal,
  }),
  upload(capture, signal) {
    const form = new FormData()
    form.append('scan', capture.scan, 'scan.jpg')
    if (capture.original) form.append('original', capture.original, 'original.jpg')
    return client.post('/notes', form, { ...quiet, signal })
  },
  recognize: (id, payload) => client.post(notePath(id) + '/recognize', payload, quiet),
  confirmDelivery: (id, payload) => client.patch(notePath(id) + '/delivery', payload, quiet),
  void: (id, payload) => client.post(notePath(id) + '/void', payload, quiet),
  editLine: (id, lineId, payload) => client.patch(notePath(id) + '/lines/' + lineId, payload, quiet),
  addLine: (id, payload) => client.post(notePath(id) + '/lines', payload, quiet),
  batches: (id, config) => client.get(batchesPath(id), { ...quiet, ...config }),
  previewBatch: (id, payload, config) => client.post(batchesPath(id) + '/preview', payload, { ...quiet, ...config }),
  startBatch: (id, payload, config) => client.post(batchesPath(id), payload, { ...batchSyncRequest, ...config }),
  resumeBatch: (id, batchId, config) => client.post(batchesPath(id) + '/' + batchId + '/resume', null, { ...batchSyncRequest, ...config }),
  aliases: kind => client.get('/aliases/' + kind, quiet),
  saveAlias: (kind, id, payload) => id == null
    ? client.post('/aliases/' + kind, payload, quiet)
    : client.patch('/aliases/' + kind + '/' + id, payload, quiet),
  suggestions: () => client.get('/aliases/suggestions', quiet),
  reviewSuggestion: (id, accept) => client.patch('/aliases/suggestions/' + id, { accept }, quiet),
}
