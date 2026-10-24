"""데이터 상태 — 「데이터가 언제 것인가 · 매일 갱신이 돌았나」 를 한 번에 (목표 기능 ① W4 · 설계서 5.2.2).

`GET /api/data/status` 가 부른다. 지금의 `GET /api/system/sync-status` 는 **외부 시세 캐시**의 신선도라
그대로 두고, 화면의 「데이터 기준일」 은 이것을 본다(설계서 5.2.2).

읽는 것 — 전부 읽기 전용(앱은 수집 DB 에 쓰지 않는다)
  - 러너 기록   data/collector/state/daily_update_last.json · daily_update_history.jsonl · daily_update.lock
  - 단계 목록   data/collector/state/daily_update_steps.json — 단계 이름표 · 막는 때 · **회차 시각(`schedule`)** 도 여기서만
                읽는다(D104 · 2026-10-15 — 앱에 12:30 사본을 두지 않는다 · 없으면 「회차 시각 모름」)
  - 숫자 파일   data/collector/state/data_guide_stats.json — 표별 **행 수**는 러너가 회차 끝에 센 이 파일에서 읽는다(자료 안내와
                같은 파일 · 3단계 2026-10-15 사용자 결정). 앱은 수집 DB 를 세지 않는다(뒤에서 세던 스레드를 없앴다)
  - 수집 DB     표별 마지막 날짜 · 거래일(`collector_db.db_path()` — 도커에서는 /app/data/csv/collector)
  - 거래일 달력 market_calendar — 「몇 거래일 늦었나」 를 세는 자. 없으면 평일로 어림하고 `approx` 를 켠다
  - HF 기록     data/hf_export/meta/manifest.json(krx-daily-market) · data/collector/ohlcv_export/manifest.json(krx-ohlcv)

늦음 판정 — 포털은 그날 시세를 **다음 날 낮**에 준다(collector/README §7)
  표의 마지막 날 뒤 · 오늘 앞에 있는 거래일 수(n)로 가른다.
    n = 0 최신 · 1 정상(12:30 갱신 전이면 보통 하루 밀려 있다) · 2 늦음 · 3 이상 멈춤
  계산 표(수정주가 · TR · 자체 지수)는 주식 일봉과 같은 날이어야 정상이다.
  출처마다 공개 마감을 안다(DF-91 · 2026-10-15 · ``FRESHNESS`` 한 곳) — 시세 · ETF · 지수의 n = 1 은 빠진 거래일의 다음 거래일
  14:00(포털 약속 13:00 + 1시간)까지만 「정상 · 공개 전」 이고 그 뒤에도 비면 「늦음 · 다시 받기」 다(고치기 전에는 그날 내내 「정상」
  이라 같은 자료를 리밸런싱 준비는 「기다림」 으로 봤다). 공시 목록 · 기사 · 정책뉴스는 정한 창, 재무 · 배당 · 일정 · 시장금리는
  「마지막 회차가 그 단계를 확인했나」 로 본다(새 행이 없는 날이 정상인 자료).

러너가 도는지는 컨테이너에서 PID 로 확인할 수 없다 — 잠금 파일이 있고 4시간 안이면 「도는 중」 으로 본다
(러너의 LOCK_STALE_HOURS 와 같은 값).
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
from datetime import date, datetime, time as dt_time, timedelta, timezone
from pathlib import Path

from app.services import collector_db

KST = timezone(timedelta(hours=9))

#: 회차 시각을 모를 때의 글(D104 · #163 02 약속 셋째 · 2026-10-15). 회차 시각은 러너(`scripts/daily_update.py` DEFAULT_TIME)가
#: 단계 목록에 쓴 `schedule` 하나다 — 앱이 사본을 들고 있으면 러너 시각을 바꿀 때 관제 · 자료 안내 · 도움말이 말없이 옛 시각을
#: 보인다(SSoT). 목록이 없거나(이 PC 에서 러너를 돌린 적 없음) 그 칸이 없거나 꼴이 틀리면 이 글을 내고, 다음 회차를 비우고,
#: 「오늘 회차 없음」 을 판정하지 않는다(말없이 12:30 으로 메우지 않는다 — TC-DST-27).
SCHEDULE_UNKNOWN = "회차 시각 모름"
_HM = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
LOCK_STALE_HOURS = 4
HISTORY_N = 7
CACHE_SECONDS = 30

#: 러너 단계의 이름표 · 묶음 · 하는 일은 **러너가 쓴 기록에서만 읽는다**(2026-10-07 · 결정 ④). 앱에 손으로 옮긴 사본을 두면
#: 단계를 더할 때 두 곳을 고쳐야 하고, 빠뜨리면 화면에 영어 단계 이름이 보인다(그 사본이 있었다 — TC-DST-08 이 지킨다).
#:   단계 목록  state/daily_update_steps.json — 러너가 회차마다 처음에 쓴다(`python scripts/daily_update.py steps --write` 로도)
#:   회차 기록  state/daily_update_last.json 의 단계 줄 — 이름표 · 묶음 · 하는 일 · 멈춤 여부를 함께 적는다
#: 둘 다 없는 옛 기록은 단계 이름 그대로 보인다.
CATALOG_FILE = "daily_update_steps.json"
#: 이 PC 용량 — 앱 컨테이너는 PC 디스크를 볼 수 없어 러너가 회차 끝에 잰다.
DISK_FILE = "pc_disk.json"
#: 도는 중의 지금 단계 — 러너가 단계를 시작할 때마다 쓴다(잠금 파일과 따로 · 2026-10-08). 수집 일정 화면의 「수집 중 — n번째 단계」.
PROGRESS_FILE = "daily_update_progress.json"
#: 숫자 파일 — 러너가 회차 끝 · 한 단계 다시 · 채우기 뒤 · `steps --write` 때 쓴다(`scripts/daily_update.py` GUIDE_STATS_PATH ·
#: 상태 폴더 안). 자료 안내(2단계 · 2026-10-11)와 관제 줄 수(3단계 · 2026-10-15)가 **같은 파일 · 같은 읽기 함수**(`load_numbers`)를
#: 쓴다 — 두 화면이 다른 수를 보이지 않게. 판이 다르면 숫자를 비운다(「옛 판」). 러너 GUIDE_STATS_SCHEMA 와 같아야 한다(TC-DG-11).
#: `extras`(관제 밖 자료 여덟 · 3단계)는 더한 칸이라 판을 올리지 않았다 — 그 칸이 없는 옛 파일이면 여덟만 「기다림」 이다.
NUMBERS_FILE = "data_guide_stats.json"
NUMBERS_SCHEMA = 1

#: (키, 표, 이름, 묶음, 출처, 판정 방식, 마지막 날짜 SQL, 행 수 SQL)
TABLES = [
    ("price_daily", "price_daily", "주식 일봉(원 가격)", "시세", "공공데이터포털 주식시세정보", "portal",
     "SELECT MAX(bas_dt) FROM price_daily", "SELECT COUNT(*) FROM price_daily"),
    ("etf_daily", "etf_daily", "ETF 일봉", "시세", "공공데이터포털 증권상품시세정보", "portal",
     "SELECT MAX(bas_dt) FROM etf_daily", "SELECT COUNT(*) FROM etf_daily"),
    ("index_daily", "index_daily", "지수 일봉", "시세", "공공데이터포털 지수시세정보", "portal",
     "SELECT MAX(bas_dt) FROM index_daily", "SELECT COUNT(*) FROM index_daily"),
    ("price_adjusted", "price_adjusted", "수정주가", "계산", "주식 일봉에서 계산", "derived",
     "SELECT MAX(bas_dt) FROM price_adjusted", "SELECT COUNT(*) FROM price_adjusted"),
    ("price_total_return", "price_total_return", "총수익(TR)", "계산", "수정주가 + 배당에서 계산", "derived",
     "SELECT MAX(bas_dt) FROM price_total_return", "SELECT COUNT(*) FROM price_total_return"),
    ("benchmark_index", "benchmark_index", "자체 재현 지수", "계산", "수정주가 · TR 에서 계산", "derived",
     "SELECT MAX(bas_dt) FROM benchmark_index", "SELECT COUNT(*) FROM benchmark_index"),
    ("dividend", "dividend", "배당 공시", "공시", "전자공시(DART) — 마지막 공시 접수일", "info",
     "SELECT MAX(substr(rcept_no, 1, 8)) FROM dividend", "SELECT COUNT(*) FROM dividend"),
    ("disclosure", "disclosure", "공시 목록", "공시", "전자공시(DART) 상장사 공시 — 마지막 접수일", "info",
     "SELECT MAX(rcept_dt) FROM disclosure", "SELECT COUNT(*) FROM disclosure"),
    # 마지막 날짜는 접수번호 색인(ix_fin_rcept)으로 — `known_at` 은 「접수번호 앞 8자리」 라 값이 같은데(188만 행 중 다른 행 0 ·
    # 2026-10-07) 색인이 없어, `MAX(known_at)` 가 도커 앱에서 표 전체를 훑느라 19 ~ 31초 걸렸다(DF-80 · TC-DST-13).
    # 안쪽 MAX 를 따로 두어야 SQLite 가 색인 끝 한 칸만 읽는다(바깥에서 자르면 최솟값 · 최댓값 최적화가 꺼진다).
    ("financial_statement", "financial_statement", "재무 주요계정", "공시",
     "전자공시(DART) 다중회사 주요계정 — 마지막으로 값이 실린 보고서 접수일", "info",
     "SELECT substr((SELECT MAX(rcept_no) FROM financial_statement), 1, 8)",
     "SELECT COUNT(*) FROM financial_statement"),
    # 전체 재무제표 · 기업 업종(2026-10-24 · 할 일 ①-05 G3 · G2) — 마지막 날은 주요계정과 같은 꼴(접수번호 색인 끝 한 칸 · DF-80).
    ("financial_statement_full", "financial_statement_full", "재무 전체 계정", "공시",
     "전자공시(DART) 단일회사 전체 재무제표 — 분봉 유니버스 351곳 · 마지막으로 값이 실린 보고서 접수일", "info",
     "SELECT substr((SELECT MAX(rcept_no) FROM financial_statement_full), 1, 8)",
     "SELECT COUNT(*) FROM financial_statement_full"),
    ("dart_company", "dart_company", "기업 업종", "공시",
     "전자공시(DART) 기업개황 업종코드 — 351곳 · 7일마다 전체 · 마지막으로 다시 받아 본 날", "info",
     "SELECT substr((SELECT MAX(last_seen_at) FROM dart_company), 1, 10)",
     "SELECT COUNT(*) FROM dart_company"),
    # 뉴스 표 하나에 출처 둘이 들어 있다(2026-10-04 부터 GDELT 언론사 기사) — 출처마다 한 줄씩(DF-87 · 2026-10-08).
    # 한 줄로 세면 정책뉴스 줄이 언론사 기사까지 세고, 마지막 날짜도 매일 받는 언론사 기사 쪽으로 당겨져 정책뉴스가 멈춰도 안 보인다.
    ("news_item", "news_item", "정책뉴스", "뉴스", "정책브리핑 정책뉴스(공공데이터포털 · 기사마다 공공누리 유형 — 제1유형만 본문) — 마지막 승인일", "info",
     "SELECT MAX(substr(pub_at, 1, 10)) FROM news_item WHERE source = 'policy_news'",
     "SELECT COUNT(*) FROM news_item WHERE source = 'policy_news'"),
    # 마지막 기사 「시각」 까지 — 36시간 판정이 날짜가 아니라 시각을 본다(DF-91). 줄의 마지막 날은 `_iso_day` 가 앞 10자로 자른다.
    ("news_gdelt", "news_item", "언론사 기사", "뉴스", "GDELT 한국어 기사 — 제목 · 원문 주소 · 시각만(본문 없음) — 마지막 기사 시각", "info",
     "SELECT MAX(pub_at) FROM news_item WHERE source = 'gdelt'",
     "SELECT COUNT(*) FROM news_item WHERE source = 'gdelt'"),
    # 한국은행 ECOS 시장금리(2026-10-13 · 재무 · 신용 위험) · 주가지수(2026-10-14 · 계절성) — 일곱 항목이 한 표 ·
    # 마지막 날짜는 표 전체의 마지막 날(참고 — 휴장일엔 값이 없다).
    ("ecos_series", "ecos_series", "금리 · 지수 · 환율 · 물가", "금리", "한국은행 ECOS — 시장금리(일별 · 국고채 3 · 10년 · 회사채 AA- · "
     "BBB- · CD · CP) · 주가지수(코스피 1995 ~ · 코스닥 2003 ~) · 기준금리 · 원/달러(일별) · 소비자물가(월별) — 마지막 날", "info",
     "SELECT MAX(date) FROM ecos_series", "SELECT COUNT(*) FROM ecos_series"),
    ("intraday_60m", "price_intraday", "60분봉", "분봉", "야후 파이낸스(09:00~15:00)", "intraday",
     "SELECT MAX(trade_date) FROM price_intraday WHERE timeframe = '60m'",
     "SELECT COUNT(*) FROM price_intraday WHERE timeframe = '60m'"),
    ("intraday_5m", "price_intraday", "5분봉", "분봉", "야후 파이낸스(09:00~15:00)", "intraday",
     "SELECT MAX(trade_date) FROM price_intraday WHERE timeframe = '5m'",
     "SELECT COUNT(*) FROM price_intraday WHERE timeframe = '5m'"),
    ("market_calendar", "market_calendar", "거래일 달력", "일정", "특일 정보(한국천문연구원) + 거래소 규칙", "calendar",
     "SELECT MAX(cal_date) FROM market_calendar", "SELECT COUNT(*) FROM market_calendar"),
    ("market_event", "market_event", "금융 일정", "일정", "휴장 · 파생 만기 · 배당", "info",
     "SELECT MAX(event_date) FROM market_event", "SELECT COUNT(*) FROM market_event"),
]

VERDICT_LABEL = {"fresh": "최신", "ok": "정상", "late": "늦음", "stale": "멈춤", "missing": "없음", "info": "참고"}
_RANK = {"fresh": 0, "ok": 0, "info": 0, "late": 1, "missing": 1, "stale": 2}

#: 출처마다 공개 마감 · 신선도 규칙(DF-91 · 2026-10-15 · 자동 수집 벤치마크 조사서 4.1절 · 2차-1) — 표 열쇠 → (꼴, 값).
#: 출처의 약속을 판정에 묶는 **한 곳**이다(판정 · 화면 글이 같은 값을 쓴다). 여기 없는 「참고」 표는 지금처럼 판정하지 않는다.
#:   deadline      빠진 거래일 d 의 공개 마감 = d 다음 거래일의 이 시각(포털 원문 「기준일자로부터 영업일 하루 뒤 오후 1시 이후」 +
#:                 1시간 여유 — 회차 판정의 「12:30 + 1시간」 과 같은 꼴). n = 1 이고 마감 전 「정상 · 공개 전」 · 마감 뒤 · n = 2 는
#:                 「늦음 · 다시 받기」 · 3 이상은 「멈춤」 그대로. 영업일은 거래일 달력으로 어림한다(휴장일을 건너뛴다)
#:   prev_day      마지막 날이 전 거래일보다 앞이면 늦음(상장사 공시 — 거래일 하루 약 700건이라 하루라도 비면 멈춘 것)
#:   max_hours     마지막 시각이 이 시간을 넘게 지나면 늦음(GDELT 15분 파일 — 회차가 지난 30시간을 읽는다 · 날짜가 아니라 시각)
#:   gap_days      마지막 날 뒤 · 오늘 앞 거래일이 이만큼 비면 늦음(정책뉴스 — 받는 창이 3일이라 더 밀리면 빠진다 · 값은 추정 —
#:                 지난 분포를 재어 고친다)
#:   step_checked  새 행이 없는 날이 정상인 자료 — 자료 날짜 대신 마지막 회차의 그 단계 결과(0 정상 · 실패 늦음 · 돌지 않음 · 기록
#:                 없음은 참고 — 모른다를 정상으로 꾸미지 않는다). 오늘 회차가 없는 것은 회차 판정(「오늘 회차 없음」)이 알린다
FRESHNESS: dict[str, tuple] = {
    "price_daily": ("deadline", (14, 0)),
    "etf_daily": ("deadline", (14, 0)),
    "index_daily": ("deadline", (14, 0)),
    "disclosure": ("prev_day", None),
    "news_gdelt": ("max_hours", 36),
    "news_item": ("gap_days", 2),
    "dividend": ("step_checked", "dividend"),
    "financial_statement": ("step_checked", "financial"),
    "market_event": ("step_checked", "calendar"),
    "ecos_series": ("step_checked", "ecos"),
    "financial_statement_full": ("step_checked", "financial_full"),
    "dart_company": ("step_checked", "company"),
}
#: 마감을 아는 판정의 상태 이름(조사서 4.1절 · 2차-1 — 「정상 · 공개 전」 · 「늦음 · 다시 받기」)
LABEL_BEFORE_PUBLISH = "정상 · 공개 전"
LABEL_REFETCH = "늦음 · 다시 받기"

_cache: dict = {}

#: 표별 행 수는 앱이 세지 않는다(2026-10-15 · 자료 안내 3단계 · 사용자 결정 「숫자 파일에서 읽기」). 2026-10-02 부터 뒤에서 세는
#: 스레드가 있었다 — 앱이 다시 켜진 뒤 첫 호출에서 컨테이너가 큰 표 다섯의 COUNT(*) 에 14.8 ~ 21초를 써서 그동안 「세는 중」 이었고,
#: 같은 수를 러너도 회차 끝에 따로 셌다(자료 안내 숫자 파일 · 2026-10-11). 이제 러너가 센 한 벌(`load_numbers`)만 읽는다.

#: 자료 안내의 관제 밖 자료 여덟 — 줄 수 · 마지막 날 · 처음 날(3단계 · 2026-10-15 사용자 결정 「추천 표대로」). 러너가 회차 끝에
#: `extra_counts` 로 세어 숫자 파일의 `extras` 에 쓰고(`scripts/daily_update.table_numbers`), 자료 안내는 대장 「숫자_상태」 칸의
#: 열쇠로 읽는다. 관제 표(TABLES)가 아니라 판정 · 「모은 줄」 합에는 넣지 않는다(근거 조각 · 용어 · 회차 줄은 시세 줄과 뜻이 다르다).
#: 앱은 이 함수를 부르지 않는다(요청 때 세지 않는다 — 자료 안내 결정 ④ · TC-DG-06).
#: (열쇠, 수집 폴더 안 DB 파일, 표, 줄 수 SQL, 마지막 날 SQL, 처음 날 SQL | None)
EXTRA_SQL = [
    ("corp_schedule", "market.sqlite3", "corp_schedule", "SELECT COUNT(*) FROM corp_schedule",
     "SELECT MAX(event_date) FROM corp_schedule WHERE event_date <> ''", None),
    ("holiday_kasi", "market.sqlite3", "holiday_kasi", "SELECT COUNT(*) FROM holiday_kasi",
     "SELECT MAX(locdate) FROM holiday_kasi", "SELECT MIN(locdate) FROM holiday_kasi"),
    ("policy_meeting", "market.sqlite3", "policy_meeting", "SELECT COUNT(*) FROM policy_meeting",
     "SELECT MAX(meeting_date) FROM policy_meeting", "SELECT MIN(meeting_date) FROM policy_meeting"),
    # 근거 DB — 줄 = 근거 조각(조를 나눈 조각 · 지난 판 포함) · 마지막 날 = 가장 늦은 판의 시행일(시행 예정 판도)
    ("kb_law", "kb.sqlite3", "kb_chunk", "SELECT COUNT(*) FROM kb_chunk",
     "SELECT MAX(effective_at) FROM kb_document", None),
    # 섹터 법령 — 줄 = 조문(해마다 고른 판) · 마지막 날 = 가장 늦은 해의 끝
    ("kb_sector", "kb_sector.sqlite3", "ks_article", "SELECT COUNT(*) FROM ks_article",
     "SELECT MAX(year) || '-12-31' FROM ks_article", None),
    # 검색 색인 — 줄 = 색인한 문서(공시 · 정책뉴스 · 언론사 기사) · 날짜는 게시일의 날 부분. 칸 그대로 MAX · MIN 을 구한 뒤 자른다 —
    # 「YYYY-MM-DD…」 글은 글자 차례가 날 차례라 결과가 같고, 색인(ix_doc_pub) 끝만 읽는다(0.2ms · 자른 뒤 구하면 84만 줄을 다 읽어 118ms)
    ("search_index", "search.sqlite3", "doc", "SELECT COUNT(*) FROM doc",
     "SELECT substr(MAX(published), 1, 10) FROM doc", "SELECT substr(MIN(published), 1, 10) FROM doc"),
]
#: 용어사전 — 앱 파일(원본이 이것 · 앱이 켜질 때 DB 에 넣는다). 줄 = 용어(다른 이름 · 관계는 세지 않는다)
GLOSSARY_FILE = Path(__file__).resolve().parent / "glossary_data" / "terms.json"
#: 숫자 파일 `extras` 의 열쇠 · 차례 — 자료 안내 대장 「숫자_상태」 칸이 부르는 이름(TC-DG-02 가 맞댄다).
#: 모의투자 그림자 일지(`paper_journal` · 2026-10-24)는 앱 DB 표라 러너가 DB 를 세지 않고 일지 단계가 쓴 내보내기 지문 목록에서 읽는다.
EXTRA_KEYS = tuple(k for k, *_ in EXTRA_SQL) + ("glossary", "run_history", "paper_journal")
#: 그림자 일지 내보내기 · 올리기 기록 — 수집 폴더의 형제 폴더 · 상태 폴더(`scripts/paper_journal.py` EXPORT_DIR · HF_LAST_PATH 와 같은 자리)
PAPER_JOURNAL_MANIFEST = ("paper_journal", "export", "manifest.json")
PAPER_JOURNAL_HF_LAST = "paper_journal_hf_last.json"


def _now() -> datetime:
    return datetime.now(KST)


def _iso_day(v: str | None) -> str | None:
    """YYYYMMDD · YYYY-MM-DD 둘 다 YYYY-MM-DD 로."""
    if not v:
        return None
    v = str(v)
    return f"{v[:4]}-{v[4:6]}-{v[6:8]}" if len(v) == 8 and v.isdigit() else v[:10]


def collector_dir() -> Path | None:
    """수집기 자료 폴더 — 로컬은 data/collector, 도커는 data/csv/collector."""
    p = collector_db.db_path()
    if p is not None:
        return p.parent
    for cand in collector_db._DEFAULT_CANDIDATES:  # noqa: SLF001 — 같은 후보를 쓴다(DB 파일만 없을 때)
        if cand.parent.is_dir():
            return cand.parent
    return None


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _parse_ts(v: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(v) if v else None
    except ValueError:
        return None


# ── 러너 ──────────────────────────────────────────────────────────────────
def _parse_hm(v) -> tuple[int, int] | None:
    """「HH:MM」(00:00 ~ 23:59) → (시, 분). 그 밖의 꼴(「25:00」 · 「7:5」 · 숫자)은 None — 말없이 고치지 않는다."""
    m = _HM.match(v) if isinstance(v, str) else None
    return (int(m.group(1)), int(m.group(2))) if m else None


def load_catalog(state_dir: Path | None) -> dict:
    """러너가 쓴 단계 목록 — {groups, steps(차례 그대로), by_name, written_at, guards, fill_max_days, schedule}. 없으면 빈 목록.

    `guards` 는 화면 실행을 막는 때(2026-10-10 · 러너가 막는 데 쓰는 함수로 셈한 시각) — 옛 목록에는 없어 빈 사전이다.
    `fill_max_days` 는 빠진 날 채우기 한 번의 범위 상한(일 · 러너 `FILL_MAX_DAYS`) — 옛 목록에는 없어 None 이고, 그러면 앱은
    채우기를 받지 않는다(짐작 금지 · TC-CQ-18 · 23).
    `schedule` 은 회차 시각 (시, 분) — 러너 DEFAULT_TIME 이 쓴 「HH:MM」 하나(D104 · 2026-10-15). 없거나 꼴이 틀리면 None 이고,
    그러면 관제는 「회차 시각 모름」 을 보이고 「오늘 회차 없음」 을 판정하지 않는다.
    """
    cat = _read_json(state_dir / CATALOG_FILE) if state_dir is not None else None
    steps = [s for s in (cat or {}).get("steps") or [] if isinstance(s, dict) and s.get("name")]
    guards = (cat or {}).get("guards")
    max_days = (cat or {}).get("fill_max_days")
    return {"groups": (cat or {}).get("groups") or [], "steps": steps,
            "by_name": {s["name"]: s for s in steps}, "written_at": (cat or {}).get("written_at"),
            "guards": guards if isinstance(guards, dict) else {},
            "fill_max_days": max_days if isinstance(max_days, int) and not isinstance(max_days, bool) else None,
            "schedule": _parse_hm((cat or {}).get("schedule"))}


def _step_view(rec: dict, by_name: dict | None = None, *, admin: bool = False) -> dict:
    """단계 한 줄 — 이름표 · 묶음 · 하는 일은 그 회차 기록 → 단계 목록 → 이름 그대로 순으로 찾는다.

    ``admin`` 이면 실패한 단계의 까닭(``error``)과 로그 파일 이름(``log_name``)을 함께 싣는다(DF-101 · 2026-10-10 결정
    「관리자 화면에만」) — 러너가 경로 · 비밀값을 걸러 적었어도 내부 말 · PC 의 파일 이름이라 모두가 보는 답에는 싣지 않는다."""
    name = rec.get("name", "")
    meta = (by_name or {}).get(name, {})
    fatal = bool(rec["fatal"]) if "fatal" in rec else bool(meta.get("fatal"))
    rc = rec.get("rc")
    if rc is None:
        status = "skipped"
    elif rc == 0:
        status = "ok"
    else:
        # 러너가 경고로 적은 줄(`warn` — 멈추는 단계의 경고 종료코드 · 시세 69 · DF-92)은 멈추는 단계여도 경고다(러너 판정 그대로)
        status = "failed" if (fatal and not rec.get("warn")) else "warning"
    out = {"name": name, "label": rec.get("label") or meta.get("label") or name,
           "group": rec.get("group") or meta.get("group") or "", "desc": rec.get("desc") or meta.get("desc") or "",
           "status": status, "rc": rc, "seconds": rec.get("seconds") or 0, "note": rec.get("note") or ""}
    if rec.get("rerun_at"):
        out["rerun_at"] = rec["rerun_at"]
    # 건너뛴 까닭 · 뒤 할 일 · 거래일(2026-10-08) — 러너가 판정해 기록에 쓴 그대로 넘긴다(앱은 종료코드를 다시 해석하지 않는다).
    # `followup` 이 있는 건너뜀(신호 단계 · 앱 DB 꺼짐)만 화면이 노랑으로 칠한다
    out.update({k: rec[k] for k in ("reason", "followup", "date") if rec.get(k)})
    # 빠진 날(2026-10-10) — 채울 날 수 · 첫날 · 마지막 날 · 다음 묶음. 러너가 상태 파일에서 모아 적은 그대로(앱은 날짜를 셈하지 않는다)
    out.update({k: rec[k] for k in ("fill_from", "fill_to", "fill_days", "fill_rest") if rec.get(k)})
    # DART 호출 수(2026-10-24 · 하루 호출 장부 · 기록만) — 러너가 단계 앞뒤로 잰 그 단계의 OpenDART 호출 수. 몫은 러너 DART_CAPS
    if rec.get("dart_calls"):
        out["dart_calls"] = rec["dart_calls"]
    if admin:
        out.update({k: rec[k] for k in ("error", "log_name") if rec.get(k)})
    return out


def pc_disk(state_dir: Path | None) -> dict | None:
    """이 PC 용량 — 러너가 잰 값(GB · 소수 한 자리). 없으면 None."""
    d = _read_json(state_dir / DISK_FILE) if state_dir is not None else None
    if not d or "free_bytes" not in d:
        return None
    gb = lambda v: round((v or 0) / 1e9, 1)  # noqa: E731
    return {"measured_at": d.get("measured_at"), "drive": d.get("drive"), "free_gb": gb(d.get("free_bytes")),
            "total_gb": gb(d.get("total_bytes")), "collector_db_gb": gb(d.get("collector_db_bytes"))}


def schedule_text(hm: tuple[int, int] | None) -> str:
    """회차 시각 글 — 「매일 HH:MM」 · 모르면 「회차 시각 모름」(화면은 이 글을 그대로 쓴다 — 「매일 낮 {시각} — …」)."""
    return f"매일 {hm[0]:02d}:{hm[1]:02d}" if hm else SCHEDULE_UNKNOWN


def runner_state(state_dir: Path | None, now: datetime, *, admin: bool = False) -> dict:
    # 회차 시각은 러너가 쓴 단계 목록 하나에서(D104) — 없으면 다음 회차 · 「오늘 회차 없음」 을 셈하지 않는다(짐작 금지)
    catalog = load_catalog(state_dir)
    hm = catalog["schedule"]
    today_run = now.replace(hour=hm[0], minute=hm[1], second=0, microsecond=0) if hm else None
    nxt = (today_run if now < today_run else today_run + timedelta(days=1)) if today_run else None
    note = ("러너 단계 목록의 회차 시각 — 작업 스케줄러에는 이 PC 에서 install 할 때 같은 시각으로 등록한다(다른 PC 는 등록해야 돈다)"
            if hm else "러너 단계 목록에 회차 시각이 없다 — 이 PC 에서 매일 수집을 돌린 적이 없거나 옛 목록이다")
    if admin:
        note += " · python scripts/daily_update.py " + ("install" if hm else "steps --write")
    out: dict = {"schedule": schedule_text(hm), "next_expected": nxt.isoformat(timespec="minutes") if nxt else None,
                 "schedule_note": note, "running": False, "last": None, "history": [], "groups": []}
    if state_dir is None or not state_dir.is_dir():
        out.update(state="missing", label="기록 없음", detail="러너 기록 폴더가 없다 — 이 PC 에서 일일 갱신을 돌린 적이 없다")
        return out

    lock = _read_json(state_dir / "daily_update.lock")
    since = _parse_ts((lock or {}).get("started_at"))
    if since and (now - since) < timedelta(hours=LOCK_STALE_HOURS):
        out["running"] = True
        out["running_since"] = since.isoformat(timespec="seconds")
        # 지금 단계 — 러너가 단계를 시작할 때 진행 파일에 적는다(2026-10-08). 같은 실행의 것만(시작 시각이 잠금과 같을 때) 믿는다.
        prog = _read_json(state_dir / PROGRESS_FILE) or {}
        step = prog.get("step") if isinstance(prog.get("step"), dict) else None
        if step and _parse_ts(prog.get("started_at")) == since:
            out["running_step"] = {k: step.get(k) for k in ("index", "total", "name", "label")}

    by_name = catalog["by_name"]
    out["groups"] = catalog["groups"]
    last = _read_json(state_dir / "daily_update_last.json")
    if last:
        steps = [_step_view(s, by_name, admin=admin) for s in last.get("steps") or []]
        started, finished = _parse_ts(last.get("started_at")), _parse_ts(last.get("finished_at"))
        out["last"] = {
            "started_at": last.get("started_at"),
            "finished_at": last.get("finished_at"),
            "minutes": round((finished - started).total_seconds() / 60, 1) if started and finished else None,
            "ok": bool(last.get("ok")),
            "upload": bool(last.get("upload")),
            "stopped": last.get("stopped"),
            "derived": last.get("derived"),
            "steps": steps,
            # 다시 돌림 줄의 로그 경로 · 요청 번호는 관리자 답에만(까닭 · 로그 파일 이름과 같은 결정 · 2026-10-10)
            "reruns": [{k: v for k, v in r.items() if admin or k not in ("log", "request_id")}
                       for r in last.get("reruns") or [] if isinstance(r, dict)],
            "price_max": _iso_day((last.get("after") or {}).get("price_max")),
        }

    hist_path = state_dir / "daily_update_history.jsonl"
    try:
        lines = hist_path.read_text(encoding="utf-8").splitlines()[-HISTORY_N:]
    except OSError:
        lines = []
    for ln in reversed(lines):
        try:
            h = json.loads(ln)
        except ValueError:
            continue
        s, f = _parse_ts(h.get("started_at")), _parse_ts(h.get("finished_at"))
        out["history"].append({
            "started_at": h.get("started_at"),
            "ok": h.get("ok") if "skipped" not in h else None,
            "skipped": h.get("skipped"),
            "stopped": h.get("stopped"),
            "only": h.get("only"),                         # 한 단계만 다시 돌린 줄(2026-10-07~)
            "fill": h.get("fill"),                         # 빠진 날 채우기 줄의 범위 {from, to}(2026-10-10~)
            "minutes": round((f - s).total_seconds() / 60, 1) if s and f else None,
            "price_max": _iso_day(h.get("price_max")),
            # 단계별 결과는 2026-10-07 뒤 회차부터 남는다 — 그 앞 줄은 None
            "steps": [_step_view(x, by_name, admin=admin) for x in h["steps"]] if isinstance(h.get("steps"), list) else None,
        })

    # 판정 — 도는 중 > 실패 > 오늘 회차 없음 > 일부 실패 > 성공
    lr = out["last"]
    ran_today = bool(lr and (lr["started_at"] or "")[:10] == now.date().isoformat())
    out["ran_today"] = ran_today
    if out["running"]:
        out.update(state="running", label="도는 중", detail=f"{out['running_since'][11:16]} 에 시작했다")
    elif not lr:
        out.update(state="missing", label="기록 없음", detail="일일 갱신이 끝난 기록이 없다")
    elif not lr["ok"] and lr["stopped"]:
        out.update(state="failed", label="실패", detail=f"멈춘 단계: {lr['stopped']}")
    elif not ran_today and today_run is not None and now >= today_run + timedelta(hours=1):
        # 회차 시각을 모르면(today_run None) 판정하지 않는다 — 「오늘 회차 없음」 을 짐작으로 띄우지 않는다(D104)
        out.update(state="late", label="오늘 회차 없음",
                   detail=f"{hm[0]:02d}:{hm[1]:02d} 회차 기록이 아직 없다 — PC 가 꺼져 있었으면 켜진 뒤 돈다(작업 스케줄러 StartWhenAvailable)")
    elif any(s["status"] in ("failed", "warning") for s in lr["steps"]):
        bad = [s["label"] for s in lr["steps"] if s["status"] in ("failed", "warning")]
        out.update(state="warning", label="일부 실패", detail="실패한 단계: " + " · ".join(bad))
    elif any(s.get("followup") for s in lr["steps"]):
        # 돌 조건이 없어 건너뛰고 채울 날이 남은 단계(2026-10-08 · 신호 단계 앱 DB 꺼짐) — 실패가 아니라 「확인할 것」 이다.
        # 회차 ok 는 러너가 쓴 그대로 둔다(리밸런싱 하루 점검은 신호를 읽지 않는다). 까닭은 러너 메모의 첫 마디
        held = [f"{s['label']}({(s.get('note') or '').split(' · ')[0] or '건너뜀'})" for s in lr["steps"] if s.get("followup")]
        out.update(state="attention", label="일부 건너뜀", detail="채울 단계: " + " · ".join(held))
    else:
        out.update(state="ok", label="성공", detail=f"{(lr['finished_at'] or '')[:16].replace('T', ' ')} 에 끝났다")
    return out


# ── 표 ────────────────────────────────────────────────────────────────────
def _connect_ro() -> sqlite3.Connection | None:
    path = collector_db.db_path()
    if path is None:
        return None
    try:
        return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error:
        return None


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def _trading_after(conn: sqlite3.Connection, has_cal: bool, after: str, before: str) -> tuple[list[str], bool]:
    """`after` 뒤 · `before` 앞의 거래일. 달력이 없으면 평일로 어림한다(두 번째 값 = 어림)."""
    if has_cal:
        rows = conn.execute("SELECT cal_date FROM market_calendar WHERE is_trading_day = 1 "
                            "AND cal_date > ? AND cal_date < ? ORDER BY cal_date", (after, before)).fetchall()
        # 달력이 그 구간을 덮지 못하면(끝을 넘김) 평일로 어림한다
        end = conn.execute("SELECT MAX(cal_date) FROM market_calendar").fetchone()[0] or ""
        if end >= before:
            return [r[0] for r in rows], False
    out, d = [], date.fromisoformat(after) + timedelta(days=1)
    stop = date.fromisoformat(before)
    while d < stop:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out, True


def _verdict_portal(n: int) -> str:
    return "fresh" if n == 0 else "ok" if n == 1 else "late" if n == 2 else "stale"


def _mmdd_hm(iso: str | None) -> str:
    """2026-10-08T13:25:30+09:00 → 10-08 13:25 (안내 글)"""
    return f"{iso[5:10]} {iso[11:16]}" if iso and len(iso) >= 16 else "—"


# ── 숫자 파일 — 러너가 회차 끝에 센 줄 수(자료 안내 · 관제가 같은 읽기) ──────────────
def load_numbers(state_dir: Path | None) -> dict:
    """러너가 쓴 숫자 파일 → {state, written_at, by, tables(열쇠 → {rows, last_date, verdict}) | None, extras | None, why}.

    state — ok(읽음) · none(파일 없음) · old(판이 다름) · error(읽지 못함 — 깨진 JSON · 꼴이 다름). ok 가 아니면 tables · extras 는
    None 이고 `why` 에 관리자용 까닭을 단다(화면 글은 읽는 쪽의 안내 줄). 파일은 몇 KB 라 요청마다 읽는다(캐시 없음 — 러너가 막
    다시 쓴 판을 곧바로 보인다). 「없음」 표는 줄 수 None(0 이 아니다) · verdict missing 으로 바꿔 읽는 쪽이 「없음」 이면 0 을 쓰지
    않는 규칙을 그대로 쓰게 한다. `extras`(관제 밖 자료 여덟 · 3단계)는 그 칸이 없는 옛 러너 파일이면 None 이다(여덟만 「기다림」).
    2026-10-15 까지 자료 안내(`data_guide`)에 있던 것을 관제도 쓰게 옮겼다 — 두 화면이 같은 파일을 다르게 읽지 않게(SSoT).
    """
    out = {"state": "none", "written_at": None, "by": None, "tables": None, "extras": None, "why": ""}
    if state_dir is None:
        return {**out, "why": "수집 폴더가 없다 — 이 PC 에서 매일 수집을 돌리지 않는다"}
    path = state_dir / NUMBERS_FILE
    if not path.exists():
        return {**out, "why": f"{NUMBERS_FILE} 이 아직 없다 — 러너가 회차 끝 · 한 단계 다시 · steps --write 때 쓴다"}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return {**out, "state": "error", "why": f"{NUMBERS_FILE} 을 읽지 못했다: {type(e).__name__}"}
    if not isinstance(raw, dict) or not isinstance(raw.get("tables"), list):
        return {**out, "state": "error", "why": f"{NUMBERS_FILE} 의 꼴이 다르다 — tables 목록이 없다"}
    if raw.get("schema") != NUMBERS_SCHEMA:
        return {**out, "state": "old", "why": f"{NUMBERS_FILE} 의 판({raw.get('schema')})이 앱이 아는 판({NUMBERS_SCHEMA})과 "
                                              "다르다 — 다음 회차에 러너가 새 판으로 쓴다"}

    def rows_of(items) -> dict[str, dict]:
        got: dict[str, dict] = {}
        for t in items:
            if not isinstance(t, dict) or not t.get("key"):
                continue
            missing = bool(t.get("missing"))
            got[t["key"]] = {"rows": None if missing else t.get("rows"), "last_date": None if missing else t.get("last_date"),
                             "first_date": None if missing else t.get("first_date"), "verdict": "missing" if missing else "ok"}
        return got

    extras = raw.get("extras")
    return {"state": "ok", "written_at": raw.get("written_at"), "by": raw.get("by"), "tables": rows_of(raw["tables"]),
            "extras": rows_of(extras) if isinstance(extras, list) else None, "why": ""}


def last_run_event(runner: dict | None) -> str | None:
    """러너 기록의 가장 늦은 일 — 회차가 끝난 때 · 한 단계 다시 · 채우기를 한 때 가운데 늦은 것(ISO). 없으면 None."""
    last = (runner or {}).get("last") or {}
    stamps = [last.get("finished_at")] + [r.get("at") for r in last.get("reruns") or [] if isinstance(r, dict)]
    parsed = [(_parse_ts(s), s) for s in stamps if s]
    parsed = [(p, s) for p, s in parsed if p is not None]
    return max(parsed)[1] if parsed else None


def numbers_stale(written_at: str | None, runner: dict | None) -> bool:
    """숫자 파일이 마지막 수집(한 단계 다시 포함)보다 앞인가 — 러너가 그 뒤에 파일을 못 썼다(🟡 「기록 파일을 쓰지 못했다」)."""
    ev = last_run_event(runner)
    w, e = _parse_ts(written_at), _parse_ts(ev)
    return bool(w and e and w < e)


def counts_view(*, running: bool, numbers: dict | None = None, runner: dict | None = None) -> tuple[dict, str]:
    """관제 표의 행 수와 그 상태 — 러너가 회차 끝에 쓴 숫자 파일에서 읽는다(자료 안내 3단계 · 2026-10-15 · 세지 않는다).

    fresh   마지막 수집(한 단계 다시 포함) 뒤에 쓴 파일 — 그 값(도는 중이어도 지난 수집 값 그대로 · 안내 글은 get_status)
    stale   마지막 수집 뒤에 파일을 못 썼다 — 지난 값과 까닭
    none · old · error   파일 없음 · 판이 다름 · 읽지 못함 — 빈 사전(행 수 「—」 · 말없이 세지 않는다)
    이름 · 키워드로 부르는 꼴 · (사전, 상태) 답은 2026-10-02 판과 같다 — 리밸런싱 시험(`test_rebalance_daily.ready_data`)이 갈아
    끼운다(이름은 지키고 뜻만 바꿈). `running` 은 그 꼴을 지키려고 받는다(값을 바꾸지 않는다).
    """
    nums = numbers if numbers is not None else {"state": "none"}
    if nums.get("state") != "ok":
        return {}, nums.get("state") or "none"
    rows = {k: t.get("rows") for k, t in (nums.get("tables") or {}).items()}
    return rows, ("stale" if numbers_stale(nums.get("written_at"), runner) else "fresh")


def _rows_note(state: str, written_at: str | None, running: bool) -> str:
    """관제 행 수의 안내 글(화면이 그대로 보인다 · 명령 없음 — 모두가 보는 답). 기준일 · 판정은 행 수와 따로 맞다."""
    at = _mmdd_hm(written_at)
    if state == "fresh":
        return f"일일 갱신이 도는 중이라 행 수는 지난 수집({at}) 기준이다" if running else ""
    return {
        "stale": f"행 수는 {at} 수집 기준이다 — 마지막 수집 뒤에 숫자를 새로 쓰지 못했다",
        "none": "행 수는 매일 수집이 끝날 때 센다 — 아직 숫자 파일이 없다(다음 수집 뒤에 보인다) · 기준일 · 판정은 그대로 맞다",
        "old": "숫자 파일이 옛 판이라 행 수를 비워 둔다 — 다음 수집 때 새로 쓴다 · 기준일 · 판정은 그대로 맞다",
        "error": "숫자 파일을 읽지 못해 행 수를 비워 둔다 — 기준일 · 판정은 그대로 맞다",
    }.get(state, "")


def _next_trading(conn: sqlite3.Connection, has_cal: bool, day: str) -> str:
    """`day` 다음 거래일(공개 마감 셈 — 영업일을 거래일 달력으로 어림). 달력이 그 뒤를 덮지 못하면 다음 평일로 어림한다."""
    if has_cal:
        r = conn.execute("SELECT MIN(cal_date) FROM market_calendar WHERE is_trading_day = 1 AND cal_date > ?",
                         (day,)).fetchone()
        if r and r[0]:
            return r[0]
    d = date.fromisoformat(day) + timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d.isoformat()


def _prev_trading(conn: sqlite3.Connection, has_cal: bool, tiso: str) -> str | None:
    """오늘 앞 마지막 거래일 — 달력이 없으면 None(공시 목록 판정을 하지 않는다 · 짐작하지 않는다)."""
    if not has_cal:
        return None
    r = conn.execute("SELECT cal_date FROM market_calendar WHERE is_trading_day = 1 AND cal_date < ? "
                     "ORDER BY cal_date DESC LIMIT 1", (tiso,)).fetchone()
    return r[0] if r else None


def _apply_deadline(conn: sqlite3.Connection, has_cal: bool, row: dict, behind: list[str], now: datetime,
                    hm: tuple[int, int]) -> None:
    """시세 · ETF · 지수(포털) — 빠진 첫 거래일의 공개 마감(다음 거래일 hm)으로 n = 1 을 「정상 · 공개 전」 과 「늦음 · 다시 받기」 로
    가르고, n = 2 도 「늦음 · 다시 받기」 로 적는다(첫날 마감이 이미 지났다). 3 이상은 「멈춤」 그대로(DF-91)."""
    first = behind[0]
    due = datetime.combine(date.fromisoformat(_next_trading(conn, has_cal, first)), dt_time(*hm), KST)
    row["deadline_at"] = due.isoformat(timespec="seconds")
    if len(behind) == 1 and now < due:
        row.update(verdict="ok", verdict_label=LABEL_BEFORE_PUBLISH,
                   detail=f"{first} 자료는 아직 공개 전이다 — 출처 약속은 다음 영업일 13:00 이후 · 마감 {due:%m-%d %H:%M}")
    elif len(behind) <= 2:
        row.update(verdict="late", verdict_label=LABEL_REFETCH,
                   detail=f"공개 마감({due:%m-%d %H:%M})이 지났는데 {' · '.join(behind)} 자료가 아직 없다")


def _apply_rule(conn: sqlite3.Connection, has_cal: bool, row: dict, rule: tuple, last: str, last_raw, *,
                now: datetime, tiso: str, prev_td: str | None, runner_last: dict | None) -> None:
    """「참고」 표의 신선도 규칙(`FRESHNESS`) — 공시 목록 · 기사 · 정책뉴스는 정한 창, 사건 자료는 마지막 회차의 그 단계 결과."""
    kind, value = rule
    if kind == "prev_day":
        if prev_td is None:
            row.update(verdict="info", detail="거래일 달력이 없어 전 거래일을 모른다")
        elif last < prev_td:
            row.update(verdict="late", detail=f"전 거래일({prev_td}) 자료가 없다 — 마지막 {last}")
        else:
            row.update(verdict="ok", detail=f"전 거래일({prev_td})까지 있다")
    elif kind == "max_hours":
        ts = _parse_ts(str(last_raw)) if last_raw else None
        if ts is None:
            row.update(verdict="info", detail="마지막 시각을 읽지 못했다")
        else:
            ts = ts if ts.tzinfo else ts.replace(tzinfo=KST)
            hours = (now - ts).total_seconds() / 3600
            row["last_at"] = ts.isoformat(timespec="seconds")
            if hours > value:
                row.update(verdict="late", detail=f"마지막 자료가 {hours:.0f}시간 전이다 — {value}시간이 넘었다")
            else:
                row.update(verdict="ok", detail=f"마지막 자료 {ts:%m-%d %H:%M} · {max(hours, 0):.0f}시간 전")
    elif kind == "gap_days":
        behind, approx = _trading_after(conn, has_cal, last, tiso)
        row.update(behind_trading_days=len(behind), approx=approx)
        if len(behind) >= value:
            row.update(verdict="late", detail=f"그 뒤 거래일 {len(behind)}일째 새 자료가 없다({', '.join(behind[:3])}"
                                              + (" …" if len(behind) > 3 else "") + ")")
        else:
            row.update(verdict="ok", detail=("오늘 앞 마지막 거래일까지 있다" if not behind else
                                             f"그 뒤 거래일 {len(behind)}일이 아직 없다({', '.join(behind)})"))
    elif kind == "step_checked":
        steps = {s.get("name"): s for s in ((runner_last or {}).get("steps") or []) if isinstance(s, dict)}
        s = steps.get(value)
        when = _parse_ts((runner_last or {}).get("started_at"))
        at = f"{when:%m-%d %H:%M} 회차" if when else "마지막 회차"
        if s is None:
            row.update(verdict="info", detail="회차 기록에 이 단계가 없어 확인했는지 모른다")
        elif s.get("rc") == 0:
            row.update(verdict="ok", detail=f"{at}가 확인했다 — 새 행이 없는 날도 정상")
        elif s.get("rc") is None:
            row.update(verdict="info", detail=f"{at}가 이 단계를 돌리지 않았다" + (f"({s['note']})" if s.get("note") else ""))
        else:
            row.update(verdict="late", detail=f"{at}에서 이 단계가 실패했다(종료코드 {s.get('rc')})")


def table_states(conn: sqlite3.Connection | None, today: date, rows_map: dict | None = None, *,
                 now: datetime | None = None, runner_last: dict | None = None) -> tuple[list[dict], dict]:
    """표마다 기준일 · 늦음 판정 · 행 수. `rows_map` 을 주면 행 수는 그 값(없는 표는 None = 세는 중)이고, 안 주면
    그 자리에서 센다(시험 · 명령 줄 — 큰 DB 에서는 느리다).

    `now` 는 공개 마감 판정의 지금 시각(DF-91) — 없으면 그날 0시(하루 밀린 시세는 「정상 · 공개 전」 · 고치기 전과 같은 판정 · 러너의
    자료 안내 숫자처럼 판정을 쓰지 않는 쪽). `runner_last` 는 마지막 회차 기록(`runner_state()["last"]`) — 사건 자료의 「그 단계를
    확인했나」 를 본다(없으면 「참고」)."""
    if conn is None:
        return [{"key": k, "table": t, "label": lab, "group": g, "source": src, "verdict": "missing",
                 "verdict_label": VERDICT_LABEL["missing"], "rows": 0, "last_date": None,
                 "detail": "수집 DB 가 없다"} for k, t, lab, g, src, *_ in TABLES], {}
    now = now or datetime.combine(today, dt_time(0, 0), KST)
    has_cal = _has_table(conn, "market_calendar") and \
        conn.execute("SELECT 1 FROM market_calendar LIMIT 1").fetchone() is not None
    out: list[dict] = []
    price_last = None
    tiso = today.isoformat()
    prev_td = _prev_trading(conn, has_cal, tiso)
    for key, table, label, group, source, mode, last_sql, count_sql in TABLES:
        row = {"key": key, "table": table, "label": label, "group": group, "source": source}
        if not _has_table(conn, table):
            row.update(verdict="missing", verdict_label=VERDICT_LABEL["missing"], rows=0, last_date=None,
                       detail="표가 아직 없다")
            out.append(row)
            continue
        last_raw = conn.execute(last_sql).fetchone()[0]
        last = _iso_day(last_raw)
        rows = rows_map.get(key) if rows_map is not None else conn.execute(count_sql).fetchone()[0]
        row.update(rows=rows, last_date=last)
        rule = FRESHNESS.get(key)
        if key == "price_daily":
            price_last = last
        if not last:
            row.update(verdict="missing", detail="행이 없다")
        elif mode in ("portal", "intraday"):
            behind, approx = _trading_after(conn, has_cal, last, tiso)
            v = _verdict_portal(len(behind))
            row.update(verdict=v, behind_trading_days=len(behind), behind_dates=behind[:10], approx=approx,
                       detail=("오늘 앞 마지막 거래일까지 있다" if not behind else
                               f"그 뒤 거래일 {len(behind)}일이 아직 없다({', '.join(behind[:3])}"
                               + (" …" if len(behind) > 3 else "") + ")"
                               + (" — 포털은 다음 날 낮에 준다" if v == "ok" else "")))
            if rule and rule[0] == "deadline" and behind:
                _apply_deadline(conn, has_cal, row, behind, now, rule[1])
        elif mode == "derived":
            if price_last and last < price_last:
                lag, _ = _trading_after(conn, has_cal, last, (date.fromisoformat(price_last) + timedelta(days=1)).isoformat())
                row.update(verdict="late", behind_trading_days=len(lag),
                           detail=f"주식 일봉({price_last})보다 {len(lag)}거래일 뒤처졌다 — 다음 갱신이 다시 만든다")
            else:
                row.update(verdict="ok", detail="주식 일봉과 같은 날까지 있다")
        elif mode == "calendar":
            left = (date.fromisoformat(last) - today).days
            upd = conn.execute("SELECT MAX(updated_at) FROM market_calendar").fetchone()[0]
            row["updated_at"] = upd
            if left < 60:
                row.update(verdict="late", detail=f"달력 끝이 {left}일 남았다 — 내년 공휴일이 발표되면 늘어난다")
            else:
                row.update(verdict="ok", detail=f"{last} 까지 있다 · 만든 시각 {(upd or '')[:16].replace('T', ' ')}")
        elif rule:
            _apply_rule(conn, has_cal, row, rule, last, last_raw, now=now, tiso=tiso, prev_td=prev_td,
                        runner_last=runner_last)
        else:
            row.update(verdict="info", detail="")
        row.setdefault("verdict_label", VERDICT_LABEL[row["verdict"]])   # 마감을 아는 판정은 제 이름(「정상 · 공개 전」 등)을 이미 적었다
        out.append(row)

    cal: dict = {}
    if has_cal:
        nxt = conn.execute("SELECT cal_date FROM market_calendar WHERE is_trading_day = 1 AND cal_date >= ? "
                           "ORDER BY cal_date LIMIT 1", (tiso,)).fetchone()
        today_row = conn.execute("SELECT is_trading_day, reason FROM market_calendar WHERE cal_date = ?",
                                 (tiso,)).fetchone()
        cal = {
            "today_is_trading_day": bool(today_row[0]) if today_row else None,
            "today_reason": today_row[1] if today_row else "",
            "next_trading_day": nxt[0] if nxt else None,
            "previous_trading_day": prev_td,
        }
    return out, cal


def _sql_counts(conn: sqlite3.Connection, table: str, count_sql: str, last_sql: str, first_sql: str | None) -> dict:
    """한 표의 줄 수 · 마지막 날 · 처음 날 — 표가 없거나 행이 없으면 「없음」(줄 수 None · 0 이 아니다)."""
    if not _has_table(conn, table):
        return {"rows": None, "last_date": None, "first_date": None, "missing": True}
    n = conn.execute(count_sql).fetchone()[0]
    if not n:
        return {"rows": None, "last_date": None, "first_date": None, "missing": True}
    last = conn.execute(last_sql).fetchone()[0]
    first = conn.execute(first_sql).fetchone()[0] if first_sql else None
    return {"rows": n, "last_date": _iso_day(last), "first_date": _iso_day(first), "missing": False}


def extra_counts(market: sqlite3.Connection | None, cdir: Path | None, state_dir: Path | None, *,
                 glossary: Path | None = None) -> list[dict]:
    """관제 밖 자료 여덟의 잰 사실 — [{key, rows, last_date, first_date, missing(, why)}] (`EXTRA_KEYS` 차례 · 판정 없음).

    **러너만 부른다**(`scripts/daily_update.table_numbers` — 회차 끝 · 한 단계 다시 뒤 · `steps --write`). 앱은 요청 때 세지 않는다.
    `market` 은 러너가 이미 읽기 전용으로 연 수집 DB 연결(일정 셋 — corp_schedule · holiday_kasi · policy_meeting) · 근거 · 섹터 법령 ·
    검색 DB 는 수집 폴더(`cdir`)에서 **읽기 전용(`mode=ro`)으로 열고 바로 닫는다** — 셋은 롤백 저널이라 보조 파일이 없다(DF-67 · DF-74 —
    도커 앱이 읽기 전용으로 붙여 여는 파일). 용어는 앱 파일(`GLOSSARY_FILE`)의 용어 수 · 회차 기록은 상태 폴더 이력 줄(깨진 줄은 세지
    않는다 · 건너뛴 회차 줄은 센다). 파일이 없으면 「없음」(까닭 없음 — 그 PC 에 그 자료가 없을 뿐) · 열거나 읽지 못하면 그 줄만 「없음」
    과 관리자용 까닭(`why`) — 한 자료 때문에 숫자 파일 전체를 못 쓰지 않게.
    """
    out: dict[str, dict] = {}
    missing = {"rows": None, "last_date": None, "first_date": None, "missing": True}
    for key, fname, table, count_sql, last_sql, first_sql in EXTRA_SQL:
        try:
            if fname == "market.sqlite3":
                out[key] = _sql_counts(market, table, count_sql, last_sql, first_sql) if market is not None else dict(missing)
                continue
            path = cdir / fname if cdir is not None else None
            if path is None or not path.exists():
                out[key] = dict(missing)
                continue
            conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=5)
            try:
                out[key] = _sql_counts(conn, table, count_sql, last_sql, first_sql)
            finally:
                conn.close()
        except sqlite3.Error as e:
            out[key] = {**missing, "why": f"{fname} {table} 을 읽지 못했다: {type(e).__name__}: {e}"}
    g = glossary or GLOSSARY_FILE
    try:
        terms = json.loads(g.read_text(encoding="utf-8")).get("terms")
        out["glossary"] = ({"rows": len(terms), "last_date": None, "first_date": None, "missing": False}
                           if isinstance(terms, list) and terms else dict(missing))
    except FileNotFoundError:
        out["glossary"] = dict(missing)
    except (OSError, ValueError, AttributeError) as e:
        out["glossary"] = {**missing, "why": f"{g.name} 을 읽지 못했다: {type(e).__name__}"}
    days: list[str] = []
    try:
        lines = (state_dir / "daily_update_history.jsonl").read_text(encoding="utf-8").splitlines() if state_dir else []
    except OSError:
        lines = []
    for ln in lines:
        try:
            h = json.loads(ln)
        except ValueError:
            continue
        if isinstance(h, dict) and isinstance(h.get("started_at"), str) and len(h["started_at"]) >= 10:
            days.append(h["started_at"][:10])
    out["run_history"] = ({"rows": len(days), "last_date": max(days), "first_date": min(days), "missing": False}
                          if days else dict(missing))
    # 모의투자 그림자 일지 — 줄 = 판마다 거래일 행의 합(규칙 둘이면 하루 두 줄) · 날짜 = 행 파일 이름의 거래일
    # (rows/<규칙>/v<판>/<거래일>.parquet). 지문 목록이 없거나 깨졌으면 「없음」(그 PC 에 일지가 없다 · 앱 DB 는 세지 않는다).
    man = _read_json(cdir.parent.joinpath(*PAPER_JOURNAL_MANIFEST)) if cdir is not None else None
    files = man.get("files") if isinstance(man, dict) else None
    dates = sorted(rel.rsplit("/", 1)[-1][:10] for rel, m in (files if isinstance(files, dict) else {}).items()
                   if isinstance(m, dict) and m.get("kind") == "day")
    out["paper_journal"] = ({"rows": len(dates), "last_date": dates[-1], "first_date": dates[0], "missing": False}
                            if dates else dict(missing))
    return [{"key": k, **out[k]} for k in EXTRA_KEYS]


# ── HF ────────────────────────────────────────────────────────────────────
def hf_state(cdir: Path | None) -> list[dict]:
    if cdir is None:
        return []
    out = []
    man = _read_json(cdir.parent / "hf_export" / "meta" / "manifest.json")
    if man:
        up = man.get("uploaded") or {}
        out.append({"repo": up.get("repo_id") or man.get("repo_id") or "qurious-quant/krx-daily-market",
                    "what": "일봉 · 수정주가 · TR · 배당(원자료 공유)",
                    "tag": up.get("tag"), "uploaded_at": up.get("at"), "exported_at": man.get("generated_at")})
    oman = _read_json(cdir / "ohlcv_export" / "manifest.json")
    if oman:
        # 업로드 기록은 상태 폴더(scripts/hf_ohlcv.py 가 올린 뒤 씀) — 없으면 매니페스트의 uploaded 칸
        up = _read_json(cdir / "state" / "hf_ohlcv_last.json") or oman.get("uploaded") or {}
        out.append({"repo": "qurious-quant/krx-ohlcv", "what": "OHLCV 규격 자료(ohlcv-v1)",
                    "tag": up.get("tag"), "uploaded_at": up.get("at"), "exported_at": oman.get("built_at"),
                    "as_of": oman.get("as_of"), "rows": oman.get("rows")})
    # 모의투자 그림자 일지 원장(2026-10-24) — 올리기 기록이 있을 때만(일지를 등록하지 않은 PC 는 줄이 없다)
    pj = _read_json(cdir / "state" / PAPER_JOURNAL_HF_LAST)
    if pj:
        out.append({"repo": pj.get("repo_id") or "qurious-quant/qurious-paper-log", "what": "모의투자 그림자 일지(추가만)",
                    "tag": None, "uploaded_at": pj.get("at"), "exported_at": None,
                    "rows": (pj.get("counts") or {}).get("day")})
    return out


# ── 복구 시험(2차-3 · 2026-10-18) ─────────────────────────────────────────
#: 도구(scripts/hf_dataset.py)가 쓰는 백업 판정 기록 · 주간 리허설(scripts/weekly_rehearsal.py)의 상태 기록 — 상태 폴더 안 이름.
#: 앱 컨테이너에는 scripts/ 가 없어 이름을 여기에도 적는다(같은지 TC-WR 이 맞댄다).
BACKUP_STATUS_FILE = "hf_backup_status.json"
WEEKLY_REHEARSAL_FILE = "weekly_rehearsal.json"
#: 마지막 성공 리허설에서 이만큼 지나면 「오래됨」 — 주 1회 + 하루 여유(예약 쪽 STALE_AFTER_DAYS 와 같은지 TC-WR 이 맞댄다).
REHEARSAL_STALE_DAYS = 8
REHEARSAL_COMMAND = "python scripts/hf_dataset.py restore"
REHEARSAL_STATE = {"ok": "최근", "stale": "오래됨", "failed": "실패", "never": "없음", "unknown": "모름"}


def rehearsal_view(snap: dict | None, weekly: dict | None, now: datetime) -> dict:
    """「마지막 성공 리허설 n일 전」 — 도구가 판정 기록에 실은 `rehearsal` 칸(증거)과 주간 예약 기록을 읽기만 한다.

    날 수는 KST 날짜로 센다(어제 밤 리허설은 「1일 전」). 마지막 리허설이 마지막 성공보다 뒤에 실패했으면 「실패」 — 성공 날짜도
    함께 보인다. 성공 기록이 없으면 지어내지 않고 「없음」 + 돌릴 명령. 판정 기록에 리허설 칸 자체가 없으면(옛 도구가 쓴 기록 ·
    기록 없음) 「없음」 이 아니라 「모름」 — 리허설은 있었을 수 있다. 예약 칸은 등록(install)이 쓴 것만 믿는다.
    """
    if not isinstance((snap or {}).get("rehearsal"), dict):
        sched = (weekly or {}).get("schedule")
        return {"state": "unknown", "state_label": REHEARSAL_STATE["unknown"],
                "label": "리허설 기록을 아직 읽지 못했습니다(다음 회차가 판정 기록을 쓰면 생깁니다)",
                "last_ok_at": None, "days_ago": None, "schedule": sched,
                "schedule_label": f"{sched} 자동" if sched else "주간 예약 없음(손으로 돌림)",
                "command": REHEARSAL_COMMAND}
    reh = snap["rehearsal"]
    ok_at = _parse_ts((reh.get("last_ok") or {}).get("at"))
    last = reh.get("last") or {}
    last_at = _parse_ts(last.get("at"))
    days = (now.date() - ok_at.astimezone(KST).date()).days if ok_at else None
    if ok_at is None:
        state = "never"
    elif last.get("ok") is False and last_at is not None and last_at > ok_at:
        state = "failed"
    elif days > REHEARSAL_STALE_DAYS:
        state = "stale"
    else:
        state = "ok"
    ago = "" if days is None else ("오늘" if days == 0 else f"{days}일 전")
    when = f"{ok_at.astimezone(KST):%m-%d}" if ok_at else ""
    if state == "never":
        label = "아직 성공한 복원 리허설이 없습니다"
    elif state == "failed":
        label = f"마지막 리허설 실패({last_at.astimezone(KST):%m-%d}) · 마지막 성공 {ago}({when})"
    else:
        label = f"마지막 성공 {ago}({when})" + (" · 주 1회보다 오래됨" if state == "stale" else "")
    sched = (weekly or {}).get("schedule")
    out = {"state": state, "state_label": REHEARSAL_STATE[state], "label": label,
           "last_ok_at": ok_at.isoformat() if ok_at else None, "days_ago": days,
           "schedule": sched, "schedule_label": f"{sched} 자동" if sched else "주간 예약 없음(손으로 돌림)",
           "command": REHEARSAL_COMMAND if state != "ok" else None}
    if weekly and weekly.get("result"):
        out["last_round"] = {k: weekly.get(k) for k in ("finished_at", "result", "why")}
    return out


# ── 모으기 ────────────────────────────────────────────────────────────────
#: 한 단계 다시 돌리기 — 앱은 러너를 부를 수 없다(컨테이너는 수집 폴더를 읽기만 하고, 러너는 PC 쪽 프로세스다).
#: 화면에서 바로 돌릴 통로(쓰기 폴더 · 요청 표 등)는 정할 것이라, 지금은 PC 에서 돌릴 명령과 막히는 때를 알려 준다.
RERUN = {
    "from_screen": False,
    "command": "python scripts/daily_update.py run --only <단계>",
}


def rerun_help(catalog: dict) -> dict:
    """한 단계 다시 돌리기 도움말 — 「막히는 때」 는 러너 단계 목록의 회차 시각 · 막는 때 끝(`guards.full.to`)에서 만든다(D104 · 사본 없음).
    시각을 모르면 「회차 시각 모름」 으로 시작한다(겹치는 때를 짐작하지 않는다)."""
    hm = catalog.get("schedule")
    end = ((catalog.get("guards") or {}).get("full") or {}).get("to")
    when = (f"{hm[0]:02d}:{hm[1]:02d} 회차와 겹치는 때(회차 시작 − 그 단계 시간 한도 ~ {end or '회차 끝'})" if hm
            else f"{SCHEDULE_UNKNOWN} — 회차와 겹치는 때를 셀 수 없다")
    return {**RERUN, "blocked": f"{when} · 다른 실행이 도는 동안 · 올리기 단계는 --upload 와 함께만"}


def runner_detail(now: datetime | None = None) -> dict:
    """수집 일정 · 단계 화면(관리자) — 마지막 회차 · 회차 기록 · 단계 목록 · 이 PC 용량을 한 답에."""
    now = now or _now()
    cdir = collector_dir()
    sdir = cdir / "state" if cdir else None
    out = runner_state(sdir, now, admin=True)               # 관리자 답 — 실패한 단계의 까닭 · 로그 파일 이름을 싣는다(DF-101)
    cat = load_catalog(sdir)
    keys = ("name", "label", "group", "desc", "fatal", "derived", "upload", "timeout_min")
    # 빠진 날 채우기 명령(2026-10-08 · 러너 단계 정의의 `fill`) — 옛 단계 목록에는 칸이 없으니 빈 글로(없는 칸을 None 으로 두면
    # 화면이 「채우기 있음」 으로 잘못 읽을 수 있다)
    out["catalog"] = {"written_at": cat["written_at"],
                      "steps": [{**{k: s.get(k) for k in keys}, "fill": s.get("fill") or ""} for s in cat["steps"]]}
    out["disk"] = pc_disk(sdir)
    out["rerun"] = rerun_help(cat)
    out["checked_at"] = now.isoformat(timespec="seconds")
    return out


def get_status(now: datetime | None = None, *, use_cache: bool = True) -> dict:
    """화면이 30초마다 불러도 같은 답을 주게 30초 동안 둔다. 행 수는 러너가 회차 끝에 쓴 숫자 파일에서(세지 않는다 · 2026-10-15) ·
    기준일 · 판정은 수집 DB 의 마지막 날로 지금 본다."""
    if use_cache and now is None and _cache.get("value") and time.monotonic() - _cache["at"] < CACHE_SECONDS:
        return _cache["value"]
    now = now or _now()
    cdir = collector_dir()
    sdir = cdir / "state" if cdir else None
    runner = runner_state(sdir, now)
    nums = load_numbers(sdir)
    conn = _connect_ro()
    rows_state, rows_note = "fresh", ""
    try:
        rows_map = None
        if conn is not None:
            rows_map, rows_state = counts_view(running=runner["running"], numbers=nums, runner=runner)
            rows_note = _rows_note(rows_state, nums.get("written_at"), runner["running"])
        tables, cal = table_states(conn, now.date(), rows_map, now=now, runner_last=runner.get("last"))
    finally:
        if conn is not None:
            conn.close()
    worst = max((_RANK.get(t["verdict"], 0) for t in tables), default=1)
    if runner["state"] in ("failed",):
        worst = 2
    elif runner["state"] in ("late", "warning", "missing", "attention"):   # attention = 일부 건너뜀(채울 날이 남음)
        worst = max(worst, 1)
    verdict = ["ok", "warning", "error"][worst]
    price = next((t for t in tables if t["key"] == "price_daily"), {})
    value = {
        "checked_at": now.isoformat(timespec="seconds"),
        "verdict": verdict,
        "verdict_label": {"ok": "정상", "warning": "확인 필요", "error": "멈춤"}[verdict],
        "as_of": price.get("last_date"),
        "summary": f"주식 시세 기준일 {price.get('last_date') or '없음'} · 일일 갱신 {runner['label']}",
        "runner": runner,
        "tables": tables,
        "calendar": cal,
        "hf": hf_state(cdir),
        # 복구 시험 — 판정(verdict)에는 섞지 않는다(자료가 최신인가와 따로인 물음 · 화면이 줄 하나로 따로 보인다)
        "rehearsal": rehearsal_view(_read_json(sdir / BACKUP_STATUS_FILE) if sdir else None,
                                    _read_json(sdir / WEEKLY_REHEARSAL_FILE) if sdir else None, now),
        "source": "collector",
        "rows_state": rows_state,
        # 행 수를 센 때 = 숫자 파일을 쓴 때(러너) — load_numbers 는 읽은(ok) 파일에만 시각을 준다(없음 · 옛 판 · 깨짐은 None · 메우지 않는다)
        "rows_counted_at": nums.get("written_at"),
    }
    if rows_note:
        value["rows_note"] = rows_note
    if use_cache:
        _cache.update(at=time.monotonic(), value=value)
    return value
