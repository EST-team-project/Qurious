"""용어사전 시험 (TC-GL) — 요구 P01-①-1 「화면의 금융 용어를 누르면 서버가 뜻 · 쉬운 뜻 · 연관 용어를 돌려주고, 용어를 검색할 수 있다」.

무엇을 지키는가 —
용어는 자료 글 넷 → 용어 파일 → DB 표 → API 로 흐른다. 단계마다 조용히 틀어질 수 있는 곳을 건다.

1. 글자 규칙: 빌드와 앱이 같은 규칙으로 글자를 다듬는다(「샤프 비율」 = 「샤프비율」 · 초성).
2. 자료 읽기: 표 · HTML · 자바스크립트 모양이 조금 달라도 용어를 빠뜨리거나 칸을 섞지 않는다.
3. 합치기: 이름이 같으면 한 용어, 별칭이 같다고는 합치지 않는다. 뜻 한 줄과 자세한 뜻은 같은 자료에서만.
4. 용어 파일: 커밋된 파일이 자료를 다시 빌드한 것과 같고, 표의 제약(길이 · 유일 · 외래 키)을 지킨다.
   화면의 용어 키 55개가 모두 용어 하나로 풀린다 — 설명창이 API 로 넘어가도 빠지는 키가 없다.
5. 적재 · 조회(DB): 같은 판이면 다시 넣지 않고, 파일이 바뀌면 표가 파일과 같아진다. 검색 순위가 규칙대로 선다.

DB 가 필요한 시험은 `QURIOUS_TEST_DATABASE_URL` 이 있을 때만 돈다(scripts/personal/test.ps1).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from app.services import glossary
from app.services.glossary_text import chosung, escape_like, is_chosung_query, norm
from scripts import glossary_build as gb

ROOT = Path(__file__).resolve().parents[1]
DB_URL = os.environ.get("QURIOUS_TEST_DATABASE_URL", "")
needs_db = pytest.mark.skipif(not DB_URL, reason="QURIOUS_TEST_DATABASE_URL 이 없다 — scripts/personal/test.ps1 로 돌린다")


# ── 1. 글자 규칙 ─────────────────────────────────────────────────────

@pytest.mark.parametrize("a, b", [
    ("샤프 비율", "샤프비율"),
    ("EV/EBITDA", "ev ebitda"),
    ("Price-to-Earnings Ratio", "price to earnings ratio"),
    ("win_rate", "Win Rate"),
    ("T+2 결제", "t2결제"),
    ("샤프", "샤프"),          # 자모가 풀린 모양(NFD) — 눈에는 같아도 다른 글자다
])
def test_norm_makes_the_same_name_the_same_string(a, b):
    """TC-GL-01 · 띄어쓰기 · 구두점 · 대소문자 · 자모 풀림이 달라도 같은 이름은 같은 찾기용 모양이 된다."""
    assert norm(a) == norm(b)


def test_norm_keeps_different_names_different():
    """TC-GL-01b · (보존 확인) 다른 이름까지 같아지지는 않는다."""
    assert norm("샤프 비율") != norm("샤프지수")
    assert norm("PER") != norm("PBR")


def test_chosung_and_chosung_query():
    """TC-GL-02 · 한글은 첫소리로, 나머지는 그대로. 초성 검색은 첫소리 두 글자 이상일 때만 켠다."""
    assert chosung("시가총액") == "ㅅㄱㅊㅇ"
    assert chosung("샤프 비율") == "ㅅㅍㅂㅇ"
    assert chosung("PER 밴드") == "perㅂㄷ"
    assert is_chosung_query("ㅅㄱㅊㅇ") and is_chosung_query(" ㅅㅍ ")
    assert not is_chosung_query("ㅅ")             # 한 글자는 용어 절반이 걸린다
    assert not is_chosung_query("시가") and not is_chosung_query("ㅅ가")


def test_escape_like_neutralises_wildcards():
    """TC-GL-03 · 검색어의 % · _ 가 「아무 글자」 로 읽히지 않는다."""
    assert escape_like("50%") == "50\\%"
    assert escape_like("win_rate") == "win\\_rate"
    assert escape_like("a\\b") == "a\\\\b"


# ── 2. 자료 읽기 (합성 글) ───────────────────────────────────────────

VOCA = """# 단어장

## 처음에 잡아둘 말

| 말 | 한자·영어 | 말의 구조 | 초보자용 뜻·예시 |
| --- | --- | --- | --- |
| 주식 | 株式 / Stock, Share | `株`는 밑동이에요. | 회사의 작은 지분이에요. 가격이 가치와 늘 같지는 않아요. |
| 자사주·자기주식 | Treasury Stock | 회사가 자기 주식을 다시 사서 가진 것이에요. |

### 숫자를 읽는 최소 공식

| 보고 싶은 것 | 가장 단순한 계산 | 읽을 때 주의할 점 |
| --- | --- | --- |
| 주가수익비율(PER) | 주가 ÷ EPS | 적자면 의미가 약해요. |

| 용어 | 영어 전체 이름 | 뜻 풀이 |
| --- | --- | --- |
| PER | Price Earnings Ratio | **PER(Price Earnings Ratio, 주가수익비율)**: 이익과 주가를 비교합니다. |

## 함께 알아두면 좋은 우리말

| 말 | 영어·한자 | 쉬운 뜻 |
| --- | --- | --- |
| 주식 | Stock, Share / 株式 | 회사의 작은 주인표예요. |

## 주식 거래에서 쓰는 기본 용어

| 말 | 영어·한자 | 자세한 뜻 풀이 |
| --- | --- | --- |
| 매수 | Buy / 買收 | 주식을 사는 일이에요. |

## 시장을 부르는 줄임말과 투자 은어

