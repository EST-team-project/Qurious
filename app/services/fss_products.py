"""상품 안내 — 금융감독원 「금융상품 한눈에」 오픈 API 실시간 연동 (예금 · 적금 · 연금저축 · 2026-10-12)

약관 — 금융상품통합비교공시시스템 오픈 API 이용약관(2026-10-12 원문 다시 확인 · 조사서 「신용평가 CSV 인제스트」 <표 7>)
- 제9조 「실시간으로 제공되는 정보를 이용자의 서비스와 연동할 수 있을 뿐이며, 정보를 복제 또는 저장하거나 전송할 수 없습니다」
  → 이 모듈은 받은 값을 캐시 · DB · 파일 어디에도 두지 않는다. 부를 때마다 받아 그 응답으로만 돌려준다
  (시험 TC-FL 의 정적 규칙이 캐시 · DB · 파일 쓰기를 막는다).
- 제9조 화면에 「금융상품통합비교공시시스템(금융감독원) 금융회사 상품정보」 를 사용한 결과임을 명시 → 응답마다 `source_notice`.
- 제5조 인증키는 발급받은 사람만 · 1인 1키 → 키는 이 서버를 돌리는 사람의 설정(`FINANCE_SUPERVISORY_API_KEY`) 하나뿐이고
  저장소에 넣지 않는다. 사용자 화면에는 키도 설정 이름도 보이지 않는다(관리자에게만 고칠 곳을 알린다 — 라우트).
- 제7조 개인 1일 10,000건 · 12개월 안 쓰면 삭제 → 한 번 볼 때 쪽 수에 상한(`MAX_PAGES`)을 두고, 넘으면 잘랐다고 알린다.

요청 · 응답 모양 — 원문 명세(「상세 및 테스트」 정기예금 · 적금 · 연금저축 쪽 · 2026-10-12)
  GET https://finlife.fss.or.kr/finlifeapi/{서비스}.json?auth=키&topFinGrpNo=권역&pageNo=쪽
  → {"result": {"err_cd", "err_msg", "total_count", "max_page_no", "now_page_no", "baseList": [...], "optionList": [...]}}
  숫자 칸도 글자로 오고(예: "total_count": "3"), 빈 키에는 {"err_cd": "100", "err_msg": "auth 누락"} 이 온다(실측).
  상품 기본 줄(baseList)과 기간 · 금리 줄(optionList)은 (금융회사 번호 · 상품 코드)로 잇는다.

말없는 fallback 금지 — 키가 없거나 · 금감원이 거절하거나 · 연결이 끊기면 빈 목록 + 분명한 `status` 를 돌려주고,
다른 자료로 메우지 않는다.
"""
from __future__ import annotations

import logging
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class _RedactAuthKey(logging.Filter):
    """httpx 는 요청마다 주소 전체를 INFO 로그에 남긴다(「HTTP Request: GET https://…?auth=…」). 금감원 인증키는
    주소의 물음표 뒤 `auth=` 에 들어가므로 그 값을 가린다 — 우리 로그 글만 조심해서는 키가 앱 · 도커 로그에 남는다."""

    _AUTH = re.compile(r"(auth=)[^&\s\"'<>]+")

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:  # 형식이 깨진 로그는 건드리지 않는다
            return True
        if "auth=" in msg:
            record.msg = self._AUTH.sub(r"\1***", msg)
            record.args = ()
        return True


for _name in ("httpx", "httpcore"):
    _lg = logging.getLogger(_name)
    if not any(isinstance(f, _RedactAuthKey) for f in _lg.filters):
        _lg.addFilter(_RedactAuthKey())

