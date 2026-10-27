return function(H)
    local host = H.Host
    local ctx = host.c.registry:ctx("ark_board")
    ctx.settings:set("url", "https://example.com/api/inkboard")
    ctx.settings:set("token", "ink_" .. string.rep("z", 43))
    ctx.is_durable = function() return true end -- The harness uses an in-memory store; this test exercises host transaction ordering.
    local posts = 0
    local data = { schema = 1, device_id = 1, server_time = "2026-10-25T12:00:00+08:00", tasks = {}, notes = {},
        messages = { { id = 99, title = "Private alert", body = "Private body", read = false, priority = "high" } },
        pending = { { id = 99 } }, pending_count = 1, active_message_ids = { 99 } }
    ctx.ark_net = { get_json = function() return { code = 200, data = data } end,
        post_json = function() posts = posts + 1; return { code = 200 } end }
    local store = host.c.store
    local transaction = store.transaction
    local function clone(v)
        if type(v) ~= "table" then return v end
        local t = {}; for k, x in pairs(v) do t[k] = clone(x) end; return t
    end
    store.transaction = function(s, fn)
        local saved = clone(s._db)
        transaction(s, fn)
        for k in pairs(s._db) do s._db[k] = nil end
        for k, v in pairs(saved) do s._db[k] = v end
        return false, "simulated COMMIT failure"
    end
    local cleaned = 0
    local ok = host:run({ "ark_board" }, false, false, function() cleaned = cleaned + 1 end)
    H.check("COMMIT failure is reported by real host", ok == false)
    H.check("failed sleeping refresh runs its power cleanup callback", cleaned == 1)
    H.check("no receipt before successful COMMIT", posts == 0)
    H.check("no private popup after failed COMMIT", not host.window.dialog)
    store.transaction = transaction
    H.step("sync through successful real host COMMIT", function() host:run({ "ark_board" }, false) end)
    H.check("receipt sent after successful real host COMMIT", posts == 1)
    H.check("real modal contains message", host.window.dialog and host.window.dialog.text == "Private body")
    data.messages, data.pending, data.active_message_ids, data.pending_count = {}, {}, {}, 0
    H.step("withdraw while real modal is visible", function() host:run({ "ark_board" }, false) end)
    H.check("withdrawal closes real modal", host.window.dialog == nil)
end
