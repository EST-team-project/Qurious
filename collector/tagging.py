"""이름표 — 공시 · 뉴스에 종목 · 주제 · 용어 · 공시 유형을 붙이는 규칙 (목표 기능 ① W7 · 설계서 5.1.6).

이름표 넷
---------
=========  ==========================================  ==========================================
종류        붙이는 법                                     예
=========  ==========================================  ==========================================
symbol     공시는 DART 의 종목 코드 칸 그대로(dart_field) · 뉴스는 상장사 이름 사전(가장 긴 이름부터 · name_dict)
topic      아래 ``TOPICS`` 규칙 — 넣을 낱말 · 뺄 낱말     「주요사항보고서(유상증자결정)」 → 증자
term       용어사전 표제어 · 다른 이름이 제목에 그대로 나오면(3글자 이상 또는 영문 약어)  「자기주식취득결정」 → 자기주식
dtype      공시 유형 글자 A~J(DART 를 유형별로 받아 안다)  정기보고서 → A
=========  ==========================================  ==========================================

왜 용어사전 분류 22 를 그대로 주제로 쓰지 않나 — 그 분류는 **용어의 종류**(퀀트 · 규제 · 채권 …)라 「이 공시가
무슨 일인가」(배당 · 증자 · 합병)를 가르지 못한다. 그래서 주제는 사건 규칙으로 두고, 용어사전은 ``term``
이름표로 잇는다 — 용어 카드에서 「이 용어가 나온 공시」 를 찾는 길이다.

규칙 기반으로 시작하고, 표본 200건을 사람이 판정해 정밀도를 잰다(목표 0.9 · W8). 규칙을 고치면
``python -m collector.search_index build`` 가 이름표를 다시 만든다(이름표는 계산한 것 — 원본에 쓰지 않는다).
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

#: (주제, 넣을 낱말, 뺄 낱말). **위에서부터** 본다 — 한 글에 여러 주제가 붙을 수 있다.
#: 낱말은 공백을 뺀 글에서 찾는다(공시 제목은 띄어쓰기가 없고, 뉴스는 「공급 계약」 처럼 띄운다).
#: ⚠️ 뺄 낱말이 넣을 낱말보다 우선한다 — 「신주인수권부사채」 의 「인수」 가 인수합병이 되면 안 된다.
TOPICS: Sequence[Tuple[str, Sequence[str], Sequence[str]]] = (
    ("실적", ("잠정실적", "영업(잠정)실적", "매출액또는손익구조", "손익구조", "실적발표", "어닝", "분기실적", "연간실적"), ()),
    ("정기보고서", ("사업보고서", "반기보고서", "분기보고서"), ()),
    ("배당", ("배당",), ()),
    ("증자", ("유상증자", "무상증자", "제3자배정", "주주배정", "일반공모증자"), ()),
    ("감자", ("감자결정", "무상감자", "유상감자", "자본감소", "감자"), ("감자칩",)),
    ("자기주식", ("자기주식", "자사주", "주식소각", "이익소각"), ()),
    ("사채", ("전환사채", "신주인수권부사채", "교환사채", "사채권", "회사채", "조건부자본증권"), ()),
    ("주식분할", ("주식분할", "액면분할", "주식병합", "액면병합"), ()),
    ("합병·분할", ("합병", "회사분할", "분할합병", "물적분할", "인적분할", "분할결정", "주식교환", "주식이전",
                 "영업양수", "영업양도", "자산양수", "자산양도", "인수합병", "M&A"), ("주식분할", "액면분할")),
    ("지배구조", ("최대주주변경", "최대주주", "대표이사변경", "대표이사", "경영권", "사외이사", "임원선임"), ()),
    ("주주총회", ("주주총회", "주총"), ()),
    ("공급계약", ("공급계약", "판매ㆍ공급계약", "판매·공급계약", "수주"), ()),
    ("투자·출자", ("신규시설투자", "시설투자", "타법인주식및출자증권", "유형자산취득", "유형자산양수", "출자"), ()),
    ("소송·제재", ("소송", "횡령", "배임", "제재", "불성실공시", "과징금", "검찰", "압수수색", "회생절차", "파산"), ()),
    ("거래정지·상장", ("매매거래정지", "거래정지", "상장폐지", "관리종목", "상장적격성", "투자주의", "투자경고",
                    "투자위험", "단기과열", "신규상장", "추가상장", "변경상장", "재상장", "정리매매"), ()),
    ("지분", ("대량보유", "소유상황보고", "특정증권등소유", "지분공시", "지분매각", "지분인수", "지분율"), ()),
    ("임상·기술", ("임상", "기술이전", "기술수출", "품목허가", "특허", "FDA", "신약"), ()),
    ("기업설명회", ("기업설명회", "IR개최", "(IR)"), ()),
    ("회계·감사", ("감사보고서", "감사의견", "내부회계", "회계처리기준위반", "외부감사"), ()),
    ("금리", ("기준금리", "금리인상", "금리인하", "금통위", "통화정책", "FOMC", "연준"), ()),
    ("환율", ("환율", "원달러", "원·달러", "달러화"), ()),
)


def _norm(text: str) -> str:
    return unicodedata.normalize("NFKC", text or "")


def _squash(text: str) -> str:
    """공백을 뺀 글 — 낱말 찾기는 이 글에서 한다."""
    return re.sub(r"\s+", "", _norm(text))


def topics_of(text: str) -> List[Tuple[str, str]]:
    """글 → [(주제, 맞은 낱말)]. 한 주제는 한 번만."""
    s = _squash(text)
    out: List[Tuple[str, str]] = []
    for topic, inc, exc in TOPICS:
        if any(x in s for x in exc):
            continue
        hit = next((w for w in inc if _squash(w) in s), "")
        if hit:
            out.append((topic, hit))
    return out


# ==================================================
# 용어 이름표 — 용어사전 표제어 · 다른 이름
# ==================================================
_ROOT = Path(__file__).resolve().parents[1]
GLOSSARY_PATH = _ROOT / "app" / "services" / "glossary_data" / "terms.json"

#: 너무 흔해 어디에나 붙는 표제어 — 이름표가 뜻을 잃는다.
TERM_STOP = frozenset({"주식", "시장", "투자", "가격", "회사", "기업", "거래", "증권", "자산", "자본", "매출", "이익",
                       "결정", "공시", "보고서", "변경", "주주", "상장", "계약", "사업", "정정", "현황", "신고"})
_ASCII_TERM = re.compile(r"^[A-Za-z][A-Za-z0-9&/\-]{1,9}$")


@dataclass(frozen=True)
class TermEntry:
    name: str       # 찾을 글(공백 뺀 것)
    term_id: str    # 용어사전 id


def load_terms(path: Path = GLOSSARY_PATH) -> List[TermEntry]:
    """용어사전에서 이름표로 쓸 이름 — 한글 3글자 이상 · 영문 약어(2~10글자) · 흔한 말 뺌. 긴 이름부터."""
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out: Dict[str, str] = {}
    for t in d.get("terms") or []:
        # 다른 이름 종류(2026-10-04): 영어 677 · 다른 이름 141 · 약어 87 · 화면 키 30 — 화면 키는 글에 나오지 않는다
        names = [t.get("term") or ""] + [a.get("alias") or "" for a in (t.get("aliases") or [])
                                          if (a.get("kind") or "") in ("다른 이름", "약어", "영어")]
        for n in names:
            n2 = _squash(n)
            if not n2 or n2 in TERM_STOP:
                continue
            hangul = sum(1 for ch in n2 if "가" <= ch <= "힣")
            if (hangul >= 3 and hangul == len(n2)) or (_ASCII_TERM.match(n2) and n2.isupper()):
                out.setdefault(n2, t.get("id") or t.get("term") or n2)
    return sorted((TermEntry(k, v) for k, v in out.items()), key=lambda e: -len(e.name))


def terms_of(text: str, entries: Sequence[TermEntry], limit: int = 5) -> List[str]:
    """글에 나온 용어 id(긴 이름부터 · 겹친 짧은 이름은 뺀다)."""
    s = _squash(text)
    taken: List[Tuple[int, int]] = []
    out: List[str] = []
    for e in entries:
        if len(out) >= limit:
            break
        start = s.find(e.name)
        if start < 0:
            continue
        if e.name.isascii():
            # 영문 약어는 앞뒤가 영문 · 숫자가 아니어야 한다(「SPAC」 안의 「PA」 같은 것을 막는다)
            ok = False
            for m in re.finditer(re.escape(e.name), s):
                a, b = m.start(), m.end()
                if (a == 0 or not s[a - 1].isalnum() or not s[a - 1].isascii()) and \
                   (b == len(s) or not s[b].isalnum() or not s[b].isascii()):
                    ok, start = True, a
                    break
            if not ok:
                continue
        end = start + len(e.name)
        if any(a <= start < b or a < end <= b for a, b in taken):
            continue
        taken.append((start, end))
        if e.term_id not in out:
            out.append(e.term_id)
    return out


# ==================================================
# 종목 이름표 — 뉴스용 상장사 이름 사전
# ==================================================
#: 이름이 이 글자 수보다 짧으면 사전에서 뺀다 — 「대상」 · 「한국」 같은 두 글자 회사 이름은 일반 낱말과 겹친다.
MIN_NAME = 3
#: 일반 낱말과 같은 회사 이름(세 글자 이상이어도 기사에 흔히 나온다)
NAME_STOP = frozenset({"이마트", "에스엠", "대한항공우"})


@dataclass(frozen=True)
class NameEntry:
    name: str       # 공백 뺀 이름
    symbol: str


def build_name_dict(pairs: Iterable[Tuple[str, str]]) -> List[NameEntry]:
    """[(종목코드, 이름)] → 긴 이름부터.

    빼는 것: 세 글자 미만 · 흔한 낱말과 같은 이름 · 스팩 · 우선주(본주 이름이 사전에 있을 때 — 기사는 「삼성전자우」 를
    거의 쓰지 않고, 본주 이름 「삼성전자」 를 우선주 코드에 붙이면 안 된다).
    """
    rows = [(symbol, _squash(name)) for symbol, name in pairs]
    bases = {n for _, n in rows}
    out: Dict[str, str] = {}
    for symbol, n in rows:
        if len(n) < MIN_NAME or n in NAME_STOP or re.search(r"스팩|SPAC|기업인수목적", n):
            continue
        m = re.match(r"^(.+?)(\d?우[A-C]?)$", n)
        if m and m.group(1) in bases:
            continue
        out.setdefault(n, symbol)
    return sorted((NameEntry(k, v) for k, v in out.items()), key=lambda e: -len(e.name))


def symbols_of(text: str, names: Sequence[NameEntry], limit: int = 5) -> List[str]:
    """글에 나온 종목 코드 — 긴 이름부터 · 이미 잡힌 자리와 겹치는 짧은 이름은 뺀다(「삼성전자우」 안의 「삼성전자」)."""
    s = _squash(text)
    taken: List[Tuple[int, int]] = []
    out: List[str] = []
    for e in names:
        if len(out) >= limit:
            break
        start = s.find(e.name)
        if start < 0:
            continue
        end = start + len(e.name)
        if any(a <= start < b or a < end <= b for a, b in taken):
            continue
        taken.append((start, end))
        if e.symbol not in out:
            out.append(e.symbol)
    return out


def disclosure_tags(row: Dict, terms: Sequence[TermEntry]) -> List[Tuple[str, str, str]]:
    """공시 한 행 → [(종류, 이름표, 붙인 법)]."""
    out: List[Tuple[str, str, str]] = []
    if row.get("stock_code"):
        out.append(("symbol", row["stock_code"], "dart_field"))
    if row.get("pblntf_ty"):
        out.append(("dtype", row["pblntf_ty"], "dart_type"))
    text = row.get("report_nm") or ""
    for topic, word in topics_of(text):
        out.append(("topic", topic, f"rule:{word}"))
    for tid in terms_of(row.get("title") or text, terms):
        out.append(("term", tid, "glossary"))
    return out


def news_tags(row: Dict, names: Sequence[NameEntry], terms: Sequence[TermEntry],
              query_symbol: Optional[str] = None) -> List[Tuple[str, str, str]]:
    """뉴스 한 건 → 이름표. 검색어로 쓴 종목이라도 제목 · 요약에 이름이 없으면 붙이지 않는다(검색 결과가 늘 그 종목 기사는 아니다).

    요약 자리는 정책뉴스의 부제(`subtitle`)다 — 본문은 보지 않는다(긴 본문은 지나가는 말까지 이름표가 된다).
    """
    text = f"{row.get('title') or ''} {row.get('subtitle') or row.get('description') or ''}"
    out: List[Tuple[str, str, str]] = []
    for sym in symbols_of(text, names):
        out.append(("symbol", sym, "name_dict" + (":query" if sym == query_symbol else "")))
    for topic, word in topics_of(text):
        out.append(("topic", topic, f"rule:{word}"))
    for tid in terms_of(row.get("title") or "", terms):
        out.append(("term", tid, "glossary"))
    return out