BASE_URL = "https://finlife.fss.or.kr/finlifeapi"
SERVICES: dict[str, tuple[str, str]] = {
    "deposit": ("depositProductsSearch", "정기예금"),
    "saving": ("savingProductsSearch", "적금"),
    "annuity": ("annuitySavingProductsSearch", "연금저축"),
}
SECTORS: dict[str, tuple[str, str]] = {          # 권역 코드(원문 명세 요청변수 topFinGrpNo)
    "bank": ("020000", "은행"),
    "savings_bank": ("030300", "저축은행"),
    "insurance": ("050000", "보험"),
    "investment": ("060000", "금융투자"),
    "credit_card": ("030200", "여신전문"),
}
TERMS = (1, 3, 6, 12, 24, 36)                   # 저축 기간(개월) — 응답 save_trm 이 쓰는 값
SORTS = ("base", "max", "name")
MAX_PAGES = 5
# 읽기 제한은 넉넉히 — 2026-10-12 실측: 적금은 우리 키로 은행 목록을 받는 데 10초를 넘겼다(예금 0.7초 · 틀린 키에는 0.1초).
# 연결이 안 되면 빨리 끊는다(화면이 오래 멈추지 않게).
TIMEOUT = httpx.Timeout(30.0, connect=5.0)
KST = timezone(timedelta(hours=9))

SOURCE_NOTICE = "이 정보는 「금융상품통합비교공시시스템(금융감독원) 금융회사 상품정보」를 사용한 결과입니다."
SOURCE_URL = "https://finlife.fss.or.kr"

_ERR_STATUS = {"010": "bad_key", "011": "bad_key", "012": "bad_key", "013": "bad_key", "020": "quota", "021": "ip_blocked"}
MESSAGES = {
    "no_key": "예금 · 적금 · 연금저축 정보를 지금은 볼 수 없습니다. 관리자에게 알려 주세요.",
    "bad_key": "예금 · 적금 · 연금저축 정보를 불러오지 못했습니다. 관리자에게 알려 주세요.",
    "quota": "오늘 조회할 수 있는 횟수를 모두 써서 정보를 불러오지 못했습니다. 내일 다시 볼 수 있습니다.",
    "ip_blocked": "예금 · 적금 · 연금저축 정보를 불러오지 못했습니다. 관리자에게 알려 주세요.",
    "upstream_error": "금융감독원에서 정보를 받지 못했습니다. 잠시 뒤 다시 시도해 주세요.",
}
# 관리자에게만 — 고칠 곳(라우트가 관리자일 때만 붙인다)
ADMIN_DETAIL = {
    "no_key": "서버 설정에 FINANCE_SUPERVISORY_API_KEY 가 없습니다 — 금융상품 한눈에(finlife.fss.or.kr) 오픈 API 에서 인증키를 받아 "
              ".env 에 넣고 앱을 다시 켜세요(키는 발급받은 사람만 쓸 수 있고 한 사람에 하나 — 약관 제5조).",
    "bad_key": "금융감독원이 인증키를 받지 않았습니다(err_cd 010 ~ 013 — 미등록 · 중지 · 삭제 · 샘플 키). 12개월 안 쓰면 삭제됩니다(약관 제7조).",
    "quota": "개인 인증키의 하루 조회 10,000건을 넘었습니다(err_cd 020 · 약관 제7조).",
    "ip_blocked": "법인(단체) 인증키의 허용 IP 가 아닙니다(err_cd 021).",
    "upstream_error": "금융감독원 응답 오류이거나 연결이 끊겼습니다(err_cd 100 · 101 · 900 · HTTP 오류 · 시간 초과).",
}
JOIN_DENY = {"1": "제한없음", "2": "서민전용", "3": "일부제한"}


def _num(v) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _int(v, default: int = 0) -> int:
    try:
        return int(str(v))
    except (TypeError, ValueError):
        return default


def _ymd(v) -> str | None:
    s = str(v or "")
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}" if len(s) >= 8 and s[:8].isdigit() else None


def _split(v) -> list[str]:
    return [x.strip() for x in str(v or "").split(",") if x.strip()]


