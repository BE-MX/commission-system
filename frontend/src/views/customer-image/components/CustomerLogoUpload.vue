<script setup>
defineProps({
  logoUrl: { type: String, default: '' },
  uploading: { type: Boolean, default: false },
  disabled: { type: Boolean, default: false },
})

const emit = defineEmits(['upload'])

function chooseFile(event) {
  const file = event.target.files?.[0]
  if (file) emit('upload', file)
  event.target.value = ''
}
</script>

<template>
  <section class="logo-upload" aria-labelledby="logo-title">
    <div class="section-heading">
      <span class="step-number">A</span>
      <div>
        <h2 id="logo-title">上传品牌 LOGO</h2>
        <p>PNG / JPG / WEBP，将用于生成产品效果图</p>
      </div>
    </div>

    <div v-if="logoUrl" class="logo-preview">
      <img :src="logoUrl" alt="已上传的品牌 LOGO">
    </div>

    <label class="upload-action" :class="{ disabled: uploading || disabled }">
      <input type="file" accept="image/*" :disabled="uploading || disabled" @change="chooseFile">
      <span class="plus" aria-hidden="true">＋</span>
      <span class="upload-copy">
        <b>{{ uploading ? '正在上传…' : logoUrl ? '更换 LOGO' : '点击上传品牌 LOGO' }}</b>
        <small>{{ logoUrl ? '替换后新生成将使用最新 LOGO' : '上传后自动保存到本次邀请' }}</small>
      </span>
    </label>
    <p v-if="!logoUrl" class="required-copy">请先上传品牌 LOGO</p>
  </section>
</template>

<style scoped>
.logo-upload { display: grid; gap: 14px; }
.section-heading { display: flex; gap: 10px; align-items: flex-start; }
.step-number { display: grid; width: 26px; height: 26px; place-items: center; flex: 0 0 26px; border-radius: 50%; color: var(--cip-accent-strong); background: var(--cip-accent-soft); font-size: 11px; font-weight: 700; }
h2 { margin: 3px 0 0; color: var(--cip-ink); font-size: 15px; }
p { margin: 4px 0 0; color: var(--cip-muted); font-size: 12px; }
.logo-preview { display: grid; min-height: 108px; place-items: center; overflow: hidden; border: 1px solid var(--cip-border); border-radius: 14px; background: var(--cip-surface-subtle); }
.logo-preview img { width: 100%; height: 108px; object-fit: contain; }
.upload-action { display: flex; min-height: 44px; align-items: center; gap: 12px; padding: 11px 12px; cursor: pointer; border: 1px dashed var(--cip-border-strong); border-radius: 12px; color: var(--cip-ink); background: var(--cip-surface-subtle); transition: transform 180ms cubic-bezier(0.23, 1, 0.32, 1); }
.upload-action:active { transform: scale(.98); }
.upload-action.disabled { cursor: wait; opacity: .62; }
.upload-action input { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }
.plus { display: grid; width: 34px; height: 34px; place-items: center; flex: 0 0 34px; border-radius: 9px; color: var(--cip-accent-strong); background: var(--cip-accent-soft); font-size: 20px; line-height: 1; }
.upload-copy { min-width: 0; }
.upload-copy b { display: block; font-size: 12px; }
.upload-copy small { display: block; margin-top: 3px; color: var(--cip-muted); font-size: 10px; }
.required-copy { color: var(--cip-danger); }
@media (hover: hover) and (pointer: fine) { .upload-action:not(.disabled):hover { border-color: var(--cip-highlight); border-style: solid; } }
@media (prefers-reduced-motion: reduce) { .upload-action { transition: none; } .upload-action:active { transform: none; } }
</style>
