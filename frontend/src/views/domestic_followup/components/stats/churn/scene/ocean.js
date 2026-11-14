// 海天与光照：物理天空 + 天空环境反射 + 自写海面着色器（多层波、菲涅尔、太阳高光、船舷白沫）。
import * as THREE from 'three'
import { Sky } from 'three/examples/jsm/objects/Sky.js'

// 海面高度：JS 与着色器同一组波，漂浮的货箱才贴得住水面
export const WAVES = [
  { dir: [0.92, 0.39], amp: 0.22, len: 34, speed: 0.55 },
  { dir: [-0.42, 0.91], amp: 0.14, len: 21, speed: 0.75 },
  { dir: [0.62, -0.78], amp: 0.08, len: 11, speed: 1.05 },
]
export function waveHeight(x, z, t) {
  let h = 0
  for (const w of WAVES) {
    const k = (Math.PI * 2) / w.len
    h += w.amp * Math.sin(k * (w.dir[0] * x + w.dir[1] * z) + t * w.speed)
  }
  return h
}

const waveGLSL = WAVES.map((w, i) => `
  {
    float k = ${((Math.PI * 2) / w.len).toFixed(5)};
    vec2 d = vec2(${w.dir[0].toFixed(3)}, ${w.dir[1].toFixed(3)});
    float ph = k * dot(d, p) + uTime * ${w.speed.toFixed(3)};
    h += ${w.amp.toFixed(3)} * sin(ph);
    grad += ${w.amp.toFixed(3)} * k * cos(ph) * d;
  }`).join('')

const vertexShader = `
  uniform float uTime;
  varying vec3 vWorld;
  varying vec2 vGrad;
  void main() {
    vec3 pos = position;
    vec2 p = pos.xz;
    float h = 0.0; vec2 grad = vec2(0.0);
    ${waveGLSL}
    pos.y += h;
    vGrad = grad;
    vec4 world = modelMatrix * vec4(pos, 1.0);
    vWorld = world.xyz;
    gl_Position = projectionMatrix * viewMatrix * world;
  }
`

const fragmentShader = `
  uniform float uTime;
  uniform vec3 uDeep, uShallow, uSky, uHorizon, uFoam, uSunDir, uSunColor;
  uniform vec2 uHull;      // 船体半长、半宽（含船首）
  uniform float uHullX;    // 船体中心 x
  varying vec3 vWorld;
  varying vec2 vGrad;

  float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
  float noise(vec2 p) {
    vec2 i = floor(p), f = fract(p);
    vec2 u = f * f * (3.0 - 2.0 * f);
    return mix(mix(hash(i), hash(i + vec2(1, 0)), u.x), mix(hash(i + vec2(0, 1)), hash(i + vec2(1, 1)), u.x), u.y);
  }
  // 细碎波纹：两层滚动噪声的梯度，叠到大波法线上
  vec2 ripple(vec2 p) {
    float e = 0.15;
    vec2 q = p * 0.55 + vec2(uTime * 0.18, uTime * 0.11);
    vec2 r = p * 1.3 - vec2(uTime * 0.07, uTime * 0.22);
    float a = noise(q) + 0.5 * noise(r);
    float bx = noise(q + vec2(e, 0.0)) + 0.5 * noise(r + vec2(e, 0.0));
    float bz = noise(q + vec2(0.0, e)) + 0.5 * noise(r + vec2(0.0, e));
    return vec2(bx - a, bz - a) / e;
  }
  float hullDistance(vec2 p) {
    vec2 q = vec2(p.x - uHullX, p.y);
    vec2 d = abs(q) - uHull;
    return length(max(d, 0.0)) + min(max(d.x, d.y), 0.0);
  }
  void main() {
    vec2 g = vGrad + ripple(vWorld.xz) * 0.06;
    vec3 n = normalize(vec3(-g.x, 1.0, -g.y));
    vec3 view = normalize(cameraPosition - vWorld);
    float fres = 0.02 + 0.98 * pow(1.0 - max(dot(n, view), 0.0), 5.0);
    float facing = clamp(dot(view, vec3(0.0, 1.0, 0.0)), 0.0, 1.0);
    vec3 water = mix(uShallow, uDeep, pow(facing, 0.6));
    vec3 col = mix(water, uSky, fres * 0.85);
    vec3 h = normalize(uSunDir + view);
    col += uSunColor * pow(max(dot(n, h), 0.0), 220.0) * 1.6;
    // 船舷白沫：贴近船体的一圈，边缘被噪声撕碎
    float dist = hullDistance(vWorld.xz);
    float foamBand = smoothstep(1.3, 0.0, dist) * smoothstep(-0.4, 0.05, dist);
    // 船首推浪更白、更宽；船尾拖出一道渐散的尾迹
    vec2 q = vec2(vWorld.x - uHullX, vWorld.z);
    float bow = smoothstep(uHull.x - 6.0, uHull.x + 1.0, q.x) * smoothstep(3.5, 0.0, dist);
    float wake = smoothstep(-uHull.x + 1.0, -uHull.x - 26.0, q.x) * (1.0 - smoothstep(0.0, uHull.y * 0.9 + (-uHull.x - q.x) * 0.12, abs(q.y)));
    float foamNoise = noise(vWorld.xz * 2.2 + uTime * 0.6) * noise(vWorld.xz * 0.8 - uTime * 0.25);
    float foam = (foamBand + bow * 0.8) * smoothstep(0.18, 0.5, foamNoise + foamBand * 0.12);
    foam += wake * smoothstep(0.22, 0.55, foamNoise) * 0.75;
    // 浪尖碎白
    foam += smoothstep(0.30, 0.42, length(vGrad)) * 0.35 * noise(vWorld.xz * 2.4 + uTime);
    col = mix(col, uFoam, clamp(foam, 0.0, 0.9));
    // 远处融进海平线
    float far = smoothstep(70.0, 250.0, length(vWorld.xz - cameraPosition.xz)); // 画面上缘的远海化进海平线雾气
    col = mix(col, uHorizon, far);
    gl_FragColor = vec4(col, 1.0);
    #include <tonemapping_fragment>
    #include <colorspace_fragment>
  }
`

