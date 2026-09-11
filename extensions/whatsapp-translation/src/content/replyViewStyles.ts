export const REPLY_PANEL_STYLES = `
.reply-panel[hidden], .reply-panel [hidden] { display:none !important; }
.reply-panel .card { display:flex; flex-direction:column; gap:12px; max-height:min(560px,65vh); overflow:hidden; padding:16px; }
.reply-panel .reply-head { display:flex; align-items:center; justify-content:space-between; gap:12px; }
.reply-panel .reply-head strong { font-size:15px; }
.reply-panel .reply-tabs { display:flex; gap:4px; border-bottom:1px solid var(--border); flex-shrink:0; }
.reply-panel .reply-tabs button { padding:8px 12px; border-radius:6px 6px 0 0; color:var(--muted); border-bottom:2px solid transparent; }
.reply-panel .reply-tabs button[aria-selected="true"] { color:var(--fg); border-bottom-color:var(--link); background:var(--surface); font-weight:600; }
.reply-panel .reply-pane { min-height:100px; overflow-y:auto; overscroll-behavior:contain; padding:0 2px; }
.reply-panel .reply-footer { border-top:1px solid var(--border); padding-top:12px; flex-shrink:0; }
.reply-panel .actions { display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
.reply-panel .reply-footer > .actions { margin-right:auto; }
.reply-panel p { margin:8px 0; }
.reply-panel h3 { font-size:13px; margin:4px 0 12px; }
.reply-panel .text { overflow-wrap:anywhere; white-space:pre-wrap; }
.reply-panel .reply-caption, .reply-panel .reply-meaning, .reply-panel .disclosure { color:var(--muted); font-size:12px; line-height:1.6; }
.reply-panel .reply-draft { font-size:15px; line-height:1.65; padding:14px; border:1px solid var(--border); border-radius:10px; background:var(--surface); }
.reply-panel .reply-meaning { padding:0 2px; }
.reply-panel .reply-empty { color:var(--muted); padding:20px 4px; }
.reply-panel summary { cursor:pointer; color:var(--muted); padding:8px 0; }
.reply-panel .reply-preferences { border-top:1px solid var(--border); margin-top:12px; }
.reply-panel .reply-settings { display:flex; align-items:center; gap:12px; flex-wrap:wrap; margin:4px 0 10px; }
.reply-panel .reply-field { display:flex; align-items:center; gap:12px; }
.reply-panel textarea, .reply-panel select, .reply-panel input[type="text"] { box-sizing:border-box; background:var(--surface); color:var(--fg); border:1px solid var(--border); border-radius:8px; font:inherit; padding:8px; max-width:100%; }
.reply-panel textarea { width:100%; min-height:60px; resize:vertical; }
.reply-panel .status { margin:0; padding:8px 10px; border-radius:8px; background:var(--surface); color:var(--muted); font-size:12px; }
.reply-panel button { min-height:32px; }
.reply-panel button:focus-visible, .reply-panel select:focus-visible, .reply-panel textarea:focus-visible, .reply-panel summary:focus-visible { outline:2px solid var(--link); outline-offset:2px; }
@media(max-width:520px) { .reply-panel .card { padding:12px; gap:8px; } .reply-panel .reply-tabs button { padding:8px; } }
`