def _savings_items(kind: str, bases: list[dict], options: list[dict], term: int) -> list[dict]:
    by_product: dict[tuple, list[dict]] = defaultdict(list)
    for o in options:
        by_product[(o.get("fin_co_no"), o.get("fin_prdt_cd"))].append(o)
    items = []
    for b in bases:
        opts = []
        for o in by_product.get((b.get("fin_co_no"), b.get("fin_prdt_cd")), []):
            row = {"term_months": _int(o.get("save_trm"), 0) or None, "rate_type": o.get("intr_rate_type_nm") or "",
                   "base": _num(o.get("intr_rate")), "max": _num(o.get("intr_rate2"))}
            if kind == "saving":
                row["reserve_type"] = o.get("rsrv_type_nm") or ""
            opts.append(row)
        opts.sort(key=lambda r: (r["term_months"] or 0, r.get("reserve_type", ""), r["rate_type"]))
        at_term = [r for r in opts if r["term_months"] == term]
        # 같은 기간에 줄이 여럿이면(단리 · 복리 · 적립 방식) 기본 금리가 가장 높은 줄 — 어느 줄인지 rate_type · reserve_type 로 함께 보인다
        rate = max(at_term, key=lambda r: (r["base"] if r["base"] is not None else -1.0)) if at_term else None
        items.append({
            "company": b.get("kor_co_nm") or "",
            "company_code": b.get("fin_co_no") or "",
            "product": b.get("fin_prdt_nm") or "",
            "product_code": b.get("fin_prdt_cd") or "",
            "join_way": _split(b.get("join_way")),
            "join_member": b.get("join_member") or "",
            "join_deny": JOIN_DENY.get(str(b.get("join_deny") or ""), ""),
            "special_conditions": b.get("spcl_cnd") or "",
            "maturity_interest": b.get("mtrt_int") or "",
            "note": b.get("etc_note") or "",
            "max_limit": _num(b.get("max_limit")),
            "disclosed_from": _ymd(b.get("dcls_strt_day")),
            "options": opts,
            "rate": dict(rate) if rate else None,
            "_month": str(b.get("dcls_month") or ""),
        })
    return items


def _annuity_items(bases: list[dict]) -> list[dict]:
    items = []
    for b in bases:
        items.append({
            "company": b.get("kor_co_nm") or "",
            "company_code": b.get("fin_co_no") or "",
            "product": b.get("fin_prdt_nm") or "",
            "product_code": b.get("fin_prdt_cd") or "",
            "join_way": _split(b.get("join_way")),
            "pension_kind": b.get("pnsn_kind_nm") or "",
            "product_type": b.get("prdt_type_nm") or "",
            "sale_start": _ymd(b.get("sale_strt_day")),
            "disclosed_rate": _num(b.get("dcls_rate")),
            "guaranteed_rate": _num(b.get("guar_rate")),
            "avg_return": _num(b.get("avg_prft_rate")),
            "past_returns": [_num(b.get(f"btrm_prft_rate_{i}")) for i in (1, 2, 3)],
            "sales_companies": _split(b.get("sale_co")),
            "maintained": _num(b.get("mntn_cnt")),
            "note": b.get("etc") or "",
            "disclosed_from": _ymd(b.get("dcls_strt_day")),
            "rate": None,
            "_month": str(b.get("dcls_month") or ""),
        })
    return items


def _sort(items: list[dict], kind: str, sort: str) -> list[dict]:
    if sort == "name":
        return sorted(items, key=lambda x: (x["company"], x["product"]))
    if kind == "annuity":
        def val(x):  # 보험은 공시이율 · 펀드는 평균 수익률
            return x["disclosed_rate"] if x["disclosed_rate"] is not None else x["avg_return"]
    else:
        field = "base" if sort == "base" else "max"

        def val(x):
            return (x["rate"] or {}).get(field)
    have = [x for x in items if val(x) is not None]
    missing = [x for x in items if val(x) is None]          # 그 기간 금리가 없는 상품도 뒤에 남긴다 — 숨기지 않는다
    have.sort(key=lambda x: (-val(x), x["company"], x["product"]))
    return have + sorted(missing, key=lambda x: (x["company"], x["product"]))


