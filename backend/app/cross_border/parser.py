"""Read DHL workbooks by the English header, keeping original text for export."""
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from io import BytesIO
import json
import math
import logging
from pathlib import Path
from zipfile import ZipFile

import openpyxl
import xlrd


HEAD = "OrderHead"
LINE = "OrderList"
BASE = "BaseTransfer"
RECEIPT = "ReceiptsHead"
FIELDS = {
    HEAD: "appType appTime appStatus orderType orderNo ebpCode ebpName ebcCode ebcName goodsValue freight currency note".split(),
    LINE: "orderNo gnum itemNo itemName itemDescribe barCode unit currency qty price totalPrice note".split(),
    RECEIPT: "appType appTime appStatus ebpName ebpCode ebcCode ebcName orderNo payCode payName payNo charge currency accountingDate note".split(),
    BASE: "copCode copName dxpMode dxpId note".split(),
}
LABELS = {
    HEAD: "报送类型 报送时间 报送状态 订单类型 订单编号 电商平台代码 电商平台名称 电商企业代码 电商企业名称 商品金额 运杂费 币制 备注".split(),
    LINE: "订单号 序号 企业商品货号 企业商品名称 企业商品描述 条形码 计量单位 币制 数量 单价 总价 备注".split(),
    RECEIPT: "报送类型 报送时间 报送状态 电商平台名称 电商平台代码 电商企业代码 电商企业名称 订单编号 支付企业代码 支付企业名称 支付交易编号 收款金额 币制 到账时间 备注".split(),
    BASE: "传输企业代码 传输企业名称 报文传输模式 报文传输编号 备注".split(),
}
NUMERIC = {HEAD: ("goodsValue", "freight"), LINE: ("qty", "price", "totalPrice"), RECEIPT: ("charge",)}
MAX_BYTES = 8 * 1024 * 1024
MAX_ROWS = 10000
logger = logging.getLogger(__name__)


class WorkbookError(ValueError):
    """File-local diagnostic safe to display to the importing specialist."""


@dataclass
class Entry:
    row_no: int
    head: dict
    line: dict | None
    base: dict
    occurrence: int
    content_hash: str


def as_text(value):
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return str(int(value)) if value.is_integer() else repr(value)
    return str(value)


def records(sheet, rows):
    next(rows, None)  # Chinese display header. Column order follows the English keys.
    keys = [as_text(cell).strip() for cell in next(rows, ())]
    for key in FIELDS[sheet]:
        if keys.count(key) != 1:
            raise WorkbookError(f"{sheet} 第 2 行缺少或重复字段 {key}")
    columns = [(key, keys.index(key)) for key in FIELDS[sheet]]
    result = []
    for number, values in enumerate(rows, 3):
        if number > MAX_ROWS + 2:
            raise WorkbookError(f"{sheet} 第 {number} 行超出导入容量")
        for key, i in columns:
            if key == "orderNo" and i < len(values) and isinstance(values[i], (int, float)) and abs(values[i]) >= 10**15:
                raise WorkbookError(f"{sheet} 第 {number} 行 orderNo 超出 Excel 数字精度，请使用文本订单号")
        row = {key: as_text(values[i]) if i < len(values) else "" for key, i in columns}
        if not any(row.values()):
            continue
        if "orderNo" in row:
            no = row["orderNo"]
            if not (no.isascii() and no.isdecimal() and 15 <= len(no) <= 20):
                raise WorkbookError(f"{sheet} 第 {number} 行 orderNo 须为 15–20 位文本数字")
        for key in NUMERIC.get(sheet, ()):
            try:
                value = Decimal(row[key])
            except InvalidOperation as exc:
                raise WorkbookError(f"{sheet} 第 {number} 行 {key} 不是有效数值") from exc
            if not value.is_finite() or value < 0 or value.adjusted() > 15 or value.as_tuple().exponent < -20:
                raise WorkbookError(f"{sheet} 第 {number} 行 {key} 超出有效数值范围")
        result.append((number, row))
    return result


def _assemble(names, get_rows):
    order = HEAD in names or LINE in names
    if order and RECEIPT in names:
        raise WorkbookError("工作簿同时含订单与收款单，请分别上传")
    sheets = (HEAD, LINE, BASE) if order else (RECEIPT, BASE)
    data = {}
    for sheet in sheets:
        if sheet not in names:
            raise WorkbookError(f"缺少工作表 {sheet}（第 1 行）")
        data[sheet] = records(sheet, iter(get_rows(sheet)))
    primary = data[sheets[0]]
    if not primary:
        raise WorkbookError(f"{sheets[0]} 第 3 行起没有数据")
    for sheet in sheets[1:]:
        if len(data[sheet]) != len(primary):
            raise WorkbookError(f"{sheet} 第 {min(len(data[sheet]), len(primary)) + 3} 行起与 {sheets[0]} 行数不一致")
    counts = Counter()
    entries = []
    for i, (number, head) in enumerate(primary):
        sources = [data[sheet][i] for sheet in sheets[1:]]
        if any(other_no != number for other_no, _ in sources):
            raise WorkbookError(f"{sheets[0]} 第 {number} 行与明细或传输行未对齐")
        line = data[LINE][i][1] if order else None
        if order and line["orderNo"] != head["orderNo"]:
            raise WorkbookError(f"{LINE} 第 {number} 行 orderNo 与 {HEAD} 不一致")
        identity = [sheets[0], {k: v for k, v in head.items() if k != "appTime"}, line]
        payload = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        counts[payload] += 1
        sequence = counts[payload]
        digest = sha256(payload + b"#" + str(sequence).encode()).hexdigest()
        entries.append(Entry(number, head, line, data[BASE][i][1], sequence, digest))
    return ("order" if order else "receipt"), entries


def parse(file_name, content):
    suffix = Path(file_name).suffix.lower()
    if len(content) > MAX_BYTES or suffix not in {".xls", ".xlsx"}:
        raise WorkbookError("请选择 8 MB 以内的 .xls 或 .xlsx 文件")
    try:
        if suffix == ".xls":
            book = xlrd.open_workbook(file_contents=content, on_demand=True)
            try:
                def rows(name):
                    sheet = book.sheet_by_name(name)
                    return (sheet.row_values(i) for i in range(sheet.nrows))
                return _assemble(book.sheet_names(), rows)
            finally:
                book.release_resources()
        with ZipFile(BytesIO(content)) as archive:
            if sum(entry.file_size for entry in archive.infolist()) > MAX_BYTES * 8:
                raise WorkbookError("工作簿解压后超出容量")
        book = openpyxl.load_workbook(BytesIO(content), read_only=True, data_only=False)
        try:
            def rows(name):
                sheet = book[name]
                if (sheet.max_column or 0) > 256 or (sheet.max_row or 0) > MAX_ROWS + 2:
                    raise WorkbookError(f"{name} 第 1 行工作表范围超出容量")
                return sheet.values
            return _assemble(book.sheetnames, rows)
        finally:
            book.close()
    except WorkbookError:
        raise
    except Exception as exc:
        # BIFF, ZIP and XML readers raise different exception types for damaged files.
        logger.warning("Unreadable DHL workbook: %s", type(exc).__name__)
        print(f"[cross_border] unreadable workbook: {type(exc).__name__}", flush=True)
        raise WorkbookError("无法读取 Excel 文件，请重新从 DHL 导出") from exc
