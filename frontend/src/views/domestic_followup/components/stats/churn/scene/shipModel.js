// 货轮模型：放样船体（V 形底、外飘船首、方尾）+ 分段涂装 + 舷墙栏杆 + 驾驶楼 + 烟囱 + 舱盖与绑扎桥。
// 坐标：x 沿船长（+x 船首），y 向上（0 = 水线），z 横向；甲板面在 y = deckY。
import * as THREE from 'three'
import { mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils.js'

const SECTION_POINTS = 18 // 半截面采样点

/** 船长方向 u∈[0,1]（0 船尾，1 船首）处的半宽系数、龙骨抬升、甲板外飘。 */
function hullShape(u) {
  const bowStart = 0.82, sternEnd = 0.08
  let beam = 1, keelRise = 0, flare = 0
  if (u > bowStart) {
    const k = (u - bowStart) / (1 - bowStart)
    beam = Math.sqrt(Math.max(0, 1 - k * k * k)) * (1 - 0.06 * k)
    keelRise = Math.pow(k, 2.2) * 0.85
    flare = k * 0.18
  } else if (u < sternEnd) {
    const k = 1 - u / sternEnd
    beam = 1 - 0.12 * k * k
    keelRise = k * k * 0.55
  }
  return { beam, keelRise, flare }
}

/** 半截面轮廓：从甲板边缘向下到龙骨，船舭圆弧过渡；返回 [z, y] 列表（z ≥ 0）。 */
function sectionProfile(halfBeam, deckY, draft, keelRise, flare) {
  const pts = []
  const bottom = -draft + keelRise * (deckY + draft)
  const bilge = Math.min(halfBeam * 0.35, (deckY - bottom) * 0.45)
  for (let i = 0; i <= SECTION_POINTS; i++) {
    const t = i / SECTION_POINTS
    let z, y
    if (t < 0.55) { // 舷侧：上部微外飘
      const k = t / 0.55
      y = deckY - k * (deckY - bottom - bilge)
      z = halfBeam * (1 + flare * (1 - k))
    } else if (t < 0.85) { // 船舭圆弧
      const a = ((t - 0.55) / 0.3) * (Math.PI / 2)
      z = halfBeam - bilge + Math.cos(a) * bilge
      y = bottom + bilge - Math.sin(a) * bilge
    } else { // 船底，略带斜升
      const k = (t - 0.85) / 0.15
      z = (halfBeam - bilge) * (1 - k)
      y = bottom + k * 0.08
    }
    pts.push([z, y])
  }
  return pts
}

function paintColor(y, deckY, colors, out) {
  if (y < -0.05) out.copy(colors.band)                // 水下防污漆
  else if (y < 0.55) out.copy(colors.hullBoot)       // 白色水线带
  else out.copy(colors.hullTop)                      // 干舷
  if (y > deckY - 0.35) out.lerp(colors.hullBoot, 0.25) // 甲板沿口一道浅色
  return out
}

function buildHullGeometry(sternX, bowX, halfBeam, deckY, draft, colors) {
  const sections = 64
  const ring = SECTION_POINTS * 2 + 1
  const positions = [], vcolors = [], indices = []
  const c = new THREE.Color()
  const length = bowX - sternX
  for (let s = 0; s <= sections; s++) {
    const u = s / sections
    const { beam, keelRise, flare } = hullShape(u)
    const x = sternX + u * length + (u > 0.82 ? Math.pow((u - 0.82) / 0.18, 2) * 1.6 : 0) // 船首前倾
    const profile = sectionProfile(Math.max(halfBeam * beam, 0.02), deckY, draft, keelRise, flare)
    // 左舷（-z）自上而下，再右舷（+z）自下而上，组成一圈
    const loop = [...profile.map(([z, y]) => [-z, y]), ...profile.slice(0, -1).reverse().map(([z, y]) => [z, y])]
    for (const [z, y] of loop) {
      positions.push(x, y, z)
      paintColor(y, deckY, colors, c)
      vcolors.push(c.r, c.g, c.b)
    }
  }
  for (let s = 0; s < sections; s++) {
    for (let i = 0; i < ring - 1; i++) {
      const a = s * ring + i, b = a + 1, d = (s + 1) * ring + i, e = d + 1
      indices.push(a, d, b, b, d, e)
    }
  }
  // 方尾封板
  const base = positions.length / 3
  const stern = []
  for (let i = 0; i < ring; i++) stern.push(i)
  const center = base
  positions.push(sternX, deckY * 0.2, 0)
  paintColor(0.6, deckY, colors, c); vcolors.push(c.r, c.g, c.b)
  for (let i = 0; i < ring - 1; i++) indices.push(center, stern[i + 1], stern[i])
  const geometry = new THREE.BufferGeometry()
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3))
  geometry.setAttribute('color', new THREE.Float32BufferAttribute(vcolors, 3))
  geometry.setIndex(indices)
  geometry.computeVertexNormals()
  return geometry
}