| 말 | 사람들이 쓰는 뜻 | 주의할 점 |
| --- | --- | --- |
| 국장 | 국내 주식시장을 줄여 부르는 말이에요. | 한 덩어리로 판단하지 않아요. |
| ISP | Internet Service Provider | 인터넷 접속을 제공하는 사업자예요. |
"""


def _by_term(raws):
    out = {}
    for r in raws:
        out.setdefault(r.term, []).append(r)
    return out


def test_voca_tables_are_read_by_header_not_by_position():
    """TC-GL-04 · 단어장 — 머리글로 칸을 가린다(한자와 영어 · 말의 구조 · 뜻), 줄임말 표의 영어 이름 줄, 계산식 붙이기."""
    raws = _by_term(gb.parse_voca(VOCA))
    stock = raws["주식"]
    assert [r.category for r in stock] == ["basics", "basics"]
    assert stock[0].english == "Stock, Share" and stock[0].hanja == "株式"          # 「한자 / 영어」
    assert stock[1].english == "Stock, Share" and stock[1].hanja == "株式"          # 「영어 / 한자」 — 차례가 바뀌어도 같다
    assert stock[0].origin_note == "株는 밑동이에요." and stock[0].long.startswith("회사의 작은 지분")
    assert stock[1].short == "회사의 작은 주인표예요." and stock[1].long == ""
    treasury = raws["자사주·자기주식"][0]                                            # 「말의 구조」 칸을 뺀 세 칸 줄
    assert treasury.origin_note == "" and treasury.long.startswith("회사가 자기 주식")
    assert treasury.aliases == ["자사주", "자기주식"]
    per = raws["PER"][0]
    assert per.category == "abbr" and per.long == "이익과 주가를 비교합니다."            # 굵은 머리말을 뗀다
    assert (per.formula, per.caution) == ("주가 ÷ EPS", "적자면 의미가 약해요.")       # 계산식 표의 「주가수익비율(PER)」 — 괄호 안 이름으로 붙는다
    assert raws["매수"][0].category == "trading" and raws["매수"][0].long == "주식을 사는 일이에요."
    slang = raws["국장"][0]
    assert slang.category == "slang" and slang.short.startswith("국내 주식시장") and slang.caution.startswith("한 덩어리")
    isp = raws["ISP"][0]                                                           # 둘째 칸이 영어 이름인 줄
    assert isp.english == "Internet Service Provider" and isp.short.startswith("인터넷 접속") and isp.caution == ""


def test_voca_formula_attaches_by_name_too_and_only_to_that_term():
    """TC-GL-04b · 계산식은 이름이 같은 용어에도 붙고, 이름도 별칭도 다른 용어에는 붙지 않는다."""
    text = VOCA.replace("| PER | Price Earnings Ratio |", "| 주가수익비율 | Price Earnings Ratio |")
    raws = _by_term(gb.parse_voca(text))
    per = raws["주가수익비율"][0]
    assert per.formula == "주가 ÷ EPS" and per.caution == "적자면 의미가 약해요."
    assert all(r.formula == "" for term, rs in raws.items() if term != "주가수익비율" for r in rs)


FINANCE = """# 투자분석 핵심 용어집

## 3. 기본적 분석 (Fundamental Analysis) 용어

### 3-3. 포트폴리오·리스크

| 용어 | 한자/약어 | 영어 | 아주 쉬운 뜻 | 실전 예시 |
|---|---|---|---|---|
| 샤프 비율 | SR | Sharpe Ratio | 위험 1단위당 초과수익 | 1.0 이상이면 준수 |
| **벤처캐피탈 (VC)** | 冒險資本 | Venture Capital | 초기 기업에 투자 | 시리즈 A |

## 11. 자주 혼동하는 용어 비교

| 비교 쌍 | A | B | 핵심 차이 |
|---|---|---|---|
| PER vs PBR | 이익 | 순자산 | 다르다 |

# 한자 병기 및 어원 사전 — 금융·투자·회계 용어

## 1. 경제·거시 용어

### 거시경제 (巨視經濟) / 미시경제 (微視經濟)
| 항목 | 내용 |
|------|------|
| **한자** | 巨視經濟 / 微視經濟 |
| **읽기** | 巨(클 거)·視(볼 시) / 微(작을 미)·視 |
| **어원** | 🇯🇵 영어 macroeconomics 의 번역어. |

## 6. 증권·투자 용어

### 주가수익비율 (株價收益比率, PER)
| 항목 | 내용 |
|------|------|
| **읽기** | 株價·收益·比率 |
| **어원** | 🆕 영어의 번역어. |

## 8. 분석·리스크 용어

### 위험 (危險) / 리스크 (risk)
| 항목 | 내용 |
|------|------|
| **읽기** | 危(위태할 위)·險(험할 험) |
| **어원** | 📜 고전 한자어. |

### 포트폴리오 (portfolio) — 한자 참고
| 항목 | 내용 |
|------|------|
| **어원** | 이탈리아어 portafolio. |
"""


def test_finance_glossary_and_origin_dictionary():
    """TC-GL-05 · 용어집 — 다섯 칸 표만 용어로 읽고(비교 쌍 표 제외), 한자 어원 사전의 제목 모양 넷을 가린다."""
    raws = _by_term(gb.parse_finance(FINANCE))
    assert "PER vs PBR" not in raws                                                # 비교 쌍은 용어가 아니다
    sharpe = raws["샤프 비율"][0]
    assert (sharpe.source, sharpe.category) == ("finance", "quant")                # 「포트폴리오·리스크」 절은 퀀트로
    assert sharpe.english == "Sharpe Ratio" and sharpe.aliases == ["SR"] and sharpe.example == "1.0 이상이면 준수"
    vc = raws["벤처캐피탈"][0]                                                       # 굵게 · 괄호 약어
    assert vc.aliases == ["VC"] and vc.hanja == "冒險資本"
    macro, micro = raws["거시경제"][0], raws["미시경제"][0]                            # 둘 다 한자가 있으면 짝을 이루는 두 용어
    assert (macro.hanja, micro.hanja) == ("巨視經濟", "微視經濟")
    assert macro.reading == "巨(클 거)·視(볼 시)" and micro.reading == "微(작을 미)·視"   # 읽기를 이름 차례대로 나눈다
    assert macro.etymology.startswith("[일본식 한자어]")                             # 기호를 글로 푼다
    per = raws["주가수익비율"][0]
    assert per.hanja == "株價收益比率" and per.aliases == ["PER"]                    # 괄호 안의 약어는 별칭
    risk = raws["위험"][0]
    assert "리스크" not in raws and risk.aliases == ["리스크", "risk"]                # 한자 없는 이름은 같은 말의 외래어 표기
    pf = raws["포트폴리오"][0]                                                       # 꼬리말을 뗀다
    assert pf.aliases == ["portfolio"] and pf.reading == ""


LECTURE_HTML = """
<dl class="glossary">
  <div class="glossary-item">
    <dt>분산투자 <small>Diversification · 分散投資</small></dt>
    <dd>
      서로 다른 자산에 나누어 투자하는
      방법입니다.
    </dd>
  </div>
  <div class="glossary-item" data-glossary-manual-only>
    <dt>
      위험 <small>Investment Risk · 危險 · Risk</small>
    </dt>
    <dd>
      <p>손실을 볼 수 있는 <strong>가능성</strong>입니다.</p>
      <p>여러 종류로 나눕니다.</p>
      <template class="glossary-rich-detail"><p>설명창이 복제해 쓰는 글</p></template>
      <div class="glossary-infographic"><span>그림 글자</span></div>
    </dd>
  </div>
