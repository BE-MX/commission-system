"""Fixed requested award rosters, resolving identities through current active bindings."""
import json
from pathlib import Path

from app.battle_report.access import bound_accounts

BASELINES = Path(__file__).resolve().parent / "assets" / "annual_baselines_2025.json"
PK_TEAMS = {"一组": ["张心茹", "罗馨瑜", "胡宁宁", "韩玥", "刘婷"],
            "二组": ["凯丽", "高瑞杰", "刘也", "栾奕", "李秀玉"]}
ALIASES = {"凯丽": "凯丽比努尔·阿伍提"}


def presets(db):
    accounts = bound_accounts(db)
    def resolve(name):
        found = [a for a in accounts if a["user_name"] == ALIASES.get(name, name)]
        return found[0] if len(found) == 1 else None
    source = json.loads(BASELINES.read_text(encoding="utf-8"))
    annual_members, annual_bases, annual_missing = [], [], []
    for row in source["baselines"]:
        account = resolve(row["name"])
        if account is None:
            annual_missing.append(row["name"])
            continue
        annual_members.append({"ark_user_id": account["ark_user_id"], "team": "年度参评", "is_captain": False})
        annual_bases.append({"ark_user_id": account["ark_user_id"], "hired_date": row["hired_date"],
                             "gmv_2025_usd": row["gmv_2025_usd"], "target_gmv_usd": row["target_gmv_usd"]})
    pk_members, pk_missing = [], []
    for team, names in PK_TEAMS.items():
        for index, name in enumerate(names):
            account = resolve(name)
            if account is None:
                pk_missing.append(name)
            else:
                pk_members.append({"ark_user_id": account["ark_user_id"], "team": team, "is_captain": index == 0})
    common = {"visibility": "activity"}
    return {"items": [
        {"ready": not annual_missing, "missing": annual_missing, "source": source["source"], "payload": {
            **common, "name": "2026年度新签复购奖", "start_date": "2026-01-01", "end_date": "2026-12-31",
            "target_deadline": "2026-10-18T23:59:59", "award_kind": "annual_repurchase", "members": annual_members,
            "award_rules": {"baselines": annual_bases, "push_start_date": "2026-10-19", "source_sha256": source["source_sha256"]}}},
        {"ready": not pk_missing, "missing": pk_missing, "source": "亮哥确认的两队名单与比赛规则", "payload": {
            **common, "name": "11月份新签PK奖", "start_date": "2026-11-01", "end_date": "2026-11-30",
            "target_deadline": "2026-10-31T23:59:59", "award_kind": "new_sign_pk", "members": pk_members,
            "award_rules": {"baselines": [], "push_start_date": "2026-11-01", "source_sha256": ""}}},
    ]}
