"""HF 데이터셋 파이프라인 — SQLite 를 파케이로 내보내고, 올리고, 되살린다.

이 파일이 답하는 질문은 하나다
------------------------------
**"2.4GB SQLite 를 지워도 되게 만들려면 무엇을 들고 나가야 하는가."**

수집기가 만든 `data/collector/market.sqlite3` 는 지금 **한 사람의 노트북 디스크에만**
있다. 그 디스크가 죽으면 6.7년치 시세와 열두 달을 훑어 모은 배당 공시가 같이 죽는다.
다시 받으려면 공공데이터포털 하루 10,000건 한도로 1,648 거래일을 다시 긁어야 한다.

그래서 **파케이로 내보내 Hugging Face dataset 저장소에 올린다.** HF 를 고른 이유는
① Xet 청크 중복제거로 매일 갱신해도 바뀐 조각만 올라가고 ② 태그로 "그날의 스냅샷"을
못박을 수 있어 백테스트 재현이 되고 ③ `load_dataset(token=True)` 로 팀원이 받을 수
있어서다.

★ 2026-09-20 에 바뀐 것 — "백업"에서 "지워도 되는 백업"으로
-----------------------------------------------------------
전에는 `raw_response`(응답 원문 · 감사 근거)와 `ingest_day`(수집 이력)를 **일부러
뺐다.** 파케이로 바꾸면 297.3MB → 298.6MB 로 오히려 커진다는 이유였다. 그 판단은
목적이 '분석용 사본'일 때만 맞다.

목적이 **로컬 용량 확보**로 바뀌면 그 판단은 틀린다. 두 표를 빼고 SQLite 를 지우면
`price_daily.raw_sha256` 1,648개가 가리키는 **감사 근거가 영구 소실**되고, 정규화를
다시 돌릴 재료도 사라진다. 크기 +0.4% 를 아끼려고 되돌릴 수 없는 것을 버리는 거래다.

그래서 지금은 **DB 의 표 여덟 개를 하나도 빼지 않고** 내보내고, 그 파케이만으로
SQLite 를 되살리는 `restore` 를 함께 둔다. `restore` 가 실제로 성공해야만 `status` 가
"지워도 된다"고 말한다 — **리허설 없이 초록을 내지 않는다.**

원자료를 밖으로 내보내는 근거 (팀 결정 · 2026-09-20)
-----------------------------------------------------
`collector/README.md §9` 는 `RAW_SHARING` 을 기본 꺼짐으로 두고 두 가지를 미결로
남겼다 — "팀원이 제3자인가", "공공누리 변경금지가 지표 계산까지 막는가". 그 두 건에
대해 **데이터 파트 담당자가 팀 결정을 확인**했고, 내용은 `SHARING_DECISION` 상수에
그대로 적어 두었다. 요약하면 팀원은 제3자가 아니고, 공유는 **private Organization
안에서만** 하며, 그래서 이 저장소는 **반드시 private 이어야 한다.**

코드는 그 결정을 말로만 적지 않고 **검사한다**:
  · `RAW_SHARING` 이 꺼져 있으면 내보내기·올리기를 멈추고 켜는 방법을 알려 준다.
  · 업로드 직전에 `repo_info` 로 **원격이 실제로 private 인지 확인**하고, public 이면
    중단한다. `create_repo(private=True, exist_ok=True)` 는 **이미 있는 저장소의 공개
    범위를 바꾸지 않는다** — org 관리자가 먼저 public 으로 만들어 뒀다면 그대로
    public 에 올라간다. 그래서 만드는 것과 확인하는 것을 따로 한다.

용어 두 층
----------
**파케이(Parquet)**
  · 뜻 — 열 단위로 저장하는 파일 형식. 행 단위 CSV 와 달리 같은 열의 값이 붙어 있어
    압축이 잘 듣고, 필요한 열만 읽을 수 있다.
  · 이 문서에서 — 표 하나를 연도별(또는 출처별) 파일로 쪼갠 것. `price_daily/year=2020/…`
  · 헷갈리는 점 — **파케이는 SQLite 의 대체재가 아니다.** PK·UNIQUE·트랜잭션이 없다.
    그래서 표의 **DDL 을 매니페스트에 함께 담아** `restore` 가 스키마까지 복원한다.

**Xet**
  · 뜻 — HF 가 2025 년에 LFS 를 대체한 저장 백엔드. 파일을 내용 기반으로 쪼개
    (content-defined chunking) 바뀐 청크만 전송한다.
  · 이 문서에서 — `hf_xet` 패키지가 깔려 있어야 켜진다. 없으면 LFS 로 가서 **파케이를
    한 줄만 고쳐도 파일 전체가 재업로드**된다.
  · 헷갈리는 점 — 파케이 쓰기 옵션(`compression`·`row_group_size`·정렬·CDC) 중
    **하나라도 바꾸면 바이트 배치가 통째로 달라져 이전 리비전과의 중복제거가 전부
    무효**가 된다. 그래서 `PARQUET_OPTS` 를 상수로 못박고 매니페스트에 함께 적는다.

**dry-run**
  · 뜻 — 실제로 하지 않고 "했다면 무엇이 일어났을지"만 출력하는 실행.
  · 이 문서에서 — `upload` 의 **기본값**이다. 원격에 올린 것은 되돌리기 어려우므로
    `--yes` 를 명시적으로 칠 때만 실제로 올라간다.

왜 이 레이아웃인가
------------------
**표별로 나눈다** — 갱신 단위가 다른 것은 파일도 나눈다. 세 가격표를 한 장으로 조인하면
`price_total_return` 만 다시 계산해도 `price_daily` 바이트까지 다시 올라간다.

**연도로 쪼갠다** — 일 단위면 1,600여 파일이라 커밋이 비대해지고, 표 통째 1파일이면
하루 갱신에 98MB 를 건드린다. **닫힌 연도(2020~2025)는 영원히 안 바뀌어 업로드
0바이트**다.

**정렬은 `(bas_dt, srtn_cd)`** — `(srtn_cd, bas_dt)` 가 파일은 19% 작지만, 새 거래일
행이 파일 전 구간에 흩어져 삽입되는 최악 패턴을 만든다. 목적이 **주기적 증분 백업**
이므로 크기보다 증분이 중요하다. `(bas_dt, srtn_cd)` 는 신규 행이 파일 끝에 붙는
append 패턴이라 중복제거가 가장 잘 듣는다.

⚠️ 디렉터리 이름 함정 두 가지 (본 세션 실측 · 앞 판의 주석이 반대로 적혀 있었다)
   ① `pyarrow.parquet.read_table` 은 상위 폴더 `year=2026/` 을 **추론해 컬럼을 붙인다.**
      17칸 파일이 **18칸**으로 읽힌다 — 디렉터리를 주든 파일 하나를 주든 똑같다.
      칸 수를 그대로 보려면 `ParquetFile(path).read()` 를 쓴다(17칸). `verify` 의
      스키마 게이트와 `restore` 가 `ParquetFile` 을 쓰는 이유가 이것이다.
   ② 그래서 **하이브 키 이름이 실제 칸 이름과 겹치면 읽기가 깨진다.**
      `raw_response/source=portal/` 로 두면 `read_table` 이
      `Unable to merge: Field source has incompatible types: string vs dictionary`
      로 죽는다(실측). 그래서 `raw_response` 는 하이브 폴더를 쓰지 않고
      **`raw_response/portal.parquet` 처럼 평범한 파일 이름**으로 쪼갠다.

무엇을 하지 않는가
------------------
· **DB 에 쓰지 않는다.** 읽기 전용 URI(`mode=ro`)로만 연다. `db.connect()` 를 쓰지
  않는 것은 그것이 매 연결마다 `executescript(SCHEMA)` 로 표를 만들기 때문이다 —
  내보내기는 읽는 일이지 스키마를 손보는 일이 아니다. 단 **경로는 `config.DB_PATH`**
  를 쓴다(`scripts/verify_trading_cost.py:14` 가 경로를 문자열로 박아 오기한 선례).
  (`restore` 만은 예외로 쓴다 — 다만 **다른 파일에** 쓴다. 원본은 건드리지 않는다.)
· **토큰을 출력하지 않는다.** 어떤 경로로도 로그에 찍지 않는다. 있으면 `설정됨`,
  없으면 무엇을 해야 하는지만 말한다.
· **기본으로 올리지 않는다.** `upload` 의 기본은 dry-run 이다.
· **매니페스트에 사용자 절대경로를 적지 않는다.** 예전 판은 `db_path` 에
  `C:\\Users\\<이름>\\…` 을 박아 그대로 HF 로 올렸다. 지금은 저장소 기준 상대경로만
  적는다.

쓰는 법
-------
::

    PYTHONPATH=. python scripts/hf_dataset.py export            # SQLite → 파케이
    PYTHONPATH=. python scripts/hf_dataset.py export --tables dividend,corporate_action
    PYTHONPATH=. python scripts/hf_dataset.py export --years 2026 --force
    PYTHONPATH=. python scripts/hf_dataset.py status            # 로컬 현황 + 삭제 판정
    PYTHONPATH=. python scripts/hf_dataset.py status --remote   # 원격까지 대조 (읽기)
    PYTHONPATH=. python scripts/hf_dataset.py verify            # 내보낸 것이 온전한가
    PYTHONPATH=. python scripts/hf_dataset.py verify --deep     # 큰 표까지 열 체크섬
    PYTHONPATH=. python scripts/hf_dataset.py restore           # ← 복구 리허설(임시 폴더)
    PYTHONPATH=. python scripts/hf_dataset.py restore --into D:/back/market.sqlite3
    PYTHONPATH=. python scripts/hf_dataset.py upload            # ← dry-run (기본)
    PYTHONPATH=. python scripts/hf_dataset.py upload --yes      # 실제 업로드

Windows PowerShell 에서는 ::

    $env:PYTHONIOENCODING="utf-8"; $env:PYTHONPATH="."
    $env:QURIOUS_RAW_SHARING="1"        # ← 공유 스위치. .env 로는 켜지지 않는다
    python scripts/hf_dataset.py export
"""

from __future__ import annotations

import argparse
import datetime
import fnmatch
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
import time
import zoneinfo
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from collector import config
from collector import manifest as collector_manifest

KST = zoneinfo.ZoneInfo("Asia/Seoul")

# ==================================================
# 1. 상수 — 한 번 정하고 바꾸지 않는 것들
# ==================================================

#: HF 저장소. dataset 타입 · **private**.
#:
#: private 이어야 하는 이유는 `price_daily` 가 사실상 포털 응답의 정규화본이고
#: `raw_response` 는 응답 그 자체라, 공개하면 **원자료 재배포**가 되기 때문이다
#: (공공데이터포털·OpenDART 약관). 무료 org 는 private 이면 Dataset Viewer 가 정책상
#: 꺼지지만, **뷰어를 쓰려고 public 으로 바꾸지 않는다.**
#:
#: ⚠️ 이 상수는 의도를 적은 것일 뿐이다. 실제 공개 범위는 `_assert_private()` 가
#:    업로드 직전에 원격에 물어서 확인한다.
REPO_ID = "qurious-quant/krx-daily-market"

#: 내보낸 파케이가 쌓이는 곳.
#:
#: ⚠️ 이 팀 저장소는 **Public** 이다. 이 경로가 `.gitignore` 에 없으면 270MB 파케이가
#:    통째로 커밋될 수 있다. `status` 가 매번 확인해서 경고한다.
EXPORT_DIR = config.ROOT / "data" / "hf_export"

#: 매니페스트 — 기계가 읽는 지문. 커밋 메시지는 사람이 읽고, 이쪽은 파싱한다.
MANIFEST_PATH = EXPORT_DIR / "meta" / "manifest.json"

#: 검증·복구 리허설의 **결과 기록**. `status` 의 "지워도 되는가" 판정이 이 둘을 본다.
#: 판정을 말이 아니라 **실행 기록**에 묶어 두려고 파일로 남긴다.
VERIFY_LOG_PATH = EXPORT_DIR / "meta" / "last_verify.json"
RESTORE_LOG_PATH = EXPORT_DIR / "meta" / "last_restore.json"

#: dataset card. 업로드할 때 원격 최상단에 뜨는 문서다.
README_PATH = EXPORT_DIR / "README.md"

#: 파케이 쓰기 옵션. **상수 하나로 못박고 절대 바꾸지 않는다.**
#:
#: 근거(조사4 실측):
#:   · `zstd` level 3 은 snappy 대비 −18%. level 9 는 거기서 −3.6% 더 줄 뿐인데
#:     쓰기 시간이 몇 배다 → 3 이 무릎점.
#:   · `row_group_size=250_000` — 행이 작아(17열) 그룹이 작으면 메타데이터 비중이
#:     커지고, 크면 부분 읽기가 안 듣는다.
#:     ⚠️ 표마다 한 행의 크기가 다르다. `raw_response` 는 한 행이 평균 23KB(최대
#:        183KB)라 25만 행 배치를 만들면 **한 배치가 수 GB** 다. 그래서 행 수는
#:        표 명세의 `fetch_rows` 가 덮어쓴다(아래 §2).
#:   · `use_content_defined_chunking=True` — pyarrow>=21 에서만 있다. **23.0.1 에서
#:     동작 확인**(모르는 키워드는 `__cinit__()` TypeError 로 거부되는데 이 키워드는
#:     통과했다 → 진짜로 인식된다).
#:
#: ⚠️ 이 중 하나라도 바꾸면 바이트 배치가 통째로 달라져 **이전 리비전과의 중복제거가
#:    전부 무효**가 된다(HF 명시 경고). 그래서 매니페스트에 이 dict 를 함께 적어 둔다.
PARQUET_OPTS: Dict[str, object] = dict(
    compression="zstd",
    compression_level=3,
    row_group_size=250_000,
    use_content_defined_chunking=True,
    write_statistics=True,
    write_page_index=True,
    version="2.6",
)

#: SQLite 에서 한 번에 끌어오는 기본 행 수. 이 크기로 arrow 배치를 만들어 곧바로 쓴다.
#: `row_group_size` 와 같게 두어 **배치 하나 = 로우그룹 하나**가 되게 한다.
FETCH_ROWS = 250_000