function buildDeckGeometry(sternX, bowX, halfBeam, deckY) {
  const shape = new THREE.Shape()
  const steps = 40, length = bowX - sternX
  const edge = []
  for (let s = 0; s <= steps; s++) {
    const u = s / steps
    const { beam, flare } = hullShape(u)
    const x = sternX + u * length + (u > 0.82 ? Math.pow((u - 0.82) / 0.18, 2) * 1.6 : 0)
    edge.push([x, Math.max(halfBeam * beam * (1 + flare), 0.02)])
  }
  shape.moveTo(edge[0][0], -edge[0][1])
  for (const [x, z] of edge) shape.lineTo(x, -z)
  for (const [x, z] of [...edge].reverse()) shape.lineTo(x, z)
  shape.closePath()
  const geometry = new THREE.ShapeGeometry(shape, 1)
  geometry.rotateX(-Math.PI / 2) // 形状平面转成水平，法线朝上
  geometry.translate(0, deckY, 0)
  return { geometry, edge }
}

function nameTexture(text) {
  const canvas = document.createElement('canvas')
  canvas.width = 1024; canvas.height = 128
  const g = canvas.getContext('2d')
  g.fillStyle = '#ffffff'
  g.font = '700 92px "Helvetica Neue", Arial, sans-serif'
  g.textAlign = 'center'; g.textBaseline = 'middle'
  g.fillText(text.split('').join(String.fromCharCode(8202)), 512, 68)
  const texture = new THREE.CanvasTexture(canvas)
  texture.colorSpace = THREE.SRGBColorSpace
  texture.anisotropy = 8
  return texture
}

/**
 * 组装整船。deckLength = 货区长度（shipLayout 给出），halfBeam = 甲板半宽。
 * 返回 { group, sternX, bowX, deckY, dispose }。
 */
