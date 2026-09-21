"""벤치마크 지수 — 시장 전체를 하나의 수로 접는다.

이 파일이 답하는 질문은 하나다: **"그래서 시장은 얼마나 올랐나."**

왜 필요한가 (비전문가용 한 문단)
--------------------------------
전략이 연 12% 를 벌었다는 말은 그 자체로는 아무 뜻이 없다. 같은 기간 시장이 15%
올랐다면 그 전략은 **진 것**이고, 시장이 3% 빠졌다면 크게 이긴 것이다. 그래서 성과를
말하려면 "시장" 에 해당하는 수가 반드시 있어야 하는데, 우리에게는 그게 없었다 —
KRX 가 내는 공식 코스피 지수는 이 프로젝트가 **약관 때문에 배제한 소스**로만 받을 수
있기 때문이다. 그래서 이미 갖고 있는 시세로 **직접 만든다.**

⚠️ **이것은 공식 KRX 지수가 아니다.** 우리 DB 로 재현한 자체 계열이다. 화면·보고서에
그냥 "KOSPI" 라고 적으면 안 된다 — 항상 "자체 재현치" 를 병기한다. 절대 레벨은
20200102 = 1000.0 으로 **우리가 임의로 정한 값**이다(1980년 기준시가총액과 45년치
제수 이력을 모른다).

⚠️ **재현 정확도는 시장마다 다르다.** 공식 연말 종가 대조 실측(2026-09-20)::

    KOSPI   연 |오차| 0.000~0.166%  평균 0.066%  · 6.7년 누적 +0.141%   → 벤치마크로 쓸 만하다
    KOSDAQ  연 |오차| 0.004~1.896%  평균 0.871%  · 6.7년 누적 +1.896%   → **미해결 결함이 있다**

코스닥을 코스피와 같은 신뢰도로 쓰면 안 된다. 자세한 내용과 기각된 원인 가설은
``OFFICIAL`` 상수의 주석에 있다.

용어 두 층
----------
**시가총액가중(market-cap weighted)**
  뜻 — 큰 회사일수록 지수에 크게 반영한다. 삼성전자 1% 와 소형주 1% 는 같지 않다.
  이 문서에서 — 가중치 ``w = 전일 종가 시가총액(price_daily.mrkt_tot_amt)``.
  헷갈리는 점 — **오늘 시총이 아니라 어제 시총**이다. 오늘 시총을 쓰면 그날 새로
  발행된 주식(유상증자·합병신주)이 수익률처럼 보여 지수가 가짜로 오른다(§라스파이레스).

**연쇄곱(chain-linking)**
  뜻 — 하루치 수익률을 차례로 곱해 누적 레벨을 만드는 방식.
  이 문서에서 — ``I_k = I_{k-1} × R_k``, ``I_0 = 1000.0``.
  헷갈리는 점 — 구성종목이 날마다 바뀌어도 **하루 안에서는 고정**이므로, 편입·이탈이
  수익률에 섞이지 않는다. 이것이 지수 산출의 핵심 장치다.

**라스파이레스(Laspeyres) 성질**
  뜻 — 분자와 분모를 **같은(전기) 수량**으로 평가한다는 것.
  이 문서에서 — ``w·ρ = [p_{k-1}·q_{k-1}] × p_k/base_k`` 이고 분모도 같은
  ``p_{k-1}·q_{k-1}`` 이라, 당일 주식수 ``q_k`` 가 식에 아예 등장하지 않는다.
  헷갈리는 점 — 그래서 ``lstg_st_cnt``(상장주식수)가 **가중치에도 수익률에도 없다.**
  주식수가 전일과 다른 종목-일 **20,230건**(보통주·ρ 계산 가능한 쌍 기준, 실측
  2026-09-20)이 자동으로 수익률에서 빠진다.
  ⚠️ 단 **한 군데 예외**가 있다 — 조정계수가 놓친 감자를 되찾을 때만 읽는다.
  가격을 고치는 데 쓰는 게 아니라 *가격이 거짓인지 판정*하는 데만 쓴다
  (§주식수 사건 보정). 이 예외가 없으면 코스닥에 가짜 +3.06%p 가 영구히 박힌다.

**PR · TR · TRN · EW**
  뜻 — 가격만 / 배당까지(세전) / 배당까지(세후 15.4%) / 동일가중.
  이 문서에서 — ``variant`` 칸. 네 계열 모두 같은 날 같은 값(1000.0)에서 출발한다.
  헷갈리는 점 — ``price_total_return.tr_index`` 는 **종목마다** 첫 거래일이 1.0 이다.
  종목끼리 시작점이 달라 그대로 평균 내면 안 된다. 아래 ⛔ 항목 참고.

계산 규칙 — 왜 이 식인가
------------------------
::

            Σ_{i∈U_k}  w_{i,k} · ρ_{i,k}
    R_k  =  ────────────────────────────      (그날의 시장 수익비, 1+r 형태)
            Σ_{i∈U_k}  w_{i,k}

    I_k  =  I_{k-1} × R_k          I_0 = 1000.0 (20200102)
    ret_k = R_k − 1                (기준일 행은 ret = NULL)

``w_{i,k}`` = 전일 종가 시가총액, ``ρ_{i,k}`` = 그 종목의 그날 가격비(계열마다 다름).

⛔ **절대 하지 않는 것 — 이 모듈에서 가장 틀리기 쉬운 두 지점**

1. ``tr_index`` 를 날짜별로 그냥 평균·가중평균하지 않는다. 종목마다 시작점(1.0)이
   달라 뒤섞인다. 반드시 **인접 두 날의 비율**로 환산한 뒤 가중한다.
2. ``Σ mrkt_tot_amt(d_k) / Σ mrkt_tot_amt(d_{k-1})`` 을 쓰지 않는다(나이브 방식).
   상장·폐지·증자가 전부 수익률로 샌다.

   **측정 정의를 못박는다** — 이 말이 숫자로 무엇인지 애매하면 재현이 안 된다::

       나이브 R_k = Σ_{그날 있는 보통주} cap(i, d_k)
                  ÷ Σ_{전일 있는 보통주} cap(i, d_{k-1})      ← 두 집합이 다르다
       정본  R_k = §계산규칙의 라스파이레스 식             ← 두 집합이 같다

   차이는 **분자의 종목 집합**뿐이다. 나이브는 그날 새로 생긴 시총을 수익으로 읽는다.
   같은 기간(20200102~20260917) 두 방식을 각각 연쇄곱한 실측 (2026-09-20 재측정)::

       KOSPI   정본 +209.07%   나이브 +280.54%   → 나이브가 **23.12% 높게** 끝난다
       KOSDAQ  정본  +22.58%   나이브  +89.81%   → 나이브가 **54.85% 높게** 끝난다

   하루로 보면 2022-01-27 LG에너지솔루션 상장일이 가장 크다 — 그날 정본은
   **−3.49%** 인데 나이브는 **+2.62%** 라 **+6.11%p** 가 가짜로 붙는다. 이 값은
   우연이 아니라 정의상 같다: LG엔솔 상장일 시총 118.2조 ÷ 전일 KOSPI 보통주
   시총합 1,932.7조 = **6.11%**. 새 시총이 통째로 수익률이 된 것이다.

구성종목 ``U_k`` — 한 줄로 끝난다
---------------------------------
::

    i ∈ U_k(m)  ⟺  (1) substr(i,6,1) = '0'                  보통주만
                AND (2) d_{k-1} 과 d_k 에 **모두** 시세가 있다
                AND (3) 두 날 모두 mrkt_ctg = m             (시장이전 차단)
                AND (4) mrkt_tot_amt(i, d_{k-1}) > 0
                AND (5) ρ 의 분자·분모가 모두 NOT NULL AND > 0

- **스팩·리츠·인프라펀드는 넣는다.** 빼 보니 공식 코스피와의 평균오차가
  0.066% → 0.230% 로 3.5배 악화했다. KRX 본지수가 이들을 포함한다는 뜻이다.
  덕분에 ``itms_nm`` 기반 필터가 **전부 사라졌고**, 617종목 개명 함정도 함께 소멸했다.
- **우선주는 뺀다.** 근거 둘 — ① 본지수 정의가 "상장 보통주" 이고 실측으로 평균오차가
  0.270% → 0.066% 로 4배 개선된다 ② 우선주 129종목은 TR 에 배당이 **한 푼도** 안
  들어가 있어(``div_factor≠1`` 인 우선주 0종목) 포함하면 TR 이 체계적으로 과소계상된다.
- **판별은 종목코드 6번째 자리만.** ``itms_nm LIKE '%우'`` 는 에코글로우·이오플로우 등
  보통주를 오탐하고 ``00104K CJ4우(전환)`` 를 놓친다. ISIN 접두사는 보통주·우선주가
  전부 ``KR7`` 이라 쓸 수 없다.
- **신규상장은 둘째 거래일부터.** 조건 (2)가 자동 처리한다. 상장 첫날 827건 중
  ``vs≠0`` 이 95.4% 라 첫날 수익률은 계산 자체가 성립하지 않는다.
- **상장폐지는 마지막 거래일까지 포함하고 −100% 로 치지 않는다.** 폐지 432종목의
  상위는 셀트리온헬스케어·HD현대미포(합병), 쌍용C&E·오스템임플란트(자진상폐)처럼
  **주주가 대가를 받고 나간** 경우다. −100% 처리는 생존편향을 고치려다 더 크게 틀린다.
- **거래정지(halted=1)를 빼지 않는다.** ``halted=1`` 은 ``trqu=0`` 과 정확히 동치이고
  ``clpr`` 은 전일 종가를 이월하므로 95.9% 가 자동으로 수익률 0 이다. 빼면 날마다
  100~250종목이 들락거려 지수가 요동친다(제외 시 누적 −0.12% 편차).

주식수 사건 보정 — 조정계수가 놓친 감자를 되찾는다
--------------------------------------------------
``adj_clpr`` 을 믿는 것이 이 모듈의 기본 전제인데, **그 전제가 깨지는 구멍이 하나
있다.** 구멍은 우리가 만든 게 아니라 ``preprocess`` 가 자기 문서에 이미 적어 둔
것이다(``classify`` 주석의 "아이엠텍 사각지대").

무슨 일이 일어나는가 — 실제 사례 하나로 끝난다::

    제일바이오 052670
      20260120~20260206  거래정지 13일.  clpr 2,080 고정 · vs = 0 · halted = 1
      20260209           거래재개.       clpr 625,000 · vs 622,920 · flt_rt +29,948%
                         상장주식수 29,129,064 → 19,419  (1,500 : 1 감자)

``preprocess`` 의 조정계수는 ``f = (clpr − vs) ÷ 전일종가`` 다. 그런데 KRX 가 준
``vs`` 는 **감자 전 종가(2,080)를 기준으로 한 값**이라 ``clpr − vs = 2,079 ≈ 2,080``
이 되어 ``f = 1.0`` — "가격이 이어진다" 로 읽힌다. 그래서 ``cum_factor`` 는 1.0 그대로고
``corporate_action`` 에도 그날 행이 **없다.** 정지 구간 내내 ``vs = 0`` 이라 가격이
이어지는 것과 조정 정보가 없는 것을 구별할 수 없었던 것이다.

결과는 조용하지 않다. 지수가 **ρ = 300.48 (+29,948%)** 를 그대로 먹는다::

    가짜 분자  606억 × 300.48 = 18.21조      실제 분모 592.9조
    그날 코스닥 지수에 **+3.060%p** · 연쇄곱이라 되돌림이 없다 (영구 각인)

**진짜 수익률은 −79.97% 다.** 1,500주(2,080원)를 들고 있던 사람이 1주(625,000원)를
갖게 됐으니 3,120,000원 → 625,000원이다. 시총도 606억 → 121억으로 같은 말을 한다.

어떻게 가려내는가 — 네 가지를 **전부** 만족할 때만 보정한다
```````````````````````````````````````````````````````````
``ρ`` = 가격비, ``c`` = 주식수비(``q_k / q_{k-1}``) 라 하자. 무상 성격의 주식수 변동
(감자·액면분할·병합)은 **회사 가치를 바꾸지 않으므로** 가격이 주식수의 역수로 움직인다.
그래서 ``ρ·c`` 가 진짜 수익비가 된다 — 이것이 곧 **시총비**다.

::

    ① cum_factor 가 그날 움직이지 않았다   preprocess 가 조정을 한 건도 안 걸었다
    ② 그런데 주식수는 움직였다             c ≠ 1
    ③ 가격비가 가격제한폭의 두 배 밖이다    |ρ−1| > 0.60  (제도상 하루 ±30%)
    ④ c 를 곱하면 1 에 훨씬 가까워진다      로그거리가 2배 이상 줄고,
                                           남은 잔차가 주식수 신호보다 작다

④ 를 로그 없이 쓴다(``ln()`` 이 없는 SQLite 빌드가 있다 — 실측 3.53.2 에 없다).
``v = max(ρc, 1/ρc)``, ``w = max(ρ, 1/ρ)``, ``s = max(c, 1/c)`` 로 두면
``v·v ≤ w  AND  v < s`` 가 정확히 같은 말이다.

**왜 이렇게 까다로운가 — 셋 다 없으면 멀쩡한 날을 부순다.** 실측으로 확인한 함정::

    ② 없으면  주식수가 안 변한 진짜 폭락을 건드린다
              카프로 −94.9% · 에코바이브 −97.7% 는 c = 1.000000 인 **실제** 등락이다
    ③ 없으면  상한가·하한가 날을 부순다. |ρ−1| = 0.30 인 종목-일이 104건 있고
              (에코마이스터 하한가 + 유상증자 신주상장) ρ·c 를 쓰면 −29.2% 가
              **+7.6%** 로 뒤집힌다
    ①④ 없으면 유상증자 신주상장 **1,881건**을 전부 부순다. 바른전자 20200113 은
              ρ = 1.000 인데 c = 38.59 라 ρ·c 를 쓰면 하루 **+3,759%** 가 된다
              (신주는 현금을 받고 찍은 것이라 시총 증가가 수익이 아니다)

**전 구간·전 시장 실측 결과 걸리는 것은 제일바이오 20260209 단 1건이다.**
여유도 충분하다 — 그 건은 ``v·v = 24.9 ≤ w = 300.5`` 로 12배 여유이고, 가장 가까운
탈락자인 코스온 20231011(실제 −88%)은 ``v·v = 75.9 > w = 8.2`` 로 9배 모자란다.
**KOSPI 는 후보가 0건이라 이 보정으로 한 값도 바뀌지 않는다.**

⚠️ **남는 사각지대 — 정직하게 적는다.** ③ 이 0.60 이라 *흡수되지 않은 2:1 액면분할*
(ρ = 0.5)은 못 잡는다. 실측으로 그런 건은 현재 0건이고, 정지 없이 거래되는 종목은
``vs`` 로 ``preprocess`` 가 잡아내므로 구멍은 "장기 거래정지 + 감자" 조합에서만 열린다.

새로 생기면 무엇이 잡는가 — **게이트 2 는 못 잡는다.** 이것이 이번에 배운 것이다:
제일바이오는 2026-02-09 인데 공식 연말 종가의 마지막 점은 2025-12-30 이라, 보정
전후로 연말 대조표가 **한 자리도 바뀌지 않았다.** 바깥 기준점은 언제나 과거에만 있다.
그래서 기준점 없이 판정하는 **게이트 6(하루 20배 넘게 오른 종목이 있는가)**을 뒀다.
감자 미흡수는 반드시 *위로* 튀므로 그 방향만 막으면 된다 — 아래로 튀는 것은 정리매매의
진짜 −99% 와 구별할 수 없고, 구별하려 들면 진짜 손실을 지우게 된다.

무엇을 하지 않는가
------------------
- **±60% 클리핑을 하지 않는다.** 위 §주식수 사건 보정을 거친 뒤 남는 것은 전부
  감자·정리매매·거래재개의 **실제** 등락이라, 지우면 진짜 손실이 조용히 사라져
  **벤치마크가 실제보다 좋아 보인다** — 가장 피해야 할 방향이다. 세기만 한다.

  ⚠️ **"최대 영향 −0.011%p" 는 KOSPI 전용 수치였다.** 시장마다 자릿수가 다르다
  (2026-09-20 전 시장 실측 · 보정 **전**)::

      KOSPI    20건   |영향| 합 0.071%p   최대 −0.022%p  (에코바이브 20231027)
      KOSDAQ  138건   |영향| 합 4.886%p   최대 +3.060%p  ← 이것이 제일바이오 버그였다
      KONEX    75건   |영향| 합 6.735%p   최대 −0.927%p  (디피코 20240607)

  코스닥의 +3.060%p 를 빼고 나면 최대는 −0.250%p(코다코 20260910)로, 여전히 KOSPI 의
  11배다. **"클리핑이 필요 없다" 는 결론은 KOSPI 에서만 값싸게 참이다.**
- **corporate_action 을 조회하지 않는다.** ``adj_clpr`` 이 이미 그 정보를 품고 있어
  조인이 낭비다. ⚠️ 그리고 **조인했어도 제일바이오는 못 잡았다** — 그 표에 그날 행이
  애초에 없다(052670 의 전체 CA 는 20210401 권리락 1건뿐). 못 만든 표를 조회해 봐야
  없는 것이 없는 채로 나온다. 그래서 보정의 근거를 ``lstg_st_cnt`` 에서 찾은 것이다.
- **전체시장 합성 계열(ALL)을 만들지 않는다.** 시장이전 47종목 때문에 규칙이 달라져
  혼동을 낳는다. KOSPI+KOSDAQ 단순 합산은 실측 −7.97% 편차라 절대 금지.
- **KOSPI 200·KOSDAQ 150 을 재현하지 않는다.** 유동주식비율이 DB 에 없어 구조적으로
  불가능하다. 대형주 계열이 필요하면 "시총 상위 N" 으로 만들되 그 이름을 빌리지 않는다.
- **세율 개념이 이 모듈에 없다.** 세후 계열은 ``price_total_return.tr_index_net`` 을
  그대로 읽는다. 세율을 바꾸려면 ``total_return build --tax`` 를 다시 돌려야 한다.
"""

