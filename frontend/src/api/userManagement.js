/**
 * 用户/角色/权限/个人资料 API
 */
import { authRequest } from './auth'

// ── 用户管理 ──────────────────────────────────────────

export function getUserList(params) {
  return authRequest.get('/users/list', { params }).then(r => r.data)
}

export function createUser(data) {
  return authRequest.post('/users', data, { loadingText: '正在创建...' }).then(r => r.data)
}

export function updateUser(userId, data) {
  return authRequest.put(`/users/${userId}`, data, { loadingText: '正在保存...' }).then(r => r.data)
}

export function deleteUser(userId) {
  return authRequest.delete(`/users/${userId}`, { loadingText: '正在删除...' }).then(r => r.data)
}

export function resetUserPassword(userId, data) {
  return authRequest.put(`/users/${userId}/password`, data, { loadingText: '正在重置...' }).then(r => r.data)
}

export function toggleUserActive(userId) {
  return authRequest.put(`/users/${userId}/toggle-active`).then(r => r.data)
}

// ── 角色管理 ──────────────────────────────────────────

export function getRoleList() {
  return authRequest.get('/roles/list').then(r => r.data)
}

export function createRole(data) {
  return authRequest.post('/roles', data, { loadingText: '正在创建...' }).then(r => r.data)
}

export function updateRole(roleId, data) {
  return authRequest.put(`/roles/${roleId}`, data, { loadingText: '正在保存...' }).then(r => r.data)
}

export function deleteRole(roleId) {
  return authRequest.delete(`/roles/${roleId}`, { loadingText: '正在删除...' }).then(r => r.data)
}

// ── 权限参考 ──────────────────────────────────────────

export function getPermissionList() {
  return authRequest.get('/permissions/list').then(r => r.data)
}

// ── 个人资料 ──────────────────────────────────────────

export function updateProfile(data) {
  return authRequest.put('/profile', data, { loadingText: '正在保存...' }).then(r => r.data)
}

export function changePassword(data) {
  return authRequest.put('/profile/password', data, { loadingText: '正在修改...' }).then(r => r.data)
}
