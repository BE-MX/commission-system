package.path = CLIENT_ROOT .. "/client/?.lua;" .. package.path
local files = { logic = "logic", view = "view", strings = "strings", config = "config", net = "net" }
for name, file in pairs(files) do
    package.preload["apps/ark_board/" .. name] = function() return assert(loadfile(CLIENT_ROOT .. "/client/ark_board/" .. file .. ".lua"))() end
end
local Logic = require("apps/ark_board/logic")
local App = assert(loadfile(CLIENT_ROOT .. "/client/ark_board/init.lua"))()
local total = 0
local function check(value, label) assert(value, label); total = total + 1 end
local function clone(v)
    if type(v) ~= "table" then return v end
    local t = {}; for k, x in pairs(v) do t[k] = clone(x) end; return t
end
local token = "ink_" .. string.rep("a", 43)
check(Logic.valid_config("https://example.com/api/inkboard", token), "HTTPS accepted")
check(not Logic.valid_config("http://example.com", token), "HTTP rejected")
check(not Logic.valid_config("https://user@example.com", token), "userinfo rejected")
check(not Logic.valid_config("https://example.com/?token=x", token), "query credential rejected")
local cache, state, popups, posts, emitted, wakes = nil, nil, {}, {}, {}, {}
local data = { schema = 1, device_id = 1, server_time = "2026-10-25T12:00:00+08:00", refresh_seconds = 300,
    tasks = { { id = 1, title = "Task", body = "Do it" } }, notes = { { id = 1, title = "Note", body = "Memo" } },
    messages = { { id = 10, title = "Alert", body = "Hello", priority = "high", read = false } },
    pending = { { id = 10 } }, pending_count = 1, active_message_ids = { 10 }, task_total = 1 }
local answer, failure, storage_failure, ack_failure, commit_failure = data, nil, false, false, false
local callbacks, current_popup = {}, nil
local armed = false
local ctx = {
    now = function() return 1000 end,
    i18n = { t = function(k) return require("apps/ark_board/strings").en[k] or k end },
    settings = { get = function(_, k) return k == "url" and "https://example.com/api/inkboard" or token end },
    wake_at = function(at) wakes[#wakes + 1] = at end,
    data = { get = function() return clone(state) end, set = function(_, _, v) state = clone(v) end },
    cache = { get = function() return clone(cache) end, put = function(_, v)
        if storage_failure then error("disk full") end
        cache = clone(v)
    end },
    ark_net = {
        get_json = function() if failure then return nil, failure end; return { code = 200, data = clone(answer) } end,
        post_json = function(url, body)
            posts[#posts + 1] = clone(body)
            if ack_failure then return nil, "unreachable" end
            return { code = 200, data = body }
        end,
    },
    notify = function(n) check(armed, "notification after first-session arm"); emitted[#emitted + 1] = n; return #emitted end,
    confirm = function(title, body, label, fn)
        current_popup = { title = title, body = body, label = label, fn = fn }; popups[#popups + 1] = current_popup
    end,
    after_commit = function(fn) callbacks[#callbacks + 1] = fn end,
    is_durable = function() return true end,
    dismiss_popup = function() current_popup = nil end,
    open = function(screen, args) current_popup = { screen = screen, args = args } end,
    toast = function() end, redraw = function() end,
}
local function refresh()
    local done_count = 0
    callbacks = {}
    local old_cache, old_state, before_posts = clone(cache), clone(state), #posts
    App.refresh(ctx, function(ok) done_count = done_count + 1; if ok then armed = true end end)
    check(#posts == before_posts, "no server receipt before outer transaction commit")
    if commit_failure then cache, state = old_cache, old_state
    else for _, fn in ipairs(callbacks) do fn() end end
    check(done_count == 1, "exactly one completion")
end
App.init(ctx); check(wakes[1] == 1001, "initial sync requested")
refresh()
check(#popups == 1 and #posts == 1 and not posts[1].read, "first new message pops up and receipt is not read")
check(cache.tasks[1].title == "Task" and cache.notes[1].body == "Memo", "task and note displayed")
check(emitted[1].title ~= "Alert" and emitted[1].body ~= "Hello", "host notification store contains no private message")
refresh(); check(#popups == 1, "duplicate sync does not repeat popup")
-- A process restart reuses durable state and must not re-alert.
App = assert(loadfile(CLIENT_ROOT .. "/client/ark_board/init.lua"))(); refresh()
check(#popups == 1, "restart preserves deduplication")
popups[1].fn(); check(cache.messages[1].read, "explicit user action marks local read")
ack_failure = true; refresh(); check(state.reads["10"], "offline read receipt is retained")
ack_failure = false; refresh(); check(not state.reads["10"], "read receipt clears only after server acceptance")
failure = "unreachable"; refresh(); check(cache.tasks[1].title == "Task", "offline cache retained")
failure = nil; answer = clone(data); answer.messages = {}; answer.pending = {}; answer.active_message_ids = {}; answer.pending_count = 0
refresh(); check(#cache.messages == 0, "withdrawn or expired messages removed")
check(current_popup == nil, "withdrawal closes already visible private popup")
answer = clone(data); commit_failure = true
count = #posts; refresh(); check(#posts == count and #cache.messages == 0, "outer COMMIT failure never acknowledges or displays message")
commit_failure = false
answer.messages[1].body = string.rep("长", 151)
refresh(); check(current_popup.label == ctx.i18n.t("full"), "long message opens full text instead of acknowledging preview")
current_popup.fn(); check(current_popup.screen == "detail" and not state.reads["10"], "view full text is not read acknowledgement")
answer = clone(data); storage_failure = true
local count = #posts; local ok = pcall(refresh)
check(not ok and #posts == count, "disk failure never acknowledges server message")
storage_failure = false; failure = "unauthorized"; refresh()
check(#cache.tasks == 0 and #cache.notes == 0 and #cache.messages == 0, "revoked credentials clear private cache")
check(popups[#popups].body ~= "Hello", "revocation replaces private popup")
local chinese = string.rep("你好", 120)
local pages = Logic.pages(chinese, 150)
check(#pages == 2 and table.concat(pages) == chinese, "UTF8 pagination does not split or drop characters")
check(wakes[#wakes] == 1300, "failure retains bounded next wake")
ctx.is_durable = function() return false end
local before = #posts
local refused = false
App.refresh(ctx, function(ok) refused = not ok end)
check(refused and #posts == before, "memory-only host refuses durable message acceptance")
print("client: " .. total .. " checks passed (LuaJIT 2.1)")