export function createOcean({ renderer, scene, colors, sunDirection }) {
  // 天空：物理散射天空，同时烘一份环境贴图给金属/漆面反射
  const sky = new Sky()
  sky.scale.setScalar(4000)
  const u = sky.material.uniforms
  u.turbidity.value = 4.2
  u.rayleigh.value = 1.4
  u.mieCoefficient.value = 0.004
  u.mieDirectionalG.value = 0.82
  u.sunPosition.value.copy(sunDirection).multiplyScalar(1000)
  scene.add(sky)

  const pmrem = new THREE.PMREMGenerator(renderer)
  const envScene = new THREE.Scene()
  const envSky = sky.clone()
  envScene.add(envSky)
  const envTarget = pmrem.fromScene(envScene, 0.02)
  scene.environment = envTarget.texture
  pmrem.dispose()

  const geometry = new THREE.PlaneGeometry(900, 600, 220, 150)
  geometry.rotateX(-Math.PI / 2)
  const material = new THREE.ShaderMaterial({
    vertexShader, fragmentShader,
    uniforms: {
      uTime: { value: 0 },
      uDeep: { value: colors.seaDeep }, uShallow: { value: colors.seaShallow }, uSky: { value: colors.horizon.clone().lerp(colors.lightSky, 0.35) },
      uHorizon: { value: colors.horizon }, uFoam: { value: colors.foam },
      uSunDir: { value: sunDirection.clone().normalize() }, uSunColor: { value: colors.lightSun },
      uHull: { value: new THREE.Vector2(40, 9) }, uHullX: { value: 0 },
    },
  })
  const mesh = new THREE.Mesh(geometry, material)
  mesh.receiveShadow = false
  scene.add(mesh)
  scene.fog = new THREE.Fog(colors.horizon, 180, 480)

  return {
    mesh,
    setTime(t) { material.uniforms.uTime.value = t },
    setHull(halfLength, halfBeam, centerX) {
      material.uniforms.uHull.value.set(halfLength, halfBeam)
      material.uniforms.uHullX.value = centerX
    },
    dispose() {
      geometry.dispose(); material.dispose()
      sky.geometry.dispose(); sky.material.dispose(); envSky.material.dispose?.()
      envTarget.dispose()
      scene.environment = null
    },
  }
}
