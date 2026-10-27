-- The actual KOReader font module and framebuffer scale function are loaded by Python.
-- Only native FreeType and widgets are stubbed: no fake Font:getFace bypassing scaling.
package.path = PLUGIN .. "/?.lua;" .. package.path
local function preload(name, value) package.preload[name] = function() return value end end
local screen = { w = 1072, h = 1448, getWidth = function(s) return s.w end,
    getHeight = function(s) return s.h end, scaleBySize = KOREADER_SCALE }
preload("device", { screen = screen })
preload("fontlist", { fontdir = "/fonts", getFontList = function() return {} end })
preload("ffi/freetype", { newFaceSize = function(_, size)
    return { size = size, getEmboldenHalfStrength = function() return 0 end }
end })
preload("logger", { dbg = function() end, err = function() end })
preload("util", { splitFilePathName = function(p) return p:match("^(.-)([^/]+)$") end })
G_reader_settings = { nilOrTrue = function() return true end, has = function() return false end }
local Font = assert(loadfile(KOREADER_FONT))()
preload("ui/font", Font)

local Geom = {}
function Geom:new(o) return o or {} end
preload("ui/geometry", Geom)
local Widget = {}
function Widget:extend(o) o = o or {}; self.__index = self; return setmetatable(o, self) end
function Widget:new(o) o = self:extend(o); if o.init then o:init() end; return o end
function Widget:free() end
preload("ui/widget/widget", Widget)
preload("ffi/blitbuffer", { COLOR_BLACK = "black", COLOR_WHITE = "white" })
local paints = {}
local Text = Widget:extend{}
function Text:init()
    self.face = Font:getAdjustedFace(self.face, self.bold)
end
function Text:getSize()
    return { w = math.min(self.max_width or 10000, #self.text * self.face.size * 0.55),
        h = math.floor(self.face.size * 1.35) }
end
function Text:paintTo(_, x, y)
    local s = self:getSize(); paints[#paints + 1] = { x = x, y = y, w = s.w, h = s.h }
end
preload("ui/widget/textwidget", Text)
preload("ui/widget/textboxwidget", Text)
local T, Draw, Row = require("ui/theme"), require("ui/draw"), require("ui/row")
local bb = { paintRoundedRect = function() end, paintBorder = function() end, paintRect = function() end }
local passed, failed, examples = 0, 0, {}
local function check(ok, label)
    if ok then passed = passed + 1 else
        failed = failed + 1; if #examples < 8 then examples[#examples + 1] = label end
    end
end
for _, dimensions in ipairs({ {1072,1448}, {1448,1072}, {600,800}, {480,640}, {800,1280} }) do
    screen.w, screen.h = unpack(dimensions)
    T.configure(screen.w, screen.h)
    for _, dpi in ipairs({ 0, 120, 300, 420 }) do
        screen.dpi_override, screen.dpi = dpi > 0, dpi
        for _, factor in ipairs({ 1, 1.15, 1.5 }) do
            T.set_text_factor(factor)
            local label = screen.w .. "x" .. screen.h .. ", dpi=" .. dpi .. ", text=" .. factor
            for _, key in ipairs({"FONT_MIN", "FONT_BODY", "FONT_TITLE", "FONT_CLOCK", "FONT_HUGE"}) do
                local face = Draw.face(T[key])
                check(face.size == T[key], label .. " " .. key .. ": wanted " .. T[key] .. ", got " .. face.size)
                local bold = Font:getAdjustedFace(face, true)
                local fallback = face.getFallbackFont(1)
                check(bold.size == T[key] and fallback.size == T[key], label .. ": bold/fallback size drift")
            end
            paints = {}
            local row = Row.new{ w = T.BW - 2*T.MARGIN, title = "Notificações",
                sub = "por app, aviso no topo, repouso", right = "›" }
            row:paintTo(bb, 0, 0)
            for _, p in ipairs(paints) do
                check(p.y >= 0 and p.y + p.h <= row.h, label .. ": row text escapes its tap target")
            end
            row:free()
        end
    end
end
print(("Font scaling regression: %d passed, %d failed"):format(passed, failed))
for _, label in ipairs(examples) do print("FAIL: " .. label) end
assert(failed == 0, "KOReader font scaling/layout regression")
