"""產生「虛構」土地登記謄本測試圖與答案檔（黑客松測試用，不具任何效力）。

用法（Windows 建議先設 PYTHONIOENCODING=utf-8）：
    python tools/make_fake_transcript.py

輸出到 data/samples/fake-transcripts/<案例>/：
    page1.png, page2.png        乾淨版（約 160 dpi、A4 直式）
    photo_page1.jpg             模擬手機翻拍（應通過品質檢查）
    photo_page1_bad.jpg         只有 C03：太暗＋模糊＋右緣被切（應不通過）
    answer.json                 標準答案（看不清的欄位標「待確認」，不猜值）

所有內容皆為虛構：範例縣、試驗鄉、範例地政事務所、農民A/B/C、遮蔽身分證號。
每頁都有斜向浮水印與頁尾聲明；不畫任何印章、簽名、條碼或 QR code。
"""
from __future__ import annotations

import json
import random
import sys
from dataclasses import dataclass, field
from pathlib import Path

try:
    from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont
except ImportError:  # pragma: no cover
    sys.exit("缺少 Pillow，請先執行：python -m pip install Pillow")

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "samples" / "fake-transcripts"

DPI = 160
PAGE_W, PAGE_H = round(8.27 * DPI), round(11.69 * DPI)  # A4 直式 1323 x 1870
MARGIN = 90

WATERMARK = "測試用虛構資料　非正式謄本"
FOOTER = "本文件為黑客松測試用虛構資料，不具任何效力"
OFFICE = "範例地政事務所（虛構）"
QUERY_DATE = "民國115年11月07日"
PENDING = "待確認"

FONT_CANDIDATES = [  # (路徑, ttc index)
    (r"C:\Windows\Fonts\mingliu.ttc", 0),
    (r"C:\Windows\Fonts\msjh.ttc", 0),
    (r"C:\Windows\Fonts\kaiu.ttf", 0),
]
BOLD_CANDIDATES = [
    (r"C:\Windows\Fonts\msjhbd.ttc", 0),
    (r"C:\Windows\Fonts\msjh.ttc", 0),
] + FONT_CANDIDATES


def _find_font(cands: list[tuple[str, int]]) -> tuple[str, int]:
    for path, idx in cands:
        if Path(path).exists():
            return path, idx
    sys.exit(
        "找不到繁體中文字型。請確認 Windows 有下列任一字型：\n  "
        + "\n  ".join(p for p, _ in FONT_CANDIDATES)
    )


_BODY = _find_font(FONT_CANDIDATES)
_BOLD = _find_font(BOLD_CANDIDATES)


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    path, idx = _BOLD if bold else _BODY
    return ImageFont.truetype(path, size, index=idx)


# ---------------------------------------------------------------- 資料模型
@dataclass
class Parcel:
    parcel_id: str
    section: str
    lot_no: str          # 一律文字，保留前導零
    area_raw: str        # 謄本上印的樣子（含千分位）
    zoning: str = "特定農業區"
    land_use: str = "農牧用地"
    reg_date: str = "民國098年07月21日"
    reg_reason: str = "地籍圖重測"
    land_value: str = "1,200"
    building_count: str = "共0棟"
    subsection: str = ""
    county: str = "範例縣"
    township: str = "試驗鄉"

    @property
    def location(self) -> str:
        return f"{self.county}{self.township}{self.section}{self.subsection}　{self.lot_no}地號"


@dataclass
class Ownership:
    parcel: Parcel
    order: str
    owner: str
    id_masked: str
    address_masked: str
    share_raw: str            # 例：全部 1分之1、2分之1
    share_num: int | str
    share_den: int | str
    reg_date: str = "民國112年05月03日"
    reg_reason: str = "買賣"
    cause_date: str = "民國112年04月20日"
    cert_no: str = "112試字第001234號"
    declared_value: str = "240.0"
    smudge: bool = False      # True：權利範圍數字被污損，答案標待確認


@dataclass
class Page:
    blocks: list            # ("land", Parcel) / ("owner", Ownership) / ("cont_from",) / ("cont_to",) / ("end",)
    sources: list = field(default_factory=list)


# ---------------------------------------------------------------- 繪圖
INK = (25, 25, 30)
GRID = (90, 90, 100)


