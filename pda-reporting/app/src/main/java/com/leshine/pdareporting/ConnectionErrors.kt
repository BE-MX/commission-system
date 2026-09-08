package com.leshine.pdareporting

import java.io.IOException
import java.net.ConnectException
import java.net.SocketTimeoutException
import java.net.UnknownHostException
import javax.net.ssl.SSLException
import javax.net.ssl.SSLPeerUnverifiedException

internal fun connectionErrorMessage(error: Exception): String = when (error) {
    is ApiException -> error.message
    is SSLPeerUnverifiedException -> "服务器证书与地址不匹配，请核对服务器地址并联系管理员"
    is SSLException -> "HTTPS 安全连接失败，请检查 PDA 日期时间；时间正确时请联系管理员检查证书或更新 APP"
    is UnknownHostException -> "无法解析服务器地址，请检查地址拼写和 Wi-Fi 网络"
    is SocketTimeoutException -> "服务器连接超时，请检查网络后重试"
    is ConnectException -> "无法连接服务器，请检查网络或联系管理员确认服务状态"
    is IOException -> "网络连接中断，请检查 Wi-Fi 后重试"
    else -> error.message ?: "未知错误"
}
