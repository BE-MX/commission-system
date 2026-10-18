"""Name-matched overlays on the two approved, unchanged PK artworks."""
from decimal import Decimal, ROUND_DOWN

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.battle_report.award_presets import ALIASES, PK_TEAMS

WIDTH, HEIGHT = 1672, 941
# Left to right in the supplied portraits; captains remain at the center.
NAMES = {team: [names[1], names[2], names[0], names[3], names[4]]
         for team, names in PK_TEAMS.items()}
LAYOUT = {
    "one": {
        "一组": [(88,435,109,27,139,466,55,46),(236,435,123,27,291,466,60,46),
                 (400,415,156,44,446,466,107,46),(594,436,112,26,642,467,62,45),
                 (752,435,105,28,804,467,58,45)],
        "二组": [(970,451,89,23,1005,479,54,39),(1095,451,84,23,1124,478,54,40),
                 (1209,437,121,32,1244,478,79,39),(1366,452,89,23,1396,479,55,38),
                 (1482,452,89,23,1513,479,52,38)],
    },
    "two": {
        "一组": [(101,430,85,24,129,455,54,45),(222,430,90,24,252,455,56,45),
                 (352,415,120,31,396,454,85,46),(515,431,78,24,540,456,57,44),
                 (640,430,80,24,669,455,55,44)],
        "二组": [(842,452,102,28,883,485,59,48),(990,453,106,27,1037,486,59,47),
                 (1135,438,143,36,1181,479,105,49),(1332,453,113,27,1381,486,64,47),
                 (1481,451,105,28,1529,485,56,47)],
    },
}


def display_name(name):
    return next((short for short, full in ALIASES.items() if name == full), name)


def matches_roster(snapshot):
    """Other custom PK rosters keep the general layout, never mismatched portraits."""
    teams = snapshot.get("teams", [])
    if len(teams) != 2 or {t["team"] for t in teams} != set(PK_TEAMS):
        return False
    for team in teams:
        people = team["people"]
        if len(people) != 5 or {display_name(p["user_name"]) for p in people} != set(PK_TEAMS[team["team"]]):
            return False
        captains = [display_name(p["user_name"]) for p in people if p["is_captain"]]
        if captains != [PK_TEAMS[team["team"]][0]]:
            return False
    return True


def box(values):
    x, y, width, height = values
    return f"left:{x}px;top:{y}px;width:{width}px;height:{height}px"


def currency(value):
    return format(Decimal(value), ",.0f")


def render_html(snapshot, assets, background_one, background_two):
    teams = {t["team"]: t for t in snapshot["teams"]}
    visible = snapshot["data_complete"]
    demo = snapshot.get("data_mode") == "demo"
    leaders = [t for t in teams.values() if t["leading"]] if visible and snapshot["period_state"] != "upcoming" else []
    if len(leaders) > 1:
        raise RuntimeError("PK领先状态冲突，请核对后生成")
    lead = leaders[0] if leaders else None
    mode = "one" if lead and lead["team"] == "一组" else "two" if lead else "neutral"
    people, totals = [], []
    for team_name in PK_TEAMS:
        team = teams[team_name]
        layout = LAYOUT["two" if mode == "two" or mode == "neutral" and team_name == "一组" else "one"][team_name]
        by_name = {display_name(p["user_name"]): p for p in team["people"]}
        for name, positions in zip(NAMES[team_name], layout):
            person = by_name[name]
            people.append(dict(name=name, name_style=box(positions[:4]), count_style=box(positions[4:]),
                               captain=person["is_captain"], tone="pink" if team_name == "一组" else "blue",
                               count=person["new_count"] if visible else "—"))
        percent = Decimal(team["new_count"]) * 100 / team["target"]
        totals.append(dict(team=team_name, count=team["new_count"] if visible else "—",
                           style=box((77,722,345,94) if team_name == "一组" else (1315,727,282,80)),
                           progress=f"目标 {team['target']} · 完成 {percent.quantize(Decimal('0.1'),rounding=ROUND_DOWN)}%" if visible else "正式数据待填",
                           fill=str(min(Decimal(100), percent)) if visible else "0",
                           tone="pink" if team_name == "一组" else "blue"))
    heading, amount, detail = "双方持平 · 暂无领先", "PK胜利奖待决出", "三项指标均相同时，胜利奖与队长询盘待裁定"
    if not visible:
        heading, amount, detail = "数据待核对", "正式数据待填", "目标奖金、PK奖金及队长询盘均待核对"
    elif snapshot["period_state"] == "upcoming":
        heading, amount, detail = "11月1日开赛 · 暂无领先", "活动未开始", "每队目标30个新签 · 双方达标后再评PK胜利奖"
    elif lead:
        decided = snapshot["period_state"] == "ended"
        lead_label = "胜出" if decided and snapshot["pk_eligible"] else "领先" if decided else "暂领先"
        heading = f"{lead['team']}{lead_label} · {'计算结果' if decided else '奖励预测'}"
        total_bonus = Decimal(lead["target_bonus"]) + Decimal(lead["pk_bonus"])
        amount = f"团队奖金 ¥{currency(total_bonus)}" if total_bonus else "未获目标奖" if decided else "目标奖金待达标"
        if snapshot["pk_eligible"]:
            detail = f"目标奖 ¥{currency(lead['target_bonus'])} + PK奖 ¥{currency(lead['pk_bonus'])} · 队长官网询盘 {lead['inquiries']}个"
        else:
            detail = "PK胜利奖不予发放 · 队长询盘不予发放" if decided else "双方达标后再评PK胜利奖 · 队长询盘待评"
    elif not snapshot["pk_eligible"]:
        decided = snapshot["period_state"] == "ended"
        amount = "PK胜利奖不予发放" if decided else "PK胜利奖待双方达标"
        detail = "双方目标未同时达成 · 队长询盘不予发放" if decided else "双方达标后再评PK胜利奖 · 队长询盘待评"
    env = Environment(loader=FileSystemLoader(assets), autoescape=select_autoescape(["html"]))
    return env.get_template("pk_ranking.html").render(
        css=(assets/"pk_ranking.css").read_text(encoding="utf-8"), mode=mode,
        background_one=background_one, background_two=background_two,
        people=people, totals=totals, demo=demo, visible=visible,
        heading=heading, amount=amount, detail=detail,
        calculated_at=snapshot["calculated_at"].replace("T"," ")[:19],
        source_synced_at=(snapshot.get("source_synced_at") or "活动未开始 / 未知").replace("T"," ")[:19],
        team_rewards="；".join(f"{t['team']}目标奖 ¥{currency(t['target_bonus'])}" for t in teams.values()) if visible else "奖励待核对",
        ended=snapshot["period_state"] == "ended")