class Canvas:
    def __init__(self) -> None:
        self.img = Image.new("RGB", (PAGE_W, PAGE_H), (252, 252, 248))
        self.d = ImageDraw.Draw(self.img)
        self.y = MARGIN
        self.f_body = font(25)
        self.f_small = font(21)
        self.f_head = font(28, bold=True)
        self.f_title = font(40, bold=True)
        self.smudge_boxes: list[tuple[int, int, int, int]] = []

    def text(self, x: int, s: str, f=None, fill=INK) -> None:
        self.d.text((x, self.y), s, font=f or self.f_body, fill=fill)

    def center(self, s: str, f) -> None:
        w = self.d.textlength(s, font=f)
        self.d.text(((PAGE_W - w) / 2, self.y), s, font=f, fill=INK)

    def section_bar(self, title: str) -> None:
        self.y += 10
        bar = f"＊＊＊＊＊＊＊＊＊＊＊　{title}　＊＊＊＊＊＊＊＊＊＊＊"
        self.center(bar, self.f_head)
        self.y += 48

    def kv_rows(self, rows: list[list[tuple[str, str]]], owner: Ownership | None = None) -> None:
        """rows：每列 1~2 組 (標籤, 值)。"""
        top = self.y - 8
        col_x = [MARGIN + 20, PAGE_W // 2 + 10]
        for row in rows:
            for i, (k, v) in enumerate(row):
                x = col_x[i] if len(row) > 1 else col_x[0]
                self.text(x, f"{k}：")
                vx = x + self.d.textlength(f"{k}：", font=self.f_body)
                self.text(int(vx), v)
                if owner is not None and owner.smudge and k == "權利範圍":
                    # 記錄數字所在位置，稍後蓋上污漬
                    start = vx + self.d.textlength(v.split("分之")[0][:-1], font=self.f_body)
                    end = vx + self.d.textlength(v.rstrip("*"), font=self.f_body)
                    self.smudge_boxes.append((int(start) - 30, self.y - 6, int(end) + 30, self.y + 34))
            self.y += 42
        self.d.rectangle((MARGIN, top, PAGE_W - MARGIN, self.y), outline=GRID, width=2)
        self.y += 18


def draw_land(c: Canvas, p: Parcel) -> None:
    c.y += 4
    c.d.rectangle((MARGIN, c.y - 8, PAGE_W - MARGIN, c.y + 44), outline=GRID, width=2, fill=(240, 240, 236))
    c.text(MARGIN + 20, f"土地坐落：{p.location}", c.f_head)
    c.y += 62
    c.section_bar("土地標示部")
    c.kv_rows([
        [("登記日期", p.reg_date), ("登記原因", p.reg_reason)],
        [("面　　積", f"******{p.area_raw}平方公尺")],
        [("使用分區", p.zoning), ("使用地類別", p.land_use)],
        [("民國115年01月　公告土地現值", f"*****{p.land_value}元／平方公尺")],
        [("地上建物建號", p.building_count)],
        [("其他登記事項", "（空白）")],
    ])


def draw_owner(c: Canvas, o: Ownership, with_bar: bool) -> None:
    if with_bar:
        c.section_bar("土地所有權部")
    c.kv_rows([
        [("（" + o.order + "）登記次序", o.order)],
        [("登記日期", o.reg_date), ("登記原因", o.reg_reason)],
        [("原因發生日期", o.cause_date)],
        [("所有權人", o.owner), ("統一編號", o.id_masked)],
        [("住　　址", o.address_masked)],
        [("權利範圍", f"{o.share_raw.replace(' ', '****')}*****")],
        [("權狀字號", o.cert_no)],
        [("當期申報地價", f"115年01月*****{o.declared_value}元／平方公尺")],
        [("其他登記事項", "（空白）")],
    ], owner=o)


def apply_smudge(img: Image.Image, boxes: list, seed: int) -> None:
    rnd = random.Random(seed)
    mask = Image.new("L", img.size, 0)
    md = ImageDraw.Draw(mask)
    for x0, y0, x1, y1 in boxes:
        for _ in range(14):
            cx = rnd.uniform(x0, x1)
            cy = rnd.uniform(y0, y1)
            rx, ry = rnd.uniform(18, 45), rnd.uniform(12, 28)
            md.ellipse((cx - rx, cy - ry, cx + rx, cy + ry), fill=rnd.randint(170, 230))
        md.rounded_rectangle((x0 + 12, y0, x1 - 12, y1), radius=14, fill=255)  # 核心區完全蓋住
    mask = mask.filter(ImageFilter.GaussianBlur(4))
    stain = Image.new("RGB", img.size, (58, 50, 44))
    img.paste(stain, (0, 0), mask)


def watermark(img: Image.Image) -> Image.Image:
    layer = Image.new("RGBA", (PAGE_W * 2, PAGE_H * 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    f = font(78, bold=True)
    w = d.textlength(WATERMARK, font=f)
    for i, yy in enumerate(range(PAGE_H // 2 - 300, PAGE_H * 3 // 2 + 300, 420)):
        x = (layer.width - w) / 2 + (i % 2) * 120 - 60
        d.text((x, yy), WATERMARK, font=f, fill=(200, 30, 30, 70))
    layer = layer.rotate(55, resample=Image.BICUBIC)
    l, t = (layer.width - PAGE_W) // 2, (layer.height - PAGE_H) // 2
    layer = layer.crop((l, t, l + PAGE_W, t + PAGE_H))
    out = img.convert("RGBA")
    out.alpha_composite(layer)
    return out.convert("RGB")


def render_page(page: Page, page_no: int, total: int, seed: int) -> Image.Image:
    c = Canvas()
    c.center("土地登記第二類謄本（所有權個人全部）", c.f_title)
    c.y += 64
    c.text(MARGIN, f"查詢日期：{QUERY_DATE}")
    rt = f"頁次：第{page_no}頁／共{total}頁"
    c.d.text((PAGE_W - MARGIN - c.d.textlength(rt, font=c.f_body), c.y), rt, font=c.f_body, fill=INK)
    c.y += 38
    c.text(MARGIN, f"資料管轄機關：{OFFICE}")
    c.y += 38
    c.text(MARGIN, "第二類謄本：所有權人以外之統一編號及住址已依規定遮蔽（本頁為虛構示範）", c.f_small)
    c.y += 44
    c.d.line((MARGIN, c.y, PAGE_W - MARGIN, c.y), fill=INK, width=3)
    c.y += 20

    prev_owner = False
    for blk in page.blocks:
        kind = blk[0]
        if kind == "land":
            draw_land(c, blk[1])
            prev_owner = False
        elif kind == "owner":
            draw_owner(c, blk[1], with_bar=not prev_owner)
            prev_owner = True
        elif kind == "cont_from":
            c.center("（接前頁）", c.f_body)
            c.y += 40
            c.section_bar("土地所有權部（續）")
            prev_owner = True
        elif kind == "cont_to":
            c.center("（續次頁）", c.f_body)
            c.y += 40
        elif kind == "end":
            c.center("（本謄本列印完畢）　以下空白", c.f_body)
            c.y += 40

    if c.smudge_boxes:
        apply_smudge(c.img, c.smudge_boxes, seed)

    fy = PAGE_H - MARGIN - 10
    c.d.line((MARGIN, fy - 16, PAGE_W - MARGIN, fy - 16), fill=GRID, width=1)
    c.y = fy
    c.center(FOOTER, c.f_head)
    return watermark(c.img)


# ---------------------------------------------------------------- 翻拍模擬
def _perspective_coeffs(dst: list, src: list) -> list[float]:
    """回傳 PIL PERSPECTIVE 係數：把輸出座標 dst 對應到輸入座標 src。"""
    a, b = [], []
    for (x, y), (u, v) in zip(dst, src):
        a.append([x, y, 1, 0, 0, 0, -u * x, -u * y]); b.append(u)
        a.append([0, 0, 0, x, y, 1, -v * x, -v * y]); b.append(v)
    n = 8  # 高斯消去
    m = [row[:] + [bb] for row, bb in zip(a, b)]
    for i in range(n):
        p = max(range(i, n), key=lambda r: abs(m[r][i]))
        m[i], m[p] = m[p], m[i]
        for r in range(n):
            if r != i:
                f = m[r][i] / m[i][i]
                m[r] = [x - f * y for x, y in zip(m[r], m[i])]
    return [m[i][n] / m[i][i] for i in range(n)]


def phone_photo(page: Image.Image, seed: int, bad: bool = False) -> Image.Image:
    rnd = random.Random(seed)
    cw, ch = 1500, 2000
    bg = Image.new("RGB", (cw, ch), (118, 96, 74))  # 木桌色
    noise = Image.effect_noise((cw, ch), 18).convert("RGB")
    bg = Image.blend(bg, noise, 0.12)

    s = 0.86 * min(cw / PAGE_W, ch / PAGE_H)
    w, h = PAGE_W * s, PAGE_H * s
    ox, oy = (cw - w) / 2, (ch - h) / 2
    if bad:
        ox += 0.17 * w  # 右緣超出畫面
    j = lambda k: rnd.uniform(-k, k)
    dst = [  # 左上、右上、右下、左下：上窄下寬＋微旋轉
        (ox + 28 + j(6), oy + 10 + j(6)),
        (ox + w - 22 + j(6), oy - 18 + j(6)),
        (ox + w + 14 + j(6), oy + h + 12 + j(6)),
        (ox - 16 + j(6), oy + h - 14 + j(6)),
    ]
    src = [(0, 0), (PAGE_W, 0), (PAGE_W, PAGE_H), (0, PAGE_H)]
    coeffs = _perspective_coeffs(dst, src)
    warped = page.transform((cw, ch), Image.PERSPECTIVE, coeffs, Image.BICUBIC)
    mask = Image.new("L", page.size, 255).transform((cw, ch), Image.PERSPECTIVE, coeffs, Image.BICUBIC)
    # 紙張陰影
    shadow = Image.new("L", (cw, ch), 0)
    shadow.paste(mask, (14, 18))
    shadow = shadow.filter(ImageFilter.GaussianBlur(14))
    bg.paste((60, 48, 36), (0, 0), shadow.point(lambda v: v * 0.6))
    bg.paste(warped, (0, 0), mask)

    # 不均勻光線：左上亮、右下暗，再加一塊手機/手的柔和陰影
    vert = Image.linear_gradient("L").resize((cw, ch), Image.BICUBIC)
    horiz = vert.transpose(Image.Transpose.TRANSPOSE).resize((cw, ch), Image.BICUBIC)
    light = Image.blend(vert, horiz, 0.5).point(lambda v: int(255 - v * 0.32))
    blob = Image.new("L", (cw, ch), 0)
    ImageDraw.Draw(blob).ellipse((cw * 0.55, ch * 0.70, cw * 1.25, ch * 1.20), fill=80)
    blob = blob.filter(ImageFilter.GaussianBlur(120))
    out = Image.composite(Image.new("RGB", (cw, ch), 0), bg, blob)
    out = ImageChops.multiply(out, Image.merge("RGB", (light,) * 3))

    if bad:
        out = out.point(lambda v: int(v * 0.30))     # 太暗
        out = out.filter(ImageFilter.GaussianBlur(5))  # 嚴重模糊
    else:
        out = out.filter(ImageFilter.GaussianBlur(1.0))
    grain = Image.effect_noise((cw, ch), 10).convert("RGB")
    out = Image.blend(out, grain, 0.04 if not bad else 0.08)
    return out


# ---------------------------------------------------------------- 案例
def case_c01():
    p1 = Parcel("P1", "示範段", "0123-0004", "1,234.56")
    p2 = Parcel("P2", "示範段", "0123-0005", "2,345.67", reg_date="民國101年10月02日", reg_reason="分割")
    addr = "範例縣試驗鄉○○村○○路**號"
    o1 = Ownership(p1, "0001", "農民A", "A12345****", addr, "全部 1分之1", 1, 1)
    o2 = Ownership(p2, "0001", "農民A", "A12345****", addr, "全部 1分之1", 1, 1,
                   cert_no="112試字第001235號")
    pages = [Page([("land", p1), ("owner", o1)]), Page([("land", p2), ("owner", o2), ("end",)])]
    src = {"P1": "page1.png", "P2": "page2.png"}
    return "C01", "正常：1 位所有權人、2 筆土地", [p1, p2], [(o1, "page1.png"), (o2, "page2.png")], src, pages, []


def case_c02():
    p1 = Parcel("P1", "測試段", "0456-0000", "3,210.00", subsection="北小段", zoning="一般農業區")
    oa = Ownership(p1, "0001", "農民A", "A12345****", "範例縣試驗鄉○○村○○路**號",
                   "2分之1", 1, 2, reg_reason="繼承", cause_date="民國111年12月01日", cert_no="112試字第002001號")
    ob = Ownership(p1, "0002", "農民B", "B23456****", "範例縣試驗鄉△△村△△街**號",
                   "2分之1", 1, 2, reg_reason="繼承", cause_date="民國111年12月01日", cert_no="112試字第002002號")
    pages = [Page([("land", p1), ("owner", oa), ("cont_to",)]),
             Page([("cont_from",), ("owner", ob), ("end",)])]
    return "C02", "共有：1 筆土地由農民A、農民B 各持分 2分之1", [p1], [(oa, "page1.png"), (ob, "page2.png")], {"P1": "page1.png"}, pages, []


def case_c03():
    p1 = Parcel("P1", "示範段", "0005-0001", "1,000.05")
    p2 = Parcel("P2", "示範一段", "0005-0001", "2,499.95", reg_date="民國103年02月14日", reg_reason="合併")
    addr = "範例縣試驗鄉□□村□□巷**號"
    o1 = Ownership(p1, "0001", "農民C", "C34567****", addr, "全部 1分之1", 1, 1, cert_no="113試字第000077號",
                   reg_date="民國113年01月09日", reg_reason="贈與", cause_date="民國112年12月25日")
    o2 = Ownership(p2, "0001", "農民C", "C34567****", addr, "3分之1", PENDING, PENDING, cert_no="113試字第000078號",
                   reg_date="民國113年01月09日", reg_reason="贈與", cause_date="民國112年12月25日", smudge=True)
    pages = [Page([("land", p1), ("owner", o1)]), Page([("land", p2), ("owner", o2), ("end",)])]
    pending = [{
        "field": "權利範圍", "parcel_id": "P2", "section": "示範一段", "lot_no": "0005-0001",
        "source": {"file": "page2.png", "page": 2},
        "note": "污損無法辨識：權利範圍的分子與分母被污漬蓋住，不得猜值，需協助者對照原件或重新申請謄本",
    }]
    return ("C03", "易錯：前導零地號、相同地號但段名相似（示範段/示範一段）、面積接近進位邊界、權利範圍污損",
            [p1, p2], [(o1, "page1.png"), (o2, "page2.png")], {"P1": "page1.png", "P2": "page2.png"}, pages, pending)


def build(case_fn, seed: int) -> None:
    case_id, desc, parcels, owns, parcel_src, pages, pending = case_fn()
    d = OUT_DIR / case_id
    d.mkdir(parents=True, exist_ok=True)
    imgs = []
    for i, pg in enumerate(pages, 1):
        im = render_page(pg, i, len(pages), seed + i)
        im.save(d / f"page{i}.png", dpi=(DPI, DPI), optimize=True)
        imgs.append(im)
    phone_photo(imgs[0], seed).save(d / "photo_page1.jpg", quality=72)
    quality = {"page1.png": "pass", "page2.png": "pass", "photo_page1.jpg": "pass"}
    quality_notes = {}
    if case_id == "C03":
        phone_photo(imgs[0], seed + 99, bad=True).save(d / "photo_page1_bad.jpg", quality=55)
        quality["photo_page1_bad.jpg"] = "fail"
        quality_notes["photo_page1_bad.jpg"] = "太暗、嚴重模糊、右側約 1/6 頁面超出畫面；應請農民重拍"

    def page_of(f: str) -> int:
        return int(f.removeprefix("page").removesuffix(".png"))

    answer = {
        "case_id": case_id,
        "fictional": True,
        "notice": FOOTER,
        "description": desc,
        "parcels": [{
            "parcel_id": p.parcel_id, "county": p.county, "township": p.township,
            "section": p.section, "subsection": p.subsection, "lot_no": p.lot_no,
            "area_raw": p.area_raw, "area_unit": "平方公尺", "area_m2": p.area_raw.replace(",", ""),
            "zoning": p.zoning, "land_use": p.land_use,
            "source": {"file": parcel_src[p.parcel_id], "page": page_of(parcel_src[p.parcel_id])},
        } for p in parcels],
        "ownerships": [{
            "parcel_id": o.parcel.parcel_id, "section": o.parcel.section, "lot_no": o.parcel.lot_no,
            "reg_order": o.order, "owner": o.owner, "id_masked": o.id_masked,
            "address_masked": o.address_masked,
            "share_raw": PENDING if o.smudge else o.share_raw,
            "share_num": o.share_num, "share_den": o.share_den,
            "source": {"file": f, "page": page_of(f)},
        } for o, f in owns],
        "pending": pending,
        "expected_quality": quality,
    }
    if quality_notes:
        answer["expected_quality_notes"] = quality_notes
    (d / "answer.json").write_text(json.dumps(answer, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{case_id}: {d.relative_to(ROOT)}  ({len(pages)} 頁)")


def main() -> None:
    for seed, fn in ((101, case_c01), (202, case_c02), (303, case_c03)):
        build(fn, seed)


if __name__ == "__main__":
    main()
