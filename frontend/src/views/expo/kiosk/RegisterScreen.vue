<template>
  <div class="reg">
    <h2 class="xk-title">先认识一下您</h2>
    <div class="xk-sub">试戴效果图将发送给您，随时回看 · 约 30 秒</div>

    <div class="form">
      <div class="row">
        <div class="field">
          <label>怎么称呼您 <i>*</i></label>
          <input v-model="flow.regForm.name" placeholder="如：陈女士" />
        </div>
        <div class="field">
          <label>手机号 <i>*</i></label>
          <input v-model="flow.regForm.phone" inputmode="tel" placeholder="用于接收效果图" />
        </div>
        <div class="field">
          <label>微信号（选填）</label>
          <input v-model="flow.regForm.wechat_id" placeholder="方便顾问发效果图" />
        </div>
      </div>

      <label class="group-label">您最关心的是</label>
      <div class="cards">
        <div
          v-for="need in NEEDS" :key="need.value"
          class="card" :class="{ sel: flow.regForm.primary_need === need.value }"
          @click="flow.regForm.primary_need = need.value"
        >
          <span class="ic">{{ need.icon }}</span>
          <span class="zh">{{ need.label }}</span>
          <span class="en">{{ need.hint }}</span>
        </div>
      </div>

      <label class="group-label">偏爱风格</label>
      <div class="cards">
        <div
          v-for="style in STYLES" :key="style"
          class="card" :class="{ sel: flow.regForm.style_pref === style }"
          @click="flow.regForm.style_pref = style"
        >
          <span class="zh">{{ style }}</span>
        </div>
      </div>

      <label class="consent" @click="flow.regForm.consent = !flow.regForm.consent">
        <span class="box" :class="{ on: flow.regForm.consent }" />
        <span>同意为生成试戴效果拍摄照片。照片仅用于本次体验与效果回看，保留 90 天，可随时联系我们删除。</span>
      </label>

      <button class="xk-btn submit" @click="flow.submitRegister()">下一步</button>
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
const STYLES = ['知性优雅', '减龄轻盈', '自然日常', '端庄大气']
</script>

<style scoped>
.reg { flex: 1; display: flex; flex-direction: column; padding: 2vh 6vw 0; overflow-y: auto; }
.form { max-width: 720px; width: 100%; margin: 3vh auto 0; display: flex; flex-direction: column; }
.row { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 14px; }
.field label, .group-label {
  display: block; font-size: 11px; letter-spacing: 0.24em;
  color: var(--xk-gold-dim); margin: 0 0 8px 2px;
}
.field label i { color: var(--xk-gold); font-style: normal; }
.group-label { margin-top: 22px; }
.field input {
  width: 100%; height: 48px; border-radius: 12px;
  border: 1px solid var(--xk-gold-line);
  background: rgba(232, 196, 121, 0.045);
  color: var(--xk-paper); font-size: 15px; padding: 0 16px; outline: none;
  box-sizing: border-box;
}
.field input:focus { border-color: var(--xk-gold); }
.field input::placeholder { color: #5d5647; }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 10px; }
.card {
  display: flex; flex-direction: column; align-items: center; gap: 4px;
  padding: 16px 8px; border-radius: 14px; cursor: pointer;
  border: 1px solid var(--xk-gold-line); background: rgba(232, 196, 121, 0.03);
}
.card.sel {
  border-color: var(--xk-gold);
  background: rgba(232, 196, 121, 0.1);
  box-shadow: inset 0 0 20px rgba(232, 196, 121, 0.12);
}
.card .ic { font-family: 'Noto Serif SC', serif; font-size: 20px; color: var(--xk-gold); font-style: italic; }
.card .zh { font-size: 14px; }
.card .en { font-size: 10px; color: var(--xk-mut); letter-spacing: 0.1em; }
.consent {
  display: flex; gap: 10px; margin-top: 24px; cursor: pointer;
  font-size: 12px; color: var(--xk-mut); line-height: 1.8;
}
.consent .box {
  flex: none; width: 18px; height: 18px; margin-top: 3px;
  border-radius: 5px; border: 1px solid var(--xk-gold); position: relative;
}
.consent .box.on { background: rgba(232, 196, 121, 0.2); }
.consent .box.on::after {
  content: ''; position: absolute; left: 5px; top: 1px;
  width: 5px; height: 10px;
  border: solid var(--xk-gold); border-width: 0 2px 2px 0; transform: rotate(40deg);
}
.submit { margin: 26px auto 4vh; min-width: 280px; }
</style>