async def search(kind: str, sector: str = "bank", term: int = 12, sort: str = "base", *,
                 api_key: str | None = None, transport: httpx.AsyncBaseTransport | None = None,
                 max_pages: int = MAX_PAGES) -> dict:
    """금감원 오픈 API 를 지금 불러 상품 목록을 돌려준다(저장하지 않는다)."""
    if kind not in SERVICES:
        raise ValueError(f"상품 종류는 {', '.join(SERVICES)} 가운데 하나입니다")
    if sector not in SECTORS:
        raise ValueError(f"권역은 {', '.join(SECTORS)} 가운데 하나입니다")
    if term not in TERMS:
        raise ValueError(f"기간은 {', '.join(map(str, TERMS))}개월 가운데 하나입니다")
    if sort not in SORTS:
        raise ValueError(f"정렬은 {', '.join(SORTS)} 가운데 하나입니다")
    key = settings.FINANCE_SUPERVISORY_API_KEY if api_key is None else api_key
    service, kind_label = SERVICES[kind]
    out = {
        "status": "ok", "kind": kind, "kind_label": kind_label, "sector": sector, "sector_label": SECTORS[sector][1],
        "term": term, "sort": sort, "items": [], "total_count": 0, "pages_read": 0, "max_page_no": None,
        "truncated": False, "disclosed_month": None, "fetched_at": datetime.now(KST).isoformat(timespec="seconds"),
        "source_notice": SOURCE_NOTICE, "source_url": SOURCE_URL, "message": "",
    }
    if not key:
        return {**out, "status": "no_key", "message": MESSAGES["no_key"]}

    def fail(status: str) -> dict:
        return {**out, "status": status, "message": MESSAGES[status]}

    bases: list[dict] = []
    options: list[dict] = []
    async with httpx.AsyncClient(timeout=TIMEOUT, transport=transport) as client:
        page = 1
        while True:
            try:
                resp = await client.get(f"{BASE_URL}/{service}.json",
                                        params={"auth": key, "topFinGrpNo": SECTORS[sector][0], "pageNo": str(page)})
            except httpx.HTTPError as e:
                # 예외 글에는 요청 주소(인증키가 든 물음표 뒤)가 섞일 수 있어 종류 이름만 남긴다
                logger.warning("금감원 오픈 API 연결 실패 — %s %d쪽 · %s", service, page, type(e).__name__)
                return fail("upstream_error")
            if resp.status_code != 200:
                logger.warning("금감원 오픈 API HTTP %d — %s %d쪽", resp.status_code, service, page)
                return fail("upstream_error")
            try:
                result = resp.json()["result"]
            except (ValueError, KeyError, TypeError):
                logger.warning("금감원 오픈 API 응답 모양이 다름 — %s %d쪽", service, page)
                return fail("upstream_error")
            err = str(result.get("err_cd") or "")
            if err != "000":
                logger.warning("금감원 오픈 API 거절 — %s %d쪽 · err_cd %s", service, page, err)
                return fail(_ERR_STATUS.get(err, "upstream_error"))
            bases += result.get("baseList") or []
            options += result.get("optionList") or []
            # 쪽마다 같은 값이 오지만, 덮어쓰지 않고 가장 큰 값을 쓴다(뒤 쪽이 다르게 와도 「다 읽었다」 로 잘못 끝나지 않게)
            out["total_count"] = max(out["total_count"], _int(result.get("total_count")))
            out["max_page_no"] = max(out["max_page_no"] or 0, _int(result.get("max_page_no"), 1))
            out["pages_read"] = page
            if page >= out["max_page_no"]:
                break
            if page >= max_pages:
                out["truncated"] = True          # 다 읽지 않았다는 것을 분명히 — 하루 조회 수(제7조)를 아끼려는 상한
                break
            page += 1

    items = _annuity_items(bases) if kind == "annuity" else _savings_items(kind, bases, options, term)
    months = sorted({x["_month"] for x in items if len(x["_month"]) == 6})
    for x in items:
        del x["_month"]
    out["items"] = _sort(items, kind, sort)
    out["disclosed_month"] = f"{months[-1][:4]}-{months[-1][4:]}" if months else None
    return out
