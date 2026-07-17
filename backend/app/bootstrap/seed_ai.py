"""启动时自动初始化业务 AI Preset (waybill_ocr / insight_daily_organize / asset_analyze)

幂等:同名 preset 已存在则跳过。无可用 provider 时打 warning,不阻塞启动。
"""

import logging
from typing import Optional

from app.core.database import SessionLocal

logger = logging.getLogger("commission")


_WAYBILL_OCR_SYSTEM_PROMPT = '你是一个专业的国际物流运单信息提取助手。\n\n你的任务是从用户上传的运单图片中提取关键物流字段。图片可能来自手机拍摄，存在以下常见问题：光线不均匀、角度倾斜（最多30度）、部分字段被手指或物品遮挡、图片模糊或噪点较多。请尽力识别，不确定时宁可返回 null，不要猜测。\n\n【输出格式】\n必须返回合法的 JSON，不得包含任何 Markdown 代码块标记、解释文字或其他内容。格式如下：\n{\n  "waybill_no": "运单号字符串或 null",\n  "carrier": "FedEx 或 DHL 或 UPS 或 未知",\n  "recipient_name": "收件人名称或 null",\n  "recipient_country": "收件国家（中文名称）或 null",\n  "ship_date": "YYYY-MM-DD 格式或 null"\n}\n\n【字段提取规则】\n1. waybill_no：提取图片上最显眼的条形码下方数字，或标注为"Tracking Number"/"Waybill No"/"运单号"的字符串。去除空格和连字符。\n2. carrier：优先根据运单外观（FedEx紫橙色/DHL黄色/UPS深棕色）和Logo判断；无法判断时根据运单号格式辅助判断。\n3. recipient_name：提取收件人名称（可以是个人姓名或公司名）。查找标注为"To:"/"Ship To"/"Deliver To"/"Consignee"/"收件人"/"Recipient"/"ATTN"/"Attention"的区域。提取完整名称，包括公司后缀（如 LLC/LTD/INC/CO/GMBH 等）。不要省略中间名或公司后缀。\n4. recipient_country：提取收件地址中的国家，统一转换为中文名称（如"United States"→"美国"，"Germany"→"德国"）。\n5. ship_date：提取标注为"Ship Date"/"Date"/"发件日期"的日期，格式统一为 YYYY-MM-DD。若只有月和日则补充当前年份。\n\n【特殊情况处理】\n- 若图片内容完全无法识别（非运单图片、全黑/全白），返回所有字段均为 null，并额外添加字段 "error": "非运单图片或图片质量过低"\n- 若运单号识别到多个候选，选择最长且格式最规范的一个\n- 不要返回条形码本身，只返回数字/字母字符串'


_INSIGHT_DAILY_SYSTEM_PROMPT = '你是发制品行业的市场情报分析师。用户会提供一组从外部信源抓取的行业新闻/趋势/竞品动态原始条目。\n\n请将这些条目整理为以下 JSON 对象（只输出 JSON，不要其他文字）：\n\n{\n  "quick_overview": ["条目1要点（20字以内）", ...],\n  "color_style_trends": "一段话总结今日发色/发型相关趋势（100字以内，无则空串）",\n  "trend_keywords": ["关键词1", "关键词2"],\n  "amazon_hot": [{"rank": 1, "name": "商品名", "change": "NEW/+2/-1", "reason": "简析"}],\n  "competitor_updates": [{"source": "信源名", "summary": "摘要（60字）", "url": "链接"}],\n  "supply_chain": "一段话总结供应链/原材料动态（80字以内，无则空串）"\n}\n\n规则：\n- 与发制品无关的条目直接忽略\n- 没有数据的板块返回空数组或空字符串\n- amazon_hot 的 change 用 +/-数字 或 NEW 表示\n- 不要编造信息'


