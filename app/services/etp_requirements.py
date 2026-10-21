"""레버리지 · 인버스 ETF 를 실제로 사려면 필요한 것 — 규제 상수표 한 곳 (2026-10-12 기준 · 화면 키 `agent-products`)

왜 한 곳에 두나
---------------
규제가 자주 바뀐다 — 2020-09 지수 레버리지 예탁금 · 교육, 2025-12 해외 상장 교육, 2026-05 단일종목 상장,
2026-07-31 단일종목 예탁금 현금 3천만 원. 상품 안내 응답의 「사려면 필요한 것」 칸과 안내 문장은 모두 이 표에서
만든다 — 숫자를 글에 따로 적지 않는다(시험 TC-PG 가 표를 바꾸면 글도 바뀌는지 본다). 규제가 바뀌면 이 표의 숫자 ·
`since` · `AS_OF` · 출처를 함께 고친다.

무엇을 말하나 · 말하지 않나
---------------------------
우리는 판매업자가 아니다 — 이 표는 우리에게 걸리는 의무가 아니라 「증권사에서 사려면 이것을 거친다」 는 사실 안내다
(ETF 범위 조사서 2.3절). 증권사마다 더 엄격할 수 있다. 발표만 된 것(교육 3시간 · 매매 단위 20좌)은 숫자 칸에
넣지 않고 `planned` 에 「시행 여부 미확인」 으로만 적는다. 원문 사본을 어디에 두는지는 `docs/3차/데이터수집/` 안내를 본다.
"""
from __future__ import annotations

AS_OF = "2026-10-12"   # 이 표를 원문과 마지막으로 맞춘 날(KST)

SOURCES: dict[str, dict[str, str]] = {
    "fsc_2020_05_18": {
        "title": "금융위원회 보도자료 「ETF·ETN 시장을 보다 건전하게 발전시키겠습니다」(2020-05-18)",
        "url": "https://www.fsc.go.kr/no010101/74332",
    },
    "samsung_2020_notice": {
        "title": "삼성증권 공지 「레버리지ETP(ETF/ETN) 매매거래제도 변경」(2020)",
        "url": "https://www.samsungpop.com/ux/kor/customer/notice/notice/noticeViewContent.do?MenuSeqNo=16993",
    },
    "fss_2026_03_18": {
        "title": "금융감독원 보도자료 「고위험 레버리지(ETF‧ETN) 투자, 각별한 주의가 필요합니다」(2026-03-18)",
        "url": "https://www.fss.or.kr/fss/bbs/B0000188/view.do?nttId=215143&menuNo=200218",
    },
    "fcpa_supervisory_reg": {
        "title": "금융소비자 보호에 관한 감독규정 제11조(적정성 원칙 대상 집합투자증권)",
        "url": "https://www.law.go.kr/LSW/admRulInfoP.do?admRulSeq=2100000285608",
    },
    "fsc_2026_05_15": {
        "title": "금융위원회 보도참고 「단일종목 레버리지·인버스 상품(ETF·ETN) 도입에 따른 투자자 유의사항 안내」(2026-05-15)",
        "url": "https://www.fsc.go.kr/no010101/86910",
    },
    "fsc_2026_07_16": {
        "title": "금융위원회 보도자료 「관계기관 합동, 단일종목 레버리지 상품(ETF·ETN) 보완방안 마련」(2026-07-16)",
        "url": "https://www.fsc.go.kr/no010101/87353",
    },
    "fsc_2026_07_24": {
        "title": "금융위원회 보도참고 「단일종목 레버리지 상품(ETF·ETN) 기본예탁금 강화 조기시행 방안 안내」(2026-07-24)",
        "url": "https://www.fsc.go.kr/no010101/87403",
    },
    "fsc_2026_07_28": {
        "title": "금융위원회 보도자료 「단일종목 관련 금융투자업권 간담회 개최」(2026-07-28)",
        "url": "https://www.fsc.go.kr/no010101/87417",
    },
}

