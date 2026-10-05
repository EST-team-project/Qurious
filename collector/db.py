"""SQLite 스키마와 연결.

왜 Postgres 가 아닌가
---------------------
본체는 Postgres 를 쓴다(`app/database/postgres.py`). 그런데 수집기는 **스택이 안 떠도
돌아야** 하는 것이 존재 이유다(collector/config.py 머리말). SQLite 는 파일 하나이고
파이썬에 들어 있어 그 조건을 그대로 만족한다.

옮겨 갈 때를 대비해 표 모양은 Postgres 로 그대로 번역되게 잡아 두었다 — 특수 타입을
쓰지 않고, 기본키를 자연키로 잡았다. 옮기는 일은 적재가 안정된 뒤에 한다.

표 일곱
-------
받은 것 (출처가 준 값 그대로) ::

    raw_response      응답 원문. 정규화를 다시 돌릴 수 있는 **유일한** 근거.
    price_daily       정규화한 일별 시세. 분석이 읽는 표.
    dividend          배당 공시에서 읽은 사실. 현금배당은 시세 표에 안 나타난다.
    ingest_day        수집 상태. 중단한 자리에서 다시 시작하는 근거.

계산한 것 (언제든 지우고 다시 만든다) ::

    price_adjusted     수정주가. preprocess 가 만든다. 분할·권리락만 고친 **PR** 계열.
    corporate_action   가격이 끊긴 날과 그 계수.
    price_total_return 총수익(TR) 계열. total_return 이 price_adjusted + dividend 로 만든다.

OHLCV 규격(`collector/ohlcv.py` · 2026-10-01)으로 더한 넷 ::

    etf_daily          ETF 일별 시세(받은 것 · 포털 증권상품시세)
    index_daily        지수 일별 시세(받은 것 · 포털 지수시세)
    price_intraday     분봉(받은 것 · 야후) — 원문은 남기지 않는다
    intraday_universe  분봉을 받는 종목과 그 근거(판마다)

거래일 달력(`collector/market_calendar.py` · 2026-10-02)으로 더한 셋 ::

    holiday_kasi       공휴일(받은 것 · 한국천문연구원 특일 정보)
    market_calendar    하루 한 행 거래일 여부 · 휴장 까닭(계산한 것 — 앞날 포함)
    market_event       금융 일정 — 휴장 · 파생 만기 · 배당 기준일 · 배당락일(계산한 것)

공시 · 재무(`collector/disclosure.py` · `collector/financials.py` · 2026-10-04 · 설계서 5.1.5)로 더한 둘 ::

    disclosure          공시 목록(받은 것 · DART list.json · 상장사 · 유형 A~J)
    financial_statement 재무제표 주요계정(받은 것 · DART fnlttMultiAcnt · 정정본마다 한 벌)

이름표 · 검색 색인은 이 파일에 두지 않는다 — 다시 만드는 것이라 `data/collector/search.sqlite3` 에 따로 둔다
(`collector/search_index.py`).

**받은 것과 계산한 것을 섞지 않는다.** 계산 규칙은 바뀌고, 바뀌면 전부 다시 만들어야
하는데 원본에 덮어써 두면 되돌릴 근거가 없어진다.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

from collector import config

SCHEMA = """
-- ── 1. 응답 원문 ────────────────────────────────────────────────────────────
-- 압축 전 원문의 sha256 을 함께 둔다. 압축 결과는 라이브러리 버전에 따라 달라질 수
-- 있어서, 그 값을 지문으로 삼으면 언젠가 "같은 자료인데 다르다" 가 나온다.
CREATE TABLE IF NOT EXISTS raw_response (
    source      TEXT    NOT NULL,          -- portal | kis | ecos | dart
    target      TEXT    NOT NULL,          -- 예: price/20260917
    fetched_at  TEXT    NOT NULL,          -- KST ISO8601. "언제부터 알 수 있었나"의 근거
    body        BLOB    NOT NULL,          -- gzip 압축한 응답 바이트
    sha256      TEXT    NOT NULL,          -- 압축 '전' 원문의 지문
    bytes       INTEGER NOT NULL,          -- 압축 전 크기
    compression TEXT    NOT NULL DEFAULT 'gzip',
    http_status INTEGER,
    note        TEXT    NOT NULL DEFAULT '',
    PRIMARY KEY (source, target, fetched_at)
);
CREATE INDEX IF NOT EXISTS ix_raw_source_target ON raw_response(source, target);

