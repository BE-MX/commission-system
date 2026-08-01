/**
 * 拍摄页「扫码传照片」子状态机：从 useTryOnFlow.js 抽出（2026-08-01，纯搬运不改行为）。
 *
 * 触发原因：useTryOnFlow.js 加了这块逻辑后过了 500 行，撞前端硬约定 12
 * （单文件 >500 行必须拆 composable），且这块逻辑本就自成一体——客户扫码→
 * kiosk 轮询待取照片→到达后关闭面板转预览，除了读写宿主的 customerId/step/
 * errorText/touch/registerPromise 外不牵扯宿主其他状态。
 *
 * 依赖显式传入，不反向 import 宿主：customerId/step/errorText 是宿主的 ref（前两个只读，
 * errorText 读写），touch 是宿主的函数，getRegisterPromise 是取值器——registerPromise
 * 在宿主里是会被重新赋值的裸变量（不是 ref），只能靠取值器在调用的那一刻拿到
 * 「当下最新」那份，直接传值会永远拿到创建时的快照。
 */
import { ref } from 'vue'
import { createUploadTicket, getPendingPhoto } from '@/api/expo'
import { publicOrigin } from '@/views/expo/kiosk/publicUrl'

export function useQrUpload({
  customerId, step, errorText, touch, getRegisterPromise,
  pollMs, pollFailHintAt, netCongestionHint,
}) {
  const qrUrl = ref('')          // 非空 = 二维码面板开启中
  const qrExpiresAt = ref(0)     // 毫秒时间戳；到点自动关面板并重新武装 idle
  const pendingName = ref('')    // 待取照片文件名，确认时随 createSession 提交

  let qrTimer = null
  let pendingPollFails = 0    // 待取照片轮询连续失败计数，复用会话轮询同一套阈值与提示文案
  let onPendingArrived = null // CaptureScreen 注册的回调：待取照片到达时把它显示为预览
  let opening = false // 在途守卫：qrUrl 变真之前 openQr 自身可能被再次触发（触屏误双击）
  // 本次开码的时刻（秒，与后端 uploaded_at 同口径）：只认这之后传上来的照片。
  // 待取文件是**按客户**留最新 3 张的，确认时只消费掉其中一张，剩下的还在目录里——
  // 不比时间的话，下次为同一客户开码会在客户还没扫之前就把旧照片当作"刚到达"弹出来，
  // 面板瞬间自己关掉并显示一张陌生的旧图（对抗性审查 I4 实测可复现）
  let qrOpenedAt = 0

  function setPendingHandler(fn) { onPendingArrived = fn }

  async function openQr() {
    if (qrUrl.value || opening) return // 面板已开 / 上一次调用还没落地：都拦掉，否则 qrTimer/pollPending 变孤儿
    opening = true
    errorText.value = ''
    try {
      // I2 生成快照（对抗性审查）：ticket 请求是 ~1.5-2s 的 frp 往返，这期间二维码面板
      // 不在屏上、头部「主页」按钮仍可点，一点就是无确认地 resetAll()。await 落地后必须
      // 重新核验，不然这份迟到的响应会无条件写 qrUrl/开 qrTimer/起轮询——即便客户早已被
      // 清场，甚至可能已经换成下一位客户在 capture 屏上，会把上一位的二维码/轮询绑过去
      let cid = customerId.value
      // 建档可能仍在后台跑（乐观切换）：与 submitPhoto 同一套「先等 registerPromise、
      // 再判 customerId」模式，避免拿一个未兑现/悬空的 customerId 去换二维码
      const registerPromise = getRegisterPromise()
      if (registerPromise) {
        try {
          await registerPromise
        } catch (e) {
          if (step.value === 'capture') errorText.value = '登记提交失败，请返回上一步重试'
          return
        }
        // customerId 在这段 await 期间 null→真实 id 是预期跳变（建档本身就是这个 promise
        // 干的事），不能拿它和 cid 比较来判断"换客户了"；step 才是"被清场"的信号——
        // resetAll 恒把 step 设回 attract，抓住这一条就够，抓 customerId 反而会把
        // 这条本该走通的路误判成"作废"
        if (step.value !== 'capture') return
        cid = customerId.value // 用刚落地的真实 id 覆盖快照，后续以它为准
      }
      if (!cid) {
        errorText.value = '登记未完成，请返回上一步重试'
        return
      }
      try {
        const res = await createUploadTicket(cid)
        if (customerId.value !== cid || step.value !== 'capture') return // 见上：核心防线
        qrUrl.value = `${publicOrigin()}${res.data.path}`
        qrExpiresAt.value = Date.now() + res.data.expires_in * 1000
        // 秒级并向下取整，与 uploaded_at（文件 mtime 取整）同口径；取「开码前一秒」留出
        // 两机时钟的小幅偏差余量——宁可偶尔多认一张刚传的，也不要漏掉客户真的刚传的那张
        qrOpenedAt = Math.floor(Date.now() / 1000) - 1
        touch()                          // 立即生效：qrUrl 非空后 touch() 不再武装，清掉已有的 idle 计时
        qrTimer = setTimeout(closeQr, res.data.expires_in * 1000)
        pendingPollFails = 0
        pollPending(cid) // 传快照而非让轮询自己读 customerId.value：resetAll 后 customerId 变 null，
                          // 不传的话一旦哪天 qrUrl 判断松动，轮询会静默发出 getPendingPhoto(null)
      } catch (e) {
        if (customerId.value !== cid || step.value !== 'capture') return
        // 503=密钥未配置（部署缺陷，重试无用，得报修）；其余按网络类故障处理，重试/直拍都可行——
        // 两种文案不同是因为前者「让顾问再点一次」是在浪费顾客时间，得让顾问知道该报修而非重试
        errorText.value = e?.response?.status === 503
          ? '扫码上传未配置，请联系管理员或直接拍照'
          : '二维码获取失败，请直接拍照或呼叫顾问'
      }
    } finally {
      opening = false
    }
  }

  function closeQr() {
    if (qrTimer) { clearTimeout(qrTimer); qrTimer = null }
    qrUrl.value = ''
    qrExpiresAt.value = 0
    // 「取消，我现场拍」时若轮询正挂着拥堵提示，一并撤掉——那条提示是二维码轮询产生的，
    // 面板都关了还留在拍摄页上会让顾问以为拍照链路也出了问题（与 poll 的同款条件清除）
    if (errorText.value === netCongestionHint) errorText.value = ''
    touch()                            // 重新武装 idle；resetAll 内调用时 step 已是 attract，
                                        // touch() 见 attract 直接返回，不会误武装（见 resetAll 注释）
  }

  // 待取照片轮询：与会话轮询（poll）不同——这里用「上一轮结束才排下一轮」的递归 setTimeout，
  // 天然互斥，不需要 pollBusy 那种在途守卫；重试也不会无限跑：二维码 10 分钟到期后
  // closeQr 清空 qrUrl，本函数入口与两条分支落地时都先查 qrUrl，过期后自然停止。
  // cid 由 openQr 传入并逐轮透传（不读 customerId.value）：轮询期间宿主状态不会变，
  // 但这样写不依赖「qrUrl 一定先被清空」这一个假设去防止用错客户的 id 发请求
  function pollPending(cid) {
    if (!qrUrl.value) return
    getPendingPhoto(cid)
      .then((res) => {
        if (!qrUrl.value) return       // 轮询在途期间面板已关（到期/清场），丢弃这次结果
        pendingPollFails = 0
        if (errorText.value === netCongestionHint) errorText.value = ''
        // 只认本次开码之后传上来的：残留的旧照片（上一轮确认只消费掉一张，其余仍在
        // 待取目录里）会在客户还没扫码时就被当作"刚到达"，面板自己关掉并弹出一张陌生旧图
        const fresh = res.data.pending && (res.data.pending.uploaded_at || 0) >= qrOpenedAt
        if (fresh) {
          pendingName.value = res.data.pending.name
          const url = res.data.pending.photo_url
          closeQr()                    // 面板任务已完成：关闭并重新武装 idle——
                                        // 客户需要回到平板确认/重拍，这段等待同样受 60s 保护
          onPendingArrived?.(url)
          return
        }
        setTimeout(() => pollPending(cid), pollMs)
      })
      .catch(() => {
        if (!qrUrl.value) return       // 已关闭面板后的迟到失败不计数、不提示（避免串味到别的屏）
        pendingPollFails += 1
        if (pendingPollFails >= pollFailHintAt && !errorText.value) {
          errorText.value = netCongestionHint
        }
        setTimeout(() => pollPending(cid), pollMs)
      })
  }

  function disposeQr() {
    if (qrTimer) clearTimeout(qrTimer)
  }

  return { qrUrl, qrExpiresAt, pendingName, openQr, closeQr, setPendingHandler, disposeQr }
}
