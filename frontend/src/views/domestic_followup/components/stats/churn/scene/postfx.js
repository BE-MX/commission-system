// 镜头后期：环境光遮蔽（GTAO）→ 泛光 → 色调映射 → 调色 / 移轴景深 / 暗角 / 颗粒 → SMAA 抗锯齿。
// 全部是着色器代码，不用贴图。性能吃紧时由场景调用 degrade() 逐级关掉最贵的环节。
import * as THREE from 'three'
import { EffectComposer } from 'three/examples/jsm/postprocessing/EffectComposer.js'
import { RenderPass } from 'three/examples/jsm/postprocessing/RenderPass.js'
import { GTAOPass } from 'three/examples/jsm/postprocessing/GTAOPass.js'
import { UnrealBloomPass } from 'three/examples/jsm/postprocessing/UnrealBloomPass.js'
import { OutputPass } from 'three/examples/jsm/postprocessing/OutputPass.js'
import { ShaderPass } from 'three/examples/jsm/postprocessing/ShaderPass.js'
import { SMAAPass } from 'three/examples/jsm/postprocessing/SMAAPass.js'

// 在显示空间（sRGB）做：暗部偏冷、亮部偏暖的分离调色，S 曲线对比，饱和度，移轴模糊，暗角，细颗粒
const GradeShader = {
  uniforms: {
    tDiffuse: { value: null },
    uResolution: { value: new THREE.Vector2(1, 1) },
    uTime: { value: 0 },
    uShadowTint: { value: new THREE.Color(0.86, 0.95, 1.06) },
    uHighlightTint: { value: new THREE.Color(1.06, 1.0, 0.9) },
    uContrast: { value: 1.12 },
    uSaturation: { value: 1.1 },
    uVignette: { value: 0.32 },
    uFocusY: { value: 0.46 },    // 清晰带中心（屏幕高度比例，0 = 底）
    uFocusBand: { value: 0.2 },  // 清晰带半宽
    uBlur: { value: 1.0 },       // 0 关闭移轴
  },
  vertexShader: 'varying vec2 vUv; void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }',
  fragmentShader: `
    uniform sampler2D tDiffuse;
    uniform vec2 uResolution;
    uniform float uTime, uContrast, uSaturation, uVignette, uFocusY, uFocusBand, uBlur;
    uniform vec3 uShadowTint, uHighlightTint;
    varying vec2 vUv;
    float hash(vec2 p) { return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453); }
    void main() {
      // 移轴：离清晰带越远，取样圆盘越大（上方远海、下方近景轻微虚化，像微缩沙盘的镜头）
      float off = max(abs(vUv.y - uFocusY) - uFocusBand, 0.0);
      float radius = smoothstep(0.0, 0.32, off) * 3.2 * uBlur;
      vec3 col = texture2D(tDiffuse, vUv).rgb;
      if (radius > 0.05) {
        vec3 sum = col; float n = 1.0;
        for (int i = 0; i < 12; i++) {
          float a = float(i) * 2.39996;
          float r = sqrt(float(i) + 0.5) / sqrt(12.0) * radius;
          sum += texture2D(tDiffuse, vUv + vec2(cos(a), sin(a)) * r / uResolution).rgb;
          n += 1.0;
        }
        col = sum / n;
      }
      float luma = dot(col, vec3(0.2126, 0.7152, 0.0722));
      col *= mix(uShadowTint, uHighlightTint, smoothstep(0.15, 0.75, luma));
      col = (col - 0.5) * uContrast + 0.5;
      luma = dot(col, vec3(0.2126, 0.7152, 0.0722));
      col = mix(vec3(luma), col, uSaturation);
      vec2 d = vUv - 0.5;
      col *= 1.0 - uVignette * smoothstep(0.25, 0.85, dot(d, d) * 2.2);
      col += (hash(vUv * uResolution + uTime) - 0.5) * 0.018;
      gl_FragColor = vec4(clamp(col, 0.0, 1.0), 1.0);
    }
  `,
}

export function createPostFX({ renderer, scene, camera, width, height, reduced }) {
  const composer = new EffectComposer(renderer)
  composer.setPixelRatio(renderer.getPixelRatio())
  composer.setSize(width, height)
  composer.addPass(new RenderPass(scene, camera))

  const ao = new GTAOPass(scene, camera, width, height)
  ao.updateGtaoMaterial({ radius: 0.9, distanceExponent: 1.4, thickness: 1.2, scale: 1.15, samples: 12 })
  ao.updatePdMaterial({ lumaPhi: 10, depthPhi: 2, normalPhi: 3, radius: 6, rings: 2, samples: 12 })
  ao.blendIntensity = 0.95
  composer.addPass(ao)

  // 只让真正亮的部分溢光：海面太阳高光、亮灯窗格、临界箱的呼吸光
  const bloom = new UnrealBloomPass(new THREE.Vector2(width, height), 0.22, 0.5, 1.0)
  composer.addPass(bloom)
  composer.addPass(new OutputPass())

  const grade = new ShaderPass(GradeShader)
  if (reduced) grade.uniforms.uBlur.value = 0.6
  composer.addPass(grade)

  const smaa = new SMAAPass(width * renderer.getPixelRatio(), height * renderer.getPixelRatio())
  composer.addPass(smaa)

  let level = 3 // 3 全开 → 2 关 AO → 1 再关泛光；之后由场景降分辨率
  return {
    render(time) {
      grade.uniforms.uTime.value = time % 1000
      composer.render()
    },
    setSize(w, h, pixelRatio) {
      composer.setPixelRatio(pixelRatio)
      composer.setSize(w, h)
      grade.uniforms.uResolution.value.set(w * pixelRatio, h * pixelRatio)
    },
    /** 关掉一级最贵的效果；已无可关时返回 false。 */
    degrade() {
      if (level === 3) { ao.enabled = false; level = 2; return true }
      if (level === 2) { bloom.enabled = false; level = 1; return true }
      return false
    },
    get level() { return level },
    dispose() {
      for (const pass of composer.passes) pass.dispose?.()
      composer.dispose()
    },
  }
}
