<template>
  <router-view />
</template>

<style>
:root {
  /* --- Palette: LeShine Gold + Black --- */
  --color-primary: #D4941C;
  --color-primary-hover: #BB8218;
  --color-primary-light: rgba(212,148,28,0.08);
  --color-primary-glow: rgba(212,148,28,0.25);
  --color-gold: #F5CB5C;
  --color-gold-soft: #FDF4DC;
  --color-accent: #D4941C;
  --color-danger: #DC3545;
  --color-success: #2D9F6F;

  --sidebar-bg-from: #141210;
  --sidebar-bg-to: #1E1B18;
  --sidebar-active: var(--color-gold);

  --text-primary: #1A1816;
  --text-secondary: #6B6560;
  --text-muted: #9C9590;
  --border-color: #E8E2DC;

  --header-height: 56px;
  --page-bg: #FAF8F6;
  --card-bg: #ffffff;
  --card-radius: 12px;
  --card-shadow: 0 1px 2px rgba(26,24,22,0.04), 0 1px 3px rgba(26,24,22,0.05);
  --card-shadow-hover: 0 4px 16px rgba(26,24,22,0.08), 0 2px 4px rgba(26,24,22,0.04);

  /* --- Typography --- */
  --font-display: 'Outfit', sans-serif;
  --font-body: 'DM Sans', sans-serif;
}

html, body, #app {
  margin: 0;
  padding: 0;
  height: 100%;
  font-family: var(--font-body);
  color: var(--text-primary);
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

/* --- Grain texture overlay --- */
#app::before {
  content: '';
  position: fixed;
  inset: 0;
  pointer-events: none;
  z-index: 9999;
  opacity: 0.018;
  background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");
}

