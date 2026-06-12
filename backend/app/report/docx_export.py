"""生产订单 Word 导出服务。

使用 python-docx 生成 .docx 文件，支持 A4/A3/A5/B5 + 横版/竖版。
"""

from __future__ import annotations

import io
from typing import Optional

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Cm, Pt, Emu, RGBColor
from docx.oxml.ns import qn

# 纸张尺寸映射 (宽 cm, 高 cm)
PAGE_SIZES = {
    "A4": (21.0, 29.7),
    "A3": (29.7, 42.0),
    "A5": (14.8, 21.0),
    "B5": (17.6, 25.0),
}

# 字体 & 颜色
_FONT = "Microsoft YaHei"
_COLOR_HEADER_BG = RGBColor(0xF0, 0xF2, 0xF7)
_COLOR_GROUP_BG = RGBColor(0xE2, 0xE5, 0xEF)
_COLOR_ACCENT = RGBColor(0xD4, 0x94, 0x1C)
_COLOR_GRAY = RGBColor(0x71, 0x80, 0x96)


def _set_cell_shading(cell, color_hex: str):
    """设置单元格底色"""
    shading = cell._element.get_or_add_tcPr()
    shd = shading.find(qn("w:shd"))
    if shd is None:
        shd = shading.makeelement(qn("w:shd"), {})
        shading.append(shd)
    shd.set(qn("w:fill"), color_hex)
    shd.set(qn("w:val"), "clear")


def _set_cell_text(cell, text: str, bold: bool = False, size: int = 9,
                   align=WD_ALIGN_PARAGRAPH.CENTER, color=None):
    """设置单元格文字"""
    cell.text = ""
    p = cell.paragraphs[0]
    p.alignment = align
    run = p.add_run(str(text))
    run.bold = bold
    run.font.size = Pt(size)
    run.font.name = _FONT
    run._element.rPr.rFonts.set(qn("w:eastAsia"), _FONT)
    if color:
        run.font.color.rgb = color
    # 缩小行距
    p.paragraph_format.space_before = Pt(1)
    p.paragraph_format.space_after = Pt(1)


def _set_cell_two_line(cell, line1: str, line2: str, bold1: bool = False,
                       size1: int = 9, size2: int = 7,
                       align=WD_ALIGN_PARAGRAPH.CENTER):
    """设置单元格双行文字（第二行小字灰色）"""
    cell.text = ""
    p = cell.paragraphs[0]
    p.alignment = align
    p.paragraph_format.space_before = Pt(1)
    p.paragraph_format.space_after = Pt(1)

    run1 = p.add_run(line1)
    run1.bold = bold1
    run1.font.size = Pt(size1)
    run1.font.name = _FONT
    run1._element.rPr.rFonts.set(qn("w:eastAsia"), _FONT)

    if line2:
        run2 = p.add_run(f"\n{line2}")
        run2.font.size = Pt(size2)
        run2.font.name = _FONT
        run2.font.color.rgb = _COLOR_GRAY
        run2._element.rPr.rFonts.set(qn("w:eastAsia"), _FONT)