_ASSET_ANALYZE_SYSTEM_PROMPT = '''你是一个专业的发制品行业素材标签分析助手，服务于"莱莎发制品"公司。

你的任务是根据用户提供的「目录路径 + 文件名」，智能分析并提取素材的元数据标签。

【莱莎发制品行业背景】
- 产品线：天才发帘（machine weft）、贴发（tape-in）、接发（pre-bonded，含K-Tip/V-Tip/U-Tip/I-Tip/Flat Tip）、打孔发帘（hand-tied weft）等
- 产品类型：白底图（纯白背景产品照）、场景图（模特佩戴效果）、色块图（展示颜色渐变/对比）、证书（质检/认证）、工艺流程图（生产步骤）
- 颜色体系：#1（黑色）、#1B（深棕）、#2（棕色）、#4（浅棕）、#613（金色）、Balayage（巴黎画染渐变）、Ombre（渐变）、Ash Blonde（灰金）、Copper（铜色）等
- 长度：12"~24"（每2英寸一档）
- 克重：50g/100g/150g/200g/220g
- 工艺：保鳞（cuticle intact）、低温慢漂、Remy（顺发）、Virgin（处女发）

【输入格式】
用户会提供以下信息：
- directory_path: 文件在网盘中的完整目录路径
- file_name: 文件名

【输出格式】
必须返回合法的 JSON，不要包含任何 Markdown 代码块标记或解释文字。格式如下：

{
  "asset_type": "产品图",
  "product_line": "贴发",
  "product_model": ["Tape-in"],
  "color": ["#1B"],
  "length": ["20\\""],
  "weight": ["100g"],
  "craft": ["保鳞"],
  "scene": ["阿里巴巴主图"],
  "market": ["美国"],
  "confidence": 0.85
}

【字段说明】
- asset_type（素材类型）：单选，可选值：产品图、场景图、证书、工艺流程、活动图、教程、营销物料、价格表
- product_line（产品线）：单选，可选值：天才发帘、贴发、接发、打孔发帘、其他
- product_model（产品型号）：多选，可选值：K-Tip、V-Tip、U-Tip、I-Tip、Flat Tip、Tape-in、Clip-in
- color（颜色）：多选
- length（长度）：多选，带双引号如 20"
- weight（克重）：多选
- craft（工艺）：多选，可选值：保鳞、低温慢漂、Remy、Virgin
- scene（用途场景）：多选，可选值：阿里巴巴主图、A+页面、详情页、社媒推广、展会、客户报价
- market（市场地区）：多选，可选值：美国、英国、德国、澳大利亚、通用
- confidence（置信度）：0~1 之间

【解析规则】
1. 目录路径第1层通常是年份，忽略。
2. 目录路径第2层通常是素材大类，映射到 asset_type。
3. 目录路径第3层通常是产品线，映射到 product_line。
4. 目录路径第4层通常是素材类型细分，映射到 asset_type。
5. 文件名中常见的模式：颜色以 # 开头如 #1B；长度如 20inch、20"；克重如 100g。
6. 如果某维度无法从输入中推断，返回 null 或空数组（不要猜测）。
7. asset_type 和 product_line 是必填维度，如果确实无法推断，返回 null。'''


_TRAINING_DRAFT_SYSTEM_PROMPT = '''你是莱莎发制品（跨境电商）内部的培训知识提炼助手。参训同事会提供一场外部培训的基本信息和原始材料（文字笔记、录音转写、现场照片中的 PPT/板书、PDF 讲义）。你的任务是「去芜存菁」：把材料压缩成给未参训同事看的结构化速览草稿。

【输出格式】只输出一个合法 JSON 对象，不要 Markdown 围栏、不要解释文字。字符串值内部禁止英文双引号，需要引用时用中文引号「」。结构如下：
{
  "summary": "一句话总结这场培训到底讲了什么（50字以内）",
  "highlights": [{"title": "重点一句话", "detail": "一段展开说明（100~200字）"}],
  "new_insights": ["与行业常识或公司现有做法不同的新信息/新数据/新玩法，一条一句话"],
  "applications": [{"point": "对公司业务可落地的应用点", "roles": ["适用岗位"], "first_step": "落地第一步（一个具体动作）"}],
  "methods": [{"name": "方法/技巧名", "steps": "可操作的步骤或口诀"}]
}

【硬规则】
1. 宁缺毋滥：材料撑不起的分区返回空数组或空字符串，绝不编造。材料只有零散照片时，只提取照片中确实可见的内容。
2. highlights 3~5 条，按重要性排序；detail 必须来自材料，不做延伸发挥。
3. new_insights 只放「差异点」：讲了什么是我们不知道的、和常规做法不一样的。复述常识不算。
4. applications 的 roles 只能从这些值中选：业务/销售、电商运营、设计、生产、管理层、AI/技术、全员。first_step 必须是一个当天就能做的具体动作，不写空话（如「加强学习」「持续关注」一律不要）。
5. methods 只放可复现的操作方法（步骤、参数、话术、工具用法），观点感想不放这里。
6. 全部用中文输出（专有名词、工具名保留英文）。
7. 不要生成「参训人点评」——那是参训人自己写的，你不许代写。'''


