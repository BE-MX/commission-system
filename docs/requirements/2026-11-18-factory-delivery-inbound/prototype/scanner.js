// 拍照扫描：直接调用方舟「文档扫描」DEMO 的真实算法模块（找边、透视校正、增强），
// 原型复用生产扫描组件的纯 JS 模块。
const BASE = '../../../../frontend/src/components/document-scanner/'
const { detectDocument } = await import(BASE + 'documentEdges.js')
const { canvasFrom, readDetectionPixels, readScanPhoto, rectifyDocument, renderScan, scanBlob } = await import(BASE + 'documentImage.js')
const { distance, fullFrame, padDetectedQuad } = await import(BASE + 'documentQuad.js')

const PREVIEW_INTERVAL = 135
const PREVIEW_EDGE = 320
const PHOTO_DETECTION_EDGE = 448
const EFFECTS = [['original', '原图'], ['enhanced', '增强'], ['mono', '黑白']]

const icon = {
  back: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M15 18l-6-6 6-6"/></svg>',
  photo: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="3" y="5" width="18" height="14" rx="2"/><circle cx="9" cy="10" r="2"/><path d="M21 16l-5-5-8 8"/></svg>',
}

export function mountScanner(root, { onCaptured, onCancel }) {
  let step = 'ready'
  let stream = null, timer = null, worker = null, pending = false, missed = 0
  let live = null, source = null, corners = fullFrame(), found = false
  let photoUrl = '', resultUrl = '', rectified = null, effect = 'enhanced', busy = false
  let cameraFailed = false, error = '', lastStep = ''
  let dragging = false
  const previewCanvas = document.createElement('canvas')

  const fileInput = Object.assign(document.createElement('input'), { type: 'file', accept: 'image/*', hidden: true })
  const nativeInput = Object.assign(document.createElement('input'), { type: 'file', accept: 'image/*', hidden: true })
  nativeInput.setAttribute('capture', 'environment')
  for (const input of [fileInput, nativeInput]) input.addEventListener('change', e => {
    const file = e.target.files?.[0]; e.target.value = ''
    if (file && !busy) processPhoto(() => readScanPhoto(file))
  })

  function setUrl(old, blob) { if (old) URL.revokeObjectURL(old); return blob ? URL.createObjectURL(blob) : '' }

  function stopCamera() {
    clearInterval(timer); timer = null
    worker?.terminate(); worker = null; pending = false; missed = 0
    stream?.getTracks().forEach(t => t.stop()); stream = null
    live = null
  }

  function present(next) {
    if (!next) { if (++missed >= 2) live = null } else {
      missed = 0
      live = live && next.every((p, i) => distance(p, live[i]) < 0.035)
        ? next.map(([x, y], i) => [0.7 * x + 0.3 * live[i][0], 0.7 * y + 0.3 * live[i][1]])
        : next
    }
    const poly = root.querySelector('.viewfinder polygon'); const guide = root.querySelector('.frame-guide')
    const hint = root.querySelector('.scan-hint')
    if (poly) poly.setAttribute('points', live ? live.map(p => p.join(',')).join(' ') : '')
    if (guide) guide.hidden = !!live
    if (hint) { hint.textContent = live ? '已找到纸张边缘，可以拍照' : '把送货单四个角都放进画面'; hint.classList.toggle('ok', !!live) }
  }

  function inspect() {
    const v = root.querySelector('video')
    if (pending || !v?.videoWidth || v.readyState < 2) return
    const px = readDetectionPixels(previewCanvas, v, v.videoWidth, v.videoHeight, PREVIEW_EDGE)
    if (!worker) { present(detectDocument(px)); return }
    pending = true
    worker.postMessage({ width: px.width, height: px.height, data: px.data }, [px.data.buffer])
  }

  async function openCamera() {
    if (!navigator.mediaDevices?.getUserMedia) { nativeInput.click(); return }
    error = ''; step = 'camera'; render()
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: 'environment' }, width: { ideal: 2560 }, height: { ideal: 1440 } }, audio: false,
      })
      const v = root.querySelector('video')
      v.srcObject = stream; await v.play()
      root.querySelector('.shutter').disabled = false
      try {
        worker = new Worker(new URL(BASE + 'documentEdgeWorker.js', import.meta.url), { type: 'module' })
        worker.onmessage = ({ data }) => { pending = false; present(data) }
        worker.onerror = () => { worker?.terminate(); worker = null; pending = false }
      } catch { worker = null }
      inspect(); timer = setInterval(inspect, PREVIEW_INTERVAL)
    } catch {
      stopCamera(); cameraFailed = true; step = 'ready'
      error = '网页相机无法打开。请允许访问相机，或使用系统相机、选择照片。'
      render()
    }
  }

  function takePhoto() {
    const v = root.querySelector('video')
    if (!v?.videoWidth) return
    const photo = canvasFrom(v, v.videoWidth, v.videoHeight)
    stopCamera()
    processPhoto(() => photo)
  }

  async function processPhoto(get) {
    busy = true; error = ''; render()
    try {
      const canvas = await get()
      const det = document.createElement('canvas')
      const find = edge => detectDocument(readDetectionPixels(det, canvas, canvas.width, canvas.height, edge, 'high'))
      const detected = find(PHOTO_DETECTION_EDGE) || find(PREVIEW_EDGE)
      source = canvas
      photoUrl = setUrl(photoUrl, await scanBlob(canvas))
      found = !!detected
      corners = detected ? padDetectedQuad(detected) : fullFrame()
      step = 'crop'
    } catch {
      error = '无法读取这张照片，请重拍或选择 JPG、PNG 图片。'
    } finally { busy = false; render() }
  }

  async function updatePreview(next, crop) {
    busy = true; render()
    await new Promise(r => setTimeout(r, 16))
    try {
      if (crop) rectified = rectifyDocument(source.getContext('2d').getImageData(0, 0, source.width, source.height), corners)
      const canvas = renderScan(rectified, next)
      resultUrl = setUrl(resultUrl, await scanBlob(canvas))
      effect = next; step = 'result'
    } catch { error = '处理图片失败，请调整四角后重试。' }
    finally { busy = false; render() }
  }

  async function finish() {
    const scan = await fetch(resultUrl).then(r => r.blob())
    const original = await scanBlob(canvasFrom(source, source.width, source.height, 2560))
    onCaptured({ scan, original, url: URL.createObjectURL(scan) })
  }

  function bindCorners(box) {
    const handles = [...box.querySelectorAll('.handle')]
    const poly = box.querySelector('polygon')
    const draw = () => {
      poly.setAttribute('points', corners.map(([x, y]) => `${x * 100},${y * 100}`).join(' '))
      handles.forEach((h, i) => { h.style.left = corners[i][0] * 100 + '%'; h.style.top = corners[i][1] * 100 + '%' })
    }
    handles.forEach((h, i) => {
      h.addEventListener('pointerdown', e => {
        if (dragging) return  // 多指保护：拖动中忽略其他触点
        dragging = true
        e.preventDefault(); h.setPointerCapture(e.pointerId)
        const move = ev => {
          const r = box.getBoundingClientRect()
          corners = corners.map((p, j) => j === i
            ? [Math.min(1, Math.max(0, (ev.clientX - r.left) / r.width)), Math.min(1, Math.max(0, (ev.clientY - r.top) / r.height))]
            : p)
          draw()
        }
        const up = () => { dragging = false; h.removeEventListener('pointermove', move); h.removeEventListener('pointerup', up); h.removeEventListener('pointercancel', up) }
        h.addEventListener('pointermove', move); h.addEventListener('pointerup', up); h.addEventListener('pointercancel', up)
      })
      h.addEventListener('keydown', e => {
        const d = { ArrowLeft: [-0.01, 0], ArrowRight: [0.01, 0], ArrowUp: [0, -0.01], ArrowDown: [0, 0.01] }[e.key]
        if (!d) return
        e.preventDefault()
        corners = corners.map((p, j) => j === i ? [Math.min(1, Math.max(0, p[0] + d[0])), Math.min(1, Math.max(0, p[1] + d[1]))] : p)
        draw()
      })
    })
    draw()
  }

  function render() {
    const head = (title, sub) => `
      <header class="appbar">
        <button class="icon-btn" data-act="back" aria-label="返回">${icon.back}</button>
        <h2>${title}${sub ? `<span class="sub" style="color:inherit;opacity:.7">${sub}</span>` : ''}</h2>
      </header>`
    const err = error ? `<p class="scan-hint" role="alert" style="color:var(--tag-danger-border)">${error}</p>` : ''
    let html = ''
    if (step === 'ready') {
      html = head('拍送货单') + `
        <div class="scan-body"><div class="scan-empty">
          <p>拍整张送货单，系统会自动找边、拉平，再识别型号和数量。</p>
          ${err}
          <button class="btn btn-primary btn-lg" data-act="camera" ${busy ? 'disabled' : ''}>打开相机</button>
          <button class="btn" data-act="pick" ${busy ? 'disabled' : ''}>从相册选择</button>
          ${cameraFailed ? '<button class="btn btn-link" data-act="native" style="color:var(--button-primary-border)">使用系统相机</button>' : ''}
        </div></div>`
    } else if (step === 'camera') {
      html = head('拍送货单') + `
        <p class="scan-hint" role="status">正在打开相机…</p>
        <div class="scan-body"><div class="viewfinder">
          <video autoplay muted playsinline></video>
          <svg viewBox="0 0 1 1" preserveAspectRatio="none" aria-hidden="true"><polygon points="" vector-effect="non-scaling-stroke"/></svg>
          <div class="frame-guide" aria-hidden="true"></div>
        </div></div>
        <div class="scan-controls">
          <button class="btn scan-side" data-act="pick" aria-label="从相册选择">${icon.photo}</button>
          <button class="shutter" data-act="shoot" aria-label="拍照" disabled></button>
          <span></span>
        </div>`
    } else if (step === 'crop') {
      html = head('校正边缘', found ? '拖动四角对准纸张' : '没找到完整边缘，请手动拖动四角') + `
        <div class="scan-body"><div class="crop">
          <img src="${photoUrl}" alt="拍到的送货单">
          <svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true"><polygon/></svg>
          ${[0, 1, 2, 3].map(i => `<span class="handle" tabindex="0" role="slider" aria-label="第 ${i + 1} 个角"></span>`).join('')}
        </div></div>
        ${err}
        <div class="scan-controls" style="grid-template-columns:1fr 1fr;gap:12px">
          <button class="btn" data-act="retake" ${busy ? 'disabled' : ''}>重拍</button>
          <button class="btn btn-primary" data-act="apply" ${busy ? 'disabled' : ''}>${busy ? '处理中…' : '下一步'}</button>
        </div>`
    } else {
      html = head('确认图片', '看清字迹再识别') + `
        <div class="scan-body"><div class="viewfinder" style="aspect-ratio:auto;background:transparent"><img src="${resultUrl}" alt="校正后的送货单" style="object-fit:contain"></div></div>
        <div class="effects" role="group" aria-label="图片效果">
          ${EFFECTS.map(([v, l]) => `<button class="btn" data-effect="${v}" aria-pressed="${effect === v}" ${busy ? 'disabled' : ''}>${l}</button>`).join('')}
        </div>
        <div class="scan-controls" style="grid-template-columns:1fr 1.4fr;gap:12px">
          <button class="btn" data-act="recrop" ${busy ? 'disabled' : ''}>调整边缘</button>
          <button class="btn btn-primary" data-act="finish" ${busy ? 'disabled' : ''}>识别这张</button>
        </div>`
    }
    root.innerHTML = `<div class="scan screen${step !== lastStep ? ' enter' : ''}">${html}</div>`
    lastStep = step
    root.append(fileInput, nativeInput)
    if (step === 'crop') bindCorners(root.querySelector('.crop'))
  }

  root.addEventListener('click', e => {
    const t = e.target.closest('[data-act],[data-effect]'); if (!t || t.disabled) return
    const act = t.dataset.act
    if (t.dataset.effect) { if (t.dataset.effect !== effect) updatePreview(t.dataset.effect, false); return }
    if (act === 'back') { if (step === 'ready') { destroy(); onCancel() } else { stopCamera(); step = step === 'result' ? 'crop' : 'ready'; render() } }
    if (act === 'camera') openCamera()
    if (act === 'pick') { if (step === 'camera') { stopCamera(); step = 'ready'; render() } fileInput.click() }
    if (act === 'native') nativeInput.click()
    if (act === 'shoot') takePhoto()
    if (act === 'retake') { step = 'ready'; render() }
    if (act === 'apply') updatePreview(effect, true)
    if (act === 'recrop') { step = 'crop'; render() }
    if (act === 'finish') finish()
  })

  const onHidden = () => { if (document.hidden && step === 'camera') { stopCamera(); step = 'ready'; render() } }
  document.addEventListener('visibilitychange', onHidden)
  function destroy() { stopCamera(); document.removeEventListener('visibilitychange', onHidden) }

  render()
  return { destroy }
}