from __future__ import annotations

import argparse
import sqlite3
import unicodedata
from typing import Dict, List, Optional, Sequence, Tuple

from collector import db

# ──────────────────────────────────────────────────────────────────────────────
# 표 — collector/db.py 의 SCHEMA 와 같은 결로 쓰되, 이 모듈이 스스로 보장한다.
# (db.py 는 다른 작업과 겹쳐 손대지 않는다. 옮길 때 이 블록을 통째로 8번으로 넣되,
#  **바로 아래 `_ADDED_COLUMNS`·`_ensure_schema` 도 같이 가져간다** — 옛 표에 칸을
#  더하는 일은 CREATE TABLE IF NOT EXISTS 가 해 주지 않는다.)
# ──────────────────────────────────────────────────────────────────────────────
SCHEMA = """
-- ── 8. 벤치마크 지수 (파생) ─────────────────────────────────────────────────
-- price_daily(시총) + price_adjusted(가격) + price_total_return(배당) = 시장의 성적.
--
-- ★ 앞선 세 표와 **축이 다르다.** 저 셋은 (날짜, 종목) 한 줄이지만 이 표는
--   (날짜, 시장, 계열) 한 줄 — 하루의 전 종목을 가로질러 접은 결과다.
--   그래서 PK 에 srtn_cd 가 없다.
-- ★ 기준일이 total_return 과 다르다. TR 은 **종목마다** 첫 거래일 1.0 이지만(종목끼리
--   비교할 일이 없으므로), 지수는 시장 단위라 **모든 계열이 같은 날 같은 값**에서
--   출발해야 계열끼리 겹쳐 그릴 수 있다 → 20200102 = 1000.0 으로 고정한다.
-- ⚠️ 이것은 KRX 공식 지수가 아니다. 공식 연말 종가와 코스피는 평균 0.066%,
--    **코스닥은 평균 0.871%** 차이난다 (머리말의 재현 정확도 표 참고).
CREATE TABLE IF NOT EXISTS benchmark_index (
    bas_dt     TEXT    NOT NULL,           -- 기준일 (YYYYMMDD · TEXT)
    mrkt_ctg   TEXT    NOT NULL,           -- 'KOSPI' · 'KOSDAQ' · 'KONEX'
    variant    TEXT    NOT NULL,           -- 'PR' · 'TR' · 'TRN' · 'EW'
    -- 그날의 시장 수익률. 기준일(첫날) 행은 비교 대상이 없어 NULL 이다.
    -- level 과 둘 다 저장하는 이유: 수익률을 곱하면 레벨이 되지만 반대로 레벨에서
    -- 수익률을 빼면 첫 행이 NaN 이 되고, 쓰는 쪽이 매번 pct_change 를 하다가 단위를
    -- 틀린다(누적 % 와 일별 비율을 섞는 사고). 계약을 표에서 못박는다.
    ret        REAL,
    level      REAL    NOT NULL,           -- 지수 레벨. 기준일 = 1000.0
    -- 그날 수익률 계산에 **실제로 쓰인** 종목 수 (= |U_k|). 시장 전체 종목 수가 아니다.
    n_const    INTEGER NOT NULL,
    mcap_total REAL    NOT NULL,           -- 분모 Σ(전일 시총). 원 단위
    -- 사후 감사용. '어느 날 몇 종목이 들고 났는가' 를 나중에 되물을 수 없으면
    -- 지수가 튄 날의 원인을 영원히 못 찾는다.
    -- ⚠️ 기준일 행과 **첫 계산일 행은 둘 다 0 이다** — 그 두 날에는 '어제의 U' 가
    --    정의되지 않기 때문이다. 항등식은 첫 계산일 **다음날부터** 성립한다.
    n_entered  INTEGER NOT NULL DEFAULT 0, -- 전일엔 없다가 그날 편입된 종목 수
    n_exited   INTEGER NOT NULL DEFAULT 0, -- 전일엔 있었으나 그날 빠진 종목 수
    -- |일별 수익률| > 60% 인 종목 수. **값은 그대로 반영하고 세기만 한다** —
    -- 클리핑하면 감자·정리매매의 진짜 손실을 지워 지수가 실제보다 좋아 보인다.
    n_outlier  INTEGER NOT NULL DEFAULT 0,
    -- §주식수 사건 보정이 그날 고친 종목 수. 0 이 정상이고 0 이 아닌 날은
    -- **반드시 사람이 한 번 봐야 한다** — 조정계수가 놓친 감자가 있었다는 뜻이다.
    n_fixed    INTEGER NOT NULL DEFAULT 0,
    -- ★ 이 행이 **어느 기준으로 만들어졌는가.** 없으면 부분 빌드가 섞여도 모른다:
    --   `build --base 20220103` 을 KOSDAQ 에만 돌리면 KOSPI 는 20200102 기준,
    --   KOSDAQ 은 20220103 기준인 행이 한 표에 남는데, 칸이 없으면 레벨만 보고는
    --   **구별할 방법이 전혀 없다**(둘 다 그냥 숫자다). 계열끼리 겹쳐 그리는 순간
    --   조용히 틀린 그림이 나온다. verify 게이트 5 가 이 두 칸으로 그걸 잡는다.
    base_dt    TEXT,                       -- 그 계열의 기준일
    base_level REAL,                       -- 그 계열의 기준일 레벨
    PRIMARY KEY (bas_dt, mrkt_ctg, variant)
);
-- 계열 하나를 시간순으로 훑는 것이 이 표의 유일한 읽기 패턴이다.
CREATE INDEX IF NOT EXISTS ix_bm_series ON benchmark_index(mrkt_ctg, variant, bas_dt);
"""

#: 나중에 붙인 칸들. ``CREATE TABLE IF NOT EXISTS`` 는 **이미 있는 표에 칸을 더하지
#: 않는다** — 옛 표가 남아 있으면 SCHEMA 를 고쳐도 조용히 무시되고 INSERT 가
#: "no column named n_fixed" 로 터진다. 그래서 칸 단위로 따로 맞춰 준다.
_ADDED_COLUMNS = (
  ("n_fixed",    "INTEGER NOT NULL DEFAULT 0"),
  ("base_dt",    "TEXT"),
  ("base_level", "REAL"),
)


def _ensure_schema(conn: sqlite3.Connection) -> None:
  """표를 만들고, 옛 표에는 빠진 칸을 더한다. 몇 번을 돌려도 같다."""
  conn.executescript(SCHEMA)
  have = {r[1] for r in conn.execute("PRAGMA table_info(benchmark_index)")}
  for name, decl in _ADDED_COLUMNS:
    if name not in have:
      conn.execute(f"ALTER TABLE benchmark_index ADD COLUMN {name} {decl}")