# 키 — 상품 안내 응답의 `requirement` 칸 값. 배수 · 단일종목 두 칸으로 정해진다(`requirement_key`).
REQUIREMENTS: dict[str, dict] = {
    "leveraged_2x": {
        "label": "레버리지 · 인버스 2배",
        "applies_to": "기초자산의 하루 수익률을 2배 또는 −2배로 따르는 ETF(주식 지수 · 채권 · 원자재 · 통화 모두)",
        "education_hours": 1,
        "education_note": "금융투자교육원 온라인 사전교육(레버리지 ETP) 1시간",
        "deposit_krw": 10_000_000,
        "deposit_cash_only": False,
        "deposit_note": "현금 또는 대용증권(시가의 70% 인정) — 증권사가 거래 경험에 따라 완화 · 강화할 수 있음",
        "other": ("신용거래로 살 수 없음 · 위탁증거금 100%",),
        "planned": (),
        "since": "2020-09-07",
        "sources": ("fsc_2020_05_18", "samsung_2020_notice", "fss_2026_03_18"),
        "certainty": "확인(원문) — 시행일은 증권사 공지로 확인",
    },
    "inverse_1x": {
        "label": "인버스(−1배)",
        "applies_to": "기초자산의 하루 수익률을 −1배로 따르는 ETF",
        "education_hours": None,
        "education_note": "레버리지 ETP 사전교육 대상 아님",
        "deposit_krw": None,
        "deposit_cash_only": False,
        "deposit_note": "기본예탁금 대상 아님",
        "other": ("증권사에서 투자자 정보 확인(금융소비자보호법 적정성 원칙)과 파생 ETF 거래 신청을 거쳐야 함",),
        "planned": (),
        "since": "2020-09-07",
        "sources": ("fsc_2020_05_18", "samsung_2020_notice", "fcpa_supervisory_reg"),
        "certainty": "확인(증권사 공지 · 감독규정 원문) — 거래소 · 금융투자협회 규정 조문은 미확인",
    },
    "single_stock": {
        "label": "단일종목 레버리지 · 인버스",
        "applies_to": "한 종목의 하루 수익률을 배수로 따르는 상품(이름에 「단일종목」 · 2026-05-27 상장)",
        "education_hours": 2,
        "education_note": "기본 1시간 + 심화 1시간",
        "deposit_krw": 30_000_000,
        "deposit_cash_only": True,
        "deposit_note": "현금만 인정 — 주식 · ETF · 채권 같은 대용증권과 매도대금담보대출은 빠지고, 판 돈은 결제일(T+2)에 "
                        "들어온 뒤 인정 · 거래 경험에 따른 완화 없음",
        "other": (
            "신용 · 미수거래로 살 수 없음",
            "국내 주식 가격제한폭이 ±30% 라 이론상 하루에 최대 60% 까지 잃을 수 있음(금융위원회 2026-05-15)",
            "신규 상장 잠정 중단 · 광고 금지(2026-07-16부터)",
        ),
        "planned": (
            "사례 중심 심화교육 1시간을 더해 3시간 — 2026-07-16 발표 「8월 중」 · 시행 여부 미확인",
            "매매 단위 1좌 → 20좌 — 2026-07-16 발표 · 시행 여부 미확인",
        ),
        "since": "2026-07-31",
        "sources": ("fsc_2026_05_15", "fsc_2026_07_16", "fsc_2026_07_24", "fsc_2026_07_28"),
        "certainty": "확인(원문) — 「예정」 칸은 시행 여부 미확인",
    },
}

NOTICE = "증권사마다 요건이 더 엄격할 수 있습니다 — 사기 전에 이용하는 증권사 안내를 확인해 주세요."


