"""跟进描述性值域由字典管理，录入和 AI 复用同一读取口。"""
from sqlalchemy.orm import Session

from app.domestic_followup.constants import DICT_CATEGORY, DICT_CHANNEL, DICT_OBSTACLE, DICT_RESULT, DICT_STATE_CHANGE
from app.system.models import SysDict

DICT_TYPES = (DICT_STATE_CHANGE, DICT_CATEGORY, DICT_CHANNEL, DICT_RESULT, DICT_OBSTACLE)


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
