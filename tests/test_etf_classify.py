"""TC-EC — 상품 안내의 ETF 분류 규칙(app/services/etf_classify.py) · 2026-10-12

무엇을 지키나
- ETF 하나를 이름 + 기초지수 이름만으로 자산군(국내주식 · 해외주식 · 국내채권 · 대체자산 · 현금 · 그 밖)과
  묶음(시장 대표 · 업종 · 테마 · 전략 · 레버리지 · 인버스 …)에 넣는다. 수집 자료(공공데이터포털 증권상품시세)에는
  거래소 분류 칸이 없어서 이름으로 가른다 — 그래서 실제 이름(2026-10-07 수집분)을 그대로 사례로 둔다.
- **모르는 것은 「그 밖 · 분류 못 함」 이다** — 아무 자산군에나 넣지 않는다(말없는 fallback 금지).
- 레버리지 · 인버스는 어느 자산군이든 같은 묶음 하나로 모은다 — 숨기지 않고 따로 보이게(사용자 2026-10-12).
"""
from __future__ import annotations

import pytest

from app.services import etf_classify as ec

# (이름, 기초지수, 자산군, 묶음, 꼭 있어야 할 표시)
CASES = [
    ("KODEX 200", "코스피 200", "국내주식", "market", set()),
    ("KODEX 200TR", "코스피 200 TR", "국내주식", "market", set()),
    ("TIGER 코스닥150", "코스닥 150", "국내주식", "market", set()),
    ("KODEX MSCI Korea TR", "MSCI Korea TR Index", "국내주식", "market", set()),
    ("TIGER 미국S&P500", "S&P 500", "해외주식", "market", set()),
    ("TIGER 미국나스닥100", "NASDAQ 100", "해외주식", "market", set()),
    ("KODEX 레버리지", "코스피 200", "국내주식", "leveraged_inverse", {"leverage"}),
    ("KODEX 200선물인버스2X", "코스피 200 선물지수", "국내주식", "leveraged_inverse", {"leverage", "inverse", "futures"}),
    ("KODEX 반도체", "KRX 반도체", "국내주식", "sector_theme", set()),
    ("TIGER KTOP30", "KTOP 30", "국내주식", "sector_theme", set()),
    ("KODEX 200타겟위클리커버드콜", "코스피 200 타겟 15% 위클리 커버드콜 지수", "국내주식", "strategy", {"option_income"}),
    ("PLUS 고배당주", "FnGuide 배당주 지수", "국내주식", "strategy", set()),
    ("KODEX 코리아밸류업", "코리아 밸류업 지수", "국내주식", "sector_theme", set()),  # 「밸류업」 은 가치(전략)로 읽지 않는다
    ("KODEX 삼성전자단일종목레버리지", "KRX 삼성전자 지수", "국내주식", "leveraged_inverse", {"leverage"}),
    ("TIGER 미국필라델피아반도체나스닥", "PHLX Semiconductor Sector Index", "해외주식", "sector_theme", set()),
    ("TIGER 미국배당다우존스", "Dow Jones U.S. Dividend 100 Price Return Index", "해외주식", "strategy", set()),
    ("RISE 버크셔포트폴리오TOP10", "Solactive Berkshire Portfolio Top10 Index(PR)", "해외주식", "sector_theme", set()),
    ("KODEX 머니마켓액티브", "KAP MMF 지수(TR)", "현금", "krw_short_rate", {"active"}),
    ("KODEX CD금리액티브(합성)", "KAP 양도성예금증서(CD)금리지수(총수익지수)", "현금", "krw_short_rate", {"active", "synthetic"}),
    ("TIGER 단기통안채", "KIS MSB 6M(총수익)", "현금", "krw_short_rate", set()),
    ("ACE KRX금현물", "KRX 금현물지수", "대체자산", "gold_silver", set()),
    ("KODEX 골드선물(H)", "S&P GSCI Gold Index(TR)", "대체자산", "gold_silver", {"futures", "hedged"}),
    ("TIGER 리츠부동산인프라", "FnGuide 리츠부동산인프라", "대체자산", "real_estate", set()),
    ("TIGER 구리실물", "S&P GSCI Cash Copper Index", "대체자산", "commodity", set()),
    ("KODEX WTI원유선물인버스(H)", "S&P GSCI Crude Oil Index ER", "대체자산", "leveraged_inverse", {"inverse", "futures", "hedged"}),
    ("KODEX 종합채권(AA-이상)액티브", "KAP 한국종합채권지수", "국내채권", "domestic_bond", {"active"}),
    ("KODEX 국고채3년", "MKF 국고채지수(총수익)", "국내채권", "domestic_bond", set()),
    ("ACE 미국30년국채액티브(H)", "Bloomberg U.S Treasury 20+ Year Total Return Index", "그 밖", "foreign_bond", {"active", "hedged"}),
    ("TIGER 미국달러SOFR금리액티브(합성)", "Solactive SOFR Daily Total Return Index", "그 밖", "currency", {"active", "synthetic"}),
    ("KODEX 삼성전자SK하이닉스채권혼합50", "KAP 삼성전자SK하이닉스채권혼합50 지수", "그 밖", "mixed", set()),
    ("TIGER 미국S&P500채권혼합액티브", "S&P 500 and Short-Term Treasury 50/50 Blend Index", "그 밖", "mixed", {"active"}),
    ("TIGER 차이나항셍30", "Hang Seng China (Hong Kong-listed) 30 Index", "해외주식", "sector_theme", set()),
    ("TIGER 홍콩H지수", "Hang Seng China Enterprises Index", "해외주식", "market", set()),  # 「홍콩」 의 「콩」 을 농산물로 읽지 않는다
    ("가상 ETF", "알 수 없는 지수", "그 밖", "unclassified", set()),
]