#: 기준일. 이 날의 레벨을 BASE_LEVEL 로 두고 앞에서 뒤로 연쇄곱한다.
#: DB 의 첫 거래일(20200102)과 같게 잡아 한 날도 버리지 않는다.
BASE_DT = "20200102"

#: 기준일 레벨. **우리가 임의로 정한 값**이다 — 공식 코스피의 절대 레벨은 1980-01-04
#: 기준시가총액과 그 후 45년치 제수(divisor) 이력을 알아야 복원되는데 둘 다 없다.
#: 공식값과 눈으로 맞추려면 `--anchor 2175.17`(20200102 공식 종가)을 준다.
BASE_LEVEL = 1000.0

#: 제도상 하루 가격제한폭. 2015-06-15 부터 ±30% 다.
#:
#: **정상 거래일은 이 폭을 넘을 수 없다.** 넘는 날은 셋 중 하나다 — 신규상장일(편입조건
#: (2)가 이미 뺀다) · 거래재개일(기준가를 새로 정한다) · 정리매매(제한폭 자체가 없다).
#: 그래서 이 값은 "이 이상이면 평범한 등락이 아니다" 의 하한선이지 **판정 기준은 아니다.**
PRICE_LIMIT = 0.30

#: 하루 |수익률| 이 이보다 크면 **세어서 보고**한다. 버리지도, 깎지도 않는다.
#: 동시에 §주식수 사건 보정의 **트리거**이기도 하다(조건 ③).
#:
#: 왜 제한폭의 **두 배**인가 — 거래재개일·정리매매는 ±30% 를 합법적으로 넘으므로
#: 0.30 을 트리거로 쓰면 **상한가·하한가 날 104건을 보정 후보로 오인한다**(실측).
#: 0.60 이면 그 104건이 전부 빠지고, 남는 진짜 후보는 제일바이오 1건뿐이다.
#:
#: 실측 2026-09-20 — 전 시장 |ρ−1| > 0.60 인 종목-일과 **그날 지수에 준 영향**.
#: 영향은 "그 한 종목을 빼고 그날 R_k 를 다시 계산했을 때의 차이"(leave-one-out)다::
#:
#:     KOSPI    20건   |영향| 합 0.071%p   최대 -0.022%p  에코바이브 015540 20231027
#:     KOSDAQ  138건   |영향| 합 4.886%p   최대 +3.060%p  제일바이오 052670 20260209
#:     KONEX    75건   |영향| 합 6.735%p   최대 -0.927%p  디피코     163430 20240607
#:
#: 코스닥의 +3.060%p 는 **등락이 아니라 버그**였다 → §주식수 사건 보정이 고친다.
#: 그것을 빼고 남는 최대는 -0.250%p(코다코 20260910)이고, 그것들은 전부 실제 등락이라
#: 클리핑하면 **진짜 손실을 조용히 지워** 벤치마크가 실제보다 좋아 보인다.
OUTLIER_TOL = 0.60

#: §주식수 사건 보정 조건 ④ 의 '개선 배수'. ``ρ·c`` 가 1 에서 떨어진 로그거리가
#: ``ρ`` 의 그것보다 이 배수 이상 작아야 "주식수가 가격 급변을 설명한다" 고 본다.
#:
#: ⚠️ 코드에서는 로그를 쓰지 않는다 — ``ln()`` 이 없는 SQLite 빌드가 있다(실측 3.53.2
#: 에 없다). ``v = max(ρc, 1/ρc)`` · ``w = max(ρ, 1/ρ)`` 로 두면 ``v**2 ≤ w`` 가
#: ``2·|ln v| ≤ |ln w|`` 와 정확히 같은 말이다. **그래서 이 값을 바꾸려면 SQL 의
#: 거듭제곱도 같이 고쳐야 한다** (지금은 ``v * v`` 로 2 가 박혀 있다).
FIX_RESCUE = 2.0

#: 게이트 6 — 하루에 이 배수를 넘게 **오른** 종목이 있으면 데이터가 깨진 것으로 본다.
#:
#: ★★ **왜 한쪽 방향만 보는가.** 가격은 0 으로 갈 수 있다 — 정리매매·상장폐지 직전의
#: −99.5%(코다코 20260910)는 실제로 일어난다. 그래서 *내려가는* 쪽에는 상한선을 그을
#: 수 없고, 그으면 진짜 파산을 지우게 된다. 반대로 **하루에 20배 오르는 주식은 없다.**
#: 그리고 감자 미흡수는 **언제나 위로 튄다**(가격 ×1500, 주식수 ÷1500) — 즉 이 게이트가
#: 막을 수 있는 방향과 실제로 사고가 난 방향이 정확히 같다.
#:
#: 값의 근거 — 보정 **후** 전 구간 최대 상승비 실측 (2026-09-20)::
#:
#:     KOSPI    2.48배  웅진에너지    20200522  (+148%)
#:     KOSDAQ   4.30배  에스에이치엔엘 20220525  (+330%)
#:     KONEX    8.00배  엠앤씨생명과학 20220420  (+700%)  ← 시총 2억짜리 초소형주
#:
#: 관측 최대(8배)의 2.5배를 상한으로 둔다. 제일바이오의 300배는 이 선의 15배라
#: **여유롭게 걸린다.** KONEX 를 빼면 5배로 낮출 수 있지만, 게이트는 전 시장 공용이다.
ABSURD_RISE = 20.0

#: 산출 계열. 이 순서로 status 가 찍는다.
VARIANTS = ("PR", "TR", "TRN", "EW")

#: 계열별 설명 — status·verify 출력과 --variants help 가 함께 쓴다.
VARIANT_DESC = {
  "PR":  "가격",
  "TR":  "세전",
  "TRN": "세후 15.4%",   # ← 세율은 total_return build --tax 가 정한다. 여기엔 없다
  "EW":  "동일가중",
}

#: 대상 시장. KONEX 는 산출하되 **벤치마크로 쓰지 않는다** — 211종목이고 거래가
#: 극히 희박해(halted 비율이 높다) 지수 변동성이 유동성 부재로 왜곡된다.
MARKETS = ("KOSPI", "KOSDAQ", "KONEX")

#: 공식 지수의 연말 종가와 앵커. **네트워크로 받지 않는다** — 공개 통계이고 연 1회만
#: 늘어난다. data.krx.co.kr 은 봇 접근에 403 이고, 우회 시도는 이 프로젝트가 소스를
#: 배제한 이유(약관)를 더 키운다.
#:
#: ★★ **코스피만 검증하면 절반만 검증한 것이다.** 실제로 코스닥에만 있던 치명 결함
#: (제일바이오 +3.060%p)을 여섯 해의 코스피 대조가 **한 번도 잡지 못했다** — 시장이
#: 다르면 게이트도 달라야 한다는 것을 그 사건이 증명했다. 그래서 코스닥을 넣는다.
#:
#: 출처 — 전 값 2026-09-20 WebSearch 로 개별 확인 🟢 (연합·이투데이·이데일리·
#: 글로벌이코노믹 등 폐장일 시황 기사. KRX 폐장 공식 발표를 그대로 옮긴 수치다)::
#:
#:     KOSDAQ 앵커 20200102 674.02   · 2020 968.42  · 2021 1033.98 · 2022  679.29
#:            2023 866.57            · 2024 678.19  · 2025  925.47
#:
#: 교차검증도 맞는다 — 2022 는 1033.98 → 679.29 로 **-34.30%**, 2025 는 678.19(2024
#: 말) → 925.47 은 연중 저점 기준 보도의 +36.5% 와 같은 해 종가 기준 +36.46% 다.
OFFICIAL = {
  "KOSPI": {
    "anchor": ("20200102", 2175.17),
    "yearend": {
      "2020": ("20201230", 2873.47),
      "2021": ("20211230", 2977.65),
      "2022": ("20221229", 2236.40),
      "2023": ("20231228", 2655.28),
      "2024": ("20241230", 2399.49),
      "2025": ("20251230", 4214.17),
    },
    # 실측 평균 0.066% 의 3배를 평균 기준으로, 최악 연도 0.569% 를 살짝 넘긴 값을
    # 연도 기준으로 둔다 — 지금 값이 기준선이고, 나빠지면 무언가 망가진 것이다.
    "year_tol": 0.60,
    "mean_tol": 0.20,
  },
  "KOSDAQ": {
    "anchor": ("20200102", 674.02),
    "yearend": {
      "2020": ("20201230", 968.42),
      "2021": ("20211230", 1033.98),
      "2022": ("20221229", 679.29),
      "2023": ("20231228", 866.57),
      "2024": ("20241230", 678.19),
      "2025": ("20251230", 925.47),
    },
    # ⚠️⚠️ **코스피보다 13배 느슨하다. 느슨해도 되어서가 아니라 아직 그만큼 못
    # 맞춰서다.** 이 두 수는 합격선이 아니라 **미해결 결함의 현재 크기**다.
    #
    # 실측 2026-09-20 (§주식수 사건 보정 **후**) — 평균 |오차| 0.871% · 최대 1.896%.
    # 연도별 재현 오차를 코스피와 나란히 놓으면 자릿수가 다르다::
    #
    #            2020     2021     2022     2023     2024     2025    누적
    #     KOSPI  +0.035  +0.003   -0.022   +0.038   +0.121   -0.044   +0.141%
    #     KOSDAQ -0.324  +0.238   +0.632   -0.092   +0.288   +0.860   +1.896%
    #
    # ★ **제일바이오 보정과는 무관하다.** 그 사건은 2026-02-09 이고 공식 상수의 마지막
    #   연말은 2025-12-30 이라, 보정 전후로 이 표의 값이 **한 자리도 바뀌지 않았다.**
    #   (그래서 게이트 2 는 그 버그를 끝내 못 잡았다 → 게이트 6 이 그 구멍을 메운다.)
    # ★ 원인 후보 하나는 실측으로 **기각**했다 — "상장폐지를 -100% 로 안 쳐서" 라면
    #   코스닥 소멸성 폐지 92종목의 마지막날 시총 2,338억이 원인이어야 하는데, 그건
    #   코스닥 전체의 0.06% 라 1.896% 를 설명하지 못한다.
    # ★ 남은 유력 후보는 **편입 범위**다. 오차가 하락장(2022 +0.632%p)과 상승장
    #   (2025 +0.860%p) 양쪽에서 같은 부호로 커지는 것이 아니라 **등락을 둘 다 크게**
    #   재현하는 모양이라, 우리 유니버스가 공식보다 소형·저유동 종목을 더 담고 있을
    #   가능성이 높다(공식 코스닥종합은 관리종목 등의 취급이 다르다). **미해결이다.**
    "year_tol": 2.00,
    "mean_tol": 1.00,
  },
}

#: 옛 이름 — 바깥에서 쓰는 곳은 없지만(2026-09-20 전수 확인) 한 줄이 싸다.
OFFICIAL_KOSPI_ANCHOR = OFFICIAL["KOSPI"]["anchor"][1]
OFFICIAL_KOSPI_YEAREND = OFFICIAL["KOSPI"]["yearend"]


# ==================================================
# 읽기 — 달력과 날짜축 단면 집계
# ==================================================
def _calendar(conn: sqlite3.Connection) -> List[str]:
  """실제 거래일 달력. **반드시 DB 에서 만든다.**

  ⛔ pandas ``bdate_range``·``BDay`` 를 쓰면 안 된다. 실측 거래일은 1,648일인데
  월~금은 1,751일이라 **103일이 어긋난다**(공휴일·임시휴장). 그 어긋남은 조용히
  '그날 전 종목이 수익률 0' 인 가짜 행을 만들어 지수를 통째로 흐린다.

  ``di``(달력 인덱스)를 쓰는 이유는 "어제" 를 정의하기 위해서다. 종목의 직전 행이
  달력상 바로 앞날인지(``prev_di == di − 1``)를 봐야 상장 공백·시장이전을 걸러낸다.
  상장구간 중간 결측이 0종목·0일이라 이 판정이 안전함은 실측으로 보장된다.
  """
  return [r[0] for r in conn.execute(
      "SELECT DISTINCT bas_dt FROM price_daily ORDER BY bas_dt")]