/* --- Scrollbar --- */
::-webkit-scrollbar { width: 5px; height: 5px; }
::-webkit-scrollbar-thumb { background: #cbd5e1; border-radius: 10px; }
::-webkit-scrollbar-thumb:hover { background: #94a3b8; }
::-webkit-scrollbar-track { background: transparent; }

/* ===== Element Plus Overrides ===== */

/* Tables */
.el-table {
  border-radius: var(--card-radius);
  overflow: hidden;
  font-family: var(--font-body);
  --el-table-border-color: var(--border-color);
}
.el-table th.el-table__cell {
  background: #F5F2EE !important;
  color: var(--text-secondary);
  font-family: var(--font-display);
  font-weight: 600;
  font-size: 12px;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  border-bottom: 2px solid var(--border-color) !important;
}
.el-table td.el-table__cell {
  color: var(--text-primary);
  font-size: 13px;
  border-bottom-color: #F5F2EE !important;
}
.el-table--striped .el-table__body tr.el-table__row--striped td.el-table__cell {
  background: #FDFCFA !important;
}
.el-table .el-table__body tr:hover > td.el-table__cell {
  background: var(--color-primary-light) !important;
}
.el-table--border .el-table__inner-wrapper::after,
.el-table--border::before,
.el-table--border::after {
  background-color: var(--border-color) !important;
}

/* Cards */
.el-card {
  border-radius: var(--card-radius) !important;
  border: 1px solid var(--border-color) !important;
  box-shadow: var(--card-shadow) !important;
  transition: box-shadow 0.3s ease, transform 0.3s ease;
}
.el-card:hover {
  box-shadow: var(--card-shadow-hover) !important;
}

/* Tags */
.el-tag {
  border-radius: 6px;
  font-family: var(--font-display);
  font-weight: 600;
  font-size: 11px;
  letter-spacing: 0.03em;
}

/* Buttons */
.el-button {
  border-radius: 8px;
  font-family: var(--font-display);
  font-weight: 600;
  transition: all 0.2s ease;
}
.el-button--primary {
  background: var(--color-primary);
  border-color: var(--color-primary);
  color: #fff;
}
.el-button--primary:hover,
.el-button--primary:focus {
  background: var(--color-primary-hover);
  border-color: var(--color-primary-hover);
  color: #fff;
}
.el-button.is-link { font-weight: 500; }

/* Link button colors — brand palette */
.el-button.is-link.el-button--primary {
  color: var(--color-primary);
  background: transparent;
  border-color: transparent;
}
.el-button.is-link.el-button--primary:hover {
  color: var(--color-primary-hover);
  background: var(--color-primary-light);
}
.el-button.is-link.el-button--success {
  color: #2D9F6F;
}
.el-button.is-link.el-button--success:hover {
  color: #248A5E;
  background: rgba(45,159,111,0.06);
}
.el-button.is-link.el-button--danger {
  color: #C0392B;
}
.el-button.is-link.el-button--danger:hover {
  color: #A93226;
  background: rgba(192,57,43,0.06);
}
.el-button.is-link.el-button--warning {
  color: var(--color-primary);
}
.el-button.is-link.el-button--warning:hover {
  color: var(--color-primary-hover);
  background: var(--color-primary-light);
}

/* ---- Tags: brand-consistent status colors ---- */
.el-tag--info {
  background: #F5F2EE;
  border-color: #E8E2DC;
  color: #6B6560;
}
.el-tag--primary, .el-tag:not([class*="--"]) {
  background: rgba(212,148,28,0.1);
  border-color: rgba(212,148,28,0.2);
  color: #B8860B;
}
.el-tag--success {
  background: rgba(45,159,111,0.08);
  border-color: rgba(45,159,111,0.18);
  color: #1E7D50;
}
.el-tag--danger {
  background: rgba(192,57,43,0.08);
  border-color: rgba(192,57,43,0.18);
  color: #A93226;
}
.el-tag--warning {
  background: rgba(245,203,92,0.15);
  border-color: rgba(245,203,92,0.3);
  color: #8B6914;
}
/* Dark effect tags (used in detail banner) */
.el-tag.el-tag--dark {
  border-color: transparent;
}
.el-tag--success.el-tag--dark {
  background: #2D9F6F;
  color: #fff;
}
.el-tag--info.el-tag--dark {
  background: #6B6560;
  color: #fff;
}
.el-tag--danger.el-tag--dark {
  background: #C0392B;
  color: #fff;
}

/* ---- Radio button group: tab style ---- */
.el-radio-group {
  --el-radio-button-checked-bg-color: var(--color-primary);
  --el-radio-button-checked-border-color: var(--color-primary);
  --el-radio-button-checked-text-color: #fff;
}
.el-radio-button__inner {
  font-family: var(--font-display);
  font-weight: 500;
  font-size: 13px;
  border-color: var(--border-color) !important;
  color: var(--text-secondary);
  transition: all 0.2s ease;
}
.el-radio-button__inner:hover {
  color: var(--color-primary);
}
.el-radio-button.is-active .el-radio-button__inner {
  background: var(--color-primary) !important;
  border-color: var(--color-primary) !important;
  color: #fff !important;
  box-shadow: -1px 0 0 0 var(--color-primary) !important;
}

/* ---- Dropdown menu ---- */
.el-dropdown-menu {
  border-radius: 10px !important;
  padding: 4px !important;
  border: 1px solid var(--border-color) !important;
}
.el-dropdown-menu__item {
  border-radius: 6px;
  font-family: var(--font-display);
  font-size: 13px;
}
.el-dropdown-menu__item:hover {
  background: var(--color-primary-light) !important;
  color: var(--color-primary) !important;
}

/* Dialogs */
.el-dialog {
  border-radius: 16px !important;
  overflow: hidden;
}
.el-dialog__header {
  padding: 20px 24px 14px;
  border-bottom: 1px solid var(--border-color);
  margin-right: 0;
}
.el-dialog__title {
  font-family: var(--font-display);
  font-size: 17px;
  font-weight: 700;
  color: var(--text-primary);
}
.el-dialog__body { padding: 20px 24px; }
.el-dialog__footer { padding: 12px 24px 20px; }

/* Pagination */
.el-pagination {
  justify-content: flex-end;
  margin-top: 16px;
  padding: 4px 0;
  font-family: var(--font-display);
}

/* Inputs */
.el-input__wrapper {
  border-radius: 8px !important;
  box-shadow: 0 0 0 1px var(--border-color) inset !important;
  transition: box-shadow 0.2s ease !important;
}
.el-input__wrapper:hover {
  box-shadow: 0 0 0 1px #cbd5e1 inset !important;
}
.el-input__wrapper.is-focus {
  box-shadow: 0 0 0 1px var(--color-primary) inset, 0 0 0 3px var(--color-primary-light) inset !important;
}
.el-select .el-input__wrapper { border-radius: 8px !important; }

/* Drawer */
.el-drawer {
  border-radius: 16px 0 0 16px !important;
}
.el-drawer__header {
  margin-bottom: 0;
  padding: 20px 24px;
  border-bottom: 1px solid var(--border-color);
  font-family: var(--font-display);
}
.el-drawer__body { padding: 20px 24px; }

/* MessageBox */
.el-message-box { border-radius: 16px; }

/* Descriptions */
.el-descriptions {
  border-radius: 10px;
  overflow: hidden;
  font-family: var(--font-body);
}

/* Alert */
.el-alert { border-radius: 10px; }

/* Upload */
.el-upload-dragger {
  border-radius: 12px;
  border: 2px dashed var(--border-color);
  transition: border-color 0.25s, background 0.25s;
}
.el-upload-dragger:hover {
  border-color: var(--color-primary);
  background: var(--color-primary-light);
}

/* Radio button group */
.el-radio-group .el-radio-button__inner { border-radius: 8px !important; }

/* Statistic */
.el-statistic__head { font-size: 12px; color: var(--text-muted); font-family: var(--font-display); }
.el-statistic__content { font-size: 22px; font-weight: 700; font-family: var(--font-display); }

/* Timeline */
.el-timeline-item__content .el-card { border-radius: 10px !important; }

/* Menu popover */
.el-menu--popup { border-radius: 10px !important; }

/* ===== Page-level shared styles ===== */

.toolbar {
  margin-bottom: 16px;
  background: var(--card-bg);
  padding: 16px 20px;
  border-radius: var(--card-radius);
  box-shadow: var(--card-shadow);
  border: 1px solid var(--border-color);
}

.el-main .el-table {
  box-shadow: var(--card-shadow);
  border: 1px solid var(--border-color);
}

/* ===== Staggered fade-in animation ===== */
@keyframes fadeSlideIn {
  from { opacity: 0; transform: translateY(12px); }
  to   { opacity: 1; transform: translateY(0); }
}
.anim-stagger > * {
  opacity: 0;
  animation: fadeSlideIn 0.4s ease forwards;
}
.anim-stagger > *:nth-child(1) { animation-delay: 0.05s; }
.anim-stagger > *:nth-child(2) { animation-delay: 0.12s; }
.anim-stagger > *:nth-child(3) { animation-delay: 0.19s; }
.anim-stagger > *:nth-child(4) { animation-delay: 0.26s; }
.anim-stagger > *:nth-child(5) { animation-delay: 0.33s; }
.anim-stagger > *:nth-child(6) { animation-delay: 0.40s; }
</style>
