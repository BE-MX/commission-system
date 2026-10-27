-- SPDX-License-Identifier: AGPL-3.0-or-later
local Logic = require("apps/ark_board/logic")
local Strings = require("apps/ark_board/strings")
local View = require("apps/ark_board/view")
local Transport = require("apps/ark_board/net")

local function rearm(ctx, interval) ctx.wake_at(ctx.now() + (interval or 300)) end
local function empty(ctx)
    ctx.dismiss_popup()
    ctx.cache:put({ tasks = {}, notes = {}, messages = {} })
    ctx.data:set("state", nil)
end

local function acknowledge(ctx, id)
    local state = ctx.data:get("state") or {}
    state.reads = state.reads or {}; state.reads[tostring(id)] = true
    ctx.data:set("state", state)
    local cache = ctx.cache:get()
    if cache then
        local copy = {}; for k, v in pairs(cache) do copy[k] = v end
        copy.messages = {}
        for i, m in ipairs(cache.messages or {}) do
            local value = {}; for k, v in pairs(m) do value[k] = v end
            if value.id == id then value.read = true end
            copy.messages[i] = value
        end
        ctx.cache:put(copy)
    end
    rearm(ctx, 1); ctx.redraw()
end

local app = {
    id = "ark_board", name = Strings.en.name, short = "ARK", description = Strings.en.description,
    version = 1, api = 1, net = true, sensitive = false,
    sizes = { "4x2", "4x4", "2x2" }, defaults = { interval = 300 },
    default_layout = { home = { size = "4x2", order = 1 }, sleep = { size = "4x2", order = 1 } },
    settings = { { key = "url", label = Strings.en.url, type = "url" }, { key = "token", label = Strings.en.token, type = "token" } },
    notifications = { { type = "message", label = Strings.en.messages } }, strings = Strings,
    init = function(ctx) rearm(ctx, 1) end,
    attention = function(ctx) return Logic.unread(ctx.cache:get()) > 0 end,
}

function app.refresh(ctx, done)
    rearm(ctx)
    if not ctx.after_commit or not ctx.dismiss_popup then return done(false, ctx.i18n.t("runtime")) end
    if not ctx.is_durable or not ctx.is_durable() then return done(false, ctx.i18n.t("storage")) end
    local url, token = ctx.settings:get("url"), ctx.settings:get("token")
    local state = ctx.data:get("state") or { shown = {}, reads = {} }
    local identity = Logic.identity(url, token)
    if state.identity and state.identity ~= identity then empty(ctx); state = { shown = {}, reads = {} } end
    if not Logic.valid_config(url, token) then return done(false, ctx.i18n.t("config")) end
    local net = ctx.ark_net or Transport
    local opts = { token = token, timeout = 6, max_bytes = 256 * 1024 }
    local envelope, why = net.get_json(url:gsub("/+$", "") .. "/device/sync", opts)
    if not envelope then
        if why == "unauthorized" or why == "forbidden" then
            empty(ctx); ctx.toast(ctx.i18n.t("denied"))
            ctx.confirm(ctx.i18n.t("name"), ctx.i18n.t("denied"), ctx.i18n.t("acknowledge"), function() end)
        end
        return done(false, ctx.i18n.t("failed"))
    end
    local data, parse_error = Logic.parse(envelope)
    if not data then return done(false, parse_error) end
    state.identity, state.shown, state.reads = identity, state.shown or {}, state.reads or {}
    local cache = Logic.merge(ctx.cache:get(), data, state.reads)
    local active = {}; for _, id in ipairs(data.active_message_ids) do active[tostring(id)] = true end
    for id in pairs(state.reads) do if not active[id] then state.reads[id] = nil end end
    for id in pairs(state.shown) do if not active[id] then state.shown[id] = nil end end
    if state.popup and not active[tostring(state.popup)] then ctx.dismiss_popup(); state.popup = nil end
    -- Persist first; any storage exception prevents the remote receipt.
    ctx.cache:put(cache); ctx.data:set("state", state)
    done(true) -- The host arms notification delivery here, including the first session refresh.
    ctx.after_commit(function()
    local newest, ids = nil, {}
    local pending = {}; for _, p in ipairs(data.pending) do pending[p.id] = true end
    for _, m in ipairs(data.messages) do
        if pending[m.id] then ids[#ids + 1] = m.id end
        local key = tostring(m.id)
        if not m.read and not state.shown[key] then
            local emitted, reason = ctx.notify{ key = "message:" .. key, type = "message", title = ctx.i18n.t("name"), body = ctx.i18n.t("unread"),
                prio = m.priority == "high" and "alta" or "normal", route = { "detail", { kind = "messages", id = m.id } } }
            if emitted or reason == "dup" then newest = m end
            state.shown[key] = true
        end
    end
    if newest then
        local id = newest.id
        local pages = Logic.pages(newest.body, 150)
        state.popup = id
        if #pages > 1 then
            ctx.confirm(newest.title .. ctx.i18n.t("preview"), pages[1], ctx.i18n.t("full"), function()
                ctx.open("detail", { kind = "messages", id = id })
            end)
        else
            ctx.confirm(newest.title, pages[1], ctx.i18n.t("acknowledge"), function() acknowledge(ctx, id) end)
        end
    end
    ctx.data:set("state", state)
    local receipt_url = url:gsub("/+$", "") .. "/device/receipts"
    if #ids > 0 then net.post_json(receipt_url, { ids = ids, read = false }, opts) end
    local reads = {}; for id in pairs(state.reads) do reads[#reads + 1] = tonumber(id); if #reads == 20 then break end end
    if #reads > 0 then
        local result = net.post_json(receipt_url, { ids = reads, read = true }, opts)
        if result and result.code == 200 then
            for _, id in ipairs(reads) do state.reads[tostring(id)] = nil end
            ctx.data:set("state", state)
        end
    end
    if (data.pending_count or 0) > #data.pending then rearm(ctx, 60) end
    ctx.redraw()
    end)
end

app.widget = View.widget
app.screens = {
    main = function(ctx, args, box)
        return View.main(ctx, args, box, {
            import = function()
                local ok = require("apps/ark_board/config").import(ctx)
                ctx.toast(ctx.i18n.t(ok and "imported" or "import_error"))
                if ok then rearm(ctx, 1) end
            end,
            detail = function(kind, id) ctx.open("detail", { kind = kind, id = id }) end,
        })
    end,
    detail = function(ctx, args, box) return View.detail(ctx, args or {}, box, function(id) acknowledge(ctx, id) end) end,
}
return app