#: 큰 표를 연도로 쪼갤 때 쓰는 범위. `bas_dt` 가 **TEXT** 라 문자열로 비교한다.
#: (정수로 비교하면 부등호가 통째로 어긋난다 — 조사2 에서 실제로 겪은 함정)
YEAR_LO = "{y}0000"
YEAR_HI = "{y}9999"

#: 팀 결정 기록 (2026-09-20 · 데이터 파트 담당).
#:
#: `collector/README.md §9` 가 미결로 남긴 두 항목에 대한 답이다. 코드가 이 결정을
#: **검사**하고(아래 `_sharing_gate`·`_assert_private`), dataset card 에도 그대로 싣는다.
#: "언급은 해 두고 진행한다" 가 지시였으므로, 말은 여기에 남기고 강제는 코드가 한다.
SHARING_DECISION: List[str] = [
    "팀원은 제3자가 아니다 — 같은 프로젝트의 구성원이고, 공유 대상은 팀 안으로 한정한다.",
    "공공누리 '변경금지' 항목은 **학습 용도로 private Organization 안에 두고 공유·회수**"
    "하는 방식으로 다룬다. 지금까지 팀이 써 온 방식과 같다.",
    "그래서 이 저장소는 **반드시 private** 이어야 한다. 업로드 직전에 원격 공개 범위를"
    " 실제로 조회하고, public 이면 올리지 않고 멈춘다.",
    "원자료(raw_response)까지 올리는 이유는 **백업의 완전성** 이다 — 로컬 SQLite 를"
    " 지워도 되게 하려면 감사 근거와 수집 이력이 함께 있어야 한다.",
    "이것은 학습 프로젝트 범위의 운영 판단이며 법률 자문이 아니다. 출처 약관이 바뀌거나"
    " 공개 범위가 바뀌면 이 결정을 다시 한다.",
]


# ==================================================
# 2. 표 명세 — 무엇을 어떻게 내보내는가
# ==================================================
#
# `partition` 은 셋 중 하나다.
#   "year"   연도별 파일 (`year=2020/part-00000.parquet`). `date_col` 로 가른다.
#   "column" 어떤 칸의 값별 파일 (`portal.parquet`). `partition_col` 로 가른다.
#            ⚠️ 하이브 폴더(`source=portal/`)를 쓰지 않는다 — 머리말 ② 참조.
#   None     통째로 한 파일.
#
# `sort` 는 파일 안 정렬 — 증분 업로드를 위해 **날짜가 앞**이다(머리말 참조).
# `fetch_rows` 는 배치(=로우그룹) 행 수. 한 행이 큰 표만 따로 준다.
# `heavy` 는 "값 게이트를 기본으로 돌리기엔 너무 큰 표" 라는 뜻이다(`verify --deep`).
# `raw` 는 "이것은 출처 응답 그 자체" 라는 뜻이다 — `RAW_SHARING` 게이트 대상.
TABLES: Dict[str, Dict] = {
    "price_daily": {
        "partition": "year", "date_col": "bas_dt",
        "sort": ("bas_dt", "srtn_cd"),
        "why": "정규화한 일별 시세. 모든 파생표의 뿌리",
        "optional": False, "heavy": True,
    },
    "price_adjusted": {
        "partition": "year", "date_col": "bas_dt",
        "sort": ("bas_dt", "srtn_cd"),
        "why": "수정주가(PR). 분할·권리락만 고친 계열",
        "optional": False, "heavy": True,
    },
    "price_total_return": {
        "partition": "year", "date_col": "bas_dt",
        "sort": ("bas_dt", "srtn_cd"),
        "why": "총수익(TR) 계열. 배당까지 더한 계열",
        "optional": False, "heavy": True,
    },
    "dividend": {
        "partition": None, "date_col": "record_dt",
        "sort": ("record_dt", "srtn_cd"),
        "why": "배당 공시에서 읽은 사실. 시세 표에 안 나타난다",
        "optional": False,
    },
    "corporate_action": {
        "partition": None, "date_col": "bas_dt",
        "sort": ("bas_dt", "srtn_cd"),
        "why": "가격이 끊긴 날과 그 계수",
        "optional": False,
    },
    "benchmark_index": {
        "partition": None, "date_col": "bas_dt",
        "sort": ("bas_dt", "mrkt_ctg", "variant"),
        "why": "벤치마크 지수(자체 재현치). KRX 공식 지수가 아니다",
        # ⚠️ 이 표는 `collector/benchmark.py` 가 아직 만들지 않았을 수 있다.
        #    없으면 조용히 건너뛰고 '아직 없다'고만 말한다 — 막다른 길로 만들지 않는다.
        "optional": True,
    },
    # ── 2026-09-20 추가: 여기부터는 '분석용'이 아니라 '복구용'이다 ──────────────
    "raw_response": {
        # 출처별로 가른다. portal 은 매일 172KB 씩 자라고 dart 는 달 단위로 움직여
        # **갱신 주기가 다르다** — 다른 것은 파일도 나눈다(머리말의 표별 분리와 같은 이유).
        "partition": "column", "partition_col": "source", "date_col": "fetched_at",
        "sort": ("fetched_at", "source", "target"),
        # 한 행이 평균 23KB·최대 183KB 다. 256행이면 배치가 최대 47MB 로 묶인다.
        "fetch_rows": 256,
        "why": "응답 원문(gzip BLOB). 재정규화의 유일한 재료이자 감사 근거",
        "optional": False, "raw": True, "restore_only": True,
    },
    "ingest_day": {
        "partition": None, "date_col": "bas_dt",
        "sort": ("bas_dt", "source"),
        "why": "기준일별 수집 상태. 중단·재개와 휴장 판정의 근거",
        "optional": False, "restore_only": True,
    },
}

#: 올리지 않는 표와 그 이유.
#:
#: **지금은 비어 있다.** 2026-09-20 에 `raw_response`·`ingest_day` 를 대상에 넣으면서
#: 제외 표가 없어졌다. 빈 dict 를 남겨 두는 이유는 두 가지다 —
#:   ① 나중에 정말 뺄 표가 생기면 **이유와 함께** 여기 적게 하려고,
#:   ② `status` 가 "DB 에는 있는데 TABLES 에도 EXCLUDED 에도 없는 표" 를 찾아내
#:      **백업에서 조용히 빠지는 표**를 잡아내려고.
EXCLUDED: Dict[str, str] = {}

#: SQLite 선언 타입 → arrow 타입. TEXT 는 string, INTEGER 는 int64, REAL 은 float64,
#: BLOB 은 binary(원문 바이트를 그대로 담는다 — 문자열로 바꾸면 인코딩 추측이 끼어들고
#: 그 순간 원문이 아니게 된다. `collector/raw_store.py` 머리말과 같은 이유다).
#: int32 로 줄이지 않는 이유: `mrkt_tot_amt` 가 수백조(5e14)까지 간다 — int32 로는
#: 조용히 넘친다. 크기보다 **틀리지 않는 쪽**을 고른다.
_SQLITE_TO_ARROW = {"TEXT": "string", "INTEGER": "int64", "REAL": "float64",
                    "BLOB": "binary"}


# ==================================================
# 3. 잔손질
# ==================================================
class _SkipDbGates(Exception):
    """원본 DB 가 없어 DB 대조 게이트를 건너뛴다는 내부 신호. 밖으로 새지 않는다."""


def _ro_connect(path: Optional[Path] = None) -> sqlite3.Connection:
    """**읽기 전용** 연결.

    `db.connect()` 를 쓰지 않는 이유는 그것이 매 연결마다 `executescript(SCHEMA)` 를
    돌려 표를 만들기 때문이다 — 내보내기는 읽는 일이다. 다른 프로세스가 수집·계산을
    돌리는 중에도 안전하게 붙으려면 읽기 전용이어야 한다.

    경로만은 `config.DB_PATH` 를 쓴다. 문자열로 박으면 언젠가 오기한다.
    """
    p = path or config.DB_PATH
    if not p.exists():
        raise SystemExit(
            f"SQLite 가 없다: {p}\n"
            f"  할 일: `python -m collector.backfill` 로 시세를 먼저 받는다.\n"
            f"         이미 파케이로 내보낸 적이 있다면 "
            f"`python scripts/hf_dataset.py restore --into {p}` 로 되살린다.")
    uri = f"file:{p.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=60000")
    return conn


def _ro_connect_opt() -> Optional[sqlite3.Connection]:
    """DB 가 없으면 **죽지 않고 None** 을 돌려준다.

    왜 필요한가 — 이 스크립트의 목적이 "로컬 SQLite 를 지워도 되게 하는 것" 이다.
    지운 다음에도 `status`·`verify` 가 돌아야 백업이 아직 온전한지 확인할 수 있다.
    원본이 없으면 DB 와 대조하는 게이트만 건너뛰고, 파일 지문 게이트는 그대로 돈다.
    """
    return _ro_connect() if config.DB_PATH.exists() else None


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def _db_tables(conn: sqlite3.Connection) -> List[str]:
    """DB 에 실제로 있는 표 이름. `sqlite_*` 내부 표는 뺀다."""
    return [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name")]


def _columns(conn: sqlite3.Connection, table: str) -> List[Tuple[str, str]]:
    """[(칸 이름, 선언 타입)] — 선언 순서 그대로."""
    return [(r[1], (r[2] or "TEXT").upper()) for r in conn.execute(f"PRAGMA table_info({table})")]


def _ddl(conn: sqlite3.Connection, table: str) -> Dict[str, object]:
    """그 표를 다시 만드는 **DDL 원문**. 매니페스트에 담아 파케이와 함께 들고 나간다.

    왜 `collector/db.py` 의 SCHEMA 상수를 쓰지 않는가 —
      ① `benchmark_index` 는 거기에 없다(`collector/benchmark.py` 가 만든다). 한쪽만
         보면 표 하나가 통째로 빠진다.
      ② 백업은 **자기 자신만으로 복구 가능**해야 한다. 파케이를 받은 사람이 우리
         저장소 코드를 안 가지고 있어도 되살릴 수 있어야 한다.
    `sqlite_autoindex_*` 는 `sql` 이 NULL 이다 — PK 가 만드는 암묵 인덱스라
    CREATE TABLE 이 다시 만들어 준다. 그래서 건너뛴다.
    """
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    idx = [r[0] for r in conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name=? "
        "AND sql IS NOT NULL ORDER BY name", (table,))]
    return {"table": row[0] if row else "", "indexes": idx}


def _arrow_schema(cols: Sequence[Tuple[str, str]]):
    import pyarrow as pa
    fields = []
    for name, decl in cols:
        t = _SQLITE_TO_ARROW.get(decl)
        if t is None:                       # 모르는 타입이면 문자열로 떨어뜨린다
            t = "string"
        fields.append(pa.field(name, getattr(pa, t)()))
    return pa.schema(fields)


def _sha256(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(chunk), b""):
            h.update(b)
    return h.hexdigest()


def _human(n: float) -> str:
    """바이트를 사람이 읽는 단위로. 숫자는 늘 `:,` 관례를 따른다."""
    for unit in ("B", "KB", "MB", "GB"):
        if abs(n) < 1024 or unit == "GB":
            return f"{n:,.1f} {unit}" if unit != "B" else f"{n:,.0f} B"
        n /= 1024.0
    return f"{n:,.1f} GB"


def _now_kst() -> str:
    return datetime.datetime.now(KST).isoformat(timespec="seconds")


