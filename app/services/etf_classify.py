"""상품 안내 — ETF 를 자산군 · 묶음으로 나누는 규칙 (2026-10-12 · 화면 키 `agent-products`)

왜 이름으로 가르나
------------------
우리 ETF 자료(공공데이터포털 「증권상품시세정보」 → 수집 DB `etf_daily`)에는 거래소의 상품 분류 칸이 없다.
있는 것은 종목 이름(`itms_nm`)과 기초지수 이름(`bss_idx_nm`)뿐이라 이름의 낱말로 가른다.

- 규칙은 위에서 아래로 **처음 맞는 것 하나**다. 차례가 곧 규칙이다 —
  혼합 → 통화 · 외화 금리 → 원화 단기 금리(현금성) → 대체자산 → 채권 → 해외 주식 → 국내 주식.
  (예: 「삼성전자채권혼합」 은 주식 · 채권 낱말이 다 있지만 혼합이 먼저다.)
- **모르는 것은 「그 밖 · 분류 못 함」** — 아무 자산군에나 넣지 않는다(말없는 fallback 금지).
- 자산군 키 다섯(국내주식 · 해외주식 · 국내채권 · 대체자산 · 현금)은 자산 배분(`app/routes/ml.py` 의
  `robo_allocation` — 오준영 님 몫)이 쓰는 글자 그대로다. 비중은 그쪽이 정본이고 상품 안내는 비중을
  계산하지 않는다 — 화면이 같은 키로 비중과 상품을 잇는다(사용자 결정 2026-10-12 · SSoT).
- 레버리지 · 인버스는 어느 자산군에서든 같은 묶음 하나로 모아 **따로 보이게** 한다 — 위험하다고 숨기지
  않는다(사용자 2026-10-12 「위험하거나 목록이 길어진다고 보여 주지 않는 것은 옳지 않다」).

실제 이름(2026-10-07 수집분 1,172개)으로 맞춰 본 함정 — 시험 `tests/test_etf_classify.py`(TC-EC)가 지킨다
- 「홍콩」 의 「콩」 이 농산물(콩)로 걸린다 → 농산물은 「대두 · 옥수수 · 농산물」 로만 본다.
- 「S&P GSCI Cash Copper」 의 Cash 가 현금성으로 걸린다 → 현금성은 「KRW Cash」 처럼 원화가 붙은 것만.
- 「Short-Term Treasury」 의 Short 를 인버스로 읽는다 → 인버스는 한글 「인버스」 로만 본다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class AssetClass:
    key: str            # 자산 배분과 같은 글자(마지막 「그 밖」 만 상품 안내에만 있다)
    label: str          # 화면 이름
    groups: tuple[str, ...]


@dataclass(frozen=True)
class EtfClass:
    asset_class: str
    group: str
    flags: tuple[str, ...]
    multiple: int = 1           # 기초지수 하루 수익률의 배수 — +2 · −1 · −2 (규제 요건이 이 칸으로 정해진다)
    single_stock: bool = False  # 단일종목 레버리지 · 인버스(이름에 「단일종목」 — 금융위가 이 표기를 의무로 함)


ASSET_CLASSES: tuple[AssetClass, ...] = (
    AssetClass("국내주식", "국내주식", ("market", "sector_theme", "strategy", "leveraged_inverse")),
    AssetClass("해외주식", "해외주식", ("market", "sector_theme", "strategy", "leveraged_inverse")),
    AssetClass("국내채권", "국내채권", ("domestic_bond", "leveraged_inverse")),
    AssetClass("대체자산", "대체자산", ("gold_silver", "commodity", "real_estate", "leveraged_inverse")),
    AssetClass("현금", "현금성", ("krw_short_rate",)),
    AssetClass("그 밖", "그 밖의 ETF", ("mixed", "foreign_bond", "currency", "unclassified", "leveraged_inverse")),
)
CLASS_BY_KEY = {c.key: c for c in ASSET_CLASSES}

GROUP_LABELS: dict[str, str] = {
    "market": "시장 대표",
    "sector_theme": "업종 · 테마",
    "strategy": "전략 · 스타일",
    "leveraged_inverse": "레버리지 · 인버스",
    "domestic_bond": "국내 채권",
    "gold_silver": "금 · 은",
    "commodity": "원자재",
    "real_estate": "부동산 · 리츠",
    "krw_short_rate": "원화 단기 금리",
    "mixed": "혼합(주식 · 채권)",
    "foreign_bond": "해외 채권",
    "currency": "통화 · 외화 금리",
    "unclassified": "분류 못 함",
}

FLAG_KEYS = ("leverage", "inverse", "futures", "synthetic", "hedged", "active", "option_income")
FLAG_LABELS: dict[str, str] = {
    "leverage": "레버리지",
    "inverse": "인버스",
    "futures": "선물",
    "synthetic": "합성",
    "hedged": "환헤지(H)",
    "active": "액티브",
    "option_income": "옵션 전략",
}
# 표시마다 한두 문장 — 상품 구조의 사실만 적는다(좋다 · 나쁘다를 말하지 않는다)
FLAG_NOTES: dict[str, str] = {
    "leverage": "기초지수의 하루 수익률을 정해진 배수(보통 2배)로 따라갑니다. 여러 날 보유하면 누적 수익률이 기초지수 누적 수익률의 배수와 달라질 수 있습니다.",
    "inverse": "기초지수의 하루 수익률을 반대 방향(−1배 또는 −2배)으로 따라갑니다. 여러 날 보유하면 누적 수익률이 달라질 수 있습니다.",
    "futures": "기초자산을 직접 담지 않고 선물 계약으로 따라갑니다. 만기마다 계약을 바꾸는 비용(롤오버)이 수익률에 영향을 줍니다.",
    "synthetic": "기초자산을 직접 담지 않고 증권사와 맺은 스와프 계약으로 따라갑니다. 계약 상대방의 위험이 있습니다.",
    "hedged": "환율 변동의 영향을 줄이는 환헤지를 합니다.",
    "active": "기초지수를 그대로 따르지 않고 운용사가 종목 · 비중을 고릅니다. 기초지수와 성과가 달라질 수 있습니다.",
    "option_income": "옵션을 팔아 분배금을 늘리는 전략(커버드콜 등)입니다. 기초자산이 크게 오를 때 이익이 제한될 수 있습니다.",
}

# ── 표시(이름 · 기초지수의 낱말) ───────────────────────────────────────────
_LEVERAGE = re.compile(r"레버리지|(?<![0-9])[23]X")
_INVERSE = re.compile(r"인버스")                     # 영문 Short 는 「Short-Term」(단기)과 겹쳐 쓰지 않는다
_FUTURES = re.compile(r"선물")
_SYNTHETIC = re.compile(r"합성")
_HEDGED = re.compile(r"[( ]H\)")                     # (H) · (합성 H)
_ACTIVE = re.compile(r"액티브")
_OPTION_NAME = re.compile(r"커버드콜|프리미엄|버퍼")
_OPTION_INDEX = re.compile(r"Covered Call|커버드콜|Premium|프리미엄|Buffer", re.I)
_SINGLE = re.compile(r"단일종목")
# 거래소 유형 「전략」 — 배당 · 커버드콜 · 동일가중 · 가치 · 성장 · 저변동 · 모멘텀 · 퀄리티 · 규모 같은 스타일(사용자 결정 2026-10-12).
# 「밸류업」(코리아 밸류업 지수)은 가치 전략이 아니라 정책 지수라 빼고, 업종 · 테마에 둔다.
_STRATEGY = re.compile(r"커버드콜|프리미엄|버퍼|배당|인컴|동일가중|로우볼|저변동|최소변동|모멘텀|퀄리티|가치주|밸류(?!업)|성장주|그로스"
                       r"|스마트베타|멀티팩터|팩터|롱숏|중소형|중형주|소형주|대형주|주주환원"
                       r"|Dividend|Equal Weight|Low Vol|Momentum|Quality|Growth|Factor|Covered Call|Premium|Buffer", re.I)

# ── 자산군(차례대로 처음 맞는 것) ────────────────────────────────────────
_MIXED = re.compile(r"혼합|TDF|TRF|자산배분|멀티에셋|올웨더|Blend|밸런스|Target ?Date|타겟데이트", re.I)
_CURRENCY = re.compile(r"달러선물|미국달러|달러인덱스|엔선물|엔화|유로선물|위안|SOFR|USD", re.I)
_KRW_SHORT = re.compile(r"MMF|머니마켓|CD금리|\(CD\)|\bCD\b|CD ?1Y|KOFR|양도성예금|단기자금|KRW Cash|콜금리|MSB|초단기|발행어음", re.I)
_REAL_ESTATE = re.compile(r"리츠|REIT|부동산|맥쿼리|Real Estate", re.I)
_GOLD_SILVER = re.compile(r"골드|금현물|KRX ?금|금선물|국제금|Gold|은선물|실버|Silver", re.I)
_COMMODITY = re.compile(r"구리|Copper|원유|WTI|Brent|브렌트|천연가스|원자재|Commodit|대두|옥수수|농산물|팔라듐|Palladium", re.I)
_BOND = re.compile(r"채권|국고채|국채|통안|회사채|크레딧|은행채|금융채|국공채|물가채|Treasury|T-?Bill|Bond|TIPS|하이일드|High Yield"
                   r"|Credit|모기지|MBS|Aggregate|Corporate|단기채|전단채", re.I)
_FOREIGN_BOND_HINT = re.compile(r"Treasury|T-?Bill|TIPS|미국|달러|U\.?S\.?|글로벌|Global|중국|China|유로|Euro|일본|이머징|신흥", re.I)
_FOREIGN = re.compile(
    r"미국|S&P|NASDAQ|나스닥|다우|Dow Jones|PHLX|필라델피아|러셀|Russell|MSCI (?!Korea)|글로벌|Global|선진|이머징|신흥|중국|차이나"
    r"|China|CSI|항셍|Hang ?Seng|홍콩|상해|Shanghai|심천|SZSE|ChiNext|차이넥스트|STAR ?50|과창판|일본|니케이|NIKKEI|토픽스|TOPIX"
    r"|인도|India|Nifty|니프티|베트남|VN30|Vietnam|유럽|Euro|STOXX|독일|DAX|영국|대만|Taiwan|TSMC|브라질|라틴|멕시코|캐나다|호주"
    r"|싱가포르|사우디|Saudi|\bUS\b|U\.S\.|World|ACWI|Indxx|MVIS|Akros|NYSE|빅테크|Big Tech|버크셔|Berkshire|일라이릴리|Eli Lilly"
    r"|BYD|테슬라|Tesla|엔비디아|NVIDIA|애플|Apple|마이크로소프트|Microsoft|아마존|Amazon|알파벳|Alphabet|팔란티어|브로드컴", re.I)
_DOMESTIC = re.compile(
    r"코스피|코스닥|KOSPI|KOSDAQ|KRX|코리아|Korea|K-|K반도체|KTOP|MKF|FnGuide|에프앤가이드|Wise|와이즈|iSelect|KEDI|KAP|KIS"
    r"|NICE|DeepSearch|밸류업|블루칩|수출주|우량업종|삼성|현대차|SK|LG|포스코|그룹", re.I)

# 「시장 대표」 기초지수(정규화한 이름). 업종 · 테마 지수(예: 코스피 200 정보기술)는 들지 않는다.
_BROAD = frozenset({
    "코스피200", "kospi200", "코스피", "코스피100", "코스닥150", "krx300", "mscikorea", "mscikorea25/50",
    "s&p500", "nasdaq100", "dowjonesindustrialaverage", "msciworld", "msciacwi", "msciemergingmarkets",
    "nikkei225", "topix", "csi300", "nifty50", "eurostoxx50", "hangsengchinaenterprises", "vn30", "msciusa",
})
_NORM_DROP = re.compile(r"\(.*?\)|net\s*total\s*return|total\s*return|price\s*return|net\s*return|index|지수|총수익"
                        r"|(?<![a-z0-9])(?:tr|pr|ntr)(?![a-z0-9])", re.I)


def _norm_index(index_name: str) -> str:
    s = _NORM_DROP.sub("", (index_name or "").lower())
    return re.sub(r"[\s\-_·]", "", s)


def _flags(name: str, index_name: str) -> tuple[str, ...]:
    out = []
    if _LEVERAGE.search(name):
        out.append("leverage")
    if _INVERSE.search(name):
        out.append("inverse")
    if _FUTURES.search(name) or _FUTURES.search(index_name):
        out.append("futures")
    if _SYNTHETIC.search(name):
        out.append("synthetic")
    if _HEDGED.search(name):
        out.append("hedged")
    if _ACTIVE.search(name):
        out.append("active")
    if _OPTION_NAME.search(name) or _OPTION_INDEX.search(index_name):
        out.append("option_income")
    return tuple(out)


def _class_and_group(name: str, index_name: str) -> tuple[str, str]:
    t = f"{name} | {index_name}"
    if _MIXED.search(t):
        return "그 밖", "mixed"
    if _CURRENCY.search(t) and not _BOND.search(index_name):
        return "그 밖", "currency"
    if _KRW_SHORT.search(t) and not _FOREIGN.search(t):
        return "현금", "krw_short_rate"
    if _REAL_ESTATE.search(t):
        return "대체자산", "real_estate"
    if _GOLD_SILVER.search(t):
        return "대체자산", "gold_silver"
    if _COMMODITY.search(t):
        return "대체자산", "commodity"
    if _BOND.search(t):
        if _FOREIGN_BOND_HINT.search(t) or _CURRENCY.search(t):
            return "그 밖", "foreign_bond"
        return "국내채권", "domestic_bond"
    if _FOREIGN.search(t):
        return "해외주식", _equity_group(t, index_name)
    if _DOMESTIC.search(t):
        return "국내주식", _equity_group(t, index_name)
    return "그 밖", "unclassified"


def _equity_group(t: str, index_name: str) -> str:
    """주식 자산군 안의 묶음 — 거래소 유형 순서(시장 대표 → 업종 · 테마 → 전략 · 스타일)."""
    if _norm_index(index_name) in _BROAD:
        return "market"
    return "strategy" if _STRATEGY.search(t) else "sector_theme"


def classify(name: str, index_name: str) -> EtfClass:
    """ETF 하나 → 자산군 · 묶음 · 표시. 순수 함수(DB · 바깥을 부르지 않는다)."""
    name, index_name = name or "", index_name or ""
    flags = _flags(name, index_name)
    asset_class, group = _class_and_group(name, index_name)
    if "option_income" in flags and asset_class in ("국내주식", "해외주식") and group in ("market", "sector_theme"):
        group = "strategy"              # 옵션 전략은 시장 대표가 아니다(지수 이름이 같아도) — 전략 · 스타일 묶음
    lev, inv = "leverage" in flags, "inverse" in flags
    multiple = -2 if (lev and inv) else -1 if inv else 2 if lev else 1
    if lev or inv:
        if "leveraged_inverse" not in CLASS_BY_KEY[asset_class].groups:
            asset_class = "그 밖"        # 레버리지 · 인버스 묶음이 없는 자산군(현금성)에 오면 「그 밖」 으로
        group = "leveraged_inverse"
    return EtfClass(asset_class, group, flags, multiple, bool(_SINGLE.search(name)))
