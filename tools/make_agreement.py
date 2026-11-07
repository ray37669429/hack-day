"""產生「土地使用同意書」Word 檔（依紙本版面重製，規格見 docs/agreement-spec.md）。

用法：
    python tools/make_agreement.py            # 產生空白範本與虛構樣本
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_ROW_HEIGHT_RULE
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

ROWS_PER_PAGE = 8  # 紙本實際為 8 列（白皮書寫 7 列，以紙本為準）
CATEGORIES = ("分耕", "輪耕", "託耕", "承租")
PENDING = "待確認"
FONT = "標楷體"

# 欄寬（cm），依紙本比例換算，合計約 26.7 cm（A4 橫式扣邊界）
COL_WIDTHS = [1.1, 4.1, 2.6, 2.6, 3.2, 4.0, 1.7, 4.0, 1.7, 1.7]


@dataclass
class Line:
    """同意書表格的一列。空字串代表留白；未確認的值請填 PENDING。"""
    category: str = ""
    location: str = ""
    area_ha: str = ""
    right_area_ha: str = ""
    period: str = ""
    owner: str = ""
    cultivator: str = ""
    note: str = ""

    def __post_init__(self) -> None:
        if self.category not in ("", PENDING, *CATEGORIES):
            raise ValueError(f"類別只能是 {CATEGORIES}，收到：{self.category}")


@dataclass
class Agreement:
    party_a: str = ""  # 甲方（所有權人）
    party_b: str = ""  # 乙方（耕作人）
    lines: list[Line] = field(default_factory=list)
    force_draft: bool = False  # 例如農民回答「不是我的地」：格子都填了也只能是草稿

    @property
    def is_draft(self) -> bool:
        if self.force_draft:
            return True
        values = [self.party_a, self.party_b]
        for ln in self.lines:
            values += [ln.category, ln.location, ln.area_ha, ln.right_area_ha,
                       ln.period, ln.owner, ln.cultivator]
        return any(PENDING in v for v in values)


def _font(run, size: float, bold: bool = False, color: RGBColor | None = None) -> None:
    run.font.name = FONT
    run.font.size = Pt(size)
    run.font.bold = bold
    run._element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), FONT)
    if color is not None:
        run.font.color.rgb = color


def _para(container, text: str = "", size: float = 13, bold: bool = False,
          align=WD_ALIGN_PARAGRAPH.LEFT, space_after: float = 0, color=None):
    p = container.add_paragraph()
    p.alignment = align
    p.paragraph_format.space_after = Pt(space_after)
    p.paragraph_format.space_before = Pt(0)
    if text:
        _font(p.add_run(text), size, bold, color)
    return p


def _cell(cell, text: str, size: float = 12, align=WD_ALIGN_PARAGRAPH.CENTER) -> None:
    cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
    p = cell.paragraphs[0]
    p.alignment = align
    p.paragraph_format.space_after = Pt(0)
    for i, part in enumerate(text.split("\n")):
        if i:
            p.add_run().add_break()
        if part:
            color = RGBColor(0xC0, 0x00, 0x00) if part == PENDING else None
            _font(p.add_run(part), size, color=color)


def _blank(name: str, width: int = 8) -> str:
    """前言的填空：有名字就填名字，沒有就留全形空白。"""
    return f"　{name}　" if name else "　" * width


def _page(doc: Document, ag: Agreement, lines: list[Line]) -> None:
    _para(doc, "土　　地　　使　　用　　同　　意　　書", size=22, bold=True,
          align=WD_ALIGN_PARAGRAPH.CENTER, space_after=10)
    _para(doc, f"本耕地所有權人（以下簡稱甲方）{_blank(ag.party_a)}"
               "持有下列耕地，經雙方協議同意由委由耕作人", space_after=4)
    _para(doc, f"（以下簡稱乙方）{_blank(ag.party_b)}"
               "等從事農業耕作，特立此協議書為證。", space_after=8)

    table = doc.add_table(rows=2 + ROWS_PER_PAGE, cols=10)
    table.style = "Table Grid"
    table.autofit = False
    for row in table.rows:
        for i, w in enumerate(COL_WIDTHS):
            row.cells[i].width = Cm(w)

    h0, h1 = table.rows[0], table.rows[1]
    for r, h in ((h0, 1.1), (h1, 1.2)):
        r.height, r.height_rule = Cm(h), WD_ROW_HEIGHT_RULE.AT_LEAST
    for col, label in {0: "類\n別", 1: "土地坐落\n及地號", 2: "本筆面積\n（公頃）",
                       3: "權利面積\n（公頃）", 4: "實施期間", 9: "備註"}.items():
        merged = h0.cells[col].merge(h1.cells[col])
        _cell(merged, label)
    _cell(h0.cells[5].merge(h0.cells[6]), "甲　　方")
    _cell(h0.cells[7].merge(h0.cells[8]), "乙　　方")
    for col, label in {5: "所有權人\n及 ID", 6: "簽名\n蓋章", 7: "耕作人\n及 ID", 8: "簽名\n蓋章"}.items():
        _cell(h1.cells[col], label)

    for i in range(ROWS_PER_PAGE):
        row = table.rows[2 + i]
        row.height, row.height_rule = Cm(1.2), WD_ROW_HEIGHT_RULE.AT_LEAST
        if i >= len(lines):
            continue
        ln = lines[i]
        values = [ln.category, ln.location, ln.area_ha, ln.right_area_ha, ln.period,
                  ln.owner, "", ln.cultivator, "", ln.note]  # 簽名蓋章兩欄一律留白
        for col, v in enumerate(values):
            _cell(row.cells[col], v, size=10.5,
                  align=WD_ALIGN_PARAGRAPH.LEFT if col == 1 else WD_ALIGN_PARAGRAPH.CENTER)

    _para(doc, "　　　　中　　華　　民　　國　　　　　　　　　　　　年"
               "　　　　　　　　　　　　月　　　　　　　　　　　　日", space_after=6)
    _para(doc, "類別：指分耕、輪耕、託耕、承租。")


def build(ag: Agreement) -> Document:
    doc = Document()
    sec = doc.sections[0]
    sec.orientation = WD_ORIENT.LANDSCAPE
    sec.page_width, sec.page_height = Cm(29.7), Cm(21.0)
    sec.left_margin = sec.right_margin = Cm(1.5)
    sec.top_margin, sec.bottom_margin = Cm(1.2), Cm(1.0)

    if ag.is_draft:
        hp = sec.header.paragraphs[0]
        hp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        _font(hp.add_run("草稿｜尚有「待確認」欄位，不得作為正式文件"), 12, bold=True,
              color=RGBColor(0xC0, 0x00, 0x00))

    pages = [ag.lines[i:i + ROWS_PER_PAGE] for i in range(0, len(ag.lines), ROWS_PER_PAGE)] or [[]]
    for n, chunk in enumerate(pages):
        if n:
            doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
        _page(doc, ag, chunk)
    return doc


if __name__ == "__main__":
    root = Path(__file__).resolve().parent.parent

    blank = root / "templates" / "土地使用同意書.docx"
    build(Agreement()).save(blank)
    print("空白範本:", blank)

    # 虛構樣本：所有姓名、證號、地號都是假的
    sample = Agreement(
        party_a="農民A",
        party_b="農民B",
        lines=[
            Line("承租", "○○縣○○鄉○○段\n0123-0004", PENDING, PENDING,
                 "116.01.01起\n118.12.31止", "農民A\nA12345****", "農民B\nB23456****"),
            Line("承租", "○○縣○○鄉○○段\n0123-0005", PENDING, PENDING,
                 "116.01.01起\n118.12.31止", "農民A\nA12345****", "農民B\nB23456****"),
            Line("承租", "○○縣○○鄉△△段\n0456-0000", PENDING, PENDING,
                 "116.01.01起\n118.12.31止", "農民A\nA12345****", "農民B\nB23456****",
                 note="持分待確認"),
        ],
    )
    out = root / "data" / "samples" / "C00_同意書_虛構樣本.docx"
    build(sample).save(out)
    print("虛構樣本:", out, "（草稿）" if sample.is_draft else "")
