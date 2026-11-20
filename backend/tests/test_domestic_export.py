from io import BytesIO
from urllib.parse import unquote

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

from app.domestic import router as domestic_router
from app.domestic.export_service import build_order_workbook


def _order_detail():
    return {
        "domestic_no": "DO20260819-001",
        "order_no": "322-3",
        "order_date": "2026-08-19",
        "customer_name": "尚都",
        "customer_custom_code": "LS-00322",
        "order_category": "special",
        "order_category_label": "特单",
        "order_type": "first_order",
        "order_type_label": "首单",
        "order_channel": "wechat",
        "order_channel_label": "微信",
        "customer_balance": 4506,
        "total_amount": 1998,
        "balance_snapshot": {"source": "ledger", "transaction_type": "order_charge",
                             "balance_before": 6504, "balance_after": 4506, "settlement_amount": 1998},
        "remark": "整单备注",
        "items": [
            {
                "line_code": "A1",
                "product_name": "头套 / 递顶 / L / 20厘米",
                "attrs": {
                    "product_type": "cap",
                    "craft": "递顶",
                    "net_color": "浅棕",
                    "size": "L",
                    "length": "20厘米",
                    "density": "中",
                    "hair_style_series": "直发",
                },
                "order_qty": 2,
                "original_price": 998,
                "unit_price": 849,
                "discount_amount": 149,
                "line_amount": 1698,
                "hairstyle": "短直发",
                "color": "自然色",
                "style_requirement": "前额和鬓角缝粘胶点",
                "remark": "明细备注",
                "ship_time": "2026-08-20T10:30:00",
                "ship_weight": 54.5,
            },
            {
                "line_code": "A2",
                "product_name": "发片 / 机制 / 15厘米",
                "attrs": {
                    "product_type": "piece",
                    "craft": "机制",
                    "net_color": None,
                    "size": "8×10",
                    "length": "15厘米",
                    "density": "轻",
                },
                "order_qty": 1,
                "original_price": 370,
                "unit_price": 300,
                "discount_amount": 70,
                "line_amount": 300,
                "hairstyle": None,
                "color": None,
                "style_requirement": None,
                "remark": None,
                "ship_time": None,
                "ship_weight": None,
            },
        ],
    }


def test_build_order_workbook_matches_requisition_layout_and_fields():
    workbook = load_workbook(build_order_workbook(_order_detail(), "Rice"), data_only=False)
    sheet = workbook.active

    assert sheet.title == "内贸订单领货单"
    assert sheet["B1"].value == "内贸订单领货单"
    assert "下单日期：2026/08/19" in sheet["A2"].value
    assert "客户订单号：322-3" in sheet["A2"].value
    assert "系统单号：DO20260819-001" in sheet["A2"].value
    assert "申请人：Rice" in sheet["A2"].value
    assert "客户编码：LS-00322" in sheet["A2"].value
    assert "客户名称：尚都" in sheet["A3"].value
    assert "之前余额：¥6504.00" in sheet["A4"].value
    assert "本次订单金额：¥1998.00" in sheet["A4"].value
    assert "扣减本次订单后余额：¥4506.00" in sheet["A4"].value
    assert "订单类别：特单" in sheet["A3"].value
    assert "订单类型：首单" in sheet["A3"].value
    assert "订单渠道：微信" in sheet["A3"].value
    assert "订单金额" not in sheet["A3"].value
    assert "客户余额" not in sheet["A3"].value

    assert [sheet.cell(5, col).value for col in range(1, 15)] == [
        "明细号", "产品类型", "产品规格", "数量", "出库数量", "原价（元/件）", "优惠金额（元/件）",
        "优惠后单价（元/件）", "手工费（元/件）", "小计（元）", "发型备注", "颜色", "发型要求", "备注",
    ]
    assert [sheet.cell(6, col).value for col in (1, 2, 4, 5, 6, 7, 8, 10, 11, 12, 13, 14)] == [
        "A1", "头套", 2, None, 998, 149, 849, 1698, "短直发", "自然色", "前额和鬓角缝粘胶点", "明细备注",
    ]
    assert "工艺/尺寸：递顶" in sheet["C6"].value
    assert "发型系列：直发" in sheet["C6"].value
    assert sheet["B7"].value == "发片"
    assert sheet["C7"].value == "工艺/尺寸：机制\n发长：15厘米"
    assert sheet["E7"].value is None
    assert sheet.row_dimensions[6].height >= 75
    assert sheet.page_setup.orientation == "landscape"
    assert sheet.print_area == "'内贸订单领货单'!$A$1:$N$9"
    assert sheet.page_setup.paperSize == 9
    assert "整单备注" in sheet["A9"].value


