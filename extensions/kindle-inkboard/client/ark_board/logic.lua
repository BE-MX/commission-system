-- SPDX-License-Identifier: AGPL-3.0-or-later
-- Pure protocol validation and cache reconciliation; no clock, filesystem or device access.
local M = {}

function M.valid_config(url, token)
    local authority = type(url) == "string" and url:match("^https://([^/]+)")
    return authority and authority:match("^[%w%.%-]+:?%d*$") ~= nil
        and not url:find("[?#%s]") and type(token) == "string" and token:match("^ink_[%w_-]+$") ~= nil
        and #token >= 30 and #token <= 100
end

function M.pages(text, count)
    local pages, chars = {}, {}
    for c in text:gmatch("[%z\1-\127\194-\244][\128-\191]*") do
        chars[#chars + 1] = c
        if #chars == (count or 180) then pages[#pages + 1] = table.concat(chars); chars = {} end
    end
    if #chars > 0 or #pages == 0 then pages[#pages + 1] = table.concat(chars) end
    return pages
end

function M.identity(url, token)
    local n = 5381
    for c in (tostring(url) .. "\0" .. tostring(token)):gmatch(".") do n = (n * 33 + c:byte()) % 4294967291 end
    return tostring(n)
end

local function valid_id(v) return type(v) == "number" and v > 0 and v == math.floor(v) end
local function array(v, max)
    if type(v) ~= "table" or #v > max then return false end
    for k in pairs(v) do if type(k) ~= "number" or k < 1 or k > #v or k ~= math.floor(k) then return false end end
    return true
end

function M.parse(envelope)
    local d = type(envelope) == "table" and envelope.code == 200 and envelope.data
    if type(d) ~= "table" or d.schema ~= 1 or not valid_id(d.device_id)
        or type(d.server_time) ~= "string" or not d.server_time:match("%+08:00$")
        or not array(d.tasks, 20) or not array(d.notes, 10) or not array(d.messages, 20)
        or not array(d.pending, 10) or not array(d.active_message_ids, 2000) then return nil, "bad_json" end
    for _, list in ipairs({ d.tasks, d.notes, d.messages }) do
        for _, item in ipairs(list) do
            if type(item) ~= "table" or not valid_id(item.id) or type(item.title) ~= "string"
                or type(item.body) ~= "string" then return nil, "bad_json" end
        end
    end
    local found, active = {}, {}
    for _, id in ipairs(d.active_message_ids) do
        if not valid_id(id) then return nil, "bad_json" end
        active[id] = true
    end
    for _, m in ipairs(d.messages) do
        if not active[m.id] or found[m.id] or type(m.read) ~= "boolean" then return nil, "bad_json" end
        found[m.id] = true
    end
    for _, p in ipairs(d.pending) do
        if type(p) ~= "table" or not found[p.id] then return nil, "bad_json" end
    end
    return d
end

function M.merge(old, d, queued_reads)
    old, queued_reads = old or {}, queued_reads or {}
    local keep, messages, order = {}, {}, {}
    for _, id in ipairs(d.active_message_ids) do keep[id] = true end
    for _, m in ipairs(old.messages or {}) do if keep[m.id] then messages[m.id] = m end end
    for _, m in ipairs(d.messages) do
        local copy = {}; for k, v in pairs(m) do copy[k] = v end
        copy.read = copy.read or queued_reads[tostring(m.id)] == true
        messages[m.id] = copy
    end
    for id in pairs(messages) do order[#order + 1] = id end
    table.sort(order, function(a, b) return a > b end)
    local list = {}
    for i = 1, math.min(#order, 200) do list[i] = messages[order[i]] end
    return { device_id = d.device_id, server_time = d.server_time, tasks = d.tasks, notes = d.notes,
        messages = list, task_total = d.task_total, tasks_allowed = d.tasks_allowed }
end

function M.unread(cache)
    local n = 0; for _, m in ipairs(cache and cache.messages or {}) do if not m.read then n = n + 1 end end
    return n
end

return M
