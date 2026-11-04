import { createApp, h } from 'vue'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import '../../../src/styles/tokens.css'
import KubaiIcon from '../../../src/components/kubai/KubaiIcon.vue'
import { ICONS } from '../../../src/components/kubai/icons.js'
import { KUBAI_ACCOUNT_ICONS, KUBAI_GROUP_ICONS, KUBAI_TOP_LEVEL_ICONS } from '../../../src/views/layout/kubaiNavIcons.js'

// Gallery of every Kubai icon in the platform: the sidebar mapping on the dark sidebar
// surface, the whole set on a light surface, and the account menu as it renders.
const used = [...Object.entries(KUBAI_TOP_LEVEL_ICONS), ...Object.entries(KUBAI_GROUP_ICONS)]
const row = (label, name, active) => h('li', { class: ['el-menu-item', { 'is-active': active }], tabindex: 0 },
  [h('span', { class: 'el-icon nav-icon' }, [h(KubaiIcon, { name })]), h('span', label)])

createApp({
  render: () => h('div', { class: 'stage' }, [
    h('ul', { class: 'sidebar' }, used.map(([key, [name]], index) => row(`${key} · ${name}`, name, index === 0))),
    h('div', { class: 'light' }, [
      h('div', { class: 'grid' }, ICONS.map(icon => h('div', { class: 'tile', tabindex: 0 }, [h('span', { class: 'big' }, [h(KubaiIcon, { name: icon.name, hoverTarget: '.tile' })]), h('small', icon.name)]))),
      h('ul', { class: 'el-dropdown-menu account' }, Object.entries(KUBAI_ACCOUNT_ICONS).map(([key, name]) =>
        h('li', { class: 'el-dropdown-menu__item', tabindex: -1 }, [h('span', { class: 'el-icon account-icon' }, [h(KubaiIcon, { name })]), key]))),
    ]),
  ]),
}).use(ElementPlus).mount('#app')