def _git_head() -> str:
    """수집기 커밋 해시. 매니페스트에 적어 '어느 코드가 만든 파일인가'를 남긴다."""
    try:
        out = subprocess.run(
            ["git", "-C", str(config.ROOT), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=10)
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def _years(conn: sqlite3.Connection, table: str, date_col: str) -> List[str]:
    """그 표에 실제로 있는 연도. 달력을 만들어 넣지 않고 **자료에 물어본다.**"""
    return [r[0] for r in conn.execute(
        f"SELECT DISTINCT substr({date_col},1,4) y FROM {table} ORDER BY y") if r[0]]


def _partitions(conn: sqlite3.Connection, table: str, spec: Dict,
                years: Optional[List[str]] = None) -> List[Optional[str]]:
    """이 표를 어떤 조각으로 나눌 것인가. 조각 이름 목록(또는 [None])을 돌려준다."""
    mode = spec["partition"]
    if mode is None:
        return [None]
    if mode == "year":
        vals = _years(conn, table, spec["date_col"])
        if years:
            vals = [y for y in vals if y in years]
        return vals
    if mode == "column":
        col = spec["partition_col"]
        return [r[0] for r in conn.execute(
            f"SELECT DISTINCT {col} v FROM {table} ORDER BY v") if r[0]]
    raise SystemExit(f"모르는 partition 모드: {mode!r} (year · column · None 만 있다)")


def _part_where(spec: Dict, part: Optional[str]) -> Tuple[str, Tuple]:
    """파티션을 고르는 WHERE 절과 파라미터."""
    if part is None:
        return "", ()
    if spec["partition"] == "year":
        # ⚠️ 문자열 비교. `bas_dt` 는 TEXT 다.
        return (f" WHERE {spec['date_col']}>=? AND {spec['date_col']}<=?",
                (YEAR_LO.format(y=part), YEAR_HI.format(y=part)))
    return f" WHERE {spec['partition_col']}=?", (part,)


def _part_path(table: str, spec: Dict, part: Optional[str]) -> Path:
    """그 파티션이 쓰일 파일 경로.

    ⚠️ `column` 모드는 하이브 폴더(`source=portal/`)를 쓰지 않는다 — 하이브 키가
       실제 칸 이름과 겹치면 `pq.read_table` 이 타입 병합에 실패해 죽는다(머리말 ②).
    """
    if part is None:
        return EXPORT_DIR / table / f"{table}.parquet"
    if spec["partition"] == "year":
        return EXPORT_DIR / table / f"year={part}" / "part-00000.parquet"
    return EXPORT_DIR / table / f"{part}.parquet"


def _count(conn: sqlite3.Connection, table: str, spec: Dict, part: Optional[str]) -> int:
    where, params = _part_where(spec, part)
    return conn.execute(f"SELECT COUNT(*) FROM {table}{where}", params).fetchone()[0]


def _sig_exprs(cols: Sequence[Tuple[str, str]]) -> List[str]:
    """내용 지문을 만드는 집계식들. **한 번의 스캔**으로 전부 구한다."""
    parts = ["COUNT(*)"]
    for n, d in cols:
        if d in ("INTEGER", "REAL"):
            parts += [f"TOTAL({n})", f"SUM({n} IS NULL)", f"MIN({n})", f"MAX({n})"]
        elif d == "BLOB":
            # BLOB 은 MIN/MAX 를 빼고 길이 합만 본다 — 바이트열 비교는 비싸고,
            # raw_response 는 PK 에 fetched_at 이 들어 있어 내용이 바뀌면 행이 는다.
            parts += [f"TOTAL(LENGTH({n}))", f"SUM({n} IS NULL)"]
        else:
            parts += [f"TOTAL(LENGTH({n}))", f"SUM({n} IS NULL)",
                      f"MIN({n})", f"MAX({n})"]
    return parts


def _quant(v):
    """실수는 유효숫자 10자리로 깎아서 지문에 넣는다.

    왜 깎는가 — SQLite 의 `TOTAL()` 은 **스캔 순서대로** 더한다. `preprocess.py` 가
    종목 단위로 DELETE 후 재삽입하면 rowid 가 바뀌어 물리 순서가 달라지고, 그러면
    **값이 하나도 안 바뀌어도** 합의 끝자리가 흔들린다. 4.46M 항 누산의 부동소수
    오차는 대략 sqrt(N)·eps ≈ 4e-13(상대)이라, 10자리에서 자르면 그 흔들림은 사라지고
    실제 변경(보통 1e-6 이상)은 그대로 잡힌다.
    """
    if isinstance(v, float):
        return f"{v:.10g}"
    return v


def _content_sig(conn: sqlite3.Connection, table: str, spec: Dict,
                 part: Optional[str], cols: Optional[Sequence[Tuple[str, str]]] = None) -> str:
    """파티션의 **내용** 지문 16자리.

    왜 필요한가 — 예전 판은 `COUNT(*)` 와 파일 바이트 수만 보고 "그대로다" 를 판정했다.
    그런데 이 수집기의 **정상 경로가 바로 행수 불변 갱신**이다:
      · `preprocess.py:257` 종목 단위 DELETE 후 재삽입 → `cum_factor`·`adj_clpr` 변경
      · `total_return.py:308` TR 재계산 → `tr_index` 변경
      · `sources/dart.py:627` 정정공시 upsert → 같은 PK 의 값 변경
    행수는 그대로이고 파일은 이미 있으니 **영원히 다시 내보내지 않는다.** 그래서
    판정을 내용 기반으로 바꾼다.

    🟡 무엇을 못 잡는가 — 길이가 같은 문자열끼리 맞바꾸면서 MIN·MAX 까지 유지되는
       변경은 못 잡는다(예: 중간 순위 종목명 한 글자 교체). 전 행 해시가 유일한 완전
       해법인데 4.46M 행 × 3표에 수십 초가 더 든다. 지금은 잡아야 할 실제 경로 셋을
       전부 덮으므로 여기서 멈춘다 — 의심되면 `--force` 로 다시 낸다.
    """
    cols = cols if cols is not None else _columns(conn, table)
    where, params = _part_where(spec, part)
    sql = "SELECT " + ", ".join(_sig_exprs(cols)) + f" FROM {table}{where}"
    row = conn.execute(sql, params).fetchone()
    payload = json.dumps([_quant(v) for v in row], ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _rel(p: Path) -> str:
    """내보내기 폴더 기준 상대 경로. 매니페스트·HF 양쪽이 같은 문자열을 쓴다."""
    return p.relative_to(EXPORT_DIR).as_posix()


def _rel_root(p: Path) -> str:
    try:
        return p.relative_to(config.ROOT).as_posix()
    except ValueError:
        return str(p)


def _write_json_atomic(path: Path, obj: Dict) -> None:
    """**원자적으로** 쓴다 — 임시 파일에 쓰고 `os.replace` 로 갈아 끼운다.

    `write_text` 는 원자적이지 않다. 270MB 를 내보내는 도중 전원이 나가면 매니페스트가
    반쪽으로 남고, 다음 실행이 그것을 읽어 **재개가 통째로 망가진다.** 같은 볼륨 안의
    `os.replace` 는 POSIX·Windows 모두 원자적이다.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _load_manifest(path: Optional[Path] = None) -> Dict:
    p = path or MANIFEST_PATH
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _manifest_fp(man: Dict) -> str:
    """매니페스트의 **파일 구성** 지문. 검증·복구 기록을 여기에 묶는다.

    `generated_at` 만으로 묶으면 `--years 2026` 처럼 일부만 다시 내보냈을 때도 전부
    무효가 된다. 반대로 아무것도 안 묶으면 옛 검증 기록이 새 파일에 초록을 준다.
    파일 경로+지문의 해시가 그 사이에서 정확하다.
    """
    items = sorted((f["path"], f.get("sha256", ""))
                   for t in man.get("tables", {}).values() for f in t.get("files", []))
    return hashlib.sha256(json.dumps(items).encode("utf-8")).hexdigest()[:16]


def _stray_parts() -> List[Path]:
    """`.part` 반쪽 파일. 내보내기가 SIGKILL 로 끊기면 남는다.

    ⚠️ 이것이 원격에 올라가면 받는 쪽이 깨진 파케이를 정상 파일로 오인한다.
       `verify` 가 실패로 잡고, `upload` 는 `ignore_patterns` 로 한 번 더 막는다.
    """
    if not EXPORT_DIR.exists():
        return []
    return sorted(EXPORT_DIR.rglob("*.part"))


def _token(required: bool = True) -> Optional[str]:
    """HF 토큰. **절대 출력하지 않는다.**

    `collector/config.py` 의 `.env` 읽기 방식을 그대로 쓴다 — 환경변수가 먼저고,
    없으면 저장소 루트 `.env` 를 본다. python-dotenv 를 쓰지 않는 것도 같은 이유
    (의존성을 하나라도 덜 만든다).
    """
    if required:
        return config.require(
            "HUGGINGFACE_ACCESS_TOKEN",
            "Hugging Face 접근 토큰 (write 권한 · huggingface.co/settings/tokens)")
    return config.env("HUGGINGFACE_ACCESS_TOKEN") or None


# ── 공유 게이트 ───────────────────────────────────────────────────────────────
def _sharing_on() -> bool:
    """`RAW_SHARING` 이 켜져 있는가.

    스위치의 **정의는 `collector/manifest.py` 한 곳**이다. 여기서 `os.environ` 을 다시
    읽지 않는 이유는, 같은 이름의 스위치가 두 군데서 따로 해석되면 한쪽만 켜진 상태가
    생기기 때문이다. 다만 모듈 import 시점에 한 번 굳는 값이라, 프로세스 안에서 환경을
    바꿔 켜는 경우(테스트)까지 보려고 환경변수도 함께 본다.
    """
    if collector_manifest.RAW_SHARING:
        return True
    return os.environ.get("QURIOUS_RAW_SHARING", "").lower() in ("1", "true", "yes")


def _sharing_gate(what: str, hint: str = "") -> None:
    """꺼져 있으면 **켜는 법까지 말하고** 멈춘다. 막다른 길로 만들지 않는다."""
    if _sharing_on():
        return
    decision = "\n".join(f"    · {line}" for line in SHARING_DECISION)
    raise SystemExit(
        f"QURIOUS_RAW_SHARING 이 꺼져 있어 {what} 을(를) 하지 않는다.\n"
        f"\n"
        f"  이 스위치는 `collector/manifest.py` 가 정의한다. 원자료를 팀 밖으로 내보내는\n"
        f"  일이라 기본이 꺼짐이고, 켜는 근거는 아래 팀 결정이다:\n"
        f"{decision}\n"
        f"\n"
        f"  ⚠️ **환경변수로만 켜진다. `.env` 에 적어도 켜지지 않는다**\n"
        f"     (`collector/manifest.py` 가 `os.environ` 만 읽는다 — 실수로 켜진 채\n"
        f"      커밋되는 것을 막으려는 설계다).\n"
        f"\n"
        f"  할 일:\n"
        f"    PowerShell   $env:QURIOUS_RAW_SHARING=\"1\"\n"
        f"    bash         export QURIOUS_RAW_SHARING=1\n"
        f"  그런 다음 같은 셸에서 이 명령을 다시 돌린다."
        + (f"\n\n  {hint}" if hint else ""))


# ==================================================
# 4. export — SQLite → 파케이
# ==================================================
def _write_partition(conn: sqlite3.Connection, table: str, spec: Dict,
                     part: Optional[str], out: Path, verbose: bool) -> Dict:
    """한 파티션(= 파일 하나)을 쓴다. 스트리밍이라 메모리는 배치 하나뿐이다.

    전 표를 메모리에 올리지 않는 것이 요점이다 — `price_daily` 는 4,460,710행이고
    파이썬 객체로 펴면 수 GB 가 된다. `fetchmany` 로 배치씩 끌어 곧바로 arrow 배치로
    바꾸고 로우그룹 하나로 흘려보낸다.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    cols = _columns(conn, table)
    names = [c for c, _ in cols]
    schema = _arrow_schema(cols)
    order = ", ".join(spec["sort"])
    where, params = _part_where(spec, part)
    fetch = int(spec.get("fetch_rows") or FETCH_ROWS)

    sql = f"SELECT {', '.join(names)} FROM {table}{where} ORDER BY {order}"

    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".parquet.part")   # 중간에 죽어도 온전한 파일이 남지 않게
    if tmp.exists():
        tmp.unlink()

    writer_opts = {k: v for k, v in PARQUET_OPTS.items() if k != "row_group_size"}
    cur = conn.execute(sql, params)
    rows_written = 0
    t0 = time.time()
    writer = pq.ParquetWriter(str(tmp), schema, **writer_opts)
    try:
        while True:
            chunk = cur.fetchmany(fetch)
            if not chunk:
                break
            # 행 → 열 전치. sqlite3.Row 는 시퀀스라 zip(*) 이 그대로 먹는다.
            columnar = list(zip(*chunk))
            batch = pa.RecordBatch.from_arrays(
                [pa.array(columnar[i], type=schema.field(i).type) for i in range(len(names))],
                schema=schema)
            writer.write_batch(batch)
            rows_written += len(chunk)
            if verbose:
                # 진행률 — 이 루프는 수 분이 걸릴 수 있어 조용하면 멈춘 줄 안다.
                print(f"\r    {table}{'/' + part if part else ''} … {rows_written:,}행",
                      end="", flush=True)
    except Exception:
        writer.close()
        tmp.unlink(missing_ok=True)
        raise
    writer.close()

    if out.exists():
        out.unlink()
    tmp.rename(out)
    dt = time.time() - t0
    size = out.stat().st_size
    if verbose:
        print(f"\r    {table}{'/' + part if part else ''}  {rows_written:,}행 · "
              f"{_human(size)} · {dt:,.1f}초" + " " * 12)
    return {
        "path": _rel(out), "rows": rows_written, "bytes": size,
        "sha256": _sha256(out), "seconds": round(dt, 2),
    }


def export(tables: Optional[List[str]] = None, years: Optional[List[str]] = None,
           force: bool = False, verbose: bool = True) -> Dict:
    """SQLite 를 파케이로 내보낸다.

    **재개 가능하다.** 이미 내보낸 파티션은 매니페스트의 **내용 지문**(`sig`)과 지금
    DB 의 지문을 대조해 **같으면 건너뛴다.** 행수만 보던 예전 판은 값만 바뀐 갱신을
    영원히 놓쳤다(`_content_sig` 머리말). 닫힌 연도(2020~2025)는 두 번 다시 건드리지
    않는다 — 이것이 증분 업로드가 0바이트로 끝나는 이유다.

    `--force` 는 그 판단을 무시하고 전부 다시 쓴다. 파케이 옵션을 바꿨을 때만 쓴다
    (그리고 그때는 HF 중복제거가 전부 무효가 된다는 것을 알고 써야 한다).

    ★ 매니페스트를 **표 하나 끝날 때마다** 원자적으로 쓴다. 예전 판은 맨 끝에 한 번만
      써서, 270MB 중 200MB 를 낸 뒤 죽으면 그 성과가 통째로 사라졌다.
    """
    conn = _ro_connect()
    prev = _load_manifest()
    prev_files = {f["path"]: f for t in prev.get("tables", {}).values() for f in t.get("files", [])}

    picked = tables or list(TABLES)
    unknown = [t for t in picked if t not in TABLES]
    if unknown:
        raise SystemExit(
            f"모르는 표: {', '.join(unknown)}\n"
            f"  쓸 수 있는 표: {', '.join(TABLES)}")

    # 원자료 표가 대상에 들어 있으면 공유 스위치를 확인한다.
    raw_picked = [t for t in picked if TABLES[t].get("raw")]
    if raw_picked:
        others = ",".join(t for t in TABLES if not TABLES[t].get("raw"))
        _sharing_gate(
            f"원자료 표({', '.join(raw_picked)}) 내보내기",
            hint=("원자료를 빼고 나머지만 내보내려면:\n"
                  f"    python scripts/hf_dataset.py export --tables {others}\n"
                  "  ⚠️ 다만 그 사본으로는 로컬 SQLite 를 지울 수 없다 — 감사 근거"
                  "(raw_response)와\n     수집 이력(ingest_day)이 빠진 '부분 사본'이다."))

    out_tables: Dict[str, Dict] = dict(prev.get("tables", {}))
    tally = {"tables": 0, "files": 0, "rows": 0, "bytes": 0, "skipped": 0, "missing": []}
    t_start = time.time()

    def _flush(partial: bool) -> Dict:
        """지금까지의 결과를 매니페스트로 남긴다. 중간에 죽어도 여기까지는 남는다."""
        man = {
            "generated_at": _now_kst(),
            "repo_id": REPO_ID,
            "collector_commit": _git_head(),
            # ⚠️ 사용자 절대경로를 적지 않는다 — 그대로 HF 로 올라간다.
            "db_relpath": _rel_root(config.DB_PATH),
            "db_bytes": config.DB_PATH.stat().st_size,
            "parquet_opts": {k: v for k, v in PARQUET_OPTS.items()},
            "excluded": EXCLUDED,
            "sharing_decision": SHARING_DECISION,
            "partial": partial,          # 아직 내보내는 중인가
            "tables": out_tables,
        }
        if prev.get("uploaded"):         # 업로드 기록은 export 가 지우지 않는다
            man["uploaded"] = prev["uploaded"]
        _write_json_atomic(MANIFEST_PATH, man)
        return man

    try:
        for name in picked:
            spec = TABLES[name]
            exists = _table_exists(conn, name)
            # 표가 **있어도 비어 있을 수 있다.** `db.connect()` 가 매 연결마다
            # `executescript(SCHEMA)` 를 돌리므로 계산 모듈을 아직 안 돌렸어도 빈 표는
            # 생긴다. 빈 파케이를 올리면 받는 쪽이 '값이 0 이다' 로 오해하므로 건너뛴다.
            if not exists or (spec["optional"] and not conn.execute(
                    f"SELECT EXISTS(SELECT 1 FROM {name})").fetchone()[0]):
                if spec["optional"]:
                    tally["missing"].append(name)
                    out_tables.pop(name, None)
                    if verbose:
                        print(f"  · {name} — {'아직 없다' if not exists else '아직 비어 있다'}"
                              f"(건너뜀). `python -m collector.benchmark build` 로 만든다")
                    continue
                raise SystemExit(f"{name} 표가 DB 에 없다 — 수집·전처리를 먼저 돌린다")

            parts = _partitions(conn, name, spec, years)
            cols = _columns(conn, name)
            if verbose:
                print(f"  {name} — {spec['why']}")

            files: List[Dict] = []
            # 연도 필터를 걸었으면 손대지 않은 조각의 기록은 그대로 물려받는다.
            keep = {f["path"]: f for f in out_tables.get(name, {}).get("files", [])}
            for pv in parts:
                out = _part_path(name, spec, pv)
                want = _count(conn, name, spec, pv)
                sig = _content_sig(conn, name, spec, pv, cols)
                old = prev_files.get(_rel(out))
                # ★ 건너뛰기 판정은 **내용 기반**이다. 행수·바이트만 보면 값만 바뀐
                #   갱신을 영원히 놓친다. `sig` 가 없는 옛 매니페스트는 건너뛰지 않는다.
                if (not force and old and out.exists()
                        and old.get("rows") == want
                        and out.stat().st_size == old.get("bytes")
                        and old.get("sig") and old.get("sig") == sig):
                    files.append(old)
                    keep.pop(old["path"], None)
                    tally["skipped"] += 1
                    if verbose:
                        print(f"    {name}{'/' + pv if pv else ''}  {want:,}행 — 그대로 (건너뜀)")
                    continue
                info = _write_partition(conn, name, spec, pv, out, verbose)
                info["sig"] = sig
                files.append(info)
                keep.pop(info["path"], None)
                tally["files"] += 1
                tally["rows"] += info["rows"]
                tally["bytes"] += info["bytes"]
            # 연도 필터로 이번에 안 건드린 파일들
            for p, f in keep.items():
                if (EXPORT_DIR / p).exists():
                    files.append(f)
            files.sort(key=lambda f: f["path"])
            out_tables[name] = {
                "rows": sum(f["rows"] for f in files),
                "bytes": sum(f["bytes"] for f in files),
                "why": spec["why"],
                "sort": list(spec["sort"]),
                "partition": spec["partition"],
                "partition_col": spec.get("partition_col"),
                "fetch_rows": int(spec.get("fetch_rows") or FETCH_ROWS),
                "restore_only": bool(spec.get("restore_only")),
                # ★ 스키마를 함께 들고 나간다 — 이것이 있어야 파케이만으로 복구된다.
                "ddl": _ddl(conn, name),
                "files": files,
            }
            tally["tables"] += 1
            _flush(partial=True)          # 표 하나 끝날 때마다 남긴다
    finally:
        conn.close()

    man = _flush(partial=False)
    # dataset card 는 내보내기 산출물의 일부다 — 여기서 함께 만들어 두면 올리기 전에
    # 사람이 읽어 볼 수 있다.
    README_PATH.write_text(_readme_yaml(man), encoding="utf-8")
    tally["seconds"] = round(time.time() - t_start, 1)
    tally["total_bytes"] = sum(t["bytes"] for t in out_tables.values())
    tally["total_rows"] = sum(t["rows"] for t in out_tables.values())
    return tally


# ==================================================
# 5. status — 로컬과 원격이 같은 곳을 보고 있는가 · 지금 지워도 되는가
# ==================================================
def _gitignored(path: Path) -> Optional[bool]:
    """이 경로가 git 에 무시되는가. 판단이 안 서면 None.

    ⚠️ `check-ignore -q` 의 exit 0 만 믿지 않는다 — `.gitignore` 에 빈 줄이 있으면
       가짜로 매치가 잡힌 사례가 있었다(2026-09-20). 그래서 `-v` 로 **어느 규칙에
       걸렸는지**까지 받아, 규칙 문자열이 비어 있으면 '모름'으로 돌린다.
    """
    try:
        r = subprocess.run(["git", "-C", str(config.ROOT), "check-ignore", "-v", str(path)],
                           capture_output=True, text=True, timeout=10)
        if r.returncode != 0:
            return False
        line = (r.stdout or "").strip()
        if not line:
            return None
        # 형식: <파일>:<줄번호>:<규칙>\t<대상>. 규칙 칸이 비어 있으면 가짜 매치다.
        head = line.split("\t")[0]
        rule = head.split(":")[-1].strip()
        return bool(rule)
    except Exception:
        return None


def _deletion_verdict(man: Dict, db_counts: Dict[str, int], remote_ok: Optional[bool],
                      db_present: bool = True) -> List[Tuple[Optional[bool], str, str]]:
    """**"지금 로컬 SQLite 를 지워도 되는가"** — 조건을 하나씩 판정한다.

    True=충족 · False=미충족 · None=확인 안 됨. `None` 을 `True` 로 치지 않는 것이
    핵심이다 — 확인하지 않은 것은 통과가 아니다.
    """
    out: List[Tuple[Optional[bool], str, str]] = []
    fp = _manifest_fp(man) if man else ""

    # ① 표를 하나도 빠뜨리지 않았는가
    covered = set(man.get("tables", {}))
    need = {n for n, s in TABLES.items() if not s["optional"]}
    miss = sorted(need - covered)
    unmapped = sorted(set(db_counts) - set(TABLES) - set(EXCLUDED))
    ok1 = not miss and not unmapped
    out.append((ok1, "DB 의 모든 표가 백업 대상에 들어 있다",
                "전부 포함" if ok1 else
                f"빠진 표: {', '.join(miss + unmapped) or '없음'}"))

    # ② 행수가 DB 와 일치하는가
    if not db_present:
        out.append((None, "파케이 행수 = 지금 DB 행수",
                    "원본이 이미 없다 — 대조할 상대가 없다"))
    else:
        bad = [n for n, rec in man.get("tables", {}).items()
               if n in db_counts and rec["rows"] != db_counts[n]]
        ok2 = bool(man) and not bad
        out.append((ok2, "파케이 행수 = 지금 DB 행수",
                    "일치" if ok2 else f"어긋남: {', '.join(bad) or '매니페스트 없음'}"))

    # ③ 파일이 다 있고 `.part` 가 남아 있지 않은가
    missing_f = [f["path"] for t in man.get("tables", {}).values() for f in t["files"]
                 if not (EXPORT_DIR / f["path"]).exists()]
    parts = _stray_parts()
    ok3 = bool(man) and not missing_f and not parts
    out.append((ok3, "내보낸 파일이 전부 디스크에 있다",
                "전부 있다" if ok3 else
                f"없는 파일 {len(missing_f)}개 · 반쪽(.part) {len(parts)}개"))

    # ④ verify --deep 이 이 매니페스트에 대해 통과했는가
    v = _load_manifest(VERIFY_LOG_PATH)
    if not v:
        ok4, why = None, "기록 없음 — `verify --deep` 을 돌린다"
    elif v.get("manifest_fp") != fp:
        ok4, why = None, "기록이 옛 매니페스트 것이다 — `verify --deep` 을 다시 돌린다"
    elif v.get("db_present") is False:
        ok4, why = None, "원본 없이 돌린 기록이다 — 파일 지문까지만 확인됐다"
    elif not v.get("deep"):
        ok4, why = None, "`--deep` 없이 돌렸다 — 큰 표의 값 게이트를 안 봤다"
    else:
        ok4 = v.get("fails") == 0
        why = f"{v.get('at','?')} · 어긋남 {v.get('fails')}건"
    out.append((ok4, "verify --deep 이 통과했다 (지문·행수·스키마·값)", why))

    # ⑤ 파케이만으로 SQLite 가 실제로 되살아났는가 (리허설)
    r = _load_manifest(RESTORE_LOG_PATH)
    if not r:
        ok5, why = None, "기록 없음 — `restore` 로 리허설한다"
    elif r.get("manifest_fp") != fp:
        ok5, why = None, "기록이 옛 매니페스트 것이다 — `restore` 를 다시 돌린다"
    else:
        ok5 = bool(r.get("ok"))
        why = (f"{r.get('at','?')} · {r.get('rows',0):,}행 복원 · "
               f"내용지문 {r.get('sig_ok',0)}/{r.get('sig_total',0)} 일치 · "
               f"원문 sha256 {r.get('raw_ok',0)}/{r.get('raw_total',0)} 일치")
    out.append((ok5, "복구 리허설이 성공했다 (파케이 → SQLite)", why))

    # ⑥ 원격에 올라갔는가
    up = man.get("uploaded") or {}
    files = {f["path"]: f["sha256"] for t in man.get("tables", {}).values() for f in t["files"]}
    if remote_ok is True:
        ok6, why = True, "원격 조회로 확인했다"
    elif remote_ok is False:
        ok6, why = False, "원격과 다른 파일이 있다 — `upload --yes` 를 먼저"
    elif not up:
        ok6, why = False, "업로드 기록이 없다 — `upload --yes` 를 먼저"
    else:
        same = [p for p, s in files.items() if up.get("files", {}).get(p) == s]
        ok6 = len(same) == len(files)
        why = (f"로컬 기록 기준 {len(same):,}/{len(files):,}개 일치"
               f" ({up.get('at','?')}) · 확실히 하려면 `status --remote`")
        if ok6:
            ok6 = None      # 로컬 기록만으로는 원격을 증명하지 못한다
    out.append((ok6, "원격(HF)에 올라가 있다", why))
    return out


def status(remote: bool = False) -> None:
    print("― HF 데이터셋 현황 ―")
    man = _load_manifest()
    if not man:
        print("  아직 없다. `python scripts/hf_dataset.py export` 로 만든다.")
    else:
        print(f"  {man.get('generated_at','?')} 생성 · 수집기 {man.get('collector_commit','?')}"
              + ("  ⚠️ 내보내는 중에 끊긴 기록이다" if man.get("partial") else ""))
        tot_b = sum(t["bytes"] for t in man["tables"].values())
        tot_r = sum(t["rows"] for t in man["tables"].values())
        nf = sum(len(t["files"]) for t in man["tables"].values())
        print(f"  {_human(tot_b)} · {nf:,}파일 · {tot_r:,}행 · 저장소 {man.get('repo_id','?')}")
        db_b = man.get("db_bytes") or 0
        if db_b:
            print(f"  SQLite {_human(db_b)} 대비 {tot_b / db_b * 100:,.2f}%")

    # 내보낸 것과 지금 DB 가 어긋나 있는가 — 이것을 모르면 옛 스냅샷을 올린다
    print("\n― 표별 (매니페스트 vs 지금 DB) ―")
    conn = _ro_connect_opt()
    db_counts: Dict[str, int] = {}
    db_present = conn is not None
    if conn is None:
        print(f"    🟡 원본 SQLite 가 없다 — {_rel_root(config.DB_PATH)}")
        print("       이미 지웠다면 정상이다. 백업만 보고 판정한다.")
        for name, rec in man.get("tables", {}).items():
            print(f"    {name:<20} 파케이 {rec['rows']:>10,}행 · {_human(rec['bytes']):>10}")
        print(f"       되살리려면: python scripts/hf_dataset.py restore --into "
              f"{_rel_root(config.DB_PATH)}")
    try:
        for name in (_db_tables(conn) if conn is not None else []):
            db_counts[name] = conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
        for name, spec in (TABLES.items() if db_present else []):
            rec = man.get("tables", {}).get(name)
            tag = "  (복구용)" if spec.get("restore_only") else ""
            if name not in db_counts:
                print(f"    {name:<20} DB 에 없다"
                      + ("  (선택 표 — 아직 안 만들었다)" if spec["optional"] else "  ⚠️"))
                continue
            now = db_counts[name]
            if not rec:
                print(f"    {name:<20} DB {now:>10,}행  ·  아직 안 내보냈다{tag}")
                continue
            mark = "✅" if rec["rows"] == now else "⚠️ 다시 내보내야 한다"
            print(f"    {name:<20} DB {now:>10,}행  파케이 {rec['rows']:>10,}행 "
                  f"· {_human(rec['bytes']):>10}  {mark}{tag}")
        # 백업에서 조용히 빠지는 표를 잡는다 — 스키마가 늘었는데 아무도 안 고쳤을 때
        unmapped = sorted(set(db_counts) - set(TABLES) - set(EXCLUDED))
        if unmapped:
            print(f"    🔴 백업 대상에 없는 표: {', '.join(unmapped)} — "
                  f"TABLES 에 넣거나 EXCLUDED 에 이유를 적는다")
    finally:
        if conn is not None:
            conn.close()

    print("\n― 올리지 않는 표 ―")
    if EXCLUDED:
        for name, why in EXCLUDED.items():
            print(f"    {name:<20} {why}")
    else:
        print("    없다 — 2026-09-20 부터 DB 의 모든 표를 내보낸다 "
              "(raw_response·ingest_day 포함).")
        print("    이유: 로컬 SQLite 를 지우는 것이 목적이라, 감사 근거와 수집 이력이")
        print("          빠지면 '백업'이 아니라 '부분 사본'이 된다.")

    # Public 저장소에 270MB 파케이가 섞여 들어가는 사고를 막는다
    ig = _gitignored(EXPORT_DIR)
    print("\n― 주의 ―")
    if ig is False:
        print(f"  ⚠️ `{_rel_root(EXPORT_DIR)}` 가 .gitignore 에 없다 — 이 팀 저장소는 "
              f"**Public** 이다.\n"
              f"     할 일: .gitignore 에 `data/hf_export/` 한 줄을 넣는다.")
    elif ig is None:
        print(f"  🔴 `{_rel_root(EXPORT_DIR)}` 의 gitignore 여부를 확인하지 못했다 — "
              f"`git status --short` 로 직접 본다")
    else:
        print(f"  ✅ `{_rel_root(EXPORT_DIR)}` 는 .gitignore 돼 있다")

    parts = _stray_parts()
    if parts:
        print(f"  🔴 반쪽(.part) 파일 {len(parts)}개가 남아 있다 — 내보내기가 끊겼다.\n"
              f"     할 일: 지우고 `export` 를 다시 돌린다. (업로드는 자동으로 제외한다)")

    print(f"  {'✅' if _sharing_on() else '🔴'} QURIOUS_RAW_SHARING "
          f"{'켜짐 — 원자료 내보내기·업로드 가능' if _sharing_on() else '꺼짐 — 업로드가 막힌다 (환경변수로만 켜진다)'}")

    tok = _token(required=False)
    print(f"  {'✅' if tok else '🔴'} HUGGINGFACE_ACCESS_TOKEN "
          f"{'설정됨' if tok else '없다 — .env 에 한 줄 넣는다'}")  # 값은 찍지 않는다
    try:
        from huggingface_hub.utils._runtime import is_xet_available
        xet = is_xet_available()
    except Exception:
        xet = False
    if xet:
        print("  ✅ hf_xet 사용 가능 — 바뀐 청크만 올라간다")
    else:
        print('  ⚠️ hf_xet 이 없다 — 이대로 올리면 LFS 로 가서 한 줄만 고쳐도 파일 전체가\n'
              '     재업로드된다. 해결: pip install -U "huggingface_hub[hf_xet]==0.36.0"')

    remote_ok: Optional[bool] = None
    if remote:
        remote_ok = _remote_status()

    # ── 결론 한 줄이 필요한 자리 ────────────────────────────────────────────
    print("\n― " + ("지금 로컬 SQLite 를 지워도 되는가" if db_present
                    else "로컬 SQLite 는 이미 없다 — 백업이 온전한가") + " ―")
    if not man:
        print("  🔴 아직 아무것도 내보내지 않았다.")
        return
    rows = _deletion_verdict(man, db_counts, remote_ok, db_present)
    for ok, label, why in rows:
        mark = "✅" if ok is True else ("🔴" if ok is False else "🟡")
        print(f"  {mark} {label}\n       {why}")
    if all(ok is True for ok, _, _ in rows):
        print(f"\n  🟢 **지워도 된다.** 되살리는 법:\n"
              f"     python scripts/hf_dataset.py restore --into "
              f"{_rel_root(config.DB_PATH)}")
    else:
        todo = [label for ok, label, _ in rows if ok is not True]
        print(f"\n  🔴 **{'아직 지우면 안 된다' if db_present else '백업이 아직 완전하지 않다'}.** "
              f"남은 조건 {len(todo)}건:")
        for t in todo:
            print(f"     · {t}")


def _remote_status() -> Optional[bool]:
    """원격 현황 — **읽기 호출만** 한다(whoami · repo_info). 아무것도 바꾸지 않는다.

    돌려주는 값은 "원격이 로컬 매니페스트와 같은가" 다 (확인 못 하면 None).
    """
    print("\n― 원격 (읽기 조회만) ―")
    from huggingface_hub import HfApi
    tok = _token(required=False)
    if not tok:
        print("  토큰이 없어 조회하지 않는다.")
        return None
    api = HfApi(token=tok)
    try:
        me = api.whoami()
    except Exception as e:                       # 네트워크·권한 문제를 구분해 준다
        print(f"  🔴 whoami 실패: {type(e).__name__} — 토큰이 만료됐거나 네트워크가 막혔다")
        return None
    orgs = [o.get("name") for o in me.get("orgs", [])]
    print(f"  계정 {me.get('name')} ({me.get('type')}) · org {', '.join(orgs) or '없음'}")
    owner = REPO_ID.split("/")[0]
    print(f"  {owner} 소속 {'✅' if owner in orgs or owner == me.get('name') else '🔴 아님'}")
    try:
        info = api.repo_info(REPO_ID, repo_type="dataset", files_metadata=True)
    except Exception as e:
        print(f"  저장소 {REPO_ID} 를 못 읽었다: {type(e).__name__} "
              f"(아직 없거나 권한이 없다 — upload --yes 가 만든다)")
        return False
    files = [s for s in info.siblings if s.rfilename.endswith(".parquet")]
    nb = sum(s.size or 0 for s in files)
    vis = "private ✅" if info.private else "🔴 **public**"
    print(f"  {REPO_ID} · {vis} · 파케이 {len(files):,}파일 · {_human(nb)}")
    if not info.private:
        print("     🔴 팀 결정은 private 이다. 업로드는 `_assert_private` 가 막는다.\n"
              "        할 일: HF 웹 Settings → Change visibility → Private")
    print(f"  최신 커밋 {str(info.sha)[:8]} · 수정 {info.last_modified}")
    try:
        refs = api.list_repo_refs(REPO_ID, repo_type="dataset")
        tags = [t.name for t in refs.tags]
        print(f"  태그 {', '.join(tags[-5:]) if tags else '없음'}")
    except Exception:
        pass

    # 로컬과 원격의 차이 — 무엇을 올려야 하는지가 이 줄에서 나온다
    man = _load_manifest()
    if not man:
        return None
    remote_sizes = {s.rfilename: (s.size or 0) for s in info.siblings}
    todo = []
    for t in man["tables"].values():
        for f in t["files"]:
            if remote_sizes.get(f["path"]) != f["bytes"]:
                todo.append(f)
    if todo:
        print(f"  ⚠️ 원격과 다른 파일 {len(todo):,}개 · {_human(sum(f['bytes'] for f in todo))} "
              f"— `upload` 로 확인한다")
        return False
    print("  ✅ 원격이 로컬 매니페스트와 같다")
    return True


# ==================================================
# 6. verify — 내보낸 것이 온전한가
# ==================================================
#
# 게이트 다섯을 둔다. 검증 없이 낸 파생물이 이 저장소에 하나도 없다.
#
#   0 범위   필수 표가 매니페스트에 다 있는가 · `.part` 가 남아 있지 않은가
#   1 지문   파일 SHA-256 을 다시 계산해 매니페스트와 대조     (전송·디스크 손상)
#   2 행수   파케이 행수 합 = 지금 DB 행수                      (빠뜨린 파티션)
#   3 스키마 칸 이름·타입이 DB 선언과 대응                       (칸 누락·순서 뒤바뀜)
#   4 값     숫자 칸의 합·NULL 수가 DB 와 일치                   (타입 변환 뭉개짐)
#
# 게이트 4 가 핵심이다. `halted` 가 정수로 남았는지, `vs` 의 **음수 부호**가 살아
# 있는지는 행수로는 절대 안 잡힌다. 다만 4.4M 행 세 표를 전부 훑으면 오래 걸려서
# 기본은 작은 표만, `--deep` 이면 전부 본다.
#
# ★ 2026-09-20 에 고친 것 — **아무것도 검사하지 않고 초록을 내던 버그.**
#   예전 판은 `picked` 를 `TABLES` 와 대조하지 않아 오타난 표 이름이 조용히 무시됐고,
#   그렇게 검사가 0건이어도 "✅ 전부 통과 — 올려도 되는 상태다" 를 찍고 exit 0 이었다.
#   지금은 ① 모르는 이름을 거부하고 ② **실제로 돌린 검사 수를 세어** 0건이면 실패다.
def verify(deep: bool = False, tables: Optional[List[str]] = None) -> int:
    import pyarrow.parquet as pq

    man = _load_manifest()
    print("― 검증 ―")
    if not man:
        print("  아직 없다. `python scripts/hf_dataset.py export` 로 만든다.")
        return 1

    known = set(TABLES) | set(man.get("tables", {}))
    if tables:
        unknown = [t for t in tables if t not in known]
        if unknown:
            raise SystemExit(
                f"모르는 표: {', '.join(unknown)}\n"
                f"  매니페스트에 있는 표: {', '.join(man.get('tables', {})) or '없음'}\n"
                f"  명세에 있는 표    : {', '.join(TABLES)}")
    picked = tables or list(man["tables"])
    fails = 0
    checks = 0          # 돌린 검사 수 (범위 게이트 포함)
    table_checks = 0    # ★ **표에 실제로 한** 검사 수. 0 이면 초록을 내지 않는다.

    # ── 게이트 0: 범위 ──────────────────────────────────────────────────────
    print("― 검증 0: 빠진 것이 없는가 ―")
    if man.get("partial"):
        print("    ❌ 매니페스트가 `partial` 이다 — 내보내는 도중에 끊겼다. "
              "`export` 를 다시 돌린다")
        fails += 1
    else:
        print("    ✅ 매니페스트가 온전하다 (내보내기가 끝까지 갔다)")
    checks += 1
    if not tables:
        need = [n for n, s in TABLES.items() if not s["optional"]]
        miss = [n for n in need if n not in man["tables"]]
        if miss:
            print(f"    ❌ 매니페스트에 없는 필수 표: {', '.join(miss)}")
            fails += 1
        else:
            print(f"    ✅ 필수 표 {len(need)}개가 전부 매니페스트에 있다 "
                  f"({', '.join(need)})")
        checks += 1
    parts = _stray_parts()
    if parts:
        print(f"    ❌ 반쪽(.part) 파일 {len(parts)}개 — 내보내기가 끊긴 흔적이다")
        for p in parts[:5]:
            print(f"       {_rel(p)}")
        fails += 1
    else:
        print("    ✅ 반쪽(.part) 파일 없음")
    checks += 1

    print("\n― 검증 1: 파일 지문이 그대로인가 (SHA-256 재계산) ―")
    for name in picked:
        rec = man["tables"].get(name)
        if not rec:
            # ★ 예전 판은 여기서 조용히 넘어갔다 — 그래서 오타난 표 이름이 무시된 채
            #   "전부 통과" 가 찍혔다. 매니페스트에 없다는 것은 **안 내보냈다**는 뜻이다.
            print(f"    {name:<20} ❌ 매니페스트에 없다 — `export --tables {name}` 을 돌린다")
            fails += 1
            checks += 1
            continue
        bad = []
        for f in rec["files"]:
            p = EXPORT_DIR / f["path"]
            if not p.exists():
                bad.append(f"{f['path']} 없음")
            elif p.stat().st_size != f["bytes"]:
                bad.append(f"{f['path']} 크기 다름")
            elif _sha256(p) != f["sha256"]:
                bad.append(f"{f['path']} 지문 다름")
        fails += len(bad)
        checks += 1
        table_checks += 1
        print(f"    {name:<20} {len(rec['files']):>2}파일  "
              f"→ {'✅ 일치' if not bad else '❌ ' + ' · '.join(bad)}")

    print("\n― 검증 2: 파케이 행수 = DB 행수 ―")
    conn = _ro_connect_opt()
    skipped_value_gate: List[str] = []
    if conn is None:
        # 원본을 이미 지웠다. 대조할 상대가 없다 — **없는 것을 통과로 치지 않는다.**
        print(f"    🟡 원본 SQLite 가 없다({_rel_root(config.DB_PATH)}) — "
              f"게이트 2·3·4 는 대조할 상대가 없어 건너뛴다.")
        print("       파일 지문(게이트 1)은 그대로 돌았다 — 백업 자체가 썩지 않았다는 뜻이다.")
        print("       값까지 확인하려면 `restore` 로 되살린 뒤 다시 돌린다.")
    no_db = conn is None
    try:
        for name in (picked if not no_db else []):
            rec = man["tables"].get(name)
            if not rec:
                continue
            if not _table_exists(conn, name):
                print(f"    {name:<20} DB 에 없다 — 대조 불가 ⚠️")
                continue
            pq_rows = sum(pq.read_metadata(EXPORT_DIR / f["path"]).num_rows
                          for f in rec["files"] if (EXPORT_DIR / f["path"]).exists())
            db_rows = conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
            ok = pq_rows == db_rows
            fails += 0 if ok else 1
            checks += 1
            table_checks += 1
            print(f"    {name:<20} 파케이 {pq_rows:>10,}  DB {db_rows:>10,}  "
                  f"→ {'✅ 일치' if ok else '❌ 어긋남'}")

        if no_db:
            print("\n― 검증 3·4 ― 원본이 없어 건너뛴다")
            raise _SkipDbGates()

        print("\n― 검증 3: 칸 이름과 타입 ―")
        for name in picked:
            rec = man["tables"].get(name)
            if not rec or not rec["files"] or not _table_exists(conn, name):
                continue
            first = EXPORT_DIR / rec["files"][0]["path"]
            if not first.exists():
                continue
            # ⚠️ `pq.read_schema` 는 **상위 폴더의 `year=` 를 컬럼으로 붙이지 않는다**
            #    (파일 하나의 스키마만 읽는다). 반면 `pq.read_table(파일)` 은 붙인다 —
            #    17칸이 18칸이 된다. 여기서는 선언 칸만 봐야 하므로 read_schema 다.
            sch = pq.read_schema(first)
            # ⚠️ arrow 타입은 **생성자 이름과 찍히는 이름이 다르다** — `pa.float64()`
            #    를 str 로 찍으면 'double' 이다. 이름 문자열로 대조하면 멀쩡한 파일이
            #    전부 ❌ 로 나온다. 그래서 DB 선언을 같은 경로로 arrow 타입까지 만들어
            #    **타입 객체끼리** 비교한다.
            exp_schema = _arrow_schema(_columns(conn, name))
            got = list(zip(sch.names, [str(t) for t in sch.types]))
            exp = list(zip(exp_schema.names, [str(t) for t in exp_schema.types]))
            ok = got == exp
            fails += 0 if ok else 1
            checks += 1
            table_checks += 1
            print(f"    {name:<20} {len(got):>2}칸 → {'✅ 일치' if ok else '❌ 어긋남'}")
            if not ok:
                print(f"      DB   {exp}")
                print(f"      파케이 {got}")

        print("\n― 검증 4: 값이 뭉개지지 않았는가 (숫자 칸 합·NULL 수) ―")
        print("  ※ 행수로는 절대 안 잡히는 것을 본다 — halted 가 정수로 남았는가, "
              "vs 의 음수 부호가 살았는가")
        for name in picked:
            rec = man["tables"].get(name)
            if not rec or not _table_exists(conn, name):
                continue
            if TABLES.get(name, {}).get("heavy") and not deep:
                print(f"    {name:<20} 건너뜀 — 큰 표다. 보려면 `--deep`")
                skipped_value_gate.append(name)
                continue
            ok = _gate_values(conn, name, rec, pq)
            fails += 0 if ok else 1
            checks += 1
            table_checks += 1
    except _SkipDbGates:
        pass
    finally:
        if conn is not None:
            conn.close()

    # ── 결론 ────────────────────────────────────────────────────────────────
    print()
    if table_checks == 0:
        # ★ 예전 판의 진짜 버그가 여기였다 — 표를 하나도 안 본 채 "전부 통과" 를 찍고
        #   exit 0 을 냈다. **검사하지 않은 것은 통과가 아니다.**
        print("  🔴 **표를 하나도 검사하지 않았다.** 초록을 낼 수 없다.\n"
              f"     고른 표: {', '.join(picked) or '없음'}\n"
              f"     매니페스트에 있는 표: {', '.join(man.get('tables', {})) or '없음'}")
        return 1
    if fails:
        print(f"  ❌ 어긋난 항목 {fails:,}건 / 검사 {checks:,}건 "
              f"— 해당 표를 `export --force` 로 다시 낸다")
    elif no_db:
        print(f"  🟡 검사 {checks:,}건 통과 — **다만 원본 SQLite 가 없어 값·스키마는 "
              f"대조하지 못했다.** 파일이 썩지 않았다는 것까지만 확인했다")
    elif skipped_value_gate:
        print(f"  🟡 검사 {checks:,}건 전부 통과. **다만 {', '.join(skipped_value_gate)} 의 "
              f"값 게이트는 보지 않았다** — `verify --deep` 으로 확인한다")
    else:
        full = not tables
        print(f"  ✅ 검사 {checks:,}건 전부 통과 — "
              + ("올려도 되는 상태다" if full else
                 f"다만 고른 표({', '.join(picked)})만 봤다"))

    # 판정을 기록으로 남긴다 — `status` 의 "지워도 되는가" 가 이 파일을 본다.
    _write_json_atomic(VERIFY_LOG_PATH, {
        "at": _now_kst(), "deep": bool(deep) and not no_db,
        "fails": fails, "checks": checks, "table_checks": table_checks,
        "db_present": not no_db,
        "tables": picked, "full": not tables,
        "skipped_value_gate": skipped_value_gate,
        "manifest_fp": _manifest_fp(man),
        "manifest_generated_at": man.get("generated_at"),
    })
    return 1 if fails else 0


def _gate_values(conn: sqlite3.Connection, name: str, rec: Dict, pq) -> bool:
    """숫자 칸의 합과 NULL 수를 DB·파케이 양쪽에서 각각 구해 대조한다.

    합을 쓰는 이유: 부호가 뒤집히거나 정수가 실수로 뭉개지면 합이 반드시 달라진다.
    NULL 수를 함께 보는 이유: 합만 보면 NULL 이 0 으로 바뀐 사고를 놓친다.
    """
    import pyarrow.compute as pc

    cols = _columns(conn, name)
    num = [c for c, d in cols if d in ("INTEGER", "REAL")]
    if not num:
        print(f"    {name:<20} 숫자 칸이 없다 — 건너뜀")
        return True

    # ⚠️ DB 스키마가 내보낸 뒤에 바뀌었을 수 있다 — 실제로 겪었다(2026-09-20:
    #    `benchmark_index` 에 n_fixed·base_dt·base_level 세 칸이 늘었는데 행수는
    #    19,776 그대로였다). 그 상태로 파케이에 없는 칸을 읽으려 들면
    #    `ArrowInvalid: No match for FieldRef.Name(n_fixed)` 로 **traceback 을 뿜고
    #    죽는다.** 검증기가 죽는 것은 검증이 아니다 — 없는 칸은 실패로 **보고**한다.
    have = set()
    for f in rec["files"]:
        p = EXPORT_DIR / f["path"]
        if p.exists():
            have |= set(pq.read_schema(p).names)
            break
    gone = [c for c in num if c not in have]
    if gone:
        print(f"    {name:<20} ❌ 파케이에 없는 숫자 칸 {len(gone)}개: {', '.join(gone)}\n"
              f"{'':<25}DB 스키마가 내보낸 뒤에 바뀌었다 — "
              f"`export --tables {name} --force` 로 다시 낸다")
        return False

    db = conn.execute(
        "SELECT " + ", ".join(f"SUM({c}), SUM({c} IS NULL)" for c in num) + f" FROM {name}"
    ).fetchone()

    sums = {c: 0.0 for c in num}
    nulls = {c: 0 for c in num}
    for f in rec["files"]:
        p = EXPORT_DIR / f["path"]
        if not p.exists():
            continue
        # `columns=num` 이라 하이브 폴더가 만들어 내는 `year` 칸은 애초에 안 읽힌다.
        tbl = pq.read_table(p, columns=num)
        for c in num:
            col = tbl.column(c)
            s = pc.sum(col).as_py()
            sums[c] += s or 0.0
            nulls[c] += col.null_count

    bad = []
    for i, c in enumerate(num):
        d_sum, d_null = db[2 * i], db[2 * i + 1]
        d_sum = 0.0 if d_sum is None else float(d_sum)
        # 실수 합은 더하는 순서에 따라 끝자리가 흔들린다 — 상대 오차로 본다.
        scale = max(abs(d_sum), abs(sums[c]), 1.0)
        if abs(d_sum - sums[c]) / scale > 1e-12 or d_null != nulls[c]:
            bad.append(f"{c}(DB {d_sum:,.4f}/{d_null} vs 파케이 {sums[c]:,.4f}/{nulls[c]})")
    print(f"    {name:<20} 숫자 {len(num):>2}칸 → {'✅ 일치' if not bad else '❌ ' + ' · '.join(bad)}")
    return not bad


# ==================================================
# 7. restore — 파케이만으로 SQLite 를 되살린다
# ==================================================
#
# **이 명령이 "지워도 된다"의 유일한 근거다.**
#
# 백업은 되살려 본 적이 없으면 백업이 아니다. 그래서 `--into` 를 주지 않으면 임시
# 폴더에 통째로 복원했다가 지우는 **리허설**로 돈다. 결과는 `meta/last_restore.json`
# 에 남고 `status` 가 그것을 읽어 판정한다.
#
# 무엇으로 되살리나 —
#   · 스키마: 매니페스트의 `ddl` (내보낼 때 `sqlite_master` 에서 그대로 떠 왔다)
#   · 값    : 파케이 파일들
#   둘 다 HF 저장소 안에 있으므로 **로컬에 아무것도 없어도** 복원된다.
def restore(into: Optional[str] = None, src: Optional[str] = None,
            tables: Optional[List[str]] = None, force: bool = False,
            verbose: bool = True) -> int:
    import pyarrow.parquet as pq

    export_dir = Path(src).resolve() if src else EXPORT_DIR
    man = _load_manifest(export_dir / "meta" / "manifest.json")
    print("― 복구 ―")
    if not man:
        print(f"  매니페스트가 없다: {export_dir / 'meta' / 'manifest.json'}\n"
              f"  할 일: `export` 를 먼저 돌리거나, HF 에서 받은 폴더를 `--from` 으로 준다.")
        return 1
    if man.get("partial"):
        print("  🔴 매니페스트가 `partial` 이다 — 내보내기가 끊긴 상태다. "
              "`export` 를 다시 돌린 뒤에 복구한다.")
        return 1

    picked = tables or list(man["tables"])
    unknown = [t for t in picked if t not in man["tables"]]
    if unknown:
        raise SystemExit(f"매니페스트에 없는 표: {', '.join(unknown)}\n"
                         f"  있는 표: {', '.join(man['tables'])}")
    no_ddl = [t for t in picked if not man["tables"][t].get("ddl", {}).get("table")]
    if no_ddl:
        print(f"  🔴 매니페스트에 DDL 이 없는 표: {', '.join(no_ddl)}\n"
              f"     옛 매니페스트다 — `export --force` 로 다시 내보내면 DDL 이 함께 담긴다.")
        return 1

    rehearsal = into is None
    tmpdir: Optional[str] = None
    if rehearsal:
        tmpdir = tempfile.mkdtemp(prefix="qurious-restore-")
        target = Path(tmpdir) / "market.sqlite3"
        print(f"  리허설 — 임시 폴더에 복원했다가 지운다 ({tmpdir})")
    else:
        target = Path(into).resolve()
        if target.exists() and not force:
            print(f"  🔴 이미 있다: {target}\n"
                  f"     덮어쓰려면 `--force` 를 준다. (원본을 실수로 날리지 않으려는 잠금이다)")
            return 1
        if target.exists():
            target.unlink()
        target.parent.mkdir(parents=True, exist_ok=True)
        print(f"  대상 {target}")

    t0 = time.time()
    total_rows = 0
    ok = True
    sig_ok = sig_total = 0
    raw_ok = raw_total = 0
    conn: Optional[sqlite3.Connection] = None
    try:
        conn = sqlite3.connect(target, timeout=60, isolation_level=None)
        # 복원은 한 번에 쏟아붓는 일이라 내구성 설정을 끈다. 중간에 죽으면 파일을 지우고
        # 처음부터 다시 하면 되므로, 여기서 WAL·fsync 를 쓸 이유가 없다.
        conn.execute("PRAGMA journal_mode=OFF")
        conn.execute("PRAGMA synchronous=OFF")
        conn.execute("PRAGMA cache_size=-262144")      # 256MB 페이지 캐시
        conn.execute("PRAGMA temp_store=MEMORY")

        # ① 표를 만든다. **인덱스는 아직 만들지 않는다** — 적재 중 인덱스를 유지하면
        #    행마다 B-트리를 손봐야 해서 몇 배 느려진다. 다 넣고 나서 한 번에 만든다.
        for name in picked:
            conn.execute(man["tables"][name]["ddl"]["table"])

        # ② 값을 넣는다.
        #
        # ★ `isolation_level=None` 은 **autocommit** 이라 `executemany` 하나하나가
        #   제 트랜잭션이 된다. 1,340만 행을 그렇게 넣으면 커밋만 수만 번이라 20분이
        #   넘어간다(본 세션 실측: 20분에 1.4GB 까지밖에 못 갔다). 표 단위로 명시적
        #   `BEGIN`/`COMMIT` 을 잡아 커밋 횟수를 **표 개수만큼**으로 줄인다.
        for name in picked:
            rec = man["tables"][name]
            cols = [c for c, _ in _columns(conn, name)]
            ins = (f"INSERT OR REPLACE INTO {name} ({', '.join(cols)}) "
                   f"VALUES ({', '.join('?' * len(cols))})")
            n = 0
            conn.execute("BEGIN")
            for f in rec["files"]:
                p = export_dir / f["path"]
                if not p.exists():
                    print(f"    🔴 파일이 없다: {f['path']}")
                    ok = False
                    continue
                # ⚠️ `pq.read_table` 이 아니라 `ParquetFile` 이다 — read_table 은 상위
                #    폴더 `year=2026/` 을 컬럼으로 붙여 **17칸 파일을 18칸으로** 읽는다.
                #    그 상태로 INSERT 하면 칸 수가 안 맞아 통째로 실패한다.
                pf = pq.ParquetFile(p)
                for batch in pf.iter_batches(batch_size=rec.get("fetch_rows") or FETCH_ROWS,
                                             columns=cols):
                    d = batch.to_pydict()
                    conn.executemany(ins, zip(*[d[c] for c in cols]))
                    n += batch.num_rows
                    if verbose:
                        print(f"\r    {name} … {n:,}행", end="", flush=True)
            conn.execute("COMMIT")
            total_rows += n
            good = (n == rec["rows"])
            ok = ok and good
            if verbose:
                mark = "✅" if good else f"❌ 매니페스트는 {rec['rows']:,}행"
                print(f"\r    {name:<20} {n:,}행 복원 → {mark}" + " " * 12)

        # ③ 인덱스를 만든다.
        for name in picked:
            for stmt in man["tables"][name]["ddl"].get("indexes", []):
                conn.execute(stmt)
        conn.commit()

        # ④ 복원한 DB 가 **원본과 같은 내용인가** — 내용 지문으로 대조한다.
        #    행수는 맞는데 값이 뭉개진 복원을 잡는 유일한 게이트다.
        print("  ― 복원 검증 1: 파티션 내용 지문 ―")
        conn.row_factory = sqlite3.Row
        for name in picked:
            rec = man["tables"][name]
            spec = TABLES.get(name)
            if not spec:
                continue
            cols = _columns(conn, name)
            bad = []
            for f in rec["files"]:
                part = _part_of(f["path"], name, spec)
                want = f.get("sig")
                if not want:
                    continue
                sig_total += 1
                got = _content_sig(conn, name, spec, part, cols)
                if got == want:
                    sig_ok += 1
                else:
                    bad.append(f["path"])
            print(f"    {name:<20} {'✅ 일치' if not bad else '❌ ' + ' · '.join(bad)}")
            ok = ok and not bad

        # ⑤ 감사 근거가 살아 있는가 — 원문을 풀어 sha256 을 다시 계산한다.
        #    BLOB 이 파케이를 왕복하며 한 바이트라도 바뀌면 여기서 걸린다.
        if "raw_response" in picked:
            print("  ― 복원 검증 2: 응답 원문 gzip 해제 + sha256 재계산 ―")
            import gzip
            bad_raw = 0
            for r in conn.execute("SELECT body, sha256, compression FROM raw_response"):
                raw_total += 1
                body = gzip.decompress(r["body"]) if r["compression"] == "gzip" else r["body"]
                if hashlib.sha256(body).hexdigest() == r["sha256"]:
                    raw_ok += 1
                else:
                    bad_raw += 1
            print(f"    raw_response         {raw_ok:,}/{raw_total:,} 일치"
                  f"{'' if not bad_raw else f'  ❌ 손상 {bad_raw:,}건'}")
            ok = ok and bad_raw == 0
            # 감사 '링크' 도 본다 — price_daily 의 raw_sha256 이 실제 원문을 가리키는가.
            if "price_daily" in picked:
                miss = conn.execute(
                    "SELECT COUNT(*) FROM (SELECT DISTINCT raw_sha256 s FROM price_daily "
                    " WHERE s<>'') WHERE s NOT IN (SELECT sha256 FROM raw_response)"
                ).fetchone()[0]
                tot = conn.execute(
                    "SELECT COUNT(DISTINCT raw_sha256) FROM price_daily WHERE raw_sha256<>''"
                ).fetchone()[0]
                print(f"    감사 링크             {tot - miss:,}/{tot:,} 개의 raw_sha256 이 "
                      f"원문을 가리킨다{'' if not miss else f'  ❌ 끊김 {miss:,}개'}")
                ok = ok and miss == 0

        size = target.stat().st_size
        dt = time.time() - t0
        print(f"\n  {'✅' if ok else '❌'} {total_rows:,}행 · {_human(size)} · {dt:,.1f}초")
        if ok and not rehearsal:
            print(f"     되살아났다. 이 파일을 `{_rel_root(config.DB_PATH)}` 로 두면 "
                  f"수집기가 그대로 이어서 돈다.")
        elif ok:
            print("     리허설 성공 — 파케이만으로 SQLite 가 복원된다. "
                  "이것이 '지워도 된다'의 근거다.")
    finally:
        # ⚠️ Windows 는 열린 파일을 지우지 못한다 — 예외로 빠져나가도 연결을 반드시
        #    닫아야 임시 폴더가 지워진다. 안 그러면 2.4GB 가 %TEMP% 에 남는다.
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)

    # 결과를 기록으로 남긴다 — `status` 가 이 파일을 읽어 판정한다.
    #
    # `--from` 으로 다른 폴더에서 복원해도 기록은 **로컬 meta/** 에 남는다. 엉뚱한
    # 리허설이 로컬 백업에 초록을 주지 않는 이유는 `manifest_fp` 를 함께 적기 때문이다 —
    # 출처가 다르면 지문이 안 맞아 `status` 가 "옛 매니페스트 것" 으로 물린다.
    _write_json_atomic(RESTORE_LOG_PATH, {
        "at": _now_kst(), "ok": bool(ok), "rehearsal": rehearsal,
        "rows": total_rows, "tables": picked,
        "sig_ok": sig_ok, "sig_total": sig_total,
        "raw_ok": raw_ok, "raw_total": raw_total,
        "seconds": round(time.time() - t0, 1),
        "manifest_fp": _manifest_fp(man),
        "manifest_generated_at": man.get("generated_at"),
    })
    return 0 if ok else 1


