<script setup>
defineProps({
  logoUrl: { type: String, default: '' },
  uploading: { type: Boolean, default: false },
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
      <span class="step-number">1</span>
      <div>
        <h2 id="logo-title">上传品牌 LOGO</h2>
        <p>将用于生成产品效果图</p>
      </div>
    </div>

    <div class="logo-preview" :class="{ empty: !logoUrl }">
      <img v-if="logoUrl" :src="logoUrl" alt="已上传的品牌 LOGO">
      <span v-else aria-hidden="true">LOGO</span>
    </div>

    <label class="upload-action" :class="{ disabled: uploading }">
      <input type="file" accept="image/*" :disabled="uploading" @change="chooseFile">
      {{ uploading ? '正在上传…' : logoUrl ? '更换 LOGO' : '选择 LOGO 图片' }}
    </label>
    <p v-if="!logoUrl" class="required-copy">请先上传品牌 LOGO</p>
  </section>
</template>

<style scoped>
.logo-upload { display: grid; gap: 14px; }
.section-heading { display: flex; gap: 10px; align-items: flex-start; }
.step-number { display: grid; width: 28px; height: 28px; place-items: center; border-radius: 50%; color: var(--cip-accent-strong); background: var(--cip-accent-soft); font-weight: 700; }
h2 { margin: 2px 0 0; color: var(--cip-ink); font-size: 15px; }
p { margin: 4px 0 0; color: var(--cip-muted); font-size: 12px; }
.logo-preview { display: grid; min-height: 112px; place-items: center; overflow: hidden; border: 1px dashed var(--cip-border-strong); border-radius: 12px; background: var(--cip-surface-subtle); }
.logo-preview.empty span { color: var(--cip-muted); font-size: 14px; letter-spacing: .16em; }
.logo-preview img { width: 100%; height: 112px; object-fit: contain; }
.upload-action { display: grid; min-height: 44px; place-items: center; cursor: pointer; border: 1px solid var(--cip-border-strong); border-radius: 10px; color: var(--cip-ink); background: var(--cip-surface); font-size: 14px; font-weight: 600; transition: transform 180ms cubic-bezier(0.23, 1, 0.32, 1); }
.upload-action:active { transform: scale(.98); }
.upload-action.disabled { cursor: wait; opacity: .62; }
.upload-action input { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }
.required-copy { color: var(--cip-danger); }
@media (hover: hover) and (pointer: fine) { .upload-action:not(.disabled):hover { border-color: var(--cip-accent); } }
@media (prefers-reduced-motion: reduce) { .upload-action { transition: none; } .upload-action:active { transform: none; } }
</style>
