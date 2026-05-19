"""素材管理 — AI 打标签服务

根据目录路径 + 文件名，调用 AI 分析建议标签值。
"""

from __future__ import annotations

import json
import re
from typing import Optional

from sqlalchemy.orm import Session

from app.ai.call_service import chat
from app.asset.models import TagDimension, TagValue


_AI_ANALYZE_SYSTEM_PROMPT = '''你是一个专业的发制品行业素材标签分析助手，服务于"莱莎发制品"公司。

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
- directory_path: 文件在网盘中的完整目录路径，如 "2024/产品图片/贴发/白底图/"
- file_name: 文件名，如 "#1B_20inch.jpg"

【输出格式】
必须返回合法的 JSON，不要包含任何 Markdown 代码块标记或解释文字。格式如下：

{
  "asset_type": "产品图",
  "product_line": "贴发",
  "product_model": ["Tape-in"],
  "color": ["#1B"],
  "length": ["20\""],
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
- confidence（置信度）：0~1 之间，表示你对这次分析结果的确信程度

【解析规则】
1. 目录路径第1层通常是年份，忽略。
2. 目录路径第2层通常是素材大类（产品图片/产品视频/活动图片/设计图片），映射到 asset_type。
3. 目录路径第3层通常是产品线（贴发/天才发帘/接发），映射到 product_line。
4. 目录路径第4层通常是素材类型细分（白底图/场景图/证书/工艺流程），映射到 asset_type 的细分值。
5. 文件名中常见的模式：
   - 颜色：以 # 开头的如 #1B，或英文颜色如 Copper、Balayage
   - 长度/尺寸：如 20inch、20"、60cm
   - 克重：如 100g、50g
   - 版本：如 v2、_v3（不要包含在标签中）
6. 如果某维度无法从输入中推断，返回 null 或空数组（不要猜测）。
7. asset_type 和 product_line 是必填维度，如果确实无法推断，返回 null。

【示例】
输入：directory_path="2024/产品图片/贴发/白底图/", file_name="#1B_20inch_100g.jpg"
输出：{"asset_type":"产品图","product_line":"贴发","product_model":["Tape-in"],"color":["#1B"],"length":["20\""],"weight":["100g"],"craft":null,"scene":["阿里巴巴主图"],"market":["通用"],"confidence":0.9}

输入：directory_path="2025/活动图片/天才发帘/", file_name="展会现场_美国市场.jpg"
输出：{"asset_type":"活动图","product_line":"天才发帘","product_model":null,"color":null,"length":null,"weight":null,"craft":null,"scene":["展会"],"market":["美国"],"confidence":0.75}'''


# 维度名 → 数据库字段名映射
_DIMENSION_MAP = {
    "asset_type": "素材类型",
    "product_line": "产品线",
    "product_model": "产品型号",
    "color": "颜色",
    "length": "长度",
    "weight": "克重",
    "craft": "工艺",
    "scene": "用途场景",
    "market": "市场地区",
}


def _clean_ai_response(content: str) -> str:
    """去除可能的 Markdown 代码块标记。"""
    content = content.strip()
    if content.startswith("```json"):
        content = content[7:]
    elif content.startswith("```"):
        content = content[3:]
    if content.endswith("```"):
        content = content[:-3]
    return content.strip()


def _find_tag_value_ids(db: Session, dim_name: str, values: list[str]) -> list[int]:
    """根据维度名和标签值，查找对应的 tag_value_ids。"""
    dim = db.query(TagDimension).filter(TagDimension.name == dim_name).first()
    if not dim:
        return []

    result = []
    for val in values:
        val_lower = val.lower().strip()
        # 先精确匹配
        tv = (
            db.query(TagValue)
            .filter(TagValue.dimension_id == dim.id, TagValue.value == val)
            .first()
        )
        if tv:
            result.append(tv.id)
            continue
        # 模糊匹配（忽略大小写，去除空格）
        all_values = db.query(TagValue).filter(TagValue.dimension_id == dim.id).all()
        for candidate in all_values:
            if candidate.value.lower().strip().replace(" ", "") == val_lower.replace(" ", ""):
                result.append(candidate.id)
                break
    return result


def analyze_asset_tags(
    db: Session,
    file_name: str,
    directory_path: Optional[str] = None,
) -> dict:
    """调用 AI 分析素材标签。返回建议标签列表。

    Returns:
        {
            "confidence": float,
            "suggestions": [
                {"dimension_id": int, "dimension_name": str, "dimension_label": str,
                 "values": [{"tag_value_id": int, "value": str}], "is_ai_suggested": true}
            ]
        }
    """
    prompt = f"""请分析以下素材的标签信息：

目录路径：{directory_path or "未知"}
文件名：{file_name}

请按系统提示中的 JSON 格式返回分析结果。"""

    result = chat(
        db,
        preset_name="asset_analyze",
        messages=[{"role": "user", "content": prompt}],
        caller_module="asset_analyze",
    )

    content = _clean_ai_response(result["content"])

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        # 尝试从文本中提取 JSON
        json_match = re.search(r'\{[\s\S]*\}', content)
        if json_match:
            try:
                parsed = json.loads(json_match.group(0))
            except json.JSONDecodeError:
                parsed = {}
        else:
            parsed = {}

    confidence = parsed.get("confidence", 0.0)

    suggestions = []
    for dim_key, dim_label in _DIMENSION_MAP.items():
        raw_values = parsed.get(dim_key)
        if raw_values is None:
            continue

        if isinstance(raw_values, str):
            raw_values = [raw_values]
        elif not isinstance(raw_values, list):
            continue

        if not raw_values:
            continue

        # 查找维度
        dim = db.query(TagDimension).filter(TagDimension.name == dim_key).first()
        if not dim:
            continue

        # 查找标签值 ID
        value_ids = _find_tag_value_ids(db, dim_key, raw_values)
        if not value_ids:
            continue

        values = (
            db.query(TagValue)
            .filter(TagValue.id.in_(value_ids))
            .all()
        )

        suggestions.append({
            "dimension_id": dim.id,
            "dimension_name": dim.name,
            "dimension_label": dim.label,
            "values": [{"tag_value_id": v.id, "value": v.value} for v in values],
            "is_ai_suggested": True,
        })

    return {
        "confidence": confidence,
        "suggestions": suggestions,
        "raw_response": content,
    }