def test_build_order_workbook_uses_safe_excel_text_for_user_content():
    detail = _order_detail()
    detail["items"][0]["remark"] = "=HYPERLINK(\"https://example.com\")"

    workbook = load_workbook(build_order_workbook(detail, "+SUM(1,1)"), data_only=False)
    sheet = workbook.active

    assert sheet["N6"].value == "'=HYPERLINK(\"https://example.com\")"
    assert "申请人：'+SUM(1,1)" in sheet["A2"].value
    assert sheet["A2"].data_type != "f"


def test_export_order_returns_named_xlsx(monkeypatch):
    detail = _order_detail() | {"created_by_name": "下单员"}
    captured = {}
    monkeypatch.setattr(domestic_router.order_service, "get_order_detail", lambda db, order_id: detail)

    def fake_workbook(data, applicant_name):
        captured["args"] = (data, applicant_name)
        return BytesIO(b"xlsx")

    monkeypatch.setattr(domestic_router.export_service, "build_order_workbook", fake_workbook)

    class FakeDb:
        committed = False

        def commit(self):
            self.committed = True

    db = FakeDb()
    response = domestic_router.export_order(
        7, db=db, current_user={"sub": "9", "roles": ["super_admin"], "permissions": []},
    )

    assert captured["args"] == (detail, "下单员")
    assert db.committed is True
    assert response.media_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert "内贸订单-DO20260819-001.xlsx" in unquote(response.headers["content-disposition"])


def test_long_remark_wraps_in_the_detail_cell_and_uses_available_column_width():
    detail = _order_detail()
    baseline = load_workbook(build_order_workbook(detail))
    remark = (
        "发际线、刘海和后面发量按确认要求加密，递针顶位置请注意衔接。\n"
        "头围 56.5，左右 32.5，前后 34.5。\n"
        "工艺：递针顶。\n毛胚长度：35 厘米。\n"
        "头发颜色：自然色。\n发型要求：毛胚。\n"
        "请保留原有发色，制作完成后核对尺寸和密度。"
    )
    detail["items"][0]["remark"] = remark

    for sheet, original in zip(load_workbook(build_order_workbook(detail)), baseline):
        first_row = original.max_row - 3
        remark_letter = get_column_letter(sheet.max_column)
        remark_cell = sheet[f"{remark_letter}{first_row}"]
        assert sheet.cell(first_row, 1).value == "A1"
        assert sheet.cell(first_row + 1, 1).value == "A2"
        assert remark_cell.value == remark
        assert remark_cell.alignment.wrap_text
        assert sheet.row_dimensions[first_row].height > original.row_dimensions[first_row].height
        assert sheet.column_dimensions[remark_letter].width > original.column_dimensions[remark_letter].width
        assert sheet.column_dimensions["D"].width == original.column_dimensions["D"].width
        assert any(sheet.column_dimensions[key].width < original.column_dimensions[key].width
                   for key in original.column_dimensions if key != remark_letter)
        assert sum(c.width for c in sheet.column_dimensions.values()) <= sum(
            c.width for c in original.column_dimensions.values()
        ) + 0.01
        assert sheet.max_row == original.max_row


def test_build_order_workbook_preserves_extreme_requirements_next_to_each_detail():
    detail = _order_detail()
    detail["items"] = []
    long_requirement = "=要求\n" * 399 + "=要求"
    long_remark = "出货前确认，有问题联系负责人。" * 120
    continuous_requirement = "要求" * 1000
    assert len(continuous_requirement) == 2000
    for index in range(1, 51):
        item = _order_detail()["items"][0] | {
            "line_code": f"A{index}",
            "style_requirement": (
                long_requirement if index == 1
                else continuous_requirement if index == 2
                else f"要求{index}"
            ),
            "remark": long_remark if index == 1 else None,
        }
        detail["items"].append(item)

    workbook = load_workbook(build_order_workbook(detail, "下单员"), data_only=False)
    order_sheet = workbook["内贸订单领货单"]
    assert len(workbook.worksheets) == 2
    assert order_sheet.page_setup.paperSize == 9
    assert order_sheet.print_title_rows == "$1:$5"
    for sheet in workbook:
        detail_rows = {
            cell.value: cell.row
            for cell in sheet["A"]
            if cell.value in {"A1", "A2", "A3", "A50"}
        }
        assert list(detail_rows) == ["A1", "A2", "A3", "A50"]
        assert detail_rows["A50"] + 2 == sheet.max_row
        assert sheet.print_area.endswith(f"${sheet.max_row}")
        for code, following, column, original in (
            ("A1", "A2", sheet.max_column - 1, "'" + long_requirement),
            ("A1", "A2", sheet.max_column, long_remark),
            ("A2", "A3", sheet.max_column - 1, continuous_requirement),
        ):
            first, following_row = detail_rows[code], detail_rows[following]
            cells = [sheet.cell(row, column) for row in range(first, following_row) if sheet.cell(row, column).value]
            assert len(cells) > 1
            assert "".join(cell.value for cell in cells) == original
            assert all(cell.alignment.wrap_text and cell.data_type == "s" for cell in cells)
            assert max(sheet.row_dimensions[row].height for row in range(first, following_row)) <= 409
            assert sheet.cell(first, 4).value == 2
            assert all(sheet.cell(row, 4).value is None for row in range(first + 1, following_row))
            assert all(sheet.cell(row, 1).value == f"{code}（续）" for row in range(first + 1, following_row))


