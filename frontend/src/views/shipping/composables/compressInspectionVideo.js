const MAX_BYTES = 100 * 1024 * 1024
const activationRequired = () => Object.assign(new Error('视频已选好，请点击开始压缩并上传'), { code: 'VIDEO_ACTIVATION_REQUIRED' })
const playbackError = error => error?.name === 'NotAllowedError'
  ? activationRequired() : new Error('无法读取视频，请重新拍摄或选择视频')

// WebKit grants media activation per element. Prime the exact element/context
// during the capture button click, then reuse them after the native camera closes.
export function prepareInspectionVideo() {
  const Audio = globalThis.AudioContext || globalThis.webkitAudioContext
  if (!Audio) return null
  const video = document.createElement('video'), audio = new Audio()
  video.playsInline = true; video.preload = 'auto'
  const dispose = () => {
    video.pause(); video.removeAttribute('src'); video.load()
    try { void audio.close().catch(error => console.warn('Video preparation cleanup failed', error)) }
    catch (error) { console.warn('Video preparation cleanup failed', error) }
  }
  try {
    // An empty element cannot produce sound. Its play promise will be aborted by
    // pause/source replacement; only the synchronous activation is needed here.
    void audio.resume().catch(() => {})
    void video.play().catch(() => {})
    video.pause()
    return { video, audio, dispose }
  } catch (error) {
    dispose()
    throw error
  }
}
export function videoDimensions(width, height) {
  const scale = Math.min(1, 1280 / Math.max(width, height))
  return [width, height].map(value => Math.max(2, Math.floor(value * scale / 2) * 2))
}

