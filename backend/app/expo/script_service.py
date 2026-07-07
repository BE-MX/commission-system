"""话术卡库 — 内贸营销策略 v2 / 直播话术 v4 的结构化落点。

分工：AiPreset 管"怎么生成"，本库管"用什么素材生成"。
禁用词校验也在这里（机器规则兜底，不赌 AI 自觉）。
"""

from sqlalchemy.orm import Session

from app.expo.models import ExpoScript

# 品牌话术禁用词（直播话术 v4 关键词矩阵"禁用"行）——拉低定位，任何生成文案不得出现
FORBIDDEN_WORDS = ["便宜", "划算", "性价比", "打折", "薅羊毛"]

# 证据库：AI 生成话术只允许引用这里的事实，不许自编数据
EVIDENCE_POINTS = {
    "baolin": "保鳞原生辫发，不烫不染不酸洗，毛鳞片完整",
    "sgs": "SGS 安全认证，无甲醛无重金属，网料医用级亲肤",
    "material": "22 岁以下原生辫发，5 道筛选（年龄/形态/垂感/弹性/色泽）",
    "brand": "1992 年创立，33 年专注，外贸 164 个国家、3000+ 家沙龙",
    "lifespan": "正常保养佩戴寿命 12-18 个月",
    "daily_cost": "按佩戴寿命折算每天不到 7 块钱",
    "account": "一顶莱莎（3200）寿命≈两顶普通品牌（2800×2=5600）",
    "time_saving": "每天省 30-60 分钟打理时间，一年约 200 小时",
    "return_policy": "7 天无理由退换，运费商家承担",
}


def check_forbidden(text: str) -> list[str]:
    """返回命中的禁用词列表，空列表即通过。"""
    return [w for w in FORBIDDEN_WORDS if w in (text or "")]


def list_scripts(db: Session, script_type: str | None = None, only_active: bool = True) -> list[ExpoScript]:
    q = db.query(ExpoScript)
    if script_type:
        q = q.filter(ExpoScript.script_type == script_type)
    if only_active:
        q = q.filter(ExpoScript.is_active == 1)
    return q.order_by(ExpoScript.script_type, ExpoScript.id).all()


def pick_scripts(db: Session, audience_tags: list[str]) -> dict:
    """按客户特征标签检索话术素材，供 AI 话术生成拼装上下文。

    返回 {opener_emotional, closer_rational, faqs} 三组，各取标签命中最多的若干条。
    """
    scripts = list_scripts(db)

    def hits(script: ExpoScript) -> int:
        tags = script.audience_tags or []
        return sum(1 for t in tags if t in audience_tags) or (1 if "通用" in tags else 0)

    def top(script_type: str, track: str | None, n: int) -> list[ExpoScript]:
        pool = [s for s in scripts if s.script_type == script_type and (track is None or s.track == track)]
        return sorted(pool, key=hits, reverse=True)[:n]

    return {
        "openers": top("opener", "emotional", 2),
        "closers": top("closer", None, 2),
        "faqs": top("faq", None, 2),
    }


# --- 种子数据（source_version=v4，导入后市场部在后台维护） ---