def _part_of(rel_path: str, table: str, spec: Dict) -> Optional[str]:
    """파일 경로에서 파티션 이름을 되읽는다. (`year=2020/…` → `2020`)"""
    if spec["partition"] is None:
        return None
    parts = rel_path.split("/")
    if spec["partition"] == "year":
        for seg in parts:
            if seg.startswith("year="):
                return seg.split("=", 1)[1]
        return None
    return parts[-1].rsplit(".", 1)[0]      # `raw_response/portal.parquet` → `portal`


# ==================================================
# 8. upload — 기본은 dry-run
# ==================================================
def _readme_yaml(man: Dict) -> str:
    """dataset card. 표가 늘면 여기도 늘어야 하므로 매니페스트에서 만든다."""
    cfgs = []
    for name in man["tables"]:
        spec = TABLES.get(name, {})
        mode = spec.get("partition")
        if mode == "year":
            path = f"{name}/**/*.parquet"
        elif mode == "column":
            path = f"{name}/*.parquet"
        else:
            path = f"{name}/{name}.parquet"
        default = "\n      default: true" if name == "price_daily" else ""
        cfgs.append(f"    - config_name: {name}{default}\n"
                    f"      data_files: [{{split: train, path: \"{path}\"}}]")
    rows = {k: v["rows"] for k, v in man["tables"].items()}
    decision = "\n".join(f"{i+1}. {line}" for i, line in enumerate(
        man.get("sharing_decision") or SHARING_DECISION))
    return f"""---
pretty_name: "KRX 일별 시세·수정주가·총수익지수·벤치마크 (2020–2026)"
license: other
license_name: "공공데이터포털·OpenDART 파생 — 출처별 이용약관 준수"
language: [ko]
size_categories: ["1M<n<10M"]
tags: [finance, korea, krx, quant]
configs:
{chr(10).join(cfgs)}
---

# KRX 일별 시세 데이터셋 (Qurious 수집기)

🔴 **이 저장소는 private 이어야 한다. 절대 public 으로 바꾸지 않는다.**

원자료는 공공데이터포털(금융위 주식시세정보)과 OpenDART 에서 받았다. 이 저장소는 그
응답을 정규화·가공한 파생물 **과 응답 원문 자체**(`raw_response`)를 함께 담는다.

## 왜 원문까지 올리는가 — 팀 결정 (2026-09-20)

`collector/README.md §9` 가 미결로 남겼던 두 항목에 대한 팀의 답이다.

{decision}

업로드 스크립트(`scripts/hf_dataset.py`)는 이 결정을 말로만 적지 않고 **검사한다** —
`QURIOUS_RAW_SHARING` 이 꺼져 있으면 올리지 않고, 업로드 직전에 원격 공개 범위를
조회해 public 이면 중단한다.

## 출처
- 금융위원회 주식시세정보 (공공데이터포털) — 일별 시세
- 전자공시시스템 OpenDART — 현금·현물 배당 공시

## 규모
생성 {man.get('generated_at','?')} · 수집기 커밋 `{man.get('collector_commit','?')}`

| 표 | 행 수 | 뜻 |
|---|---|---|
""" + "\n".join(
        f"| `{k}` | {v:,} | {man['tables'][k].get('why','')} |" for k, v in rows.items()
    ) + """

## 되살리는 법 — 이 저장소만으로 SQLite 가 복원된다

`meta/manifest.json` 에 각 표의 **DDL 원문**(`CREATE TABLE`·`CREATE INDEX`)이 들어 있다.
그래서 우리 저장소 코드가 없어도 스키마까지 그대로 되살아난다.

```bash
huggingface-cli download --repo-type dataset {repo} --local-dir ./hf_export
PYTHONPATH=. python scripts/hf_dataset.py restore \\
    --from ./hf_export --into data/collector/market.sqlite3
```

복원은 ① 행수 ② 파티션별 **내용 지문** ③ `raw_response` 전량 gzip 해제 후 sha256
재계산 ④ `price_daily.raw_sha256` → `raw_response.sha256` 감사 링크까지 확인한다.

## 정의
- `price_adjusted` — **PR**(가격) 계열. 분할·권리락만 고친 수정주가.
- `price_total_return` — **TR** 계열. `tr_index` 는 세전, `tr_index_net` 은 세후 15.4%.
  ⚠️ 종목마다 **첫 거래일이 1.0** 이다. 종목끼리 레벨을 비교하면 안 되고, 반드시
  인접 두 날의 **비율**로 환산해서 쓴다.
- `benchmark_index` — ⚠️ **KRX 공식 지수가 아니다.** 우리 DB 로 재현한 자체 계열이며
  20200102 = 1000.0 으로 정규화했다. 공식 코스피 연말 종가와 평균 0.066% 차이난다.
  화면·보고서에 그냥 'KOSPI' 라고 적으면 안 된다 — 항상 '자체 재현치'를 병기한다.
- `raw_response` — 출처 응답 **원문**(gzip BLOB). 분석용이 아니라 감사·재정규화용이다.
  `body` 를 gzip 해제하면 `sha256` 칸과 일치한다.
- `ingest_day` — 기준일별 수집 상태. `empty` 는 휴장 확정이 아니라 보류다.

## 주의
- `price_daily.halted = 1` 인 행이 **202,423행(4.5%)** 있다. 이것은 '거래정지'가 아니라
  `trqu = 0`(그날 거래가 없었다)과 동치다. `clpr` 은 전일 종가를 이월한다.
- `bas_dt` 는 **TEXT**(`YYYYMMDD`)다. 문자열로 비교한다.
- 디렉터리의 `year=YYYY` 는 파일 정리 규칙일 뿐 컬럼이 아니다. 연도는 `bas_dt` 로 가른다.
  ⚠️ 다만 `pyarrow.parquet.read_table` 은 그 폴더 이름을 **컬럼으로 추론해 붙인다**
  (17칸이 18칸이 된다). 선언 칸만 보려면 `ParquetFile(path).read()` 를 쓴다.

## 파케이 옵션
""".replace("{repo}", man.get("repo_id", REPO_ID)) + "```\n" + json.dumps(
        man.get("parquet_opts", {}), ensure_ascii=False, indent=2) + "\n```\n" + """
⚠️ 이 중 하나라도 바꾸면 바이트 배치가 달라져 이전 리비전과의 중복제거가 무효가 된다.
"""