// Re-encode locally, including audio. No original video is sent before completion.
export async function compressInspectionVideo(file, { onProgress = () => {}, signal, prepared } = {}) {
  const mimeType = ['video/mp4;codecs=avc1.42E01E,mp4a.40.2', 'video/mp4'].find(
    type => globalThis.MediaRecorder?.isTypeSupported(type))
  const Audio = globalThis.AudioContext || globalThis.webkitAudioContext
  if (!mimeType || !Audio) { prepared?.dispose(); throw new Error('当前浏览器不支持视频压缩，请更新浏览器或使用微信小程序') }
  const video = prepared?.video || document.createElement('video'), canvas = document.createElement('canvas')
  if (!canvas.captureStream) { prepared?.dispose(); throw new Error('当前浏览器不支持视频压缩，请使用微信小程序') }
  const url = URL.createObjectURL(file)
  let audio = prepared?.audio, stream, recorder, timer, timeout, source, destination, rejectActive
  const abort = () => rejectActive?.(new Error('视频压缩已取消，请重新选择视频'))
  const hidden = () => { if (document.hidden) rejectActive?.(new Error('压缩已暂停，请保持页面在前台并重新选择视频')) }
  try {
    if (signal?.aborted) throw new Error('视频压缩已取消')
    signal?.addEventListener('abort', abort)
    document.addEventListener('visibilitychange', hidden)
    // Request audio before awaiting; a native file-picker return is not always
    // an activation event on iOS. A subsequent page button click is.
    audio ||= new Audio()
    source = audio.createMediaElementSource(video)
    destination = audio.createMediaStreamDestination()
    source.connect(destination) // Preserve audio without playing through the speaker.
    // Start resume synchronously, and consume rejection immediately.
    const resumed = audio.resume().then(() => true, () => false)
    video.playsInline = true; video.preload = 'auto'
    await new Promise((resolve, reject) => {
      rejectActive = reject
      timeout = setTimeout(() => reject(new Error('读取视频超时，请重新选择视频')), 15000)
      video.onloadeddata = () => { video.pause(); resolve() }
      video.onerror = () => reject(new Error('无法读取视频，请重新拍摄'))
      video.src = url
      // Safari may not decode/preload until play is requested. Unlock this same
      // element in the input/click event, before any await consumes activation.
      video.play().catch(error => reject(playbackError(error)))
    })
    clearTimeout(timeout)
    const audioReady = await Promise.race([resumed, new Promise(resolve => { timeout = setTimeout(() => resolve(false), 5000) })])
    clearTimeout(timeout)
    if (!audioReady || audio.state !== 'running') {
      if (audio.state === 'suspended') throw activationRequired()
      throw new Error('声音处理已中断，请保持页面在前台并重试压缩')
    }
    if (signal?.aborted || document.hidden) throw new Error('请保持页面在前台并重新选择视频')
    if (!Number.isFinite(video.duration) || video.duration <= 0 || !video.videoWidth) throw new Error('视频内容无效，请重新拍摄')
    // Priming playback must not trim the beginning of the recording.
    if (video.currentTime > 0) {
      await new Promise((resolve, reject) => {
        rejectActive = reject
        timeout = setTimeout(() => reject(new Error('视频定位超时，请重试压缩')), 10000)
        video.onseeked = resolve
        video.currentTime = 0
      })
      clearTimeout(timeout)
      video.onseeked = null
    }
    ;[canvas.width, canvas.height] = videoDimensions(video.videoWidth, video.videoHeight)
    const context = canvas.getContext('2d')
    context.drawImage(video, 0, 0, canvas.width, canvas.height)
    stream = canvas.captureStream(24)
    destination.stream.getAudioTracks().forEach(track => stream.addTrack(track))
    const result = await new Promise((resolve, reject) => {
      rejectActive = reject
      const chunks = []; let bytes = 0
      recorder = new MediaRecorder(stream, { mimeType, videoBitsPerSecond: 1800000, audioBitsPerSecond: 96000 })
      recorder.ondataavailable = event => {
        if (event.data.size) { chunks.push(event.data); bytes += event.data.size }
        if (bytes > MAX_BYTES) reject(new Error('压缩后视频仍超过100MB，请分段拍摄'))
      }
      recorder.onerror = () => reject(new Error('视频压缩失败，请重新拍摄或选择视频'))
      recorder.onstop = () => resolve(new Blob(chunks, { type: 'video/mp4' }))
      video.onerror = () => reject(new Error('视频解码失败，请重新拍摄'))
      video.onended = () => { if (recorder.state !== 'inactive') recorder.stop() }
      timeout = setTimeout(() => reject(new Error('视频压缩超时，请缩短视频后重试')), (video.duration * 1.5 + 30) * 1000)
      recorder.start(1000)
      let lastTime = video.currentTime, lastAdvance = Date.now()
      timer = setInterval(() => {
        if (video.currentTime !== lastTime) { lastTime = video.currentTime; lastAdvance = Date.now() }
        if (Date.now() - lastAdvance >= 10000) { reject(new Error('视频处理停滞，请保持页面在前台并重试压缩')); return }
        try { context.drawImage(video, 0, 0, canvas.width, canvas.height) }
        catch { reject(new Error('视频画面处理失败，请重新拍摄')); return }
        onProgress(Math.min(99, Math.round(video.currentTime / video.duration * 100)))
      }, 1000 / 24)
      video.play().catch(error => reject(playbackError(error)))
    })
    if (!result.size || result.size > MAX_BYTES) throw new Error('压缩结果无效或超过100MB，请分段拍摄')
    onProgress(100)
    // Avoid increasing already compact native MP4/MOV files.
    if (file.size <= result.size && /\.(mp4|mov|m4v)$/i.test(file.name)) return file
    return new File([result], file.name.replace(/\.[^.]+$/, '') + '.mp4', { type: 'video/mp4' })
  } finally {
    rejectActive = null
    clearInterval(timer); clearTimeout(timeout)
    video.onended = null; video.onerror = null; video.onloadeddata = null; video.onseeked = null
    if (recorder && recorder.state !== 'inactive') recorder.stop()
    video.pause(); video.removeAttribute('src'); video.load()
    new Set([...(stream?.getTracks() || []), ...(destination?.stream.getTracks() || [])])
      .forEach(track => track.stop())
    source?.disconnect(); destination?.disconnect()
    // Closing a suspended/interrupted audio context must not block the result,
    // the visible error, or the remaining resource cleanup.
    if (audio) {
      try { void audio.close().catch(error => console.warn('Video compression audio cleanup failed', error)) }
      catch (error) { console.warn('Video compression audio cleanup failed', error) }
    }
    URL.revokeObjectURL(url)
    signal?.removeEventListener('abort', abort)
    document.removeEventListener('visibilitychange', hidden)
  }
}