def requirement_key(multiple: int, single_stock: bool) -> str | None:
    """배수 · 단일종목 → 요건 키. 1배 상품은 None(이 표의 대상이 아니다).

    법령 정의는 「1배를 초과한 배율 · 음의 배율」 이고 상한은 ±2배다 — 그래서 |배수| ≥ 2 는 모두 레버리지 요건,
    −1배는 따로다(교육 · 예탁금 대상 아님).
    """
    if single_stock:
        return "single_stock"
    if abs(multiple) >= 2:
        return "leveraged_2x"
    if multiple == -1:
        return "inverse_1x"
    return None


def won(n: int) -> str:
    """10_000_000 → 「1,000만 원」 · 만 원 단위로 안 떨어지면 「12,345원」."""
    man, rest = divmod(n, 10_000)
    return f"{man:,}만 원" if rest == 0 else f"{n:,}원"


def _need(r: dict) -> str:
    """요건 하나를 한 문장으로 — 숫자는 표에서만 가져온다."""
    parts = []
    if r["education_hours"]:
        parts.append(f"사전교육 {r['education_hours']}시간")
    if r["deposit_krw"]:
        parts.append(f"{'현금 ' if r['deposit_cash_only'] else ''}기본예탁금 {won(r['deposit_krw'])}")
    if not parts:
        return f"{r['label']} — 사전교육 · 기본예탁금 대상은 아닙니다. 다만 {r['other'][0]}."
    return f"{r['label']} — 사려면 {'과 '.join(parts)}이 필요합니다(시행 {r['since']})."


def multiple_label(multiple: int) -> str:
    """2 → 「2배」 · −1 → 「−1배」 — 화면 글의 배수 표기를 한 곳에서."""
    return f"{'−' if multiple < 0 else ''}{abs(multiple)}배"


def risk_note(multiple: int | None = None) -> str:
    """위험 구조 한 줄 — 배수를 모르면 목록 칸 머리 글, 알면 그 상품 서랍의 고정 띠(닫기 없음).

    문구를 한 곳에 둬서 목록 머리와 서랍 띠가 갈라지지 않게 한다(금융감독원 2026-03-18 「단기 투자용」 원문).
    """
    if multiple is None:
        return ("레버리지 · 인버스는 기초자산의 하루 수익률을 배수로 따르는 단기 투자용 상품입니다 — 여러 날 이어진 수익률은 "
                "배수와 다를 수 있고, 오르내림을 되풀이하면 기초자산이 제자리여도 손실이 날 수 있습니다(음의 복리).")
    m = multiple_label(multiple)
    return (f"이 상품은 기초자산의 하루 수익률을 {m}로 따르는 단기 투자용 상품입니다 — 여러 날 이어진 수익률은 "
            f"‘기초자산 × {m}’와 다를 수 있고, 오르내림을 되풀이하면 기초자산이 제자리여도 손실이 날 수 있습니다"
            "(음의 복리 · 금융감독원 2026-03-18).")


def need(key: str | None) -> str | None:
    """요건 키 → 한 문장(숫자는 표에서만) · 키가 없으면 None."""
    return _need(REQUIREMENTS[key]) if key else None


def notes() -> list[str]:
    """레버리지 · 인버스 칸 머리에 싣는 안내 — 위험 구조 한 줄 + 요건마다 한 줄 + 기준일."""
    return [
        risk_note(),
        *(_need(REQUIREMENTS[k]) for k in ("leveraged_2x", "single_stock", "inverse_1x")),
        f"요건은 {AS_OF} 기준 금융위원회 · 금융감독원 원문으로 확인한 것입니다. {NOTICE}",
    ]


def public() -> dict:
    """응답에 싣는 모양 — 출처는 키 대신 제목 · 주소로 풀어 준다."""
    items = {}
    for key, r in REQUIREMENTS.items():
        items[key] = {
            **{k: v for k, v in r.items() if k != "sources"},
            "other": list(r["other"]),
            "planned": list(r["planned"]),
            "sources": [{"key": s, **SOURCES[s]} for s in r["sources"]],
        }
    return {"as_of": AS_OF, "notice": NOTICE, "items": items}
