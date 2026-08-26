<script setup>
import { useCustomerImageI18n } from '../i18n.js'

const { locale, setLocale, t } = useCustomerImageI18n()

const languageOptions = Object.freeze([
  { value: 'en', labelKey: 'language.english', shortLabel: 'EN' },
  { value: 'zh-CN', labelKey: 'language.chinese', shortLabel: '中文' },
])
</script>

<template>
  <div class="language-switcher" role="group" :aria-label="t('language.label')">
    <button
      v-for="option in languageOptions"
      :key="option.value"
      type="button"
      :aria-label="t(option.labelKey)"
      :aria-pressed="locale === option.value"
      @click="setLocale(option.value)"
    >
      {{ option.shortLabel }}
    </button>
  </div>
</template>

<style scoped>
.language-switcher {
  position: fixed;
  z-index: 50;
  top: 12px;
  right: 20px;
  display: inline-flex;
  gap: 2px;
  padding: 3px;
  border: 1px solid var(--cip-border);
  border-radius: 999px;
  background: var(--cip-surface);
  box-shadow: 0 6px 18px var(--cip-shadow);
}

button {
  box-sizing: border-box;
  width: 44px;
  min-width: 44px;
  min-height: 44px;
  padding: 0 12px;
  cursor: pointer;
  border: 0;
  border-radius: 999px;
  color: var(--cip-muted);
  background: transparent;
  font: inherit;
  font-size: 12px;
  font-weight: 700;
  transition: transform 160ms cubic-bezier(0.23, 1, 0.32, 1);
}

button[aria-pressed='true'] {
  color: var(--cip-on-accent);
  background: var(--cip-accent);
  box-shadow: 0 3px 10px var(--cip-shadow);
}

button:focus-visible {
  outline: 3px solid var(--cip-accent-strong);
  outline-offset: 2px;
}

button:active {
  transform: scale(.97);
}

@media (hover: hover) and (pointer: fine) {
  button[aria-pressed='false']:hover {
    color: var(--cip-ink);
    background: var(--cip-surface-subtle);
  }
}

@media (max-width: 760px) {
  .language-switcher {
    top: max(5px, env(safe-area-inset-top));
    right: max(8px, env(safe-area-inset-right));
  }
}

@media (prefers-reduced-motion: reduce) {
  button {
    transition: none;
  }

  button:active {
    transform: none;
  }
}
</style>
