"""只能由专用业务页面维护、不可暴露给通用字典接口的类型。"""


TEAM_DICT_TYPE = "dingtalk_gmv_team"
MEMBER_DICT_TYPE = "dingtalk_gmv_member"
ADMIN_DICT_TYPE = "dingtalk_gmv_admin"

RESERVED_DICT_TYPES = (TEAM_DICT_TYPE, MEMBER_DICT_TYPE, ADMIN_DICT_TYPE)
RESERVED_DICT_TYPE_SET = frozenset(RESERVED_DICT_TYPES)

