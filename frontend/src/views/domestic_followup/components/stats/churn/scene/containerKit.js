// 集装箱套件：纯几何建模，不用任何贴图。
// 梯形截面瓦楞侧板 / 端板、角柱、上下边梁、顶板加强筋、四角角件、门端双门板 + 锁杆 + 把手 + 铰链。
// 底部接触暗部写在顶点颜色里；漆面颜色由材质 color 决定，同一套几何能套三档风险色。
import * as THREE from 'three'
import { mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils.js'

export const CONTAINER_SIZES = {
  big: { w: 1.5, h: 0.98, d: 1.15, ribs: 22, endRibs: 8 },   // 40 尺：S/A 级
  mid: { w: 1.05, h: 0.9, d: 1.1, ribs: 16, endRibs: 8 },    // 20 尺：B/C 级
  small: { w: 0.8, h: 0.7, d: 0.9, ribs: 12, endRibs: 6 },   // 未定级
}
export const sizeOf = level => (level === 'S级' || level === 'A级' ? 'big' : level ? 'mid' : 'small')

const T = 0.05      // 框架构件截面
const RIB = 0.032   // 瓦楞深度：要大到在全景距离也能被光影读出

/** 梯形瓦楞：一个周期 = 外平面 30% → 斜面 20% → 内平面 30% → 斜面 20%。返回 [u, depth] 列表。 */
function corrugationProfile(ribs) {
  const pts = []
  for (let i = 0; i < ribs; i++) {
    const s = i / ribs, p = 1 / ribs
    pts.push([s, 1], [s + p * 0.3, 1], [s + p * 0.5, 0], [s + p * 0.8, 0])
  }
  pts.push([1, 1])
  return pts
}

/**
 * 一块瓦楞板：沿局部 x 长 length、沿 y 高 height，瓦楞朝局部 +z 凸出 RIB。
 * 非索引几何，法线按三角面算，棱线清楚。
 */
function corrugatedPanel(length, height, ribs) {
  const profile = corrugationProfile(ribs)
  const pos = []
  for (let i = 0; i < profile.length - 1; i++) {
    const [u0, d0] = profile[i], [u1, d1] = profile[i + 1]
    const x0 = (u0 - 0.5) * length, x1 = (u1 - 0.5) * length
    const z0 = d0 * RIB, z1 = d1 * RIB
    const y0 = -height / 2, y1 = height / 2
    pos.push(x0, y0, z0, x1, y0, z1, x1, y1, z1, x0, y0, z0, x1, y1, z1, x0, y1, z0)
  }
  const geometry = new THREE.BufferGeometry()
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3))
  geometry.computeVertexNormals()
  return geometry
}

function box(w, h, d, x, y, z) {
  const g = new THREE.BoxGeometry(w, h, d).toNonIndexed()
  g.deleteAttribute('uv')
  g.translate(x, y, z)
  return g
}
function bar(radius, height, x, y, z) {
  const g = new THREE.CylinderGeometry(radius, radius, height, 6, 1).toNonIndexed()
  g.deleteAttribute('uv')
  g.translate(x, y, z)
  return g
}

/** 顶点颜色：shade 是构件本身的明暗，再乘底部接触暗部（越靠箱底越暗）。 */
function shadeGeometry(g, h, shade) {
  const p = g.attributes.position, colors = new Float32Array(p.count * 3)
  for (let i = 0; i < p.count; i++) {
    const k = THREE.MathUtils.clamp((p.getY(i) + h / 2) / (h * 0.45), 0, 1)
    const ao = 0.62 + 0.38 * (k * k * (3 - 2 * k))
    const v = shade * ao
    colors[i * 3] = colors[i * 3 + 1] = colors[i * 3 + 2] = v
  }
  g.setAttribute('color', new THREE.BufferAttribute(colors, 3))
  return g
}

