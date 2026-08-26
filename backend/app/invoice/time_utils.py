"""订单域时间兼容导出；新代码统一从 app.core.time 导入。"""

from app.core.time import BEIJING_TIMEZONE, beijing_now, to_beijing_time


__all__ = ("BEIJING_TIMEZONE", "beijing_now", "to_beijing_time")