#: 업로드에서 **절대 올리지 않는** 것.
#:
#: · `*.part` — 내보내기가 끊겨 남은 반쪽 파일. 받는 쪽이 정상 파케이로 오인한다.
#: · `*.tmp`  — 매니페스트 원자적 쓰기의 중간 파일.
#: · `.cache/**` — `upload_large_folder` 가 재개용으로 폴더 안에 만드는 작업 캐시.
UPLOAD_IGNORE = ["*.part", "**/*.part", "*.tmp", "**/*.tmp",
                 ".cache/**", "**/.cache/**"]


def _open_year_patterns(man: Dict) -> List[str]:
    """'아직 자라는 연도'의 glob.

    ⚠️ 예전 판은 **오늘의 연도 하나**로만 패턴을 만들었다. 그러면 1월 2일에 12월 마지막
       거래일이 뒤늦게 들어와도 `year=2025/` 가 패턴에 없어 **한 해가 통째로 빠진다.**
       그래서 ① 오늘 연도 ② 작년 ③ 매니페스트에 있는 가장 큰 연도 — 셋을 모두 넣는다.
    """
    now = datetime.datetime.now(KST).year
    years = {now, now - 1}          # ① 오늘 연도 ② 작년(연초에 12월 자료가 늦게 온다)
    seen = {int(s.split("=", 1)[1])
            for t in man.get("tables", {}).values() for f in t.get("files", [])
            for s in f["path"].split("/") if s.startswith("year=")}
    if seen:
        years.add(max(seen))        # ③ 매니페스트에 있는 가장 큰 연도
    return sorted(f"*/year={y}/*" for y in sorted(years))