function buildContainer({ w, h, d, ribs, endRibs }) {
  const paint = [], dark = []
  const innerW = w - T * 2, innerH = h - T * 2, innerD = d - T * 2
  // 两侧瓦楞板（±z）
  for (const side of [-1, 1]) {
    const panel = corrugatedPanel(innerW, innerH, ribs)
    if (side < 0) panel.rotateY(Math.PI)
    panel.translate(0, 0, side * (d / 2 - T * 0.7))
    paint.push(shadeGeometry(panel, h, 1))
  }
  // 后端瓦楞板（-x）
  const back = corrugatedPanel(innerD, innerH, endRibs)
  back.rotateY(-Math.PI / 2)
  back.translate(-(w / 2 - T * 0.7), 0, 0)
  paint.push(shadeGeometry(back, h, 0.96))
  // 门端（+x）：两扇平门板，中间留缝
  for (const side of [-1, 1]) {
    paint.push(shadeGeometry(box(0.012, innerH, innerD / 2 - 0.006, w / 2 - T * 0.55, 0, side * (innerD / 4 + 0.003)), h, 0.98))
  }
  // 顶板 + 横向加强筋；底板
  paint.push(shadeGeometry(box(innerW, 0.014, innerD, 0, h / 2 - T * 0.6, 0), h, 1.02))
  for (let i = 1; i < 7; i++) paint.push(shadeGeometry(box(0.018, 0.01, innerD, -innerW / 2 + (innerW * i) / 7, h / 2 - T * 0.45, 0), h, 0.95))
  paint.push(shadeGeometry(box(innerW, 0.02, innerD, 0, -h / 2 + T * 0.5, 0), h, 0.7))
  // 框架：角柱、上下侧梁、上下端梁（同漆面，明暗略深，读出框的轮廓）
  for (const sx of [-1, 1]) for (const sz of [-1, 1]) paint.push(shadeGeometry(box(T, h, T, sx * (w / 2 - T / 2), 0, sz * (d / 2 - T / 2)), h, 0.82))
  for (const sz of [-1, 1]) {
    paint.push(shadeGeometry(box(w, T, T, 0, h / 2 - T / 2, sz * (d / 2 - T / 2)), h, 0.88))
    paint.push(shadeGeometry(box(w, T * 1.3, T, 0, -h / 2 + T * 0.65, sz * (d / 2 - T / 2)), h, 0.78))
  }
  for (const sx of [-1, 1]) {
    paint.push(shadeGeometry(box(T, T, d, sx * (w / 2 - T / 2), h / 2 - T / 2, 0), h, 0.88))
    paint.push(shadeGeometry(box(T, T * 1.3, d, sx * (w / 2 - T / 2), -h / 2 + T * 0.65, 0), h, 0.78))
  }
  // 深色件：八个角件
  const c = T * 1.25
  for (const sx of [-1, 1]) for (const sy of [-1, 1]) for (const sz of [-1, 1]) {
    dark.push(box(c, c, c, sx * (w / 2 - c / 2 + 0.003), sy * (h / 2 - c / 2 + 0.003), sz * (d / 2 - c / 2 + 0.003)))
  }
  // 门端：四根锁杆（上下各一个锁座）+ 把手 + 每扇门三片铰链
  const doorX = w / 2 - T * 0.25
  for (const z of [-innerD * 0.36, -innerD * 0.14, innerD * 0.14, innerD * 0.36]) {
    dark.push(bar(0.009, innerH * 0.94, doorX + 0.012, 0, z))
    dark.push(box(0.03, 0.03, 0.035, doorX + 0.01, innerH * 0.47, z))
    dark.push(box(0.03, 0.03, 0.035, doorX + 0.01, -innerH * 0.47, z))
    dark.push(box(0.022, 0.012, 0.06, doorX + 0.025, -innerH * 0.08, z + 0.02))
  }
  for (const side of [-1, 1]) for (const y of [-0.32, 0, 0.32]) {
    dark.push(box(0.025, 0.05, 0.03, doorX + 0.005, y * innerH, side * (innerD / 2 - 0.01)))
  }
  const paintGeo = mergeGeometries(paint)
  const darkGeo = mergeGeometries(dark.map(g => shadeGeometry(g, h, 1)))
  paint.forEach(g => g.dispose()); dark.forEach(g => g.dispose())
  const geometry = mergeGeometries([paintGeo, darkGeo], true) // group 0 漆面，group 1 深色件
  paintGeo.dispose(); darkGeo.dispose()
  geometry.computeBoundingBox()
  geometry.computeBoundingSphere()
  return geometry
}

export function createContainerKit({ darkColor }) {
  const geometries = Object.fromEntries(Object.entries(CONTAINER_SIZES).map(([key, size]) => [key, buildContainer(size)]))
  const outline = Object.fromEntries(Object.entries(CONTAINER_SIZES).map(([key, { w, h, d }]) => {
    const b = new THREE.BoxGeometry(w, h, d)
    const e = new THREE.EdgesGeometry(b)
    b.dispose()
    return [key, e]
  }))

  /** variant 让每个箱子漆面粗糙度略有差异（新箱更亮、旧箱更哑），不靠贴图做磨损感。 */
  function materials(color, variant = 0) {
    const wear = ((Math.abs(variant) * 2654435761) >>> 0) / 4294967296
    const paint = new THREE.MeshPhysicalMaterial({
      color, vertexColors: true, metalness: 0.18, roughness: 0.46 + wear * 0.26,
      clearcoat: 0.22 - wear * 0.16, clearcoatRoughness: 0.35 + wear * 0.3, envMapIntensity: 0.6,
    })
    const dark = new THREE.MeshStandardMaterial({ color: darkColor, vertexColors: true, metalness: 0.6, roughness: 0.55 })
    return { list: [paint, dark], paint, all: [paint, dark] }
  }

  return {
    geometries, edges: outline, materials,
    dispose() {
      Object.values(geometries).forEach(g => g.dispose())
      Object.values(outline).forEach(g => g.dispose())
    },
  }
}