def _install_calendar(conn: sqlite3.Connection, cal: Sequence[str]) -> None:
  """달력을 TEMP 표로 올려 둔다. 집계 SQL 이 이걸 세 번 조인한다.

  TEMP 이므로 연결이 닫히면 사라진다 — 기존 표를 건드리지 않는다.
  """
  conn.execute("DROP TABLE IF EXISTS temp.bm_cal")
  conn.execute("CREATE TEMP TABLE bm_cal(bas_dt TEXT PRIMARY KEY, di INTEGER NOT NULL)")
  conn.executemany("INSERT INTO temp.bm_cal(bas_dt, di) VALUES (?,?)",
                   [(d, i) for i, d in enumerate(cal)])


# 날짜축 단면 집계 — 이 모듈의 유일한 새 로직.
#
# 기존 9개 모듈은 **전부 종목축**(`for code in codes`)이다. 날짜 단면을 읽어 접는
# 코드가 collector 에 한 줄도 없었다. 파이썬 루프로 446만 행을 왕복시키는 대신
# **SQL 창(window) 함수로 전일 행을 끌어와 GROUP BY bas_dt 로 접는다** — 시장당
# 한 번의 스캔으로 끝나고, 파이썬에 돌아오는 것은 거래일 수(1,648)만큼의 행뿐이다.
#
# 구조:
#   s  … 그 시장의 보통주 행 + 달력 인덱스 + 세 값(adj / tr / trn)
#   g  … 종목별로 시간순 정렬해 **1일 전(p_)과 2일 전(q_)** 을 같은 줄에 끌어온다
#          p_ 는 ρ 의 분모와 가중치 w 를 준다
#          q_ 는 "어제 이 종목이 구성종목이었나" 를 판정해 n_entered 를 센다
#   선택 … di 단면으로 접는다. 계열 4벌을 **한 번에** 누산한다(네 번 읽으면 I/O 4배)
#
# ⚠️ LAG 는 `s` 안에서만 앞을 본다. `s` 가 이미 `mrkt_ctg = ?` 로 걸러져 있으므로
#    시장이전 종목(포스코DX 등 47종목)은 이전 첫날의 p_ 가 NULL 이 되어 자동으로
#    빠진다 — 이것이 편입조건 (3) 이다. 이 조건이 없으면 20240102 에 +0.515%p 가 샌다.
# ⚠️ COALESCE 로 감싸는 이유: SQL 3값 논리에서 `NULL AND TRUE` 는 NULL 이고
#    `NOT NULL` 도 NULL 이라, q_ 가 없는(=어제 없던) 종목이 "편입 아님" 으로 새 버린다.
#
# ⚠️ CTE 가 넷인 이유 — `r`·`e` 는 §주식수 사건 보정 때문에 생겼다.
#    보정 판정식은 길어서 쓰는 자리마다 펼치면 12번 반복된다(PR·TR·TRN·EW ×
#    분자·분모·카운터). **한 번 계산해 이름을 붙이고** 그 뒤로는 `fixq` 만 곱한다.
#      r … ρ(가격비)와 c(주식수비)에 이름을 준다
#      e … 네 조건을 다 만족하면 fixq = c, 아니면 fixq = 1.0 (곱해도 아무 일 없음)
#    그래서 아래 본문은 `adj / p_adj` 가 `adj / p_adj * fixq` 로 바뀐 것 말고는
#    보정 전과 **글자 그대로 같다.** 보정이 꺼지면(fixq=1) 옛 결과가 그대로 나온다.
_AGG_SQL = """
WITH s AS (
  SELECT p.srtn_cd cd, c.di di, p.mrkt_tot_amt cap, p.halted hl,
         p.lstg_st_cnt q, a.cum_factor cf,
         a.adj_clpr adj, t.tr_index tr, t.tr_index_net trn
    FROM price_daily p
    JOIN temp.bm_cal c              ON c.bas_dt = p.bas_dt
    LEFT JOIN price_adjusted a      ON a.bas_dt = p.bas_dt AND a.srtn_cd = p.srtn_cd
    LEFT JOIN price_total_return t  ON t.bas_dt = p.bas_dt AND t.srtn_cd = p.srtn_cd
   WHERE p.mrkt_ctg = ? AND substr(p.srtn_cd, 6, 1) = '0'
), g AS (
  SELECT cd, di, cap, hl, q, cf, adj, tr, trn,
         LAG(di, 1)  OVER w p_di,  LAG(di, 2)  OVER w q_di,
         LAG(cap, 1) OVER w p_cap, LAG(cap, 2) OVER w q_cap,
         LAG(adj, 1) OVER w p_adj, LAG(adj, 2) OVER w q_adj,
         LAG(tr, 1)  OVER w p_tr,  LAG(tr, 2)  OVER w q_tr,
         LAG(trn, 1) OVER w p_trn, LAG(trn, 2) OVER w q_trn,
         LAG(q, 1)   OVER w p_q,   LAG(cf, 1)  OVER w p_cf
    FROM s
  WINDOW w AS (PARTITION BY cd ORDER BY di)
), r AS (
  SELECT g.*,
         CASE WHEN adj > 0 AND p_adj > 0 THEN adj / p_adj END   rho,
         CASE WHEN q   > 0 AND p_q   > 0 THEN q * 1.0 / p_q END qr
    FROM g
), e AS (
  SELECT r.*,
         -- §주식수 사건 보정. 네 조건을 **전부** 만족할 때만 c 를 돌려준다.
         CASE WHEN rho IS NOT NULL AND qr IS NOT NULL
                   AND cf > 0 AND p_cf > 0
                   -- ① preprocess 가 그날 조정을 한 건도 걸지 않았다
                   AND ABS(cf / p_cf - 1.0) <= 1e-9
                   -- ② 그런데 주식수는 움직였다
                   AND ABS(qr - 1.0) > 1e-9
                   -- ③ 가격비가 가격제한폭의 두 배 밖이다 (정상 거래로는 불가능)
                   AND ABS(rho - 1.0) > ?
                   -- ④ c 를 곱하면 1 에 훨씬 가까워지고(로그거리 2배 이상),
                   --    남은 잔차가 주식수 신호보다 작다.
                   --    v*v <= w 가 2*|ln v| <= |ln w| 와 같다 → FIX_RESCUE 주석 참고
                   AND max(rho * qr, 1.0 / (rho * qr))
                     * max(rho * qr, 1.0 / (rho * qr)) <= max(rho, 1.0 / rho)
                   AND max(rho * qr, 1.0 / (rho * qr)) < max(qr, 1.0 / qr)
              THEN qr ELSE 1.0 END fixq
    FROM r
)
SELECT di,
       -- ── PR·EW (분모가 다를 뿐 유효성 판정은 같다) ──────────────────────
       COUNT(CASE WHEN adj > 0 AND p_adj > 0 THEN 1 END)                       n_pr,
       SUM(CASE WHEN adj > 0 AND p_adj > 0 THEN p_cap END)                     den_pr,
       SUM(CASE WHEN adj > 0 AND p_adj > 0 THEN p_cap * adj / p_adj * fixq END) num_pr,
       SUM(CASE WHEN adj > 0 AND p_adj > 0 THEN adj / p_adj * fixq END)         num_ew,
       SUM(CASE WHEN adj > 0 AND p_adj > 0
                 AND NOT COALESCE(q_di = di - 2 AND q_cap > 0 AND q_adj > 0, 0)
                THEN 1 ELSE 0 END)                                             ent_pr,
       SUM(CASE WHEN adj > 0 AND p_adj > 0 AND ABS(adj / p_adj * fixq - 1.0) > ?
                THEN 1 ELSE 0 END)                                             out_pr,
       -- ── TR (세전) ────────────────────────────────────────────────────
       -- ⚠️ fixq 를 TR 에도 **똑같이** 곱한다. 감자는 가격에서 온 사건이고
       --    tr_index 는 그 가격 위에 배당을 얹은 것이라 **같은 배율로 오염**된다
       --    (제일바이오 실측: tr 0.5848 → 175.71 로 PR 과 똑같이 300.48배 튀었다).
       --    PR 만 고치면 TR÷PR 이 1/300 로 꺼져 배당 기여가 음수가 된다.
       COUNT(CASE WHEN tr > 0 AND p_tr > 0 THEN 1 END)                         n_tr,
       SUM(CASE WHEN tr > 0 AND p_tr > 0 THEN p_cap END)                       den_tr,
       SUM(CASE WHEN tr > 0 AND p_tr > 0 THEN p_cap * tr / p_tr * fixq END)     num_tr,
       SUM(CASE WHEN tr > 0 AND p_tr > 0
                 AND NOT COALESCE(q_di = di - 2 AND q_cap > 0 AND q_tr > 0, 0)
                THEN 1 ELSE 0 END)                                             ent_tr,
       SUM(CASE WHEN tr > 0 AND p_tr > 0 AND ABS(tr / p_tr * fixq - 1.0) > ?
                THEN 1 ELSE 0 END)                                             out_tr,
       -- ── TRN (세후) ───────────────────────────────────────────────────
       COUNT(CASE WHEN trn > 0 AND p_trn > 0 THEN 1 END)                       n_trn,
       SUM(CASE WHEN trn > 0 AND p_trn > 0 THEN p_cap END)                     den_trn,
       SUM(CASE WHEN trn > 0 AND p_trn > 0 THEN p_cap * trn / p_trn * fixq END) num_trn,
       SUM(CASE WHEN trn > 0 AND p_trn > 0
                 AND NOT COALESCE(q_di = di - 2 AND q_cap > 0 AND q_trn > 0, 0)
                THEN 1 ELSE 0 END)                                             ent_trn,
       SUM(CASE WHEN trn > 0 AND p_trn > 0 AND ABS(trn / p_trn * fixq - 1.0) > ?
                THEN 1 ELSE 0 END)                                             out_trn,
       -- ── 감사용 카운터 ────────────────────────────────────────────────
       SUM(CASE WHEN adj IS NULL OR p_adj IS NULL THEN 1 ELSE 0 END)           no_adj,
       SUM(CASE WHEN adj > 0 AND p_adj > 0 AND (tr IS NULL OR p_tr IS NULL)
                THEN 1 ELSE 0 END)                                             no_tr,
       -- ⚠️ `adj <> p_adj` 로 비교하면 안 된다. 값이 같아도 부동소수점 마지막 비트가
       --    달라 거짓 양성이 난다(실측: 대유플러스 20241025·키위미디어그룹 20201105 —
       --    둘 다 비율이 정확히 1.0 인데 <> 로는 걸렸다). **비율에 허용오차**를 준다.
       --    세는 것은 "거래가 없었는데 수정주가가 움직인" 날 = 조정계수가 그 움직임을
       --    **흡수하지 못한** 날이다(CLI 문구가 이 방향과 같아야 한다).
       SUM(CASE WHEN hl = 1 AND adj > 0 AND p_adj > 0
                 AND ABS(adj / p_adj - 1.0) > 1e-9
                THEN 1 ELSE 0 END)                                             hl_moved,
       -- §주식수 사건 보정이 그날 고친 종목 수와 그 내역.
       SUM(CASE WHEN fixq <> 1.0 THEN 1 ELSE 0 END)                            n_fix,
       group_concat(CASE WHEN fixq <> 1.0
                    THEN cd || '|' || printf('%.6f', rho)
                            || '|' || printf('%.9f', qr)
                            || '|' || printf('%.0f', p_cap) END)               fix_detail,
       -- 이상치는 세기만 하는 게 아니라 **어느 종목인지** 남겨야 원인을 되물을 수 있다.
       -- 건수가 극소(KOSPI 20건)라 group_concat 으로 같이 들고 나와도 부담이 없다.
       -- ★ 보정 **후**의 비율로 센다 — 제일바이오는 보정 뒤에도 -80% 라 여전히
       --   이상치다(맞다, 그날 진짜로 -80% 였다). 다만 이제 +29,948% 가 아니다.
       group_concat(CASE WHEN adj > 0 AND p_adj > 0
                          AND ABS(adj / p_adj * fixq - 1.0) > ?
                    THEN cd || '|' || printf('%.6f', adj / p_adj * fixq)
                            || '|' || printf('%.0f', p_cap) END)               out_detail
  FROM e
 WHERE p_di = di - 1 AND p_cap > 0
 GROUP BY di
 ORDER BY di
"""


