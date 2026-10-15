"""모델 비교 계산 작업 — 앱 안 작업 · 1초마다 진행 묻기 · 자료 지문으로 맞춰 보는 결과 캐시 (2026-10-15 사용자 결정)

왜 따로 두나
-----------
한 번 계산에 10 ~ 30초가 든다(앱 안 실측 — 2년 11.8초 · 5년 30.3초). 요청 하나로 기다리게 하면 10초를 넘는 순간
사람이 주의를 잃고(NN/g), 다른 화면에 다녀오면 계산이 버려진다. 그래서 계산은 앱 안 작업으로 띄우고 화면은 진행을
묻는다. 계산 엔진(`model_compare`)은 그대로 두고, 이 파일은 「언제 · 몇 개를 · 어디에 담나」 만 맡는다(SRP).

규칙
----
- **결과 캐시** — 앱 표준 `data_cache`(앱 DB)에 `model_compare:v1:코드:기간:설정 지문` 열쇠로 담는다. 값에 자료 지문을
  함께 담고, 요청마다 일봉을 읽어(빠름) **지문이 같을 때만** 저장본을 준다 — 수정주가 표는 매 거래일 통째로 다시 만들어져
  분할 · 권리락이 생기면 과거 값이 바뀌므로 기준일만으로는 모자란다. 오류는 담지 않는다 · 7일이 지나면 쓰지 않는다.
- **같은 열쇠는 한 번만** — 계산 중인 열쇠로 또 오면 새로 띄우지 않고 그 작업에 붙는다(single-flight).
- **동시 계산 수 한도** — CPU 를 다 쓰는 계산이라 한 번에 `MAX_CONCURRENT` 개까지 · 나머지는 「차례 기다림」.
- **진행은 실제로 센 값** — 모델 k / 전체 · 겹 f / 전체 · 지금 시험 구간 · 지난 시간 · 보통 걸리는 시간(같은 기간의 지난 계산이
  있으면 그 값). 지어낸 백분율은 쓰지 않는다.
- 작업은 이 프로세스 기억에만 있다 — 서버를 다시 켜면 계산 중이던 작업은 사라지고(화면은 「다시 계산」 을 보인다),
  끝난 결과는 캐시에 남는다. 끝난 작업은 `JOB_KEEP_SECONDS` 뒤에 지운다.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

from app.services import model_compare as mc
from app.services.data_cache import cache_get, cache_set

logger = logging.getLogger(__name__)

CACHE_TTL_HOURS = 24 * 7
MAX_CONCURRENT = 2
JOB_KEEP_SECONDS = 15 * 60
MAX_JOBS = 64
KST = timezone(timedelta(hours=9))


@dataclass
class Job:
    id: str
    key: str
    code: str
    period: str
    n_splits: Optional[int]
    gap: Optional[int]
    status: str = "queued"                 # queued · running · done · error
    progress: Dict = field(default_factory=dict)
    created: float = field(default_factory=time.monotonic)
    started: Optional[float] = None
    finished: Optional[float] = None
    result: Optional[Dict] = None
    error: Optional[mc.ModelCompareError] = None
    task: Optional[asyncio.Task] = None

    def elapsed_ms(self) -> int:
        end = self.finished or time.monotonic()
        return int((end - (self.started or self.created)) * 1000)


_jobs: Dict[str, Job] = {}
_by_key: Dict[str, str] = {}
_lock = threading.Lock()
_slots = threading.BoundedSemaphore(MAX_CONCURRENT)
_last_ms: Dict[str, int] = {}             # 기간마다 지난 계산에 걸린 시간 — 「보통 n초」 의 근거


def expected_ms(period: str) -> Dict:
    last = _last_ms.get(period)
    if last:
        return {"expected_ms": last, "expected_basis": "last"}
    return {"expected_ms": mc.PERIOD_SPEC[period]["expected_ms"], "expected_basis": "typical"}


def _now_kst() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


def _purge() -> None:
    """끝난 지 오래된 작업을 지운다 · 너무 많으면 오래된 끝난 작업부터(도는 작업은 지우지 않는다)."""
    now = time.monotonic()
    with _lock:
        done = [j for j in _jobs.values() if j.finished and now - j.finished > JOB_KEEP_SECONDS]
        extra = max(0, len(_jobs) - len(done) - MAX_JOBS)
        if extra:
            done += sorted((j for j in _jobs.values() if j.finished and j not in done), key=lambda j: j.finished)[:extra]
        for j in done:
            _jobs.pop(j.id, None)
            if _by_key.get(j.key) == j.id:
                _by_key.pop(j.key, None)


def view(job: Job) -> Dict:
    """화면이 묻는 진행 — 끝났으면 결과, 오류면 예외(라우트가 그 상태 코드로)."""
    if job.status == "error" and job.error is not None:
        raise job.error
    out = {"status": job.status, "job_id": job.id, "cached": False, "elapsed_ms": job.elapsed_ms(),
           **expected_ms(job.period), "progress": dict(job.progress)}
    if job.status == "done":
        out["result"] = job.result
    return out


def _compute(job: Job, loaded: Dict) -> Dict:
    """작업 스레드 — 자리가 날 때까지 기다린 뒤 엔진을 돌린다. 진행은 엔진이 알린 값을 그대로 옮긴다."""
    with _slots:
        job.status = "running"
        job.started = time.monotonic()

        def tell(info: Dict) -> None:
            job.progress = info

        return mc.compute_loaded(loaded, job.n_splits, job.gap, progress=tell)


async def _run(job: Job, loaded: Dict) -> None:
    try:
        result = await asyncio.to_thread(_compute, job, loaded)
        result["computed_at"] = _now_kst()
        result["cached"] = False
        job.result = result
        job.finished = time.monotonic()
        _last_ms[job.period] = job.elapsed_ms()
        job.status = "done"
        await cache_set(job.key, {"fingerprint": loaded["fingerprint"], "computed_at": result["computed_at"],
                                  "elapsed_ms": result.get("elapsed_ms"), "result": result})
    except mc.ModelCompareError as e:
        job.error, job.status, job.finished = e, "error", time.monotonic()
    except Exception as e:  # 엔진의 뜻밖 오류 — 사람에게는 까닭 한 줄 · 관리자에게는 종류와 글
        logger.exception("[model_compare] %s %s 계산 실패", job.code, job.period)
        job.error = mc.ModelCompareError(500, "계산 중 문제가 생겼습니다. 잠시 뒤 다시 시도해 주세요.",
                                         hint=f"{type(e).__name__}: {e}", code="compute_failed")
        job.status, job.finished = "error", time.monotonic()


def _start_or_join(key: str, loaded: Dict, n_splits: Optional[int], gap: Optional[int]) -> Job:
    with _lock:
        jid = _by_key.get(key)
        job = _jobs.get(jid) if jid else None
        if job is not None and job.status in ("queued", "running"):
            return job                                     # 같은 열쇠 — 붙는다
        job = Job(id=uuid.uuid4().hex, key=key, code=loaded["code"], period=loaded["period"],
                  n_splits=n_splits, gap=gap)
        job.progress = {"stage": "queued"}
        _jobs[job.id] = job
        _by_key[key] = job.id
    job.task = asyncio.get_running_loop().create_task(_run(job, loaded))
    return job


async def start(symbol: str, period: str, n_splits: Optional[int] = None, gap: Optional[int] = None,
                admin: bool = False) -> Dict:
    """계산 시작(또는 저장본 · 도는 작업에 붙기). 저장본이 맞으면 곧바로 결과를 준다."""
    _purge()
    code = mc.check_request(symbol, period, n_splits, gap, admin)
    loaded = await asyncio.to_thread(mc.load_daily, code, period)
    key = mc.cache_key(code, period, mc.N_SPLITS if n_splits is None else n_splits, gap)
    hit = await cache_get(key, max_age_hours=CACHE_TTL_HOURS)
    if hit and hit.get("fingerprint") == loaded["fingerprint"] and isinstance(hit.get("result"), dict):
        result = dict(hit["result"], cached=True)
        return {"status": "done", "job_id": None, "cached": True, "elapsed_ms": 0, **expected_ms(period),
                "progress": {}, "result": result}
    return view(_start_or_join(key, loaded, n_splits, gap))


def status(job_id: str) -> Dict:
    _purge()
    job = _jobs.get(job_id or "")
    if job is None:
        raise mc.ModelCompareError(404, "계산 작업을 찾지 못했습니다 — 서버가 다시 켜졌거나 오래된 작업입니다. "
                                        "다시 계산해 주세요.", code="job_not_found")
    return view(job)


async def compute(symbol: str, period: str, n_splits: Optional[int] = None, gap: Optional[int] = None,
                  admin: bool = False) -> Dict:
    """기다렸다가 결과만 — 화면이 아닌 쪽(스크립트 · 점검)이 부르는 길. 같은 작업 · 캐시를 쓴다."""
    got = await start(symbol, period, n_splits, gap, admin)
    if got["status"] == "done":
        return got["result"]
    job = _jobs[got["job_id"]]
    await asyncio.shield(job.task)
    return view(job)["result"]


def reset_for_tests() -> None:
    with _lock:
        _jobs.clear()
        _by_key.clear()
    _last_ms.clear()