@pytest.mark.parametrize("name,index,cls,group,must_flags", CASES)
def test_classify_real_names(name, index, cls, group, must_flags):
    got = ec.classify(name, index)
    assert (got.asset_class, got.group) == (cls, group), f"{name} · {index} → {got}"
    assert must_flags <= set(got.flags), f"{name}: 표시 {sorted(got.flags)} 에 {sorted(must_flags)} 가 있어야 한다"


def test_short_term_is_not_inverse():
    # 「Short-Term」(단기)을 인버스로 읽지 않는다 — 영문 Short 로 인버스를 가리지 않는 까닭
    got = ec.classify("TIGER 미국S&P500채권혼합액티브", "S&P 500 and Short-Term Treasury 50/50 Blend Index")
    assert "inverse" not in got.flags


def test_market_group_only_for_broad_indices():
    # 코스피 200 의 업종 지수는 「시장 대표」 가 아니다
    assert ec.classify("TIGER 200 IT", "코스피 200 정보기술").group == "sector_theme"
    assert ec.classify("KODEX 200", "코스피 200").group == "market"


def test_asset_class_keys_are_allocation_keys_plus_other():
    # 다섯 키는 자산 배분 화면(robo_allocation)이 쓰는 글자 그대로 — 화면이 비중과 상품을 같은 키로 잇는다
    keys = [c.key for c in ec.ASSET_CLASSES]
    assert keys[:5] == ["국내주식", "해외주식", "국내채권", "대체자산", "현금"]
    assert keys[5] == "그 밖"
    assert len(keys) == 6


def test_every_group_has_label_and_belongs_to_class():
    for c in ec.ASSET_CLASSES:
        assert c.label and c.groups, c
        for g in c.groups:
            assert g in ec.GROUP_LABELS, (c.key, g)
    # 주식 두 자산군은 거래소 유형 순서(시장 대표 → 업종 · 테마 → 전략 · 스타일)로 묶는다(사용자 결정 2026-10-12)
    for key in ("국내주식", "해외주식"):
        assert ec.CLASS_BY_KEY[key].groups[:3] == ("market", "sector_theme", "strategy"), key
    # 레버리지 · 인버스 묶음은 모든 자산군에 있다(어느 자산군의 레버리지 · 인버스도 따로 보인다)
    for c in ec.ASSET_CLASSES:
        if c.key != "현금":
            assert "leveraged_inverse" in c.groups, c.key


def test_flag_notes_cover_every_flag():
    for f in ec.FLAG_KEYS:
        assert ec.FLAG_NOTES.get(f), f
        assert ec.FLAG_LABELS.get(f), f


def test_unknown_is_not_silently_domestic():
    got = ec.classify("새로운 ETF", "Some Unknown Index")
    assert got.asset_class == "그 밖" and got.group == "unclassified"


@pytest.mark.parametrize("name,index,multiple,single", [
    ("KODEX 200", "코스피 200", 1, False),
    ("KODEX 레버리지", "코스피 200", 2, False),
    ("KODEX 인버스", "코스피 200 선물지수", -1, False),
    ("KODEX 200선물인버스2X", "코스피 200 선물지수", -2, False),
    ("KODEX 삼성전자단일종목레버리지", "KRX 삼성전자 지수", 2, True),
])
def test_multiple_and_single_stock(name, index, multiple, single):
    # 배수는 이름의 「레버리지 · 2X」 와 「인버스」 로 — 규제 요건(사전교육 · 기본예탁금)이 이 두 칸으로 정해진다
    got = ec.classify(name, index)
    assert (got.multiple, got.single_stock) == (multiple, single), (name, got)
