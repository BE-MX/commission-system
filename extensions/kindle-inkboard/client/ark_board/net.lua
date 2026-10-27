-- SPDX-License-Identifier: AGPL-3.0-or-later
-- Verified HTTPS transport: CA chain AND SAN hostname are checked before any bearer header is sent.
local Logic = require("apps/ark_board/logic")
local M = {}

function M.matches(host, name)
    if type(name) ~= "string" or name:find("%z") then return false end
    host, name = host:lower(), name:lower()
    if name == host then return true end
    local suffix = name:match("^%*%.(.+)$")
    if not suffix or not suffix:find("%.") then return false end
    local first, rest = host:match("^([^.]+)%.(.+)$")
    return first ~= nil and rest == suffix
end

local function matches_certificate(cert, host)
    local extensions = cert and cert:extensions()
    local san = extensions and extensions["2.5.29.17"]
    if not san then return false end
    for _, value in ipairs(san.dNSName or {}) do if M.matches(host, value) then return true end end
    for _, value in ipairs(san.iPAddress or {}) do if value == host then return true end end
    return false
end

local function request(method, url, body, opts)
    opts = opts or {}
    if not Logic.valid_config(url, opts.token) then return nil, "unauthorized" end
    local socket, ssl = require("socket"), require("ssl")
    local http, ltn12, json = require("socket.http"), require("ltn12"), require("json")
    if http.PROXY then return nil, "unreachable" end -- Never send this credential through implicit proxy configuration.
    local authority, path = url:match("^https://([^/]+)(/.*)$")
    authority = authority or url:match("^https://(.+)$"); path = path or "/"
    local host, port = authority:match("^([^:]+):(%d+)$")
    host, port = host or authority, tonumber(port) or 443
    local ca_file = (debug.getinfo(1, "S").source:match("^@(.*/)") or "") .. "certs/ca-bundle.crt"
    local timeout = opts.timeout or 6
    local function create()
        local conn = { sock = assert(socket.tcp()) }
        function conn:settimeout() return self.sock:settimeout(timeout) end
        function conn:connect()
            self.sock:settimeout(timeout)
            local ok = self.sock:connect(host, port)
            if not ok then self.sock:close(); return nil, "connect failed" end
            local wrapped, why = ssl.wrap(self.sock, { mode = "client", protocol = "any", verify = "peer", cafile = ca_file,
                options = { "all", "no_sslv2", "no_sslv3", "no_tlsv1" } })
            if not wrapped then self.sock:close(); return nil, "TLS unavailable" end
            self.sock = wrapped; wrapped:settimeout(timeout); wrapped:sni(host)
            local secured = wrapped:dohandshake()
            if not secured or not matches_certificate(wrapped:getpeercertificate(), host) then
                wrapped:close(); return nil, "certificate verification failed"
            end
            return 1
        end
        return setmetatable(conn, { __index = function(t, key)
            local fn = t.sock[key]
            if type(fn) == "function" then return function(_, ...) return fn(t.sock, ...) end end
        end })
    end
    local raw = body and json.encode(body) or nil
    local chunks, size, too_large = {}, 0, false
    local req = {
        -- LuaSocket parses HTTP framing; the custom connector always performs verified TLS to the original endpoint.
        url = "http://" .. authority .. path, method = method, create = create, redirect = false,
        headers = { Host = authority, Authorization = "Bearer " .. opts.token, Accept = "application/json", ["Accept-Encoding"] = "identity" },
        sink = function(chunk)
            if chunk then size = size + #chunk; if size > (opts.max_bytes or 262144) then too_large = true; return nil, "too large" end
                chunks[#chunks + 1] = chunk end
            return 1
        end,
    }
    if raw then req.source = ltn12.source.string(raw); req.headers["Content-Type"] = "application/json"; req.headers["Content-Length"] = tostring(#raw) end
    local socketutil = require("socketutil")
    socketutil:set_timeout(timeout, timeout + 8)
    local call_ok, result, code = pcall(http.request, req)
    socketutil:reset_timeout()
    if too_large then return nil, "too_large" end
    if not call_ok or not result then return nil, "unreachable" end
    if code == 401 then return nil, "unauthorized" end
    if code == 403 then return nil, "forbidden" end
    if code ~= 200 then return nil, "http" end
    local ok, parsed = pcall(json.decode, table.concat(chunks))
    if not ok or type(parsed) ~= "table" then return nil, "bad_json" end
    return parsed
end

function M.get_json(url, opts) return request("GET", url, nil, opts) end
function M.post_json(url, body, opts) return request("POST", url, body, opts) end
return M
