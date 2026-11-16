// 客户流失态势三维场景：组装海天（scene/ocean）、货轮（scene/shipModel）、集装箱（scene/containerKit），
// 逐帧让货箱追随 shipLayout 原地更新的位置。不持有业务状态；由 ChurnShipStage 动态加载。
import * as THREE from 'three'
import { DECK } from './shipLayout'
import { createContainerKit, sizeOf, CONTAINER_SIZES } from './scene/containerKit'
import { createOcean, waveHeight } from './scene/ocean'
import { buildShip } from './scene/shipModel'
import { createPostFX } from './scene/postfx'

const DECK_Y = 2.0
const CARGO_Y = DECK_Y + 0.22 // 舱盖顶面
const FALL_SECONDS = 1.25
const MAX_FALLING = 8
// 低角度斜阳（仰角约 20°）：影子拉长、体积感强，天空近海平线泛暖
const SUN_DIRECTION = new THREE.Vector3(-0.58, 0.36, 0.73).normalize()

function cssColor(name) {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return value ? new THREE.Color(value) : new THREE.Color(0.5, 0.5, 0.5) // 令牌缺失时退回中性灰
}
const damp = (a, b, k, dt) => a + (b - a) * (1 - Math.exp(-k * dt))

function markTexture(ch, ink, paper) {
  const canvas = document.createElement('canvas')
  canvas.width = canvas.height = 64
  const g = canvas.getContext('2d')
  g.fillStyle = paper
  g.beginPath(); g.arc(32, 32, 30, 0, Math.PI * 2); g.fill()
  g.fillStyle = ink
  g.font = '600 38px "PingFang SC", "Microsoft YaHei", sans-serif'
  g.textAlign = 'center'; g.textBaseline = 'middle'
  g.fillText(ch, 32, 35)
  const texture = new THREE.CanvasTexture(canvas)
  texture.colorSpace = THREE.SRGBColorSpace
  return texture
}

function readColors() {
  const map = {
    stable: '--churn-stable', warning: '--churn-warning', critical: '--churn-critical', fallen: '--churn-fallen',
    hullTop: '--churn-hull-top', hullBoot: '--churn-hull-boot', band: '--churn-hull-band', deck: '--churn-deck',
    deckAlt: '--churn-deck-alt', hatch: '--churn-hatch', structure: '--churn-structure', edge: '--churn-edge',
    accent: '--churn-brand', brandDeep: '--churn-brand-deep', pink: '--churn-brand-pink', rim: '--churn-rim',
    window: '--churn-window', lifeboat: '--churn-lifeboat',
    seaDeep: '--churn-sea-deep', seaShallow: '--churn-sea-shallow', foam: '--churn-foam', horizon: '--churn-horizon',
    lightSky: '--churn-light-sky', lightGround: '--churn-light-ground', lightSun: '--churn-light-sun', splash: '--churn-splash',
  }
  return Object.fromEntries(Object.entries(map).map(([key, token]) => [key, cssColor(token)]))
}

