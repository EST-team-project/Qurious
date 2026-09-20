"""프로젝트 계획서 Markdown 정본을 제출용 .docx 로 변환한다.

왜 스크립트인가
---------------
계획서는 작업마다 숫자가 바뀐다. Markdown 과 .docx 두 벌을 손으로 맞추면 반드시
어긋나고, 어긋난 쪽이 제출본일 때 가장 나쁘다. 그래서 **Markdown 이 정본**이고
.docx 는 여기서 다시 만든다.

무엇을 옮기고 무엇을 버리는가
-----------------------------
| 원본 | .docx |
|---|---|
| 제목 `#`~`####` | Heading 1~4 |
| 표 | Word 표 (머리행 음영) |
| 코드블록 (ASCII 그림·명령) | 고정폭 + 연회색 배경 |
| 인용 `>` | 들여쓴 회색 글 |
| 목록 `-` `1.` | 글머리/번호 목록 |
| **굵게** · `코드` · [링크](url) | 굵게 · 고정폭 · 밑줄 파랑(주소는 각주 대신 본문 뒤 괄호) |
| ```mermaid``` | ⚠️ 버린다 — Word 가 못 그린다. 대신 "그림 설명" 한 줄을 남긴다 |

사용법
------
    python scripts/build_plan_docx.py
    python scripts/build_plan_docx.py --src docs/계획서/프로젝트계획서_v1.0.md
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

try:
    from docx import Document
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Pt, RGBColor
except ImportError:  # pragma: no cover - 환경 안내
    sys.exit(
        "python-docx 가 필요합니다. 아래를 실행하세요:\n"
        "    pip install python-docx\n"
        "(requirements.txt 에도 올려 두었습니다)"
    )

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SRC = REPO_ROOT / "docs" / "계획서" / "프로젝트계획서_v1.0.md"

#: 한글이 깨지지 않게 본문 글꼴을 동아시아 글꼴까지 지정한다.
BODY_FONT = "맑은 고딕"
MONO_FONT = "D2Coding"  # 없으면 Consolas 로 대체된다 — ASCII 그림 정렬용
MONO_FALLBACK = "Consolas"

GRAY = RGBColor(0x59, 0x59, 0x59)
LINK_BLUE = RGBColor(0x1A, 0x4F, 0xBA)

#: 인라인 표기를 쪼개는 정규식. 순서가 중요하다 — 코드가 먼저다.
INLINE = re.compile(
    r"(`[^`]+`)"            # `코드`
    r"|(\*\*[^*]+\*\*)"      # **굵게**
    r"|(\[[^\]]+\]\([^)]+\))"  # [글자](주소)
    r"|(\*[^*]+\*)"          # *기울임*
    r"|(~~[^~]+~~)"          # ~~취소선~~
)


def set_cell_shading(cell, hex_color: str) -> None:
    """표 칸 배경색. python-docx 가 직접 지원하지 않아 XML 로 넣는다."""
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:fill"), hex_color)
    tc_pr.append(shd)


def set_para_shading(paragraph, hex_color: str) -> None:
    """문단 배경색 — 코드블록용."""
    p_pr = paragraph._p.get_or_add_pPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:fill"), hex_color)
    p_pr.append(shd)


def style_run(run, *, mono: bool = False, size: int | None = None) -> None:
    """글꼴을 라틴·동아시아 양쪽에 지정한다. 한쪽만 하면 한글이 다른 글꼴로 나온다."""
    name = MONO_FONT if mono else BODY_FONT
    run.font.name = name
    r_pr = run._element.get_or_add_rPr()
    r_fonts = r_pr.find(qn("w:rFonts"))
    if r_fonts is None:
        r_fonts = OxmlElement("w:rFonts")
        r_pr.append(r_fonts)
    r_fonts.set(qn("w:eastAsia"), name)
    if mono:
        # D2Coding 이 없는 PC 에서 Consolas 로 떨어지게 한다.
        r_fonts.set(qn("w:cs"), MONO_FALLBACK)
    if size:
        run.font.size = Pt(size)


def add_inline(paragraph, text: str, *, size: int | None = None) -> None:
    """**굵게** · `코드` · [링크](url) 를 해석해 run 으로 나눠 넣는다."""
    pos = 0
    for m in INLINE.finditer(text):
        if m.start() > pos:
            r = paragraph.add_run(text[pos : m.start()])
            style_run(r, size=size)
        token = m.group(0)
        if token.startswith("`"):
            r = paragraph.add_run(token[1:-1])
            style_run(r, mono=True, size=size)
        elif token.startswith("**"):
            r = paragraph.add_run(token[2:-2])
            r.bold = True
            style_run(r, size=size)
        elif token.startswith("~~"):
            r = paragraph.add_run(token[2:-2])
            r.font.strike = True
            style_run(r, size=size)
        elif token.startswith("["):
            label, url = re.match(r"\[([^\]]+)\]\(([^)]+)\)", token).groups()
            r = paragraph.add_run(label)
            r.font.color.rgb = LINK_BLUE
            r.underline = True
            style_run(r, size=size)
            # 인쇄본에서도 주소를 알 수 있게 한다. 너무 길면 생략한다.
            if not url.startswith("#") and len(url) < 90:
                r2 = paragraph.add_run(f" ({url})")
                r2.font.color.rgb = GRAY
                style_run(r2, size=(size or 10) - 2)
        elif token.startswith("*"):
            r = paragraph.add_run(token[1:-1])
            r.italic = True
            style_run(r, size=size)
        pos = m.end()
    if pos < len(text):
        r = paragraph.add_run(text[pos:])
        style_run(r, size=size)


def split_row(line: str) -> list[str]:
    """표 한 줄을 칸으로 쪼갠다. 앞뒤 파이프를 버린다."""
    return [c.strip() for c in line.strip().strip("|").split("|")]


def is_separator(line: str) -> bool:
    """표 머리행 아래 구분선인가 (`|---|:--:|`)."""
    return bool(re.fullmatch(r"\|[\s:|-]+\|", line.strip()))


def add_table(doc: Document, rows: list[list[str]]) -> None:
    width = max(len(r) for r in rows)
    table = doc.add_table(rows=len(rows), cols=width)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, row in enumerate(rows):
        for j in range(width):
            cell = table.cell(i, j)
            cell.text = ""
            para = cell.paragraphs[0]
            text = row[j] if j < len(row) else ""
            # 칸 안 줄바꿈: Markdown 의 <br> 를 진짜 줄바꿈으로
            for k, chunk in enumerate(re.split(r"<br\s*/?>", text)):
                if k:
                    para = cell.add_paragraph()
                add_inline(para, chunk, size=9)
                para.paragraph_format.space_after = Pt(0)
            if i == 0:
                set_cell_shading(cell, "E8EDF5")
                for p in cell.paragraphs:
                    for r in p.runs:
                        r.bold = True
    doc.add_paragraph()


def add_code_block(doc: Document, lines: list[str], lang: str) -> None:
    if lang == "mermaid":
        # Word 는 mermaid 를 못 그린다. 버리되 무엇이 있었는지는 남긴다.
        p = doc.add_paragraph()
        r = p.add_run("[그림] 흐름도 — 원본 Markdown 에서 볼 수 있습니다.")
        r.italic = True
        r.font.color.rgb = GRAY
        style_run(r, size=9)
        return
    for line in lines:
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.left_indent = Pt(12)
        set_para_shading(p, "F4F4F4")
        r = p.add_run(line if line else " ")
        style_run(r, mono=True, size=8.5)
    doc.add_paragraph()


def convert(src: Path, dst: Path) -> None:
    text = src.read_text(encoding="utf-8").replace("\r\n", "\n")
    lines = text.split("\n")

    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = BODY_FONT
    style.font.size = Pt(10)
    style.element.rPr.rFonts.set(qn("w:eastAsia"), BODY_FONT)

    i = 0
    stats = {"heading": 0, "table": 0, "code": 0, "para": 0}

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # --- 코드블록 ---
        if stripped.startswith("```"):
            lang = stripped[3:].strip()
            block: list[str] = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                block.append(lines[i])
                i += 1
            i += 1
            add_code_block(doc, block, lang)
            stats["code"] += 1
            continue

        # --- 표 ---
        if stripped.startswith("|") and i + 1 < len(lines) and is_separator(lines[i + 1]):
            rows = [split_row(stripped)]
            i += 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(split_row(lines[i]))
                i += 1
            add_table(doc, rows)
            stats["table"] += 1
            continue

        # --- 구분선 ---
        if stripped in ("---", "***", "___"):
            doc.add_paragraph("─" * 60).alignment = WD_ALIGN_PARAGRAPH.CENTER
            i += 1
            continue

        # --- 제목 ---
        m = re.match(r"^(#{1,4})\s+(.*)", stripped)
        if m:
            level, title = len(m.group(1)), m.group(2)
            h = doc.add_heading(level=level)
            add_inline(h, title)
            for r in h.runs:
                r.font.color.rgb = RGBColor(0x1F, 0x2A, 0x44)
            stats["heading"] += 1
            i += 1
            continue

        # --- 인용 ---
        if stripped.startswith(">"):
            body = stripped.lstrip(">").strip()
            if body:
                p = doc.add_paragraph()
                p.paragraph_format.left_indent = Pt(18)
                add_inline(p, body, size=9)
                for r in p.runs:
                    if r.font.color.rgb is None:
                        r.font.color.rgb = GRAY
            i += 1
            continue

        # --- 목록 ---
        m = re.match(r"^(\s*)([-*+]|\d+\.)\s+(.*)", line)
        if m:
            indent, marker, body = m.groups()
            style_name = "List Number" if marker[0].isdigit() else "List Bullet"
            p = doc.add_paragraph(style=style_name)
            p.paragraph_format.left_indent = Pt(18 + len(indent) * 6)
            add_inline(p, body)
            i += 1
            continue

        # --- 빈 줄 · 일반 문단 ---
        if not stripped:
            i += 1
            continue

        p = doc.add_paragraph()
        add_inline(p, re.sub(r"</?sub>", "", stripped))
        stats["para"] += 1
        i += 1

    dst.parent.mkdir(parents=True, exist_ok=True)
    doc.save(dst)
    print(f"만들었습니다: {dst}")
    print(
        f"  제목 {stats['heading']} · 표 {stats['table']} · "
        f"코드블록 {stats['code']} · 문단 {stats['para']}"
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="계획서 Markdown → .docx")
    ap.add_argument("--src", type=Path, default=DEFAULT_SRC, help="원본 .md")
    ap.add_argument("--out", type=Path, default=None, help="출력 .docx (기본: 같은 이름)")
    args = ap.parse_args()

    src = args.src if args.src.is_absolute() else REPO_ROOT / args.src
    if not src.exists():
        sys.exit(f"원본이 없습니다: {src}")
    dst = args.out or src.with_suffix(".docx")
    convert(src, dst)


if __name__ == "__main__":
    main()