def _incremental_selection(man: Dict) -> Tuple[List[str], str]:
    """증분으로 올릴 파일 목록과 그 근거 한 줄.

    **내용 기반이 기본이다** — 매니페스트의 `uploaded` 기록과 지금 파일의 sha256 을
    맞춰 보고 **달라진 것만** 고른다. '올해 연도' 같은 달력 추측이 아니라 실제 차이다.
    업로드 기록이 아직 없으면(첫 업로드) 달력 기반 패턴으로 떨어진다.
    """
    files = {f["path"]: f["sha256"]
             for t in man.get("tables", {}).values() for f in t.get("files", [])}
    up = (man.get("uploaded") or {}).get("files") or {}
    if up:
        changed = sorted(p for p, s in files.items() if up.get(p) != s)
        return changed + ["meta/*", "README.md"], \
            f"업로드 기록과 sha256 이 다른 파일 {len(changed):,}개"
    pats = _open_year_patterns(man)
    small = [n for n, sp in TABLES.items() if sp["partition"] is None]
    cols = [n for n, sp in TABLES.items() if sp["partition"] == "column"]
    return (pats + [f"{n}/*" for n in small + cols] + ["meta/*", "README.md"]), \
        f"업로드 기록이 없다 — 열린 연도({', '.join(pats)})와 작은 표로 고른다"


