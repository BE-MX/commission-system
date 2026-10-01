/* 详情抽屉：字段、验收标准、子任务、关联、AI 完成证据、时间线 */
const LINK_KIND = { branch: '分支', commit: 'COMMIT', merge: '合并', doc: '文档', proto: '原型' }

function pathOf(t) { const p = []; let c = t; while (c.parent) { c = byId(c.parent); p.unshift(`T-${c.id} ${c.title}`) } return p }

function evidenceHtml(t) {
  const p = PROPOSALS[t.id]
  if (t.status !== 'pending' || !p) return ''
  const ok = p.checks.every((c) => c[1])
  return `<div class="evidence">
    <div class="eh"><span class="ai-dot">AI</span>${ok ? '判定已完成，等你确认' : '判定基本完成，有 1 项没找到证据'}</div>
    <p>${esc(p.reason)}</p>
    <ul class="checks">${p.checks.map(([c, hit]) => `<li class="${hit ? '' : 'miss'}">${esc(c)}${hit ? '' : '（未找到对应改动）'}</li>`).join('')}</ul>
    <div class="commits">${p.commits.map(esc).join('<br>')}<br><span style="color:var(--text-muted)">${p.stat}</span></div>
    <div class="ev-actions">
      <button class="btn btn-primary btn-sm" data-act="confirm">${ok ? '确认完成' : '仍然确认完成'}</button>
      <button class="btn btn-ghost btn-sm" data-act="reject">驳回，继续做</button>
      ${ok ? '' : '<button class="btn btn-soft btn-sm" data-act="split">把缺的一项拆成子任务</button>'}
    </div></div>`
}

function linksHtml(t) {
  const list = LINKS[t.id] || (t.git ? [['branch', t.git, 'exact']] : [])
  return `<div class="dr-sec"><h4>关联 <a data-act="link">+ 挂文档 / 原型</a></h4><div class="links">
    ${list.length ? list.map(([k, ref, m], i) => `<div class="link ${m === 'suggested' ? 'is-suggested' : ''}">
      <span class="k">${LINK_KIND[k]}</span><code title="${esc(ref)}">${esc(ref)}</code>
      ${m === 'suggested' ? `<span class="tag">AI 推测相关</span><button class="mini" data-act="accept-link" data-i="${i}">认领</button>` : `<span class="tag ok">${t.id && k === 'branch' ? 'T-编号' : '已关联'}</span>`}
      ${k === 'proto' || k === 'doc' ? '<button class="mini">预览</button>' : ''}</div>`).join('')
      : '<div class="link" style="color:var(--text-muted)">暂无。分支名或 commit 带上 <code style="flex:0">T-' + t.id + '</code> 会自动挂到这里</div>'}
  </div></div>`
}

function timelineHtml(t) {
  const ev = [['09/22 10:14', '亮哥 创建 · 来源：导航「' + (MODS[t.mod]?.title || '') + '」悬浮 +', '']]
  if (t.git) ev.push(['09/27 15:40', `上报器 检测到分支 ${t.git}`, ''])
  if (t.merged) ev.push(['09/29 21:08', '上报器 检测到合并进 main', ''])
  if (t.status === 'pending') ev.push(['09/29 21:09', 'AI 对照验收标准，提议完成', 'ai'])
  if (t.status === 'done') ev.push(['09/29 22:30', '亮哥 确认完成', ''])
  return `<div class="dr-sec"><h4>时间线</h4><ul class="timeline">${ev.reverse().map(([tm, s, c]) => `<li class="${c}"><time>${tm}</time>${esc(s)}</li>`).join('')}</ul></div>`
}

