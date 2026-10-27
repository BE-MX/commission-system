-- SPDX-License-Identifier: AGPL-3.0-or-later
local Logic = require("apps/ark_board/logic")
local M = {}

function M.widget(ctx, size, box)
    local cache = ctx.cache:get()
    local L = ctx.i18n.t
    local lines = {}
    if cache and cache.tasks and cache.tasks[1] then lines[#lines + 1] = { L("tasks"), cache.tasks[1].title } end
    if cache and cache.notes and cache.notes[1] then lines[#lines + 1] = { L("notes"), cache.notes[1].title } end
    local primary = cache and (tostring(Logic.unread(cache)) .. " " .. L("unread")) or L("empty")
    return ctx.ui.basic(box, { title = L("name"), primary = primary,
        secondary = cache and cache.server_time and cache.server_time:sub(6, 16):gsub("T", " ") or L("config"), lines = lines })
end

function M.main(ctx, args, box, actions)
    local cache = ctx.cache:get() or {}
    local L, rows = ctx.i18n.t, {}
    rows[#rows + 1] = { title = L("import"), on_tap = actions.import }
    for _, part in ipairs({ { "messages", cache.messages or {} }, { "tasks", cache.tasks or {} }, { "notes", cache.notes or {} } }) do
        rows[#rows + 1] = { section = L(part[1]) }
        if #part[2] == 0 then rows[#rows + 1] = { note = { L("no_items") } } end
        for _, entry in ipairs(part[2]) do
            local item, kind = entry, part[1]
            rows[#rows + 1] = { title = item.title,
                sub = kind == "messages" and (item.read and L("read") or L("unread")) or (item.due_date or ""),
                on_tap = function() actions.detail(kind, item.id) end }
        end
    end
    if (cache.task_total or 0) > 20 then rows[#rows + 1] = { note = { L("task_limit") } } end
    return { title = L("name"), body = ctx.ui.rows(box, rows) }
end

function M.detail(ctx, args, box, acknowledge)
    local cache = ctx.cache:get() or {}
    local item
    for _, m in ipairs(cache[args.kind] or {}) do if m.id == args.id then item = m; break end end
    if not item then return { title = ctx.i18n.t("body"), body = ctx.ui.text(ctx.i18n.t("no_items"), ctx.ui.theme.FONT_BODY, false, box.w) } end
    local ui, T = ctx.ui, ctx.ui.theme
    local pages = Logic.pages(item.body)
    local page = math.max(1, math.min(tonumber(args.page) or 1, #pages))
    local button_h = (T.BTN_H + T.GAP) * ((args.kind == "messages" and 1 or 0) + (#pages > 1 and 1 or 0))
    local children = { ui.textbox(pages[page], T.FONT_BODY, box.w, box.h - button_h) }
    if #pages > 1 then children[#children + 1] = ui.button_row({
        { "‹", function() ctx.open("detail", { kind = args.kind, id = args.id, page = math.max(1, page - 1) }) end },
        { tostring(page) .. "/" .. tostring(#pages), function() end },
        { "›", function() ctx.open("detail", { kind = args.kind, id = args.id, page = math.min(#pages, page + 1) }) end },
    }, box.w) end
    if args.kind == "messages" then children[#children + 1] = ui.button{
        label = ctx.i18n.t("acknowledge"), w = box.w, inv = true,
        on_tap = function() acknowledge(item.id) end } end
    return { title = item.title, body = ui.vstack(children, T.GAP) }
end
return M
