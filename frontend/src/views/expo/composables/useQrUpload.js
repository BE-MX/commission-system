/**
 * 拍摄页「扫码传照片」子状态机：从 useTryOnFlow.js 抽出（2026-08-01，纯搬运不改行为）。
 *
 * 触发原因：useTryOnFlow.js 加了这块逻辑后过了 500 行，撞前端硬约定 12
 * （单文件 >500 行必须拆 composable），且这块逻辑本就自成一体——客户扫码→
 * kiosk 轮询待取照片→到达后关闭面板转预览，除了读写宿主的 customerId/step/
 * errorText/touch/registerPromise 外不牵扯宿主其他状态。
 *
 * 依赖显式传入，不反向 import 宿主：customerId/errorText 是宿主的 ref（前者只读，
 * 后者读写），touch 是宿主的函数，getRegisterPromise 是取值器——registerPromise
 * 在宿主里是会被重新赋值的裸变量（不是 ref），只能靠取值器在调用的那一刻拿到
 * 「当下最新」那份，直接传值会永远拿到创建时的快照。
 */
import { ref } from 'vue'
import { createUploadTicket, getPendingPhoto } from '@/api/expo'
import { publicOrigin } from '@/views/expo/kiosk/publicUrl'

export function useQrUpload({
  customerId, errorText, touch, getRegisterPromise,
  pollMs, pollFailHintAt, netCongestionHint,
}) {
  const qrUrl = ref('')          // 非空 = 二维码面板开启中
  const qrExpiresAt = ref(0)     // 毫秒时间戳；到点自动关面板并重新武装 idle
  const pendingName = ref('')    // 待取照片文件名，确认时随 createSession 提交

  let qrTimer = null
  let pendingPollFails = 0    // 待取照片轮询连续失败计数，复用会话轮询同一套阈值与提示文案
  let onPendingArrived = null // CaptureScreen 注册的回调：待取照片到达时把它显示为预览

  function setPendingHandler(fn) { onPendingArrived = fn }

  async function openQr() {
    if (qrUrl.value) return // 面板已开：拦掉触屏误双击重复取号（否则旧 qrTimer/pollPending 变孤儿，见下）
    errorText.value = ''
    // 建档可能仍在后台跑（乐观切换）：与 submitPhoto 同一套「先等 registerPromise、
    // 再判 customerId」模式，避免拿一个未兑现/悬空的 customerId 去换二维码
    //（后端会 404，或者——万一 registerPromise 尚未来得及赋值——直接打到 undefined）
    const registerPromise = getRegisterPromise()
    if (registerPromise) {
      try {
        await registerPromise
      } catch (e) {
        errorText.value = '登记提交失败，请返回上一步重试'
        return
      }
    }
    if (!customerId.value) {
      errorText.value = '登记未完成，请返回上一步重试'
      return
    }
    try {
      const res = await createUploadTicket(customerId.value)
      qrUrl.value = `${publicOrigin()}${res.data.path}`
      qrExpiresAt.value = Date.now() + res.data.expires_in * 1000
      touch()                          // 立即生效：qrUrl 非空后 touch() 不再武装，清掉已有的 idle 计时
      qrTimer = setTimeout(closeQr, res.data.expires_in * 1000)
      pendingPollFails = 0
      pollPending()
    } catch (e) {
      // 503=密钥未配置（部署缺陷，重试无用，得报修）；其余按网络类故障处理，重试/直拍都可行——
      // 两种文案不同是因为前者「让顾问再点一次」是在浪费顾客时间，得让顾问知道该报修而非重试
      errorText.value = e?.response?.status === 503
        ? '扫码上传未配置，请联系管理员或直接拍照'
        : '二维码获取失败，请直接拍照或呼叫顾问'
    }
  }

  function closeQr() {
    if (qrTimer) { clearTimeout(qrTimer); qrTimer = null }
    qrUrl.value = ''
    qrExpiresAt.value = 0
    touch()                            // 重新武装 idle；resetAll 内调用时 step 已是 attract，
                                        // touch() 见 attract 直接返回，不会误武装（见 resetAll 注释）
  }

  // 待取照片轮询：与会话轮询（poll）不同——这里用「上一轮结束才排下一轮」的递归 setTimeout，
  // 天然互斥，不需要 pollBusy 那种在途守卫；重试也不会无限跑：二维码 10 分钟到期后
  // closeQr 清空 qrUrl，本函数入口与两条分支落地时都先查 qrUrl，过期后自然停止
  function pollPending() {
    if (!qrUrl.value) return
    getPendingPhoto(customerId.value)
      .then((res) => {
        if (!qrUrl.value) return       // 轮询在途期间面板已关（到期/清场），丢弃这次结果
        pendingPollFails = 0
        if (errorText.value === netCongestionHint) errorText.value = ''
        if (res.data.pending) {
          pendingName.value = res.data.pending.name
          const url = res.data.pending.photo_url
          closeQr()                    // 面板任务已完成：关闭并重新武装 idle——
                                        // 客户需要回到平板确认/重拍，这段等待同样受 60s 保护
          onPendingArrived?.(url)
          return
        }
        setTimeout(pollPending, pollMs)
      })
      .catch(() => {
        if (!qrUrl.value) return       // 已关闭面板后的迟到失败不计数、不提示（避免串味到别的屏）
        pendingPollFails += 1
        if (pendingPollFails >= pollFailHintAt && !errorText.value) {
          errorText.value = netCongestionHint
        }
        setTimeout(pollPending, pollMs)
      })
  }

  function disposeQr() {
    if (qrTimer) clearTimeout(qrTimer)
  }

  return { qrUrl, qrExpiresAt, pendingName, openQr, closeQr, setPendingHandler, disposeQr }
}
