// Synthetic UI-only responses. Browser tests never contact a live backend or image provider.
import { readFile } from 'node:fs/promises'
export const original = '/demo-original.webp'
export const portrait = '/src/assets/expo/atelier-hero.webp'
export const wigs = ['轻盈短发', '优雅齐肩', '柔感层次', '自然短发', '柔和波波', '知性中发'].map((name, i) => ({
  wig_id: i + 1, model_no: `DEMO-${i + 1}`, name, series: i === 1 ? 'zhizhen' : 'classic',
  cover_url: portrait, thumb_url: portrait, score: 95 - i,
  reason: '柔和层次，与知性气质自然相衬',
}))
export const scenes = ['商务肖像', '日常生活', '晚宴时刻', '旅行记忆'].map((label, i) => ({
  key: `scene-${i}`, label, tagline: '场景示意', image: portrait, category: i < 2 ? 'career' : 'life',
}))
export async function installExpoFixture(page, baseURL) {
  const state = { calls: [], phase: 'pending', mode: 'tryon', polls: 0, results: [], quota: 50, versions: true, failGeneration: false, displayFail: false, originalFail: false, displayMissing: false }
  await page.addInitScript(() => {
    localStorage.setItem('ark_access_token', 'synthetic-ui-test')
    window.__printed = []
    window.Android = { printPhoto: url => window.__printed.push(url) }
  })
  const pixels = await readFile(new URL('../../src/assets/expo/atelier-hero.webp', import.meta.url))
  await page.route(`${baseURL}/demo-*.webp*`, route => {
    const failed = new URL(route.request().url()).pathname === original ? state.originalFail : state.displayFail
    return route.fulfill({ status: failed ? 404 : 200, contentType: 'image/webp', headers: { 'cache-control': 'no-store' }, body: failed ? Buffer.from('unavailable') : pixels })
  })
  await page.route(`${baseURL}/api/**`, async route => {
    const req = route.request(), path = new URL(req.url()).pathname
    let body = null
    if ((req.headers()['content-type'] || '').includes('application/json')) body = req.postDataJSON()
    state.calls.push({ path, method: req.method(), body })
    let data = {}
    if (path === '/api/auth/me') return route.fulfill({ json: { id: 1, username: 'ui-demo', roles: [], permissions: ['expo:write'] } })
    if (path.endsWith('/stores/quota')) data = { bound: true, remaining: state.quota, store_name: '演示门店' }
    else if (path.endsWith('/register')) data = { customer_id: 1 }
    else if (path.endsWith('/prompt-versions/picker')) data = state.versions ? [{ id: 91, name: '真实', hint: '如实还原 · 不修皮肤', is_default: true }, { id: 104, name: '柔光', hint: '光线更柔 · 保留质感' }, { id: 230, name: '美颜', hint: '磨皮提亮 · 精修质感' }] : []
    else if (path.endsWith('/wigs/picker')) data = [...wigs, { ...wigs[0], wig_id: 20, name: '自选造型' }]
    else if (/\/wigs\/\d+\/colors$/.test(path)) data = [{ id: 8, name: '栗棕', hex: '#543321' }, { id: 9, name: '自然黑', hex: '#221912' }]
    else if (path.endsWith('/scenes')) data = scenes
    else if (path.endsWith('/upload-ticket')) data = { path: '/test-upload', expires_in: 300 }
    else if (path.endsWith('/pending-photo')) data = { pending: null }
    else if (path === '/api/expo/sessions' && req.method() === 'POST') {
      state.mode = /name="mode"\r\n\r\nscene/.test(req.postData() || '') ? 'scene' : 'tryon'
      state.phase = 'pending'; state.polls = 0; state.results = []; data = { session_id: 1 }
    } else if (path.endsWith('/generate')) {
      state.phase = 'generating'; state.polls = 0; data = { status: 'generating' }
    } else if (path === '/api/expo/sessions/1') {
      state.polls++
      if (state.phase === 'pending' && state.polls > 1) state.phase = 'analyzed'
      if (state.phase === 'generating' && state.polls > 1) {
        state.phase = 'done'
        if (!state.failGeneration) state.results.push({ id: state.results.length + 1, wig_id: state.mode === 'tryon' ? 1 : null, wig_name: '轻盈短发', status: 'done', image_url: `${original}?id=${state.results.length + 1}`, display_url: state.displayMissing ? null : `/demo-display.webp?id=${state.results.length + 1}`, short_code: 'demo-only', hair_color: { name: '栗棕', hex: '#543321' }, scene: scenes[0] })
      }
      data = { status: state.phase, photo_url: portrait, matches: wigs, results: state.results,
        analysis: { face_shape: 'oval', skin_tone: { depth: 'medium', undertone: 'warm' }, temperament: '知性优雅', suit_length: 'short', display_notes: '自然柔和的线条，与知性气质相衬。' } }
    } else if (path.endsWith('/kiosk/leads')) data = { total: 1, items: [{ customer_id: 1, name: '演示女士', phone_masked: '138****0000', result_count: 1, intent_level: 'A' }] }
    else if (path.endsWith('/strategy')) data = { customer: { name: '演示女士', phone_masked: '138****0000', primary_need: 'style_change', style_pref: '知性优雅' }, strategy: { opener: '这个发型很衬您的气质。', followup: '可以请顾问协助实物试戴。', objections: [] }, tried_wigs: ['轻盈短发'] }
    return route.fulfill({ json: { code: 200, message: 'ok', data } })
  })
  return state
}