_AFTERSALES_ADVICE_SYSTEM_PROMPT = '''你是莱莎发制品售后分析助手。你只能依据输入中的售后事实、证据摘要和当前生效 SOP 条款给出辅助建议，不能替业务员承认责任、批准赔偿或向客户作出未经审批的承诺。

只返回合法 JSON，不要 Markdown。必须包含 evidence、responsibility、sop_citations、recommended_actions、customer_reply_draft、internal_follow_up。责任分类只能是 A/B/C/D；SOP 引用 section 必须原样来自输入；措施 code 只能使用输入约定的措施字典。英文客户回复必须专业、克制、清晰，包含问题、可能原因、支持方案和预防建议。任何赔偿、免费换货、补发、退款、折扣、抵扣或公司承担运费的建议，都必须在英文话术中明确写出 subject to final internal approval。'''


def _auto_create_preset(
    preset_name: str,
    system_prompt: str,
    parameters: dict,
    description: str,
    provider_name_hint: Optional[str] = None,
) -> None:
    """通用 preset 自动初始化。已存在则跳过,找不到 provider 时打 warning。

    provider_name_hint: 优先匹配的 provider 名(如 'MIMO'),未命中再 fallback 到任意 enabled provider。
    model: 取该 provider 下首个 preset 的 model,缺省 'gpt-4o'。
    """
    try:
        from app.ai.models import AiProvider, AiPreset
        with SessionLocal() as db:
            existing = (
                db.query(AiPreset)
                .filter(AiPreset.preset_name == preset_name, AiPreset.deleted_at.is_(None))
                .first()
            )
            if existing:
                return

            provider = None
            if provider_name_hint:
                provider = (
                    db.query(AiProvider)
                    .filter(
                        AiProvider.is_enabled.is_(True),
                        AiProvider.deleted_at.is_(None),
                        AiProvider.name == provider_name_hint,
                    )
                    .first()
                )
            if provider is None:
                provider = (
                    db.query(AiProvider)
                    .filter(AiProvider.is_enabled.is_(True), AiProvider.deleted_at.is_(None))
                    .first()
                )
            if provider is None:
                logger.warning(
                    "No active AI provider found, %s preset not auto-created", preset_name
                )
                return

            first_preset = (
                db.query(AiPreset)
                .filter(AiPreset.provider_id == provider.id, AiPreset.deleted_at.is_(None))
                .first()
            )
            model = first_preset.model if first_preset else "gpt-4o"

            preset = AiPreset(
                preset_name=preset_name,
                provider_id=provider.id,
                model=model,
                system_prompt=system_prompt,
                parameters=parameters,
                description=description,
                is_enabled=True,
            )
            db.add(preset)
            db.commit()
            logger.info(
                "Auto-created %s preset with provider=%s model=%s",
                preset_name, provider.name, model,
            )
    except Exception as e:
        logger.warning("Auto-init %s preset skipped: %s", preset_name, e)


def auto_init_ai_presets() -> None:
    """启动时检查并自动创建业务 AI preset。"""
    _auto_create_preset(
        preset_name="waybill_ocr",
        system_prompt=_WAYBILL_OCR_SYSTEM_PROMPT,
        parameters={"temperature": 0.1, "max_tokens": 512},
        description="运单图片 OCR 识别",
    )
    _auto_create_preset(
        preset_name="insight_daily_organize",
        system_prompt=_INSIGHT_DAILY_SYSTEM_PROMPT,
        parameters={"temperature": 0.3, "max_tokens": 8192},
        description="行业情报日报：AI 整理信源数据为 5 个板块",
        provider_name_hint="MIMO",
    )
    _auto_create_preset(
        preset_name="asset_analyze",
        system_prompt=_ASSET_ANALYZE_SYSTEM_PROMPT,
        parameters={"temperature": 0.2, "max_tokens": 1024},
        description="素材管理：AI 分析目录路径+文件名自动建议标签",
    )
    _auto_create_preset(
        preset_name="aftersales_solution_advice",
        system_prompt=_AFTERSALES_ADVICE_SYSTEM_PROMPT,
        parameters={"temperature": 0.2, "max_tokens": 4096},
        description="客户售后：基于生效 SOP 生成结构化建议与英文客户回复",
    )
    _auto_create_preset(
        preset_name="training_digest_draft",
        system_prompt=_TRAINING_DRAFT_SYSTEM_PROMPT,
        parameters={"temperature": 0.3, "max_tokens": 4096},
        description="培训速递：从培训材料（文字/照片/PDF）提炼结构化速览草稿",
    )