def _aggregate(conn: sqlite3.Connection, market: str) -> List[sqlite3.Row]:
  """한 시장의 전 거래일 단면 집계. 반환 행 수 = 그 시장의 거래일 수 − 1.

  ``?`` 는 순서대로 **6개**다 — 시장 하나, 보정 트리거(③) 하나, 이상치 기준 넷
  (PR·TR·TRN·내역). 전부 같은 ``OUTLIER_TOL`` 을 쓰는 것이 우연이 아니다: "평범한
  등락이 아니다" 의 선이 하나여야 세는 것과 고치는 것이 어긋나지 않는다.
  """
  return list(conn.execute(
      _AGG_SQL, (market,) + (OUTLIER_TOL,) * 5))


def _base_row(conn: sqlite3.Connection, market: str, base_dt: str) -> Tuple[int, float]:
  """기준일 행에 넣을 ``(n_const, mcap_total)``.

  기준일에는 '어제' 가 없어 ``U_0`` 가 정의되지 않는다. 그래서 **그날 시세가 있는
  보통주 수와 그 시총 합**을 넣는다 — 수익률 계산에 쓰인 수가 아니라 '그날 시장이
  이만했다' 는 기록이다. 네 계열 모두 같은 값을 쓴다(계열별로 갈라지는 것은 ρ 뿐인데
  기준일에는 ρ 가 없다).
  """
  r = conn.execute(
      "SELECT COUNT(*), COALESCE(SUM(mrkt_tot_amt), 0) FROM price_daily "
      "WHERE bas_dt = ? AND mrkt_ctg = ? AND substr(srtn_cd, 6, 1) = '0' "
      "  AND mrkt_tot_amt > 0", (base_dt, market)).fetchone()
  return int(r[0]), float(r[1])


# ==================================================
# 계산 — 연쇄곱
# ==================================================
#: 계열별로 (분자칸, 분모칸, 종목수칸, 편입칸, 이상치칸) 을 어디서 읽는가.
#: EW 는 분모가 '종목 수' 다 — 가중치 w = 1.0 이라 Σw = |U_k| 이기 때문이다.
_VARIANT_COLS = {
  "PR":  ("num_pr",  "den_pr",  "n_pr",  "ent_pr",  "out_pr"),
  "TR":  ("num_tr",  "den_tr",  "n_tr",  "ent_tr",  "out_tr"),
  "TRN": ("num_trn", "den_trn", "n_trn", "ent_trn", "out_trn"),
  "EW":  ("num_ew",  "n_pr",    "n_pr",  "ent_pr",  "out_pr"),
}


def _chain(rows: Sequence[sqlite3.Row], cal: Sequence[str], variant: str,
           market: str, base_di: int, base_dt: str,
           base_level: float) -> List[tuple]:
  """단면 집계를 연쇄곱해 (레벨, 수익률) 행으로 편다.

  누적 방향은 **앞 → 뒤** 다(``total_return`` 과 같다). ``preprocess.cumulative()``
  가 뒤 → 앞인 것과 반대인데, 이유가 다르다: 수정주가는 '오늘 가격이 바뀌면 안 되니'
  오늘을 1.0 으로 두고 과거를 고치고, 지수는 '누적 수익이 곧 답이라' 시작점을 고정한다.

  ``n_exited`` 는 집합 항등식으로 유도한다::

      |U_k| = |U_{k-1}| + 편입 − 이탈   →   이탈 = |U_{k-1}| + 편입 − |U_k|

  이탈 종목은 그날 **행 자체가 없어서**(상장폐지) 단면 집계로는 셀 수 없다. 편입만
  세고 나머지는 이 항등식으로 얻는 편이 정확하고 싸다.

  ⚠️ **첫 계산일은 편입·이탈을 0 으로 둔다.** SQL 의 ``ent_*`` 는 "2일 전에도
  구성종목이었나" 를 ``LAG(…, 2)`` 로 보는데, 첫 계산일에는 2일 전 행이 **전 종목
  NULL** 이라 구성종목 전체가 '신규 편입' 으로 잡힌다(실측: 20200103 KOSPI 에서
  n_const 799 · 편입 799). 이건 편입이 아니라 **관측 시작**이다. 항등식도 그날은
  성립하지 않는다 — 기준일 행의 ``n_const`` 는 ρ 로 고른 |U| 가 아니라 '그날 시세가
  있는 보통주 수' 라서 애초에 같은 집합이 아니기 때문이다. 그래서 세지 않는다.
  """
  num_c, den_c, n_c, ent_c, out_c = _VARIANT_COLS[variant]
  out: List[tuple] = []
  level = base_level
  prev_n: Optional[int] = None
  for r in rows:
    di = r["di"]
    if di < base_di:
      continue                      # 기준일 이전은 버린다 (--base 로 뒤로 미뤘을 때)
    den, num, n = r[den_c], r[num_c], r[n_c]
    if not den or not n:
      continue                      # 그 시장이 그날 하루도 성립하지 않았다
    ratio = num / den
    level *= ratio
    first = prev_n is None          # 첫 계산일 — '어제의 U' 가 없다
    ent = 0 if first else r[ent_c]
    exited = 0 if first else max(prev_n + ent - n, 0)
    out.append((cal[di], market, variant, ratio - 1.0, level, n,
                float(r["den_pr"] or 0.0) if variant == "EW" else float(den),
                ent, exited, r[out_c], r["n_fix"], base_dt, base_level))
    prev_n = n
  return out


def build(conn: sqlite3.Connection, markets: Optional[Sequence[str]] = None,
          variants: Optional[Sequence[str]] = None, *,
          base_dt: str = BASE_DT, base_level: float = BASE_LEVEL,
          verbose: bool = False) -> Dict[str, int]:
  """벤치마크 계열을 다시 만든다. **몇 번을 돌려도 같은 결과**가 된다.

  재실행 안전(idempotent)이 네 겹으로 보장된다 ::

      ① (시장, 계열) 조합별 DELETE → INSERT
      ② 전체를 감싸는 단일 BEGIN IMMEDIATE (중간 커밋 없음)
      ③ 입력이 전부 DB 안의 결정적 값 — 네트워크 0회
      ④ 산식이 순수 함수 (난수·시각·환경 의존 없음)

  그래서 ``rebuild`` 서브커맨드가 필요 없다. ``build`` 가 곧 전체 재계산이다.
  """
  _ensure_schema(conn)
  markets = list(markets) if markets else list(MARKETS)
  variants = list(variants) if variants else list(VARIANTS)

  cal = _calendar(conn)
  if base_dt not in cal:
    raise SystemExit(
        f"기준일 {base_dt} 은 거래일이 아니다. price_daily 의 거래일 중에서 고른다 "
        f"(첫날 {cal[0]} · 마지막 {cal[-1]}).")
  base_di = cal.index(base_dt)
  _install_calendar(conn, cal)

  tally = {"markets": 0, "variants": 0, "rows": 0, "days": 0,
           "no_adjusted": 0, "no_tr": 0, "outlier": 0, "halted_moved": 0,
           "fixed": 0}
  seen_days = set()
  conn.execute("BEGIN IMMEDIATE")
  try:
    for m in markets:
      rows = _aggregate(conn, m)
      if not rows:
        if verbose:
          print(f"  ⚠️ {m}: 시세가 한 줄도 없다 — 건너뛴다")
        continue
      # 감사 카운터는 계열과 무관한 '읽기' 수준의 수라 시장당 한 번만 센다.
      for r in rows:
        if r["di"] < base_di:
          continue
        seen_days.add(r["di"])
        tally["no_adjusted"] += r["no_adj"]
        tally["no_tr"] += r["no_tr"]
        tally["halted_moved"] += r["hl_moved"]
      _report_fixes(conn, m, rows, cal, base_di, tally, verbose)
      _report_outliers(conn, m, rows, cal, base_di, tally, verbose)

      n_base, cap_base = _base_row(conn, m, base_dt)
      for v in variants:
        body = _chain(rows, cal, v, m, base_di, base_dt, base_level)
        if not body:
          continue
        # 기준일 행 — ret 은 NULL 이고 level 은 base_level 그대로다.
        head = (base_dt, m, v, None, base_level, n_base, cap_base, 0, 0, 0, 0,
                base_dt, base_level)
        conn.execute("DELETE FROM benchmark_index WHERE mrkt_ctg=? AND variant=?", (m, v))
        conn.executemany(
            "INSERT INTO benchmark_index "
            "(bas_dt,mrkt_ctg,variant,ret,level,n_const,mcap_total,"
            " n_entered,n_exited,n_outlier,n_fixed,base_dt,base_level) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [head] + body)
        tally["rows"] += len(body) + 1
        tally["variants"] += 1
      tally["markets"] += 1
    conn.execute("COMMIT")
  except Exception:
    conn.execute("ROLLBACK")
    raise
  tally["days"] = len(seen_days) + 1        # +1 = 기준일
  return tally


def _names(conn: sqlite3.Connection, codes: Sequence[str]) -> Dict[str, str]:
  """표시용 종목명. **조인·필터 키로 쓰면 안 된다** — 617종목이 개명했다."""
  return {cd: (conn.execute(
      "SELECT itms_nm FROM price_daily WHERE srtn_cd=? ORDER BY bas_dt DESC LIMIT 1",
      (cd,)).fetchone() or [""])[0] for cd in set(codes)}


def _report_fixes(conn: sqlite3.Connection, market: str, rows: Sequence[sqlite3.Row],
                  cal: Sequence[str], base_di: int, tally: Dict[str, int],
                  verbose: bool) -> None:
  """§주식수 사건 보정이 고친 종목-일을 세고 **항상** 찍는다.

  ⚠️ ``verbose`` 와 무관하게 출력한다. 이상치(``_report_outliers``)와 다른 이유는
  성격이 다르기 때문이다 — 이상치는 '시장에서 실제로 일어난 일' 이라 조용해도 되지만,
  보정은 **우리가 원본 데이터를 뒤집은 것**이다. 소리 없이 값을 바꾸는 것이 이 모듈이
  고치려는 바로 그 병이다. 건수가 극소(전 구간 1건)라 시끄러울 일도 없다.
  """
  hits: List[Tuple[str, str, float, float, float]] = []
  for r in rows:
    if r["di"] < base_di or not r["fix_detail"]:
      continue
    for item in r["fix_detail"].split(","):
      cd, rho, qr, pcap = item.split("|")
      hits.append((cal[r["di"]], cd, float(rho), float(qr), float(pcap)))
  tally["fixed"] += len(hits)
  if not hits:
    return
  names = _names(conn, [h[1] for h in hits])
  for dt, cd, rho, qr, pcap in sorted(hits, key=lambda h: h[0]):
    print(f"  🔧 주식수 사건 보정 — {market} {dt} {cd} {names.get(cd, '')} "
          f"가격비 {(rho - 1) * 100:+,.1f}% × 주식수비 {qr:.8f} "
          f"→ {(rho * qr - 1) * 100:+.2f}% (전일시총 {pcap / 1e8:,.0f}억)")
    print(f"     조정계수가 놓친 감자·병합으로 본다. 근거는 §주식수 사건 보정 ①~④")


def _report_outliers(conn: sqlite3.Connection, market: str, rows: Sequence[sqlite3.Row],
                     cal: Sequence[str], base_di: int, tally: Dict[str, int],
                     verbose: bool) -> None:
  """하루 ±60% 를 넘은 종목-일을 세고, verbose 면 목록을 찍는다.

  **값은 그대로 지수에 반영된다.** 여기서 하는 일은 기록뿐이다 — 카프로 −94.9%,
  에코바이브 −97.7% 같은 값은 감자·거래재개 뒤의 **실제** 등락이고, 지우면
  벤치마크가 실제보다 좋아 보인다.

  ★ 세는 기준은 **§주식수 사건 보정을 거친 뒤**의 비율이다. 그래서 제일바이오
  20260209 는 여기에 +29,948% 가 아니라 **−80.0%** 로 나온다 — 여전히 이상치이고
  (그날 진짜로 −80% 였다) 그 값 그대로 지수에 들어간다.
  """
  hits: List[Tuple[str, str, float, float]] = []
  for r in rows:
    if r["di"] < base_di or not r["out_detail"]:
      continue
    for item in r["out_detail"].split(","):
      cd, ratio, pcap = item.split("|")
      hits.append((cal[r["di"]], cd, float(ratio) - 1.0, float(pcap)))
  tally["outlier"] += len(hits)
  if not (verbose and hits):
    return
  names = _names(conn, [h[1] for h in hits])
  for dt, cd, ret, pcap in sorted(hits, key=lambda h: abs(h[2]), reverse=True):
    print(f"  ⚠️ 하루 ±60% — {market} {dt} {cd} {names.get(cd, '')} "
          f"{ret * 100:.1f}% (전일시총 {pcap / 1e8:,.0f}억)")


# ==================================================
# 보고 — 숫자를 사람이 읽을 수 있게
# ==================================================
def _pad(s: str, width: int) -> str:
  """한글을 **두 칸**으로 세어 오른쪽을 채운다.

  ``str.ljust`` 는 글자 수로 세기 때문에 "TR (세전)" 과 "TRN(세후 15.4%)" 를 나란히
  두면 터미널에서 표가 어긋난다. 한글·전각기호는 화면에서 두 칸을 차지한다.
  """
  w = sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)
  return s + " " * max(width - w, 0)


