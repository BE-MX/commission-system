import { inkboardClient as client } from './clients'

const quiet = { showLoading: false }
export const listDevices = config => client.get('/devices', { ...quiet, ...config })
export const bindDevice = data => client.post('/devices', data, quiet)
export const revokeDevice = id => client.post(`/devices/${id}/revoke`, {}, quiet)
export const listNotes = config => client.get('/notes', { ...quiet, ...config })
export const saveNote = data => data.id
  ? client.put(`/notes/${data.id}`, data, quiet) : client.post('/notes', data, quiet)
export const deleteNote = data => client.post(`/notes/${data.id}/delete`, { version: data.version }, quiet)
export const listMessages = config => client.get('/messages', { ...quiet, ...config })
export const sendMessage = data => client.post('/messages', data, { ...quiet, suppressToast: true })
export const withdrawMessage = id => client.post(`/messages/${id}/withdraw`, {}, quiet)
