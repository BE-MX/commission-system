// Build a presentation-only snapshot; route components are never imported or executed.
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const crypto = require('node:crypto');
const root = path.resolve(__dirname, '../../..');
const source = fs.readFileSync(path.join(root, 'frontend/src/config/navigation.js'), 'utf8');
const icons = source.match(/import\s*\{([^}]+)\}\s*from '@element-plus\/icons-vue'/)[1].split(',').map(s => s.trim()).filter(Boolean);
const script = source.replace(/import\s*\{[^}]+\}\s*from '@element-plus\/icons-vue'/, '').replace(/export const /g, 'const ') + '\n;({groups:MENU_GROUPS,entries:NAV_ENTRIES})';
const registry = vm.runInNewContext(script, Object.fromEntries(icons.map(n => [n, n])), { timeout: 1000 });
const nodes = Object.entries(registry.groups).map(([id,g],i) => ({ id, kind:'group', label:g.title, original:g.title, icon:g.icon, parent:'', order:i+20, visible:true, builtin:true, protected:id==='system', badge:g.iconBadge||'', badgePlace:g.iconBadge?'icon':'text', badgeTone:'gold' }));
registry.entries.filter(e=>e.menu&&!e.hideInMenu).forEach((e,i)=>nodes.push({ id:e.name||e.path, kind:'page', label:e.menu.title||e.title, original:e.menu.title||e.title, icon:e.menu.icon||'Document', parent:e.menu.group||'', order:e.menu.order??i, visible:true, builtin:true, protected:e.name==='Dashboard', path:e.path, rule:[e.permission,...(e.anyPermission||[]),e.menu.permission,...(e.menu.anyPermission||[])].filter(Boolean).join(' / ')||'沿用原访问规则', business:e.menu.badge||e.menu.anomalyDomain||'', phase:!!e.menu.commercePhases, badge:'', badgeTone:'gold', badgePlace:'text', titleSync:false }));
nodes.push({id:'NavigationManagement',kind:'page',label:'导航管理',original:'导航管理',icon:'Connection',parent:'system',order:35,visible:true,builtin:true,protected:true,path:'/system/navigation',rule:'navigation:read（设计新增）',badge:'',badgeTone:'gold',badgePlace:'text',titleSync:false});
fs.writeFileSync(path.join(__dirname,'snapshot.js'), 'window.NAV_SNAPSHOT = '+JSON.stringify({hash:crypto.createHash('sha256').update(source).digest('hex'),nodes,icons},null,2)+';\n');
console.log(JSON.stringify({groups:Object.keys(registry.groups).length,pages:nodes.filter(n=>n.kind==='page').length,includesProposedPage:true}));