window.openDrawer = function (id) {
  const t = byId(id); if (!t) return
  S.selected = id
  const k = kids(id), d = $('#drawer'), sc = $('#scrim'), wasHidden = d.hidden
  const path = pathOf(t)
  d.innerHTML = `
    <div class="dr-head">
      <div class="line1"><span class="code">T-${t.id}</span>${statusTag(t.status)}<span class="prio ${t.prio}">${t.prio} ${PRIO[t.prio]}</span>
        <button class="x" data-act="close" aria-label="关闭">×</button></div>
      ${path.length ? `<div class="dr-path">${path.map(esc).join(' › ')}</div>` : ''}
      <h2>${esc(t.title)}</h2>
    </div>
    <div class="dr-body">
      ${evidenceHtml(t)}
      ${t.status === 'blocked' ? `<div class="dup" style="color:var(--color-danger-text);background:var(--color-danger-bg)">受阻：${esc(t.blocked)}</div>` : ''}
      <div class="fields">
        <label class="field"><span>状态</span><select data-field="status">${Object.entries(STATUS).filter(([s]) => s !== 'pending' || t.status === 'pending').map(([s, [l]]) => `<option value="${s}" ${s === t.status ? 'selected' : ''}>${l}</option>`).join('')}</select></label>
        <label class="field"><span>重要性</span><select data-field="prio">${Object.entries(PRIO).map(([p, l]) => `<option value="${p}" ${p === t.prio ? 'selected' : ''}>${p} ${l}</option>`).join('')}</select></label>
        <div class="field"><span>关联模块</span><b>${esc(MODS[t.mod]?.group)} · ${esc(MODS[t.mod]?.title)}</b></div>
        <div class="field"><span>截止</span><b>${t.due || '未设置'}</b></div>
      </div>
      <div class="dr-sec"><h4>验收标准 <a>编辑</a></h4>${t.acceptance
        ? `<ol class="accept">${t.acceptance.map((a) => `<li>${esc(a)}</li>`).join('')}</ol>`
        : '<div class="dup">还没有验收标准。AI 提议完成时要对照这一栏，建议补两三条。</div>'}</div>
      <div class="dr-sec"><h4>子任务 ${k.length ? `· ${progress(t)[0]}/${progress(t)[1]}` : ''} <a data-child="${t.id}">+ 子任务</a> </h4><div class="sub-list">
        ${k.length ? sortTasks(k).map((c) => `<div class="sub-row" data-open="${c.id}"><span class="code">T-${c.id}</span><span style="flex:1">${esc(c.title)}</span>${statusTag(c.status)}</div>`).join('')
          : '<div class="sub-row" style="color:var(--text-muted);cursor:default">没有子任务。任务大于一天，可以让 AI 拆一下</div>'}
      </div></div>
      ${linksHtml(t)}
      ${timelineHtml(t)}
    </div>
    <div class="dr-foot">
      <button class="btn btn-ghost btn-sm" data-act="brief">生成代理任务书</button><span class="sp"></span>
      ${t.status === 'done' ? '<button class="btn btn-ghost btn-sm" data-act="reopen">重开</button>'
        : t.status === 'pending' ? '' : '<button class="btn btn-primary btn-sm" data-act="confirm">标记完成</button>'}
    </div>`
  if (wasHidden) {
    d.hidden = sc.hidden = false; d.classList.add('is-enter'); sc.classList.add('is-enter')
    requestAnimationFrame(() => requestAnimationFrame(() => { d.classList.remove('is-enter'); sc.classList.remove('is-enter') }))
  }
  renderAll()
}

window.closeDrawer = function () {
  const d = $('#drawer'), sc = $('#scrim'); if (d.hidden) return
  d.classList.add('is-enter'); sc.classList.add('is-enter'); S.selected = null
  setTimeout(() => { d.hidden = sc.hidden = true }, 180)
  renderAll()
}

function setStatus(t, s, msg) {
  const prev = t.status; t.status = s
  if (s === 'done') t.merged = t.merged || false
  toast(msg, () => { t.status = prev; openDrawer(t.id) })
  openDrawer(t.id)
}

window.drawerAction = function (act, el) {
  const t = byId(S.selected); if (!t) return
  if (act === 'close') return closeDrawer()
  if (act === 'confirm') {
    const open = kids(t.id).filter((c) => !CLOSED.has(c.status))
    if (open.length && !confirm(`还有 ${open.length} 个子任务没结束，仍然标记完成？`)) return
    return setStatus(t, 'done', `T-${t.id} 已完成`)
  }
  if (act === 'reject') { const r = prompt('驳回理由（写入时间线，AI 下次提议会参考）', '列表页筛选还没做'); if (r === null) return; return setStatus(t, 'doing', `已驳回，T-${t.id} 回到进行中`) }
  if (act === 'reopen') return setStatus(t, 'todo', `T-${t.id} 已重开`)
  if (act === 'split') {
    const id = Math.max(...TASKS.map((x) => x.id)) + 1
    TASKS.push({ id, parent: t.id, title: '回款审计：列表页按操作人筛选', prio: t.prio, status: 'todo', mod: t.mod, due: null })
    S.open.add(t.id); S.flash = id; toast(`已拆出 T-${id}`); return openDrawer(t.id)
  }
  if (act === 'accept-link') { const l = LINKS[t.id][+el.dataset.i]; l[2] = 'exact'; toast('已认领，这条 commit 计入该任务'); return openDrawer(t.id) }
  if (act === 'brief') {
    const text = `任务 T-${t.id}：${t.title}\n模块：${MODS[t.mod]?.group} / ${MODS[t.mod]?.title}\n验收标准：\n${(t.acceptance || ['（待补）']).map((a, i) => `${i + 1}. ${a}`).join('\n')}\n分支命名：<tool>/T-${t.id}-<slug>，commit message 带 T-${t.id}\n完成后调用 MCP propose_complete，不要自行标记完成。`
    navigator.clipboard?.writeText(text); return toast('代理任务书已复制，可直接粘给 Codex / Claude')
  }
  if (act === 'link') return toast('原型：从 docs/ 选文件或贴 URL，二期由上报器同步快照')
}

window.drawerField = function (field, value) {
  const t = byId(S.selected); if (!t) return
  if (field === 'status' && value === 'done') return drawerAction('confirm')
  if (field === 'status' && value === 'blocked') { const r = prompt('受阻原因（必填）'); if (!r) return openDrawer(t.id); t.blocked = r }
  t[field] = value; toast('已保存'); openDrawer(t.id)
}