def _tail(conn: sqlite3.Connection, market: str, variant: str) -> Optional[sqlite3.Row]:
  return conn.execute(
      "SELECT bas_dt, level, n_const FROM benchmark_index "
      "WHERE mrkt_ctg=? AND variant=? ORDER BY bas_dt DESC LIMIT 1",
      (market, variant)).fetchone()


def _head_level(conn: sqlite3.Connection, market: str, variant: str) -> Optional[float]:
  r = conn.execute(
      "SELECT level FROM benchmark_index WHERE mrkt_ctg=? AND variant=? "
      "ORDER BY bas_dt LIMIT 1", (market, variant)).fetchone()
  return r["level"] if r else None


def status(conn: sqlite3.Connection) -> None:
  """적재 현황."""
  _ensure_schema(conn)
  n, nm, nv, a, b = conn.execute(
      "SELECT COUNT(*), COUNT(DISTINCT mrkt_ctg), COUNT(DISTINCT variant), "
      "       MIN(bas_dt), MAX(bas_dt) FROM benchmark_index").fetchone()
  print("― 벤치마크 지수 현황 ―")
  if not n:
    print("  아직 없다. `python -m collector.benchmark build` 로 만든다.")
    return
  print(f"  {n:,}행 · 시장 {nm:,}개 · 계열 {nv:,}개 · {a} ~ {b}")
  base = _head_level(conn, "KOSPI", "PR")
  print(f"  기준일 {a} = {base:.1f}" if base else "")

  # 시장 순서는 알파벳순이 아니라 **MARKETS 상수 순서**(KOSPI → KOSDAQ → KONEX)다.
  # 읽는 사람이 먼저 보고 싶은 것은 본지수인 KOSPI 이고, 참고용인 KONEX 가 맨 뒤다.
  have = [r[0] for r in conn.execute("SELECT DISTINCT mrkt_ctg FROM benchmark_index")]
  for m in [x for x in MARKETS if x in have] + [x for x in have if x not in MARKETS]:
    note = "  (참고용 — 거래가 희박해 벤치마크로 쓰지 않는다)" if m == "KONEX" else ""
    print(f"\n― {m} ―{note}")
    pr = _tail(conn, m, "PR")
    base_m = _head_level(conn, m, "PR") or BASE_LEVEL
    for v in VARIANTS:
      t = _tail(conn, m, v)
      if not t:
        continue
      lvl = t["level"]
      line = (_pad(f"    {v:<3}({VARIANT_DESC[v]})", 24)
              + f"{lvl:10.4f}  →  {(lvl / base_m - 1) * 100:+8.2f}%")
      if v in ("TR", "TRN") and pr:
        line += f"   배당 기여 {(lvl / pr['level'] - 1) * 100:+6.2f}%p"
      elif v == "EW" and pr:
        line += f"   시총가중 대비 {(lvl / pr['level'] - 1) * 100:+7.2f}%p"
      else:
        line += f"   구성 {t['n_const']:,}종목"
      print(line)

  print("\n― 구성종목 변동 (최근 10 거래일) ―")
  for r in conn.execute(
      "SELECT bas_dt, mrkt_ctg, n_const, n_entered, n_exited, n_outlier "
      "FROM benchmark_index WHERE variant='PR' "
      "  AND bas_dt IN (SELECT DISTINCT bas_dt FROM benchmark_index "
      "                  ORDER BY bas_dt DESC LIMIT 10) "
      "ORDER BY bas_dt DESC, mrkt_ctg"):
    print(f"    {r['bas_dt']}  {r['mrkt_ctg']:<7}{r['n_const']:>6,}종목  "
          f"편입 {r['n_entered']} · 이탈 {r['n_exited']} · 이상치 {r['n_outlier']}")

  # ── 원본을 뒤집은 곳은 **현황에서도 보여야 한다** ────────────────────────────
  fixes = list(conn.execute(
      "SELECT bas_dt, mrkt_ctg, n_fixed FROM benchmark_index "
      "WHERE variant='PR' AND n_fixed > 0 ORDER BY bas_dt"))
  print("\n― 주식수 사건 보정 ―")
  if not fixes:
    print("    없음 — 조정계수가 놓친 감자·병합이 한 건도 없다")
  for r in fixes:
    print(f"    {r['bas_dt']}  {r['mrkt_ctg']:<7}{r['n_fixed']}종목  "
          f"(조정계수가 놓친 감자·병합을 시총비로 되돌렸다)")

  print("\n― 주의 ―")
  miss = conn.execute(
      "SELECT COUNT(*) FROM dividend WHERE needs_review=1 AND dps IS NULL").fetchone()[0]
  if miss:
    print(f"  ⚠️ 배당 누락 {miss:,}건 (dps 를 공시 본문에서 못 읽음) "
          f"— TR 이 그만큼 과소계상돼 있다")
    print(f"     `python -m collector.dividend` 로 다시 읽어 본다")
  # 기준이 다른 계열이 한 표에 섞였는가 — base_dt·base_level 이 그걸 드러낸다.
  mixed = list(conn.execute(
      "SELECT mrkt_ctg, variant, COUNT(DISTINCT base_dt || '/' || base_level) k "
      "FROM benchmark_index GROUP BY mrkt_ctg, variant HAVING k > 1"))
  bases = list(conn.execute(
      "SELECT DISTINCT base_dt, base_level FROM benchmark_index "
      "WHERE base_dt IS NOT NULL"))
  if mixed or len(bases) > 1:
    print(f"  ⚠️ **기준이 다른 계열이 한 표에 섞여 있다** — 겹쳐 그리면 안 된다:")
    for b in bases:
      print(f"     기준일 {b['base_dt']} = {b['base_level']}")
    print(f"     `build` 를 시장·계열 지정 없이 한 번 더 돌려 전체를 맞춘다")
  elif bases:
    print(f"  · 전 계열 공통 기준 {bases[0]['base_dt']} = {bases[0]['base_level']}")
  print("  ⚠️ 이 계열은 **KRX 공식 지수가 아니다.** 자체 재현치이며 공식 연말 종가와")
  print("     코스피 평균 0.066% · **코스닥 평균 0.871%** 차이난다 (`verify` 참조).")
  print("     코스닥은 미해결 결함이 남아 있어 코스피와 같은 신뢰도로 쓰면 안 된다.")
  print("     기준일 레벨 1000.0 은 임의값이다")


# ==================================================
# 검증 — 공식값을 쓸 수 없는 상황에서 어떻게 맞다고 확신하는가
# ==================================================
#: 게이트 1 — 독립된 두 경로가 같은 수에 닿는가.
#:   A (정본)  adj_clpr(t) / adj_clpr(t−1)      ← preprocess 의 뒤→앞 누적을 거친 값
#:   B (독립)  clpr(t) / (clpr(t) − vs(t))      ← price_daily 원본 두 칸, 누적 없음
#: 수학적으로 동일해야 한다(preprocess.factors 의 f = base/prev_clpr 를 대입하면
#: cum 이 약분돼 clpr(t)/(clpr(t)−vs(t)) 만 남는다). 어긋나면 누적 방향 오류·
#: cum_factor 손상·조인 어긋남·날짜 정렬 오류 중 하나다.
_GATE1_SQL = """
WITH s AS (
  SELECT p.srtn_cd cd, c.di di, p.clpr clpr, p.vs vs, a.adj_clpr adj
    FROM price_daily p
    JOIN temp.bm_cal c         ON c.bas_dt = p.bas_dt
    LEFT JOIN price_adjusted a ON a.bas_dt = p.bas_dt AND a.srtn_cd = p.srtn_cd
   WHERE p.mrkt_ctg = ? AND substr(p.srtn_cd, 6, 1) = '0'
), g AS (
  SELECT cd, di, clpr, vs, adj, LAG(di) OVER w p_di, LAG(adj) OVER w p_adj
    FROM s WINDOW w AS (PARTITION BY cd ORDER BY di)
)
SELECT COUNT(*) n, MAX(ABS(adj / p_adj - clpr * 1.0 / (clpr - vs))) worst
  FROM g
 WHERE p_di = di - 1 AND adj > 0 AND p_adj > 0 AND clpr > 0 AND (clpr - vs) > 0
"""


def _gate1(conn: sqlite3.Connection, markets: Sequence[str]) -> bool:
  print("― 검증 1: 두 경로가 같은 수에 닿는가 (수정주가 비율 vs 종가÷기준가) ―")
  ok_all = True
  for m in markets:
    r = conn.execute(_GATE1_SQL, (m,)).fetchone()
    if not r["n"]:
      # ⚠️ '대조할 쌍이 없다' 는 통과가 아니라 **검사를 못 한 것**이다.
      #    검사 못 한 것을 통과로 세면 빈 DB 가 조용히 초록불을 받는다.
      print(f"  {m:<7} 대조할 쌍이 없다 → ❌ 검증 불가")
      ok_all = False
      continue
    ok = r["worst"] < 1e-9
    ok_all &= ok
    print(f"  {m:<7} 대조 {r['n']:,}쌍  최대차 {r['worst']:.3e}  "
          f"→ {'✅ 일치' if ok else '❌ 어긋남'}")
  return ok_all


def _gate2(conn: sqlite3.Connection, markets: Sequence[str]) -> bool:
  """공식 연말 종가 대조 — 시장마다 앵커 1점만 빌린다.

  우리 계열의 절대 레벨은 임의값(1000.0)이라 그대로는 공식값과 못 견준다. 그래서
  기준일 하나만 공식 종가에 맞춰 통째로 비례 확대한 뒤(앵커), **그 뒤의 모든 연말값이
  스스로 맞아떨어지는지**를 본다. 앵커는 배율 하나일 뿐이라 여섯 해의 일치는 공짜가
  아니다 — 산식·편입규칙·조정계수가 전부 맞아야 나온다.

  ★★ **코스피만 보면 안 된다.** 이 게이트가 코스피만 보던 동안, 코스닥에는
  제일바이오 +3.060%p 가 6.7년째 박혀 있었고 여섯 해의 코스피 대조는 그것을
  **한 번도 알아차리지 못했다.** 시장이 다르면 터지는 곳도 다르다.
  """
  print("\n― 검증 2: 공식 연말 종가 대조 ―")
  ok_all = True
  for m in markets:
    spec = OFFICIAL.get(m)
    if not spec:
      # KONEX 처럼 공식 상수가 없는 시장은 **검사 대상이 아니다**(실패가 아니다).
      print(f"  {m:<7} 공식 연말 종가 상수가 없다 — 대조하지 않는다")
      continue
    anchor_dt, anchor_val = spec["anchor"]
    base = _head_level(conn, m, "PR")
    if not base:
      print(f"  {m:<7} PR 계열이 없다 — `build` 를 먼저 돌린다 → ❌ 검증 불가")
      ok_all = False
      continue
    head_dt = conn.execute(
        "SELECT MIN(bas_dt) FROM benchmark_index WHERE mrkt_ctg=? AND variant='PR'",
        (m,)).fetchone()[0]
    # 앵커는 '기준일의 공식 종가' 다. 기준일이 다르면 배율이 틀려 전부 어긋난다.
    if head_dt != anchor_dt:
      print(f"  {m:<7} 기준일이 {head_dt} 인데 앵커는 {anchor_dt} 다 "
            f"— 배율을 못 만든다 → ❌ 검증 불가")
      ok_all = False
      continue
    scale = anchor_val / base
    print(f"  ― {m} (앵커 {anchor_dt} = {anchor_val}) ―")
    errs: List[float] = []
    for year in sorted(spec["yearend"]):
      want_dt, official = spec["yearend"][year]
      r = conn.execute(
          "SELECT bas_dt, level FROM benchmark_index "
          "WHERE mrkt_ctg=? AND variant='PR' AND bas_dt LIKE ? "
          "ORDER BY bas_dt DESC LIMIT 1", (m, year + "%")).fetchone()
      if not r:
        print(f"    {year} 재현치 없음 → ❌")
        ok_all = False
        continue
      got = r["level"] * scale
      err = (got / official - 1) * 100
      errs.append(abs(err))
      mark = "✅" if abs(err) < spec["year_tol"] else "❌ 게이트 초과"
      dt_note = "" if r["bas_dt"] == want_dt else f" (공식 기준일 {want_dt})"
      print(f"    {year} {r['bas_dt']}  재현 {got:9.2f}  공식 {official:9.2f}  "
            f"→ {err:+.3f}%  {mark}{dt_note}")
    if not errs:
      ok_all = False
      continue
    mean = sum(errs) / len(errs)
    ok = mean < spec["mean_tol"] and max(errs) < spec["year_tol"]
    ok_all &= ok
    print(f"    평균 |오차| {mean:.3f}% · 최대 {max(errs):.3f}%  "
          f"· 게이트 연 {spec['year_tol']:.2f}% / 평균 {spec['mean_tol']:.2f}% "
          f"→ {'✅ 통과' if ok else '❌ 회귀'}")
    # ⚠️ 통과했다고 '잘 맞는다' 는 뜻이 아니다. 기준선이 시장마다 다르므로,
    #    가장 엄격한 시장보다 느슨한 기준을 쓰는 곳은 **그 사실을 말해야 한다.**
    #    안 그러면 초록불 하나로 "코스닥도 코스피만큼 맞는다" 고 읽힌다.
    tight = min(s["mean_tol"] for s in OFFICIAL.values())
    if ok and spec["mean_tol"] > tight:
      print(f"    ⚠️ 이 기준({spec['mean_tol']:.2f}%)은 가장 엄격한 시장"
            f"({tight:.2f}%)보다 {spec['mean_tol'] / tight:.0f}배 느슨하다 —"
            f" 합격선이 아니라 **미해결 결함의 현재 크기**다 (OFFICIAL 주석 참고)")
  return ok_all


