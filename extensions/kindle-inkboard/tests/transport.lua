local Net = require("apps/ark_board/net")
local tests = 0
local function check(ok, label) assert(ok, label); tests = tests + 1 end
check(Net.matches("ark.example.com", "*.example.com"), "single-label wildcard")
check(not Net.matches("a.ark.example.com", "*.example.com"), "wildcard does not span labels")
check(not Net.matches("example.com", "*.example.com"), "wildcard cannot match root")
check(not Net.matches("ark.example.com", "ark.example.com\0.evil"), "NUL rejected")
local host_ok, chain_ok, sent = true, true, 0
local response = { code = 200, data = { ok = true } }
local fake_socket = {}
function fake_socket.tcp()
    return { settimeout = function() return 1 end, connect = function() return 1 end, close = function() end }
end
package.preload["socket"] = function() return fake_socket end
package.preload["socketutil"] = function() return { set_timeout = function() end, reset_timeout = function() end } end
package.preload["ssl"] = function() return { wrap = function(tcp, options)
    check(options.verify == "peer" and options.cafile:match("ca%-bundle.crt$"), "CA verification required")
    return { settimeout = function() end, sni = function(_, host) check(host == "ark.example.com", "SNI matches origin") end,
        dohandshake = function() return chain_ok end, close = function() end,
        getpeercertificate = function() return { extensions = function() return {
            ["2.5.29.17"] = { dNSName = { host_ok and "ark.example.com" or "evil.example.com" } }
        } end } end }
end } end
package.preload["socket.http"] = function() return { request = function(req)
    local connection = req.create()
    local ok = connection:connect()
    if not ok then return nil, "failed" end
    sent = sent + 1
    check(req.redirect == false, "redirect cannot forward bearer")
    check(req.headers.Host == "ark.example.com", "original HTTP host preserved")
    req.sink("{}")
    return 1, 200
end } end
package.preload["ltn12"] = function() return { source = { string = function(raw) return function() return raw end end } } end
package.preload["json"] = function() return { encode = function() return "{}" end, decode = function() return response end } end
local opts = { token = "ink_" .. string.rep("x", 43) }
check(Net.get_json("https://ark.example.com/api/inkboard/device/sync", opts) == response, "verified TLS request works")
chain_ok = false
check(not Net.get_json("https://ark.example.com/api", opts) and sent == 1, "bad CA chain prevents authenticated HTTP send")
chain_ok, host_ok = true, false
check(not Net.get_json("https://ark.example.com/api", opts) and sent == 1, "wrong SAN prevents authenticated HTTP send")
print("transport: " .. tests .. " checks passed")
