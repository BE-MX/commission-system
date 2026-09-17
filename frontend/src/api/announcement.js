import { announcementClient } from './clients'
const unwrap = response => response.data?.data ?? response.data
export const announcementApi = {
  get: (path = '', params) => announcementClient.get(path, { params, showLoading: false }).then(unwrap),
  post: (path, data = {}) => announcementClient.post(path, data).then(unwrap),
  put: (path, data) => announcementClient.put(path, data).then(unwrap),
  delete: path => announcementClient.delete(path).then(unwrap),
}
