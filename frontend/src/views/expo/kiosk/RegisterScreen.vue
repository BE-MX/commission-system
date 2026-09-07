<template>
  <div class="reg">
    <p class="xk-eyebrow">A LITTLE ABOUT YOU</p>
    <h2 class="xk-title">先认识一下您</h2>
    <div class="xk-sub">试戴效果图将发送给您，随时回看 · 约 30 秒</div>

    <div class="form">
      <div class="row">
        <div class="field">
          <label for="expo-name">怎么称呼您 <i>*</i></label>
          <input id="expo-name" autocomplete="name" v-model="flow.regForm.name" placeholder="如：陈女士" />
        </div>
        <div class="field">
          <label for="expo-phone">手机号 <i>*</i></label>
          <!-- 提前说清 11 位要求，别让客户填完点了「下一步」才被退回来（页头已说明用途） -->
          <input id="expo-phone" autocomplete="tel" v-model="flow.regForm.phone" inputmode="tel" placeholder="11 位手机号" />
        </div>
        <div class="field">
          <label for="expo-wechat">微信号（选填）</label>
          <input id="expo-wechat" v-model="flow.regForm.wechat_id" placeholder="方便顾问发效果图" />
        </div>
      </div>

      <label class="group-label">您最关心的是</label>
      <div class="cards">
        <button type="button"
          :aria-pressed="flow.regForm.primary_need === need.value"
          v-for="need in NEEDS" :key="need.value"
          class="card" :class="{ sel: flow.regForm.primary_need === need.value }"
          @click="flow.regForm.primary_need = need.value"
        >
          <span class="ic">{{ need.icon }}</span>
          <span class="zh">{{ need.label }}</span>
          <span class="en">{{ need.hint }}</span>
        </button>
      </div>

      <label class="group-label">偏爱风格</label>
      <div class="cards">
        <button type="button"
          :aria-pressed="flow.regForm.style_pref === style"
          v-for="style in STYLES" :key="style"
          class="card" :class="{ sel: flow.regForm.style_pref === style }"
          @click="flow.regForm.style_pref = style"
        >
          <span class="zh">{{ style }}</span>
        </button>
      </div>

      <label class="consent">
        <input v-model="flow.regForm.consent" type="checkbox" />
        <span>同意为生成试戴效果拍摄照片。照片仅用于本次体验与效果回看，保留 90 天，可随时联系我们删除。</span>
      </label>

      <button class="xk-btn submit" @click="flow.submitRegister()">下一步 · 拍摄照片 →</button>
    </div>
  </div>
</template>

<script setup>
import { inject } from 'vue'

const flow = inject('tryonFlow')

const NEEDS = [
  { value: 'volume', label: '发量丰盈', hint: '头顶 · 发缝', icon: '丰' },
  { value: 'gray_cover', label: '白发遮盖', hint: '自然发色', icon: '遮' },
  { value: 'style_change', label: '造型变换', hint: '日常 · 场合', icon: '变' },
]
// 与发型库 fit_tags.styles、AI 分析 temperament 枚举三处同步（改一处必须同步另两处）
const STYLES = ['知性优雅', '减龄轻盈', '自然日常', '端庄大气', '温柔清纯', '时尚轻熟']
</script>

<style scoped>
.reg { flex: 1; min-height: 0; overflow-y: auto; padding: 34px 6vw; }
.form { width: 100%; max-width: 880px; margin: 28px auto 0; }
.row { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 18px; }
.field label, .group-label { display: block; color: var(--xk-gold-dim); font-size: 14px; margin-bottom: 10px; }
.field label i { color: var(--xk-warn); font-style: normal; }
.field input { width: 100%; height: 54px; padding: 0 16px; border: 1px solid var(--xk-gold-line); border-radius: 8px; background: var(--xk-ink-2); color: var(--xk-paper); }
.field input::placeholder { color: var(--xk-mut); }
.group-label { margin-top: 30px; }
.cards { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
.card { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 5px; min-height: 58px; padding: 18px 12px; border: 1px solid var(--xk-gold-line); border-radius: 10px; background: var(--xk-ink-2); color: var(--xk-paper); cursor: pointer; transition: transform 180ms var(--xk-ease), background 180ms ease; }
.card.sel { border-color: var(--xk-gold); background: var(--xk-selected); }
.card:active { transform: scale(0.98); }
.ic { font: 24px var(--xk-serif); color: var(--xk-gold); }
.zh { font-size: 16px; }
.en { font-size: 12px; color: var(--xk-mut); }
.consent { display: flex; align-items: flex-start; gap: 12px; margin-top: 28px; color: var(--xk-mut); font-size: 13px; line-height: 1.9; padding: 10px 0; cursor: pointer; }
.consent input { flex: none; margin-top: 3px; width: 22px; height: 22px; accent-color: var(--xk-gold); }
.submit { margin: 26px auto 0; width: min(100%, 460px); }
@media (max-width: 600px) { .reg { padding: 24px 20px; } .row { grid-template-columns: 1fr; gap: 14px; } .cards { gap: 8px; } .card { padding: 14px 6px; } .zh { font-size: 14px; } .group-label { margin-top: 24px; } }
</style>