</dl>
<div class="not-glossary"><dt>딴 것</dt><dd>무시</dd></div>
"""

LECTURE_JS = """
const COMMON_ENTRIES = [
  { title: '기준금리', aliases: 'Policy Rate · Base Rate', detail: ['중앙은행이 정하는 금리입니다.', '상품 금리와 같지는 않습니다.'] },
  { title: '베타', alias: 'β · Beta', paragraphs: ['시장 민감도입니다. \\'과거\\' 통계입니다.'] },
  {
    title: '이더리움',
    aliases: 'Ethereum · ETH',
    detailHtml: `
      <p>지분증명으로 <strong>바뀌었습니다</strong>.</p>
      <h3>제목</h3>
      <p>둘째 문단.</p>`,
  },
];
"""


def test_lecture_html_and_script_entries():
    """TC-GL-06 · 강의 사이트 — 용어 항목만 읽고, 문단을 나누고, 복제용 틀은 건너뛴다. 스크립트의 세 모양도 읽는다."""
    html = _by_term(gb.parse_lecture_html(LECTURE_HTML, "01"))
    assert set(html) == {"분산투자", "위험"}
    assert html["분산투자"][0].long == "서로 다른 자산에 나누어 투자하는 방법입니다."      # 줄바꿈 · 들여쓰기를 한 칸으로
    assert html["분산투자"][0].english == "Diversification" and html["분산투자"][0].hanja == "分散投資"
    risk = html["위험"][0]
    assert risk.long == "손실을 볼 수 있는 가능성입니다.\n\n여러 종류로 나눕니다."        # 문단 둘 · 복제용 틀과 그림 글자는 없다
    assert risk.english == "Investment Risk" and risk.aliases == ["Risk"] and risk.category == "derivatives"

    js = _by_term(gb.parse_lecture_js(LECTURE_JS))
    assert js["기준금리"][0].long == "중앙은행이 정하는 금리입니다.\n\n상품 금리와 같지는 않습니다."
    assert js["기준금리"][0].aliases == ["Base Rate"]
    assert js["베타"][0].long == "시장 민감도입니다. '과거' 통계입니다."                  # 따옴표 이스케이프
    assert js["이더리움"][0].long == "지분증명으로 바뀌었습니다.\n\n둘째 문단." and js["이더리움"][0].aliases == ["ETH"]


def test_qurious_terms_need_a_category():
    """TC-GL-07 · 화면 용어 — 키 · 제목 · 설명을 읽고, 분류가 없는 새 키가 있으면 빌드를 멈춘다."""
    js = 'const TERMS = {\n  mdd:    { title: "MDD (최대낙폭)", body: "고점 대비 \\"최대\\" 하락입니다." },\n  rsi: { title: "RSI", body: "모멘텀 지표." },\n};\n'
    raws = gb.parse_qurious(js)
    assert [(r.key, r.term, r.aliases) for r in raws] == [("mdd", "MDD", ["최대낙폭"]), ("rsi", "RSI", [])]
    assert raws[0].app_note == '고점 대비 "최대" 하락입니다.'
    with pytest.raises(SystemExit):
        gb.parse_qurious(js.replace("rsi:", "brand_new_key:"))


# ── 3. 합치기 ────────────────────────────────────────────────────────

def _raw(term, source, category="basics", **kw):
    return gb.Raw(term, source, category, **kw)


def test_same_name_merges_but_shared_alias_does_not():
    """TC-GL-08 · 이름이 같으면(띄어쓰기 무시) 한 용어 — 별칭이 같다고는 합치지 않는다."""
    groups = gb.group([
        _raw("캔들 차트", "voca"), _raw("캔들차트", "finance"),
        _raw("보통주·우선주", "voca", aliases=["보통주", "우선주"]), _raw("우선주", "finance"),
    ])
    assert sorted(len(g) for g in groups) == [1, 1, 2]
    assert {g[0].term for g in groups} == {"캔들 차트", "보통주·우선주", "우선주"}


def test_same_as_and_supplement_sources_join_existing_terms(monkeypatch):
    """TC-GL-08b · 이름이 다른 같은 말은 SAME_AS 로, 화면 용어 · 한자 어원 사전은 괄호 안 이름으로 이미 있는 용어에 붙는다."""
    monkeypatch.setattr(gb, "SAME_AS", {"샤프지수": "샤프 비율", "순이익·당기순이익": "순이익"})
    groups = {g[0].term: g for g in gb.group([
        _raw("순이익·당기순이익", "voca"), _raw("순이익", "finance"),
        _raw("샤프 비율", "finance"), _raw("샤프지수", "qurious", key="sharpe"),
        _raw("MDD", "finance"), _raw("MDD", "qurious", aliases=["최대낙폭"], key="mdd"),
        _raw("PER", "finance"), _raw("주가수익비율", "finance-origin", aliases=["PER"]),
        _raw("모의투자", "qurious", key="paper_trading"),
    ])}
    assert set(groups) == {"순이익", "샤프 비율", "MDD", "PER", "모의투자"}       # 대표 이름은 묶음 열쇠와 같은 이름
    assert [r.source for r in groups["순이익"]] == ["finance", "voca"]           # 먼저 읽힌 단어장 줄이 뒤로 간다
    assert [r.source for r in groups["PER"]] == ["finance", "finance-origin"]


def test_merge_takes_summary_and_definition_from_one_source():
    """TC-GL-09 · 뜻 한 줄과 자세한 뜻은 같은 자료에서만 — 다른 자료의 풀이는 이름표를 붙여 따로 남긴다.

    「내재가치」 는 용어집에서는 기업의 적정 가격이고 강의에서는 옵션의 내재가치다. 섞으면 앞뒤가 안 맞는 풀이가 된다.
    """
    term = gb.merge([
        _raw("내재가치", "finance", "fundamental", english="Intrinsic Value", short="기업의 진짜 적정 가격", example="DCF", where="가치평가"),
        _raw("내재가치", "lecture", "derivatives", long="옵션을 지금 행사했을 때의 이익입니다. 음수는 없습니다.", where="01일차 용어"),
        _raw("내재가치", "qurious", "app", app_note="이 앱에서는 DCF 값입니다.", key="intrinsic"),
    ])
    assert (term["summary"], term["definition"], term["lead_source"]) == ("기업의 진짜 적정 가격", "", "finance")
    assert term["notes"] == [{"source": "lecture", "label": "01일차 용어", "text": "옵션을 지금 행사했을 때의 이익입니다. 음수는 없습니다."}]
    assert term["category"] == "fundamental" and term["sources"] == ["finance", "lecture", "qurious"]
    assert term["app_note"] == "이 앱에서는 DCF 값입니다."
    assert {"alias": "intrinsic", "kind": "화면 키"} in term["aliases"] and {"alias": "Intrinsic Value", "kind": "영어"} in term["aliases"]


def test_merge_fallbacks_for_single_source_terms():
    """TC-GL-09b · 자세한 뜻만 있으면 첫 문장이 뜻 한 줄 · 화면 용어뿐이면 앱 설명의 첫 문장 · 어원 사전뿐이면 한자 풀이."""
    lecture = gb.merge([_raw("듀레이션", "lecture", "bond", long="금리 민감도입니다. 클수록 가격이 크게 움직입니다.")])
    assert lecture["summary"] == "금리 민감도입니다." and lecture["definition"].endswith("움직입니다.")
    app = gb.merge([_raw("모의투자", "qurious", "app", app_note="가상의 잔고로 매매합니다. 위험이 없습니다.", key="paper_trading")])
    assert (app["summary"], app["definition"], app["lead_source"]) == ("가상의 잔고로 매매합니다.", "", "qurious")
    origin = gb.merge([_raw("발행", "finance-origin", "basics", hanja="發行", reading="發(펼 발)·行(다닐 행)", etymology="[일본식 한자어] 내보냄.")])
    assert origin["summary"] == "한자 풀이 — 發(펼 발)·行(다닐 행)" and origin["definition"] == "[일본식 한자어] 내보냄."
    assert origin["origin_note"] == "" and origin["lead_source"] == "finance"      # 어원이 곧 본문이라 두 번 싣지 않는다


def test_overrides_fix_a_source_text_before_the_summary_is_derived(monkeypatch):
    """TC-GL-09c · 자료의 글을 고치지 않고 바로잡는다 — 바로잡은 글에서 뜻 한 줄이 나온다(옛 글이 남지 않는다)."""
    monkeypatch.setattr(gb, "OVERRIDES", {"모의계좌": {"app_note": "PostgreSQL 에만 있는 가상 잔고입니다. 실제 돈이 아닙니다.", "category": "quant"}})
    term = gb.merge([_raw("모의계좌", "qurious", "app", app_note="MongoDB 에만 있는 가상 잔고입니다.", key="virtual_account")])
    assert term["app_note"].startswith("PostgreSQL") and term["summary"] == "PostgreSQL 에만 있는 가상 잔고입니다."
    assert term["category"] == "quant"


@pytest.mark.parametrize("text, expected", [
    ("Stock, Share", ["Stock", "Share"]),
    ("Creation / Redemption", ["Creation", "Redemption"]),
    ("Open·High·Low·Close (OHLC)", ["Open", "High", "Low", "Close", "OHLC"]),
    ("Net Interest Margin (NIM)", ["Net Interest Margin", "NIM"]),            # 괄호 안 약어도 이름이다
    ("Low Volatility(로우 볼래틸러티)", ["Low Volatility", "로우 볼래틸러티"]),    # 괄호 안 읽는 법도 찾는 이름이 된다
    ("FinTech (Finance + Technology)", ["FinTech"]),                          # 말의 짜임을 푼 괄호는 이름이 아니다
    ("거래상대방 위험: Counterparty Risk", []),                                  # 「이름표: 값」 은 이름이 아니다
    ("소재·부품·장비", ["소재·부품·장비"]),                                       # 한글은 가운뎃점에서 나누지 않는다
    ("EV/EBITDA", ["EV/EBITDA"]),                                             # 띄지 않은 빗금은 한 이름
    ("(H)", ["(H)"]),                                                         # 괄호가 곧 이름
    ("σ (sigma)", ["σ", "sigma"]),
    ("", []),
])
def test_name_parts_split_lists_and_lift_parentheses(text, expected):
    """TC-GL-22 · 이름 칸의 글을 이름 조각으로 나눈다 — 늘어놓은 영문은 나누고, 괄호 안 약어 · 읽는 법은 따로 떼고, 이름이 아닌 것은 버린다.

    예전에는 「Low Volatility(로우 볼래틸러티)」 가 통째로 한 이름이라 「Low Volatility」 로도 「로우볼」 로도 찾지 못했고,
    「소재·부품·장비」 가 셋으로 나뉘어 「장비」 로 찾으면 「소부장」 이 나왔다.
    """
    assert gb.name_parts(text) == expected


@pytest.mark.parametrize("alias, kind", [
    ("PER", "약어"), ("EV/EBITDA", "약어"), ("Rf", "약어"), ("bps", "약어"), ("GWh", "약어"), ("Div.", "약어"), ("β", "약어"),
    ("Risk", "영어"), ("Front-month", "영어"), ("K-Fold", "영어"), ("Return on Equity", "영어"),
    ("주가수익비율", "다른 이름"), ("債權", "다른 이름"), ("MG새마을금고", "다른 이름"),
])
def test_alias_kind_tells_abbreviations_from_english_names(alias, kind):
    """TC-GL-22b · 별칭의 종류 — 짧고 대문자 위주면 약어, 낱말이면 영어 이름, 한글 · 한자가 들면 다른 이름.

    예전에는 영문 열두 자 이하를 모두 「약어」 로 불러 Risk · Equity 가 약어였고, 긴 영어 이름은 「다른 이름」 이었다.
    """
    assert gb.alias_kind(alias) == kind


def test_english_name_holds_only_latin_text():
    """TC-GL-22c · 영어 이름 칸에는 영문만 — 괄호 안 한글은 떼고, 영문이 없으면 비운다(그 말은 별칭으로 간다)."""
    assert gb.english_name("Liquidity(리퀴디티)") == "Liquidity"
    assert gb.english_name("Buy Now Pay Later (후불결제)") == "Buy Now Pay Later"
    assert gb.english_name("Net Interest Margin (NIM)") == "Net Interest Margin (NIM)"       # (보존 확인) 영문 괄호는 그대로
    assert gb.english_name("자기자본이익률") == "" and gb.english_name("") == ""
    term = gb.merge([_raw("ROE", "lecture", "quant", english="자기자본이익률", aliases=["Return on Equity"], long="자기자본으로 번 이익의 비율입니다.")])
    assert term["english"] == "Return on Equity"                                            # 영어로 판정된 별칭을 쓴다
    assert {"alias": "자기자본이익률", "kind": "다른 이름"} in term["aliases"]


def test_alias_goes_to_the_term_that_names_it_whole(monkeypatch):
    """TC-GL-24 · 같은 이름을 두 용어가 내세우면 — 화면 키 → 통째로 적은 쪽 → 늘어놓은 쪽 차례로 임자를 정한다.

    진 쪽에는 「함께 쓰는 이름」(shared_names)으로 남는다 — 이름으로 한 건을 찾으면 임자가 나오고, 검색에서는 두 용어가 다 나온다.
    예전(먼저 읽은 쪽이 갖는다)에는 「괴리율 | Premium / Discount」 가 앞에 있으면 「Premium」 이 프리미엄이 아니라 괴리율로 갔다.
    """
    for name in ("OVERRIDES", "SAME_AS", "RENAME", "NOT_ALIAS"):
        monkeypatch.setattr(gb, name, {})
    monkeypatch.setattr(gb, "read_sources", lambda: [
        _raw("괴리율", "finance", "fund", english="Premium / Discount", short="시장가격과 순자산가치의 차이"),
        _raw("프리미엄", "lecture", "derivatives", english="Premium", long="옵션을 살 때 내는 값입니다."),
        _raw("섹터형", "lecture", "fund", english="Sector ETF", long="한 업종에 투자하는 상품입니다."),
        _raw("섹터 ETF", "qurious", "fund", app_note="산업군을 묶은 ETF 입니다.", key="sector_etf"),
    ])
    by = {t["term"]: t for t in gb.build()["terms"]}
    assert {"alias": "Premium", "kind": "영어"} in by["프리미엄"]["aliases"]          # 통째로 적은 쪽이 임자
    assert [a["alias"] for a in by["괴리율"]["aliases"]] == ["Discount"] and by["괴리율"]["shared_names"] == ["Premium"]
    assert {"alias": "sector_etf", "kind": "화면 키"} in by["섹터 ETF"]["aliases"]    # 화면 키가 영어 이름보다 먼저다
    assert by["섹터형"]["aliases"] == [] and by["섹터형"]["shared_names"] == ["Sector ETF"]
    assert all("_split" not in t for t in by.values())                              # 임자를 정할 때만 쓴 칸은 파일에 가지 않는다


def test_stale_curation_lines_stop_the_build(monkeypatch):
    """TC-GL-25 · 사람이 적은 규칙(RENAME · NOT_ALIAS)이 자료에 없는 이름을 가리키면 빌드가 멈춘다 — 규칙이 말없이 꺼지지 않게."""
    monkeypatch.setattr(gb, "NOT_ALIAS", {**gb.NOT_ALIAS, "레이 달리오": {"자료에 없는 말"}})
    with pytest.raises(SystemExit):
        gb.build()
    monkeypatch.undo()
    monkeypatch.setattr(gb, "RENAME", {**gb.RENAME, "자료에 없는 제목(X)": "X"})
    with pytest.raises(SystemExit):
        gb.build()


# ── 4. 용어 파일 (실제 자료) ─────────────────────────────────────────

@pytest.fixture(scope="module")
def built() -> dict:
    return gb.build()


@pytest.fixture(scope="module")
def seed() -> dict:
    return glossary.read_seed()[0]


def test_committed_file_equals_a_fresh_build(built):
    """TC-GL-10 · 커밋된 용어 파일 = 자료를 지금 다시 빌드한 것. 자료나 빌드 규칙만 고치고 파일을 안 올리면 실패한다."""
    assert gb.OUT.read_bytes().decode("utf-8").replace("\r\n", "\n") == gb.render(built), \
        "python scripts/glossary_build.py 를 돌려 terms.json 을 다시 만든다"
    assert gb.render(gb.build()) == gb.render(built)                 # 다시 돌려도 같은 글자 — 체크섬이 흔들리지 않는다


def test_seed_checksum_ignores_line_endings(tmp_path):
    """TC-GL-11 · 체크섬은 줄끝(CRLF · LF)과 무관하다 — Windows 에서 받은 파일이라고 다시 넣지 않는다. 빌드의 셈과도 같다."""
    text = gb.OUT.read_bytes().decode("utf-8").replace("\r\n", "\n")
    lf, crlf = tmp_path / "lf.json", tmp_path / "crlf.json"
    lf.write_bytes(text.encode("utf-8"))
    crlf.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
    assert glossary.read_seed(lf)[1] == glossary.read_seed(crlf)[1] == gb.checksum(text)


def test_every_term_is_complete_and_ids_are_unique(seed):
    """TC-GL-12 · 용어마다 ID · 이름 · 뜻 한 줄 · 아는 분류 · 아는 자료가 있고, ID 는 겹치지 않으며 고정 주소와 부딪히지 않는다."""
    terms = seed["terms"]
    categories = {c["code"] for c in seed["categories"]}
    sources = {s["code"] for s in seed["sources"]}
    ids = [t["id"] for t in terms]
    assert len(ids) == len(set(ids)) and all(ids)
    for t in terms:
        assert t["term"] and t["summary"], t["id"]
        assert t["category"] in categories and t["lead_source"] in sources and set(t["sources"]) <= sources, t["id"]
        assert t["lead_source"] in t["sources"], t["id"]
        assert {n["source"] for n in t["notes"]} <= sources, t["id"]
        assert not t["english"] or any(c.isascii() and c.isalpha() for c in t["english"]), t["id"]   # 영어 이름 칸에는 영문
        assert {a["kind"] for a in t["aliases"]} <= {"약어", "영어", "다른 이름", "화면 키"}, t["id"]
        assert not any(":" in a["alias"] for a in t["aliases"]), t["id"]                          # 「이름표: 값」 은 이름이 아니다
    names = {norm(t["id"]) for t in terms} | {norm(a["alias"]) for t in terms for a in t["aliases"]}
    assert not names & set(glossary.RESERVED_IDS)                    # /api/glossary/categories · /meta 와 같은 이름의 용어는 없다
    assert sum(c["terms"] for c in seed["categories"]) == len(terms)


def test_descriptions_and_other_concepts_do_not_become_names(seed):
    """TC-GL-23 · (실제 자료) 이름 옆의 설명은 별칭이 아니고, 제목의 괄호가 다른 개념을 가르면 따로 선 용어다.

    예전에는 「투자자」 로 찾으면 「레이 달리오」 가 나왔고(강의 용어의 곁말이 사람 소개였다), 「신용위험」 의 뜻 한 줄이
    CDS 계약의 풀이였다(강의 제목 「신용위험(CDS)」 에서 괄호를 떼자 「신용위험」 과 한 용어가 됐다).
    """
    terms = seed["terms"]
    owner = {norm(a["alias"]): t["term"] for t in terms for a in t["aliases"]} | {norm(t["term"]): t["term"] for t in terms}
    for word in ("투자자", "브리지워터 창립자", "미국 투자운용사", "작가", "강연가", "PF", "IR", "장비", "부품"):
        assert norm(word) not in owner, word
    assert owner[norm("소재부품장비")] == "소부장" and owner[norm("신협")] == "신용협동조합" and owner["nim"] == "예대마진"
    by = {t["term"]: t for t in terms}
    assert by["CDS"]["summary"].startswith("CDS") and "CDS" not in by["신용위험"]["summary"]
    assert owner["ytm"] == "만기수익률" and owner[norm("Yield to Maturity")] == "만기수익률"
    assert "YTM" not in [a["alias"] for a in by["수익률"]["aliases"]]
    assert by["장외"]["summary"].startswith("장외")                                  # 「장내거래는 …」 으로 시작하지 않는다
    # 같은 이름의 다른 풀이는 이름표에 자료의 제목이 붙는다 — 어느 뜻의 풀이인지 읽는 사람이 가린다
    assert {n["label"] for n in by["채권"]["notes"]} >= {"03일차 용어 · 채권(債權)", "03일차 용어 · 채권(債券)"}


def test_screen_term_keys_all_resolve_to_one_term(seed):
    """TC-GL-13 · 화면의 용어 키(core.js 의 TERMS)가 모두 용어 하나로 풀린다 — 설명창이 API 로 넘어가도 빠지는 키가 없다."""
    keys = [r.key for r in gb.parse_qurious((ROOT / "public" / "js" / "core.js").read_text(encoding="utf-8"))]
    assert len(keys) >= 50 and len(keys) == len(set(keys))
    _, _, _, aliases = glossary.seed_rows(seed)
    owner = {a["alias_norm"]: a["term_id"] for a in aliases}
    missing = [k for k in keys if norm(k) not in owner]
    assert missing == []
    by_id = {t["id"]: t for t in seed["terms"]}
    assert all(by_id[owner[norm(k)]]["app_note"] for k in keys)      # 화면 용어의 앱 설명이 그 용어에 실려 있다


def test_seed_rows_fit_the_table_constraints(seed):
    """TC-GL-14 · 용어 파일이 표의 제약을 지킨다 — 칸 길이 · 이름의 유일 · 외래 키. 적재가 DB 에서야 터지지 않게 미리 본다."""
    from app.models import GlossaryAlias, GlossaryCategory, GlossarySource, GlossaryTerm

    categories, sources, terms, aliases = glossary.seed_rows(seed)
    for model, rows in ((GlossaryCategory, categories), (GlossarySource, sources), (GlossaryTerm, terms), (GlossaryAlias, aliases)):
        for column in model.__table__.columns:
            limit = getattr(column.type, "length", None)
            if limit:
                longest = max((len(r[column.name]) for r in rows if column.name in r), default=0)
                assert longest <= limit, f"{model.__tablename__}.{column.name}: {longest} > {limit}"
    norms = [a["alias_norm"] for a in aliases]
    assert len(norms) == len(set(norms))                             # 이름 하나는 용어 하나만 가리킨다
    term_ids = {t["id"] for t in terms}
    assert {a["term_id"] for a in aliases} <= term_ids
    assert {t["category_code"] for t in terms} <= {c["code"] for c in categories}
    assert {t["lead_source_code"] for t in terms} <= {s["code"] for s in sources}
    primary = {a["term_id"] for a in aliases if a["kind"] == glossary.ALIAS_KIND_PRIMARY}
    assert primary == term_ids                                       # 모든 용어가 대표 이름으로 찾아진다
    for t in terms:
        assert t["name_text"].startswith("|") and t["name_text"].endswith("|") and t["sort_key"] in t["name_text"]
    # 함께 쓰는 이름 — 별칭 표에는 임자만 들어가고(이름 하나 = 용어 하나), 검색용 글에는 그 이름을 쓰는 용어마다 들어간다.
    owner = {a["alias_norm"]: a["term_id"] for a in aliases}
    rows = {t["id"]: t for t in terms}
    shared = [(t["id"], norm(name)) for t in seed["terms"] for name in t["shared_names"]]
    assert shared                                                     # 실제 자료에 있다(「NAV」 — 순자산가치 · 기준가격)
    for term_id, key in shared:
        assert f"|{key}|" in rows[term_id]["name_text"] and owner[key] != term_id, (term_id, key)


def test_rows_checksum_follows_the_rows_not_only_the_file(seed, monkeypatch):
    """TC-GL-14b · 「다시 넣을지」 의 기준은 넣을 행이다 — 파일이 같아도 검색용 칸을 만드는 규칙이 바뀌면 값이 달라진다.

    파일 체크섬만 보던 때에는, 찾기용 모양 · 초성 규칙을 고쳐도 파일이 그대로라 표가 옛 값으로 남았다.
    """
    before = glossary.rows_checksum(glossary.seed_rows(seed))
    assert before == glossary.rows_checksum(glossary.seed_rows(seed))              # (보존 확인) 같은 파일 · 같은 규칙이면 같은 값
    monkeypatch.setattr(glossary, "chosung", lambda text: "규칙이 바뀜")
    assert glossary.rows_checksum(glossary.seed_rows(seed)) != before


# ── 검색 순위 (DB 없이) ──────────────────────────────────────────────

PER_ROW = {"sort_key": "per", "chosung": "per", "name_text": "|per|priceearningsratio|주가수익비율|", "body_text": "주가가 1주당 이익의 몇 배인지"}
EPS_ROW = {"sort_key": "eps", "chosung": "eps", "name_text": "|eps|earningspershare|주당순이익|", "body_text": "주식 1주당 이익. per 과 함께 본다."}
CFO_ROW = {"sort_key": "cfo", "chosung": "cfo", "name_text": "|cfo|cashflowfromoperations|", "body_text": "영업활동 현금흐름"}
CAP_ROW = {"sort_key": "시가총액", "chosung": "ㅅㄱㅊㅇ", "name_text": "|시가총액|marketcapitalization|marketcap|", "body_text": "현재 주가에 발행주식 수를 곱한 값"}
PROP_ROW = {"sort_key": "동산", "chosung": "ㄷㅅ", "name_text": "|동산|movables|", "body_text": "토지와 건물이 아닌 재산(personal property)"}
BAND_ROW = {"sort_key": "밴드차트", "chosung": "ㅂㄷㅊㅌ", "name_text": "|밴드차트|", "body_text": "per이 움직인 범위를 띠로 그린다"}


@pytest.mark.parametrize("query, row, expected", [
    ("PER", PER_ROW, (0, "이름")),                      # 대표 이름과 정확히 같다(대소문자 무시)
    ("주가 수익 비율", PER_ROW, (0, "이름")),              # 다른 이름과 정확히 같다(띄어쓰기 무시)
    ("시가", CAP_ROW, (1, "이름")),                      # 대표 이름이 검색어로 시작한다
    ("market", CAP_ROW, (2, "이름")),                   # 영어 이름이 검색어로 시작한다
    ("수익비", PER_ROW, (3, "이름")),                     # 한글은 이름 가운데도 찾는다
    ("earning", PER_ROW, (3, "이름")),                  # 영문 네 글자 이상도 이름 가운데를 찾는다
    ("per", EPS_ROW, (4, "본문")),                       # 이름 가운데의 per(earnings-PER-share)는 안 보고, 풀이에 나온 것으로 잡는다
    ("per", CFO_ROW, None),                             # o-per-ations 는 걸리지 않는다
    ("per", PROP_ROW, None),                            # 풀이의 per-sonal · pro-per-ty 도 걸리지 않는다 — 짧은 영문은 낱말로 있을 때만
    ("per", BAND_ROW, (4, "본문")),                      # (보존 확인) 「per이」 처럼 한글이 붙은 것은 낱말이다
    ("proper", PROP_ROW, (4, "본문")),                   # (보존 확인) 영문 네 글자 이상은 낱말의 일부여도 찾는다
    ("발행주식", CAP_ROW, (4, "본문")),
    ("ㅅㄱㅊㅇ", CAP_ROW, (1, "초성")),
    ("ㄱㅊ", CAP_ROW, (2, "초성")),
    ("ㅂㄷ", CAP_ROW, None),
    ("없는말", CAP_ROW, None),
    ("  ", CAP_ROW, None),
])
def test_match_rank_rules(query, row, expected):
    """TC-GL-15 · 검색 순위 — 정확히 같음 0 · 대표 이름 머리 1 · 다른 이름 머리 2 · 이름 가운데 3 · 본문 4 · 초성."""
    assert glossary.match_rank(query, row) == expected


def test_fixed_paths_are_registered_before_the_name_path():
    """TC-GL-16 · `/categories` · `/meta` 가 `/{name}` 보다 먼저 등록돼 있다 — 뒤바뀌면 그 주소가 「없는 용어」 로 404 가 난다."""
    from app.routes import glossary as routes

    paths = [r.path for r in routes.router.routes]
    assert paths.index("/api/glossary/categories") < paths.index("/api/glossary/{name}")
    assert paths.index("/api/glossary/meta") < paths.index("/api/glossary/{name}")
    assert set(glossary.RESERVED_IDS) == {p.rsplit("/", 1)[1] for p in paths if p.count("/") == 3 and "{" not in p}


# ── 5. 적재 · 조회 (DB) ──────────────────────────────────────────────

@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def db():
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    import app.models  # noqa: F401
    from app.models.base import Base

    engine = create_async_engine(DB_URL, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


def _small_seed(tmp_path: Path, **change) -> Path:
    """실제 파일에서 용어 몇 개만 남긴 작은 용어 파일 — 적재 규칙을 재는 데는 이것으로 충분하다."""
    data = glossary.read_seed()[0]
    keep = {"per", "pbr", "샤프-비율", "시가총액", "mdd"}
    data["terms"] = [t for t in data["terms"] if t["id"] in keep]
    for key, value in change.items():
        data[key] = value(data) if callable(value) else value
    path = tmp_path / f"terms-{len(list(tmp_path.iterdir()))}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return path


@needs_db
@pytest.mark.anyio
async def test_load_is_skipped_when_checksum_is_unchanged(db, tmp_path):
    """TC-GL-17 · 처음에는 넣고, 같은 파일이면 다시 넣지 않는다(적재 이력이 한 줄 그대로)."""
    from sqlalchemy import func, select

    from app.models import GlossaryAlias, GlossaryLoad, GlossaryTerm

    path = _small_seed(tmp_path)
    first = await glossary.ensure_loaded(db, path)
    assert (first["status"], first["terms"]) == ("넣음", 5)
    second = await glossary.ensure_loaded(db, path)
    assert second["status"] == "건너뜀" and second["checksum"] == first["checksum"]
    assert (await db.execute(select(func.count()).select_from(GlossaryLoad))).scalar_one() == 1
    assert (await db.execute(select(func.count()).select_from(GlossaryTerm))).scalar_one() == 5
    assert (await db.execute(select(func.count()).select_from(GlossaryAlias))).scalar_one() == first["aliases"]


@needs_db
@pytest.mark.anyio
async def test_reload_when_only_the_search_column_rule_changes(db, tmp_path, monkeypatch):
    """TC-GL-17b · 파일이 같아도 검색용 칸을 만드는 규칙이 바뀌면 다시 넣는다 — 표에 옛 규칙의 값이 남지 않는다."""
    from sqlalchemy import select

    from app.models import GlossaryLoad, GlossaryTerm

    path = _small_seed(tmp_path)
    assert (await glossary.ensure_loaded(db, path))["status"] == "넣음"
    monkeypatch.setattr(glossary, "chosung", lambda text: "규칙이 바뀜")
    again = await glossary.ensure_loaded(db, path)
    assert again["status"] == "넣음"
    assert set((await db.execute(select(GlossaryTerm.chosung))).scalars().all()) == {"규칙이 바뀜"}
    loads = (await db.execute(select(GlossaryLoad.checksum, GlossaryLoad.rows_checksum).order_by(GlossaryLoad.id))).all()
    assert loads[0].checksum == loads[1].checksum and loads[0].rows_checksum != loads[1].rows_checksum   # 파일은 같고 넣은 행이 다르다
    assert (await glossary.ensure_loaded(db, path))["status"] == "건너뜀"                                  # (보존 확인) 그 뒤에는 다시 건너뛴다


@needs_db
@pytest.mark.anyio
async def test_reload_makes_tables_equal_to_the_new_file(db, tmp_path):
    """TC-GL-18 · 파일이 바뀌면 표가 새 파일과 같아진다 — 고친 뜻은 고쳐지고, 사라진 용어 · 옮겨 간 이름은 남지 않는다."""
    from sqlalchemy import select

    from app.models import GlossaryAlias, GlossaryLoad, GlossaryTerm

    await glossary.ensure_loaded(db, _small_seed(tmp_path))

    def changed(data):
        terms = [t for t in data["terms"] if t["id"] != "pbr"]                    # 용어 하나가 사라지고
        per = next(t for t in terms if t["id"] == "per")
        per["summary"] = "고친 뜻"                                                 # 뜻이 바뀌고
        mdd = next(t for t in terms if t["id"] == "mdd")
        moved = [a for a in mdd["aliases"] if a["alias"] == "최대낙폭"]
        mdd["aliases"] = [a for a in mdd["aliases"] if a["alias"] != "최대낙폭"]
        per["aliases"] = per["aliases"] + moved                                   # 이름 하나가 다른 용어로 옮겨 간다
        return terms

    result = await glossary.ensure_loaded(db, _small_seed(tmp_path, terms=changed))
    assert (result["status"], result["terms"]) == ("넣음", 4)
    ids = set((await db.execute(select(GlossaryTerm.id))).scalars().all())
    assert ids == {"per", "샤프-비율", "시가총액", "mdd"}
    assert (await db.execute(select(GlossaryTerm.summary).where(GlossaryTerm.id == "per"))).scalar_one() == "고친 뜻"
    owner = (await db.execute(select(GlossaryAlias.term_id).where(GlossaryAlias.alias_norm == norm("최대낙폭")))).scalar_one()
    assert owner == "per"
    assert (await db.execute(select(GlossaryAlias).where(GlossaryAlias.term_id == "pbr"))).first() is None
    loads = (await db.execute(select(GlossaryLoad.checksum).order_by(GlossaryLoad.id))).scalars().all()
    assert len(loads) == 2 and loads[0] != loads[1]                                # 이력은 쌓인다 — 언제 어떤 판이 들어왔나


@needs_db
@pytest.mark.anyio
async def test_unknown_file_format_is_refused(db, tmp_path):
    """TC-GL-19 · 모르는 판의 파일은 넣지 않고 알린다 — 추측해서 넣지 않는다."""
    with pytest.raises(RuntimeError):
        await glossary.ensure_loaded(db, _small_seed(tmp_path, format_version=99))


@needs_db
@pytest.mark.anyio
async def test_search_lookup_categories_and_meta(db):
    """TC-GL-20 · 실제 용어 파일을 넣고 — 검색 순위 · 화면 키로 단건 · 분류 · 판 정보가 요구대로 나온다."""
    info = await glossary.ensure_loaded(db)
    assert info["status"] == "넣음" and info["terms"] >= 700

    found = await glossary.search(db, "PER", limit=5)
    assert found["items"][0]["id"] == "per" and found["items"][0]["match"] == "이름"
    assert [i["term"] for i in found["items"][:2]] == ["PER", "PER 밴드"]            # 정확히 같음 → 대표 이름 머리
    every_per = [i["term"] for i in (await glossary.search(db, "per", limit=100))["items"]]
    assert "PER" in every_per and not {"동산", "법인", "부동산"} & set(every_per)    # 풀이의 property · person 은 PER 이 아니다
    nav = [i["term"] for i in (await glossary.search(db, "NAV"))["items"]]
    assert {"순자산가치", "기준가격"} <= set(nav[:3])                                # 이름을 함께 쓰는 두 용어가 다 나온다
    assert (await glossary.get_term(db, "NAV"))["term"] in ("순자산가치", "기준가격")  # 이름으로 한 건을 찾으면 임자 하나
    assert (await glossary.search(db, "ㅅㄱㅊㅇ"))["items"][0]["term"] == "시가총액"
    assert (await glossary.search(db, "샤프비율"))["items"][0]["id"] == "샤프-비율"     # 띄어쓰기 없이
    assert (await glossary.search(db, "100%"))["total"] < info["terms"]            # % 가 「아무 글자」 로 읽히지 않는다
    assert (await glossary.search(db, "zzz없는말zzz"))["total"] == 0

    everything = await glossary.search(db, "", limit=100)
    assert everything["total"] == info["terms"] and len(everything["items"]) == 100
    page2 = await glossary.search(db, "", limit=100, offset=100)
    assert not {i["id"] for i in everything["items"]} & {i["id"] for i in page2["items"]}
    only_app = await glossary.search(db, "", category="app")
    assert only_app["total"] >= 5 and {i["category"]["code"] for i in only_app["items"]} == {"app"}

    by_key = await glossary.get_term(db, "sharpe")                                  # 화면의 용어 키
    assert by_key["id"] == "샤프-비율" and by_key["matched"] == {"alias": "sharpe", "kind": "화면 키"}
    assert by_key["app_note"] and any(s["lead"] for s in by_key["sources"])
    assert (await glossary.get_term(db, "샤프 비율"))["id"] == (await glossary.get_term(db, "Sharpe Ratio"))["id"] == "샤프-비율"
    assert all(a["kind"] != glossary.ALIAS_KIND_PRIMARY for a in by_key["aliases"])
    assert await glossary.get_term(db, "없는용어") is None and await glossary.get_term(db, "  ") is None

    cats = await glossary.categories(db)
    assert cats["total_terms"] == info["terms"] and [c["code"] for c in cats["categories"]][:2] == ["basics", "trading"]
    meta = await glossary.meta(db)
    assert meta["loaded"] and meta["in_sync"] and meta["checksum"] == info["checksum"]
    assert {s["code"] for s in meta["sources"]} == {"voca", "finance", "lecture", "qurious"}
    assert sum(1 for s in meta["sources"] if s["terms"] > 0) == 4


@needs_db
@pytest.mark.anyio
async def test_route_returns_404_for_unknown_name(db):
    """TC-GL-21 · 없는 용어 · 칸 길이를 넘는 이름은 404 — 화면은 이 응답으로 「사전에 없는 말」 을 가린다."""
    from fastapi import HTTPException

    from app.routes import glossary as routes

    await glossary.ensure_loaded(db)
    assert (await routes.get_term("mdd", db))["term"] == "MDD"
    for name in ("없는용어", "x" * 121):
        with pytest.raises(HTTPException) as err:
            await routes.get_term(name, db)
        assert err.value.status_code == 404


def test_search_line_says_which_name_matched():
    """TC-GL-26 · 검색 결과 한 줄이 「어느 이름으로 맞았나」 를 준다(API-GLOS-01 · matched · 2026-10-02).

    「per」 로 PCE 가 나온 까닭(영어 이름 Personal … 이 per 로 시작)을 화면이 보여 줄 수 있게 — 순위 규칙(match_rank)과 같은 기준.
    """
    pce = [("PCE", "대표 이름", "pce"), ("Personal Consumption Expenditure", "영어", "personalconsumptionexpenditure"),
           ("개인소비지출", "다른 이름", "개인소비지출")]
    pick = glossary.pick_matched_alias
    assert pick("per", 2, "이름", "PCE", pce) == {"alias": "Personal Consumption Expenditure", "kind": "영어"}
    sharpe = [("샤프 비율", "대표 이름", "샤프비율"), ("SR", "약어", "sr"), ("sharpe", "화면 키", "sharpe"),
              ("샤프지수", "다른 이름", "샤프지수")]
    assert pick("SR", 0, "이름", "샤프 비율", sharpe) == {"alias": "SR", "kind": "약어"}
    assert pick("sharpe", 0, "이름", "샤프 비율", sharpe) == {"alias": "sharpe", "kind": "화면 키"}
    assert pick("샤프", 1, "이름", "샤프 비율", sharpe) == {"alias": "샤프 비율", "kind": "대표 이름"}
    assert pick("ㅅㅍ", 1, "초성", "샤프 비율", sharpe) == {"alias": "샤프 비율", "kind": "초성"}
    assert pick("위험", 4, "본문", "샤프 비율", sharpe) == {"alias": None, "kind": "본문"}
    # 같은 순위에서 여럿 맞으면 대표 이름 → 약어 → 영어 차례 · 짧은 것
    assert pick("샤프", 3, "이름", "샤프 비율", sharpe)["alias"] == "샤프 비율"


# ── 화면 (2026-10-02 · 화면 설계 결정 ① ②) — 브라우저 없이 연결만 본다 ─────────────────────
_PUB = Path(__file__).resolve().parents[1] / "public"


def _read(rel: str) -> str:
    return (_PUB / rel).read_text(encoding="utf-8")


def test_glossary_screen_is_wired():
    """TC-GL-27 · 용어사전 화면이 메뉴 · 화면 자리 · 모듈로 이어져 있다(「금융 필수 지식」 › 연습 › 용어사전)."""
    core, app, fin, gl = _read("js/core.js"), _read("app.html"), _read("js/finlearn.js"), _read("js/glossary.js")
    assert '{ key: "fin-glossary"' in core and '"fin-glossary":' in core, "메뉴 · 사용법 안내"
    assert 'data-view="fin-glossary"' in app and 'id="glossary-root"' in app, "화면 자리"
    assert 'view === "fin-glossary"' in fin and 'import("/js/glossary.js")' in fin, "화면이 켜질 때 모듈을 부른다"
    for api_path in ("/api/glossary/categories", "/api/glossary?limit=", "/api/glossary/${"):
        assert api_path in gl, api_path
    assert "termCardHtml" in gl, "용어 한 장은 서랍과 같은 카드"


def test_screen_term_chips_open_the_glossary_card():
    """TC-GL-28 · 화면의 용어 칩(설명창)이 용어사전 카드를 연다 — 모양 셋 · 화면보다 커지지 않음 · 마이페이지 설정."""
    core, card, css, my = _read("js/core.js"), _read("js/termcard.js"), _read("css/qurious.css"), _read("js/mypage.js")
    hook = core[core.index("function openTermModal"):core.index("function closeTermModal")]
    assert "window.QTerm" in hook and "fallback: term" in hook, "칩 → 카드 · 못 찾으면 화면의 짧은 설명"
    assert hook.index("window.QTerm") < hook.index("if (!term) return"), "용어사전에만 있는 말도 열린다"
    assert "window.QTerm = {" in card, "설명창(core.js)이 부를 전역"
    for view in ('"drawer"', '"modal-sm"', '"modal-lg"'):
        assert view in card, view
    assert 'qurious.termView' in card, "고른 모양은 이 브라우저에 저장"
    # 화면 크기를 넘지 않게(2026-10-02 피드백 — 창이 화면을 자르거나 가득 채우던 문제)
    assert "100vw" in css and "100dvh" in css and "overflow-y: auto" in css
    assert "TERM_VIEWS" in my and "setTermView" in my, "마이페이지 화면 설정이 같은 목록을 쓴다"
    assert 'kind === "화면 키"' in card, "화면 키(sharpe)는 사람에게 보이는 이름 대신 쓰지 않는다"