def _select(man: Dict, patterns: Optional[List[str]]) -> List[Tuple[str, List[Dict]]]:
    """(표 이름, 올릴 파일들). `patterns` 가 None 이면 전부."""
    out = []
    for name, t in man["tables"].items():
        fs = [f for f in t["files"]
              if patterns is None or any(fnmatch.fnmatch(f["path"], p) for p in patterns)]
        if fs:
            out.append((name, fs))
    return out


def _assert_private(api, create: bool) -> bool:
    """원격이 **실제로 private 인지** 확인한다. 아니면 올리지 않는다.

    ⚠️ `create_repo(private=True, exist_ok=True)` 는 **이미 있는 저장소의 공개 범위를
       바꾸지 않는다.** org 관리자가 먼저 public 으로 만들어 뒀다면 그대로 public 에
       올라간다. 이 스크립트의 약관 논리 전체가 private 을 전제로 하므로(팀 결정 §3),
       만드는 것과 확인하는 것을 따로 한다.
    """
    if create:
        api.create_repo(REPO_ID, repo_type="dataset", private=True, exist_ok=True)
    try:
        info = api.repo_info(REPO_ID, repo_type="dataset")
    except Exception as e:
        print(f"  🔴 공개 범위를 확인하지 못했다: {type(e).__name__}\n"
              f"     확인 못 한 것은 통과가 아니다 — 올리지 않는다.")
        return False
    if info.private:
        print("  ✅ 원격이 private 임을 확인했다")
        return True
    print(f"  🔴 **원격이 public 이다.** 올리지 않는다.\n"
          f"     팀 결정은 'private Organization 안에서만 공유' 다(SHARING_DECISION §2·§3).\n"
          f"     할 일: https://huggingface.co/datasets/{REPO_ID}/settings\n"
          f"            → Change visibility → Private 로 바꾼 뒤 다시 돌린다.")
    return False


