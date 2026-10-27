-- SPDX-License-Identifier: AGPL-3.0-or-later
-- Explicit one-time import. Never log file contents or include credentials in exports.
local Logic = require("apps/ark_board/logic")
local M = {}
function M.import(ctx)
    local path = require("datastorage"):getDataDir() .. "/ark-board.local.json"
    local file = io.open(path, "rb")
    if not file then return false end
    local raw = file:read(4097); file:close()
    if not raw or #raw > 4096 then return false end
    local ok, value = pcall(require("json").decode, raw)
    if not ok or type(value) ~= "table" or not Logic.valid_config(value.url, value.token) then return false end
    local a = ctx.settings:set("url", value.url:gsub("/+$", ""))
    local b = ctx.settings:set("token", value.token)
    if not a or not b then return false end
    ctx.cache:put({ tasks = {}, notes = {}, messages = {} })
    ctx.data:set("state", nil)
    os.remove(path)
    return true
end
return M