def generate_production_order_docx(
    data: dict,
    page_size: str = "A4",
    orientation: str = "portrait",
) -> bytes:
    """生成生产订单 .docx 文件，返回 bytes。

    Args:
        data: get_production_order_print_data 返回的数据
        page_size: A4/A3/A5/B5
        orientation: portrait/landscape
    """
    doc = Document()

    # ── 页面设置 ──
    section = doc.sections[0]
    w, h = PAGE_SIZES.get(page_size, PAGE_SIZES["A4"])
    if orientation == "landscape":
        w, h = h, w
    section.page_width = Cm(w)
    section.page_height = Cm(h)
    section.orientation = WD_ORIENT.LANDSCAPE if orientation == "landscape" else WD_ORIENT.PORTRAIT
    section.top_margin = Cm(1.2)
    section.bottom_margin = Cm(1.0)
    section.left_margin = Cm(1.0)
    section.right_margin = Cm(1.0)

    header = data.get("header", {})
    sub_tables = data.get("sub_tables", [])
    column_defs = data.get("column_defs", [])
    rows = data.get("rows", [])
    col_totals = data.get("col_totals", {})
    weight_totals = data.get("weight_totals", {})
    weight_t_totals = data.get("weight_t_totals", {})

    # ── 标题 ──
    p_company = doc.add_paragraph()
    p_company.alignment = WD_ALIGN_PARAGRAPH.LEFT
    run_company = p_company.add_run(header.get("company_name", ""))
    run_company.bold = True
    run_company.font.size = Pt(16)
    run_company.font.name = _FONT
    run_company._element.rPr.rFonts.set(qn("w:eastAsia"), _FONT)

    # 副标题
    p_sub = doc.add_paragraph()
    p_sub.alignment = WD_ALIGN_PARAGRAPH.LEFT
    run_sub = p_sub.add_run("生产订单 · 库存单")
    run_sub.font.size = Pt(11)
    run_sub.font.color.rgb = _COLOR_GRAY
    run_sub.font.name = _FONT
    run_sub._element.rPr.rFonts.set(qn("w:eastAsia"), _FONT)

    # 订单信息
    info_parts = [f"订单编号：{header.get('order_no', '')}"]
    if header.get("batch_no"):
        info_parts.append(f"批次号：{header['batch_no']}")
    if header.get("remark"):
        info_parts.append(f"备注：{header['remark']}")
    p_info = doc.add_paragraph()
    p_info.alignment = WD_ALIGN_PARAGRAPH.LEFT
    run_info = p_info.add_run("　　".join(info_parts))
    run_info.font.size = Pt(9)
    run_info.font.name = _FONT
    run_info._element.rPr.rFonts.set(qn("w:eastAsia"), _FONT)

    if not column_defs or not rows:
        p_empty = doc.add_paragraph("该订单暂无明细数据")
        p_empty.alignment = WD_ALIGN_PARAGRAPH.CENTER
        buf = io.BytesIO()
        doc.save(buf)
        return buf.getvalue()

    # ── 按型号分类拆分的子表 ──────────────────────────────
    tables_to_render = []
    if sub_tables:
        for sub in sub_tables:
            sub_cdefs = sub.get("column_defs", [])
            sub_rows = sub.get("rows", [])
            sub_ct = sub.get("col_totals", {})
            sub_remarks = sub.get("category_remarks", [])
            sub_label = sub.get("category_label", "颜色")
            if sub_cdefs:
                tables_to_render.append((sub_cdefs, sub_rows, sub_ct, sub_remarks, sub_label))
    else:
        # 无分类数据时兜底：渲染全量单表
        tables_to_render.append((column_defs, rows, col_totals, [], "颜色"))

    for tbl_idx, (tbl_cdefs, tbl_rows, tbl_ct, tbl_remarks, tbl_label) in enumerate(tables_to_render):
        if tbl_idx > 0:
            doc.add_paragraph()  # 子表间空行

        num_cols = 1 + len(tbl_cdefs) + 1
        total_doc_rows = 2 + len(tbl_rows) + 1
        table = doc.add_table(rows=total_doc_rows, cols=num_cols)
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        table.style = "Table Grid"

        # ── 一级表头（group-header）────────────────────────────
        cell_color_header = table.cell(0, 0)
        remark_text = "\n".join(tbl_remarks) if tbl_remarks else tbl_label
        _set_cell_text(cell_color_header, remark_text, bold=True, size=7,
                       align=WD_ALIGN_PARAGRAPH.LEFT)
        _set_cell_shading(cell_color_header, "E2E5EF")
        cell_color_header.merge(table.cell(1, 0))

        last_col_idx = num_cols - 1
        cell_total_header = table.cell(0, last_col_idx)
        _set_cell_text(cell_total_header, "合计", bold=True, size=9)
        _set_cell_shading(cell_total_header, "FEF9F0")
        cell_total_header.merge(table.cell(1, last_col_idx))

        # 合并 group 列
        col_idx = 1
        current_group = None
        for col_def in tbl_cdefs:
            if col_def["group"] != current_group:
                current_group = col_def["group"]
                group_cols = [c for c in tbl_cdefs if c["group"] == current_group]
                span = len(group_cols)
                start = col_idx
                end = col_idx + span - 1
                cell = table.cell(0, start)
                if span > 1:
                    cell.merge(table.cell(0, end))
                _set_cell_text(cell, current_group, bold=True, size=9)
                _set_cell_shading(cell, "E2E5EF")
            col_idx += 1

        # ── 二级表头（size-header）────────────────────────────
        for i, col_def in enumerate(tbl_cdefs):
            cell = table.cell(1, 1 + i)
            size_req = col_def.get("size_req", "")
            if size_req:
                _set_cell_two_line(cell, col_def["size"], size_req)
            else:
                _set_cell_text(cell, col_def["size"], size=8)
            _set_cell_shading(cell, "F0F2F7")

        # ── 数据行 ────────────────────────────────────────────
        for row_i, row_data in enumerate(tbl_rows):
            actual_row = 2 + row_i

            color_cell = table.cell(actual_row, 0)
            color_req = row_data.get("production_color_requirement", "")
            color_main = row_data.get("color", "")
            if color_req:
                _set_cell_two_line(color_cell, color_main, color_req,
                                   bold1=True, align=WD_ALIGN_PARAGRAPH.LEFT)
            else:
                _set_cell_text(color_cell, color_main, bold=True,
                               align=WD_ALIGN_PARAGRAPH.LEFT)

            for col_i, col_def in enumerate(tbl_cdefs):
                val = row_data.get(col_def["key"], 0)
                cell = table.cell(actual_row, 1 + col_i)
                _set_cell_text(cell, str(val), size=9,
                               color=_COLOR_GRAY if val == 0 else None)

            row_total = row_data.get("row_total", 0)
            total_cell = table.cell(actual_row, last_col_idx)
            _set_cell_text(total_cell, str(row_total), bold=True, size=9)
            _set_cell_shading(total_cell, "FEF9F0")

        # ── 合计行 ────────────────────────────────────────────
        footer_row = 2 + len(tbl_rows)
        _set_cell_text(table.cell(footer_row, 0), "合计", bold=True, size=9,
                       align=WD_ALIGN_PARAGRAPH.LEFT)
        _set_cell_shading(table.cell(footer_row, 0), "F8F9FC")

        for col_i, col_def in enumerate(tbl_cdefs):
            val = tbl_ct.get(col_def["key"], 0)
            cell = table.cell(footer_row, 1 + col_i)
            _set_cell_text(cell, str(val), bold=True, size=9)
            _set_cell_shading(cell, "F8F9FC")

        grand_total = tbl_ct.get("grand_total", 0)
        gt_cell = table.cell(footer_row, last_col_idx)
        _set_cell_text(gt_cell, str(grand_total), bold=True, size=10,
                       color=_COLOR_ACCENT)
        _set_cell_shading(gt_cell, "FEF9F0")

    # ── 公斤数统计表 ──────────────────────────────────────
    if weight_totals:
        doc.add_paragraph()  # 空行
        p_wt_title = doc.add_paragraph()
        run_wt = p_wt_title.add_run("公斤数统计（kg）")
        run_wt.bold = True
        run_wt.font.size = Pt(10)
        run_wt.font.name = _FONT
        run_wt._element.rPr.rFonts.set(qn("w:eastAsia"), _FONT)

        # 公斤数表基于全量 column_defs，需独立计算列数
        wt_num_cols = 1 + len(column_defs) + 1
        wt_last_col = wt_num_cols - 1

        # 公斤数表：theader 2 行 + 数据行(纯色 + T色)
        has_t = weight_t_totals.get("grand_total", 0) > 0
        wt_data_rows = 1 + (1 if has_t else 0)
        wt_table = doc.add_table(rows=2 + wt_data_rows, cols=wt_num_cols)
        wt_table.alignment = WD_TABLE_ALIGNMENT.CENTER
        wt_table.style = "Table Grid"

        # 一级表头
        wt_cell0 = wt_table.cell(0, 0)
        _set_cell_text(wt_cell0, "等级", bold=True, size=9)
        _set_cell_shading(wt_cell0, "E2E5EF")
        wt_cell0.merge(wt_table.cell(1, 0))

        wt_cell_last = wt_table.cell(0, wt_last_col)
        _set_cell_text(wt_cell_last, "合计", bold=True, size=9)
        _set_cell_shading(wt_cell_last, "E2E5EF")
        wt_cell_last.merge(wt_table.cell(1, wt_last_col))

        col_idx = 1
        current_group = None
        for col_def in column_defs:
            if col_def["group"] != current_group:
                current_group = col_def["group"]
                span = len([c for c in column_defs if c["group"] == current_group])
                start = col_idx
                end = col_idx + span - 1
                cell = wt_table.cell(0, start)
                if span > 1:
                    cell.merge(wt_table.cell(0, end))
                _set_cell_text(cell, current_group, bold=True, size=9)
                _set_cell_shading(cell, "E2E5EF")
            col_idx += 1

        # 二级表头
        for i, col_def in enumerate(column_defs):
            cell = wt_table.cell(1, 1 + i)
            size_req = col_def.get("size_req", "")
            if size_req:
                _set_cell_two_line(cell, col_def["size"], size_req)
            else:
                _set_cell_text(cell, col_def["size"], size=8)
            _set_cell_shading(cell, "F0F2F7")

        # 纯色行
        wt_row = 2
        _set_cell_text(wt_table.cell(wt_row, 0), "纯色", bold=True, size=9,
                       align=WD_ALIGN_PARAGRAPH.LEFT)
        for col_i, col_def in enumerate(column_defs):
            val = weight_totals.get(col_def["key"], 0)
            cell = wt_table.cell(wt_row, 1 + col_i)
            _set_cell_text(cell, str(val), size=9,
                           color=_COLOR_GRAY if val == 0 else None)
        gt = weight_totals.get("grand_total", 0)
        _set_cell_text(wt_table.cell(wt_row, wt_last_col), str(gt),
                       bold=True, size=9, color=_COLOR_ACCENT)

        # T色行
        if has_t:
            wt_row += 1
            _set_cell_text(wt_table.cell(wt_row, 0), "T色", bold=True, size=9,
                           align=WD_ALIGN_PARAGRAPH.LEFT)
            for col_i, col_def in enumerate(column_defs):
                val = weight_t_totals.get(col_def["key"], 0)
                cell = wt_table.cell(wt_row, 1 + col_i)
                _set_cell_text(cell, str(val), size=9,
                               color=_COLOR_GRAY if val == 0 else None)
            gt_t = weight_t_totals.get("grand_total", 0)
            _set_cell_text(wt_table.cell(wt_row, wt_last_col), str(gt_t),
                           bold=True, size=9, color=_COLOR_ACCENT)

    # ── 签字区（与 HTML 打印模板对齐：预填制单人/审核人/日期） ──
    doc.add_paragraph()
    creator = header.get("creator_name", "")
    reviewer = header.get("reviewer_name", "")
    print_date = header.get("print_date", "")

    p_sign = doc.add_paragraph()
    sign_parts = [f"制单人：{creator}"]
    sign_parts.append(f"审核人：{reviewer}")
    sign_parts.append(f"日期：{print_date}")
    run_sign = p_sign.add_run("　　".join(sign_parts))
    run_sign.font.size = Pt(10)
    run_sign.font.name = _FONT
    run_sign._element.rPr.rFonts.set(qn("w:eastAsia"), _FONT)

    # ── 页脚 ──
    p_footer = doc.add_paragraph()
    p_footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run_footer = p_footer.add_run(f"{header.get('company_name', '')}　　{header.get('order_no', '')}")
    run_footer.font.size = Pt(8)
    run_footer.font.color.rgb = _COLOR_GRAY
    run_footer.font.name = _FONT
    run_footer._element.rPr.rFonts.set(qn("w:eastAsia"), _FONT)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
