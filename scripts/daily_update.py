"""일일 데이터 갱신 — 시세·배당·파생 표를 최신으로 만들고 HF 에 증분으로 올린다.

이 파일이 답하는 질문은 하나다
------------------------------
**"아무도 기억하지 않아도 데이터가 매일 최신이 되려면 무엇이 돌아야 하는가."**

수집기의 각 단계(`collector/README.md §1` 의 1~7)는 이미 있다. 빠진 것은 **순서대로
이어 부르는 손**이었다. 사람이 세션마다 기억해서 돌리면 결국 안 돌린다 — 2026-09-28
확인 때 원격 스냅샷은 09-21, 로컬 시세는 09-22, 수정주가·TR·벤치마크는 09-17 에
멈춰 있었다. 단계마다 멈춘 날이 달랐던 것이 그 증거다.

그래서 이 러너는 **Windows 작업 스케줄러**에 올려 매일 한 번 돈다. Claude 세션·터미널·
앱 스택(Postgres·Redis)과 **아무 관계가 없다** — 세션이 끝나도, 스택이 꺼져 있어도 돈다.
Celery Beat(`app/celery_app.py`)에도 같은 일정이 있지만 그쪽은 스택이 떠 있을 때만
돈다(`collector/README.md §2` 의 "스택이 안 뜨는 날 시세를 통째로 놓친다" 와 같은 이유).

단계 — 앞 단계가 뒤 단계의 재료다
---------------------------------
::

    ① price         backfill recent         최근 14일의 빈 거래일을 채운다 (포털)
    ② dividend      dividend scan --recent 2  이번 달·지난달 배당 공시를 **다시** 훑는다 (DART)
    ②' calendar     market_calendar build   공휴일(특일 정보) → 거래일 달력 → 배당락일 다시 계산 → 금융 일정
                                            (2026-10-02 · 실패해도 뒤를 막지 않는다)
    ③ adjusted      preprocess              수정주가·조정 이벤트를 다시 계산
    ④ total_return  total_return build      ③+② → TR 계열
    ⑤ benchmark     benchmark build         ③+④ → 자체 재현 지수
    ⑥ manifest      manifest write          팀원 대조용 지문
    ⑦ export        hf_dataset export       바뀐 파티션만 파케이로        (--upload 일 때만)
    ⑧ verify        hf_dataset verify       지문·행수·스키마·값 게이트   (--upload 일 때만)
    ⑨ upload        hf_dataset upload --yes --incremental                 (--upload 일 때만)

· ② 가 `--recent` 인 이유 — `dividend scan` 은 다 훑은 달을 `done` 으로 찍고 다시 보지
  않는다. 09-19 에 훑은 2026-09 가 `done` 이면 그 뒤 9월 공시는 영원히 안 들어온다.
· ② 가 ③ 보다 **앞인** 이유 — 파생 단계(③④⑤)를 돌릴지는 ③ 직전에 한 번 판정한다.
  배당을 뒤에 두면 "시세는 그대로 · 배당만 새로 옴" 인 날 TR 이 건너뛰어진다. 배당 스캔은
  배당락일 계산에 시세 **달력**(`price_daily`)만 쓰므로 ① 뒤면 충분하다.
· ② 가 실패해도(DART 점검·한도) ③④⑤ 는 돈다 — 배당은 어제 것 그대로 두고 시세만이라도
  최신으로 만든다. ② 의 실패는 상태 파일에 🟡 로 남는다.
· ②' 가 ③ 보다 **앞인** 이유 — 배당락일은 거래일 달력으로 센 값이라, 달력이 바뀌면(내년 공휴일 발표 ·
  임시공휴일) 같은 배당의 배당락일이 옮겨 간다. 배당 지문(`snapshot` 의 dividend 넷째 값)이 배당락일을
  보므로 ②' 가 고친 날이 있으면 ③ 직전 판정이 TR 을 다시 만든다.
· ③④⑤ 는 **새 자료가 없으면 건너뛴다** — 같은 날 두 번 돌아도 CPU 를 태우지 않는다.
  판정은 `needs_derived()` 한 곳이다.
· ⑨ 는 **바뀐 파케이가 0개면 건너뛴다** — 안 그러면 내용 없는 커밋·태그가 매일 쌓인다.

원자료 공유 스위치 (`QURIOUS_RAW_SHARING`)
------------------------------------------
`hf_dataset.py` 는 이 스위치가 꺼져 있으면 원자료 표 내보내기·업로드를 멈춘다. 스위치는
**`.env` 로는 켜지지 않게** 설계돼 있다(실수로 켜진 채 남지 않게). 이 러너는 `--upload`
를 **명시적으로 준 실행에서만**, ⑦⑨ 자식 프로세스에게만 스위치를 켜서 넘긴다. 즉 켜는
결정은 작업 스케줄러에 등록된 **명령줄 자체**에 남는다(`status` 가 그 명령줄을 보여 준다).
private 확인·xet 확인 등 나머지 게이트는 `hf_dataset.upload()` 가 그대로 건다.

무엇을 하지 않는가
------------------
· **git 을 건드리지 않는다.** 커밋·push 없음. 산출물은 전부 gitignore 된 `data/` 아래다.
· **토큰·키를 출력하지 않는다.** 자식 프로세스 출력은 로그 파일로만 가고, 그 자식들이
  이미 토큰을 찍지 않는다(`hf_dataset._token` 머리말).
· **두 벌이 겹쳐 돌지 않는다.** 잠금 파일(`state/daily_update.lock`)에 PID 를 적는다.
  ⚠️ Windows 에서 `os.kill(pid, 0)` 은 살아 있는지 묻는 게 아니라 **그 프로세스를 죽인다**
  (TerminateProcess). 그래서 생존 확인은 `OpenProcess` 로 한다.

쓰는 법
-------
::

    python scripts/daily_update.py run              # 로컬 갱신만 (①~⑥)
    python scripts/daily_update.py run --upload     # + HF 증분 업로드 (⑦~⑨)
    python scripts/daily_update.py run --only news  # 그 단계 하나만 다시(예약 회차와 겹치는 시간에는 막힘)
    python scripts/daily_update.py run --manual --request <요청 번호>  # 화면 「전체 수집」 — PC 작업자가 부른다(11:00 ~ 13:30 막힘)
    python scripts/daily_update.py run --fill signals --from 2026-10-02 --to 2026-10-06  # 빠진 날 채우기(31일까지)
    python scripts/daily_update.py status           # 마지막 실행 결과 + 예약 상태
    python scripts/daily_update.py steps --write    # 단계 목록 · 이 PC 용량 파일을 지금 쓴다(앱이 읽는다)
    python scripts/daily_update.py install          # 작업 스케줄러에 매일 12:30 등록 (--upload 포함)
    python scripts/daily_update.py install --time 18:30 --no-upload
    python scripts/daily_update.py start            # 등록된 작업을 지금 한 번 돌린다(비동기)
    python scripts/daily_update.py uninstall        # 등록 해제

종료코드 — 0 성공 · 2 고를 수 없는 단계 · 받는 값이 틀림 · 3 앱 DB 꺼짐으로 건너뜀(한 단계 다시 · 채우기) · 75 막힘(12:30 회차와
겹침 · 다른 실행 — 나중에 다시 · EX_TEMPFAIL) · 78 앱 DB 주소를 만들지 못함(EX_CONFIG) · 124 시간 초과 · 그 밖 = 실패한 단계의
종료코드. 화면 수집 요청(`scripts/collect_worker.py`)은 75 를 「다시 기다림」 으로, 나머지를 결과로 읽는다(2026-10-10).

실패한 단계의 까닭(DF-101) — 단계 줄에 까닭 한 줄(``error`` · 그 단계 로그 구간의 마지막 예외 줄 · 경로 · 비밀값을 걸러 200자)과
로그 파일 이름(``log_name``)을 남긴다. 결과 줄이 「종료코드 1」 만 남아 로그를 열어야 까닭을 알던 것(2026-10-10 배당 · 기업 일정)을
고쳤다. 빠진 날(앱 DB 가 꺼져 신호가 건너뛴 거래일)은 ``state/daily_update_fill.json`` 에 모아 단계 줄에 「채울 날 n · 첫날 ·
마지막 날」 로 적고, ``run --fill`` 이 채운 날만 지운다(이틀 넘게 꺼졌던 때 · 2026-10-10 사용자 결정).

로그는 `data/collector/logs/daily_update-*.log`(최근 30개 보관), 마지막 결과는
`data/collector/state/daily_update_last.json`, 이력은 같은 폴더 `daily_update_history.jsonl`.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid
import zoneinfo
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, TextIO

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collector import config  # noqa: E402

KST = zoneinfo.ZoneInfo("Asia/Seoul")

TASK_NAME = "Qurious-daily-data-update"
DEFAULT_TIME = "12:30"

LOG_DIR = config.DATA_DIR / "logs"
LOCK_PATH = config.STATE_DIR / "daily_update.lock"
LAST_PATH = config.STATE_DIR / "daily_update_last.json"
HISTORY_PATH = config.STATE_DIR / "daily_update_history.jsonl"
#: 단계 목록(이름표 · 묶음 · 하는 일) — 회차마다 처음에 다시 쓴다. 앱은 이 파일과 회차 기록만 읽는다(결정 ④).
CATALOG_PATH = config.STATE_DIR / "daily_update_steps.json"
#: 이 PC 용량(드라이브 여유 · 수집 DB 크기) — 회차 끝에 잰다. 앱 컨테이너는 PC 디스크를 볼 수 없어 러너가 대신 잰다.
DISK_PATH = config.STATE_DIR / "pc_disk.json"
#: 도는 중의 지금 단계(몇 번째 · 이름표) — 단계를 시작할 때마다 다시 쓰고 끝나면 지운다(2026-10-08). 잠금 파일(다른 실행 막기)과
#: 따로 둔다 — 잠금을 고쳐 쓰다 실패하면 다른 실행을 막는 일이 흔들린다. 앱은 잠금의 시작 시각과 같은 실행일 때만 믿는다
#: (수집 일정 화면의 「수집 중 — n번째 단계」).
PROGRESS_PATH = config.STATE_DIR / "daily_update_progress.json"
#: 빠진 날 — 앱 DB 가 꺼져 건너뛴 거래일을 단계마다 모은다({"steps": {이름: {"days": [YYYY-MM-DD …]}}}). 회차 기록은 회차마다 새로
#: 쓰므로 여러 날 꺼졌던 때를 셀 수 없다 — 그래서 따로 둔다(2026-10-10). 정기 회차가 그날을 계산하면 그날만, 채우기가 범위를 돌면
#: 그 범위만 지운다(말없이 사라지지 않게).
FILL_PATH = config.STATE_DIR / "daily_update_fill.json"

#: 빠진 날 채우기 한 번의 범위 상한(일 · 양 끝 포함) — 사용자 결정 2026-10-10 「31일」. 앱은 단계 목록의 ``fill_max_days`` 로
#: 받아 쓴다(사본을 두지 않는다).
FILL_MAX_DAYS = 31
#: 채우기 시간 한도의 상한(분) — 한도는 범위의 평일 수 × 단계 한도로 늘고 여기서 멈춘다(막는 때도 이 한도로 센다).
FILL_TIMEOUT_CAP_MIN = 120
#: 실패한 단계의 까닭 한 줄 길이 상한(자) — 요청 결과 칸(300자)에 앞말과 함께 들어가게.
ERROR_LINE_MAX = 200

#: 로그 보관 개수. 하루 한 번이면 한 달치다.
KEEP_LOGS = 30

#: 잠금이 이보다 오래됐으면 PID 가 살아 있어도 멈춘 것으로 본다(작업 스케줄러 한도와 같다).
LOCK_STALE_HOURS = 4

#: 변화 감지에 쓰는 되돌아보기 창. `backfill.RECENT_WINDOW`(14일)보다 넉넉히 잡는다.
SNAPSHOT_WINDOW_DAYS = 31


@dataclass
class Step:
    name: str
    args: List[str]
    timeout_min: int
    fatal: bool = True          # 실패하면 뒤 단계를 멈추는가
    derived: bool = False       # 새 자료가 없으면 건너뛰는 파생 단계인가
    upload: bool = False        # --upload 일 때만 도는가
    sharing: bool = False       # 원자료 공유 스위치를 켜서 넘기는가
    # 화면에 보이는 이름표 · 묶음 · 하는 일 — **여기 한 곳에만 둔다**(2026-10-07 · 결정 ④). 러너가 회차 기록과 단계 목록
    # 파일(``CATALOG_PATH``)에 함께 쓰고, 앱(``app/services/data_status.py``)은 그 기록만 읽는다 — 단계를 더하면 화면이 따라온다.
    label: str = ""
    group: str = ""
    desc: str = ""
    # 앱 DB(PostgreSQL)를 쓰는 단계인가 — 그런 단계에만 PC 쪽 주소를 넘긴다(``host_app_db_env`` · 2026-10-08 신호 단계).
    app_db: bool = False
    # 빠진 날을 채우는 명령(날짜 칸은 YYYY-MM-DD 그대로) — 회차가 그날을 놓쳤을 때 사람이 돌린다. 단계 목록에 실려 수집 일정
    # 화면이 그 단계에만 보인다(2026-10-08 · #142 답글 「앱 DB 가 꺼진 날은 --from · --to 로 채운다」).
    fill: str = ""
    # 빠진 날 채우기 인자 — ``{from}`` · ``{to}`` 자리에 날짜를 넣어 ``run --fill`` 이 돌린다(2026-10-10 · 화면 「빠진 날 채우기」).
    # 이것이 있는 단계만 채우기를 받고, 명령 글(``fill``)도 여기서 만든다 — 명령 글과 실제 인자가 두 곳에서 갈라지지 않게.
    fill_args: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.fill_args and not self.fill:
            shown = [a.replace("{from}", "YYYY-MM-DD").replace("{to}", "YYYY-MM-DD") for a in self.fill_args]
            self.fill = "python " + " ".join(shown)


#: 단계 묶음 — 화면이 이 차례로 머리를 단다(단계는 묶음 안에서 러너 차례 그대로).
GROUPS: List[Dict[str, str]] = [
    {"key": "받기", "note": "출처에서 새 자료를 받는다"},
    {"key": "계산", "note": "받은 자료로 새 표를 만든다"},
    {"key": "백업", "note": "Hugging Face 데이터셋으로 올린다"},
    {"key": "근거 문서", "note": "근거 답이 쓰는 법령을 대조한다"},
]

STEPS: List[Step] = [
    Step("price", ["-m", "collector.backfill", "recent", "--quiet"], 30,
         label="시세", group="받기", desc="최근 거래일 시세를 받아 빈 날을 메운다"),
    Step("dividend", ["-m", "collector.dividend", "scan", "--recent", "2", "--quiet"], 60,
         fatal=False, label="배당", group="받기", desc="최근 두 달 배당 공시를 다시 훑어 배당 기록을 고친다"),
    # 공시 · 재무 · 검색 색인(2026-10-04 · 목표 기능 ① W7) — 시세와 무관하고 실패해도 기존 단계를 막지 않는다.
    # 공시 목록(최근 3일 · 유형 A~J × 시장 3 · 약 40회) → 새 정기보고서 · 정정본의 재무 → 이름표 · 낱말 색인(바뀐 것만).
    # 달력(③-②) **앞에** 둔다 — 실적 · 주총 일정을 공시 목록에서 만든다.
    Step("disclosure", ["-m", "collector.disclosure", "daily", "--quiet"], 15, fatal=False,
         label="공시", group="받기", desc="전자공시(DART) 최근 3일 상장사 공시 목록"),
    Step("financial", ["-m", "collector.financials", "daily", "--quiet"], 15, fatal=False,
         label="재무", group="받기", desc="새 정기보고서 · 정정본의 재무 주요계정"),
    # 주주총회 · 배당금 지급 일정(2026-10-05) — 최근 60일 소집결의 본문(새 것만 · 하루 수십 회) → 날짜 읽기. 달력 앞.
    Step("schedule", ["-m", "collector.corp_schedule", "daily", "--quiet"], 15, fatal=False,
         label="기업 일정", group="받기", desc="주주총회 · 배당금 지급 같은 기업 일정"),
    # 정책브리핑 정책뉴스(2026-10-05) — 오늘까지 3일 창 한 번(공공데이터포털 · 하루 1,000회). 이름표 · 색인 앞.
    Step("news", ["-m", "collector.policy_news", "daily", "--quiet"], 10, fatal=False,
         label="정책뉴스", group="받기", desc="정책브리핑 정책뉴스 — 공공누리 제1유형만 본문"),
    # 언론사 기사 메타데이터(2026-10-05) — GDELT 번역 GKG 15분 파일(지난 30시간 · 아직 안 읽은 것 · 하루 약 96파일 · 550MB)에서
    # 한국어 원문 기사의 제목 · 주소 · 시각 · 언론사만. 본문은 받지 않는다.
    Step("gdelt", ["-m", "collector.gdelt_news", "daily", "--quiet"], 30, fatal=False,
         label="언론사 기사", group="받기", desc="제목 · 링크 · 시각 · 언론사만(본문은 받지 않는다)"),
    Step("search", ["-m", "collector.search_index", "build", "--quiet"], 15, fatal=False,
         label="검색 색인", group="계산", desc="수집 자료 검색 색인 — 바뀐 것만 다시 짓는다"),
    # 거래일 달력 · 금융 일정(2026-10-02) — 공휴일 받기 → 달력 → 배당락일 다시 계산 → 일정.
    # 파생 판정(③ 직전) **앞에** 둔다 — 배당락일이 바뀌면 배당 지문이 바뀌어 TR 을 다시 만든다.
    Step("calendar", ["-m", "collector.market_calendar", "build", "--quiet"], 10, fatal=False,
         label="시장 달력", group="계산", desc="휴장일 · 거래일 달력 · 배당락일 · 금융 일정"),
    Step("adjusted", ["-m", "collector.preprocess"], 30, derived=True,
         label="수정주가", group="계산", desc="분할 · 병합 · 배당을 반영해 과거 가격을 고친다(새 자료가 없으면 건너뜀)"),
    Step("total_return", ["-m", "collector.total_return", "build", "--quiet"], 30,
         derived=True, label="총수익", group="계산", desc="배당을 다시 투자한 총수익(TR) 지수"),
    Step("benchmark", ["-m", "collector.benchmark", "build", "--quiet"], 30, derived=True,
         label="벤치마크", group="계산", desc="수정주가 · TR 로 다시 만든 지수 — 비교 기준"),
    # OHLCV 규격 자료(2026-10-01) — ETF · 지수 일봉 · 분봉 · krx-ohlcv 내보내기. 실패해도 기존 단계를 막지 않는다.
    Step("ohlcv", ["-m", "collector.ohlcv_load", "daily"], 40, fatal=False,
         label="일봉", group="계산", desc="ETF · 지수 일봉과 분봉을 받아 묶음으로 적재 · 내보내기"),
    # 다중 주기 신호(2026-10-08 · 팀원 #140 배치 · #142 요청) — 그날 일봉 · 60분봉이 들어온 **뒤**에 돈다. 인자 없이 수집 DB 의
    # 마지막 거래일 하루를 계산해 앱 DB(PostgreSQL)의 T2 `signal_snapshots` 에 쓴다(같은 날은 값만 바뀐다 — 여러 번 돌려도 안전).
    # 수집 DB 는 읽기 전용으로 연다. 배치 코드는 목표 기능 ② 주담당 것이라 여기서는 부르기만 한다.
    Step("signals", ["scripts/signals_daily.py"], 10, fatal=False, app_db=True,
         label="신호", group="계산", desc="분봉 유니버스 401종목의 다중 주기 신호를 T2 에 기록",
         fill_args=["scripts/signals_daily.py", "--from", "{from}", "--to", "{to}"]),
    Step("manifest", ["-m", "collector.manifest", "write"], 10, fatal=False,
         label="목록표", group="백업", desc="백업할 표 · 행 수 · 지문 목록(대조용)"),
    Step("export", ["scripts/hf_dataset.py", "export", "--quiet"], 30,
         upload=True, sharing=True, label="내보내기", group="백업", desc="바뀐 표를 파케이 파일로 내보낸다"),
    Step("verify", ["scripts/hf_dataset.py", "verify"], 30, upload=True,
         label="대조", group="백업", desc="행 수 · 지문 · 형식 · 값 대조"),
    Step("upload", ["scripts/hf_dataset.py", "upload", "--yes", "--incremental"], 60,
         upload=True, sharing=True, label="올리기", group="백업", desc="시세 데이터셋에 바뀐 조각만 올린다"),
    Step("ohlcv_upload", ["scripts/hf_ohlcv.py", "upload", "--yes"], 30,
         fatal=False, upload=True, sharing=True, label="일봉 올리기", group="백업", desc="일봉 · 분봉 데이터셋에 올린다"),
    # 섹터별 · 연도별 근거 법령(2026-10-05) — 7일에 한 번만 실제로 돈다(판 목록 대조 → 바뀐 해만 본문 → 내보내기 → 바뀌었으면
    # HF kb-sector-laws 에 올리고 받아서 대조). 그 밖의 날은 「건너뜀」 한 줄. 실패해도 다른 단계를 막지 않는다.
    Step("sector_laws", ["scripts/hf_sector_laws.py", "weekly", "--yes", "--quiet"], 40,
         fatal=False, upload=True, sharing=True,
         label="섹터 법령", group="근거 문서", desc="섹터별 근거 법령 — 7일에 한 번 개정 대조"),
]


# ==================================================
# 1. 작은 도구
# ==================================================
def now_kst() -> datetime.datetime:
    return datetime.datetime.now(KST)


def _iso(t: datetime.datetime) -> str:
    return t.isoformat(timespec="seconds")


def _write_json_atomic(path: Path, obj: Dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def write_progress(started: datetime.datetime, step: "Step", run: Optional["Run"] = None) -> None:
    """지금 단계를 진행 파일에 적는다 — 몇 번째(단계 목록 차례 · 1부터) · 모두 몇 · 이름 · 이름표.

    못 쓰면 회차를 멈추지 않고 로그에 한 줄 남긴다(화면의 「n번째」 만 빠지고 수집은 그대로다).
    """
    index = next((i for i, s in enumerate(STEPS, 1) if s.name == step.name), 0)
    try:
        _write_json_atomic(PROGRESS_PATH, {"started_at": _iso(started), "at": _iso(now_kst()),
                                           "step": {"index": index, "total": len(STEPS), "name": step.name,
                                                    "label": step.label or step.name}})
    except OSError as e:
        if run is not None:
            run.say(f"🟡 진행 파일을 쓰지 못했다 — {e}")


def clear_progress() -> None:
    """진행 파일을 지운다. 지우지 못해도 해가 없다 — 앱은 잠금과 시작 시각이 같은 실행의 진행 파일만 읽는다."""
    try:
        PROGRESS_PATH.unlink(missing_ok=True)
    except OSError:
        pass


def pid_alive(pid: int) -> bool:
    """그 PID 의 프로세스가 아직 살아 있는가. **죽이지 않고** 묻는다."""
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_ulong()
        ok = kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        kernel32.CloseHandle(handle)
        return bool(ok) and code.value == 259               # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def lock_holder(path: Path = LOCK_PATH, *, now: Optional[datetime.datetime] = None) -> Optional[str]:
    """잠금을 쥔 실행이 살아 있으면 그 까닭 한 줄, 아니면 None — **읽기만** 한다(지우지 않는다).

    ① PID 가 죽었거나 ② ``LOCK_STALE_HOURS`` 보다 오래된 잠금은 쥔 것이 아니다 — ``acquire_lock`` 이 치우고 다시 잡는 그
    판정 그대로다. 화면 수집 요청 작업자가 요청을 가져가기 전에 「지금 다른 실행이 도나」 만 묻는다(2026-10-10). 경로는
    부르는 쪽이 넘긴다(기본값은 정의할 때 묶이니 시험이 경로를 바꾸면 넘겨야 한다).
    """
    now = now or now_kst()
    try:
        held = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        held = {}
    pid = int(held.get("pid") or 0)
    try:
        since = datetime.datetime.fromisoformat(held.get("started_at", ""))
    except ValueError:
        since = None
    old = since is None or (now - since).total_seconds() > LOCK_STALE_HOURS * 3600
    if pid_alive(pid) and not old:
        return f"다른 실행이 돌고 있다 (PID {pid} · {held.get('started_at')} 시작)"
    return None


def acquire_lock(path: Path = LOCK_PATH, *, now: Optional[datetime.datetime] = None) -> Optional[str]:
    """잠금을 잡는다. 잡으면 None, 못 잡으면 그 이유 한 줄.

    ``O_EXCL`` 로 만들어 두 프로세스가 동시에 잡는 일이 없다. 남은 잠금은 ① PID 가
    죽었거나 ② ``LOCK_STALE_HOURS`` 보다 오래됐으면 치우고 다시 잡는다(판정은 ``lock_holder`` 한 곳).
    """
    now = now or now_kst()
    path.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(2):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            busy = lock_holder(path, now=now)
            if busy:
                return busy
            path.unlink(missing_ok=True)                    # 죽었거나 너무 오래된 잠금
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"pid": os.getpid(), "started_at": _iso(now)}, f)
        return None
    return "잠금을 잡지 못했다 (치운 직후 다른 실행이 먼저 잡았다)"


def release_lock(path: Path = LOCK_PATH) -> None:
    try:
        held = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if int(held.get("pid") or 0) == os.getpid():
        path.unlink(missing_ok=True)


#: 앱 DB 주소의 정본 — compose 의 앱 서비스 환경(DATABASE_URL)과 그 DB 서비스의 포트 짝.
COMPOSE_PATH = ROOT / "docker-compose.yml"

#: 러너가 정하는 종료코드 — 앱 DB 주소를 compose 에서 만들지 못해 앱 DB 단계를 돌리지 않았다(sysexits 의 EX_CONFIG).
#: 시간 초과의 124 처럼 러너가 적는 코드라, 앱은 해석을 바꾸지 않아도 「경고」 로 보인다. 설정 결함은 건너뜀으로 숨기지 않는다.
EX_CONFIG = 78

#: 러너가 정하는 종료코드 — 「지금은 돌 수 없다, 나중에 다시」(sysexits 의 EX_TEMPFAIL). 한 단계 다시 · 수동 전체 수집이 12:30
#: 회차와 겹치거나 다른 실행이 도는 동안 돌리지 않고 이 번호로 끝난다(2026-10-10 · 화면 수집 단추). 옛 번호 3 은 단계가 스스로
#: 내는 3(달력의 공휴일 받기 실패 · 앱 DB 꺼짐 건너뜀)과 겹쳐, 작업자가 「기다림」 과 「경고」 를 가를 수 없었다(2026-10-07 깨 보기
#: 에서도 시험 단계의 3 이 막힘 3 과 겹쳐 검사를 꺼도 시험이 통과했다).
EX_TEMPFAIL = 75


def host_app_db_env(compose: Optional[Path] = None) -> tuple:
    """PC(호스트)에서 도는 단계가 앱 DB 를 부를 환경 변수 — ``({"DATABASE_URL": …}, 못 만든 까닭 또는 None)``.

    컨테이너끼리는 서비스 이름(``postgres:5432``)으로 부르지만 PC 에서는 compose 가 연 포트(``15432``)로 불러야 한다. 앱 설정
    (``app/config.py``)은 ENV_FILE 이 없으면 ``.env.dev`` 를 읽고, 컨테이너가 받는 주소는 compose 의 environment 에만 있다 —
    2026-10-08 러너로 신호 단계를 돌리자 앱 DB 가 떠 있는데도 ``ConnectionRefusedError`` 로 끝났다. 주소를 여기 한 번 더 적지
    않고 compose 에서 만든다(개발 모드 스크립트 ``scripts/personal/dev.ps1`` 3단계와 같은 값 — TC-DU 가 맞댄다). 호스트 이름은
    ``127.0.0.1``(이 PC 에서 ``localhost`` 는 요청마다 1초 — DF-63). 못 만들면 빈 값과 까닭을 돌려준다(러너가 로그에 적는다).
    """
    from urllib.parse import urlsplit, urlunsplit

    import yaml

    path = compose or COMPOSE_PATH
    try:
        services = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("services") or {}
    except (OSError, yaml.YAMLError) as e:
        return {}, f"compose 를 읽지 못했다 — {type(e).__name__}"
    env = (services.get("app") or {}).get("environment") or {}
    if isinstance(env, list):                                # `- KEY=값` 꼴과 `KEY: 값` 꼴 둘 다
        env = dict(x.split("=", 1) for x in env if isinstance(x, str) and "=" in x)
    url = env.get("DATABASE_URL")
    if not url:
        return {}, "compose 의 앱 서비스에 DATABASE_URL 이 없다"
    u = urlsplit(url)
    svc = services.get(u.hostname or "") or {}
    want = str(u.port or 5432)
    host_port = None
    for p in svc.get("ports") or []:                         # "15432:5432" · "127.0.0.1:15432:5432/tcp" · 긴 꼴(사전)
        if isinstance(p, dict):
            if str(p.get("target")) == want and p.get("published"):
                host_port = str(p["published"])
            continue
        parts = str(p).split("/")[0].split(":")
        if len(parts) >= 2 and parts[-1] == want:
            host_port = parts[-2]
    if not host_port:
        return {}, f"compose 의 {u.hostname} 서비스에 {want} 포트를 PC 로 여는 짝이 없다"
    auth = u.netloc.rsplit("@", 1)[0] + "@" if "@" in u.netloc else ""
    return {"DATABASE_URL": urlunsplit((u.scheme, f"{auth}127.0.0.1:{host_port}", u.path, u.query, u.fragment))}, None


def _db_where(url: str) -> str:
    """로그용 — 비밀번호 없이 호스트:포트/DB 만."""
    from urllib.parse import urlsplit
    u = urlsplit(url)
    return f"{u.hostname}:{u.port}{u.path}"


def app_db_unreachable(env: Dict[str, str], timeout: float = 3.0) -> Optional[str]:
    """앱 DB 포트에 닿는가 — 닿으면 None, 아니면 까닭 한 줄(연결 거부 · 시간 초과 …).

    「돌다가 실패」 와 「돌 조건이 없어 돌지 않음」 을 가르려고 돌리기 **전에** 묻는다(2026-10-08 · 조사서 안 B — Airflow 의
    skipped/failed · systemd 의 ExecCondition 과 같은 생각). 종료코드 3 만 보고 건너뜀으로 바꾸면 「DB 는 떠 있는데 주소 ·
    계정이 틀림」(그날 실측)도 건너뜀 뒤에 숨는다. 포트가 열렸는데 단계가 실패하면 그때는 경고다.
    """
    import socket
    from urllib.parse import urlsplit

    u = urlsplit(env.get("DATABASE_URL", ""))
    try:
        with socket.create_connection((u.hostname or "", u.port or 5432), timeout=timeout):
            return None
    except socket.timeout:                                   # OSError 의 하위라 먼저 잡는다
        return f"{timeout:g}초 안에 답이 없다"
    except ConnectionRefusedError:
        return "연결 거부"
    except OSError as e:
        return type(e).__name__


def _as_of_day() -> Optional[str]:
    """그 회차가 계산했을 거래일 — 지금 시세 마지막 날(YYYY-MM-DD). 못 재면 None(건너뜀 줄의 「빠진 날」 표시에만 쓴다)."""
    try:
        p = (snapshot() or {}).get("price_max")
    except (sqlite3.Error, OSError):
        return None
    return f"{p[:4]}-{p[4:6]}-{p[6:8]}" if isinstance(p, str) and len(p) == 8 else None


def child_python() -> str:
    """자식 프로세스용 파이썬. 작업 스케줄러는 창이 안 뜨는 ``pythonw`` 로 이 러너를
    부르는데, 자식까지 ``pythonw`` 면 표준출력이 없어 로그가 빈다 → 같은 폴더의 ``python``."""
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe":
        cand = exe.with_name("python.exe")
        if cand.exists():
            return str(cand)
    return str(exe)


# ==================================================
# 1-2. 단계 목록 · 이 PC 용량 — 앱이 읽는 기록 파일
# ==================================================
def step_catalog(now: Optional[datetime.datetime] = None) -> Dict:
    """화면이 그리는 단계 목록 — 이름표 · 묶음 · 하는 일과 실패 · 건너뛰기 성질. 러너 ``STEPS`` 차례 그대로.

    ``guards`` 는 화면 실행을 막는 때(2026-10-10) — ``guard_window`` 로 센 시각 그대로. 앱은 단추를 미리 끄고 까닭을 보이는 데만
    쓰고(앱 이미지에는 scripts/ 가 없다), 판정은 작업자 · 러너가 같은 함수로 다시 한다.
    """
    now = now or now_kst()
    return {
        "written_at": _iso(now),
        "guards": guards(now),
        "fill_max_days": FILL_MAX_DAYS,                     # 채우기 한 번의 범위 상한 — 앱은 이 값을 받아 쓴다(사본 없음)
        "schedule": DEFAULT_TIME,
        "groups": GROUPS,
        "steps": [{"name": s.name, "label": s.label, "group": s.group, "desc": s.desc,
                   "fatal": s.fatal, "derived": s.derived, "upload": s.upload,
                   "timeout_min": s.timeout_min, "fill": s.fill} for s in STEPS],
    }


def _rec(step: Step) -> Dict:
    """회차 기록의 단계 한 줄 — 이름표 · 묶음 · 하는 일을 함께 적는다(그 회차에 화면이 무엇을 보였어야 하나가 남는다)."""
    return {"name": step.name, "label": step.label, "group": step.group, "desc": step.desc,
            "fatal": step.fatal, "rc": None, "seconds": 0.0, "note": ""}


def _compact(recs: List[Dict]) -> List[Dict]:
    """이력 줄(JSONL)에 남길 단계 결과 — 이름표는 단계 목록 파일에 있으니 이름 · 종료코드 · 시간 · 메모만.
    건너뛴 줄의 까닭 · 뒤 할 일 · 거래일은 있을 때만 붙인다(지난 회차도 같은 색으로 그리게 · 2026-10-08).
    빠진 날(채울 날 · 첫날 · 마지막 날) · 실패한 단계의 까닭 · 로그 파일 이름도 있을 때만(2026-10-10 · DF-101)."""
    out = []
    for r in recs:
        row = {"name": r["name"], "rc": r.get("rc"), "seconds": r.get("seconds") or 0.0, "note": r.get("note") or ""}
        row.update({k: r[k] for k in ("reason", "followup", "date", "fill_from", "fill_to", "fill_days", "fill_rest",
                                      "error", "log_name") if r.get(k)})
        out.append(row)
    return out


def measure_disk(now: Optional[datetime.datetime] = None, db_path: Optional[Path] = None) -> Dict:
    """이 PC 의 드라이브 여유와 수집 DB 크기(본 파일 + -wal · -shm). 앱 컨테이너는 PC 디스크를 볼 수 없다."""
    db = db_path or config.DB_PATH
    usage = shutil.disk_usage(db.parent if db.parent.exists() else ROOT)
    parts = [db, db.with_name(db.name + "-wal"), db.with_name(db.name + "-shm")]
    return {"measured_at": _iso(now or now_kst()), "drive": (ROOT.drive or "/"),
            "free_bytes": usage.free, "total_bytes": usage.total,
            "collector_db_bytes": sum(p.stat().st_size for p in parts if p.exists())}


def write_side_files() -> List[str]:
    """단계 목록 · 이 PC 용량 파일을 쓴다. 실패해도 회차를 막지 않게 까닭만 돌려준다."""
    errors: List[str] = []
    for path, make in ((CATALOG_PATH, step_catalog), (DISK_PATH, measure_disk)):
        try:
            _write_json_atomic(path, make())
        except Exception as e:                              # 기록 파일 하나 때문에 갱신이 멈추면 안 된다
            errors.append(f"{path.name}: {type(e).__name__}: {e}")
    return errors


# ==================================================
# 1-3. 실패한 단계의 까닭(DF-101) · 빠진 날(2026-10-10)
# ==================================================
#: 파이썬 예외 줄 — 「모듈.경로.이름Error: 글」(줄 머리부터 · 들여쓴 줄은 Traceback 의 몸통이다)
_EXC_LINE = re.compile(r"^(?:[A-Za-z_]\w*\.)*([A-Za-z_]\w*(?:Error|Exception|Exit|Interrupt|Timeout|Warning))(?::\s*(.*))?$")
#: 걸러 낼 것 — 차례가 뜻이 있다(주소의 물음표 뒤 → 주소의 계정 → 경로 → 「키 = 값」 → 긴 토큰)
_SCRUB = [
    (re.compile(r"(\b[a-z][a-z0-9+.-]*://[^\s?#]*)[?#]\S*", re.I), r"\1"),                 # 주소의 물음표 뒤(키가 거기 실린다)
    (re.compile(r"(\b[a-z][a-z0-9+.-]*://)[^\s/@]+@", re.I), r"\1"),                       # 주소 안 계정 · 비밀번호
    (re.compile(r"\b[A-Za-z]:[\\/](?:[^\\/\s]+[\\/])*([^\\/\s]+)"), r"\1"),             # 이 PC 경로 → 파일 이름
    (re.compile(r"(?<![\w:/.])/(?:[^/\s]+/)+([^/\s]+)"), r"\1"),                            # 리눅스 경로 → 파일 이름
    (re.compile(r"(?i)\b([\w-]*(?:key|token|secret|passw(?:or)?d|pwd|auth|crtfc)[\w-]*)(\s*[=:]\s*)\S+"), r"\1\2***"),
    (re.compile(r"\b[A-Za-z0-9_-]{32,}\b"), "***"),                                          # 긴 토큰 · 키
]
_FAIL_MARK = re.compile(r"🔴|실패|오류")


def scrub_line(text: str) -> str:
    """화면 · 요청 결과에 나가는 한 줄 — 경로는 파일 이름만 · 주소는 물음표 뒤와 계정을 떼고 · 비밀값 · 긴 토큰은 *** ·
    빈칸을 하나로 · ``ERROR_LINE_MAX`` 자를 넘으면 자르고 「…」."""
    out = text
    for pat, rep in _SCRUB:
        out = pat.sub(rep, out)
    out = " ".join(out.split())
    return out if len(out) <= ERROR_LINE_MAX else out[:ERROR_LINE_MAX - 1] + "…"


def failure_line(text: str) -> str:
    """실패한 단계 로그 구간에서 까닭 한 줄 — 마지막 예외 줄(모듈 경로는 뗀다) · 없으면 실패 표시 줄(🔴 · 실패 · 오류) · 그것도
    없으면 마지막 줄. 2026-10-10 배당 · 기업 일정이 DART 점검으로 멈췄을 때 결과 줄이 「종료코드 1」 뿐이라 로그를 열어야 했다."""
    lines = [ln.rstrip() for ln in (text or "").splitlines() if ln.strip()]
    if not lines:
        return ""
    for ln in reversed(lines):
        m = _EXC_LINE.match(ln)
        if m:
            return scrub_line(f"{m.group(1)}: {m.group(2)}" if m.group(2) else m.group(1))
    red = next((ln for ln in reversed(lines) if "🔴" in ln), None)       # 수집기는 멈추는 까닭을 🔴 로 적는다
    mark = red or next((ln for ln in reversed(lines) if _FAIL_MARK.search(ln)), None)
    return scrub_line((mark or lines[-1]).strip())


def _log_mark(run: "Run") -> int:
    """그 단계 로그 구간의 시작 — 지금 로그 파일 크기(바이트). 자식이 같은 파일에 이어 쓴다."""
    run.log.flush()
    try:
        return run.log_path.stat().st_size
    except OSError:
        return 0


def step_failure(run: "Run", step: Step, rc: int, mark: int, timeout_min: Optional[int] = None) -> Dict[str, str]:
    """실패한 단계 줄에 붙일 칸 — 까닭 한 줄(``error``)과 로그 파일 이름(``log_name`` · 경로 없이). 성공이면 빈 dict."""
    if rc == 0:
        return {}
    if rc == 124:
        why = f"시간 한도 {timeout_min or step.timeout_min}분을 넘겨 멈춤"
    else:
        run.log.flush()
        try:
            with run.log_path.open("rb") as f:                # 끝 64KB 만 — 긴 단계 로그를 통째로 읽지 않는다
                f.seek(0, os.SEEK_END)
                end = f.tell()
                f.seek(max(mark, end - 65536))
                text = f.read().decode("utf-8", errors="replace")
            # 러너가 단계 앞에 적는 머리(▶ 단계: 명령 · ==== 줄)는 까닭이 아니다 — 자식이 아무것도 찍지 않고 끝났을 때
            # 명령 줄이 까닭으로 잡히지 않게
            why = failure_line("\n".join(ln for ln in text.splitlines()
                                         if not ln.startswith("▶ ") and set(ln.strip()) != {"="}))
        except OSError:
            why = ""
        why = why or f"종료코드 {rc}"
    return {"error": why, "log_name": run.log_path.name}


def load_fill() -> Dict[str, List[str]]:
    """단계마다 빠진 날(차례대로) — 파일이 없거나 깨졌으면 빈 dict(회차를 막지 않는다)."""
    try:
        raw = json.loads(FILL_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out: Dict[str, List[str]] = {}
    for name, v in ((raw or {}).get("steps") or {}).items():
        days = sorted({d for d in (v or {}).get("days") or [] if isinstance(d, str) and len(d) == 10})
        if days:
            out[name] = days
    return out


def save_fill(days: Dict[str, List[str]]) -> None:
    _write_json_atomic(FILL_PATH, {"updated_at": _iso(now_kst()),
                                   "steps": {n: {"days": sorted(set(d))} for n, d in days.items() if d}})


def fill_fields(days: List[str]) -> Dict[str, object]:
    """단계 줄에 적을 빠진 날 — 뒤 할 일 ``fill`` · 첫날 · 마지막 날 · 날 수. 채우기 한 번은 ``FILL_MAX_DAYS`` 일까지라
    첫날부터 그 안의 날만 한 묶음으로 적고, 남은 날 수는 ``fill_rest`` 로(그 묶음을 채우면 다음 묶음이 나온다)."""
    days = sorted(set(days))
    if not days:
        return {}
    first = datetime.date.fromisoformat(days[0])
    edge = (first + datetime.timedelta(days=FILL_MAX_DAYS - 1)).isoformat()
    chunk = [d for d in days if d <= edge]
    out: Dict[str, object] = {"followup": "fill", "fill_from": chunk[0], "fill_to": chunk[-1], "fill_days": len(chunk)}
    if len(days) > len(chunk):
        out["fill_rest"] = len(days) - len(chunk)
    return out


def _fill_note(f: Dict[str, object]) -> str:
    if not f:
        return ""
    rest = f" · 다음 묶음 {f['fill_rest']}일" if f.get("fill_rest") else ""
    return f"채울 날 {f['fill_days']} · {f['fill_from']} ~ {f['fill_to']}{rest}"


def _apply_fill(rec: Dict, days: List[str]) -> None:
    """단계 줄에 남은 빠진 날을 적는다 — 칸(뒤 할 일 · 첫날 · 마지막 날 · 날 수)과 메모 한 마디. 남은 날이 없으면 그대로."""
    f = fill_fields(days)
    if f:
        rec.update(f)
        rec["note"] = " · ".join(x for x in (rec.get("note"), _fill_note(f)) if x)


def _save_fill(run: "Run", pending: Dict[str, List[str]]) -> None:
    try:
        save_fill(pending)
    except OSError as e:                                    # 파일 하나 때문에 회차를 멈추지 않는다 — 까닭은 로그에
        run.say(f"🟡 빠진 날 파일을 쓰지 못했다 — {type(e).__name__}: {e}")


def _parse_day(s: Optional[str]) -> Optional[datetime.date]:
    if not isinstance(s, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return None
    try:
        return datetime.date.fromisoformat(s)
    except ValueError:
        return None


def fill_range_error(step: Step, d_from: Optional[str], d_to: Optional[str], today: datetime.date) -> Optional[str]:
    """빠진 날 채우기의 받는 값 — 되면 None, 아니면 까닭 한 줄. 채우기 인자가 있는 단계 · 날짜 꼴 · 첫날 ≤ 마지막 날 ·
    마지막 날 ≤ 오늘 · ``FILL_MAX_DAYS`` 일 안(양 끝 포함). 작업자 · 러너가 같은 함수로 본다."""
    if not step.fill_args:
        return f"{step.label or step.name} 단계는 빠진 날 채우기를 하지 않는다(채우기 인자가 없다)"
    a, b = _parse_day(d_from), _parse_day(d_to)
    if a is None or b is None:
        return f"날짜는 YYYY-MM-DD 꼴로 둘 다 준다 — 첫날 {d_from or '없음'} · 마지막 날 {d_to or '없음'}"
    if a > b:
        return f"첫날({d_from})이 마지막 날({d_to})보다 뒤다"
    if b > today:
        return f"마지막 날({d_to})이 오늘({today.isoformat()})보다 뒤다"
    if (b - a).days + 1 > FILL_MAX_DAYS:
        return f"한 번에 {FILL_MAX_DAYS}일까지 채운다 — {d_from} ~ {d_to} 는 {(b - a).days + 1}일"
    return None


def _weekdays(a: datetime.date, b: datetime.date) -> int:
    return sum(1 for i in range((b - a).days + 1) if (a + datetime.timedelta(days=i)).weekday() < 5)


def fill_timeout_min(step: Step, d_from: str, d_to: str) -> int:
    """채우기 시간 한도(분) — 범위의 평일 수(휴장일은 모른다 · 넉넉한 쪽) × 단계 한도 · ``FILL_TIMEOUT_CAP_MIN`` 에서 멈춘다."""
    a, b = _parse_day(d_from), _parse_day(d_to)
    n = _weekdays(a, b) if a and b and a <= b else 1
    return min(FILL_TIMEOUT_CAP_MIN, max(1, n) * step.timeout_min)


def fill_timeout_cap(step: Step) -> int:
    """가장 긴 범위(``FILL_MAX_DAYS`` 일 · 평일이 가장 많은 꼴)의 시간 한도 — 단계 목록의 채우기 막는 때가 이 값으로 센다."""
    most = (FILL_MAX_DAYS // 7) * 5 + min(5, FILL_MAX_DAYS % 7)
    return min(FILL_TIMEOUT_CAP_MIN, most * step.timeout_min)


def fill_blocked(step: Step, d_from: str, d_to: str, now: datetime.datetime) -> Optional[str]:
    """채우기를 돌려도 되는가 — 안 되면 까닭 한 줄. 한 단계 다시와 같은 막는 때를 그 범위의 시간 한도로 센다."""
    limit = fill_timeout_min(step, d_from, d_to)
    lo, hi = guard_window(limit, now)
    if lo <= now <= hi:
        return (f"{lo.strftime('%H:%M')} ~ {hi.strftime('%H:%M')} 에는 채우기를 돌리지 않는다 — {DEFAULT_TIME} 회차와 겹친다"
                f"({step.label or step.name} 채우기 시간 한도 {limit}분)")
    return None


# ==================================================
# 2. 변화 감지 — 파생 단계를 돌릴 것인가
# ==================================================
def snapshot(db_path: Path = config.DB_PATH) -> Dict[str, object]:
    """DB 의 '지금' 을 몇 개의 수로 접는다. **읽기 전용**으로 연다.

    전체 COUNT(*) 는 4.4M 행이라 느리다 — 최근 ``SNAPSHOT_WINDOW_DAYS`` 안만 센다.
    기본키가 ``(bas_dt, srtn_cd)`` 라 이 범위 조회는 인덱스로 끝난다.
    """
    if not db_path.exists():
        return {}
    since = (now_kst() - datetime.timedelta(days=SNAPSHOT_WINDOW_DAYS)).strftime("%Y%m%d")
    conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True, timeout=60)
    try:
        def one(sql: str, *args):
            try:
                return conn.execute(sql, args).fetchone()
            except sqlite3.OperationalError:               # 표가 아직 없다
                return None

        out: Dict[str, object] = {}
        r = one("SELECT MAX(bas_dt), COUNT(*) FROM price_daily WHERE bas_dt >= ?", since)
        out["price_max"], out["price_recent_rows"] = (r or (None, 0))
        for key, table in (("adjusted_max", "price_adjusted"),
                           ("tr_max", "price_total_return"),
                           ("benchmark_max", "benchmark_index")):
            r = one(f"SELECT MAX(bas_dt) FROM {table}")
            out[key] = r[0] if r else None
        # 정정공시는 접수번호가 커지고, 금액만 바뀐 정정은 합이 바뀐다 — 셋을 함께 본다.
        # 넷째 값은 배당락일의 합 — 거래일 달력이 바뀌어 배당락일만 옮겨도 TR 을 다시 만들게(2026-10-02).
        r = one("SELECT COUNT(*), MAX(rcept_no), TOTAL(dps), "
                "TOTAL(CAST(NULLIF(ex_div_dt, '') AS INTEGER)) FROM dividend")
        out["dividend"] = list(r) if r else None
        return out
    finally:
        conn.close()


def needs_derived(before: Dict[str, object], after: Dict[str, object]) -> Optional[str]:
    """파생 단계(수정주가·TR·벤치마크)를 돌려야 하면 그 이유, 아니면 None.

    둘 중 하나면 돈다 — ① 이번 실행에 시세·배당이 바뀌었다 ② 파생 표가 시세보다
    뒤처져 있다(예전 실행이 중간에 죽었거나, 사람이 수집만 돌리고 전처리를 잊었다).
    ②를 빼면 한 번 어긋난 파생 표가 **새 거래일이 올 때까지** 뒤처진 채로 남는다.
    """
    if not after:
        return "DB 가 없다 — 처음부터 만든다"
    if before.get("price_max") != after.get("price_max") \
            or before.get("price_recent_rows") != after.get("price_recent_rows"):
        return f"시세가 바뀌었다 ({before.get('price_max')} → {after.get('price_max')})"
    if before.get("dividend") != after.get("dividend"):
        return "배당 표가 바뀌었다"
    p = after.get("price_max") or ""
    lag = [k for k in ("adjusted_max", "tr_max", "benchmark_max")
           if (after.get(k) or "") < p]
    if lag:
        return "파생 표가 시세보다 뒤처져 있다 (" + ", ".join(
            f"{k.replace('_max', '')} {after.get(k)}" for k in lag) + f" < {p})"
    return None


# ==================================================
# 3. 실행
# ==================================================
@dataclass
class Run:
    started: datetime.datetime
    upload: bool
    log: TextIO
    log_path: Path
    steps: List[Dict] = field(default_factory=list)
    #: 앱 DB 를 쓰는 단계에 넘길 PC 쪽 주소(``prepare_app_db`` 가 채운다 · 다른 단계에는 넘기지 않는다)
    app_db_env: Dict[str, str] = field(default_factory=dict)
    #: 주소를 못 만들었으면 그 까닭 — 앱 DB 단계는 돌리지 않고 이 까닭으로 경고를 남긴다
    app_db_why: str = ""

    def say(self, msg: str) -> None:
        line = f"[{now_kst().strftime('%H:%M:%S')}] {msg}"
        self.log.write(line + "\n")
        self.log.flush()
        if sys.stdout is not None:                          # pythonw 면 stdout 이 없다
            try:
                print(line, flush=True)
            except (OSError, ValueError):
                pass


def prepare_app_db(run: Run, steps: Sequence[Step]) -> None:
    """돌릴 단계 가운데 앱 DB 를 쓰는 것이 있으면 PC 쪽 주소를 한 번 만들어 둔다 · 로그에는 비밀번호 없이 주소만."""
    if not any(s.app_db for s in steps):
        return
    env, why = host_app_db_env()
    run.app_db_env, run.app_db_why = env, why or ""
    if env:
        run.say(f"앱 DB 주소(PC 쪽 · compose 에서) {_db_where(env['DATABASE_URL'])} — 앱 DB 를 쓰는 단계에만 넘긴다")
    else:
        # 앱 설정의 기본 주소(.env.dev · 기초 코드의 lumina@localhost)로 돌리면 다른 DB 에 말없이 쓸 수 있다 → 돌리지 않는다
        run.say(f"🟡 앱 DB 주소를 만들지 못했다 — {why} · 앱 DB 를 쓰는 단계는 돌리지 않는다(경고)")


def app_db_gate(run: Run, step: Step) -> Optional[Dict]:
    """앱 DB 단계를 돌려도 되는가 — 되면 None, 안 되면 단계 줄에 쓸 칸(rc · 까닭 · 메모 …).

    · 주소를 못 만듦 → 돌리지 않음 · 종료코드 ``EX_CONFIG``(경고 — 설정 결함은 숨기지 않는다)
    · 포트에 닿지 않음(앱 DB 꺼짐) → 돌리지 않음 · ``rc`` 없음(회차 ok 를 깨지 않는다) · 까닭 ``app_db_down`` · 뒤 할 일
      ``fill``(단계 정의의 채우기 명령) · 그 회차가 계산했을 거래일. 리밸런싱 하루 점검(팀원)은 신호를 읽지 않는다.
    """
    if not step.app_db:
        return None
    if not run.app_db_env:
        return {"rc": EX_CONFIG, "reason": "app_db_address_unknown",
                "note": f"앱 DB 주소를 만들지 못함 — {run.app_db_why} · 돌리지 않음",
                "error": scrub_line(f"앱 DB 주소를 만들지 못함 — {run.app_db_why}"), "log_name": run.log_path.name}
    why = app_db_unreachable(run.app_db_env)
    if why is None:
        return None
    return {"rc": None, "reason": "app_db_down", "followup": "fill", "date": _as_of_day(),
            "note": f"앱 DB 꺼짐 · {_db_where(run.app_db_env['DATABASE_URL'])} {why} · 건너뜀"}


def _run_step(run: Run, step: Step, *, args: Optional[List[str]] = None, timeout_min: Optional[int] = None) -> int:
    """단계 하나를 자식 파이썬으로 — ``args`` · ``timeout_min`` 은 빠진 날 채우기(날짜를 넣은 채우기 인자 · 범위로 센 한도)."""
    args = list(args) if args is not None else step.args
    timeout_min = timeout_min or step.timeout_min
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env["PYTHONIOENCODING"] = "utf-8"
    if step.sharing and run.upload:
        env["QURIOUS_RAW_SHARING"] = "1"       # ← 머리말 "원자료 공유 스위치" 참고
    else:
        env.pop("QURIOUS_RAW_SHARING", None)
    if step.app_db:
        env.update(run.app_db_env)             # ← ``host_app_db_env`` — 컨테이너 주소가 아니라 compose 가 연 포트
    run.log.write(f"\n{'=' * 70}\n▶ {step.name}: python {' '.join(args)}\n{'=' * 70}\n")
    run.log.flush()
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        p = subprocess.run([child_python(), *args], cwd=ROOT, env=env,
                           stdout=run.log, stderr=subprocess.STDOUT,
                           timeout=timeout_min * 60, creationflags=flags)
        return p.returncode
    except subprocess.TimeoutExpired:
        run.log.write(f"\n⏱ {timeout_min}분을 넘겨 멈췄다\n")
        return 124


def _prune_logs() -> None:
    logs = sorted(LOG_DIR.glob("daily_update-*.log"))
    for old in logs[:-KEEP_LOGS]:
        old.unlink(missing_ok=True)


def run_all(upload: bool = False, force_derived: bool = False, *, manual: bool = False,
            request_id: Optional[str] = None) -> int:
    """회차 하나 — 정기(작업 스케줄러) 또는 수동(화면 「전체 수집」 · ``manual``).

    수동 회차는 12:30 회차와 겹치는 때(``full_run_blocked``)와 다른 실행이 도는 동안 돌지 않고 ``EX_TEMPFAIL`` 로 끝난다 — 작업자가
    요청을 다시 대기로 돌리고, 이력에 「건너뜀」 줄을 남기지 않는다(요청 줄이 기록이다). 정기 회차의 겹침은 지금처럼 0 과 「건너뜀」
    줄이다. 회차 기록 · 이력 줄에 ``trigger``(schedule · manual) · ``request_id`` · ``rc`` · ``log`` 를 남겨 작업자가 요청 번호로
    결과를 찾는다(2026-10-10).
    """
    started = now_kst()
    if manual:
        why = full_run_blocked(started)
        if why:
            if sys.stdout is not None:
                print(f"멈춤: {why}")
            return EX_TEMPFAIL
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"daily_update-{started.strftime('%Y%m%d-%H%M%S')}{'-manual' if manual else ''}.log"
    trigger: Dict[str, str] = {"trigger": "manual" if manual else "schedule"}
    if request_id:
        trigger["request_id"] = request_id

    busy = acquire_lock(now=started)      # 잠금 · 진행 파일이 같은 시작 시각 — 앱이 같은 실행인지 시각으로 가른다
    if busy:
        if manual:                        # 수동 회차는 나중에 다시(작업자가 대기로 되돌린다) — 「건너뜀」 이력 줄은 쓰지 않는다
            if sys.stdout is not None:
                print(f"멈춤: {busy}")
            return EX_TEMPFAIL
        # 로그를 새로 만들지 않는다 — 돌고 있는 쪽 로그가 정본이다.
        msg = f"{_iso(started)} 건너뜀: {busy}"
        if sys.stdout is not None:
            print(msg)
        with HISTORY_PATH.open("a", encoding="utf-8") as h:
            h.write(json.dumps({"started_at": _iso(started), "skipped": busy},
                               ensure_ascii=False) + "\n")
        return 0

    rc_total = 0
    with log_path.open("w", encoding="utf-8") as log:
        run = Run(started, upload, log, log_path)
        try:
            run.say(f"일일 갱신 시작 · 업로드 {'켬' if upload else '끔'} · PID {os.getpid()}"
                    + (f" · 수동(화면 요청 {request_id[:8]})" if request_id else (" · 수동" if manual else "")))
            for err in write_side_files():                  # 단계 목록 · 이 PC 용량(앱이 읽는다)
                run.say(f"🟡 기록 파일을 쓰지 못했다 — {err}")
            prepare_app_db(run, STEPS)
            pending = load_fill()                           # 빠진 날 — 앱 DB 가 꺼진 회차마다 더하고, 그날을 계산하면 지운다
            pending_changed = False
            before = snapshot()
            run.say(f"시작 상태 {json.dumps(before, ensure_ascii=False)}")
            derived_why: Optional[str] = None
            stop = ""
            for step in STEPS:
                rec = _rec(step)
                run.steps.append(rec)
                # 건너뛴 줄에는 까닭 코드를 함께 적는다 — 화면이 「할 일 없는 건너뜀(회색)」 과 「채울 것이 있는 건너뜀(노랑)」 을 가른다
                if step.upload and not upload:
                    rec.update(note="업로드 끔", reason="upload_off")
                    continue
                if stop:
                    rec.update(note=f"앞 단계 실패로 건너뜀 ({stop})", reason="upstream_failed")
                    continue
                if step.derived:
                    if derived_why is None:
                        derived_why = "강제(--force-derived)" if force_derived \
                            else (needs_derived(before, snapshot()) or "")
                        run.say(f"파생 단계 판정: {derived_why or '새 자료 없음 — 건너뛴다'}")
                    if not derived_why:
                        rec.update(note="새 자료 없음", reason="no_new_data")
                        continue
                if step.name == "upload":
                    pending = _pending_upload()
                    if pending == []:
                        rec.update(note="바뀐 파케이 0개 — 원격과 같다", reason="nothing_to_upload")
                        run.say("upload: 바뀐 파케이가 없어 올리지 않는다")
                        continue
                    run.say(f"upload: 바뀐 파케이 "
                            f"{'(업로드 기록 없음)' if pending is None else f'{len(pending)}개'}")
                gate = app_db_gate(run, step)                # 앱 DB 단계 — 돌리기 전에 전제 조건을 묻는다(안 B)
                if gate:
                    rec.update(gate)
                    run.say(f"🟡 {step.name} · {gate['note']}")
                    if gate["rc"] is not None:              # 주소를 못 만듦 = 설정 결함 → 경고로 센다(건너뜀이 아니다)
                        rc_total = rc_total or gate["rc"]
                    elif gate.get("followup") == "fill" and gate.get("date"):   # 그 회차가 계산했을 거래일을 빠진 날로
                        days = pending.setdefault(step.name, [])
                        if gate["date"] not in days:
                            days.append(gate["date"])
                            pending_changed = True
                    continue
                t0 = time.time()
                run.say(f"▶ {step.name} …")
                write_progress(started, step, run)         # 수집 일정 화면의 「수집 중 — n번째 단계」
                mark = _log_mark(run)
                rc = _run_step(run, step)
                rec["rc"], rec["seconds"] = rc, round(time.time() - t0, 1)
                rec.update(step_failure(run, step, rc, mark))   # 실패면 까닭 한 줄 · 로그 파일 이름(DF-101)
                if rc == 0 and pending.get(step.name):     # 앱 DB 가 다시 떴다 — 이 회차가 계산한 그날만 지운다
                    day = _as_of_day()
                    if day in pending[step.name]:
                        pending[step.name].remove(day)
                        pending_changed = True
                run.say(f"{'✅' if rc == 0 else ('🟡' if not step.fatal else '🔴')} "
                        f"{step.name} · 종료코드 {rc} · {rec['seconds']:,.0f}초")
                if rc != 0:
                    rc_total = rc_total or rc
                    if step.fatal:
                        stop = f"{step.name} 종료코드 {rc}"
            if pending_changed:
                _save_fill(run, pending)
            for rec in run.steps:                           # 남은 빠진 날은 성공 줄이어도 「채울 것」 으로(말없이 사라지지 않게)
                _apply_fill(rec, pending.get(rec["name"], []))
            after = snapshot()
            ok = not stop and all(s["rc"] in (None, 0) for s in run.steps)
            state = {
                "started_at": _iso(started), "finished_at": _iso(now_kst()),
                "ok": ok, "upload": upload, "stopped": stop or None,
                "derived": derived_why, "steps": run.steps,
                "before": before, "after": after,
                "log": log_path.relative_to(ROOT).as_posix(),
            } | trigger
            _write_json_atomic(LAST_PATH, state)
            with HISTORY_PATH.open("a", encoding="utf-8") as h:
                h.write(json.dumps({k: state[k] for k in
                                    ("started_at", "finished_at", "ok", "upload", "stopped", "log")}
                                   | {"price_max": after.get("price_max"), "rc": rc_total,
                                      "steps": _compact(run.steps)} | trigger,
                                   ensure_ascii=False) + "\n")
            for err in write_side_files():                  # 용량은 회차 끝에 다시 잰다
                run.say(f"🟡 기록 파일을 쓰지 못했다 — {err}")
            run.say(f"끝 · {'✅ 전부 성공' if ok else '🔴/🟡 실패 단계 있음'} · "
                    f"시세 {after.get('price_max')} · 수정주가 {after.get('adjusted_max')} · "
                    f"TR {after.get('tr_max')} · 벤치마크 {after.get('benchmark_max')}")
        except Exception as e:                              # 러너 자체의 결함도 기록으로 남긴다
            run.say(f"🔴 러너 오류: {type(e).__name__}: {e}")
            err = {"started_at": _iso(started), "finished_at": _iso(now_kst()), "ok": False,
                   "upload": upload, "stopped": f"러너 오류 {type(e).__name__}: {e}",
                   "steps": run.steps, "log": log_path.relative_to(ROOT).as_posix()} | trigger
            _write_json_atomic(LAST_PATH, err)
            if request_id:                                  # 작업자가 요청 번호로 결과를 찾는다 — 러너 오류도 기록으로
                with HISTORY_PATH.open("a", encoding="utf-8") as h:
                    h.write(json.dumps({k: err[k] for k in ("started_at", "finished_at", "ok", "upload", "stopped", "log")}
                                       | {"rc": 1, "steps": _compact(run.steps)} | trigger, ensure_ascii=False) + "\n")
            rc_total = 1
        finally:
            clear_progress()
            release_lock()
    _prune_logs()
    return rc_total


#: 한 단계만 다시 돌릴 때 예약 회차를 비켜 가는 뒤쪽 여유(분) — 회차는 보통 25 ~ 60분 돈다(2026-10-07 은 60분).
RERUN_GUARD_AFTER_MIN = 60

#: 화면의 「전체 수집」(수동 회차)을 막는 앞쪽 여유(분) — 12:30 보다 이만큼 앞서 시작한 수동 회차는 정기 회차 시각까지 끝나지 않을 수
#: 있다. 그러면 정기 회차가 잠금에 걸려 통째로 건너뛰고(작업 스케줄러는 다시 시도하지 않는다) 그날 마지막 회차의 시작이 12:30 앞이
#: 되어 리밸런싱 하루 점검(「오늘 12:30 뒤 시작한 회차」)이 하루 내내 기다린다. 90분 = 최근 회차의 긴 쪽(10-07 60분)에 여유를 더한 값.
MANUAL_FULL_GUARD_BEFORE_MIN = 90


def guard_window(before_min: int, now: datetime.datetime) -> tuple:
    """그날 화면 실행을 막는 때 — (회차 시작 − before_min, 회차 시작 + ``RERUN_GUARD_AFTER_MIN``).

    한 단계 다시(그 단계 시간 한도) · 수동 전체 수집(``MANUAL_FULL_GUARD_BEFORE_MIN``) · 단계 목록의 「막는 때」 가 모두 이 함수
    하나로 센다 — 셈이 두 곳에 있으면 한쪽만 고쳐 화면과 판정이 어긋난다(2026-10-10).
    """
    hh, mm = (int(x) for x in DEFAULT_TIME.split(":"))
    sched = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    return sched - datetime.timedelta(minutes=before_min), sched + datetime.timedelta(minutes=RERUN_GUARD_AFTER_MIN)


def rerun_blocked(step: Step, now: datetime.datetime) -> Optional[str]:
    """한 단계만 돌려도 되는가 — 안 되면 그 까닭 한 줄.

    예약 회차(``DEFAULT_TIME``)와 겹치면 막는다. 단계가 회차 시작 전에 끝나지 않으면 회차가 잠금에 걸려 **통째로 건너뛰고**
    (작업 스케줄러는 다시 시도하지 않는다), 회차가 도는 동안에는 같은 표를 두 프로세스가 고친다. 그래서
    「회차 시작 − 그 단계의 시간 한도」 부터 「회차 시작 + 60분」 까지는 돌리지 않는다.
    """
    lo, hi = guard_window(step.timeout_min, now)
    if lo <= now <= hi:
        return (f"{lo.strftime('%H:%M')} ~ {hi.strftime('%H:%M')} 에는 돌리지 않는다 — {DEFAULT_TIME} 회차와 겹친다"
                f"({step.label or step.name} 시간 한도 {step.timeout_min}분)")
    return None


def full_run_blocked(now: datetime.datetime) -> Optional[str]:
    """화면의 「전체 수집」(수동 회차)을 돌려도 되는가 — 안 되면 까닭 한 줄. 정기 회차(작업 스케줄러)에는 쓰지 않는다."""
    lo, hi = guard_window(MANUAL_FULL_GUARD_BEFORE_MIN, now)
    if lo <= now <= hi:
        return (f"{lo.strftime('%H:%M')} ~ {hi.strftime('%H:%M')} 에는 전체 수집을 돌리지 않는다 — {DEFAULT_TIME} 회차와 겹친다"
                f"(정기 회차가 그날 전체를 돈다)")
    return None


def guards(now: Optional[datetime.datetime] = None) -> Dict:
    """단계 목록에 싣는 막는 때 — {schedule, full: {from, to}, steps: {이름: {from, to}}, fill: {이름: {from, to}}}(HH:MM).

    ``fill`` 은 빠진 날 채우기를 받는 단계만 — 가장 긴 범위(``fill_timeout_cap``)로 센 창이다. 화면은 이 창으로 단추를 끄고, 짧은
    범위는 러너 · 작업자가 그 범위로 다시 센다(창이 더 좁다 — 화면이 끈 때에 러너가 막지 않는 일은 있어도 그 반대는 없다).
    """
    now = now or now_kst()

    def hm(w: tuple) -> Dict[str, str]:
        return {"from": w[0].strftime("%H:%M"), "to": w[1].strftime("%H:%M")}

    return {"schedule": DEFAULT_TIME, "full": hm(guard_window(MANUAL_FULL_GUARD_BEFORE_MIN, now)),
            "steps": {s.name: hm(guard_window(s.timeout_min, now)) for s in STEPS},
            "fill": {s.name: hm(guard_window(fill_timeout_cap(s), now)) for s in STEPS if s.fill_args}}


def rearm_wal(db_path: Optional[Path] = None) -> bool:
    """수집 DB 의 WAL 보조 파일(``-wal`` · ``-shm``)을 다시 남긴다 — 둘이 있으면 참.

    앱(도커)은 ``data/`` 를 읽기 전용으로 붙여 열어, WAL DB 의 보조 파일이 없으면 만들지 못하고 「unable to open database
    file」 로 멈춘다(DF-74 와 같은 뿌리). 이 PC 의 **쓰기** 연결이 마지막으로 닫히면 SQLite 가 둘을 지운다 — 2026-10-07 에
    ``run --only manifest`` 를 돌린 뒤 데이터 API 8개가 그렇게 멈췄다. 읽기 전용 연결은 열 때 둘을 만들고 닫아도 지우지
    않으므로, 단계를 돌린 뒤 한 번 읽기 전용으로 열어 둔다. 정기 회차는 끝의 ``snapshot()`` 이 같은 일을 한다.
    """
    db = db_path or config.DB_PATH                          # 부를 때 읽는다 — 시험이 경로를 바꿀 수 있게
    if not db.exists():
        return False
    try:
        conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True, timeout=60)
        try:
            conn.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return False
    return db.with_name(db.name + "-wal").exists() and db.with_name(db.name + "-shm").exists()


def _finish_one(run: Run, step: Step, rec: Dict, rc: int, *, gate: Optional[Dict], started: datetime.datetime,
                upload: bool, request_id: Optional[str], fill: Optional[Dict[str, str]] = None) -> None:
    """한 단계 다시 · 빠진 날 채우기의 뒷일 — 끝 상태를 다시 재고, 마지막 회차 기록의 그 줄만 바꾸고(다시 돌림 줄 하나 더),
    이력에 한 줄을 남기고, 단계 목록 · 용량 파일을 다시 쓴다. ``fill`` 은 채운 범위({from, to}) — 다시 돌림 줄 · 이력 줄에 함께."""
    name = step.name
    # 끝 상태(시세 기준일 · 파생 표 기준일 · 배당 지문)를 다시 잰다(2026-10-08 · DF-85). 옛 코드는 단계 줄만 바꾸고
    # `after` 를 회차 때 값으로 두어, 시세를 다시 받아도 리밸런싱 하루 점검 준비 판정(팀원 #136)이 회차 기록의
    # 옛 기준일로 「시세 기준일이 다름」 을 냈다. 못 재면 옛 값을 지우지 않되 기록 · 로그에 그 사실을 남긴다
    # (옛 값이 말없이 「지금 값」 처럼 보이지 않게). 읽기 전용 연결이라 WAL 보조 파일을 지우지 않는다(DF-81).
    after: Optional[Dict[str, object]] = None
    after_error: Optional[Dict[str, str]] = None
    try:
        after = snapshot()
    except (sqlite3.Error, OSError) as e:
        after_error = {"at": rec["rerun_at"], "why": f"{type(e).__name__}: {e}"}
        run.say(f"🟡 시세 기준일을 다시 재지 못했다 — {after_error['why']} · 회차 기록의 기준일은 회차 때 값 그대로다")
    if not gate:                                     # 돌리지 않은 단계는 위에서 까닭 한 줄을 이미 남겼다
        run.say(f"{'✅' if rc == 0 else ('🟡' if not step.fatal else '🔴')} {name} · 종료코드 {rc} · {rec['seconds']:,.0f}초"
                + (f" · 시세 기준일 {after.get('price_max')}" if after else ""))
    extra: Dict[str, object] = ({"request_id": request_id} if request_id else {}) | ({"fill": fill} if fill else {})
    last = None
    try:
        last = json.loads(LAST_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    if last:                                         # 마지막 회차의 그 줄만 바꾼다 — 화면은 그 줄의 결과가 바뀐다
        rows = list(last.get("steps") or [])
        if any(s.get("name") == name for s in rows):
            rows = [rec if s.get("name") == name else s for s in rows]
        else:
            # 회차 뒤에 더한 단계(2026-10-08 신호 단계를 처음 붙인 날) — 바꿀 줄이 없으면 결과를 버리지 않고
            # 단계 목록 차례 자리에 끼운다(옛 이름 · 지운 단계 줄은 그대로 앞에 둔다).
            order = {s.name: i for i, s in enumerate(STEPS)}
            at = sum(1 for s in rows if order.get(s.get("name"), -1) < order[name])
            rows.insert(at, rec)
        last["steps"] = rows
        last.setdefault("reruns", []).append({"name": name, "at": rec["rerun_at"], "rc": rc,
                                              "log": run.log_path.relative_to(ROOT).as_posix()} | extra)
        last["ok"] = not last.get("stopped") and all(s.get("rc") in (None, 0) for s in last["steps"])
        if after is not None:                        # 다시 잰 끝 상태 — 회차의 시작 상태(before)는 그대로
            last["after"], last["after_at"] = after, rec["rerun_at"]
            last.pop("after_error", None)
        else:
            last["after_error"] = after_error
        _write_json_atomic(LAST_PATH, last)
    with HISTORY_PATH.open("a", encoding="utf-8") as h:
        h.write(json.dumps({"started_at": _iso(started), "finished_at": _iso(now_kst()), "only": name,
                            "ok": rc == 0, "upload": upload, "stopped": None,
                            "price_max": (after or {}).get("price_max"), "rc": rc,
                            "log": run.log_path.relative_to(ROOT).as_posix(), "trigger": "manual",
                            "steps": _compact([rec])} | extra,
                           ensure_ascii=False) + "\n")
    for err in write_side_files():
        run.say(f"🟡 기록 파일을 쓰지 못했다 — {err}")


def _rearm_or_say(run: Run) -> None:
    if not rearm_wal():                              # 단계가 쓰기 연결로 끝났어도 앱이 수집 DB 를 읽게
        run.say("🟡 수집 DB 의 WAL 보조 파일(-wal · -shm)을 다시 만들지 못했다 — 앱의 데이터 화면을 확인한다"
                "(check.ps1 -Group 데이터)")


def run_one(name: str, upload: bool = False, *, now: Optional[datetime.datetime] = None,
            request_id: Optional[str] = None) -> int:
    """단계 하나만 다시 돌린다 — 마지막 회차 기록의 그 줄을 새 결과로 바꾸고, 이력에 「다시 돌림」 한 줄을 남긴다.

    파생 판정 · 올릴 것 판정은 하지 않는다(사람이 그 단계를 골랐다). 앞 단계 실패로 건너뛴 뒤 단계들은 돌리지 않으므로
    회차의 「멈춘 곳」 은 그대로 남는다. 종료코드: 0 성공 · 2 고를 수 없는 단계 · 75 막힘(회차와 겹침 · 다른 실행 — 나중에 다시 ·
    ``EX_TEMPFAIL``) · 3 앱 DB 꺼짐으로 건너뜀(채울 것) · 78 앱 DB 주소 결함 · 그 밖 = 단계 종료코드. ``request_id`` 는 화면
    요청 번호 — 이력 줄 · 다시 돌림 줄에 남겨 작업자가 결과를 찾는다(2026-10-10). 빠진 날이 남은 단계는 이번에 계산한 그날만
    지운다(정기 회차와 같다).
    """
    step = next((s for s in STEPS if s.name == name), None)
    if step is None:
        print(f"멈춤: 그런 단계가 없다 — {name} (있는 단계: {', '.join(s.name for s in STEPS)})")
        return 2
    if step.upload and not upload:
        print(f"멈춤: {name} 은 올리기 단계다 — `run --only {name} --upload` 로 공유 스위치를 켜서 돌린다")
        return 2
    started = now or now_kst()
    why = rerun_blocked(step, started)
    if why:
        print(f"멈춤: {why}")
        return EX_TEMPFAIL
    busy = acquire_lock(now=started)
    if busy:
        print(f"멈춤: {busy}")
        return EX_TEMPFAIL
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"daily_update-{started.strftime('%Y%m%d-%H%M%S')}-only-{name}.log"
    rc = 1
    try:
        with log_path.open("w", encoding="utf-8") as log:
            run = Run(started, upload, log, log_path)
            run.say(f"한 단계만 다시 돌림 · {name}({step.label}) · 업로드 {'켬' if upload else '끔'} · PID {os.getpid()}")
            rec = _rec(step)
            prepare_app_db(run, [step])
            gate = app_db_gate(run, step)                    # 앱 DB 단계 — 꺼져 있으면 돌리지 않는다(정기 회차와 같은 규칙)
            pending = load_fill()
            t0 = time.time()
            if gate:
                rec.update(gate, rerun_at=_iso(now_kst()))
                rc = 3 if gate["rc"] is None else gate["rc"]  # 3 = 막힘(지금은 돌 조건이 없다) · 78 = 설정 결함
                run.say(f"🟡 {name} · {gate['note']}")
                if gate["rc"] is None and gate.get("date") and gate["date"] not in pending.get(name, []):
                    pending.setdefault(name, []).append(gate["date"])
                    _save_fill(run, pending)
            else:
                write_progress(started, step, run)
                mark = _log_mark(run)
                rc = _run_step(run, step)
                rec.update(rc=rc, seconds=round(time.time() - t0, 1), note="다시 돌림", rerun_at=_iso(now_kst()))
                rec.update(step_failure(run, step, rc, mark))
                if rc == 0 and pending.get(name):
                    day = _as_of_day()
                    if day in pending[name]:
                        pending[name].remove(day)
                        _save_fill(run, pending)
                _rearm_or_say(run)
            _apply_fill(rec, pending.get(name, []))
            _finish_one(run, step, rec, rc, gate=gate, started=started, upload=upload, request_id=request_id)
    finally:
        clear_progress()
        release_lock()
        _prune_logs()
    return rc


def run_fill(name: str, d_from: str, d_to: str, *, now: Optional[datetime.datetime] = None,
             request_id: Optional[str] = None) -> int:
    """빠진 날 채우기 — 그 단계의 채우기 인자에 날짜를 넣어 한 번 돌리고, 성공하면 그 범위의 빠진 날만 지운다(2026-10-10 ·
    화면 「빠진 날 채우기」 · 사용자 결정 — 새 요청 종류 fill · 상한 31일).

    받는 값(``fill_range_error``)이 틀리면 2(돌리지 않고 남기지도 않는다) · 12:30 회차와 겹치는 때(그 범위의 시간 한도로 센 막는 때 ·
    ``fill_blocked``)와 다른 실행이 돌 때는 75(작업자가 다시 대기로) · 앱 DB 가 꺼져 있으면 돌리지 않고 3 · 78 앱 DB 주소 결함 ·
    그 밖은 단계 종료코드. 뒷일은 한 단계 다시와 같다(``_finish_one`` — 회차 기록의 그 줄 · 다시 돌림 줄 · 이력 줄) · 두 줄에
    채운 범위(``fill``)를 함께 적는다.
    """
    step = next((s for s in STEPS if s.name == name), None)
    if step is None:
        print(f"멈춤: 그런 단계가 없다 — {name} (있는 단계: {', '.join(s.name for s in STEPS)})")
        return 2
    started = now or now_kst()
    err = fill_range_error(step, d_from, d_to, started.date())
    if err:
        print(f"멈춤: {err}")
        return 2
    why = fill_blocked(step, d_from, d_to, started)
    if why:
        print(f"멈춤: {why}")
        return EX_TEMPFAIL
    busy = acquire_lock(now=started)
    if busy:
        print(f"멈춤: {busy}")
        return EX_TEMPFAIL
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"daily_update-{started.strftime('%Y%m%d-%H%M%S')}-fill-{name}.log"
    limit = fill_timeout_min(step, d_from, d_to)
    rc = 1
    try:
        with log_path.open("w", encoding="utf-8") as log:
            run = Run(started, False, log, log_path)
            run.say(f"빠진 날 채우기 · {name}({step.label}) · {d_from} ~ {d_to} · 시간 한도 {limit}분 · PID {os.getpid()}"
                    + (f" · 화면 요청 {request_id[:8]}" if request_id else ""))
            rec = _rec(step)
            prepare_app_db(run, [step])
            gate = app_db_gate(run, step)
            pending = load_fill()
            t0 = time.time()
            if gate:                                         # 앱 DB 가 아직 꺼져 있다 — 빠진 날은 그대로 둔다(그날을 더하지도 않는다)
                rec.update({k: v for k, v in gate.items() if k != "date"}, rerun_at=_iso(now_kst()))
                rc = 3 if gate["rc"] is None else gate["rc"]
                run.say(f"🟡 {name} · {gate['note']}")
            else:
                write_progress(started, step, run)
                args = [a.replace("{from}", d_from).replace("{to}", d_to) for a in step.fill_args]
                mark = _log_mark(run)
                rc = _run_step(run, step, args=args, timeout_min=limit)
                rec.update(rc=rc, seconds=round(time.time() - t0, 1), note=f"빠진 날 채움 {d_from} ~ {d_to}",
                           rerun_at=_iso(now_kst()))
                rec.update(step_failure(run, step, rc, mark, limit))
                if rc == 0 and pending.get(name):            # 채운 범위의 빠진 날만 지운다 — 범위 밖 날은 그대로 「채울 것」
                    pending[name] = [d for d in pending[name] if not d_from <= d <= d_to]
                    _save_fill(run, pending)
                _rearm_or_say(run)
            _apply_fill(rec, pending.get(name, []))
            _finish_one(run, step, rec, rc, gate=gate, started=started, upload=False, request_id=request_id,
                        fill={"from": d_from, "to": d_to})
    finally:
        clear_progress()
        release_lock()
        _prune_logs()
    return rc


def _pending_upload() -> Optional[List[str]]:
    from scripts import hf_dataset
    return hf_dataset.changed_since_upload()


# ==================================================
# 4. 작업 스케줄러 — 세션이 끝나도 도는 부분
# ==================================================
def task_xml(time_hm: str, upload: bool, *, python_w: str, root: Path,
             today: Optional[datetime.date] = None) -> str:
    """작업 스케줄러 정의(XML). ``schtasks /Create /XML`` 로 등록한다.

    PowerShell ``Register-ScheduledTask`` 대신 XML 인 이유 — Windows PowerShell 5.1 은
    BOM 없는 UTF-8 스크립트를 ANSI 로 읽어 한글 설명이 깨진다. XML 은 인코딩을 스스로
    밝힌다. 설정의 뜻:

    · ``StartWhenAvailable`` — 그 시각에 PC 가 꺼져 있었으면 **켜진 뒤 곧바로** 돈다.
      이것이 없으면 노트북을 닫아 둔 날은 통째로 건너뛴다.
    · ``RunOnlyIfNetworkAvailable`` — 네트워크 없이 돌면 ①부터 실패하므로 기다린다.
    · ``InteractiveToken`` — 로그인해 있을 때만 돈다. 비밀번호를 저장하지 않는다.
    · ``IgnoreNew`` — 이전 실행이 아직 돌면 새 실행을 만들지 않는다(러너의 잠금과 이중).
    """
    hh, mm = (int(x) for x in time_hm.split(":"))
    start = datetime.datetime.combine(today or datetime.date.today(), datetime.time(hh, mm))
    args = f'"{root / "scripts" / "daily_update.py"}" run' + (" --upload" if upload else "")

    def esc(s: str) -> str:
        return (s.replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;").replace('"', "&quot;"))

    desc = ("Qurious 수집기 일일 갱신 — 시세·배당·수정주가·TR·벤치마크"
            + (" + HF(qurious-quant/krx-daily-market) 증분 업로드" if upload else "")
            + ". 정의: scripts/daily_update.py")
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>{esc(desc)}</Description>
    <URI>\\{TASK_NAME}</URI>
  </RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>{start.isoformat(timespec="seconds")}</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>
    </CalendarTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>true</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <ExecutionTimeLimit>PT{LOCK_STALE_HOURS}H</ExecutionTimeLimit>
    <Enabled>true</Enabled>
    <WakeToRun>false</WakeToRun>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{esc(python_w)}</Command>
      <Arguments>{esc(args)}</Arguments>
      <WorkingDirectory>{esc(str(root))}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def _pythonw() -> str:
    exe = Path(sys.executable)
    cand = exe.with_name("pythonw.exe")
    return str(cand if cand.exists() else exe)


def _schtasks(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["schtasks", *args], capture_output=True, text=True,
                          encoding="mbcs" if os.name == "nt" else "utf-8", errors="replace")


def install(time_hm: str = DEFAULT_TIME, upload: bool = True) -> int:
    if os.name != "nt":
        print("작업 스케줄러 등록은 Windows 전용이다. 다른 OS 는 cron 에 "
              f"`cd {ROOT} && python scripts/daily_update.py run --upload` 를 건다.")
        return 1
    xml = task_xml(time_hm, upload, python_w=_pythonw(), root=ROOT)
    fd, tmp = tempfile.mkstemp(suffix=".xml")
    os.close(fd)
    try:
        Path(tmp).write_text(xml, encoding="utf-16")
        p = _schtasks("/Create", "/TN", TASK_NAME, "/XML", tmp, "/F")
    finally:
        os.unlink(tmp)
    if p.returncode != 0:
        print(f"🔴 등록 실패 (schtasks 종료코드 {p.returncode})\n{p.stdout}{p.stderr}")
        return p.returncode
    print(f"✅ 작업 스케줄러에 등록했다 — '{TASK_NAME}' · 매일 {time_hm} · "
          f"업로드 {'켬' if upload else '끔'}")
    print("   PC 가 그 시각에 꺼져 있었으면 켜진 뒤 곧바로 돈다(StartWhenAvailable).")
    print("   지금 한 번 돌리려면: python scripts/daily_update.py start")
    return 0


def uninstall() -> int:
    p = _schtasks("/Delete", "/TN", TASK_NAME, "/F")
    print("✅ 등록을 해제했다" if p.returncode == 0 else f"🟡 {p.stdout}{p.stderr}".strip())
    return p.returncode


def start() -> int:
    p = _schtasks("/Run", "/TN", TASK_NAME)
    print(f"✅ '{TASK_NAME}' 를 시작시켰다 — 진행은 `status` 와 로그로 본다"
          if p.returncode == 0 else f"🔴 시작 실패: {p.stdout}{p.stderr}".strip())
    return p.returncode


def _task_info() -> Optional[Dict[str, str]]:
    """등록된 작업의 명령줄·마지막/다음 실행. 없으면 None. (읽기만 한다)"""
    if os.name != "nt":
        return None
    ps = (f"$t=Get-ScheduledTask -TaskName '{TASK_NAME}' -ErrorAction SilentlyContinue;"
          "if($t){$i=$t|Get-ScheduledTaskInfo;"
          "[pscustomobject]@{state=[string]$t.State;"
          "command=($t.Actions|%{$_.Execute+' '+$_.Arguments}) -join ' ; ';"
          "last=$i.LastRunTime.ToString('s');result=[string]$i.LastTaskResult;"
          "next=$i.NextRunTime.ToString('s')}|ConvertTo-Json -Compress}")
    p = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    out = (p.stdout or "").strip()
    return json.loads(out) if out.startswith("{") else None


def status() -> int:
    info = _task_info()
    print("― 예약 (작업 스케줄러) ―")
    if info:
        res = info.get("result")
        res_txt = {"0": "0 (성공)", "267009": "267009 (지금 도는 중)",
                   "267011": "267011 (아직 한 번도 안 돌았다)"}.get(res, res)
        print(f"  {TASK_NAME} · 상태 {info.get('state')}\n"
              f"  명령   {info.get('command')}\n"
              f"  마지막 {info.get('last')} · 결과 {res_txt}\n"
              f"  다음   {info.get('next')}")
    else:
        print(f"  등록돼 있지 않다 — `python scripts/daily_update.py install`")
    print("\n― 마지막 실행 ―")
    if LOCK_PATH.exists():
        try:
            held = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            held = {}
        alive = pid_alive(int(held.get("pid") or 0))
        print(f"  ⏳ {'지금 도는 중' if alive else '잠금만 남음(비정상 종료 흔적 — 다음 실행이 치운다)'}"
              f" · PID {held.get('pid')} · {held.get('started_at')} 시작")
    if not LAST_PATH.exists():
        print("  아직 끝난 실행이 없다.")
        return 0
    s = json.loads(LAST_PATH.read_text(encoding="utf-8"))
    how = ""
    if s.get("trigger") == "manual":
        how = " · 수동" + (f"(화면 요청 {str(s.get('request_id'))[:8]})" if s.get("request_id") else "")
    print(f"  {s.get('started_at')} → {s.get('finished_at')} · "
          f"{'✅ 성공' if s.get('ok') else '🔴 실패 있음'} · 업로드 {'켬' if s.get('upload') else '끔'}{how}")
    if s.get("stopped"):
        print(f"  멈춘 곳: {s['stopped']}")
    for st in s.get("steps", []):
        rc = st.get("rc")
        mark = "·" if rc is None else ("✅" if rc == 0 else "🔴")
        print(f"    {mark} {st['name']:<13} "
              + (f"종료코드 {rc} · {st.get('seconds', 0):,.0f}초" if rc is not None else "")
              + (f"  {st['note']}" if st.get("note") else ""))
        if st.get("error"):                                  # 실패한 단계의 까닭(DF-101) — 로그를 열기 전에 한 줄
            print(f"        까닭: {st['error']} · 로그 {st.get('log_name', '')}")
    a = s.get("after") or {}
    print(f"  데이터: 시세 {a.get('price_max')} · 수정주가 {a.get('adjusted_max')} · "
          f"TR {a.get('tr_max')} · 벤치마크 {a.get('benchmark_max')} · "
          f"배당 {(a.get('dividend') or [None])[0]}건")
    print(f"  로그   {s.get('log')}")
    return 0


# ==================================================
# 5. CLI
# ==================================================
def utf8_stdio() -> None:
    """표준출력·표준오류를 UTF-8 로 맞춘다.

    git bash(mintty)에서 파이썬은 표준출력을 콘솔이 아니라 파이프로 보고 cp949 를 고른다 → `status` 가
    ✅ 에서 UnicodeEncodeError 로 죽고 한글은 `▒▒` 로 깨졌다(2026-09-28 S54 실측). 작업 스케줄러의
    ``pythonw`` 는 표준출력이 None 이라 ``hasattr`` 에서 걸러진다 — 예약 실행은 그대로다
    (자식 단계에는 ``_run_step`` 이 ``PYTHONIOENCODING=utf-8`` 을 따로 넣는다).
    """
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def main(argv: Optional[Sequence[str]] = None) -> int:
    utf8_stdio()
    p = argparse.ArgumentParser(prog="python scripts/daily_update.py",
                                description="수집기 일일 갱신 — 시세·배당·파생 표 + HF 증분 업로드")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="지금 한 번 돌린다(이 터미널에서)")
    r.add_argument("--upload", action="store_true", help="HF 증분 업로드까지 한다")
    r.add_argument("--force-derived", action="store_true",
                   help="새 자료가 없어도 수정주가·TR·벤치마크를 다시 계산한다")
    r.add_argument("--only", metavar="단계",
                   help="그 단계 하나만 다시 돌린다(예약 회차와 겹치는 시간 · 다른 실행이 돌 때는 막는다)")
    r.add_argument("--manual", action="store_true",
                   help="수동 회차(화면 「전체 수집」) — 12:30 회차와 겹치는 때(11:00 ~ 13:30)와 다른 실행이 돌 때는 75 로 끝낸다")
    r.add_argument("--request", metavar="요청번호",
                   help="화면 수집 요청 번호(UUID) — 회차 기록 · 이력에 남겨 작업자가 결과를 찾는다(전체 수집이면 수동 회차)")
    r.add_argument("--fill", metavar="단계",
                   help=f"그 단계의 빠진 날을 채운다 — --from · --to 와 함께(양 끝 포함 · {FILL_MAX_DAYS}일까지)")
    r.add_argument("--from", dest="date_from", metavar="YYYY-MM-DD", help="채울 첫날(--fill 과 함께)")
    r.add_argument("--to", dest="date_to", metavar="YYYY-MM-DD", help="채울 마지막 날(--fill 과 함께)")
    sub.add_parser("status", help="마지막 실행 결과와 예약 상태")
    s = sub.add_parser("steps", help="단계 목록(이름표 · 묶음 · 하는 일) — 앱이 읽는 목록")
    s.add_argument("--write", action="store_true", help="단계 목록 · 이 PC 용량 파일을 지금 쓴다(회차를 기다리지 않고)")
    i = sub.add_parser("install", help="작업 스케줄러에 매일 실행 등록 (기본 업로드 포함)")
    i.add_argument("--time", default=DEFAULT_TIME, help=f"실행 시각 HH:MM (기본 {DEFAULT_TIME})")
    i.add_argument("--no-upload", action="store_true", help="로컬 갱신만 하고 HF 에 올리지 않는다")
    sub.add_parser("start", help="등록된 작업을 지금 한 번 돌린다(비동기 · 세션과 무관)")
    sub.add_parser("uninstall", help="작업 스케줄러 등록 해제")
    a = p.parse_args(argv)

    if a.cmd == "run":
        rid = None
        if a.request:
            try:
                rid = str(uuid.UUID(a.request))
            except ValueError:
                print("멈춤: --request 는 화면 수집 요청 번호(UUID)다")
                return 2
        if a.fill or a.date_from or a.date_to:
            # 채우기는 그것만 — 다른 실행 고르기와 섞이면 무엇을 돌렸는지 기록이 흐려진다
            if not a.fill:
                print("멈춤: --from · --to 는 --fill <단계> 와 함께만 쓴다")
                return 2
            if not (a.date_from and a.date_to):
                print("멈춤: --fill 은 --from · --to 를 둘 다 준다(YYYY-MM-DD)")
                return 2
            if a.only or a.manual or a.upload or a.force_derived:
                print("멈춤: --fill 은 --only · --manual · --upload · --force-derived 와 함께 쓰지 않는다")
                return 2
            return run_fill(a.fill, a.date_from, a.date_to, request_id=rid)
        if a.only:
            return run_one(a.only, upload=a.upload, request_id=rid)
        return run_all(upload=a.upload, force_derived=a.force_derived, manual=a.manual or rid is not None,
                       request_id=rid)
    if a.cmd == "status":
        return status()
    if a.cmd == "steps":
        for g in GROUPS:
            print(f"― {g['key']} — {g['note']}")
            for st in (x for x in STEPS if x.group == g["key"]):
                flags = " · ".join(f for f, on in (("멈춤", st.fatal), ("파생", st.derived), ("올리기", st.upload)) if on)
                print(f"  {st.name:<13} {st.label:<8} {st.desc}" + (f"  [{flags}]" if flags else ""))
        if a.write:
            errors = write_side_files()
            print("\n".join(f"🟡 {e}" for e in errors) if errors
                  else f"\n✅ 썼다: {CATALOG_PATH.relative_to(ROOT).as_posix()} · {DISK_PATH.relative_to(ROOT).as_posix()}")
            return 1 if errors else 0
        return 0
    if a.cmd == "install":
        return install(a.time, upload=not a.no_upload)
    if a.cmd == "start":
        return start()
    return uninstall()


if __name__ == "__main__":
    raise SystemExit(main())
