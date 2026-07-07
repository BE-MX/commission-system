/**
 * 统一操作反馈（2026-07-03 治理 F-2）。
 * 目标：全站成功/失败/危险确认的文案句式与视觉一致，新页面禁止散写 ElMessage 文案风格。
 */
import { ElMessage, ElMessageBox } from 'element-plus'

/** 操作成功。msgSuccess('保存') → "保存成功" */
export function msgSuccess(action = '操作') {
  ElMessage.success(`${action}成功`)
}

/** 操作失败。拦截器已对接口错误统一弹窗，本函数用于本地校验/非接口失败场景 */
export function msgError(text = '操作失败') {
  ElMessage.error(text)
}

/**
 * 危险操作二次确认（删除/作废/清空等不可逆动作）。
 * confirmDanger('删除', '客户「陈女士」') → 确认框；用户取消时 reject（调用方 catch 即可）
 */
export function confirmDanger(action, target, extra = '此操作不可恢复。') {
  return ElMessageBox.confirm(
    `确定${action}${target ? `「${target}」` : ''}？${extra}`,
    `${action}确认`,
    { type: 'warning', confirmButtonText: `确定${action}`, cancelButtonText: '取消', confirmButtonClass: 'el-button--danger' },
  )
}
