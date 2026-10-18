"""Deterministic HTML overlays on the supplied, unchanged 1199 x 1312 artwork."""
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.battle_report.award_statistics import annual_order_key

WIDTH, HEIGHT = 1199, 1312
CAPACITY = 17

# Absolute data blanks measured from the source artwork, in native pixels.
PODIUM = {
    1: {"name": (520, 402, 157, 31), "values": [(597,448,81,20),(597,480,82,21),(597,514,82,21),(597,548,82,21)], "progress": (586,582,108,24), "tone": "gold"},
    2: {"name": (321, 425, 147, 28), "values": [(390,463,78,21),(390,494,77,20),(389,527,77,20),(388,560,77,21)], "progress": (375,594,105,25), "tone": "silver"},
    3: {"name": (728, 425, 144, 29), "values": [(800,464,75,21),(801,495,76,20),(802,528,77,19),(804,561,76,20)], "progress": (793,594,109,25), "tone": "bronze"},
    4: {"name": (117, 464, 150, 28), "values": [(184,495,81,22),(181,525,81,22),(179,557,80,21),(177,588,79,20)], "progress": (160,619,107,23), "tone": "cream"},
    5: {"name": (925, 465, 147, 28), "values": [(999,499,77,21),(1003,528,78,21),(1006,559,80,20),(1009,589,81,21)], "progress": (998,618,110,24), "tone": "cream"},
}
TABLE_CENTERS = [791.5, 828, 864, 901, 936.5, 973, 1009, 1046, 1082, 1119, 1154.5, 1191]
TABLE_FIELDS = [(176,125),(328,82),(437,105),(570,106),(707,169)]


def box_style(box):
    x, y, width, height = box
    return f"left:{x}px;top:{y}px;width:{width}px;height:{height}px"


def values(row, visible):
    if not visible or row is None:
        return ["待填", "—", "—", "—", "—"]
    amount = Decimal(row["repeat_amount"]).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    amount_text = format(amount, ",.0f" if amount == amount.to_integral_value() else ",.2f")
    return [row["user_name"], format(Decimal(row["score"]).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), ".2f"),
            str(row["new_count"]), str(row["repeat_count"]),
            amount_text]


def progress(row, visible):
    if not visible or row is None or not row["gmv_complete"]:
        return {"fill": "0", "label": "—"}
    exact = Decimal(row["gmv"]) / Decimal(row["target"]) * 100
    # Truncation cannot turn 99.99% into a false displayed 100%.
    label = format(exact.quantize(Decimal("0.1"), rounding=ROUND_DOWN), "f") + "%"
    return {"fill": format(min(Decimal(100), max(Decimal(0), exact)), "f"), "label": label}


def render_html(snapshot, assets, background):
    people = sorted(snapshot["people"], key=annual_order_key)
    if len(people) > CAPACITY:
        raise RuntimeError("当前年度底图仅支持17人，请先调整模板席位")
    demo = snapshot.get("data_mode") == "demo"
    visible = demo or snapshot["data_complete"]
    podium = []
    for rank, layout in PODIUM.items():
        row = people[rank-1] if rank <= len(people) else None
        texts = values(row, visible)
        fields = [{"style": box_style(layout["name"]), "text": texts[0], "kind": "name"}]
        fields += [{"style": box_style(box), "text": text, "kind": "money" if index == 3 else "number"}
                   for index, (box, text) in enumerate(zip(layout["values"], texts[1:]))]
        podium.append({"rank": rank, "fields": fields, "style": box_style(layout["progress"]),
                       "tone": layout["tone"], **progress(row, visible)})
    table = []
    for index, center in enumerate(TABLE_CENTERS):
        row = people[index+5] if index+5 < len(people) else None
        texts = values(row, visible)
        fields = [{"style": box_style((x,center-12,width,24)), "text": value,
                   "kind": "name" if column == 0 else "number"}
                  for column, ((x,width),value) in enumerate(zip(TABLE_FIELDS,texts))]
        table.append({"rank": index+6, "fields": fields,
                      "style": box_style((901,center-14,211,28)), **progress(row,visible)})
    env = Environment(loader=FileSystemLoader(assets), autoescape=select_autoescape(["html"]))
    qualified_count = sum(row["qualified"] for row in people)
    group_label = ""
    if visible:
        groups = []
        if qualified_count:
            groups.append(f"已达标：01—{qualified_count:02d}")
        if qualified_count < len(people):
            groups.append(f"未达标：{qualified_count+1:02d}—{len(people):02d}")
        group_label = "；".join(groups)
    return env.get_template("annual_ranking.html").render(
        css=(assets/"annual_ranking.css").read_text(encoding="utf-8"), background=background,
        podium=podium, table=table, demo=demo, visible=visible, group_label=group_label,
        calculated_at=snapshot["calculated_at"].replace("T"," ")[:19],
        source_synced_at=(snapshot.get("source_synced_at") or "未知").replace("T"," ")[:19],
        issue_count=len(snapshot.get("issues",[])), cutoff_tie=snapshot.get("cutoff_tie",False))
