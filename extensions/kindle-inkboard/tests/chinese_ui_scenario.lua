return function(H)
    local host, win = H.Host, H.window()
    local S = require("ui/strings")
    H.check("Chinese language choice is accepted", host:set("lang", "zh") ~= false)
    H.check("UI language is Chinese", S.get_lang() == "zh")
    for id, name in pairs(require("locales/zh").names) do
        H.check("Chinese app name: " .. id, host:appName(id) == name)
    end
    for _, page in ipairs({
        {"main", "系统设置", "无线网络"}, {"notifs", "通知", "电量低于 20%"},
        {"updates", "刷新计划", "夜间免打扰"}, {"sleep", "休眠", "自动休眠"},
        {"conn", "连接", "服务器"}, {"screen", "屏幕与导航", "字号"},
        {"apps", "应用", "笔记"}, {"data", "数据", "导出诊断"},
    }) do
        H.step("Chinese system page: " .. page[1], function() win:goHome(); win:openApp("sistema", page[1]) end)
        H.check("Chinese page title: " .. page[1], H.contains_text(win[1], page[2]))
        local found = H.contains_text(win[1], page[3])
        for n = 1, 2 do
            if not found then
                H.step("Chinese list page " .. n .. ": " .. page[1], function() win:setPage(n) end)
                found = H.contains_text(win[1], page[3])
            end
        end
        H.check("Chinese page content: " .. page[1], found)
    end
    for _, app in ipairs({ {"nota", "最大字数"}, {"timer", "专注时长"}, {"ark_board", "设备凭证"} }) do
        H.step("Chinese app settings: " .. app[1], function()
            win:goHome(); win:openApp("sistema", "app", { id = app[1] })
        end)
        H.check("Chinese field labels: " .. app[1], H.contains_text(win[1], app[2]))
    end
    for _, app in ipairs({"relogio", "bateria", "contagem", "nota", "timer", "repouso", "ark_board"}) do
        H.step("Chinese bundled app: " .. app, function() win:goHome(); win:openApp(app) end)
        H.check("Bundled app title: " .. app, H.contains_text(win[1], host:appName(app)))
    end
    H.check("Language choices use Chinese names", S.LANG_NAMES.pt == "葡萄牙语" and S.LANG_NAMES.en == "英语")
end