_SEED = [
    # 开场 · 情感线
    dict(script_type="opener", track="emotional", title="气质变化钩子",
         audience_tags=["通用"],
         content="明明化了妆、穿得也不差，但镜子里的自己就是差点意思？差在头发。头发对气质的影响占一半以上——从发廊做完头发出来的那种状态，莱莎让它天天在线。",
         evidence_points=["lifespan"]),
    dict(script_type="opener", track="identity", title="身份认同钩子",
         audience_tags=["职业女性", "高消费信号"],
         content="买莱莎的客户——做老师的、做管理的、开公司的——她们买的不是假发，是每天出门时那种稳稳的精致感。有些东西，花了钱就不用再花时间。",
         evidence_points=["time_saving"]),
    dict(script_type="opener", track="rational", title="健康关切钩子",
         audience_tags=["敏感肌", "长期佩戴"],
         content="假发是贴着头皮 8-12 小时的东西。吃的看配料表、护肤看成分——头上戴的，看过它的成分吗？有没有甲醛、重金属、强酸处理？您的头皮最先知道。",
         evidence_points=["sgs", "baolin"]),
    # 演示引导（短发五演示，供销售现场配合实物）
    dict(script_type="demo", track="rational", title="光泽度对比",
         audience_tags=["短发"],
         content="两顶都用了半年：一顶打光是暗的、毛糙的；莱莎这顶光泽柔和有层次，跟刚做完护理一样。好的发质自带光泽，不靠产品维持——这是原料的差距。",
         evidence_points=["baolin"]),
    dict(script_type="demo", track="rational", title="手感对比",
         audience_tags=["短发"],
         content="您自己摸一下——一顶手指划过是干涩有阻力的；莱莎这顶一划就过去，像摸真丝。好的假发不是看出来的，是摸出来的，手感骗不了人。",
         evidence_points=["baolin"]),
    dict(script_type="demo", track="emotional", title="佩戴气质对比",
         audience_tags=["通用"],
         content="同一个人换一顶假发，整个气质就出来了——不是变好看了多少，是变精致了。假发的作用不是遮掩，是提升整体状态。",
         evidence_points=[]),
    dict(script_type="demo", track="rational", title="发际线与头旋细节",
         audience_tags=["短发", "挑剔细节"],
         content="短发露出的面积大，发际线、鬓角、头旋全暴露，工艺要求比长发高得多。您看——每根都是手工单独钩的，方向不规则、有碎发，头旋有疏密变化。短发最值钱的是这些'不完美的真实细节'。",
         evidence_points=["material"]),
    dict(script_type="demo", track="rational", title="亲肤网料展示",
         audience_tags=["敏感肌"],
         content="短发跟头皮贴合面积更大，网料亲肤性特别重要。翻开看——纤度细、透光，无甲醛无重金属认证。戴一上午，不红不痒没有压痕。",
         evidence_points=["sgs"]),
    # 逼单
    dict(script_type="closer", track="identity", title="身份定位法",
         audience_tags=["高消费信号", "心动至臻"],
         content="护肤品您用好的，衣服穿好的——每天贴着头皮 8 小时的东西，值不值得用选护肤品的标准来对待？对自己好，是每个细节都不将就。",
         evidence_points=["return_policy"]),
    dict(script_type="closer", track="rational", title="状态投资法",
         audience_tags=["职业女性", "打理时间敏感"],
         content="每天在头发上花 30-60 分钟，一年就是 200 多个小时。一顶莱莎=每天省 30 分钟+出门就是做好头发的状态。买的不是假发，是每天多出来的半小时和出门的底气。",
         evidence_points=["time_saving", "return_policy"]),
    dict(script_type="closer", track="rational", title="一顶顶两顶算账法",
         audience_tags=["犹豫价格", "长期佩戴"],
         content="普通品牌佩戴 6-9 个月开始衰减，两顶 5600；莱莎一顶 12-18 个月。表面多花几百，实际一顶顶两顶。您不是在为'最贵'买单，是在为'最久'买单。",
         evidence_points=["account", "lifespan"]),
    dict(script_type="closer", track="rational", title="健康投资法",
         audience_tags=["敏感肌", "长期佩戴"],
         content="头皮是全身最薄的皮肤之一。已经决定长期戴的话，请选健康的——SGS 认证、无甲醛无重金属、医用级亲肤网料。这不是花钱，是省了未来的麻烦。",
         evidence_points=["sgs", "return_policy"]),
    # 弹幕/异议应对
    dict(script_type="faq", track="rational", title="能用多久",
         audience_tags=["犹豫价格"],
         content="正常保养 12-18 个月，折算每天不到 7 块钱——一杯咖啡的钱，换一整天气质在线。",
         evidence_points=["lifespan", "daily_cost"]),
    dict(script_type="faq", track="rational", title="为什么比别人贵",
         audience_tags=["犹豫价格"],
         content="贵在两个地方：一是原料不酸洗（健康），二是时间（半年后还好看）。今天看不出来，半年后就知道了。",
         evidence_points=["baolin"]),
    dict(script_type="faq", track="rational", title="短发怎么选",
         audience_tags=["短发"],
         content="短发看脸型——圆脸选有碎刘海的显脸小，方脸选鬓角长一点的修饰线条。",
         evidence_points=[]),
    dict(script_type="faq", track="rational", title="敏感肌能戴吗",
         audience_tags=["敏感肌"],
         content="敏感肌反而更要选好的——网料无甲醛无重金属、透气。7 天退换，戴了不舒服退给我们。",
         evidence_points=["sgs", "return_policy"]),
    dict(script_type="faq", track="emotional", title="戴短发会不会硬朗",
         audience_tags=["短发"],
         content="看款式——我们的短发都设计过弧度和层次，柔化线条显温柔，不是'寸头'。",
         evidence_points=[]),
    dict(script_type="faq", track="emotional", title="气质说不准",
         audience_tags=["通用"],
         content="气质是综合的，但发型对了，整个人就对了。您试一下就知道，不合适可以退。",
         evidence_points=["return_policy"]),
    # 品牌信任
    dict(script_type="opener", track="rational", title="品牌故事（健康+匠心）",
         audience_tags=["通用", "首次接触"],
         content="莱莎 1992 年开始做假发，33 年，外贸做到 164 个国家、3000 多家沙龙。标准是 22 岁以下原生辫发、5 道筛选、不烫不染不酸洗——贴着头皮的东西，必须安全。",
         evidence_points=["brand", "material"]),
]


def seed_default_scripts(db: Session) -> int:
    """幂等导入种子话术卡（按 title 查重），返回新增条数。"""
    existing = {s.title for s in db.query(ExpoScript.title).all()}
    created = 0
    for item in _SEED:
        if item["title"] in existing:
            continue
        db.add(ExpoScript(**item))
        created += 1
    db.commit()
    return created