def _gate3(conn: sqlite3.Connection, markets: Sequence[str]) -> bool:
  """레벨 ↔ 수익률 왕복. 둘 다 저장하므로 서로 재현되어야 한다.

  연쇄곱 누적 버그(순서 뒤집힘·기준일 오프셋·NULL 전파)를 잡는다.
  """
  print("\n― 검증 3: 레벨을 되돌려 수익률이 재현되는가 ―")
  ok_all, seen = True, 0
  for m in markets:
    for v in VARIANTS:
      rows = list(conn.execute(
          "SELECT bas_dt, ret, level FROM benchmark_index "
          "WHERE mrkt_ctg=? AND variant=? ORDER BY bas_dt", (m, v)))
      if len(rows) < 2:
        continue
      seen += 1
      worst = 0.0
      head_ok = rows[0]["ret"] is None
      for prev, cur in zip(rows, rows[1:]):
        worst = max(worst, abs(cur["level"] / prev["level"] - 1 - cur["ret"]))
      ok = worst < 1e-12 and head_ok
      ok_all &= ok
      print(f"  {m:<7} {v:<3} level 비율 vs 저장된 ret  최대차 {worst:.2e}  "
            f"→ {'✅ 일치' if ok else '❌ 어긋남'}"
            + ("" if head_ok else "  (기준일 ret 이 NULL 이 아니다)"))
  if not seen:
    print("  검사할 계열이 없다 → ❌ 검증 불가")
    return False
  return ok_all


def _series(conn: sqlite3.Connection, market: str, variant: str) -> Dict[str, float]:
  return {r["bas_dt"]: r["ret"] for r in conn.execute(
      "SELECT bas_dt, ret FROM benchmark_index WHERE mrkt_ctg=? AND variant=? "
      "  AND ret IS NOT NULL", (market, variant))}


def _corr(a: Dict[str, float], b: Dict[str, float]) -> Optional[float]:
  """두 일별 수익률 계열의 피어슨 상관. numpy 없이 — collector 는 표준 라이브러리만."""
  keys = sorted(set(a) & set(b))
  n = len(keys)
  if n < 2:
    return None
  xs = [a[k] for k in keys]
  ys = [b[k] for k in keys]
  mx, my = sum(xs) / n, sum(ys) / n
  sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
  sxx = sum((x - mx) ** 2 for x in xs)
  syy = sum((y - my) ** 2 for y in ys)
  return sxy / (sxx * syy) ** 0.5 if sxx > 0 and syy > 0 else None


#: 시총 상위 N 종목만 담은 가중 계열과 전체 계열의 일별 상관.
#:
#: ⚠️ 이 계열을 **'KOSPI 200' 이라 부르면 안 된다.** 공식 KOSPI 200 은 유동주식비율로
#: 가중하고 반기 정기변경으로 구성을 정하는데, 우리 DB 에는 유동주식비율 칸 자체가
#: 없어 구조적으로 재현이 불가능하다. 이름을 빌리는 순간 구조적 오차가 버그로 오해된다.
#: 여기서는 오로지 **가중치 산술이 맞는지 보는 검증용**으로만 쓰고 표에 저장하지 않는다.
_TOPN_SQL = """
WITH s AS (
  SELECT p.srtn_cd cd, c.di di, p.mrkt_tot_amt cap, a.adj_clpr adj
    FROM price_daily p
    JOIN temp.bm_cal c         ON c.bas_dt = p.bas_dt
    LEFT JOIN price_adjusted a ON a.bas_dt = p.bas_dt AND a.srtn_cd = p.srtn_cd
   WHERE p.mrkt_ctg = ? AND substr(p.srtn_cd, 6, 1) = '0'
), g AS (
  SELECT cd, di, adj, LAG(di) OVER w p_di, LAG(cap) OVER w p_cap, LAG(adj) OVER w p_adj
    FROM s WINDOW w AS (PARTITION BY cd ORDER BY di)
), e AS (
  SELECT di, p_cap, adj / p_adj r,
         RANK() OVER (PARTITION BY di ORDER BY p_cap DESC) rk
    FROM g
   WHERE p_di = di - 1 AND p_cap > 0 AND adj > 0 AND p_adj > 0
)
SELECT di,
       SUM(p_cap * r) / SUM(p_cap) - 1                                    all_r,
       SUM(CASE WHEN rk <= ? THEN p_cap * r END)
         / SUM(CASE WHEN rk <= ? THEN p_cap END) - 1                      top_r
  FROM e GROUP BY di HAVING top_r IS NOT NULL ORDER BY di
"""


def _top_n_corr(conn: sqlite3.Connection, market: str, n: int) -> Optional[float]:
  rows = list(conn.execute(_TOPN_SQL, (market, n, n)))
  if len(rows) < 2:
    return None
  return _corr({str(r["di"]): r["all_r"] for r in rows},
               {str(r["di"]): r["top_r"] for r in rows})


def _gate4(conn: sqlite3.Connection, markets: Sequence[str]) -> bool:
  """경제적 상식 검사 — 수치가 아니라 **방향과 크기**를 본다.

  게이트 1~3 은 내부 일관성만 본다. 전부 통과해도 산식 자체가 틀렸으면(예: 가중치를
  당일 시총으로 잡았으면) 조용히 통과한다. 그걸 잡는 것은 "배당 기여가 연 2% 쯤이어야
  한다" 같은 **바깥 세상의 상식**뿐이다.

  ⚠️ 합격/불합격을 내는 것은 **TR>PR 단조성**과 **상위200 vs 전체 상관** 둘뿐이다.
  배당 기여율과 동일가중 상관은 읽을거리다 — 기준선이 없는 수에 ❌ 를 붙이면
  게이트가 양치기 소년이 된다.
  """
  print("\n― 검증 4: 경제적 상식 ―")
  ok_all = True
  for m in markets:
    pr, tr = _tail(conn, m, "PR"), _tail(conn, m, "TR")
    if not (pr and tr):
      continue
    first = conn.execute(
        "SELECT MIN(bas_dt) FROM benchmark_index WHERE mrkt_ctg=?", (m,)).fetchone()[0]
    years = (int(pr["bas_dt"][:4]) - int(first[:4])
             + (int(pr["bas_dt"][4:]) - int(first[4:])) / 1231.0)
    contrib = (tr["level"] / pr["level"] - 1) * 100
    per_year = contrib / years if years > 0 else 0.0
    print(f"  {m:<7} 배당 기여 {contrib:+.2f}%p / {years:.1f}년 "
          f"= 연 {per_year:+.2f}%p")

  # TR > PR 단조성 — 배당은 음수가 될 수 없으므로 TR÷PR 이 줄어드는 날이 있으면 안 된다.
  for m in markets:
    prs = list(conn.execute(
        "SELECT bas_dt, level FROM benchmark_index WHERE mrkt_ctg=? AND variant='PR' "
        "ORDER BY bas_dt", (m,)))
    trs = {r["bas_dt"]: r["level"] for r in conn.execute(
        "SELECT bas_dt, level FROM benchmark_index WHERE mrkt_ctg=? AND variant='TR' "
        "ORDER BY bas_dt", (m,))}
    if not prs or not trs:
      continue
    worst, worst_dt = 0.0, ""
    prev = None
    for r in prs:
      if r["bas_dt"] not in trs or r["level"] <= 0:
        continue
      ratio = trs[r["bas_dt"]] / r["level"]
      if prev is not None and ratio - prev < worst:
        worst, worst_dt = ratio - prev, r["bas_dt"]
      prev = ratio
    ok = worst > -1e-9
    ok_all &= ok
    print(f"  {m:<7} TR > PR 단조성 "
          f"→ {'✅ 전 구간 성립' if ok else f'❌ {worst_dt} 에서 {worst:.2e} 역전'}")

  # ── 가중치가 제대로 걸렸는가 ──────────────────────────────────────────────
  #
  # ★ 설계 초안은 "동일가중 vs 시총가중 상관 > 0.80, 아니면 계산 오류" 를 게이트로
  #   두려 했다. **그 임계값은 쓸 수 없다** — 실측하니 KOSPI 가 0.750 으로 걸리는데,
  #   원인이 버그가 아니라 **시장 집중도**였다(2026-09-20 실측)::
  #
  #       KOSPI 상위 2종목 시총 비중   20200102  28.3%  →  20260917  51.3%
  #       KOSPI 상위 10종목            20200102  42.0%  →  20260917  63.2%
  #
  #   시총의 절반이 두 종목(삼성전자·SK하이닉스)인 지수가 831종목을 똑같이 담은
  #   지수와 0.9 로 붙을 수는 없다. 집중도가 낮은 KOSDAQ 이 0.912 인 것이 그 증거다.
  #   즉 이 상관은 **가중치 오류의 탐지기가 아니라 시장 구조의 측정치**다.
  #
  # ★ 가중치 오류를 실제로 잡는 것은 아래 '시총 상위 200 vs 전체' 쪽이다. 상위 200이
  #   KOSPI 시총의 96.9% 를 차지하므로 가중치가 제대로 걸렸다면 거의 같은 계열이
  #   나와야 한다(실측 0.9995). 가중치를 당일 시총으로 잘못 잡거나 유니버스가 어긋나면
  #   두 계열이 서로 다른 방식으로 오염돼 이 값이 먼저 무너진다.
  for m in markets:
    c = _corr(_series(conn, m, "PR"), _series(conn, m, "EW"))
    if c is None:
      continue
    print(f"  {m:<7} 동일가중 vs 시총가중 일별 상관 {c:.3f}  "
          f"(집중도 측정치 — 낮다고 오류가 아니다)")
  for m in markets:
    c = _top_n_corr(conn, m, 200)
    if c is None:
      continue
    ok_all &= c > 0.95
    print(f"  {m:<7} 시총 상위 200 vs 전체 일별 상관 {c:.4f} "
          f"→ {'✅' if c > 0.95 else '❌ 0.95 미만 — 가중치 계산 오류를 의심한다'}")
  return ok_all


