"""三个描述性值域的唯一读取口：后台可增删，AI 与校验都从这里取（红线 7）。"""
from sqlalchemy.orm import Session

from app.domestic_followup.constants import DICT_CATEGORY, DICT_CHANNEL, DICT_STATE_CHANGE
from app.system.models import SysDict

DICT_TYPES = (DICT_STATE_CHANGE, DICT_CATEGORY, DICT_CHANNEL)


def load_values(db: Session) -> dict[str, list[str]]:
    rows = (
        db.query(SysDict.type, SysDict.label)
        .filter(SysDict.type.in_(DICT_TYPES), SysDict.is_active.is_(True))
        .order_by(SysDict.type, SysDict.sort, SysDict.id)
        .all()
    )
    values = {dict_type: [] for dict_type in DICT_TYPES}
    for dict_type, label in rows:
        values[dict_type].append(label)
    return values