export function buildShip({ deckLength, halfBeam, deckY, colors, regions, pitch }) {
  const group = new THREE.Group()
  const disposables = []
  const keep = obj => { disposables.push(obj); return obj }
  const sternX = -deckLength / 2 - 13
  const bowX = deckLength / 2 + 9
  const draft = 2.6

  const paint = keep(new THREE.MeshPhysicalMaterial({ vertexColors: true, roughness: 0.48, metalness: 0.15, clearcoat: 0.35, clearcoatRoughness: 0.3, side: THREE.DoubleSide }))
  const hull = new THREE.Mesh(keep(buildHullGeometry(sternX, bowX, halfBeam + 0.5, deckY, draft, colors)), paint)
  hull.castShadow = true; hull.receiveShadow = true
  group.add(hull)

  const { geometry: deckGeo, edge } = buildDeckGeometry(sternX, bowX, halfBeam + 0.5, deckY)
  const deckMat = keep(new THREE.MeshStandardMaterial({ color: colors.deck, roughness: 0.85, metalness: 0.05 }))
  const deck = new THREE.Mesh(keep(deckGeo), deckMat)
  deck.receiveShadow = true
  group.add(deck)

  // 舷墙：沿甲板边一圈矮墙，船首段加高
  const wallMat = keep(new THREE.MeshStandardMaterial({ color: colors.hullTop, roughness: 0.6, metalness: 0.2, side: THREE.DoubleSide }))
  const wallGeos = []
  for (const side of [-1, 1]) {
    for (let i = 0; i < edge.length - 1; i++) {
      const [x0, z0] = edge[i], [x1, z1] = edge[i + 1]
      const u = i / (edge.length - 1)
      const h = u > 0.8 ? 0.55 + (u - 0.8) * 3 : 0.32
      const seg = new THREE.PlaneGeometry(Math.hypot(x1 - x0, z1 - z0), h)
      seg.rotateY(-Math.atan2(side * (z1 - z0), x1 - x0))
      seg.translate((x0 + x1) / 2, deckY + h / 2, side * (z0 + z1) / 2)
      wallGeos.push(seg)
    }
  }
  const walls = new THREE.Mesh(keep(mergeGeometries(wallGeos)), wallMat)
  wallGeos.forEach(g => g.dispose())
  walls.castShadow = true
  group.add(walls)

  // 栏杆：船尾段两侧立柱 + 扶手
  const railMat = keep(new THREE.MeshStandardMaterial({ color: colors.structure, roughness: 0.4, metalness: 0.5 }))
  const postGeo = keep(new THREE.CylinderGeometry(0.03, 0.03, 0.7, 5))
  const railX0 = sternX + 0.6, railX1 = -deckLength / 2 - 1
  const postCount = Math.max(4, Math.round((railX1 - railX0) / 0.8))
  const posts = new THREE.InstancedMesh(postGeo, railMat, postCount * 2)
  const m = new THREE.Matrix4()
  let idx = 0
  for (const side of [-1, 1]) {
    for (let i = 0; i < postCount; i++) {
      m.makeTranslation(railX0 + (i / (postCount - 1)) * (railX1 - railX0), deckY + 0.35, side * (halfBeam + 0.35))
      posts.setMatrixAt(idx++, m)
    }
    const rail = new THREE.Mesh(keep(new THREE.CylinderGeometry(0.035, 0.035, railX1 - railX0, 6)), railMat)
    rail.rotation.z = Math.PI / 2
    rail.position.set((railX0 + railX1) / 2, deckY + 0.7, side * (halfBeam + 0.35))
    group.add(rail)
  }
  group.add(posts)

  // 舱盖与绑扎桥：每个市场分区一块舱盖，分区之间一道绑扎桥
  const hatchMat = keep(new THREE.MeshStandardMaterial({ color: colors.hatch, roughness: 0.7, metalness: 0.25 }))
  const hatchAltMat = keep(new THREE.MeshStandardMaterial({ color: colors.deckAlt, roughness: 0.7, metalness: 0.25 }))
  const bridgeMat = keep(new THREE.MeshStandardMaterial({ color: colors.hatch.clone().lerp(colors.structure, 0.35), roughness: 0.6, metalness: 0.45 }))
  regions.forEach((region, index) => {
    const hatch = new THREE.Mesh(keep(new THREE.BoxGeometry(region.len + 0.2, 0.22, halfBeam * 2 - 0.6)), index % 2 ? hatchAltMat : hatchMat)
    hatch.position.set(region.xc, deckY + 0.11, 0)
    hatch.receiveShadow = true; hatch.castShadow = true
    hatch.userData.region = region.key
    group.add(hatch)
    const x = region.x0 + region.len + pitch * 0.2
    for (const side of [-1, 1]) {
      const post = new THREE.Mesh(keep(new THREE.BoxGeometry(0.09, 1.7, 0.09)), bridgeMat)
      post.position.set(x, deckY + 0.85, side * (halfBeam - 0.2))
      post.castShadow = true
      group.add(post)
    }
    const beam = new THREE.Mesh(keep(new THREE.BoxGeometry(0.07, 0.07, halfBeam * 2 - 0.2)), bridgeMat)
    beam.position.set(x, deckY + 1.7, 0)
    beam.castShadow = true
    group.add(beam)
  })

  // 驾驶楼：三层生活区（退台）+ 通宽驾驶台（两翼外伸、正面前倾大玻璃、遮阳檐）+ 雷达桅 + 烟囱 + 吊艇架救生艇
  const plainMat = keep(new THREE.MeshPhysicalMaterial({ color: colors.structure, roughness: 0.42, metalness: 0.08, clearcoat: 0.3 }))
  const glassMat = keep(new THREE.MeshStandardMaterial({ color: colors.hullTop.clone().multiplyScalar(0.45), roughness: 0.06, metalness: 0.9, envMapIntensity: 1.4 }))
  const houseX = sternX + 5.2
  const living = [[6.2, 1.25, halfBeam * 2 - 3], [5.7, 1.15, halfBeam * 2 - 3.4], [5.2, 1.15, halfBeam * 2 - 3.8]]
  let y = deckY
  const paneSlots = []
  living.forEach(([w, h, d], i) => {
    const box = new THREE.Mesh(keep(new THREE.BoxGeometry(w, h, d)), plainMat)
    box.position.set(houseX + i * 0.25, y + h / 2, 0)
    // 实体窗格：每层一排，正面（+x）与两舷；约四分之一亮灯
    const cx = houseX + i * 0.25, cy = y + h * 0.55
    const along = (count, span) => Array.from({ length: count }, (_, k) => (k - (count - 1) / 2) * (span / count))
    for (const z of along(Math.floor(d / 0.62), d - 0.5)) paneSlots.push([cx + w / 2 + 0.012, cy, z, Math.PI / 2])
    for (const side of [-1, 1]) {
      for (const x of along(Math.floor(w / 0.62), w - 0.6)) paneSlots.push([cx + x, cy, side * (d / 2 + 0.012), side > 0 ? 0 : Math.PI])
    }
    box.castShadow = true; box.receiveShadow = true
    group.add(box)
    // 每层甲板一道外伸走廊边沿，打破白盒子的平整
    const ledge = new THREE.Mesh(keep(new THREE.BoxGeometry(w + 0.3, 0.07, d + 0.3)), plainMat)
    ledge.position.set(houseX + i * 0.25, y + h, 0)
    ledge.castShadow = true
    group.add(ledge)
    y += h
  })
  const paneGeo = keep(new THREE.PlaneGeometry(0.34, 0.38))
  const litMat = keep(new THREE.MeshStandardMaterial({ color: colors.window, emissive: colors.window, emissiveIntensity: 0.55, roughness: 0.3 }))
  const lit = paneSlots.filter((_, k) => (k * 7 + 3) % 4 === 0), darkPanes = paneSlots.filter((_, k) => (k * 7 + 3) % 4 !== 0)
  for (const [slots, mat] of [[darkPanes, glassMat], [lit, litMat]]) {
    const panes = new THREE.InstancedMesh(paneGeo, mat, slots.length)
    const o = new THREE.Object3D()
    slots.forEach(([x, py, z, ry], k) => { o.position.set(x, py, z); o.rotation.set(0, ry, 0); o.updateMatrix(); panes.setMatrixAt(k, o.matrix) })
    group.add(panes)
  }
  // 驾驶台：通宽，两翼伸出生活区
  const bridgeW = 3.6, bridgeH = 1.15, bridgeD = halfBeam * 2 - 0.4
  const bridgeX = houseX + 1.0
  const wheelhouse = new THREE.Mesh(keep(new THREE.BoxGeometry(bridgeW, bridgeH, bridgeD)), plainMat)
  wheelhouse.position.set(bridgeX, y + bridgeH / 2, 0)
  wheelhouse.castShadow = true; wheelhouse.receiveShadow = true
  group.add(wheelhouse)
  // 正面前倾大玻璃（顶部外倾，反射天空）+ 两翼侧窗
  const front = new THREE.Mesh(keep(new THREE.PlaneGeometry(bridgeD - 0.3, 0.62)), glassMat)
  front.rotation.set(0, Math.PI / 2, 0)
  front.rotateX(-0.22)
  front.position.set(bridgeX + bridgeW / 2 + 0.07, y + bridgeH * 0.58, 0)
  group.add(front)
  for (const side of [-1, 1]) {
    const wing = new THREE.Mesh(keep(new THREE.PlaneGeometry(bridgeW - 0.5, 0.5)), glassMat)
    wing.position.set(bridgeX, y + bridgeH * 0.6, side * (bridgeD / 2 + 0.01))
    if (side < 0) wing.rotation.y = Math.PI
    group.add(wing)
  }
  const visor = new THREE.Mesh(keep(new THREE.BoxGeometry(0.45, 0.06, bridgeD + 0.1)), plainMat)
  visor.position.set(bridgeX + bridgeW / 2 + 0.18, y + bridgeH - 0.02, 0)
  visor.castShadow = true
  group.add(visor)
  y += bridgeH
  const roof = new THREE.Mesh(keep(new THREE.BoxGeometry(bridgeW + 0.2, 0.1, bridgeD + 0.1)), plainMat)
  roof.position.set(bridgeX, y + 0.05, 0)
  roof.castShadow = true
  group.add(roof)
  // 雷达桅：桅杆 + 横桁 + 旋转天线 + 航行灯
  const mastMat = keep(new THREE.MeshStandardMaterial({ color: colors.structure, roughness: 0.35, metalness: 0.6 }))
  const mast = new THREE.Mesh(keep(new THREE.CylinderGeometry(0.07, 0.11, 2.6, 8)), mastMat)
  mast.position.set(bridgeX + 0.4, y + 1.3, 0)
  const yard = new THREE.Mesh(keep(new THREE.BoxGeometry(0.08, 0.08, 2.6)), mastMat)
  yard.position.set(bridgeX + 0.4, y + 1.8, 0)
  const radar = new THREE.Mesh(keep(new THREE.BoxGeometry(0.16, 0.07, 1.8)), mastMat)
  radar.position.set(bridgeX + 0.4, y + 2.25, 0)
  const lampMat = keep(new THREE.MeshBasicMaterial({ color: colors.window }))
  const lamp = new THREE.Mesh(keep(new THREE.SphereGeometry(0.08, 10, 8)), lampMat)
  lamp.position.set(bridgeX + 0.4, y + 2.65, 0)
  group.add(mast, yard, radar, lamp)
  // 烟囱坐在驾驶楼顶后半部：本体（干舷色）→ 金色公司色带（略凸出）→ 黑色烟囱帽
  const funnelTop = deckY + living.reduce((sum, [, h]) => sum + h, 0)
  const funnelX = houseX - 1.7, funnelH = 3.0
  const funnelBody = new THREE.Mesh(keep(new THREE.CylinderGeometry(0.78, 0.95, funnelH, 24)), keep(new THREE.MeshPhysicalMaterial({ color: colors.structure, roughness: 0.4, metalness: 0.1, clearcoat: 0.4 }))) // 白底绿带粉描边，对应 logo
  funnelBody.position.set(funnelX, funnelTop + funnelH / 2, 0)
  funnelBody.scale.z = 1.3
  funnelBody.castShadow = true
  const stripe = new THREE.Mesh(keep(new THREE.CylinderGeometry(0.85, 0.89, 0.75, 24)), keep(new THREE.MeshStandardMaterial({ color: colors.accent, roughness: 0.3, metalness: 0.45 })))
  const stripeEdge = new THREE.Mesh(keep(new THREE.CylinderGeometry(0.88, 0.9, 0.12, 24)), keep(new THREE.MeshStandardMaterial({ color: colors.pink, roughness: 0.35, metalness: 0.3 })))
  stripeEdge.scale.z = 1.3
  stripe.position.set(funnelX, funnelTop + funnelH * 0.62, 0)
  stripe.scale.z = 1.3
  stripeEdge.position.set(funnelX, funnelTop + funnelH * 0.62 + 0.43, 0) // logo 那道玫瑰粉描边
  const cap = new THREE.Mesh(keep(new THREE.CylinderGeometry(0.8, 0.8, 0.3, 24)), keep(new THREE.MeshStandardMaterial({ color: colors.edge, roughness: 0.85 })))
  cap.position.set(funnelX, funnelTop + funnelH + 0.12, 0)
  cap.scale.z = 1.3
  group.add(funnelBody, stripe, stripeEdge, cap)
  // 救生艇：橙色艇体 + 白色封闭艇顶，挂在两舷吊艇架上，略伸出生活区外墙
  const boatMat = keep(new THREE.MeshStandardMaterial({ color: colors.lifeboat, roughness: 0.45 }))
  const canopyMat = keep(new THREE.MeshStandardMaterial({ color: colors.structure, roughness: 0.4 }))
  const davitMat = keep(new THREE.MeshStandardMaterial({ color: colors.structure, roughness: 0.45, metalness: 0.5 }))
  const hullGeo = keep(new THREE.CapsuleGeometry(0.38, 2.0, 4, 12))
  const canopyGeo = keep(new THREE.CapsuleGeometry(0.33, 1.7, 4, 12))
  const postGeoD = keep(new THREE.BoxGeometry(0.1, 1.3, 0.1)), armGeo = keep(new THREE.BoxGeometry(0.1, 0.1, 0.9))
  const boatY = deckY + 2.55, wall = halfBeam - 1.5
  for (const side of [-1, 1]) {
    const z = side * (wall + 0.75)
    const hullBoat = new THREE.Mesh(hullGeo, boatMat)
    hullBoat.rotation.z = Math.PI / 2
    hullBoat.scale.set(1, 1, 0.85)
    hullBoat.position.set(houseX - 0.3, boatY, z)
    const canopy = new THREE.Mesh(canopyGeo, canopyMat)
    canopy.rotation.z = Math.PI / 2
    canopy.scale.set(0.75, 1, 0.8)
    canopy.position.set(houseX - 0.3, boatY + 0.28, z)
    hullBoat.castShadow = canopy.castShadow = true
    group.add(hullBoat, canopy)
    for (const dx of [-1.0, 0.9]) {
      const post = new THREE.Mesh(postGeoD, davitMat)
      post.position.set(houseX - 0.3 + dx, boatY + 0.1, side * (wall + 0.05))
      const arm = new THREE.Mesh(armGeo, davitMat)
      arm.position.set(houseX - 0.3 + dx, boatY + 0.72, side * (wall + 0.45))
      post.castShadow = arm.castShadow = true
      group.add(post, arm)
    }
  }
  // 船名：船首两舷，白字
  const nameTex = keep(nameTexture('LESHINE ARK'))
  const nameMat = keep(new THREE.MeshBasicMaterial({ map: nameTex, transparent: true, depthWrite: false, toneMapped: false, opacity: 0.92 }))
  const nameGeo = keep(new THREE.PlaneGeometry(5.6, 0.7))
  const nameX = sternX + (bowX - sternX) * 0.74
  for (const side of [-1, 1]) {
    const plate = new THREE.Mesh(nameGeo, nameMat)
    plate.position.set(nameX, deckY - 0.75, side * (halfBeam + 0.5 + 0.04))
    if (side < 0) plate.rotation.y = Math.PI
    group.add(plate)
  }

  return {
    group, sternX, bowX, deckY,
    halfLength: (bowX - sternX) / 2, centerX: (bowX + sternX) / 2,
    tick(dt) { radar.rotation.y += dt * 1.4 },
    dispose() { for (const obj of disposables) obj.dispose?.() },
  }
}