def _gate5(conn: sqlite3.Connection) -> bool:
  """한 표 안의 모든 계열이 **같은 기준**으로 만들어졌는가.

  ``build`` 는 (시장, 계열) 단위로 DELETE→INSERT 한다. 그래서
  ``build --markets KOSDAQ --base 20220103`` 처럼 **일부만** 다시 만들면 한 표에
  기준이 다른 행이 남는다. 레벨은 둘 다 그냥 숫자라 **눈으로는 절대 구별되지 않고**,
  계열끼리 겹쳐 그리는 순간 조용히 틀린 그림이 나온다. ``base_dt``·``base_level``
  칸은 바로 이 사고를 드러내려고 있다.
  """
  print("\n― 검증 5: 모든 계열이 같은 기준인가 ―")
  rows = list(conn.execute(
      "SELECT mrkt_ctg, variant, base_dt, base_level, COUNT(*) n "
      "FROM benchmark_index GROUP BY mrkt_ctg, variant, base_dt, base_level "
      "ORDER BY mrkt_ctg, variant"))
  if not rows:
    print("  계열이 없다 → ❌ 검증 불가")
    return False
  legacy = [r for r in rows if r["base_dt"] is None]
  if legacy:
    # 칸을 붙이기 **전에** 만든 행이다. 실패로 치지 않고 다시 만들라고만 한다.
    print(f"  base_dt 가 비어 있는 계열 {len(legacy)}개 — 칸이 생기기 전에 만든 행이다")
    print(f"  `build` 를 한 번 더 돌리면 채워진다 → ⚠️ 판정 보류")
    return True
  bases = {(r["base_dt"], r["base_level"]) for r in rows}
  ok = len(bases) == 1
  for b in sorted(bases):
    who = [f"{r['mrkt_ctg']}/{r['variant']}" for r in rows
           if (r["base_dt"], r["base_level"]) == b]
    print(f"  기준 {b[0]} = {b[1]:.1f}  ← {len(who)}개 계열 "
          f"({', '.join(who[:4])}{' …' if len(who) > 4 else ''})")
  print(f"  → {'✅ 전 계열 한 기준' if ok else '❌ 기준이 섞였다 — 겹쳐 그리면 안 된다'}")
  return ok


#: 게이트 6 — 보정을 거친 뒤에도 하루 ABSURD_RISE 배 넘게 오른 종목-일을 찾는다.
#: `_AGG_SQL` 의 `r`·`e` 와 **판정식이 글자 그대로 같아야 한다** — 다르면 build 가
#: 고친 것을 verify 가 못 고친 것으로 보거나 그 반대가 된다.
_GATE6_SQL = """
WITH s AS (
  SELECT p.srtn_cd cd, c.di di, p.bas_dt dt, p.lstg_st_cnt q,
         a.adj_clpr adj, a.cum_factor cf
    FROM price_daily p
    JOIN temp.bm_cal c         ON c.bas_dt = p.bas_dt
    LEFT JOIN price_adjusted a ON a.bas_dt = p.bas_dt AND a.srtn_cd = p.srtn_cd
   WHERE p.mrkt_ctg = ? AND substr(p.srtn_cd, 6, 1) = '0'
), g AS (
  SELECT cd, di, dt, q, adj, cf, LAG(di) OVER w p_di,
         LAG(adj) OVER w p_adj, LAG(q) OVER w p_q, LAG(cf) OVER w p_cf
    FROM s WINDOW w AS (PARTITION BY cd ORDER BY di)
), r AS (
  SELECT g.*, CASE WHEN adj > 0 AND p_adj > 0 THEN adj / p_adj END   rho,
              CASE WHEN q   > 0 AND p_q   > 0 THEN q * 1.0 / p_q END qr
    FROM g
), e AS (
  SELECT r.*,
         CASE WHEN rho IS NOT NULL AND qr IS NOT NULL AND cf > 0 AND p_cf > 0
                   AND ABS(cf / p_cf - 1.0) <= 1e-9
                   AND ABS(qr - 1.0) > 1e-9
                   AND ABS(rho - 1.0) > ?
                   AND max(rho * qr, 1.0 / (rho * qr))
                     * max(rho * qr, 1.0 / (rho * qr)) <= max(rho, 1.0 / rho)
                   AND max(rho * qr, 1.0 / (rho * qr)) < max(qr, 1.0 / qr)
              THEN qr ELSE 1.0 END fixq
    FROM r
)
SELECT dt, cd, rho * fixq rr, COUNT(*) OVER () n
  FROM e
 WHERE p_di = di - 1 AND rho IS NOT NULL AND rho * fixq > ?
 ORDER BY rr DESC LIMIT 5
"""


def _gate6(conn: sqlite3.Connection, markets: Sequence[str]) -> bool:
  """보정 뒤에도 남은 '하루에 20배' 가 있는가 — 실제 사고를 잡는 게이트.

  ★ 게이트 2(공식 연말 종가)는 이 사고를 **잡지 못했다.** 제일바이오는 2026-02-09
  인데 공식 상수의 마지막 연말은 2025-12-30 이다. 즉 **가장 최근 연도의 사고는
  연말값이 생길 때까지 구조적으로 보이지 않는다.** 그 빈 구간을 메우는 것이 이
  게이트다 — 바깥 기준점이 없어도 "하루에 20배는 없다" 는 것만으로 판정한다.
  """
  print(f"\n― 검증 6: 하루 {ABSURD_RISE:.0f}배 넘게 오른 종목이 남았는가 ―")
  ok_all = True
  for m in markets:
    rows = list(conn.execute(_GATE6_SQL, (m, OUTLIER_TOL, ABSURD_RISE)))
    if not rows:
      print(f"  {m:<7} 0건 → ✅")
      continue
    ok_all = False
    names = _names(conn, [r["cd"] for r in rows])
    print(f"  {m:<7} {rows[0]['n']}건 → ❌ 조정계수·보정이 둘 다 놓친 사건이 있다")
    for r in rows:
      print(f"     {r['dt']} {r['cd']} {names.get(r['cd'], '')} "
            f"{(r['rr'] - 1) * 100:+,.0f}%  — lstg_st_cnt 와 vs 를 직접 확인한다")
  return ok_all


def verify(conn: sqlite3.Connection, markets: Sequence[str]) -> bool:
  """게이트 1~6 을 **전부** 돌리고 하나라도 실패하면 False.

  ⚠️ ``and`` 로 단락(short-circuit)시키지 않는다. 첫 게이트가 실패해도 나머지를
  돌려야 **한 번에 전체 그림**을 본다 — 고치고 다시 돌리기를 다섯 번 반복하는 것과
  한 번에 다 보는 것은 다르다.
  """
  _ensure_schema(conn)
  _install_calendar(conn, _calendar(conn))
  results = [
    _gate1(conn, markets),
    _gate2(conn, markets),
    _gate3(conn, markets),
    _gate4(conn, markets),
    _gate5(conn),
    _gate6(conn, markets),
  ]
  # 편입규칙 민감도(6변형)는 **다시 계산하지 않는다.** 이름 기반 필터를 6벌 만들어
  # KOSPI 전 구간을 여섯 번 더 훑어야 하는데, 그 필터들은 §편입규칙의 결론
  # (스팩·리츠·인프라를 **포함**한다)에 따라 이 모듈에서 이미 폐기된 코드다.
  # 폐기한 규칙을 검증하려고 되살리면 '죽은 코드' 가 다시 생긴다.
  # 1회성 실측 결과는 설계 문서에 남아 있다(평균|오차|: 전종목 0.270% / 우선주만 제외
  # 0.066% / +리츠제외 0.167% / +인프라제외 0.230%).
  print("\n― 참고 ―")
  print("  편입규칙 민감도는 1회성 실측이라 verify 가 다시 계산하지 않는다.")
  print("  스팩·리츠·인프라펀드를 **빼면** 공식 대조 오차가 0.066% → 0.230% 로")
  print("  3.5배 악화한다 — 그래서 넣는다. 규칙을 바꾸려면 그 표부터 다시 만든다.")

  names = ("1 두 경로 일치", "2 공식 연말 종가", "3 레벨↔수익률",
           "4 경제적 상식", "5 기준 일관성", "6 상식 밖 상승")
  bad = [n for n, r in zip(names, results) if not r]
  print("\n― 검증 종합 ―")
  if bad:
    print(f"  ❌ **{len(bad)}개 게이트 실패** — {' · '.join(bad)}")
    print(f"     산식이나 데이터가 망가졌다. 종료코드 1 로 나간다.")
  else:
    print(f"  ✅ 게이트 {len(results)}개 전부 통과")
  return not bad


# ==================================================
# CLI
# ==================================================
def main(argv: Optional[List[str]] = None) -> int:
  p = argparse.ArgumentParser(
      prog="python -m collector.benchmark",
      description="벤치마크 지수 — 시장 전체를 하나의 수로 접는다")
  p.add_argument("mode", choices=["build", "status", "verify"],
                 help="build=다시 계산 · status=현황 · verify=독립 경로·공식값 대조")
  p.add_argument("--markets", help="대상 시장 (예: KOSPI,KOSDAQ). 생략하면 전 시장")
  p.add_argument("--variants",
                 help="대상 계열 (예: PR,TR). 생략하면 PR,TR,TRN,EW. "
                      "TRN 의 세율은 이 모듈이 정하지 않는다 — "
                      "price_total_return.tr_index_net 을 그대로 읽으므로 "
                      "세율을 바꾸려면 `total_return build --tax` 를 다시 돌린다")
  p.add_argument("--base", default=BASE_DT,
                 help=f"기준일. 이 날을 {BASE_LEVEL:.0f} 으로 둔다. 기본 {BASE_DT}")
  p.add_argument("--anchor", type=float,
                 help="공식 지수와 눈으로 맞출 때만. 기준일 레벨을 이 값으로 (예: 2175.17)")
  p.add_argument("--quiet", action="store_true")
  a = p.parse_args(argv)

  conn = db.connect()
  markets = [c.strip() for c in a.markets.split(",")] if a.markets else None
  variants = [c.strip() for c in a.variants.split(",")] if a.variants else None
  # 종료코드. **게이트가 실패하면 0 이 아니어야 한다** — 산식이 망가져도 늘 0 을
  # 돌려주면 CI·스크립트가 감지할 방법이 없다. 사람이 화면을 읽어야만 알 수 있는
  # 검증은 검증이 아니다.
  rc = 0
  try:
    if a.mode == "status":
      status(conn)
    elif a.mode == "verify":
      rc = 0 if verify(conn, markets or ["KOSPI", "KOSDAQ"]) else 1
    else:
      print("벤치마크 지수 계산 중 …")
      t = build(conn, markets, variants, base_dt=a.base,
                base_level=a.anchor or BASE_LEVEL, verbose=not a.quiet)
      print(f"  시장 {t['markets']:,} · 계열 {t['variants']:,} · 행 {t['rows']:,} "
            f"· 거래일 {t['days']:,}")
      if t["no_adjusted"]:
        print(f"  ⚠️ 수정주가가 없어 뺀 종목-일 {t['no_adjusted']:,} "
              f"— `python -m collector.preprocess` 를 먼저 돌린다")
      if t["no_tr"]:
        print(f"  ⚠️ TR 계열이 없어 뺀 종목-일 {t['no_tr']:,} "
              f"— `python -m collector.total_return build` 를 먼저 돌린다")
      if t["fixed"]:
        print(f"  🔧 주식수 사건 보정 {t['fixed']:,}건 "
              f"— 조정계수가 놓친 감자·병합을 시총비로 되돌렸다. 위 줄에 내역이 있다")
      if t["outlier"]:
        print(f"  ⚠️ 하루 ±60% 를 넘은 종목-일 {t['outlier']:,}건 "
              f"— **값은 그대로 넣었다**. 위 줄에 목록이 있다")
      if t["halted_moved"]:
        # ⚠️ 이 문구는 SQL 의 `hl_moved` 정의와 **방향이 같아야 한다.**
        #    SQL 은 `halted=1 AND 수정주가 비율 ≠ 1` 을 센다 — 즉 조정계수가
        #    그 움직임을 **흡수하지 못한** 날이다. 예전 문구("조정계수로 흡수했다")는
        #    정반대였고, 읽는 사람이 "그럼 괜찮은 거네" 하고 넘기게 만든다.
        print(f"  ⚠️ 거래가 없는데 수정주가가 움직인 종목-일 "
              f"{t['halted_moved']:,}건 — 거래소가 기준가를 다시 매긴 날이고, "
              f"조정계수가 그것을 **흡수하지 못했다**")
        print(f"     (그래서 그날 수익률이 0 이 아니다. 대부분 리츠·선박펀드의 "
              f"소액 재산정이라 영향은 작지만, 급증하면 원인을 봐야 한다)")
  finally:
    conn.close()
  return rc


if __name__ == "__main__":
  raise SystemExit(main())
