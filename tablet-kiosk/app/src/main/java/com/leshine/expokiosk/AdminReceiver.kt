package com.leshine.expokiosk

import android.app.admin.DeviceAdminReceiver

/**
 * 设备管理接收器。仅用于把本应用设为「设备所有者」后开启 Lock Task 真锁定。
 * 无自定义逻辑，声明存在即可（见 AndroidManifest 与 res/xml/device_admin.xml）。
 */
class AdminReceiver : DeviceAdminReceiver()