def upload(yes: bool = False, incremental: bool = False, allow_lfs: bool = False,
           tag: Optional[str] = None) -> int:
    """파케이를 HF 로 올린다. **기본은 dry-run** — 아무것도 올리지 않는다.

    원격에 올린 것은 되돌리기 어렵다. 그래서 `--yes` 를 명시적으로 칠 때만 실제로
    올라간다. dry-run 은 "무엇이 · 얼마나 · 어디로" 를 그대로 보여 준다.

    게이트 넷을 통과해야 실제로 올라간다:
      1. `QURIOUS_RAW_SHARING` 이 켜져 있다 (팀 결정을 명시적으로 확인한 흔적)
      2. 매니페스트가 `partial` 이 아니고 `.part` 반쪽 파일이 없다
      3. hf_xet 이 켜져 있다 (없으면 `--allow-lfs` 를 따로 줘야 한다)
      4. 원격이 **실제로 private** 이다
    """
    man = _load_manifest()
    if not man:
        print("올릴 것이 없다. `python scripts/hf_dataset.py export` 를 먼저 돌린다.")
        return 1

    # 증분이면 **실제로 올라갈 것만** 센다. dry-run 이 전체 크기를 보여 주면
    # "30MB 면 되는데 270MB 를 올리려는 줄" 알고 손을 멈추게 된다 — 거짓 정보다.
    patterns: Optional[List[str]] = None
    why_inc = ""
    if incremental:
        patterns, why_inc = _incremental_selection(man)
    sel = _select(man, patterns)
    files = [f for _, fs in sel for f in fs]
    missing = [f["path"] for f in files if not (EXPORT_DIR / f["path"]).exists()]
    total = sum(f["bytes"] for f in files)

    try:
        from huggingface_hub.utils._runtime import is_xet_available
        xet = is_xet_available()
    except Exception:
        xet = False

    print(f"― 업로드 {'(실행)' if yes else '(dry-run — 아무것도 올리지 않는다)'} ―")
    print(f"  대상   {REPO_ID} (dataset · private 이어야 한다)")
    print(f"  원본   {EXPORT_DIR}")
    print(f"  방식   {'upload_folder(증분)' if incremental else 'upload_large_folder(전체)'}")
    if incremental:
        print(f"  선택   {why_inc}")
    print(f"  파일   {len(files):,}개 · {_human(total)}"
          + (f"  (전체 {sum(len(t['files']) for t in man['tables'].values()):,}개 중)"
             if incremental else ""))
    for name, fs in sel:
        tagtxt = "  (복구용)" if TABLES.get(name, {}).get("restore_only") else ""
        print(f"    {name:<20} {len(fs):>2}파일 · "
              f"{_human(sum(f['bytes'] for f in fs)):>10} "
              f"· {sum(f['rows'] for f in fs):>10,}행{tagtxt}")
    print("  README.md · meta/manifest.json · meta/last_*.json 도 함께 올린다")
    print(f"  제외   {', '.join(UPLOAD_IGNORE)}")
    if missing:
        print(f"  ❌ 매니페스트에 있는데 디스크에 없는 파일 {len(missing):,}개 "
              f"— `export` 를 다시 돌린다")
        for p in missing[:5]:
            print(f"     {p}")
        return 1

    # ── 게이트 2: 반쪽 파일·partial ──────────────────────────────────────────
    if man.get("partial"):
        print("  🔴 매니페스트가 `partial` 이다 — 내보내기가 끊긴 상태다. "
              "`export` 를 다시 돌린다.")
        return 1
    parts = _stray_parts()
    if parts:
        print(f"  🔴 반쪽(.part) 파일 {len(parts)}개가 남아 있다 — 내보내기가 끊겼다.\n"
              f"     업로드에서는 `ignore_patterns` 로 빠지지만, 그 전에 `export` 를\n"
              f"     다시 돌려 온전한 파일을 만드는 것이 맞다.")
        for p in parts[:5]:
            print(f"     {_rel(p)}")

    # ── 게이트 1: 공유 스위치 ───────────────────────────────────────────────
    if _sharing_on():
        print("  ✅ QURIOUS_RAW_SHARING 켜짐 — 팀 결정(SHARING_DECISION)에 따라 올린다")
    else:
        print("  🔴 QURIOUS_RAW_SHARING 꺼짐 — 실제 업로드는 막힌다 "
              "(dry-run 은 계속 보여 준다)")

    # ── 게이트 3: xet ───────────────────────────────────────────────────────
    if not xet:
        msg = ('hf_xet 이 없어 LFS 로 올라간다 — 파케이를 한 줄만 고쳐도 파일 전체가\n'
               '  재업로드되어 증분 백업이 무효가 된다.\n'
               '  해결: pip install -U "huggingface_hub[hf_xet]==0.36.0"\n'
               '        python -c "from huggingface_hub.utils._runtime import '
               'is_xet_available; print(is_xet_available())"   # True 여야 한다')
        if yes and not allow_lfs:
            print(f"  🔴 {msg}")
            print("  그래도 올리려면 `--allow-lfs` 를 함께 준다.")
            return 1
        print(f"  ⚠️ {msg}")
    else:
        print("  ✅ hf_xet 켜짐 — 바뀐 청크만 올라간다")

    today = datetime.datetime.now(KST).strftime("%Y-%m-%d")
    tag_name = tag or f"snapshot-{today}"
    msg = (f"데이터 스냅샷 {today}(KST) · "
           + " · ".join(f"{k} {v['rows']:,}행" for k, v in man["tables"].items())
           + f" · 수집기 {man.get('collector_commit','?')}")
    print(f"  커밋   {msg}")
    print(f"  태그   {tag_name}  (이미 있으면 그 태그를 그대로 둔다)")

    if not yes:
        # dry-run 에서도 **읽기 조회**로 공개 범위를 미리 본다. 읽기만 하므로 안전하다.
        tok = _token(required=False)
        if tok:
            from huggingface_hub import HfApi
            print("  ― 원격 공개 범위 미리 확인 (읽기만) ―")
            try:
                info = HfApi(token=tok).repo_info(REPO_ID, repo_type="dataset")
                print(f"  {'✅ private' if info.private else '🔴 public — 이대로면 올리지 않는다'}")
            except Exception as e:
                print(f"  🟡 아직 없거나 권한이 없다({type(e).__name__}) — "
                      f"`--yes` 가 private 으로 만든다")
        print("\n  실제로 올리려면 `--yes` 를 준다. "
              "(되돌리기 어려우므로 사용자 승인이 필요하다)")
        return 0

    # ── 여기서부터가 실제 쓰기다 ──────────────────────────────────────────────
    _sharing_gate("HF 업로드")            # 게이트 1 — 꺼져 있으면 여기서 멈춘다

    from huggingface_hub import HfApi
    api = HfApi(token=_token())              # 토큰은 여기서만 쓰고 절대 찍지 않는다
    if not _assert_private(api, create=True):   # 게이트 4
        return 1

    README_PATH.write_text(_readme_yaml(man), encoding="utf-8")

    t0 = time.time()
    if incremental:
        # 증분: 바뀐 파일 + 메타만. 단일 커밋이라 커밋 메시지를 남길 수 있다.
        api.upload_folder(
            repo_id=REPO_ID, repo_type="dataset", folder_path=str(EXPORT_DIR),
            allow_patterns=patterns, ignore_patterns=UPLOAD_IGNORE,
            commit_message=msg)
    else:
        # 전체: 중단돼도 **재개**된다(진행 상태를 폴더 안 `.cache/huggingface` 에 캐시).
        # ⚠️ commit_message·path_in_repo·run_as_future 를 지원하지 않는다 —
        #    커밋이 여러 개로 쪼개지기 때문이다. 넘기면 실패한다.
        api.upload_large_folder(
            repo_id=REPO_ID, repo_type="dataset", folder_path=str(EXPORT_DIR),
            ignore_patterns=UPLOAD_IGNORE, num_workers=8, print_report=True)
    # ★ 태그는 업로드가 **끝난 뒤에** 단다(전체 업로드는 커밋이 여러 개다).
    #   `exist_ok=True` 가 없으면 같은 날 두 번째 업로드가 270MB 를 다 올린 뒤
    #   409 로 죽는다 — 일이 다 끝나고 나서 실패하는 최악의 자리다.
    api.create_tag(REPO_ID, repo_type="dataset", tag=tag_name, tag_message=msg,
                   exist_ok=True)

    # 무엇을 올렸는지 매니페스트에 적는다 — 다음 증분 업로드가 이 기록으로 차이를 낸다.
    up_files = {f["path"]: f["sha256"] for _, fs in sel for f in fs}
    prev_up = (man.get("uploaded") or {}).get("files") or {}
    prev_up.update(up_files)
    man["uploaded"] = {"at": _now_kst(), "tag": tag_name, "repo_id": REPO_ID,
                       "mode": "incremental" if incremental else "full",
                       "files": prev_up}
    _write_json_atomic(MANIFEST_PATH, man)

    print(f"  ✅ 끝 · {time.time() - t0:,.1f}초 · "
          f"https://huggingface.co/datasets/{REPO_ID}/tree/{tag_name}")
    print("  ⚠️ 업로드 폴더 안에 생긴 `.cache/huggingface` 를 git add 하지 않는다")
    print("  ※ 방금 올린 매니페스트에는 이 업로드 기록이 아직 없다(기록이 업로드보다"
          " 뒤다). 다음 업로드 때 함께 올라간다 — 원격의 정본 판정은 `status --remote` 다.")
    return 0


# ==================================================
# 9. CLI
# ==================================================
def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="python scripts/hf_dataset.py",
        description="HF 데이터셋 — SQLite 를 파케이로 내보내 올리고, 되살린다")
    p.add_argument("mode", choices=["export", "upload", "status", "verify", "restore"],
                   help="export=파케이로 내보내기 · upload=HF 로 올리기(기본 dry-run) · "
                        "status=현황과 '지워도 되는가' 판정 · verify=온전한지 확인 · "
                        "restore=파케이로 SQLite 되살리기(기본은 임시 폴더 리허설)")
    p.add_argument("--tables", help=f"대상 표 (예: dividend,corporate_action). "
                                    f"생략하면 전부: {','.join(TABLES)}")
    p.add_argument("--years", help="대상 연도 (예: 2026 또는 2025,2026). "
                                   "연도로 쪼갠 표에만 듣는다")
    p.add_argument("--force", action="store_true",
                   help="export: 이미 낸 파티션도 다시 쓴다 "
                        "(⚠️ 파케이 옵션을 바꿨을 때만 — HF 중복제거가 전부 무효가 된다) · "
                        "restore: 대상 파일이 이미 있어도 덮어쓴다")
    p.add_argument("--yes", action="store_true",
                   help="upload: **실제로 올린다.** 없으면 dry-run 이다")
    p.add_argument("--incremental", action="store_true",
                   help="upload: 업로드 기록과 달라진 파일만 단일 커밋으로 올린다")
    p.add_argument("--allow-lfs", action="store_true",
                   help="upload: hf_xet 없이(=LFS) 올리는 것을 허용한다. 권하지 않는다")
    p.add_argument("--tag", help="upload: 붙일 태그. 기본 snapshot-YYYY-MM-DD")
    p.add_argument("--remote", action="store_true",
                   help="status: 원격까지 조회한다 (whoami·repo_info — 읽기만)")
    p.add_argument("--deep", action="store_true",
                   help="verify: 큰 표까지 숫자 칸 합·NULL 수를 대조한다 (느리다)")
    p.add_argument("--into", help="restore: 되살릴 SQLite 경로. "
                                  "생략하면 임시 폴더에 복원했다 지우는 리허설")
    p.add_argument("--from", dest="src",
                   help="restore: 파케이가 있는 폴더. 생략하면 data/hf_export")
    p.add_argument("--quiet", action="store_true")
    a = p.parse_args(argv)

    tables = [c.strip() for c in a.tables.split(",")] if a.tables else None
    years = [c.strip() for c in a.years.split(",")] if a.years else None

    if a.mode == "status":
        status(remote=a.remote)
        return 0
    if a.mode == "verify":
        return verify(deep=a.deep, tables=tables)
    if a.mode == "restore":
        return restore(into=a.into, src=a.src, tables=tables, force=a.force,
                       verbose=not a.quiet)
    if a.mode == "upload":
        return upload(yes=a.yes, incremental=a.incremental,
                      allow_lfs=a.allow_lfs, tag=a.tag)

    print("파케이로 내보내는 중 …")
    t = export(tables=tables, years=years, force=a.force, verbose=not a.quiet)
    print(f"  표 {t['tables']:,} · 새로 쓴 파일 {t['files']:,} · 건너뜀 {t['skipped']:,} "
          f"· {t['seconds']:,.1f}초")
    print(f"  내보낸 것 전체: {t['total_rows']:,}행 · {_human(t['total_bytes'])}")
    db_b = config.DB_PATH.stat().st_size
    print(f"  SQLite {_human(db_b)} 대비 {t['total_bytes'] / db_b * 100:,.2f}%")
    if t["missing"]:
        print(f"  ⚠️ 아직 없어 건너뛴 표: {', '.join(t['missing'])} "
              f"— 만들어지면 다시 `export` 를 돌린다")
    print(f"  매니페스트 {_rel_root(MANIFEST_PATH)}")
    print(f"  dataset card {_rel_root(README_PATH)}")
    print("  다음: `verify --deep` → `restore`(리허설) → `status` 로 삭제 판정을 본다")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