-- ── 2. 정규화한 일별 시세 ───────────────────────────────────────────────────
-- 값은 포털 응답 그대로다. 수정주가는 여기에 **담지 않는다** — 조정은 과거 전체를
-- 다시 쓰는 일이라, 원본 표를 덮어쓰면 "원본이 무엇이었나" 를 잃는다.
-- 조정은 preprocess 가 읽어서 파생 표로 만든다.
CREATE TABLE IF NOT EXISTS price_daily (
    bas_dt      TEXT    NOT NULL,          -- YYYYMMDD
    srtn_cd     TEXT    NOT NULL,          -- 단축코드 6자리
    isin_cd     TEXT    NOT NULL DEFAULT '',
    itms_nm     TEXT    NOT NULL DEFAULT '',
    mrkt_ctg    TEXT    NOT NULL DEFAULT '',   -- KOSPI | KOSDAQ | KONEX
    clpr        INTEGER,                   -- 종가
    vs          INTEGER,                   -- 전일 대비 '금액'. 조정계수의 근거(README 참고)
    flt_rt      REAL,                      -- 전일 대비 '등락률'. 소수 2자리라 검증용으로만
    mkp         INTEGER,                   -- 시가. 0 이면 그날 거래가 없었다
    hipr        INTEGER,
    lopr        INTEGER,
    trqu        INTEGER,                   -- 거래량
    tr_prc      INTEGER,                   -- 거래대금
    lstg_st_cnt INTEGER,                   -- 상장주식수. 분할·증자를 여기서도 볼 수 있다
    mrkt_tot_amt INTEGER,                  -- 시가총액
    halted      INTEGER NOT NULL DEFAULT 0,-- 거래정지 판정(0/1). 판정 규칙은 preprocess
    raw_sha256  TEXT    NOT NULL DEFAULT '', -- 이 행이 나온 원문
    PRIMARY KEY (bas_dt, srtn_cd)
);
CREATE INDEX IF NOT EXISTS ix_price_srtn ON price_daily(srtn_cd, bas_dt);
CREATE INDEX IF NOT EXISTS ix_price_mrkt ON price_daily(mrkt_ctg, bas_dt);

-- ── 3. 기준일별 수집 상태 ───────────────────────────────────────────────────
-- 백필은 몇 시간 걸린다. 중간에 끊긴다는 전제로 만든다.
--
-- status 가 넷인 이유:
--   done     행을 받아 넣었다
--   empty    응답은 정상인데 0건이었다. **휴장일과 "아직 안 올라온 거래일" 이
--            똑같이 0건으로 온다** — 포털은 둘을 구분해 주지 않는다(실측 2026-09-19).
--            그래서 empty 는 확정이 아니라 보류다.
--   holiday  empty 가 재시도 한도를 넘겨 휴장으로 확정한 것
--   error    호출 자체가 실패했다. 재시도 대상
CREATE TABLE IF NOT EXISTS ingest_day (
    source      TEXT    NOT NULL,
    bas_dt      TEXT    NOT NULL,
    status      TEXT    NOT NULL,
    rows        INTEGER NOT NULL DEFAULT 0,
    attempts    INTEGER NOT NULL DEFAULT 0,
    updated_at  TEXT    NOT NULL,
    message     TEXT    NOT NULL DEFAULT '',
    PRIMARY KEY (source, bas_dt)
);
CREATE INDEX IF NOT EXISTS ix_ingest_status ON ingest_day(source, status);

-- ── 4. 수정주가 (파생) ──────────────────────────────────────────────────────
-- price_daily 를 덮어쓰지 않고 따로 쌓는다. 조정은 규칙이 바뀌면 전부 다시 계산해야
-- 하는데, 원본 표에 덮어쓰면 "원본이 무엇이었나" 를 잃어 되돌릴 수 없다.
-- 이 표는 언제든 통째로 지우고 preprocess 가 다시 만든다.
CREATE TABLE IF NOT EXISTS price_adjusted (
    bas_dt      TEXT    NOT NULL,
    srtn_cd     TEXT    NOT NULL,
    adj_clpr    REAL,                      -- 조정 종가 (가장 최근 날을 1.0 기준으로)
    adj_mkp     REAL,
    adj_hipr    REAL,
    adj_lopr    REAL,
    cum_factor  REAL    NOT NULL,          -- 이 날에 곱해진 누적 조정계수
    PRIMARY KEY (bas_dt, srtn_cd)
);
CREATE INDEX IF NOT EXISTS ix_adj_srtn ON price_adjusted(srtn_cd, bas_dt);

