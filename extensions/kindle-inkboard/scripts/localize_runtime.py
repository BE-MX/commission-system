"""Add complete Simplified Chinese tables to the pinned Tinta runtime."""
from pathlib import Path
import json
import re


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError(f"Pinned localization context changed: {old[:65]}")
    return text.replace(old, new)


def lua_table(values):
    return "{\n" + "\n".join(
        f"[{json.dumps(k, ensure_ascii=False)}] = "
        + (lua_table(v) if isinstance(v, dict) else json.dumps(v, ensure_ascii=False)) + ","
        for k, v in sorted(values.items())
    ) + "\n}"


def apply_chinese(destination):
    root = Path(__file__).resolve().parents[1]
    tables = {p.stem: json.loads(p.read_text(encoding="utf-8"))
              for p in (root / "client/locales/zh").glob("*.json")}
    tables["names"] = {"sistema": "系统设置", "notificacoes": "通知", "bateria": "电池", "relogio": "时钟",
                       "contagem": "倒计时", "nota": "笔记", "repouso": "休眠", "timer": "计时器", "ark_board": "方舟看板"}
    tables["extra"] = {"abaixo de 20%": "电量低于 20%", "carga completa": "电池充满",
                       "servidor sem resposta": "服务器无响应", "servidor de volta": "服务器恢复"}
    locale = destination / "locales/zh.lua"
    locale.parent.mkdir(exist_ok=True)
    locale.write_text("-- Simplified Chinese translations for the pinned Tinta build.\nlocal M = " + lua_table(tables) + '''
function M.label(value, strings, lang)
    if lang ~= "zh" or type(value) ~= "string" then return value end
    for _, source in ipairs({ strings and strings.pt or {}, strings and strings.en or {} }) do
        for key, original in pairs(source) do
            if original == value and strings.zh and strings.zh[key] then return strings.zh[key] end
        end
    end
    return M.extra[value] or value
end
return M
''', encoding="utf-8", newline="\n")

    def edit(relative, fn):
        path = destination / relative
        path.write_text(fn(path.read_text(encoding="utf-8")), encoding="utf-8", newline="\n")

    edit("core/i18n.lua", lambda s: replace_once(s, 'M.LANGS = { "pt", "en" }', 'M.LANGS = { "pt", "en", "zh" }')
         .replace('local current = M.DEFAULT_LANG', '''M.STRINGS.zh = require("locales/zh").core
M.STRINGS.zh.lang_zh = "简体中文"
M.STRINGS.pt.lang_zh = "简体中文"
M.STRINGS.en.lang_zh = "简体中文"
local current = M.DEFAULT_LANG'''))
    edit("core/settings.lua", lambda s: replace_once(s, 'lang = { "pt", "en" },', 'lang = { "pt", "en", "zh" },'))
    def ui_strings(s):
        s = replace_once(s, 'M.LANGS = { "pt", "en" }', 'M.LANGS = { "pt", "en", "zh" }')
        s = replace_once(s, 'M.LANG_NAMES = { pt = "Português", en = "English" }',
                         'M.zh = require("locales/zh").ui\nM.LANG_NAMES = { pt = "Português", en = "English", zh = "简体中文" }')
        old = 'function M.set_lang(l) if M[l] and type(M[l]) == "table" and l ~= "LANGS" and l ~= "LANG_NAMES" then lang = l end end'
        return replace_once(s, old, '''function M.set_lang(l)
    if M[l] and type(M[l]) == "table" and l ~= "LANGS" and l ~= "LANG_NAMES" then
        lang = l
        M.LANG_NAMES = l == "zh" and { pt = "葡萄牙语", en = "英语", zh = "简体中文" }
            or { pt = "Português", en = "English", zh = "简体中文" }
    end
end''')
    edit("ui/strings.lua", ui_strings)

    for app in tables.keys() - {"core", "ui", "names", "extra"}:
        def strings(s, app=app):
            s = replace_once(s, "return {", "local strings = {")
            return s + f'\nstrings.zh = require("locales/zh").{app}\nreturn strings\n'
        edit(f"apps/{app}/strings.lua", strings)
        def manifest(s):
            s, count = re.subn(r'names = \{ pt = (\w+)\.pt\.name, en = \1\.en\.name \}',
                              r'names = { pt = \1.pt.name, en = \1.en.name, zh = \1.zh.name }', s)
            if count != 1:
                raise RuntimeError("App manifest names changed")
            return s
        edit(f"apps/{app}/init.lua", manifest)
    edit("apps/notificacoes/init.lua", lambda s: replace_once(s,
         'names = { pt = "Notificações", en = "Notifications" }',
         'names = { pt = "Notificações", en = "Notifications", zh = "通知" }'))
    edit("ui/organizer.lua", lambda s: replace_once(s, 'local short = m.short or m.name or it.app',
         'local short = (S.get_lang() == "zh" and require("locales/zh").names[it.app]) or m.short or m.name or it.app'))
    def system_screens(s):
        marker = 'local function types_text(m)'
        s = replace_once(s, marker, '''local function app_text(m, value)
    return require("locales/zh").label(value, m and m.strings, S.get_lang())
end

local function types_text(m)''')
        s = replace_once(s, '(n.label or n.type)', '(app_text(m, n.label or n.type))')
        s = s.replace('choice_label(f, v)', 'choice_label(f, v, m)')
        s = s.replace('return ch.label or tostring(v)', 'return app_text(m, ch.label or tostring(v))')
        s = s.replace('f.label or f.key', 'app_text(m, f.label or f.key)')
        s = s.replace('(f.hint or "")', '(app_text(m, f.hint or ""))')
        return s.replace('label = ch.label or tostring(ch.value)', 'label = app_text(m, ch.label or tostring(ch.value))')
    edit("apps/sistema/screens.lua", system_screens)
    edit("apps/sistema/logic.lua", lambda s: replace_once(s, 'if lang ~= "en" then s = s:gsub',
                                                        'if lang == "pt" then s = s:gsub'))
    edit("_meta.lua", lambda s: re.sub(r'description = _\(\[\[.*?\]\]\)',
         'description = _([[Kindle 信息看板：组件、通知、定时刷新与低功耗休眠。]])', s, flags=re.S))