export function createShipScene(canvas, { reduced = false, onFrame } = {}) {
  const C = readColors()
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, powerPreference: 'high-performance' })
  // 清晰度自适应：先按屏幕最高 2 倍渲染，实测持续掉帧再逐级降到 1 倍（只降不升，避免来回跳）
  let pixelRatio = Math.min(window.devicePixelRatio || 1, 2)
  renderer.setPixelRatio(pixelRatio)
  renderer.toneMapping = THREE.ACESFilmicToneMapping
  renderer.toneMappingExposure = 0.7
  renderer.shadowMap.enabled = true
  renderer.shadowMap.type = THREE.PCFSoftShadowMap
  const scene = new THREE.Scene()
  const camera = new THREE.PerspectiveCamera(32, 1, 1, 5000)

  const post = createPostFX({ renderer, scene, camera, width: canvas.clientWidth || 1, height: canvas.clientHeight || 1, reduced })
  const ocean = createOcean({ renderer, scene, colors: C, sunDirection: SUN_DIRECTION })
  scene.add(new THREE.HemisphereLight(C.lightSky, C.lightGround, 0.45))
  const sun = new THREE.DirectionalLight(C.lightSun, 2.7)
  sun.position.copy(SUN_DIRECTION).multiplyScalar(90)
  sun.castShadow = true
  sun.shadow.mapSize.set(4096, 4096)
  sun.shadow.bias = -0.0003
  sun.shadow.normalBias = 0.02
  sun.shadow.radius = 3
  scene.add(sun, sun.target)
  // 冷色逆光：从船后上方勾出船体、货箱和驾驶楼的轮廓
  const rim = new THREE.DirectionalLight(C.rim, 0.9)
  rim.position.set(25, 30, -70)
  scene.add(rim)
  scene.environmentIntensity = 0.9

  const kit = createContainerKit({ darkColor: C.edge.clone().lerp(C.hullTop, 0.25) })
  const ink = `#${C.hullTop.getHexString()}`, paper = `#${C.structure.getHexString()}`
  const marks = { follow: markTexture('跟', ink, paper), order: markTexture('单', ink, paper) }
  const markGeo = new THREE.PlaneGeometry(0.52, 0.52)
  const strapMat = new THREE.MeshStandardMaterial({ color: C.edge, roughness: 0.7 })
  const strapGeos = Object.fromEntries(Object.entries(CONTAINER_SIZES).map(([key, d]) => [key, new THREE.BoxGeometry(0.07, 0.03, d.d + 0.03)]))

  // 水花：每次落水一圈白环 + 一簇向上溅起的水珠
  const ringGeo = new THREE.RingGeometry(0.55, 0.72, 32)
  const splashes = Array.from({ length: 8 }, () => {
    const ring = new THREE.Mesh(ringGeo, new THREE.MeshBasicMaterial({ color: C.splash, transparent: true, opacity: 0, side: THREE.DoubleSide, depthWrite: false }))
    ring.rotation.x = -Math.PI / 2
    const count = 36
    const geo = new THREE.BufferGeometry()
    geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(count * 3), 3))
    const drops = new THREE.Points(geo, new THREE.PointsMaterial({ color: C.foam, size: 0.16, transparent: true, opacity: 0, depthWrite: false }))
    const vel = new Float32Array(count * 3)
    ring.visible = drops.visible = false
    scene.add(ring, drops)
    return { ring, drops, vel, t: 1 }
  })
  function splash(x, z) {
    const s = splashes.find(item => item.t >= 1) || splashes[0]
    s.t = 0
    s.ring.position.set(x, 0.35, z)
    s.ring.visible = s.drops.visible = true
    const pos = s.drops.geometry.attributes.position.array
    for (let i = 0; i < pos.length; i += 3) {
      const a = Math.random() * Math.PI * 2, r = 0.6 + Math.random() * 1.6
      pos[i] = x; pos[i + 1] = 0.3; pos[i + 2] = z
      s.vel[i] = Math.cos(a) * r; s.vel[i + 1] = 3 + Math.random() * 3.5; s.vel[i + 2] = Math.sin(a) * r
    }
    s.drops.geometry.attributes.position.needsUpdate = true
  }

  let world = null, ship = null, model = null, boxes = new Map(), pickables = [], seaTime = 0
  let seaOn = !reduced, snap = true, selectedId = null, hoveredId = null, filter = null, focusX = null
  const cam = { target: new THREE.Vector3(), dist: 100, tTarget: new THREE.Vector3(), tDist: 100 }
  // 俯角约 28°：甲板仍看得清，画面上缘落到远处海面，融进海平线雾气
  const camDir = new THREE.Vector3(-0.2, 0.48, 0.86).normalize()
  const viewDir = camDir.clone(), UP = new THREE.Vector3(0, 1, 0)
  let breath = 0
  const worldOwned = []

  function clearWorld() {
    if (!world) return
    for (const obj of worldOwned) obj.dispose?.()
    worldOwned.length = 0
    ship?.dispose()
    scene.remove(world)
    world = null
  }

  function setModel(next) {
    clearWorld()
    model = next
    world = new THREE.Group()
    scene.add(world)
    boxes = new Map(); pickables = []
    ship = buildShip({ deckLength: model.length, halfBeam: DECK.HALF, deckY: DECK_Y, colors: C, regions: model.regions, pitch: DECK.PITCH })
    world.add(ship.group)
    ship.group.traverse(obj => { if (obj.userData.region) pickables.push(obj) })
    ocean.setHull(ship.halfLength + 0.6, DECK.HALF + 1.2, ship.centerX)
    // 阴影相机只罩住整船和近旁海面：同样 4096 贴图，覆盖越小边缘越锐利
    Object.assign(sun.shadow.camera, { left: -(ship.halfLength + 8), right: ship.halfLength + 8, top: DECK.HALF + 16, bottom: -(DECK.HALF + 16), near: 20, far: 200 })
    sun.shadow.camera.updateProjectionMatrix()
    sun.target.position.set(ship.centerX, 0, 0)
    sun.position.set(ship.centerX, 0, 0).addScaledVector(SUN_DIRECTION, 100)

    // 稳固箱垛：一箱约代表四家稳固的 B/C 级与未定级客户
    const stackSets = [0, 1, 2].map(i => kit.materials(C.stable.clone(), i))
    stackSets.forEach(set => worldOwned.push(...set.all))
    for (const region of model.regions) {
      const count = Math.min(region.cols * 4, Math.ceil(region.stackCount / 4))
      for (let i = 0; i < count; i++) {
        const mesh = new THREE.Mesh(kit.geometries.mid, stackSets[(i * 7 + region.cols) % stackSets.length].list)
        mesh.position.set(region.x0 + ((i % region.cols) + 0.5) * DECK.PITCH, CARGO_Y + CONTAINER_SIZES.mid.h / 2 + Math.floor(i / region.cols) * 0.92, 0)
        mesh.castShadow = mesh.receiveShadow = true
        mesh.userData.region = region.key
        world.add(mesh); pickables.push(mesh)
      }
    }
    // 单独绘制的客户箱
    for (const item of model.items) {
      const size = sizeOf(item.level), d = CONTAINER_SIZES[size]
      const mats = kit.materials(C.stable.clone(), item.id)
      worldOwned.push(...mats.all)
      const mesh = new THREE.Mesh(kit.geometries[size], mats.list)
      mesh.castShadow = mesh.receiveShadow = true
      const edgeMat = new THREE.LineBasicMaterial({ color: C.structure.clone(), transparent: true, opacity: 0 })
      worldOwned.push(edgeMat)
      const edge = new THREE.LineSegments(kit.edges[size], edgeMat)
      edge.scale.setScalar(1.015)
      mesh.add(edge)
      const straps = [-1, 1].map(k => {
        const strap = new THREE.Mesh(strapGeos[size], strapMat)
        strap.position.set(k * d.w * 0.3, d.h / 2 + 0.016, 0)
        mesh.add(strap); return strap
      })
      const markMat = new THREE.MeshBasicMaterial({ map: marks.follow, transparent: true })
      worldOwned.push(markMat)
      const mark = new THREE.Mesh(markGeo, markMat)
      mark.rotation.x = -Math.PI / 2; mark.position.y = d.h / 2 + 0.04
      mesh.add(mark)
      mesh.visible = false
      mesh.userData.itemId = item.id
      boxes.set(item.id, { item, mesh, paint: mats.paint, mats: mats.all, edge, straps, mark, d, mode: 'deck', pos: new THREE.Vector3(), rx: 0, ry: 0, rz: 0, scale: 1, fall: null, flash: 0 })
      world.add(mesh); pickables.push(mesh)
    }
    // 浮标：每个市场一枚，漂在该市场海域
    const buoyBody = new THREE.MeshStandardMaterial({ color: C.accent, roughness: 0.4, metalness: 0.3 })
    const buoyBase = new THREE.MeshStandardMaterial({ color: C.structure, roughness: 0.5 })
    const buoyLight = new THREE.MeshBasicMaterial({ color: C.window })
    worldOwned.push(buoyBody, buoyBase, buoyLight)
    for (const region of model.regions) {
      const buoy = new THREE.Group()
      const base = new THREE.Mesh(new THREE.CylinderGeometry(0.8, 0.9, 0.5, 16), buoyBase); base.position.y = 0.15
      const body = new THREE.Mesh(new THREE.ConeGeometry(0.55, 1.6, 16), buoyBody); body.position.y = 1.15
      const lamp = new THREE.Mesh(new THREE.SphereGeometry(0.14, 12, 8), buoyLight); lamp.position.y = 2.05
      for (const part of [base, body, lamp]) { part.castShadow = true; worldOwned.push(part.geometry); buoy.add(part) }
      buoy.position.set(region.xc, 0, DECK.HALF + 15.5)
      buoy.userData.buoy = true
      world.add(buoy)
    }
    snap = true
    fit(true)
  }

  function fit(instant) {
    const w = canvas.clientWidth || 1, h = canvas.clientHeight || 1
    renderer.setSize(w, h, false)
    post?.setSize(w, h, renderer.getPixelRatio())
    camera.aspect = w / h
    camera.updateProjectionMatrix()
    const L = (ship ? ship.halfLength * 2 : model?.length) || 60
    const vf = (camera.fov * Math.PI) / 360, hf = Math.atan(Math.tan(vf) * camera.aspect)
    const full = Math.max((L + 10) / 2 / Math.tan(hf), (DECK.HALF * 2 + 40) / 2 / Math.tan(vf) * 0.8)
    const cx = ship ? ship.centerX - 2 : -1
    if (focusX !== null) { cam.tTarget.set(focusX, 0, 1.5); cam.tDist = Math.max(full * 0.5, 62) }
    else { cam.tTarget.set(cx, 0, 5); cam.tDist = full }
    if (instant) { cam.target.copy(cam.tTarget); cam.dist = reduced || !snap ? cam.tDist : cam.tDist * 0.84 }
  }

  let fallQueue = 0
  function tick(dt, now) {
    fallQueue = 0
    for (const box of boxes.values()) {
      const { item, mesh } = box
      if (!item.visible) { mesh.visible = false; box.mode = 'deck'; continue }
      const deckY = CARGO_Y + box.d.h / 2 + item.stack * (box.d.h + 0.02)
      const fallen = item.tier === 'fallen'
      if (!mesh.visible || snap) {
        mesh.visible = true
        box.scale = snap ? 1 : 0.9
        if (fallen) { box.mode = 'sea'; box.pos.set(item.x, 0.1, item.z); box.rx = (item.h2 - 0.5) * 0.5; box.rz = (item.h1 - 0.5) * 0.5; box.ry = item.h1 * 6 }
        else { box.mode = 'deck'; box.pos.set(item.x, deckY, item.z); box.rx = box.rz = box.ry = 0 }
      }
      if (fallen && box.mode === 'deck') {
        const active = [...boxes.values()].filter(b => b.mode === 'falling').length
        if (reduced || active >= MAX_FALLING) { box.mode = 'sea'; box.pos.set(item.x, 0.1, item.z); box.flash = 1 }
        else { box.mode = 'falling'; box.fall = { t: -fallQueue++ * 0.08, p0: box.pos.clone(), done: false } }
      }
      if (!fallen && box.mode !== 'deck') { box.mode = 'deck'; box.fall = null }
      if (box.mode === 'deck') {
        box.pos.x = damp(box.pos.x, item.x, 9, dt); box.pos.y = damp(box.pos.y, deckY, 9, dt); box.pos.z = damp(box.pos.z, item.z, 9, dt)
        const loose = item.row?.strap === 'loose'
        box.rx = damp(box.rx, 0, 10, dt); box.rz = damp(box.rz, 0, 10, dt); box.ry = damp(box.ry, loose ? (item.h2 - 0.5) * 0.36 : 0, 8, dt)
      } else if (box.mode === 'falling') {
        const f = box.fall
        f.t += dt
        if (f.t > 0) {
          const u = Math.min(f.t / FALL_SECONDS, 1), edge = item.side * (DECK.HALF + 0.9), out = edge + item.side * 1.9
          if (u < 0.3) { const k = (u / 0.3) ** 2; box.pos.z = f.p0.z + (edge - f.p0.z) * k }
          else if (u < 0.62) { const k = (u - 0.3) / 0.32; box.pos.z = edge + (out - edge) * k; box.pos.y = f.p0.y + (-0.9 - f.p0.y) * k * k; box.rx = item.side * 1.7 * k }
          else {
            if (!f.done) { f.done = true; splash(box.pos.x, box.pos.z) }
            const k = (u - 0.62) / 0.38, e = 1 - (1 - k) ** 3
            box.pos.y = -0.9 + (waveHeight(box.pos.x, box.pos.z, seaTime) + 1.0) * e
            box.pos.z = out + (item.z - out) * 0.12 * e
            box.rx = item.side * 1.7 + ((item.h2 - 0.5) * 0.5 - item.side * 1.7) * e
          }
          if (u >= 1) { box.mode = 'sea'; box.fall = null }
        }
      } else {
        box.pos.x = damp(box.pos.x, item.x, 0.7, dt); box.pos.z = damp(box.pos.z, item.z, 0.7, dt)
        box.pos.y = waveHeight(box.pos.x, box.pos.z, seaTime) + 0.1 // 箱子半浸在水里
        const bob = seaOn ? Math.sin(now * 0.9 + item.h1 * 9) * 0.05 : 0
        box.rx = damp(box.rx, (item.h2 - 0.5) * 0.5 + bob, 3, dt); box.rz = damp(box.rz, (item.h1 - 0.5) * 0.5, 3, dt); box.ry = damp(box.ry, item.h1 * 6, 2, dt)
      }
      box.scale = damp(box.scale, 1, 12, dt)
      mesh.position.copy(box.pos); mesh.rotation.set(box.rx, box.ry, box.rz); mesh.scale.setScalar(box.scale)
      const tier = box.mode === 'deck' ? item.tier : box.mode === 'falling' ? 'critical' : 'fallen'
      const target = C[tier] || C.stable
      const pulse = item.tier === 'critical' && box.mode === 'deck' ? (reduced ? 0.18 : 0.1 + 0.12 * (0.5 + 0.5 * Math.sin(now * 2.6))) : 0
      box.flash = Math.max(0, box.flash - dt * 1.6)
      const dim = filter ? !filter(item) : false
      box.paint.color.lerp(target, 1 - Math.exp(-8 * dt))
      box.paint.emissive.copy(C.critical).multiplyScalar(pulse).addScalar(box.flash * 0.4)
      for (const mat of box.mats) { mat.transparent = dim; mat.opacity = dim ? 0.16 : 1 }
      mesh.castShadow = !dim
      const onDeck = box.mode === 'deck'
      const strap = item.row?.strap
      box.straps.forEach((s, i) => { s.visible = onDeck && strap && strap !== 'none'; s.rotation.y = strap === 'loose' ? (i ? -0.5 : 0.38) : 0 })
      box.mark.visible = onDeck && item.tier !== 'stable' && Boolean(item.row?.clock)
      if (box.mark.visible) box.mark.material.map = marks[item.row.clock] || marks.follow
      const hot = item.id === selectedId || item.id === hoveredId
      box.edge.material.opacity = damp(box.edge.material.opacity, hot ? 1 : 0, 18, dt)
    }
    snap = false
    for (const s of splashes) {
      if (s.t >= 1) continue
      s.t += dt / 0.9
      const k = Math.min(s.t, 1), e = 1 - (1 - k) ** 3
      s.ring.scale.setScalar(1 + e * 4.5)
      s.ring.material.opacity = 0.8 * (1 - k)
      const pos = s.drops.geometry.attributes.position.array
      for (let i = 0; i < pos.length; i += 3) {
        s.vel[i + 1] -= 9.8 * dt
        pos[i] += s.vel[i] * dt; pos[i + 1] = Math.max(0.1, pos[i + 1] + s.vel[i + 1] * dt); pos[i + 2] += s.vel[i + 2] * dt
      }
      s.drops.geometry.attributes.position.needsUpdate = true
      s.drops.material.opacity = 0.95 * (1 - k)
      if (s.t >= 1) s.ring.visible = s.drops.visible = false
    }
    world?.children.forEach(child => {
      if (!child.userData.buoy) return
      child.position.y = waveHeight(child.position.x, child.position.z, seaTime) - 0.05
      child.rotation.z = Math.sin(seaTime * 0.9 + child.position.x) * 0.08
    })
    if (seaOn) ship?.tick(dt) // 雷达旋转与海面同属氛围动效，减少动态时一起停
    cam.target.lerp(cam.tTarget, 1 - Math.exp(-7 * dt)); cam.dist = damp(cam.dist, cam.tDist, 7, dt)
    // 镜头呼吸：极慢地左右环绕约 ±2.5°、上下浮动，像手持航拍；减少动态时静止
    if (seaOn) {
      breath += dt
      viewDir.copy(camDir).applyAxisAngle(UP, Math.sin(breath * 0.16) * 0.044)
      viewDir.y += Math.sin(breath * 0.23) * 0.012
      viewDir.normalize()
    } else viewDir.copy(camDir)
    camera.position.copy(cam.target).addScaledVector(viewDir, cam.dist)
    camera.lookAt(cam.target)
  }

  const projected = new THREE.Vector3()
  function project(x, y, z) {
    projected.set(x, y, z).project(camera)
    return { x: ((projected.x + 1) / 2) * canvas.clientWidth, y: ((1 - projected.y) / 2) * canvas.clientHeight, behind: projected.z > 1 }
  }

  let raf = 0, last = 0, running = false
  const intervals = []
  function adaptResolution(interval) {
    intervals.push(interval)
    if (intervals.length < 45) return
    const sorted = [...intervals].sort((a, b) => a - b)
    intervals.length = 0
    if (sorted[Math.floor(sorted.length / 2)] <= 0.046) return // 中位帧间隔 > 46ms ≈ 低于 22 帧才降
    if (post.degrade()) return // 先关环境光遮蔽，再关泛光，最后才降分辨率
    if (pixelRatio > 1) {
      pixelRatio = Math.max(1, pixelRatio - 0.25)
      renderer.setPixelRatio(pixelRatio)
      fit(false)
    }
  }
  function loop(nowMs) {
    raf = requestAnimationFrame(loop)
    const raw = (nowMs - last) / 1000
    const dt = Math.max(0, Math.min(raw, 0.05))
    if (dt < 1 / 31 && !snap) return // 帧率上限 30
    last = nowMs
    if (raw < 0.5) adaptResolution(raw) // 切回标签页等长停顿不计
    if (seaOn) seaTime += dt
    ocean.setTime(seaTime)
    if (model) tick(dt, nowMs / 1000)
    post.render(nowMs / 1000)
    onFrame?.(project)
  }
  function start() { if (running) return; running = true; last = performance.now(); intervals.length = 0; raf = requestAnimationFrame(loop) }
  function stop() { running = false; cancelAnimationFrame(raf) }

  const ray = new THREE.Raycaster(), pointer = new THREE.Vector2()
  function pick(clientX, clientY) {
    const rect = canvas.getBoundingClientRect()
    pointer.set(((clientX - rect.left) / rect.width) * 2 - 1, -((clientY - rect.top) / rect.height) * 2 + 1)
    ray.setFromCamera(pointer, camera)
    const hit = ray.intersectObjects(pickables.filter(m => m.visible), false)[0]
    if (!hit) return null
    if (hit.object.userData.itemId != null) return { itemId: hit.object.userData.itemId }
    return hit.object.userData.region ? { region: hit.object.userData.region } : null
  }

  return {
    setModel,
    jump() { snap = true },
    setFocus(region) { focusX = region ? model?.regions.find(r => r.key === region)?.xc ?? null : null; fit(false) },
    jumpCamera() { cam.target.copy(cam.tTarget); cam.dist = cam.tDist },
    setSelected(id) { selectedId = id },
    setHovered(id) { hoveredId = id },
    setFilter(fn) { filter = fn },
    setSea(on) { seaOn = on && !reduced },
    resize() { fit(false) },
    pick, start, stop, project,
    dispose() {
      stop()
      clearWorld()
      kit.dispose(); ocean.dispose()
      Object.values(marks).forEach(t => t.dispose())
      Object.values(strapGeos).forEach(g => g.dispose())
      markGeo.dispose(); strapMat.dispose(); ringGeo.dispose()
      for (const s of splashes) { s.ring.material.dispose(); s.drops.geometry.dispose(); s.drops.material.dispose() }
      post.dispose()
      renderer.dispose()
      renderer.forceContextLoss?.()
    },
  }
}