def test_reference_images_are_embedded_in_their_product_cells(tmp_path, monkeypatch):
    from zipfile import ZipFile
    from PIL import Image
    from app.domestic import file_service

    monkeypatch.setattr(file_service, "storage_root", lambda: tmp_path)
    Image.new("RGB", (240, 320), "red").save(tmp_path / "first.png")
    Image.new("RGB", (320, 240), "blue").save(tmp_path / "second.webp")
    detail = _order_detail()
    detail["items"][0]["hairstyle_images"] = ["first.png", "second.webp"]
    detail["items"][1]["style_images"] = ["second.webp"]
    stream = build_order_workbook(detail)
    with ZipFile(stream) as archive:
        assert len([name for name in archive.namelist() if name.startswith("xl/media/")]) == 6
        assert all(b"TargetMode=\"External\"" not in archive.read(name)
                   for name in archive.namelist() if name.endswith(".rels"))
    stream.seek(0)
    workbook = load_workbook(stream)
    sheet = workbook.active
    public = workbook.worksheets[1]
    assert [(image.anchor._from.row, image.anchor._from.col) for image in public._images] == [(4, 5), (4, 5), (5, 7)]
    assert [(image.anchor._from.row, image.anchor._from.col) for image in sheet._images] == [(5, 10), (5, 10), (6, 12)]
    assert sheet["K6"].value == "短直发"
    assert sheet["M7"].value == "—"
    for image in sheet._images:
        assert image.anchor.ext.cx > 0 and image.anchor.ext.cy > 0
        assert image.anchor._from.rowOff + image.anchor.ext.cy <= sheet.row_dimensions[image.anchor._from.row + 1].height * 12700


def test_export_reports_unavailable_or_outside_images_without_losing_order(tmp_path, monkeypatch):
    from app.domestic import file_service
    monkeypatch.setattr(file_service, "storage_root", lambda: tmp_path / "private")
    detail = _order_detail()
    detail["items"][0]["hairstyle_images"] = ["missing.png", "../outside.png"]
    sheet = load_workbook(build_order_workbook(detail)).active
    assert "2 张参考图不可用" in sheet["K6"].value
    assert len(sheet._images) == 0


def test_multiline_remark_is_preserved_above_reference_images(tmp_path, monkeypatch):
    from PIL import Image
    from app.domestic import file_service
    from app.domestic.export_image_service import wrapped_text_lines

    monkeypatch.setattr(file_service, "storage_root", lambda: tmp_path)
    Image.new("RGB", (240, 320), "red").save(tmp_path / "reference.png")
    detail = _order_detail()
    text = "\n".join(["短发要求"] * 12)
    assert len(text) < 80
    detail["items"][0].update(remark=text, remark_images=["reference.png"])
    workbook = load_workbook(build_order_workbook(detail))
    for view in workbook:
        image = view._images[0]
        row, col = image.anchor._from.row + 1, image.anchor._from.col + 1
        cell = view.cell(row, col)
        assert view.cell(row, 1).value == "A1"
        assert col == view.max_column
        assert cell.value == text
        assert image.anchor._from.rowOff >= len(
            wrapped_text_lines(cell.value, view.column_dimensions[cell.column_letter].width)
        ) * 19 * 9525
        assert image.anchor._from.rowOff + image.anchor.ext.cy <= view.row_dimensions[row].height * 12700


