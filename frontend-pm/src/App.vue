<template>
  <router-view v-slot="{ Component }">
    <transition name="fade" mode="out-in">
      <component :is="Component" />
    </transition>
  </router-view>
  <UiToast />
</template>

<script setup>
import UiToast from './components/UiToast.vue'
</script>
