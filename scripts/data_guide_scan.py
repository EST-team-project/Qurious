"""자료 안내 설명 생성물 — 대장(TSV) 넷 → `app/services/data_guide.json` (2026-10-08 · 「자료 안내」 화면 1단계).

왜 이 파일이 있는가
-------------------
「데이터 › 자료 안내」 화면은 우리가 모으는 자료가 무엇이고 · 어떻게 모으고 · 무엇을 읽으면 되는지를 보인다. 그 설명
(쉬운 이름 · 한 줄 · 출처 · 이용 조건 · 흐름 · 길잡이 · 틀리기 쉬운 것)을 화면 파일이나 앱 코드에 손으로 적으면 데이터 관제 ·
백업 카드 · 문서와 어긋나는 다섯째 사본이 된다(설계 03 문서 13절 ④ — 손으로 옮긴 숫자 · 글이 이미 다섯 곳에서 어긋났다).
그래서 정본 · 생성물 · 앱을 나눈다(2026-10-08 결정 ④ · SSoT).

  정본    docs/데이터/대장/자료안내-자료.tsv · 자료안내-출처.tsv · 자료안내-길잡이.tsv · 자료안내-뺀표.tsv (사람이 고친다)
  생성물  app/services/data_guide.json — 이 스캐너가 만든다 · git 에 들어가고 앱 이미지에 함께 실린다
  앱      생성물을 읽기만 한다(GET /api/data/guide) — 앱 이미지에는 docs/ · scripts/ 가 없다(Dockerfile)

같은 꼴의 선례 — API 문서 카탈로그(`api_scan.py --catalog` → public/api-docs/catalog.json · TC-AD) · 용어 파일(terms.json).

    python scripts/data_guide_scan.py            # 요약 + 대장 점검(모르는 열쇠 · 쉬운 칸의 개발 말 · 안내에 없는 수집 표)
    python scripts/data_guide_scan.py --write    # 생성물을 다시 쓴다 — 점검에 걸리면 쓰지 않는다(종료코드 1)
    python scripts/data_guide_scan.py --check    # 생성물이 대장과 같은지만 — 다르면 종료코드 1(줄 끝은 접어서 견준다)

숫자는 여기 없다
---------------
줄 수 · 기간 · 연도별은 날마다 바뀌므로 생성물에 넣지 않는다 — 바뀌는 칸(시각 · 숫자)이 없어 대장이 같으면 바이트까지 같다.
앱이 요청 때 상태(`data_status`)와 백업 매니페스트 두 장에서 잰다. **이 스캐너는 수집 DB 를 열지 않는다** — 수집 표 목록도
표 속성 대장(DB = 수집)에서 읽는다(앱이 읽기 전용으로 붙인 WAL DB 를 다른 프로세스가 열면 앱이 멈출 수 있다 · DF-81).

왜 표 속성 대장에 칸 둘(쉬운 이름 · 읽는 길)을 더하지 않고 새 대장으로 나눴나 (2026-10-08)
---------------------------------------------------------------------------------------
설계(03 문서 8.2절)는 「표 속성 대장에 칸 둘을 더한다」 였다. `scripts/schema_scan.py` 는 대장을 머리글 이름으로 읽어
(csv.DictReader) 데이터 사전 · ERD 의 표시 칸은 그대로였겠지만, 세 가지가 걸렸다.
  1. 머리 줄을 순서까지 고정해 견준다 — `표속성_대조` 가 「머리 줄이 정한 칸과 다르다」 를 알리고, 시험 `test_ss08` 이
     실제 대장의 머리 줄 = `표속성_칸` 을 건다 → 칸을 더하면 남의 시험이 깨지고 스캐너까지 고쳐야 한다.
     `--json` 출력도 대장 줄 전체를 싣는다(생성물이 바뀐다).
  2. 단위가 다르다 — 안내의 「자료」 는 표와 1 대 1 이 아니다(분봉 한 표 → 60분봉 · 5분봉 / 뉴스 한 표 → 정책뉴스 ·
     언론사 기사 / 주봉은 표가 없다 / 용어사전은 앱 DB 의 표 여섯). 표 속성 대장은 테이블정의서(표 한 줄)이고
     자료 안내는 화면에 보일 자료 한 줄이다 — 한 파일이 두 단위를 맡으면 SRP 가 깨진다.
  3. 공용 대장의 칸 수를 늘리면 앱 표 마흔여 줄에도 빈 칸이 생긴다(`빈_칸` 점검이 칸마다 값을 요구한다).
그래서 자료 대장은 표 이름(`개발_표` 칸)으로 표 속성 대장에 **잇기만** 한다 — 한글명 · 공개 같은 표 단위 속성은 표 속성 대장
한 곳에 남고(SSoT), 이 스캐너는 잇는 표 이름이 그 대장에 있는지 대조한다(참조 무결성).

한계 — 이 스캐너가 판정하지 않는 것
------------------------------------
- 글이 **사실인지**는 보지 않는다. 쉬운 칸에 개발 말이 섞였는지 · 열쇠가 이어지는지만 본다.
- 숫자 열쇠(`숫자_상태`)가 상태 응답에 실제로 있는지는 앱 코드를 import 하지 않는 이 스캐너가 모른다 — 시험(TC-DG)이 맞댄다.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEDGER_DIR = ROOT / "docs" / "데이터" / "대장"
ATTR_LEDGER = LEDGER_DIR / "표-속성대장.tsv"
APP_HTML = ROOT / "public" / "app.html"
OUT = ROOT / "app" / "services" / "data_guide.json"
SCHEMA = 1
SOURCE_TAG = "scripts/data_guide_scan.py --write"

#: 대장 넷 — 파일 이름과 머리 줄(순서까지 이대로다 · 바꾸면 점검이 알린다).
#: 칸 이름 앞의 「개발_」 은 관리자에게만 싣는 칸, 「숫자_」 은 앱이 숫자를 잇는 데만 쓰는 칸(응답에 싣지 않는다).
#: 「읽는길」 = 화면이 없을 때(또는 관리자 화면뿐일 때) 어디서 읽나 — 쉬운 말(「백업 파일」 처럼). 「화면 없음 · 백업 파일」 로 보인다.
ITEM_COLS = ("자료", "묶음", "쉬운이름", "한줄", "범위", "갱신", "출처", "모으는법", "다듬기", "쓰는곳", "쓰지말곳",
             "화면", "읽는길", "이용조건", "숫자주의", "바둑판", "개발_표", "개발_키", "개발_읽는길", "개발_백업", "개발_명령",
             "숫자_상태", "숫자_백업")
SOURCE_COLS = ("출처", "이름", "곳", "종류", "표시", "이용조건", "공개")
GUIDE_COLS = ("종류", "열쇠", "제목", "설명", "자료", "화면", "관리자")
EXCL_COLS = ("표", "까닭")
LEDGERS = {
    "자료": ("자료안내-자료.tsv", ITEM_COLS),
    "출처": ("자료안내-출처.tsv", SOURCE_COLS),
    "길잡이": ("자료안내-길잡이.tsv", GUIDE_COLS),
    "뺀표": ("자료안내-뺀표.tsv", EXCL_COLS),
}

#: 출처의 「종류」 — 바깥 = 밖에서 받는 곳(화면의 「출처 N곳」 은 이것만 센다) · 계산 = 우리가 계산 · 팀 = 팀이 모은 글 · 기록 = 작업 기록
SOURCE_KINDS = ("바깥", "계산", "팀", "기록")
#: 길잡이 대장의 「종류」 — 흐름 = 흐름 그림의 상자(열쇠 = 매일 낮 수집의 단계 묶음 이름 · 출처 상자는 「출처」) ·
#: 흐름덧말 = 흐름 아래 한 줄 · 길잡이 = 하려는 일 → 읽을 자료 → 어디서 · 주의 = 틀리기 쉬운 것
GUIDE_KINDS = ("흐름", "흐름덧말", "길잡이", "주의")
#: 백업 매니페스트 줄 열쇠 — hf:<표>(krx-daily-market 연도 파일) · ohlcv:<주기>[/<가격>[/<시장>+<시장>]](krx-ohlcv)
OHLCV_TF = ("1d", "1w", "60m", "5m")
OHLCV_BASIS = ("raw", "adj_base", "adj_split")
OHLCV_MARKETS = ("KOSPI", "KOSDAQ", "KONEX", "ETF", "INDEX")

#: 화면 본문(쉬운 칸)에 쓰지 않는 말 — UI 명세서 5.1 「화면 글」 · 설계 03 문서 9절 「화면에 쓰지 않는 말」 · 결정 ②.
#: 영문 낱말은 영문 · 숫자 · 밑줄에 붙지 않을 때만 잡는다(한글에 붙은 영문도 잡힌다 — 파이썬 \b 는 한글을 낱말 글자로 본다).
PLAIN_BANNED = (
    (r"/api/", "API 경로"),
    (r"(?<![A-Za-z0-9_])API-[A-Z]+-\d+", "API ID"),
    (r"(?i)(?<![A-Za-z0-9_])python(?![A-Za-z0-9_])", "명령"),
    (r"(?<![A-Za-z0-9_])collector(?![A-Za-z0-9_])|scripts/", "코드 경로"),
    (r"(?i)\.sqlite3?|(?<![A-Za-z0-9_])sqlite(?![A-Za-z0-9_])", "DB 파일"),
    (r"(?<![A-Za-z0-9_])DB(?![A-Za-z0-9_])", "DB 이름"),
    (r"(?i)hugging ?face|(?<![A-Za-z0-9_])HF(?![A-Za-z0-9_])", "백업 서비스 이름"),
    (r"(?i)파케이|parquet", "파일 형식"),
    (r"(?i)매니페스트|manifest", "개발 말"),
    (r"러너|스캐너|커밋", "작업 말"),
    (r"(?<!공유 )저장소", "「팀 공유 저장소」 밖의 저장소"),
    (r"팀원|정할 것|예시 값", "개발 티"),
    (r"krx-daily-market|krx-ohlcv|dart-disclosure-financials|kb-legal-base|kb-sector-laws|search-index|qurious-quant",
     "백업 이름"),
)
#: 대장마다 화면 본문에 나가는 칸(쉬운 칸) — 이 칸들만 위의 말을 막는다(개발_ · 관리자 칸은 관리자에게만 간다)
PLAIN_COLS = {
    "자료": ("쉬운이름", "한줄", "범위", "갱신", "모으는법", "다듬기", "쓰는곳", "쓰지말곳", "읽는길", "이용조건", "숫자주의", "바둑판"),
    "출처": ("이름", "곳", "표시", "이용조건", "공개"),
    "길잡이": ("제목", "설명"),
}

VIEW_RE = re.compile(r'<div class="view" data-view="([^"]+)">')
KEY_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


# ── 읽기 ──────────────────────────────────────────────────────────────────
def read_tsv(path: Path, cols: tuple[str, ...], problems: list[str]) -> list[dict[str, str]]:
    """대장 하나를 줄 목록으로. 없거나 머리 줄이 다르면 까닭을 남기고 빈 목록 — 멈추지 않고 모든 까닭을 한 번에 보인다."""
    if not path.exists():
        problems.append(f"대장이 없다: {path.name}")
        return []
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        head = list(reader.fieldnames or [])
        rows = [{k: (v or "").strip() for k, v in r.items() if k is not None} for r in reader]
    if head != list(cols):
        problems.append(f"{path.name} 머리 줄이 정한 칸과 다르다 — 지금 「{' · '.join(head)}」 · 정한 칸 「{' · '.join(cols)}」")
        return []
    return [r for r in rows if any(r.values())]          # 빈 줄은 건너뛴다


def read_attr(path: Path = ATTR_LEDGER) -> list[dict[str, str]]:
    """표 속성 대장(표 단위 속성의 정본) — 표 이름 · DB 칸만 쓴다. 없으면 빈 목록."""
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return [{k: (v or "").strip() for k, v in r.items() if k is not None} for r in csv.DictReader(f, delimiter="\t")]


def collector_tables(attr: list[dict[str, str]]) -> set[str]:
    """수집 쪽 표(수집 DB · 근거 문서 · 섹터 법령 · 검색 색인 파일) — 표 속성 대장의 DB = 수집 줄."""
    return {r["표"] for r in attr if r.get("DB") == "수집" and r.get("표")}


def screen_views(app_html: Path = APP_HTML) -> set[str] | None:
    """화면 키 — app.html 의 view 뿌리(화면 스캐너 view_scan 과 같은 규칙). 파일이 없으면 None(대조하지 않는다)."""
    if not app_html.exists():
        return None
    return set(VIEW_RE.findall(app_html.read_text(encoding="utf-8")))


def split(value: str) -> list[str]:
    """「 · 」 로 이은 여러 값 → 목록(빈 값 없음 · 차례 그대로)."""
    return [x.strip() for x in value.split("·") if x.strip()]


def dev_words(text: str, tables: set[str]) -> list[str]:
    """쉬운 칸의 글에 섞인 개발 말 — 찾은 말의 종류. 표 이름은 영문 · 숫자 · 밑줄에 붙지 않은 것만 잡는다."""
    found = [label for pat, label in PLAIN_BANNED if re.search(pat, text)]
    found += [f"표 이름 {t}" for t in sorted(tables) if re.search(rf"(?<![A-Za-z0-9_]){re.escape(t)}(?![A-Za-z0-9_])", text)]
    return found


def backup_spec_problem(spec: str, collector: set[str]) -> str | None:
    """숫자_백업 열쇠의 꼴 — 틀리면 까닭(앱은 모르는 열쇠를 숫자 없음으로 둔다 · 여기서 먼저 막는다)."""
    kind, _, rest = spec.partition(":")
    if kind == "hf":
        return None if rest in collector else f"hf:{rest} — 표 속성 대장의 수집 표가 아니다"
    if kind == "ohlcv":
        parts = rest.split("/")
        if not parts[0] or parts[0] not in OHLCV_TF:
            return f"{spec} — 주기는 {' · '.join(OHLCV_TF)} 가운데 하나"
        if len(parts) > 1 and parts[1] not in OHLCV_BASIS:
            return f"{spec} — 가격은 {' · '.join(OHLCV_BASIS)} 가운데 하나"
        if len(parts) > 2 and not set(parts[2].split("+")) <= set(OHLCV_MARKETS):
            return f"{spec} — 시장은 {' · '.join(OHLCV_MARKETS)} 를 + 로 잇는다"
        if len(parts) > 3:
            return f"{spec} — 칸이 너무 많다(주기/가격/시장)"
        return None
    return f"{spec} — hf: 나 ohlcv: 로 시작해야 한다"


# ── 만들기 ────────────────────────────────────────────────────────────────
def build(ledger_dir: Path = LEDGER_DIR, attr_path: Path = ATTR_LEDGER,
          app_html: Path = APP_HTML) -> tuple[dict, list[str]]:
    """대장 넷 → 생성물 dict 와 점검 까닭 목록. 까닭이 하나라도 있으면 생성물을 쓰지 않는다(말없이 빠지는 줄이 없게)."""
    problems: list[str] = []
    led = {name: read_tsv(ledger_dir / fname, cols, problems) for name, (fname, cols) in LEDGERS.items()}
    attr = read_attr(attr_path)
    if not attr:
        problems.append(f"표 속성 대장이 없다: {attr_path.name} — 표 이름을 대조할 수 없다")
    all_tables = {r["표"] for r in attr if r.get("표")}
    collector = collector_tables(attr)
    views = screen_views(app_html)

    # 쉬운 칸의 개발 말 — 화면 본문에 표 이름 · API 경로 · 명령이 나가지 않게(결정 ②)
    for name, cols in PLAIN_COLS.items():
        for row in led[name]:
            who = row.get("자료") or row.get("출처") or f"{row.get('종류', '')} {row.get('제목') or row.get('열쇠') or ''}".strip()
            for col in cols:
                for word in dev_words(row.get(col, ""), all_tables):
                    problems.append(f"{LEDGERS[name][0]} {who}.{col} — 쉬운 칸에 {word}")

    # 출처
    sources: list[dict] = []
    for r in led["출처"]:
        if not KEY_RE.match(r["출처"]):
            problems.append(f"출처 열쇠 「{r['출처']}」 — 영문 소문자 · 숫자 · - 만")
        if r["종류"] not in SOURCE_KINDS:
            problems.append(f"출처 {r['출처']}.종류 「{r['종류']}」 — {' · '.join(SOURCE_KINDS)} 가운데 하나")
        for col in ("이름", "곳", "표시", "이용조건", "공개"):
            if not r[col]:
                problems.append(f"출처 {r['출처']}.{col} 이 비었다")
        sources.append({"key": r["출처"], "name": r["이름"], "org": r["곳"], "kind": r["종류"], "tag": r["표시"],
                        "terms": r["이용조건"], "release": r["공개"]})
    src_keys = [s["key"] for s in sources]
    for k in sorted({k for k in src_keys if src_keys.count(k) > 1}):
        problems.append(f"출처 「{k}」 가 두 번 적혔다")
    by_src = {s["key"]: s for s in sources}

    # 자료
    items: list[dict] = []
    for r in led["자료"]:
        key = r["자료"]
        if not KEY_RE.match(key):
            problems.append(f"자료 열쇠 「{key}」 — 영문 소문자 · 숫자 · - 만")
        # 열쇠는 일반 사용자 응답에도 나간다 — 표 이름 그대로는 물론 「-」 로 나눈 조각에도 표 이름이 없어야 한다
        # (dividend-notice 의 dividend 가 TC-DG-03 에 걸렸다 · 2026-10-08)
        if key.replace("-", "_") in all_tables or set(key.split("-")) & all_tables:
            problems.append(f"자료 열쇠 「{key}」 에 표 이름이 들어 있다 — 열쇠는 일반 사용자 응답에도 나가므로 표 이름을 쓰지 않는다")
        for col in ("묶음", "쉬운이름", "한줄", "범위", "갱신", "출처", "모으는법", "쓰는곳"):
            if not r[col]:
                problems.append(f"자료 {key}.{col} 이 비었다")
        src = split(r["출처"])
        for s in src:
            if s not in by_src:
                problems.append(f"자료 {key}.출처 「{s}」 — 출처 대장에 없다")
        item_views = split(r["화면"])
        if views is not None:
            for v in item_views:
                if v not in views:
                    problems.append(f"자료 {key}.화면 「{v}」 — app.html 에 그런 화면이 없다")
        tables = split(r["개발_표"])
        for t in tables:
            if t not in all_tables:
                problems.append(f"자료 {key}.개발_표 「{t}」 — 표 속성 대장에 없다")
        spec = r["숫자_백업"]
        if spec and (why := backup_spec_problem(spec, collector)):
            problems.append(f"자료 {key}.숫자_백업 {why}")
        if r["바둑판"] and not spec:
            problems.append(f"자료 {key}.바둑판 — 연도별 줄 수를 읽을 숫자_백업 열쇠가 없다")
        # 이용 조건 표시 — 자료 칸이 비면 출처의 표시를 잇는다(출처 대장 한 곳 · 계산한 자료처럼 자료가 다를 때만 자료 칸에 쓴다)
        tag = r["이용조건"] or " · ".join(dict.fromkeys(by_src[s]["tag"] for s in src if s in by_src))
        items.append({
            "key": key, "group": r["묶음"], "name": r["쉬운이름"], "line": r["한줄"], "scope": r["범위"],
            "update": r["갱신"], "sources": src, "tag": tag, "how": r["모으는법"], "processing": r["다듬기"],
            "uses": r["쓰는곳"], "avoid": r["쓰지말곳"], "views": item_views, "read_hint": r["읽는길"], "note": r["숫자주의"],
            "grid": r["바둑판"],
            "dev": {"tables": tables, "keys": r["개발_키"], "read": r["개발_읽는길"], "backup": r["개발_백업"],
                    "command": r["개발_명령"]},
            "stats_from": {"status": split(r["숫자_상태"]), "backup": spec},
        })
    keys = [it["key"] for it in items]
    for k in sorted({k for k in keys if keys.count(k) > 1}):
        problems.append(f"자료 「{k}」 가 두 번 적혔다")
    item_keys = set(keys)
    used_src = {s for it in items for s in it["sources"]}
    for s in src_keys:
        if s not in used_src:
            problems.append(f"출처 「{s}」 를 쓰는 자료가 없다 — 지우거나 자료에 잇는다")
    status_keys = [k for it in items for k in it["stats_from"]["status"]]
    for k in sorted({k for k in status_keys if status_keys.count(k) > 1}):
        problems.append(f"숫자_상태 「{k}」 를 두 자료가 쓴다 — 모은 줄 합이 두 번 센다")

    # 묶음 — 자료 대장에 처음 나온 차례(표 속성 대장의 업무 영역과 같은 규칙)
    groups: list[dict] = []
    for it in items:
        g = next((x for x in groups if x["key"] == it["group"]), None)
        if g is None:
            groups.append({"key": it["group"], "name": it["group"], "items": 1})
        else:
            g["items"] += 1

    # 길잡이 대장 — 흐름 · 흐름덧말 · 길잡이 · 주의
    flow, flow_notes, tasks, pitfalls = [], [], [], []
    for r in led["길잡이"]:
        kind = r["종류"]
        who = f"{kind} {r['제목'] or r['열쇠'] or r['설명'][:12]}"
        if kind not in GUIDE_KINDS:
            problems.append(f"길잡이 「{who}」.종류 — {' · '.join(GUIDE_KINDS)} 가운데 하나")
            continue
        refs = split(r["자료"])
        for k in refs:
            if k not in item_keys:
                problems.append(f"길잡이 「{who}」.자료 「{k}」 — 자료 대장에 없다")
        vws = split(r["화면"])
        if views is not None:
            for v in vws:
                if v not in views:
                    problems.append(f"길잡이 「{who}」.화면 「{v}」 — app.html 에 그런 화면이 없다")
        if kind == "흐름":
            if not r["열쇠"] or not r["제목"]:
                problems.append(f"길잡이 「{who}」 — 흐름 상자는 열쇠 · 제목이 있어야 한다")
            flow.append({"key": r["열쇠"], "title": r["제목"], "text": r["설명"], "items": refs, "dev": r["관리자"]})
        elif kind == "흐름덧말":
            if not r["설명"]:
                problems.append(f"길잡이 「{who}」 — 흐름 덧말은 설명이 있어야 한다")
            flow_notes.append({"key": r["열쇠"], "text": r["설명"], "items": refs})
        elif kind == "길잡이":
            if not r["제목"] or not refs or not vws:
                problems.append(f"길잡이 「{who}」 — 하려는 일 · 읽을 자료 · 어디서가 모두 있어야 한다")
            tasks.append({"title": r["제목"], "text": r["설명"], "items": refs, "views": vws, "dev": r["관리자"]})
        else:
            if not r["제목"] or not r["설명"]:
                problems.append(f"길잡이 「{who}」 — 주의는 제목 · 설명이 있어야 한다")
            pitfalls.append({"title": r["제목"], "text": r["설명"], "items": refs})
    fkeys = [f["key"] for f in flow]
    for k in sorted({k for k in fkeys if fkeys.count(k) > 1}):
        problems.append(f"흐름 상자 「{k}」 가 두 번 적혔다")

    # 안내에서 뺀 표 — 까닭이 있어야 하고, 안내에 있는 표를 빼지 않는다
    covered = {t for it in items for t in it["dev"]["tables"]}
    excluded: list[dict] = []
    for r in led["뺀표"]:
        if r["표"] not in all_tables:
            problems.append(f"뺀표 「{r['표']}」 — 표 속성 대장에 없다")
        if not r["까닭"]:
            problems.append(f"뺀표 「{r['표']}」 — 까닭이 비었다")
        if r["표"] in covered:
            problems.append(f"뺀표 「{r['표']}」 — 안내의 자료가 이미 쓰는 표다")
        excluded.append({"table": r["표"], "why": r["까닭"]})

    guide = {"schema": SCHEMA, "source": SOURCE_TAG, "groups": groups, "sources": sources, "items": items,
             "flow": flow, "flow_notes": flow_notes, "tasks": tasks, "pitfalls": pitfalls, "excluded": excluded}
    return guide, problems


def coverage(guide: dict, tables: set[str]) -> dict[str, list[str]]:
    """수집 표가 안내에 빠짐없이 있나 — 자료가 쓰거나(개발_표) 뺀 까닭이 있어야 한다(백업의 TC-HF-01 과 같은 꼴).

    표 목록은 DB 를 열지 않고 받는다(표 속성 대장 · 백업 도구의 TABLES · EXCLUDED). 점검은 요약에 ⚠️ 로만 알리고
    생성물 쓰기를 막지 않는다 — 막는 것은 시험(TC-DG-02)이다(표를 더한 날 다른 설명까지 못 고치는 일이 없게)."""
    covered = {t for it in guide["items"] for t in it["dev"]["tables"]}
    excluded = {e["table"]: e["why"] for e in guide["excluded"]}
    return {
        "빠진_표": sorted(set(tables) - covered - set(excluded)),
        "까닭_없는_뺀_표": sorted(t for t, why in excluded.items() if not why.strip()),
        "안내와_뺀_표에_모두": sorted(covered & set(excluded)),
    }


def dumps(guide: dict) -> str:
    """생성물 글 — 같은 대장이면 같은 바이트(키 차례 고정 · 시각 칸 없음)."""
    return json.dumps(guide, ensure_ascii=False, indent=1) + "\n"


def _summary(guide: dict, cover: dict[str, list[str]], out: Path) -> None:
    print("자료 안내 대장 — docs/데이터/대장/자료안내-*.tsv")
    print(f"  묶음 {len(guide['groups'])} · 자료 {len(guide['items'])} · 출처 {len(guide['sources'])}"
          f"(바깥 {sum(1 for s in guide['sources'] if s['kind'] == '바깥')}) · 흐름 상자 {len(guide['flow'])}"
          f" · 길잡이 {len(guide['tasks'])} · 틀리기 쉬운 것 {len(guide['pitfalls'])} · 뺀 표 {len(guide['excluded'])}")
    print(f"  바둑판 줄 {sum(1 for it in guide['items'] if it['grid'])} · 숫자를 잇는 자료 "
          f"{sum(1 for it in guide['items'] if it['stats_from']['status'] or it['stats_from']['backup'])}")
    if any(cover.values()):
        for k, v in cover.items():
            if v:
                print(f"  ⚠️ {k.replace('_', ' ')} {len(v)}: {', '.join(v)}")
    else:
        print("  ✅ 수집 표가 모두 안내에 있다(또는 뺀 까닭이 있다)")
    old = out.read_bytes().decode("utf-8").replace("\r\n", "\n") if out.exists() else ""
    print("  ✅ 생성물이 대장과 같다" if old == dumps(guide) else "  ⚠️ 생성물이 대장보다 뒤처졌다 — --write 로 다시 쓴다")


def main(argv: list[str] | None = None) -> int:
    # git bash(mintty)에서는 표준출력이 cp949 가 된다 → ✅ · ⚠️ · — 한 글자에서 죽는다(DF-11 · schema_scan 과 같다).
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="자료 안내 설명 생성물 — 대장(TSV) → app/services/data_guide.json")
    ap.add_argument("--write", action="store_true", help="생성물을 다시 쓴다(점검에 걸리면 쓰지 않는다)")
    ap.add_argument("--check", action="store_true", help="고치지 않고 생성물이 대장과 다르면 종료코드 1")
    ap.add_argument("--out", metavar="파일", default=str(OUT), help="생성물 위치(시험이 임시 파일로 견줄 때)")
    args = ap.parse_args(argv)

    guide, problems = build()
    out = Path(args.out)
    if problems:
        print(f"⚠️ 대장 점검에 걸린 곳 {len(problems)} — 생성물을 만들지 않는다")
        for p in problems:
            print(f"   - {p}")
        return 1
    new = dumps(guide)
    old = out.read_bytes().decode("utf-8") if out.exists() else ""
    if args.check:
        # 줄 끝을 접어서 견준다 — core.autocrlf 작업 트리는 체크아웃 때 CRLF 로 바꿔 써서, 바이트 그대로 견주면 대장이 같아도
        # 머지 · 브랜치 전환 뒤 늘 「뒤처졌다」 가 된다(API 문서 카탈로그 DF-77 · 검색 색인 지문 DF-68 과 같은 꼴).
        same = new == old.replace("\r\n", "\n")
        print("✅ 생성물이 대장과 같다" if same else "⚠️ 생성물이 대장보다 뒤처졌다 — --write 로 다시 쓴다")
        return 0 if same else 1
    if args.write:
        # 줄 끝은 지금 파일이 쓰던 것을 따른다 — 작업 트리가 CRLF 면 CRLF 로(섞으면 git 이 w/mixed 로 본다)
        nl = "\r\n" if "\r\n" in old else "\n"
        out.write_bytes(new.replace("\n", nl).encode("utf-8"))
        print(f"생성물: {out} · 자료 {len(guide['items'])} · 출처 {len(guide['sources'])}")
        return 0
    _summary(guide, coverage(guide, collector_tables(read_attr())), out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