def test_image_continues_on_the_same_detail_when_the_remark_fills_its_row(tmp_path, monkeypatch):
    from PIL import Image
    from app.domestic import file_service

    monkeypatch.setattr(file_service, "storage_root", lambda: tmp_path)
    Image.new("RGB", (240, 320), "red").save(tmp_path / "reference.png")
    detail = _order_detail()
    remark = "\n".join(f"确认要求{i}" for i in range(20))
    detail["items"][0].update(remark=remark, remark_images=["reference.png"])

    for sheet in load_workbook(build_order_workbook(detail)):
        image = sheet._images[0]
        row, col = image.anchor._from.row + 1, image.anchor._from.col + 1
        assert col == sheet.max_column
        assert sheet.cell(row - 1, 1).value == "A1"
        assert sheet.cell(row - 1, col).value == remark
        assert sheet.cell(row, 1).value == "A1（续）"
        assert sheet.cell(row + 1, 1).value == "A2"
        assert image.anchor._from.rowOff + image.anchor.ext.cy <= sheet.row_dimensions[row].height * 12700


def test_export_money_includes_labor_and_never_uses_customer_name_fallback():
    detail = _order_detail()
    detail["customer_custom_code"] = None
    detail["items"][0].update(unit_price=879, labor_fee=30, line_amount=1758)
    sheet = load_workbook(build_order_workbook(detail)).active
    assert [sheet.cell(6, col).value for col in (6, 7, 8, 9, 10)] == [998, 149, 849, 30, 1758]
    assert "客户编码：未填写" in sheet["A2"].value
    assert "尚都" not in sheet["A2"].value


def test_export_adjustment_and_draft_balances_are_labeled():
    detail = _order_detail()
    detail["balance_snapshot"].update(transaction_type="order_adjustment", settlement_amount=-100)
    sheet = load_workbook(build_order_workbook(detail)).active
    assert "实际退回：¥100.00" in sheet["A4"].value
    assert "最近调整前余额" in sheet["A4"].value
    detail["balance_snapshot"]["source"] = "draft_preview"
    sheet = load_workbook(build_order_workbook(detail)).active
    assert "草稿未扣款" in sheet["A4"].value and "预计扣减后余额" in sheet["A4"].value


def test_two_export_sheets_separate_all_structured_financial_information():
    detail = _order_detail()
    detail['items'][0].update(labor_fee=30, unit_price=879, line_amount=1758)
    workbook = load_workbook(build_order_workbook(detail))
    assert workbook.sheetnames == ['内贸订单领货单', '内贸订单领货单（无价格）']
    normal, public = workbook.worksheets
    for sheet in workbook:
        assert '客户名称：尚都' in sheet['A3'].value
    assert normal['I6'].value == 30
    assert public.max_column == 9
    assert [public.cell(4, col).value for col in range(1, 10)] == [
        '明细号', '产品类型', '产品规格', '数量', '出库数量', '发型备注', '颜色', '发型要求', '备注',
    ]
    text = ' '.join(str(cell.value or '') for row in public for cell in row)
    assert not any(word in text for word in ('原价', '优惠', '手工费', '小计', '金额', '余额', '¥'))
    assert not any(d.hidden for d in public.column_dimensions.values())
    assert not any(cell.value in (998, 149, 849, 30, 1758, 1998, 6504, 4506) for row in public for cell in row)
    assert [public.cell(5, col).value for col in (1, 2, 4, 5, 6, 9)] == ['A1', '头套', 2, None, '短直发', '明细备注']


def test_production_two_sheets_show_customer_without_inventing_prices():
    detail = _order_detail() | {'order_kind':'production', 'customer_name':'备货客户'}
    workbook = load_workbook(build_order_workbook(detail))
    assert workbook.sheetnames == ['内贸生产备货单', '内贸生产备货单（无价格）']
    for sheet in workbook:
        assert '客户名称：备货客户' in sheet['A3'].value
        assert sheet.max_column == 12
        text = ' '.join(str(cell.value or '') for row in sheet for cell in row)
        assert not any(word in text for word in ('原价', '优惠', '手工费', '小计', '余额', '¥'))


def test_production_remarks_and_order_notes_preserve_all_text_in_their_sections():
    detail = _order_detail() | {"order_kind": "production"}
    detail["items"][0]["remark"] = "确认备货尺寸与发长，完工后核对数量。" * 10
    detail["remark"] = "\n".join(f"整单要求{i}" for i in range(120))
    workbook = load_workbook(build_order_workbook(detail))
    for sheet in workbook:
        assert sheet["L5"].value == detail["items"][0]["remark"]
        assert sheet["L5"].alignment.wrap_text
        assert sheet["A8"].value.startswith("注意事项")
        notes = "".join(sheet.cell(row, 1).value for row in range(8, sheet.max_row + 1))
        assert notes.split("订单备注：", 1)[1] == detail["remark"]
        assert sheet.print_area.endswith(f"${sheet.max_row}")
        assert all(sheet.cell(row, 1).alignment.wrap_text and sheet.row_dimensions[row].height <= 409
                   for row in range(8, sheet.max_row + 1))
