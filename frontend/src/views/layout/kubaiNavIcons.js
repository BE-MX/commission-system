// Kubai (立体动态) icons for first-level navigation. Pure presentation: navigation.js, the
// navigation catalog and saved configurations keep their Element Plus icon names.
//
// Each entry pairs the drawing with the source icon it replaces. The drawing is used only
// while the node still shows that source icon; once an administrator picks another icon in
// 导航管理, their choice is shown as-is.
import {
  Aim, Box, Brush, Camera, DataAnalysis, DataLine, Document, Finished, Money, Monitor,
  Notebook, OfficeBuilding, Picture, Reading, Setting, Shop, Tickets, User, Van, Wallet,
  MagicStick,
} from '@element-plus/icons-vue'

export const KUBAI_GROUP_ICONS = {
  customerPortal: ['购物车', Shop],
  personnel: ['用户', User],
  customer: ['地球', OfficeBuilding],
  customerOperations: ['聊天', Aim],
  invoice: ['剪贴板', Document],
  aftersales: ['耳机', Notebook],
  expo: ['旗帜', MagicStick],
  commission: ['钱包', Money],
  salary: ['计算器', Wallet],
  tracking: ['货车', Van],
  stock: ['包裹', Box],
  colorwork: ['快捷方式', Brush],
  domestic: ['文档', Tickets],
  shipping: ['扫码', Van],
  asset: ['照片', Picture],
  color: ['色卡', MagicStick],
  insight: ['灯泡', Aim],
  knowledge: ['书本', Reading],
  design: ['相机', Camera],
  report: ['图表', DataAnalysis],
  system: ['设置', Setting],
  governance: ['盾牌', DataLine],
  task: ['便签', Finished],
}

// Top-level pages that sit beside the groups, keyed by route name.
export const KUBAI_TOP_LEVEL_ICONS = {
  Dashboard: ['主页', DataAnalysis],
  Announcements: ['通知', Document],
  AgentTaskCenter: ['机器人', Monitor],
}

// Header account menu.
export const KUBAI_ACCOUNT_ICONS = { profile: '用户', password: '钥匙', logout: '退出' }

function resolve(table, key, icon) {
  const entry = table[key]
  return entry && entry[1] === icon ? entry[0] : null
}

export const kubaiGroupIcon = (key, icon) => resolve(KUBAI_GROUP_ICONS, key, icon)
export const kubaiTopLevelIcon = (name, icon) => resolve(KUBAI_TOP_LEVEL_ICONS, name, icon)
