<template>
  <section class="retail-attract">
    <div class="retail-orbit"><span>AI</span></div>
    <p>LESHINE INTELLIGENT TRY-ON</p>
    <h1>看看哪款发型<br />更适合现在的你</h1>
    <span>拍摄或上传一张正面照片，AI 将分析脸型与气质，并生成一款发型试戴效果。</span>
    <button class="xk-btn" @click="$emit('start')">开始 AI 发型试戴</button>
    <small>本次资格仅限本人使用 · 照片仅用于本次分析与生成</small>
  </section>
</template>

<script setup>
defineEmits(['start'])
</script>

<style scoped>
.retail-attract { flex:1; min-height:0; padding:34px 24px; display:flex; align-items:center; justify-content:center; flex-direction:column; text-align:center; background:radial-gradient(circle at 50% 40%,var(--xk-selected),transparent 38%); }
.retail-orbit { width:132px; height:132px; margin-bottom:22px; display:grid; place-items:center; position:relative; border:1px solid var(--xk-gold-line); border-radius:50%; box-shadow:0 0 60px var(--xk-selected); }
.retail-orbit:before,.retail-orbit:after { content:""; position:absolute; inset:14px; border:1px solid var(--xk-gold-dim); border-radius:50%; }.retail-orbit:after { inset:-10px; border-style:dashed; animation:spin 18s linear infinite; }.retail-orbit span { color:var(--xk-gold-hi); font:600 34px var(--xk-serif); letter-spacing:.08em; }
@keyframes spin { to { transform:rotate(360deg); } }
.retail-attract>p { margin:0 0 14px; color:var(--xk-gold); font-size:12px; letter-spacing:.24em; }.retail-attract h1 { margin:0; color:var(--xk-gold-hi); font:500 clamp(40px,6vw,76px)/1.2 var(--xk-serif); letter-spacing:.06em; }.retail-attract>span { max-width:650px; margin:22px auto 28px; color:var(--xk-mut); font-size:16px; line-height:1.9; }.retail-attract button { min-width:280px; min-height:58px; font-size:17px; }.retail-attract small { margin-top:17px; color:var(--xk-gold-dim); font-size:11px; letter-spacing:.08em; }
@media(max-width:600px){.retail-attract{padding:24px 18px}.retail-orbit{width:104px;height:104px}.retail-attract h1{font-size:40px}.retail-attract>span{font-size:15px}.retail-attract button{width:100%;min-width:0}}
</style>
