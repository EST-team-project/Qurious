"""용어사전 자료 빌드 — 글 자료 넷을 읽어 앱이 쓰는 용어 파일 하나로 만든다.

무엇을 하나
    통합본(`rag-lab/`)의 용어집 글 · 강의 사이트 용어와 Qurious 화면의 용어 상수를 읽어,
    같은 용어를 하나로 합치고 `app/services/glossary_data/terms.json` 을 쓴다.
    앱은 켜질 때 이 파일로 만든 행이 마지막 적재와 다를 때만 표에 다시 넣는다(`app/services/glossary.py`).

왜 파일을 거치나
    용어의 **원본은 git 파일**이다. 파일이면 「어떤 용어가 어떻게 바뀌었나」 가 PR 에서 줄 단위로 보이고,
    되돌리기도 git 으로 된다. DB 는 그 사본이라 언제든 다시 만들 수 있다.
    이 파일은 시각 · 난수를 담지 않는다 — 자료가 같으면 늘 같은 바이트가 나와야 체크섬이 흔들리지 않는다.

자료 넷 (읽는 차례 = 같은 용어가 겹칠 때 대표 이름을 주는 차례)
    voca      rag-lab/data/voca.md                         주식 학습 단어장 (강사님 investment-analysis)
    finance   rag-lab/data/samples/finance_glossary.txt    투자분석 핵심 용어집 + 한자 어원 사전 (강사님 domain-rag-lab)
    lecture   rag-lab/frontend/days/*.html · assets/glossary-*.js   강의 사이트의 용어 (강사님 domain-rag-lab)
    qurious   public/js/core.js 의 TERMS                   이 앱 화면의 용어 설명 (화면 키로 설명창을 연다)

쓰는 법
    python scripts/glossary_build.py            # 용어 파일을 다시 쓴다(바뀐 곳이 없으면 그대로)
    python scripts/glossary_build.py --check    # 다시 만들었을 때 파일과 다르면 종료코드 1 (커밋 전 · 시험)
    python scripts/glossary_build.py --stats    # 자료별 · 분류별 개수와 합쳐진 용어를 본다(쓰지 않는다)

용어를 고치려면 — 자료 글은 고치지 않는다(`rag-lab/` 은 원본 그대로 둔다). 이 파일의 표 넷 가운데 하나에 한 줄을 더한다.
    뜻 · 분류가 틀렸다            → OVERRIDES   {대표 이름: {칸: 값}}
    이름이 다른 같은 말이다        → SAME_AS     {자료에 적힌 이름: 대표 이름}
    이름이 같은데 다른 말이다      → RENAME      {자료에 적힌 제목: 이 사전에서 쓸 제목}
    이름 옆의 말이 이름이 아니다   → NOT_ALIAS   {대표 이름: 별칭에서 뺄 말}
    화면 용어를 더한다            → public/js/core.js 의 TERMS 에 더하고 QURIOUS_CATEGORY 에 분류를 적는다.
    그 뒤 이 스크립트를 돌리고, 바뀐 terms.json 을 함께 커밋한다. 표의 줄이 자료에 없는 이름을 가리키면 빌드가 멈춘다.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:             # `python scripts/glossary_build.py` 로 바로 돌릴 때 앱 모듈을 찾게
    sys.path.insert(0, str(ROOT))

# 찾기용 모양은 앱이 검색어를 다듬는 규칙과 **같은 함수**를 쓴다 — 따로 두면 빌드와 앱이 어긋난다.
from app.services.glossary_text import norm      # noqa: E402

RAGLAB = ROOT / "rag-lab"
OUT = ROOT / "app" / "services" / "glossary_data" / "terms.json"

#: 파일 모양이 바뀌면 올린다 — 앱의 적재기가 모르는 판이면 넣지 않고 알린다.
FORMAT_VERSION = 1

# ─────────────────────────────────────────────────────────────────────
# 자료 원천 · 분류 — 사람이 정한 것 (코드는 한 번 붙이면 바꾸지 않는다)
# ─────────────────────────────────────────────────────────────────────
SOURCES: list[dict[str, str]] = [
    {"code": "voca", "title": "주식 학습 단어장",
     "origin": "강사님 edumgt/investment-analysis 의 docs/voca.md",
     "paths": "rag-lab/data/voca.md"},
    {"code": "finance", "title": "투자분석 핵심 용어집 · 한자 어원 사전",
     "origin": "강사님 edumgt/domain-rag-lab 의 data/samples/finance_glossary.txt",
     "paths": "rag-lab/data/samples/finance_glossary.txt"},
    {"code": "lecture", "title": "강의 사이트 용어모음 (4일 금융 이론)",
     "origin": "강사님 edumgt/domain-rag-lab 의 frontend/days/",
     "paths": "rag-lab/frontend/days/01.html · 02.html · 03.html · 04.html · assets/glossary-modal.js · assets/glossary-drawer.js"},
    {"code": "qurious", "title": "Qurious 화면 용어 설명",
     "origin": "이 저장소의 public/js/core.js (강사님 lumina-invest 기초 코드 + 팀이 더한 것)",
     "paths": "public/js/core.js"},
]

# (코드, 이름, 한 줄 설명) — 적힌 차례가 화면에 보이는 차례다.
CATEGORIES: list[tuple[str, str, str]] = [
    ("basics", "주식 기초", "주식 · 주주 · 배당처럼 처음에 잡아 둘 말"),
    ("trading", "주문 · 거래", "호가 · 체결 · 결제 · 세금처럼 사고팔 때 쓰는 말"),
    ("technical", "기술적 분석", "추세 · 이동평균 · 보조지표 · 캔들 패턴"),
    ("fundamental", "기본적 분석", "재무제표 · 가치평가"),
    ("quant", "퀀트 · 포트폴리오", "백테스트 · 성과 지표 · 자산배분 · 위험"),
    ("macro", "거시 경제", "금리 · 물가 · 환율 · 경기"),
    ("industry", "산업 분석", "경쟁 구조 · 시장 규모 · 공급망"),
    ("report", "리포트 · 투자 의견", "목표주가 · 투자 의견 · 시나리오"),
    ("derivatives", "선물 · 옵션", "파생상품의 구조와 위험"),
    ("fund", "펀드 · ETF", "집합투자 · 상장지수펀드"),
    ("bond", "채권 · 코인", "채권 · 금리 민감도 · 암호자산"),
    ("general", "금융 일반", "여러 주제에 걸쳐 나오는 말"),
    ("abbr", "약어 · 산업 용어", "영문 약어와 반도체 · 전력 같은 산업 용어"),
    ("ml", "머신러닝 · 딥러닝", "예측 모델과 학습 · 검증"),
    ("stats", "통계 · 수학", "평균 · 분포 · 검정"),
    ("dev", "웹앱 · API", "이 앱 같은 서비스를 만드는 기술"),
    ("app", "이 앱의 기능", "Qurious 화면에서만 쓰는 말"),
    ("regulation", "금융 제도 · 규제", "금융회사 종류와 자본시장법"),
    ("theory", "금융 · 보험 이론", "정보 비대칭 · 사회보험 · 보험 원리"),
    ("private", "벤처 · 사모 · 절세", "벤처캐피탈 · 사모펀드 · 신탁 · 세금"),
    ("corporate", "기업 · 회계 · 세무", "법인 · 회계 · 조세 · 부동산 용어의 한자와 어원"),
    ("slang", "시장 줄임말 · 은어", "투자자들이 줄여 부르는 말 — 뜻과 주의할 점"),
]
CATEGORY_CODES = [c[0] for c in CATEGORIES]

# Qurious 화면 용어(키)의 분류. core.js 의 TERMS 에 키가 늘면 여기에도 적는다(빠지면 빌드가 멈춘다).
QURIOUS_CATEGORY: dict[str, str] = {
    "shap": "ml", "confidence": "app", "rebalancing": "quant", "drift": "quant",
    "rsi": "technical", "ma": "technical", "macd": "technical", "bollinger": "technical", "atr": "technical",
    "sharpe": "quant", "mdd": "quant", "win_rate": "quant", "cost_bps": "quant", "slippage": "quant",
    "lightgbm": "ml", "mlp": "ml", "kmeans": "ml", "gridsearch": "ml", "cross_validation": "ml",
    "dbscan": "ml", "stacking": "ml", "regression": "stats", "ridge_lasso": "ml",
    "seasonality": "quant", "covariance_opt": "quant", "black_litterman": "quant", "risk_parity": "quant", "mvo": "quant",
    "dcf": "fundamental", "eva": "fundamental", "fcf": "fundamental",
    "pine_script": "app", "alpaca": "app", "paper_trading": "app", "broker_api": "app",
    "rag": "dev", "embedding": "dev", "qdrant": "dev", "cb_score": "general",
    "golden_cross": "technical", "dead_cross": "technical", "signal": "quant", "backtest": "quant",
    "virtual_account": "app", "auto_trade_cycle": "app", "notification_channel": "app", "audit_log": "app",
    "vix": "macro", "dxy": "macro", "sector_etf": "fund", "macro_indicator": "macro",
    "custom_indicator": "app", "position_sizing": "quant", "drawdown": "quant", "broker_catalog": "app",
}

# 자료마다 이름이 달라 자동으로 못 잇는 같은 말 — {자료에 적힌 이름: 대표 이름}.
# 이름이 같아야만 합치는 것이 기본이라(group), 같은 말인데 이름이 다른 것은 사람이 여기에 적는다.
# 찾는 법: `--stats` 가 「영어 이름이 같은 다른 용어」 를 알려 준다 — 같은 말이면 여기에, 다른 말이면 그대로 둔다.
SAME_AS: dict[str, str] = {
    "샤프지수": "샤프 비율",
    "매매 시그널": "시그널",
    "상장지수펀드": "ETF",
    "상장지수증권": "ETN",
    "최대낙폭": "MDD",
    "매출액": "매출",
    "업종 순환매·섹터 로테이션": "섹터 로테이션",
    "순이익·당기순이익": "순이익",
    "당기순이익": "순이익",
    "자본·순자산": "자본",
    "Inverse": "인버스",
    "Leverage": "레버리지",
    "섹터형": "섹터 ETF",
}

# 자료의 글을 고치지 않고 바로잡는 곳. {대표 이름: {칸: 값}} — 칸은 Raw 의 이름(app_note · short · long …)이거나
# 결과의 이름(category · summary · definition)이다. 앞의 것은 합치기 전에, 뒤의 것은 합친 뒤에 덮어쓴다.
OVERRIDES: dict[str, dict[str, str]] = {
    # 화면 용어 설명은 「앱 내부(MongoDB)」 라고 적혀 있지만 Qurious 의 장부는 PostgreSQL 이다(Mongo 를 쓰지 않는다).
    "모의계좌": {"app_note": "실제 증권 계좌와 분리된, 앱 내부 데이터베이스(PostgreSQL)에만 존재하는 가상의 잔고입니다. "
                         "자동매매 로직을 실 자금 없이 검증할 때 사용합니다."},
    # 분류 — 자료가 놓아둔 자리보다 뜻에 맞는 자리가 분명한 것만.
    "금리": {"category": "macro"},
    "물가": {"category": "macro"},
    "채권": {"category": "bond"},
    "공매도": {"category": "trading"},
    "무차입 공매도": {"category": "trading"},
    "상관관계": {"category": "stats"},
    "위험": {"category": "quant"},
    "유동성": {"category": "basics"},
    "변동성": {"category": "quant"},
    "에스크로": {"category": "regulation"},
    "오버피팅": {"category": "ml"},
    "벤처캐피탈": {"category": "private"},
    "신용위험": {"category": "bond"},             # 강의가 펀드 단원에서 풀었지만 채권 발행자가 못 갚을 위험이다
    "지정참가회사": {"category": "fund"},
    "환헤지": {"category": "fund"},
    # 강의 풀이가 「장내거래는 …」 으로 시작해, 첫 문장을 뜻 한 줄로 쓰면 장외의 뜻이 아니다 — 같은 풀이의 둘째 문단 첫 문장을 쓴다.
    "장외": {"summary": "장외(OTC)거래는 거래소의 공개 주문장 밖에서 금융회사·기업 등 당사자가 거래 조건을 직접 합의하는 방식입니다."},
}

# 자료의 제목이 괄호로 가른 **다른 개념** — 괄호를 떼면 이름이 같아져 다른 풀이와 한 용어로 합쳐진다.
# {자료에 적힌 제목: 이 사전에서 쓸 제목}. 새 제목의 괄호 안은 별칭이 된다(term_parts).
RENAME: dict[str, str] = {
    "신용위험(CDS)": "CDS(신용부도스왑)",     # 강의 1일차 — 풀이가 신용위험이 아니라 신용부도스왑 계약이다
    "수익률(YTM)": "만기수익률(YTM)",         # 강의 3일차 — 채권의 만기수익률. 일반 수익률과 다른 말이다
    "국채 ETF(EDV)": "EDV",                  # 강의 3일차 — 국채 ETF 일반이 아니라 상품 하나의 풀이다
    "미국국채 ETF(TLT)": "TLT",
}

# 자료가 이름 옆에 적어 둔 말 가운데 **이름이 아닌 것** — 별칭으로 넣으면 그 말로 찾았을 때 엉뚱한 용어가 나온다.
# {대표 이름: 별칭에서 뺄 말}
NOT_ALIAS: dict[str, set[str]] = {
    "레이 달리오": {"투자자", "브리지워터 창립자"},     # 강의 용어의 곁말이 사람 소개다 — 「투자자」 로 찾으면 이 사람이 나왔다
    "브리지워터": {"미국 투자운용사"},
    "토니 로빈스": {"작가", "강연가"},
    # 두 글자 약어 — 강의는 이 뜻으로 썼지만 우리 시장에서는 다른 뜻이 더 흔하다(PF 대출 · 기업 IR)
    "포트폴리오": {"PF"},
    "금리": {"IR"},
}

# 한자 어원 사전이 쓰는 표기 기호 — 기호만으로는 뜻을 알 수 없어 글로 푼다(원문 「읽는 법」 의 풀이를 줄인 것).
ORIGIN_MARKS = {"🇯🇵": "[일본식 한자어]", "🀄": "[중국 고전 유래]", "📜": "[동아시아 공통 한자어]", "🆕": "[현대에 만든 말]"}

SOURCE_ORDER = {"voca": 0, "finance": 1, "lecture": 2, "finance-origin": 3, "qurious": 4}


def category_rank(raw: "Raw") -> int:
    """같은 용어를 자료마다 다른 분류에 두었을 때 어느 것을 따를지 — 숫자가 작을수록 먼저.

    자료가 「어디서 가르쳤나」 로 나눈 분류보다 「무엇에 관한 말인가」 로 나눈 분류를 앞에 둔다.
    용어 98개가 자료마다 분류가 갈렸고(2026-09-30), 이 차례로도 어색한 것은 OVERRIDES 에 적었다.
    """
    source, category = raw.source, raw.category
    if source == "finance" and category not in ("regulation", "private", "theory"):
        return 0                                   # 용어집의 도메인 절(거시 · 기본적 · 기술적 · 퀀트 …)
    if source == "voca" and category == "trading":
        return 1                                   # 단어장의 「주문 · 거래」 — 매수 · 호가 · 체결은 기초보다 여기
    if source == "voca" and category == "basics":
        return 2
    if source == "lecture" and category != "general":
        return 3                                   # 강의 날짜별 주제(선물 · 옵션 / 펀드 · ETF / 채권 · 코인)
    if source == "finance":
        return 4 if category in ("private", "theory") else 5   # 큰 묶음(제도 · 규제)은 뒤로
    if source == "finance-origin":
        return 6
    if source == "qurious":
        return 7
    return 8                                       # 단어장의 약어 · 은어 묶음, 강의의 공통 용어


# ─────────────────────────────────────────────────────────────────────
# 글자 다듬기
# ─────────────────────────────────────────────────────────────────────
_HAN = re.compile(r"[㐀-䶿一-鿿豈-﫿]")
_HANGUL = re.compile(r"[가-힣]")
_LATIN = re.compile(r"[A-Za-z]")


def clean(text: str) -> str:
    """마크다운 · HTML 표시를 떼고 공백을 하나로. 뜻을 바꾸는 글자는 건드리지 않는다."""
    text = re.sub(r"!?\[([^\]]+)\]\([^)]*\)", r"\1", text)       # [글](주소) → 글
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"[`*]|~~", "", text)
    text = text.replace("\\|", "|")
    return " ".join(text.split())


def slug(text: str) -> str:
    """용어 ID — 주소에 그대로 쓴다. 소문자 · 공백은 붙임표 · 한글은 그대로."""
    text = unicodedata.normalize("NFC", text).lower().strip()
    text = re.sub(r"[·/]", "-", text)
    text = re.sub(r"[^0-9a-z가-힣α-ω\- ]", "", text)
    return re.sub(r"[\s\-]+", "-", text).strip("-")


def split_cells(line: str) -> list[str]:
    """마크다운 표 한 줄 → 칸. 칸 안의 `\\|` 는 세로줄 글자다."""
    line = line.strip()
    line = line[1:] if line.startswith("|") else line
    line = line[:-1] if line.endswith("|") else line
    return [clean(c) for c in re.split(r"(?<!\\)\|", line)]


def tables(text: str) -> list[dict]:
    """글에서 마크다운 표를 차례로 — 그 표가 놓인 제목(#, ##, ###)과 함께."""
    lines = text.splitlines()
    out, h = [], ["", "", ""]
    i = 0
    while i < len(lines):
        line = lines[i]
        m = re.match(r"^(#{1,3})\s+(.*)$", line)
        if m:
            level = len(m.group(1))
            h[level - 1] = clean(m.group(2))
            for deeper in range(level, 3):
                h[deeper] = ""
        if re.match(r"^\s*\|", line) and i + 1 < len(lines) and re.match(r"^\s*\|?\s*:?-{3,}", lines[i + 1]):
            header = split_cells(line)
            rows, j = [], i + 2
            while j < len(lines) and re.match(r"^\s*\|", lines[j]):
                rows.append(split_cells(lines[j]))
                j += 1
            out.append({"h1": h[0], "h2": h[1], "h3": h[2], "header": header, "rows": rows})
            i = j
            continue
        i += 1
    return out


def split_names(cell: str) -> tuple[str, str]:
    """「株式 / Stock, Share」 같은 칸 → (영어 이름, 한자). 한자가 든 조각은 한자, 나머지는 영어다."""
    english, hanja = [], []
    for part in re.split(r"\s+/\s+|\s+·\s+", cell):
        part = part.strip()
        if not part or part in ("-", "—", "–"):
            continue
        if _HAN.search(part) and not _LATIN.search(part):
            hanja.append(part)
        else:
            english.append(part)
    return ", ".join(english), " · ".join(hanja)


def term_parts(raw: str) -> tuple[str, list[str]]:
    """표에 적힌 용어 이름 → (대표 이름, 별칭들).

    「주당순이익(EPS)」 → 주당순이익 + EPS · 「자사주·자기주식」 → 그대로 + 자사주 · 자기주식.
    가운뎃점으로 이은 이름은 한 줄이 여러 말을 함께 풀이한 것이라 통째로 대표 이름으로 두고, 조각을 별칭으로 둔다.
    """
    raw = clean(raw)
    aliases = [m.strip() for m in re.findall(r"\(([^)]+)\)", raw)]
    base = re.sub(r"\s*\([^)]*\)", "", raw).strip()
    if "·" in base:
        aliases += [p.strip() for p in base.split("·") if len(p.strip()) >= 2]
    return base, [a for a in aliases if a and a != base]


def name_parts(text: str) -> list[str]:
    """이름이 적힌 칸(영어 이름 · 별칭)의 글 → 이름 조각들.

    쉼표 · 빗금 · 가운뎃점으로 이은 영문은 나누고(「Stock, Share」 「Open·High·Low·Close」), 괄호 안의 약어 · 읽는 법 · 번역은
    따로 떼어 낸다 — 「Net Interest Margin (NIM)」 → Net Interest Margin · NIM / 「Low Volatility(로우 볼래틸러티)」 → Low Volatility · 로우 볼래틸러티.
    이름이 아닌 것은 버린다: 「이름표: 값」 모양(「거래상대방 위험: Counterparty Risk」)과 말의 짜임을 푼 괄호(「FinTech (Finance + Technology)」).
    한글이 든 조각은 가운뎃점에서 나누지 않는다 — 「소재·부품·장비」 는 셋이 모여 한 이름이다(「장비」 로 찾아 「소부장」 이 나오면 안 된다).
    """
    out: list[str] = []
    for part in name_list(text):
        outer = re.sub(r"\s*\([^)]*\)", "", part).strip()
        if not outer:                             # 「(H)」 처럼 괄호가 곧 이름인 것 — 그대로 둔다
            out.append(part)
            continue
        out.append(outer)
        out += [x.strip() for x in re.findall(r"\(([^)]*)\)", part) if x.strip() and "+" not in x]
    return out


def name_list(text: str) -> list[str]:
    """한 칸에 늘어놓은 이름들 — 쉼표 · 빗금 · (영문의) 가운뎃점에서 나눈 것. 괄호는 그대로 둔다.

    둘 이상이면 그 칸은 「이름 여럿을 늘어놓은 칸」 이다. 그런 칸에서 얻은 이름은, 다른 용어가 통째로 적은 같은 이름에 진다(build).
    """
    out: list[str] = []
    for piece in re.split(r",\s*|\s+/\s+", text or ""):
        for part in ([piece] if _HANGUL.search(piece) else re.split(r"\s*·\s*", piece)):
            part = part.strip()
            if part and ":" not in part:
                out.append(part)
    return out


def alias_kind(alias: str) -> str:
    """별칭의 종류 — 화면이 「약어 PER · 영어 Price Earnings Ratio · 다른 이름 주가수익비율」 처럼 나눠 보여 줄 때 쓴다.

    한글 · 한자가 들었으면 다른 이름이다. 영문은 글자가 셋 이하이거나(bps · pt), 열두 자 안쪽이면서 소문자가 셋 넘게 이어지지
    않으면(PER · Rf · GWh · EV/EBITDA) 약어이고, 나머지는 영어 이름이다(Risk · Front-month · Return on Equity).
    글자 없는 기호(β · Δ · ≈)는 약어로 둔다.
    """
    if _HANGUL.search(alias) or _HAN.search(alias):
        return "다른 이름"
    letters = re.sub(r"[^A-Za-z]", "", alias)
    if len(letters) <= 3 or (len(alias) <= 12 and not re.search(r"[a-z]{3,}", alias)):
        return "약어"
    return "영어"


def english_name(text: str) -> str:
    """영어 이름 칸에 보일 글 — 괄호 안의 한글(읽는 법 · 번역)을 떼고, 영문이 없으면 비운다.

    「Liquidity(리퀴디티)」 → Liquidity · 「Net Interest Margin (NIM)」 → 그대로 · 「자기자본이익률」 → 빈 글.
    자료가 이 칸에 우리말 번역을 적어 둔 줄이 있다(「Exit | 투자 회수」). 그 말은 별칭으로 가고(name_parts), 여기에는 싣지 않는다.
    """
    text = re.sub(r"\s*\([^)]*[가-힣][^)]*\)", "", text or "").strip()
    return text if _LATIN.search(text) else ""


def first_sentence(text: str, limit: int = 140) -> str:
    """긴 풀이에서 한 줄 요약을 떼어 낸다 — 첫 문장, 그래도 길면 자르고 말줄임표."""
    m = re.match(r"(.+?(?:[.!?]|다\.|요\.))(?:\s|$)", text)
    head = (m.group(1) if m else text).strip()
    return head if len(head) <= limit else head[:limit - 1].rstrip() + "…"


# ─────────────────────────────────────────────────────────────────────
# 자료 읽기 — 자료마다 「그 자료에 적힌 그대로」 의 항목(Raw)을 만든다
# ─────────────────────────────────────────────────────────────────────
@dataclass
class Raw:
    term: str                       # 대표 이름(괄호 · 굵게 표시를 뗀 것)
    source: str                     # 자료 코드
    category: str
    aliases: list[str] = field(default_factory=list)
    english: str = ""
    hanja: str = ""
    short: str = ""                 # 쉬운 뜻 한 줄
    long: str = ""                  # 자세한 뜻
    example: str = ""
    caution: str = ""
    formula: str = ""
    origin_note: str = ""           # 말의 구조 · 어원
    reading: str = ""               # 한자 읽기(한자 어원 사전) — 다른 풀이가 없을 때 한 줄 뜻으로 쓴다
    etymology: str = ""             # 어원 풀이(한자 어원 사전)
    app_note: str = ""              # 이 앱에서의 뜻(화면 용어)
    key: str = ""                   # 화면 용어의 키
    where: str = ""                 # 자료 안의 자리(표 제목) — 「다른 자료의 설명」 에 붙는 이름표
    title: str = ""                 # 자료에 적힌 제목 그대로(「채권(債權)」) — 같은 이름의 다른 풀이를 이름표에서 가린다


def parse_voca(text: str) -> list[Raw]:
    out: list[Raw] = []
    formulas: dict[str, tuple[str, str]] = {}
    for t in tables(text):
        header, section = t["header"], (t["h3"] or t["h2"])
        if header[0] == "보고 싶은 것":                      # 계산식 표 — 용어가 아니라 용어에 붙일 식
            for r in t["rows"]:
                base, aliases = term_parts(r[0])
                for name in [base, *aliases]:
                    formulas[norm(name)] = (r[1], r[2] if len(r) > 2 else "")
            continue
        if "사람들이 쓰는 뜻" in header:                       # 줄임말 · 은어 표 — 뜻 + 주의할 점
            for r in t["rows"]:
                base, aliases = term_parts(r[0])
                second = r[1] if len(r) > 1 else ""
                third = r[2] if len(r) > 2 else ""
                if third and not _HANGUL.search(second):     # 「ISP | Internet Service Provider | 풀이」 — 둘째 칸이 영어 이름인 줄
                    out.append(Raw(base, "voca", "slang", aliases, english=second, short=third, where=t["h2"]))
                else:
                    out.append(Raw(base, "voca", "slang", aliases, short=second, caution=third, where=t["h2"]))
            continue
        name_i = next((i for i, x in enumerate(header) if re.search("한자|영어", x)), -1)
        origin_i = next((i for i, x in enumerate(header) if re.search("말의 구조|유래", x)), -1)
        if name_i < 0:
            continue
        category = ("trading" if "거래에서 쓰는" in t["h2"] else
                    "abbr" if header[0] == "용어" else "basics")
        detailed = any(re.search("자세한|초보자용|뜻 풀이", x) for x in header)
        for r in t["rows"]:
            base, aliases = term_parts(r[0])
            english, hanja = split_names(r[name_i]) if name_i < len(r) else ("", "")
            origin = r[origin_i] if 0 <= origin_i < len(r) else ""
            body = " ".join(c for i, c in enumerate(r) if i not in (0, name_i, origin_i)).strip()
            if origin_i >= 0 and len(r) == 3:              # 「말의 구조」 칸을 빼고 설명만 적은 줄
                origin, body = "", r[2]
            body = re.sub(r"^[A-Za-z]+\([^)]*\):\s*", "", body)   # 「PER(…, 주가수익비율): 설명」 의 머리말을 뗀다
            raw = Raw(base, "voca", category, aliases, english, hanja, origin_note=origin, where=section)
            if detailed:
                raw.long = body
            else:
                raw.short = body
            out.append(raw)
    for raw in out:                                        # 계산식 · 읽을 때 주의할 점을 그 용어에 붙인다
        for name in [raw.term, *raw.aliases]:
            if norm(name) in formulas and not raw.formula:
                raw.formula, caution = formulas[norm(name)]
                raw.caution = raw.caution or caution
    return out


_FINANCE_SECTION = {"1": "macro", "2": "industry", "3": "fundamental", "4": "technical", "5": "report", "6": "quant",
                    "7": "ml", "8": "dev", "9": "stats", "12": "regulation", "13": "private"}
_ORIGIN_SECTION = {"1": "macro", "5": "general", "6": "basics", "8": "quant"}


def parse_finance(text: str) -> list[Raw]:
    out: list[Raw] = []
    for t in tables(text):
        header = t["header"]
        number = (re.match(r"(\d+)\.", t["h2"]) or [None, ""])[1]
        if t["h1"].startswith("투자분석"):
            if header[0] != "용어" or len(header) != 5:        # 비교 쌍 · 구분 표는 용어 표가 아니다
                continue
            category = _FINANCE_SECTION.get(number, "general")
            if "포트폴리오" in t["h3"] or "백테스트" in t["h3"]:
                category = "quant"
            if "이론 용어" in t["h3"]:
                category = "theory"
            for r in t["rows"]:
                if len(r) < 5:
                    continue
                base, aliases = term_parts(r[0])
                english, hanja = split_names(r[2])
                extra_en, extra_han = split_names(r[1])      # 「한자/약어」 칸 — 한자이거나 약어다
                if extra_en and norm(extra_en) != norm(base):
                    aliases.append(extra_en)
                out.append(Raw(base, "finance", category, aliases, english, hanja or extra_han,
                               short=r[3], example=r[4], where=t["h3"] or t["h2"]))
        elif header == ["항목", "내용"] and t["h3"]:              # 한자 어원 사전 — 제목이 용어, 표가 속성
            props = {r[0]: r[1] for r in t["rows"] if len(r) == 2}
            category = _ORIGIN_SECTION.get(number, "corporate")
            if "자산배분" in t["h2"]:
                category = "quant"
            etymology = " ".join(x for x in (props.get("어원", ""), props.get("비고", "")) if x)
            for mark, words in ORIGIN_MARKS.items():
                etymology = etymology.replace(mark, words)
            heading = re.sub(r"\s+—.*$", "", t["h3"])            # 「포트폴리오 (portfolio) — 한자 참고」 의 꼬리말을 뗀다
            named = []                                          # (이름, 한자, 괄호 안 다른 이름들)
            for name in re.split(r"\s+/\s+|\s+vs\s+", heading):
                inside = [x.strip() for m in re.findall(r"\(([^)]*)\)", name) for x in m.split(",")]
                base = " ".join(re.sub(r"\([^)]*\)", " ", name).split())   # 「거시 (巨視) 분석」 → 거시 분석
                if base:
                    named.append((base, " · ".join(x for x in inside if _HAN.search(x)),
                                  [x for x in inside if x and not _HAN.search(x)]))   # 「(株價收益比率, PER)」 의 PER
            # 「위험 (危險) / 리스크 (risk)」 처럼 한자가 없는 이름은 같은 말의 외래어 표기다 — 따로 용어로 두지 않고
            # 한자가 있는 이름의 별칭으로 둔다. 「거시경제 (…) / 미시경제 (…)」 처럼 둘 다 한자가 있으면 짝을 이루는 두 용어다.
            with_hanja = [n for n in named if n[1]] or named[:1]
            loan_names = [x for n in named if n not in with_hanja for x in (n[0], *n[2])]
            readings = [x.strip() for x in props.get("읽기", "").split(" / ")]
            for i, (base, hanja, aliases) in enumerate(with_hanja):
                reading = readings[i] if len(readings) == len(with_hanja) else props.get("읽기", "")
                out.append(Raw(base, "finance-origin", category, aliases + (loan_names if i == 0 else []), hanja=hanja,
                               reading=reading, etymology=etymology, where="한자 어원 사전"))
    return out


class _GlossaryItems(HTMLParser):
    """강의 HTML 의 `<div class="glossary-item"><dt>용어 <small>별칭</small></dt><dd>풀이</dd></div>`."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.items: list[dict] = []
        self._item: dict | None = None
        self._where = ""            # dt · small · dd · p · skip
        self._div_depth = 0
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if self._item is None:
            if tag == "div" and "glossary-item" in (a.get("class") or "").split():
                self._item = {"term": "", "small": "", "paragraphs": [], "loose": ""}
                self._div_depth = 1
            return
        if self._skip_depth:
            self._skip_depth += 1
            return
        if tag == "template":         # 자세한 풀이 틀 — 설명창이 복제해 쓰는 것이라 본문과 겹친다
            self._skip_depth = 1
        elif tag == "div":
            self._div_depth += 1
        elif tag == "dt":
            self._where = "dt"
        elif tag == "small" and self._where == "dt":
            self._where = "small"
        elif tag == "dd":
            self._where = "dd"
        elif tag == "p" and self._where in ("dd", "p"):
            self._where = "p"
            self._item["paragraphs"].append("")

    def handle_endtag(self, tag):
        if self._item is None:
            return
        if self._skip_depth:
            self._skip_depth -= 1
            return
        if tag == "small" and self._where == "small":
            self._where = "dt"
        elif tag == "dt":
            self._where = ""
        elif tag == "p" and self._where == "p":
            self._where = "dd"
        elif tag == "dd":
            self._where = ""
        elif tag == "div":
            self._div_depth -= 1
            if self._div_depth == 0:
                self.items.append(self._item)
                self._item = None

    def handle_data(self, data):
        if self._item is None or self._skip_depth:
            return
        if self._where == "dt":
            self._item["term"] += data
        elif self._where == "small":
            self._item["small"] += data
        elif self._where == "p":
            self._item["paragraphs"][-1] += data
        elif self._where == "dd":
            self._item["loose"] += data


_DAY_CATEGORY = {"01": "derivatives", "02": "fund", "03": "bond", "04": "quant"}


_RENAME_SEEN: set[str] = set()      # 자료에서 실제로 만난 RENAME 의 제목 — 자료가 바뀌어 안 쓰이게 된 줄을 build 가 알린다


def _lecture_raw(term: str, small: str, paragraphs: list[str], category: str, where: str) -> Raw | None:
    title = clean(term)
    if title in RENAME:
        _RENAME_SEEN.add(title)
        term = RENAME[title]
    base, aliases = term_parts(term)
    if not base:
        return None
    english_parts, hanja_parts = [], []
    for part in re.split(r"\s+·\s+", clean(small)):           # 「Diversification · 分散投資 · R」
        part = part.strip()
        if not part:
            continue
        (hanja_parts if _HAN.search(part) and not _LATIN.search(part) else english_parts).append(part)
    paragraphs = [clean(p) for p in paragraphs if clean(p)]
    english = english_parts[0] if english_parts else ""
    return Raw(base, "lecture", category, aliases + english_parts[1:], english, " · ".join(hanja_parts),
               long="\n\n".join(paragraphs), where=where, title=title)


def parse_lecture_html(text: str, day: str) -> list[Raw]:
    parser = _GlossaryItems()
    parser.feed(text)
    out = []
    for item in parser.items:
        paragraphs = item["paragraphs"] or [item["loose"]]
        raw = _lecture_raw(item["term"], item["small"], paragraphs, _DAY_CATEGORY.get(day, "general"), f"{day}일차 용어")
        if raw and raw.long:
            out.append(raw)
    return out


def parse_lecture_js(text: str) -> list[Raw]:
    """용어 서랍 · 설명창 스크립트에 적힌 공통 용어 — `{ title: '…', aliases: '…', detail: ['…'] }`."""
    out = []
    quoted = r"'((?:[^'\\]|\\.)*)'"
    for m in re.finditer(r"\{\s*title:\s*" + quoted + r",\s*alias(?:es)?:\s*" + quoted
                         + r",\s*(?:detail|paragraphs):\s*\[(.*?)\]\s*\}", text, re.S):
        paragraphs = [p.replace("\\'", "'") for p in re.findall(quoted, m.group(3))]
        raw = _lecture_raw(m.group(1), m.group(2), paragraphs, "general", "공통 용어")
        if raw and raw.long:
            out.append(raw)
    # 긴 풀이를 HTML 로 적은 항목(`detailHtml`) — 첫 문단들만 글로 옮긴다.
    for m in re.finditer(r"title:\s*" + quoted + r",\s*aliases:\s*" + quoted + r",\s*detailHtml:\s*`(.*?)`", text, re.S):
        paragraphs = re.findall(r"<p>(.*?)</p>", m.group(3), re.S)
        raw = _lecture_raw(m.group(1), m.group(2), paragraphs, "bond", "공통 용어")
        if raw and raw.long:
            out.append(raw)
    return out


def parse_qurious(js: str) -> list[Raw]:
    """`public/js/core.js` 의 `const TERMS = { 키: { title: "…", body: "…" }, … }`."""
    start = js.index("const TERMS = {")
    block = js[start:js.index("\n};", start)]
    out = []
    for m in re.finditer(r'^\s{2}([a-z_0-9]+):\s*\{\s*title:\s*("(?:[^"\\]|\\.)*"),\s*body:\s*("(?:[^"\\]|\\.)*")\s*\},?\s*$',
                         block, re.M):
        key, title, body = m.group(1), json.loads(m.group(2)), json.loads(m.group(3))
        if key not in QURIOUS_CATEGORY:
            raise SystemExit(f"화면 용어 「{key}」 의 분류가 없다 — QURIOUS_CATEGORY 에 한 줄을 더한다")
        base, aliases = term_parts(title)
        out.append(Raw(base, "qurious", QURIOUS_CATEGORY[key], aliases, app_note=body, key=key, where="화면 용어 설명"))
    return out


def read_sources() -> list[Raw]:
    _RENAME_SEEN.clear()
    raws: list[Raw] = []
    raws += parse_voca((RAGLAB / "data" / "voca.md").read_text(encoding="utf-8"))
    raws += parse_finance((RAGLAB / "data" / "samples" / "finance_glossary.txt").read_text(encoding="utf-8"))
    days = RAGLAB / "frontend" / "days"
    for day in ("01", "02", "03", "04"):
        raws += parse_lecture_html((days / f"{day}.html").read_text(encoding="utf-8"), day)
    for name in ("glossary-modal.js", "glossary-drawer.js"):
        raws += parse_lecture_js((days / "assets" / name).read_text(encoding="utf-8"))
    raws += parse_qurious((ROOT / "public" / "js" / "core.js").read_text(encoding="utf-8"))
    return raws


# ─────────────────────────────────────────────────────────────────────
# 합치기 — 같은 용어를 하나로
# ─────────────────────────────────────────────────────────────────────
def group(raws: list[Raw]) -> list[list[Raw]]:
    """같은 용어끼리 묶는다.

    묶는 기준은 **대표 이름이 같은가**(찾기용 모양으로) 하나다. 별칭이 같다고 묶지 않는다 —
    「보통주·우선주」 의 별칭 「우선주」 때문에 다른 자료의 「우선주」 와 한 용어가 되면 안 된다.
    예외는 둘이다. 이름이 달라도 같은 말이라고 사람이 적어 둔 것(SAME_AS)은 그 대표 이름으로 묶는다.
    그리고 화면 용어 · 한자 어원 사전은 제목의 괄호 안 이름(「MDD (최대낙폭)」 · 「주가수익비율 (株價收益比率, PER)」)이
    이미 있는 용어의 대표 이름과 같으면 그 용어에 붙인다 — 둘 다 다른 자료의 용어를 **보태는** 자료라서 그렇다.
    """
    same_as = {norm(k): norm(v) for k, v in SAME_AS.items()}
    groups: dict[str, list[Raw]] = {}
    for raw in sorted(raws, key=lambda r: SOURCE_ORDER[r.source]):     # 안정 정렬 — 자료 안의 차례는 그대로
        key = same_as.get(norm(raw.term), norm(raw.term))
        if key not in groups and raw.source in ("qurious", "finance-origin"):
            key = next((norm(c) for c in (raw.term, *raw.aliases) if norm(c) in groups), key)
        groups.setdefault(key, []).append(raw)
    # 대표 이름은 묶음 열쇠와 이름이 같은 항목의 것 — 「순이익·당기순이익」 이 먼저 읽혀도 대표 이름은 「순이익」 이다.
    for key, members in groups.items():
        members.sort(key=lambda r: norm(r.term) != key)               # 안정 정렬 — 이름이 같은 것만 앞으로
    return list(groups.values())


def merge(members: list[Raw], unused: set[tuple[str, str]] | None = None) -> dict:
    """한 묶음 → 용어 한 줄.

    뜻 한 줄(summary)과 자세한 뜻(definition)은 **같은 자료**에서만 가져온다. 이름이 같아 합쳐졌어도 자료마다
    가리키는 것이 다를 수 있어서다(「내재가치」 — 용어집은 기업의 적정 가격, 강의는 옵션의 내재가치).
    고르지 않은 풀이는 버리지 않고 자료 이름을 붙여 「다른 자료의 설명」(notes)으로 남긴다.

    unused 를 주면, NOT_ALIAS 의 (대표 이름, 뺄 말) 가운데 이 묶음에서 실제로 뺀 것을 거기서 지운다(build 가 안 쓰인 줄을 알린다).
    """
    first = members[0]
    fix = OVERRIDES.get(first.term, {})

    def pick(attr: str) -> str:
        return fix.get(attr) or next((getattr(r, attr) for r in members if getattr(r, attr)), "")

    lead = next((r for r in members if r.short), None) or next((r for r in members if r.long), None)
    if lead is not None:
        summary = lead.short or first_sentence(lead.long)
        definition = lead.long if lead.long != summary else ""
        origin_note = pick("origin_note") or " — ".join(x for x in (pick("reading"), pick("etymology")) if x)
        lead_source = lead.source
    elif pick("app_note"):                               # 화면 용어뿐인 말 — 앱 설명의 첫 문장을 한 줄 뜻으로
        summary, definition, origin_note = first_sentence(pick("app_note")), "", ""
        lead_source = "qurious"
    else:                                                # 한자 어원 사전에만 있는 말 — 그 자료가 가진 것을 그대로 쓴다
        reading, etymology = pick("reading"), pick("etymology")
        summary = f"한자 풀이 — {reading}" if reading else first_sentence(etymology)
        definition, origin_note = etymology, ""          # 어원 풀이가 곧 본문이라 두 번 싣지 않는다
        lead_source = "finance"

    notes, noted = [], {summary, definition}
    for r in members:
        # 이름표에 자료의 제목을 붙이는 때 — 그 풀이가 다른 이름(「샤프지수」)이나 한자로 가른 다른 말(「채권(債權)」)의 것일 때.
        titled = norm(r.term) != norm(first.term) or (_HAN.search(r.title) and norm(r.title) != norm(first.term))
        label = f"{r.where} · {r.title or r.term}" if titled else r.where
        for text in (r.short, r.long):
            if text and text not in noted:
                noted.add(text)
                notes.append({"source": r.source.replace("-origin", ""), "label": label, "text": text})

    aliases: list[tuple[str, str, bool]] = []            # (이름, 종류, 한 칸을 나눠서 얻은 이름인가)
    for r in members:
        if r.key:
            aliases.append((r.key, "화면 키", False))
        if norm(r.term) != norm(first.term):
            aliases.append((r.term, alias_kind(r.term), False))
        for text in (*r.aliases, r.english):
            listed = len(name_list(text)) > 1            # 이름 여럿을 늘어놓은 칸인가(괄호 안 약어는 늘어놓은 것이 아니다)
            aliases += [(name, alias_kind(name), listed) for name in name_parts(text)]
    not_alias = {norm(a): a for a in NOT_ALIAS.get(first.term, ())}
    seen, unique, split = {norm(first.term)}, [], set()
    for alias, kind, from_split in aliases:
        alias = alias.strip()
        key = norm(alias)
        if key in not_alias:                              # 이름이 아닌 말 — 별칭으로 넣지 않는다
            if unused is not None:
                unused.discard((first.term, not_alias[key]))
            continue
        if alias and key and key not in seen:
            seen.add(key)
            unique.append({"alias": alias, "kind": kind})
            if from_split:
                split.add(key)

    # 영어 이름 칸에는 영문만 — 자료가 그 칸에 우리말 번역을 적은 줄은 별칭(위)으로만 가고, 영어로 판정된 별칭이 있으면 그것을 쓴다.
    english = (fix.get("english")
               or next((e for e in (english_name(r.english) for r in members) if e), "")
               or next((a["alias"] for a in unique if a["kind"] == "영어"), ""))

    return {
        "id": slug(first.term),
        "term": first.term,
        "english": english,
        "hanja": pick("hanja"),
        "category": fix.get("category") or min(members, key=category_rank).category,
        "summary": fix.get("summary") or summary,
        "definition": fix.get("definition") or definition,
        "example": pick("example"),
        "caution": pick("caution"),
        "formula": pick("formula"),
        "origin_note": origin_note,
        "app_note": pick("app_note"),
        "lead_source": lead_source.replace("-origin", ""),   # 뜻 한 줄을 준 자료
        "sources": sorted({r.source.replace("-origin", "") for r in members}, key=lambda s: SOURCE_ORDER[s]),
        "aliases": unique,
        "notes": notes,
        "_split": split,                                 # build 가 별칭의 임자를 정할 때만 쓰고 파일에는 쓰지 않는다
    }


def build() -> dict:
    raws = read_sources()
    unused = {(term, alias) for term, names in NOT_ALIAS.items() for alias in names}
    terms = [merge(g, unused) for g in group(raws)]
    names = {t["term"] for t in terms}
    # 자료에서 사라진 이름 · 제목을 가리키는 줄 — 조용히 무시하지 않는다(규칙이 말없이 꺼지면 고친 것이 되돌아온다).
    stale = (sorted(k for k in OVERRIDES if k not in names) + sorted(v for v in SAME_AS.values() if v not in names)
             + sorted(k for k in RENAME if k not in _RENAME_SEEN) + sorted(f"{t} ← {a}" for t, a in unused))
    if stale:
        raise SystemExit(f"OVERRIDES · SAME_AS · RENAME · NOT_ALIAS 가 자료에 없는 이름을 가리킨다: {stale}")

    # ID 가 겹치면 멈춘다 — 조용히 덮어쓰면 용어 하나가 사라진다.
    clash = [k for k, n in Counter(t["id"] for t in terms).items() if n > 1 or not k]
    if clash:
        raise SystemExit(f"용어 ID 가 겹치거나 비었다: {clash} — 대표 이름을 다듬거나 OVERRIDES 로 가른다")

    # 별칭 하나는 용어 하나만 가리킨다. 대표 이름과 같은 별칭은 버리고(대표 이름이 이긴다), 두 용어가 같은 별칭을
    # 내세우면 아래 차례로 임자를 정한다 — 같은 차례 안에서는 먼저 읽은 자료의 용어가 갖는다. 버린 것은 세어서 알린다.
    #   0 화면 키       화면의 설명창이 그 키로 용어를 찾는다. 다른 용어의 영어 이름에 밀리면 엉뚱한 용어가 뜬다
    #                  (「sector_etf」 가 강의 용어 「섹터형」 의 영어 이름 Sector ETF 에 밀렸었다). 두 용어가 같은 키를 내세우면 멈춘다.
    #   1 통째로 적힌 이름   자료의 한 칸이 그대로 이름인 것(「프리미엄 | Premium」)
    #   2 나눠서 얻은 이름   한 칸을 쉼표 · 빗금 · 괄호에서 나눈 것(「괴리율 | Premium / Discount」 의 Premium) — 통째로 적힌 쪽에 진다
    primary = {norm(t["term"]): t["id"] for t in terms} | {norm(t["id"]): t["id"] for t in terms}
    owner: dict[str, str] = {}

    def level(term: dict, a: dict) -> int:
        return 0 if a["kind"] == "화면 키" else 2 if norm(a["alias"]) in term["_split"] else 1

    for turn in (0, 1, 2):
        for term in terms:
            for a in term["aliases"]:
                key = norm(a["alias"])
                if level(term, a) != turn or primary.get(key, term["id"]) != term["id"]:
                    continue
                if owner.setdefault(key, term["id"]) != term["id"] and turn == 0:
                    raise SystemExit(f"화면 키 「{a['alias']}」 를 두 용어가 내세운다: {owner[key]} · {term['id']}")
    dropped = 0
    for term in terms:
        kept = [a for a in term["aliases"] if owner.get(norm(a["alias"])) == term["id"]]
        dropped += len(term["aliases"]) - len(kept)
        # 임자가 다른 용어인 이름 — 「NAV」 는 순자산가치도 기준가격도 쓴다. 이름으로 한 건을 찾을 때는 임자에게 가지만,
        # 검색에서는 이 용어도 나와야 한다(적재할 때 찾기용 글에만 넣는다 — app/services/glossary.py 의 seed_rows).
        term["shared_names"] = [a["alias"] for a in term["aliases"] if a not in kept]
        term["aliases"] = kept
        del term["_split"]

    order = {code: i for i, code in enumerate(CATEGORY_CODES)}
    terms.sort(key=lambda t: (order[t["category"]], norm(t["term"])))
    counts = Counter(t["category"] for t in terms)
    return {
        "format_version": FORMAT_VERSION,
        "sources": [{**s, "terms": sum(1 for t in terms if s["code"] in t["sources"])} for s in SOURCES],
        "categories": [{"code": c, "name": n, "description": d, "sort_order": i * 10, "terms": counts[c]}
                       for i, (c, n, d) in enumerate(CATEGORIES, 1)],
        "terms": terms,
        "_build": {"raw_entries": len(raws), "aliases_dropped": dropped},
    }


def render(data: dict) -> str:
    """파일에 쓸 글자 — 늘 같은 모양(키 차례 고정 · 들여쓰기 1칸 · 끝에 줄바꿈)."""
    body = {k: v for k, v in data.items() if not k.startswith("_")}
    return json.dumps(body, ensure_ascii=False, indent=1) + "\n"


def checksum(text: str) -> str:
    """용어 파일의 판 — 줄끝을 LF 로 맞춘 내용의 SHA-256. 앱의 적재기가 같은 방법으로 센다."""
    return hashlib.sha256(text.replace("\r\n", "\n").encode("utf-8")).hexdigest()


def main(argv: list[str] | None = None) -> int:
    # git bash(mintty)에서는 표준출력이 cp949 가 된다 → ✅ · — 한 글자에서 죽는다. 도움말보다 먼저 맞춘다.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="용어사전 자료 빌드 — 글 자료 넷을 용어 파일 하나로")
    ap.add_argument("--check", action="store_true", help="다시 만든 결과가 파일과 다르면 종료코드 1 (쓰지 않는다)")
    ap.add_argument("--stats", action="store_true", help="자료별 · 분류별 개수를 본다 (쓰지 않는다)")
    args = ap.parse_args(argv)

    data = build()
    text = render(data)
    terms = data["terms"]
    print(f"자료 항목 {data['_build']['raw_entries']} → 용어 {len(terms)} · 별칭 {sum(len(t['aliases']) for t in terms)}"
          f" (겹쳐서 버린 별칭 {data['_build']['aliases_dropped']}) · 판 {checksum(text)[:12]}")
    if args.stats:
        for s in data["sources"]:
            print(f"  자료 {s['code']:8s} 용어 {s['terms']:4d}  {s['title']}")
        for c in data["categories"]:
            print(f"  분류 {c['code']:12s} {c['terms']:4d}  {c['name']}")
        multi = [t for t in terms if len(t["sources"]) > 1]
        print(f"  두 자료 이상에 나온 용어 {len(multi)} · 뜻 한 줄이 빈 용어 {sum(1 for t in terms if not t['summary'])}")
        # 영어 이름이 같은데 따로 있는 용어 — 같은 말이면 SAME_AS 에 적고, 다른 말이면 그대로 둔다.
        by_english: dict[str, set[str]] = {}
        for t in terms:
            for name in re.split(r",\s*|\s*·\s*", t["english"]):
                if len(norm(name)) >= 3:
                    by_english.setdefault(norm(name), set()).add(t["term"])
        for name, owners in sorted(by_english.items()):
            if len(owners) > 1:
                print(f"  영어 이름이 같은 다른 용어: {name} → {' · '.join(sorted(owners))}")
        return 0
    current = OUT.read_bytes().decode("utf-8").replace("\r\n", "\n") if OUT.exists() else ""
    if args.check:
        same = current == text
        print("✅ 용어 파일이 자료와 같다" if same else f"⚠️ 용어 파일이 자료와 다르다 — python scripts/glossary_build.py 를 돌린다: {OUT}")
        return 0 if same else 1
    if current != text:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_bytes(text.encode("utf-8"))
    print(f"{'썼다' if current != text else '바뀐 곳 없음'}: {OUT.relative_to(ROOT)} · {len(text.encode('utf-8')) / 1024:.0f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