-- ── 5. 조정 이벤트 ──────────────────────────────────────────────────────────
-- 분할·병합·권리락처럼 '가격이 끊기는' 날. 사람이 눈으로 확인할 수 있게 남긴다.
-- 포털은 조정 사유를 알려 주지 않으므로(KIS 도 분할일에 사유 필드가 비어 있었다, #33)
-- **사유 칸은 비워 두고 계수만 적는다.** 추측해서 채우지 않는다.
CREATE TABLE IF NOT EXISTS corporate_action (
    bas_dt      TEXT    NOT NULL,
    srtn_cd     TEXT    NOT NULL,
    itms_nm     TEXT    NOT NULL DEFAULT '',
    prev_clpr   INTEGER,                   -- 직전 거래일 종가 (조정 전)
    base_price  INTEGER,                   -- clpr - vs. 거래소가 정한 '조정 기준가'
    factor      REAL    NOT NULL,          -- base_price / prev_clpr
    lstg_before INTEGER,                   -- 상장주식수 변화도 함께 본다 (교차 확인)
    lstg_after  INTEGER,
    -- f(가격계수) x q(주식수비율). 분할이면 1 이어야 한다. 1 에서 멀면 두 신호가
    -- 어긋난 것이고, 어느 쪽이 맞는지는 자동으로 정하지 않는다 (preprocess 머리말).
    lstg_cross  REAL,
    needs_review INTEGER NOT NULL DEFAULT 0,
    -- split=주식수 변화와 일치 / rights=권리락(주식수 불변) / review=두 신호 모두 어긋남
    -- / shares=정지 뒤 vs 가 조용한데 주식수가 줄었다 → 주식수로 조정 (결함 DF-01)
    kind        TEXT    NOT NULL DEFAULT 'review',
    PRIMARY KEY (bas_dt, srtn_cd)
);

-- ── 6. 배당 ─────────────────────────────────────────────────────────────────
-- 출처는 DART 「현금ㆍ현물배당결정」 공시 본문이다(sources/dart.py).
--
-- 왜 price_daily 와 따로 두나: 현금배당은 거래소가 기준가를 조정하지 않으므로
-- 시세 표의 어느 칸에도 나타나지 않는다. 가격에 섞을 수 있는 값이 아니라 수익률에
-- **더하는** 값이라, 표를 따로 둔다. 수정주가(price_adjusted)와 합쳐 TR 을 만든다.
--
-- 기본키를 (종목, 배당기준일)로 잡은 이유: 한 종목이 같은 기준일에 두 번 배당하는 일은
-- 없다. 정정공시는 접수번호만 달라지므로 '나중 접수번호가 이긴다' 로 처리한다
-- (sources/dart.py 의 upsert).
CREATE TABLE IF NOT EXISTS dividend (
    srtn_cd     TEXT    NOT NULL,          -- 단축코드 6자리
    record_dt   TEXT    NOT NULL,          -- 배당기준일 YYYYMMDD (공시에 적힌 값)
    rcept_no    TEXT    NOT NULL DEFAULT '',   -- 공시 접수번호. 원문 추적 키
    corp_code   TEXT    NOT NULL DEFAULT '',   -- DART 기업 고유번호 8자리
    itms_nm     TEXT    NOT NULL DEFAULT '',
    report_nm   TEXT    NOT NULL DEFAULT '',   -- 공시 제목. 정정공시 여부가 여기 보인다
    div_kind    TEXT    NOT NULL DEFAULT '',   -- 결산배당 | 분기배당 | 중간배당
    div_type    TEXT    NOT NULL DEFAULT '',   -- 현금배당 | 현물배당 | 현금ㆍ현물배당 (본문 「배당종류」 칸 그대로)
    dps         REAL,                      -- 1주당 배당금(원) 보통주식
    dps_pref    REAL,                      -- 1주당 배당금(원) 종류주식(우선주)
    yield_pct   REAL,                      -- 시가배당율(%). 검증용 — 주가와 대조하면 맞는다
    total_amt   INTEGER,                   -- 배당금총액(원)
    -- 배당락일. 기준일에서 **거래일 달력으로** 역산한 값이다(sources/dart.py 머리말).
    -- 공시에 적힌 값이 아니라 우리가 계산한 값이므로, 규칙이 바뀌면 다시 계산한다.
    ex_div_dt   TEXT    NOT NULL DEFAULT '',
    board_dt    TEXT    NOT NULL DEFAULT '',   -- 이사회결의일(결정일)
    raw_sha256  TEXT    NOT NULL DEFAULT '',   -- 이 행이 나온 공시 본문 원문
    -- 본문에서 필요한 칸을 못 읽었다. 추측해서 채우지 않고 여기에 표시만 한다 —
    -- 조용히 0원으로 담기면 백테스트가 조용히 틀린다.
    needs_review INTEGER NOT NULL DEFAULT 0,
    note        TEXT    NOT NULL DEFAULT '',
    PRIMARY KEY (srtn_cd, record_dt)
);
CREATE INDEX IF NOT EXISTS ix_div_exdt ON dividend(ex_div_dt);
CREATE INDEX IF NOT EXISTS ix_div_review ON dividend(needs_review);

-- ── 7. 총수익 계열 (파생) ───────────────────────────────────────────────────
-- price_adjusted(가격) + dividend(배당) = 실제로 번 돈.
--
-- 왜 price_adjusted 에 칸을 더하지 않고 표를 새로 두나: 둘은 **다시 만드는 조건이
-- 다르다.** 수정주가는 시세가 새로 들어오면 다시 만들고, TR 은 거기에 더해 배당 공시가
-- 새로 들어오거나 세율 가정이 바뀌면 다시 만든다. 한 표에 섞으면 배당 한 건 때문에
-- 수정주가 전체를 다시 계산하게 되고, 반대로 수정주가만 고쳤는데 TR 이 옛 배당 가정을
-- 그대로 물고 있는 일이 생긴다.
--
-- 지수는 종목마다 **첫 거래일을 1.0** 으로 둔다. 쓰는 쪽이 보는 것은 절대값이 아니라
-- 두 날 사이의 비율이므로 시작점이 달라도 된다.
-- ⚠️ price_adjusted 와 누적 방향이 반대다 — 수정주가는 오늘이 1.0(뒤→앞),
--    TR 은 첫날이 1.0(앞→뒤). 이유는 total_return.py 의 build 머리말에 적었다.
CREATE TABLE IF NOT EXISTS price_total_return (
    bas_dt       TEXT NOT NULL,
    srtn_cd      TEXT NOT NULL,
    tr_index     REAL,                     -- 총수익 지수 (세전). 첫 거래일 = 1.0
    tr_index_net REAL,                     -- 총수익 지수 (세후 15.4%)
    pr_index     REAL,                     -- 가격수익 지수. 같은 기준 — 비교용
    -- 그날의 배당 계수 = 1 + 주당배당금 ÷ 그날 종가. 배당이 없는 날은 1.0.
    -- 같은 날의 두 값을 나눈 것이라 **분할 조정과 무관**하다(total_return.py 머리말).
    div_factor   REAL NOT NULL DEFAULT 1.0,
    dps_applied  REAL,                     -- 그날 실제로 더한 주당 배당금(원). 없으면 NULL
    PRIMARY KEY (bas_dt, srtn_cd)
);
CREATE INDEX IF NOT EXISTS ix_tr_srtn ON price_total_return(srtn_cd, bas_dt);
CREATE INDEX IF NOT EXISTS ix_tr_dps ON price_total_return(dps_applied);

-- ── 7. ETF 일별 시세 (받은 것) ─────────────────────────────────────────────
-- 공공데이터포털 「금융위원회_증권상품시세정보」 getETFPriceInfo 하루치 전종목.
-- 실측 2026-10-01 (basDt=20260929): 1,171종목 · 459,653 B · 칸 18개.
-- 주식 시세(price_daily)와 칸이 달라(NAV · 기초지수 · 순자산) 표를 나눈다.
-- 수집 상태는 ingest_day 의 source='portal_etf' 줄이 맡는다.
CREATE TABLE IF NOT EXISTS etf_daily (
    bas_dt       TEXT    NOT NULL,         -- YYYYMMDD
    srtn_cd      TEXT    NOT NULL,         -- 단축코드 6자리(영문 섞임 — 예 0000D0)
    isin_cd      TEXT    NOT NULL DEFAULT '',
    itms_nm      TEXT    NOT NULL DEFAULT '',
    clpr         INTEGER,                  -- 종가
    vs           INTEGER,                  -- 전일 대비 금액 — 조정계수의 근거(주식과 같은 식)
    flt_rt       REAL,
    nav          REAL,                     -- 순자산가치(1좌당)
    mkp          INTEGER,                  -- 시가. 0 이면 그날 거래가 없었다
    hipr         INTEGER,
    lopr         INTEGER,
    trqu         INTEGER,                  -- 거래량
    tr_prc       INTEGER,                  -- 거래대금
    mrkt_tot_amt INTEGER,                  -- 시가총액
    st_lstg_cnt  INTEGER,                  -- 상장좌수
    bss_idx_nm   TEXT    NOT NULL DEFAULT '', -- 기초지수 이름
    bss_idx_clpr REAL,                     -- 기초지수 종가
    npt_tot_amt  INTEGER,                  -- 순자산총액
    halted       INTEGER NOT NULL DEFAULT 0,
    raw_sha256   TEXT    NOT NULL DEFAULT '',
    PRIMARY KEY (bas_dt, srtn_cd)
);
CREATE INDEX IF NOT EXISTS ix_etf_srtn ON etf_daily(srtn_cd, bas_dt);

-- ── 8. 지수 일별 시세 (받은 것) ────────────────────────────────────────────
-- 공공데이터포털 「금융위원회_지수시세정보」 getStockMarketIndex 하루치 전지수.
-- 실측 2026-10-01 (basDt=20260929): 171개 · KOSPI시리즈 53 · KRX시리즈 40 ·
-- KOSDAQ시리즈 39 · 테마지수 39.
-- ⚠️ **같은 이름이 시리즈마다 따로 있다**(「IT 서비스」 가 KOSPI · KOSDAQ 둘 다) —
--    그래서 기본키에 시리즈(idx_csf)가 들어간다. 이름만으로 고르면 다른 지수가 섞인다.
CREATE TABLE IF NOT EXISTS index_daily (
    bas_dt         TEXT    NOT NULL,
    idx_csf        TEXT    NOT NULL,       -- 시리즈: KOSPI시리즈 · KOSDAQ시리즈 · KRX시리즈 · 테마지수
    idx_nm         TEXT    NOT NULL,       -- 지수 이름
    epy_itms_cnt   INTEGER,                -- 구성 종목 수
    clpr           REAL,                   -- 종가(포인트)
    vs             REAL,
    flt_rt         REAL,
    mkp            REAL,
    hipr           REAL,
    lopr           REAL,
    trqu           INTEGER,
    tr_prc         INTEGER,
    lstg_mrkt_tot_amt INTEGER,             -- 상장 시가총액
    bas_pntm       TEXT    NOT NULL DEFAULT '', -- 기준 시점
    bas_idx        REAL,                   -- 기준 지수
    raw_sha256     TEXT    NOT NULL DEFAULT '',
    PRIMARY KEY (bas_dt, idx_csf, idx_nm)
);
CREATE INDEX IF NOT EXISTS ix_index_nm ON index_daily(idx_nm, bas_dt);

-- ── 9. 분봉 (받은 것) ──────────────────────────────────────────────────────
-- 야후 파이낸스(yfinance) 5분 · 60분봉. 과거로 받을 수 있는 창이 짧아(60분 730거래일 ·
-- 5분 60거래일 · 2026-10-01 실측) 처음에 창 전체를 받고 날마다 쌓는다.
-- ⚠️ 야후 분봉은 **09:00~15:00 만** 준다(15:00~15:30 · 종가 단일가 없음) — 분봉 거래량 합은
--    일봉의 68~77%(삼성전자 2026-09-23~30). 일봉을 이 표에서 만들지 않는다.
-- ⚠️ 야후는 분할을 비율로 고친 값을 준다(price_basis='adj_split'). 원문 보관 대상
--    (raw_store.ALLOWED_SOURCES)이 아니어서 정규화 결과만 남긴다.
CREATE TABLE IF NOT EXISTS price_intraday (
    symbol      TEXT    NOT NULL,          -- 단축코드 6자리
    timeframe   TEXT    NOT NULL,          -- 60m | 5m | 1m
    bar_start   TEXT    NOT NULL,          -- 봉 시작 시각 KST ISO8601(+09:00)
    trade_date  TEXT    NOT NULL,          -- KST 날짜 YYYY-MM-DD
    open        REAL,
    high        REAL,
    low         REAL,
    close       REAL,
    volume      INTEGER,
    session     TEXT    NOT NULL,          -- regular | close_auction | pre_open | outside
    source      TEXT    NOT NULL,          -- yahoo
    price_basis TEXT    NOT NULL,          -- adj_split (야후)
    fetched_at  TEXT    NOT NULL,          -- 받은 시각 KST
    PRIMARY KEY (symbol, timeframe, bar_start)
);
CREATE INDEX IF NOT EXISTS ix_intraday_day ON price_intraday(timeframe, trade_date);

-- ── 10. 분봉 수집 대상 (유니버스) ──────────────────────────────────────────
-- 모든 종목의 분봉은 받지 않는다(설계서 2.2) — 누가 대상인지와 그 근거를 판마다 남긴다.
CREATE TABLE IF NOT EXISTS intraday_universe (
    version     TEXT    NOT NULL,          -- 판 이름 — 예 u1-20260929
    symbol      TEXT    NOT NULL,
    itms_nm     TEXT    NOT NULL DEFAULT '',
    market      TEXT    NOT NULL,          -- KOSPI | KOSDAQ | ETF
    reason      TEXT    NOT NULL,          -- 뽑힌 근거 — 예 'KOSPI 시가총액 12위'
    rank        INTEGER,
    PRIMARY KEY (version, symbol)
);

-- ── 11. 공휴일 (받은 것) ───────────────────────────────────────────────────
-- 한국천문연구원 특일 정보(공공데이터포털 getRestDeInfo) 응답 행 그대로. 한 해를 받으면 그 해
-- 행을 지우고 다시 넣는다(임시공휴일이 더해지거나 빠진 것을 따라간다). 만드는 쪽: market_calendar.py
CREATE TABLE IF NOT EXISTS holiday_kasi (
    locdate     TEXT    NOT NULL,          -- YYYY-MM-DD
    date_name   TEXT    NOT NULL,          -- 예 추석 · 대체공휴일(삼일절) · 노동절 · 전국동시지방선거
    is_holiday  TEXT    NOT NULL,          -- Y | N (응답 그대로)
    date_kind   TEXT    NOT NULL DEFAULT '',
    seq         INTEGER,
    fetched_at  TEXT    NOT NULL,          -- 받은 시각 KST
    PRIMARY KEY (locdate, date_name)
);

-- ── 12. 거래일 달력 (계산한 것) ────────────────────────────────────────────
-- 하루 한 행. 지난날은 시세로 확인(observed), 시세 마지막 날 뒤는 규칙 · 공휴일 표로 예정(rule).
-- 규칙 = 주말 + 공휴일 + 근로자의 날(5-1) + 연말 휴장일(12-31 · 주말이면 앞 평일). 2020~2026-09 시세와 0일 어긋남.
CREATE TABLE IF NOT EXISTS market_calendar (
    cal_date        TEXT    NOT NULL PRIMARY KEY,  -- YYYY-MM-DD
    is_trading_day  INTEGER NOT NULL,              -- 1 거래일 · 0 휴장
    reason          TEXT    NOT NULL DEFAULT '',   -- 휴장 까닭 — 공휴일 이름 · 토요일 · 일요일 · 근로자의 날 · 연말 휴장일
    basis           TEXT    NOT NULL,              -- observed | rule
    note            TEXT    NOT NULL DEFAULT '',   -- 규칙과 시세가 어긋난 날 · 시세가 아직 없는 날
    updated_at      TEXT    NOT NULL
);

-- ── 13. 금융 일정 (계산한 것) ──────────────────────────────────────────────
-- 설계서 5.2.4 표 9 의 일정 종류를 한 표에. 첫판은 넷 — 평일 휴장 · 파생 만기 · 배당 기준일 · 배당락일.
CREATE TABLE IF NOT EXISTS market_event (
    event_id    TEXT    NOT NULL PRIMARY KEY,      -- 종류:날짜(:종목) — 다시 만들어도 같은 키
    kind        TEXT    NOT NULL,                  -- market_closure | deriv_expiry | dividend_record | dividend_ex
    event_date  TEXT    NOT NULL,                  -- YYYY-MM-DD
    event_time  TEXT    NOT NULL DEFAULT '',       -- HH:MM (모르면 빈칸)
    market      TEXT    NOT NULL DEFAULT '',       -- KRX (시장 전체) · 종목 일정은 빈칸
    symbol      TEXT    NOT NULL DEFAULT '',       -- 종목 단축코드(시장 전체 일정은 빈칸)
    title       TEXT    NOT NULL,
    detail      TEXT    NOT NULL DEFAULT '',
    confidence  TEXT    NOT NULL,                  -- confirmed 확정 · scheduled 예정 · computed 규칙으로 계산
    source      TEXT    NOT NULL,                  -- kasi · krx_rule · dividend(DART 공시)
    source_ref  TEXT    NOT NULL DEFAULT '',       -- 공시 접수번호 등
    updated_at  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_event_date ON market_event(event_date, kind);
CREATE INDEX IF NOT EXISTS ix_event_symbol ON market_event(symbol, event_date);

-- ── 14. 공시 목록 (받은 것) ────────────────────────────────────────────────
-- 전자공시(DART) list.json 한 줄 = 한 행. 상장사(유가 · 코스닥 · 코넥스)만 · 유형(A~J)별로 받아 유형을 안다
-- (응답에는 유형 칸이 없다 — 2026-10-04 실측). 만드는 쪽: collector/disclosure.py
-- ⚠️ 같은 접수번호를 다시 받으면 fetched_at(처음 받은 시각)은 그대로 두고 updated_at · rm 만 고친다.
CREATE TABLE IF NOT EXISTS disclosure (
    rcept_no    TEXT    NOT NULL PRIMARY KEY,  -- 접수번호 14자리 — 앞 8자리가 접수일
    rcept_dt    TEXT    NOT NULL,              -- YYYYMMDD (응답 그대로)
    corp_code   TEXT    NOT NULL,              -- DART 고유번호 8자리
    corp_name   TEXT    NOT NULL DEFAULT '',
    stock_code  TEXT    NOT NULL DEFAULT '',   -- 종목 단축코드 6자리
    corp_cls    TEXT    NOT NULL DEFAULT '',   -- Y 유가 · K 코스닥 · N 코넥스
    pblntf_ty   TEXT    NOT NULL DEFAULT '',   -- A 정기 · B 주요사항 · C 발행 · D 지분 · E 기타 · F 외부감사 · G 펀드 · H 자산유동화 · I 거래소 · J 공정위
    report_nm   TEXT    NOT NULL,              -- 보고서 이름(공백만 하나로 접음 · 머리 [기재정정] · 꼬리 설명 포함)
    title       TEXT    NOT NULL DEFAULT '',   -- 머리 [..] · 꼬리 설명을 뗀 이름 — 유형 판정 · 일정 · 재무 잇기에 쓴다
    revision    TEXT    NOT NULL DEFAULT '',   -- 머리 [..] 안 글 — 기재정정 · 첨부정정 · 첨부추가 · 변경등록 …
    period      TEXT    NOT NULL DEFAULT '',   -- 정기보고서 기간 YYYY.MM — 「사업보고서 (2025.12)」 → 2025.12
    flr_nm      TEXT    NOT NULL DEFAULT '',   -- 공시 제출인
    rm          TEXT    NOT NULL DEFAULT '',   -- 비고(유 · 코 · 넥 · 채 · 연 · 정 · 철 …) — 마지막으로 받은 날 기준
    fetched_at  TEXT    NOT NULL,              -- 처음 받은 시각 KST
    updated_at  TEXT    NOT NULL,              -- 마지막으로 다시 받은 시각 KST
    raw_sha256  TEXT    NOT NULL DEFAULT ''    -- 이 행이 나온 목록 응답 원문
);
CREATE INDEX IF NOT EXISTS ix_disc_date ON disclosure(rcept_dt);
CREATE INDEX IF NOT EXISTS ix_disc_stock ON disclosure(stock_code, rcept_dt);
CREATE INDEX IF NOT EXISTS ix_disc_period ON disclosure(corp_code, period);

-- ── 15. 재무제표 (받은 것) ─────────────────────────────────────────────────
-- DART 다중회사 주요계정(fnlttMultiAcnt · 한 번에 100개사) 한 줄 = 한 행. 만드는 쪽: collector/financials.py
-- ⚠️ DART 재무 API 는 **가장 최근 정정본의 값과 접수번호만** 준다(2026-10-04 실측 — GS건설 2023 사업보고서는
--    2024-03-21 첫 제출 · 정정 셋 · 지금 부르면 2026-06-30 정정본). 그래서 접수번호를 기본 키에 넣어 정정본마다
--    새 행으로 쌓고(앞으로 매일 받는 정정은 그날의 판이 남는다), 미래 참조를 막는 날짜를 둘 둔다:
--      known_at       = 이 값이 실린 보고서의 접수일(접수번호 앞 8자리) — 이 값 그대로를 알 수 있었던 첫날
--      first_known_at = 그 기간 보고서가 처음 나온 날(정정 전 원본 · disclosure 에서 잇는다) — 그 기간 숫자가 처음 나온 날
CREATE TABLE IF NOT EXISTS financial_statement (
    corp_code       TEXT    NOT NULL,
    bsns_year       TEXT    NOT NULL,          -- 사업연도 YYYY
    reprt_code      TEXT    NOT NULL,          -- 11013 1분기 · 11012 반기 · 11014 3분기 · 11011 사업
    fs_div          TEXT    NOT NULL,          -- CFS 연결 · OFS 별도
    sj_div          TEXT    NOT NULL,          -- BS 재무상태표 · IS 손익계산서
    ord             INTEGER NOT NULL,          -- 계정 정렬 순서(응답 그대로)
    account_nm      TEXT    NOT NULL,          -- 계정 이름(응답 그대로 — 예 당기순이익(손실))
    rcept_no        TEXT    NOT NULL,          -- 이 값이 실린 보고서 접수번호(정정이 있으면 정정본)
    scope           TEXT    NOT NULL DEFAULT 'major',  -- major = 주요계정
    stock_code      TEXT    NOT NULL DEFAULT '',
    period_end      TEXT    NOT NULL DEFAULT '',       -- 당기 끝날 YYYY-MM-DD(thstrm_dt 에서)
    thstrm_amount     INTEGER,                 -- 당기(분 · 반기 손익계산서는 3개월)
    thstrm_add_amount INTEGER,                 -- 당기 누적
    frmtrm_amount     INTEGER,                 -- 전기
    frmtrm_add_amount INTEGER,                 -- 전기 누적
    bfefrmtrm_amount  INTEGER,                 -- 전전기(사업보고서만)
    currency        TEXT    NOT NULL DEFAULT 'KRW',
    known_at        TEXT    NOT NULL,          -- YYYYMMDD — 접수번호 앞 8자리
    first_known_at  TEXT    NOT NULL DEFAULT '',  -- YYYYMMDD — 그 기간 원본 보고서 접수일(모르면 빈칸)
    fetched_at      TEXT    NOT NULL,          -- 받은 시각 KST
    raw_sha256      TEXT    NOT NULL DEFAULT '',
    PRIMARY KEY (corp_code, bsns_year, reprt_code, fs_div, sj_div, ord, account_nm, rcept_no)
);
CREATE INDEX IF NOT EXISTS ix_fin_stock ON financial_statement(stock_code, bsns_year, reprt_code);
CREATE INDEX IF NOT EXISTS ix_fin_rcept ON financial_statement(rcept_no);
"""

#: 16. 금통위 · FOMC 공식 일정(받은 것) — 한국은행 · 연준 누리집에서 받는다. 만드는 쪽: collector/event_sources.py
#: 거래일 달력의 일정(market_event · 계산한 것)이 이 표를 읽어 다시 만든다.
POLICY_MEETING_DDL = """
CREATE TABLE IF NOT EXISTS policy_meeting (
    org          TEXT NOT NULL,              -- bok(한국은행 금통위) | fomc(미국 연준)
    meeting_date TEXT NOT NULL,              -- YYYY-MM-DD — 금통위는 KST 회의일 · FOMC 는 둘째 날(미국 동부)
    title        TEXT NOT NULL,
    detail       TEXT NOT NULL DEFAULT '',
    source_url   TEXT NOT NULL,
    fetched_at   TEXT NOT NULL,              -- 받은 시각 KST
    PRIMARY KEY (org, meeting_date)
);
"""
SCHEMA += POLICY_MEETING_DDL

#: 17. 주주총회 · 배당금 지급 일정(계산한 것) — 공시 본문 원문(raw_response 의 dart agm/ · dividend/)에서 날짜를 읽는다.
#: 만드는 쪽: collector/corp_schedule.py · 지워도 `python -m collector.corp_schedule build` 가 원문에서 되살린다.
#: 거래일 달력의 일정(market_event · agm · dividend_pay)이 이 표를 읽어 다시 만든다.
CORP_SCHEDULE_DDL = """
CREATE TABLE IF NOT EXISTS corp_schedule (
    rcept_no    TEXT NOT NULL,              -- 근거 공시 접수번호(주주총회소집결의 · 현금ㆍ현물배당결정)
    kind        TEXT NOT NULL,              -- agm 주주총회 · dividend_pay 배당금 지급
    stock_code  TEXT NOT NULL DEFAULT '',
    corp_name   TEXT NOT NULL DEFAULT '',
    event_date  TEXT NOT NULL DEFAULT '',   -- YYYY-MM-DD — 본문에서 못 읽으면 빈칸(추측하지 않는다)
    event_time  TEXT NOT NULL DEFAULT '',   -- HH:MM — 모르면 빈칸
    label       TEXT NOT NULL DEFAULT '',   -- 정기주주총회 · 임시주주총회 · 결산배당 · 중간배당 · 분기배당
    detail      TEXT NOT NULL DEFAULT '',   -- 장소 · 안건 앞 몇 개 · 1주당 배당금 · 날짜 칸의 원문 글
    orig_filed  TEXT NOT NULL DEFAULT '',   -- 정정 공시면 「정정관련 공시서류제출일」(YYYY-MM-DD) — 원 공시를 찾는 열쇠
    raw_sha256  TEXT NOT NULL DEFAULT '',   -- 읽은 본문 원문의 sha256
    parsed_at   TEXT NOT NULL,              -- 읽은 시각 KST
    PRIMARY KEY (rcept_no, kind)
);
CREATE INDEX IF NOT EXISTS ix_csched_stock ON corp_schedule(stock_code, event_date);
"""
SCHEMA += CORP_SCHEDULE_DDL

#: 18. 뉴스(받은 것) — 기사 한 건 = 한 행. 출처 둘:
#:    policy_news  정책브리핑 정책뉴스(공공데이터포털 15095335) — collector/policy_news.py · 원문 XML 은 raw_response 의 policy_news
#:    gdelt        언론사 기사 메타데이터(GDELT 번역 GKG 15분 원자료의 한국어 원문 기사) — collector/gdelt_news.py · 원문 zip 은 두지 않는다
#: ⚠️ 본문(body)은 정책뉴스 가운데 공공누리 제1유형(출처 표시) 기사만 둔다 — 기사마다 kogl_type 칸이 따로 온다. 언론사 기사는
#:    제목 · 원문 주소 · 시각 · 언론사만(본문 · 요약 없음 · 근거 답에 넣지 않는다). 같은 기사를 다시 받으면 fetched_at(처음 받은
#:    시각)은 그대로 두고, 고친 판(revision)이 오면 내용과 updated_at 만 고친다.
NEWS_ITEM_DDL = """
CREATE TABLE IF NOT EXISTS news_item (
    news_id      TEXT    NOT NULL PRIMARY KEY,  -- 출처:번호 — policy:148972963(정책브리핑 기사 ID) · gdelt:<주소 sha256 앞 16자>
    source       TEXT    NOT NULL,              -- policy_news(정책브리핑) · gdelt(언론사 기사 메타데이터)
    title        TEXT    NOT NULL,
    subtitle     TEXT    NOT NULL DEFAULT '',   -- 부제목 1 ~ 3(줄바꿈으로 잇는다)
    body         TEXT    NOT NULL DEFAULT '',   -- 태그를 뺀 본문 글 — 공공누리 제1유형만(아니면 빈칸)
    url          TEXT    NOT NULL DEFAULT '',   -- 원문 주소(정책뉴스 www.korea.kr · 언론사 기사 주소)
    publisher    TEXT    NOT NULL DEFAULT '',   -- 정책뉴스 부처 · 기관(MinisterCode — 빈칸인 기사가 있다) · 언론사 도메인
    category     TEXT    NOT NULL DEFAULT '',   -- 콘텐츠 성격(GroupingCode — policy 정책 · fact 사실 확인 · brief 보도자료)
    kogl_type    TEXT    NOT NULL DEFAULT '',   -- 공공누리 유형 1 ~ 4(빈칸 = 모름 → 본문을 두지 않는다)
    pub_at       TEXT    NOT NULL,              -- 처음 승인된 시각 KST ISO(ApproveDate)
    embargo_at   TEXT    NOT NULL DEFAULT '',   -- 엠바고가 풀린 시각 KST ISO(EmbargoDate · 있을 때만)
    available_at TEXT    NOT NULL,              -- 볼 수 있게 된 시각 = 승인 · 엠바고 가운데 늦은 것 — 미래 참조 방지의 기준
    modified_at  TEXT    NOT NULL DEFAULT '',   -- 마지막으로 고친 시각 KST ISO(ModifyDate)
    revision     INTEGER NOT NULL DEFAULT 1,    -- 고친 횟수(ModifyId · 처음 등록 1)
    fetched_at   TEXT    NOT NULL,              -- 처음 받은 시각 KST(다시 받아도 그대로)
    updated_at   TEXT    NOT NULL,              -- 내용이 바뀐 판을 마지막으로 받은 시각 KST — 검색 색인이 이 칸으로 따라간다
    raw_sha256   TEXT    NOT NULL DEFAULT ''    -- 이 판이 나온 응답 원문
);
CREATE INDEX IF NOT EXISTS ix_news_pub ON news_item(pub_at);
CREATE INDEX IF NOT EXISTS ix_news_updated ON news_item(updated_at);
"""
SCHEMA += NEWS_ITEM_DDL


def connect(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """연결을 열고 표를 보장한다.

    ``isolation_level=None`` 은 파이썬이 몰래 트랜잭션을 여는 것을 끄는 설정이다.
    트랜잭션 경계를 호출하는 쪽이 `BEGIN IMMEDIATE` 로 직접 잡는다 — 원문·정규화·
    상태가 **함께** 커밋돼야 하기 때문이다. 하나만 남으면 재개 로직이 거짓말을 한다.
    """
    config.ensure_dirs()
    conn = sqlite3.connect(db_path or config.DB_PATH, timeout=60, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=60000")
    # WAL: 수집이 도는 중에도 다른 프로세스가 읽을 수 있다. 대시보드가 이 경로를 탄다.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(SCHEMA)
    return conn
