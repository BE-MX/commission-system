-- SPDX-License-Identifier: AGPL-3.0-or-later
local text = {
    name = "方舟看板", description = "个人待办、备忘与消息", url = "方舟接口地址", token = "设备凭证",
    empty = "等待同步", tasks = "待办", notes = "备忘", messages = "消息", read = "已读", unread = "未读",
    import = "导入设备配置", imported = "配置已导入，请点击顶部刷新", import_error = "未找到有效的设备配置文件",
    config = "请先导入设备配置", failed = "同步失败，保留上次信息", denied = "设备凭证失效，请重新绑定",
    body = "详情", acknowledge = "知道了", no_items = "暂无内容", refresh = "约每 5 分钟同步",
    full = "查看全文", preview = "（消息预览）", runtime = "请使用配套安装包更新 Tinta",
    storage = "本地存储不可用，暂不确认接收消息",
    pending_read = "已读回执待同步", task_limit = "显示前 20 项，全部任务请到方舟查看",
    settings_changed = "配置已变化，等待重新同步",
}
-- App content is Chinese; both host language modes use the same complete key set.
return { pt = text, en = text, zh = text }
