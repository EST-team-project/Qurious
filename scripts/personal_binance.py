"""개인 프로젝트용 코인 수집(Binance Vision) — 받기 → 정제 → 적재 → (개인 조직에만) 올리기 (할 일 ①-13 · 2026-10-30).

**팀 러너(`daily_update.py`)에 넣지 않는다.** 대용량 개인 확장용이라 이동원 PC 에서만 손으로 돌리고, 저장처는 개인 조직 `Finance-Data` 다
(팀원은 그 조직 권한이 없다 — 올리기 전에 `collector.hf_orgs` 가 권한을 읽어 없으면 에러 없이 건너뛴다).

    python scripts/personal_binance.py fetch   --symbols BTCUSDT,ETHUSDT --from 2026-09 --to 2026-09          # 받기 + 정제(달 파일)
    python scripts/personal_binance.py compile --symbols BTCUSDT,ETHUSDT --years 2026                         # 적재(연 · 종목 파일)
    python scripts/personal_binance.py upload  --repo Finance-Data/binance-spot-ohlcv --dry-run               # 올릴 것만 보기
    python scripts/personal_binance.py upload  --repo Finance-Data/binance-spot-ohlcv                         # 올리기(100개 안팎씩 커밋)

  · 기본 루트 `data/personal/binance`(git 제외). 받을 때 0.1초 간격 · 체크섬 대조 · 이미 받은 달은 건너뜀(`--force` 로 다시).
  · 주기 기본 = 바이낸스 원본 15종(1초봉 제외 — 계약 문서 3.3절). 이용 조건: CC BY-NC-SA 4.0(비상업 · 학습 · 연구).
"""
from __future__ import annotations

import argparse
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import List, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collector import binance_store, binance_vision, hf_orgs  # noqa: E402
from collector.console import utf8_stdio  # noqa: E402

DEFAULT_ROOT = ROOT / "data" / "personal" / "binance"
UA = {"User-Agent": "qurious-personal-research"}
DELAY_S = 0.1
BATCH = 90          # HF 한 커밋 100개 미만 권장


def _http(url: str, timeout: int = 60) -> Optional[bytes]:
    try:
        return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None                       # 그 달 파일이 없다(상장 전 · 폐지 뒤) — 오류가 아니다
        raise


def fetch_one(root: Path, symbol: str, interval: str, year: int, month: int, *, force: bool = False) -> str:
    """한 (종목 · 주기 · 달) — `ok` · `skip` · `none`(원천에 없음). 체크섬이 안 맞으면 `ValueError`."""
    target = binance_store.month_path(root, interval, symbol, year, month)
    if target.exists() and not force:
        return "skip"
    data = _http(binance_vision.zip_url(symbol, interval, year, month))
    if data is None:
        return "none"
    sha = None
    chk = _http(binance_vision.checksum_url(symbol, interval, year, month))
    if chk is not None:
        sha = binance_vision.parse_checksum(chk.decode("utf-8"))
    out = binance_vision.to_v2_rows(data, symbol, interval, expected_sha256=sha, fetched_at=time.strftime("%Y-%m-%dT%H:%M:%S+09:00", time.gmtime(time.time() + 9 * 3600)))
    if out["problems"]:
        print(f"  ⚠ {symbol} {interval} {year}-{month:02d}: 값 규칙 위반 {out['problems']} (줄은 보관)")
    binance_store.write_month(root, interval, symbol, year, month, out["rows"])
    time.sleep(DELAY_S)
    return "ok"


def cmd_fetch(a) -> int:
    fy, fm = (int(x) for x in a.frm.split("-"))
    ty, tm = (int(x) for x in a.to.split("-"))
    months = binance_vision.month_range((fy, fm), (ty, tm))
    intervals = list(binance_vision.INTERVALS) if a.intervals == "all" else a.intervals.split(",")
    syms = a.symbols.split(",")
    count = {"ok": 0, "skip": 0, "none": 0}
    for sym in syms:
        for iv in intervals:
            for (y, m) in months:
                count[fetch_one(Path(a.root), sym, iv, y, m, force=a.force)] += 1
        print(f"✅ {sym} — 받기 {count}")
    return 0


def cmd_compile(a) -> int:
    root = Path(a.root)
    syms = a.symbols.split(",")
    years = [int(y) for y in a.years.split(",")]
    n, dups = 0, []
    for sym in syms:
        for iv in binance_vision.INTERVALS:
            targets = [None] if iv in binance_vision.COARSE else years
            for y in targets:
                r = binance_store.compile_partition(root, root, iv, sym, y)
                if r:
                    n += 1
                    if r["dropped_exact_dups"]:
                        dups.append(f"{sym} {iv} {y or '전체'}: {r['dropped_exact_dups']}줄")
    s = binance_store.summarize(root)
    total = sum(v["bytes"] for v in s.values())
    print(f"✅ 적재 파일 {n}개 · 합 {total / 1e6:.2f} MB")
    if dups:
        print("   원천에서 같은 줄이 두 번 온 것을 한 줄로 줄임 — " + " · ".join(dups))
    for tf, v in sorted(s.items(), key=lambda kv: -kv[1]["bytes"]):
        print(f"   {tf:5} 파일 {v['files']:4} · {v['bytes'] / 1e6:8.2f} MB")
    return 0


def cmd_upload(a) -> int:
    """개인 조직에만 올린다 — 권한 사전 점검 → 없으면 건너뜀(에러 아님). `--dry-run` 은 올릴 파일만 센다."""
    root = Path(a.root)
    files = sorted((root / "ohlcv").glob("**/*.parquet"))
    if not files:
        print("올릴 적재 파일이 없다 — `compile` 을 먼저 돌린다")
        return 0
    org = a.repo.split("/")[0]
    if org == hf_orgs.TEAM_ORG:
        print(f"🔴 {org} 는 팀 조직이다 — 대용량 개인 자료는 {hf_orgs.PERSONAL_ORG} 에만 올린다")
        return 2
    tok = hf_orgs.personal_token()
    if not tok:
        print("⏭ 토큰이 없다 — 개인 조직 올리기는 건너뛴다")
        return 0
    from huggingface_hub import CommitOperationAdd, HfApi
    api = HfApi(token=tok)
    acc = hf_orgs.check_with_api(api, org)
    if not acc.ok:
        print(f"⏭ {acc.reason}")
        return 0
    print(f"✅ {acc.reason} · 올릴 파일 {len(files)}개 · 합 {sum(f.stat().st_size for f in files) / 1e6:.1f} MB → {a.repo}")
    if a.dry_run:
        print("(dry-run — 올리지 않았다)")
        return 0
    try:
        for i in range(0, len(files), BATCH):
            batch = files[i:i + BATCH]
            ops = [CommitOperationAdd(path_in_repo=f.relative_to(root).as_posix(), path_or_fileobj=str(f)) for f in batch]
            api.create_commit(repo_id=a.repo, repo_type="dataset", operations=ops,
                              commit_message=f"binance spot ohlcv — {len(batch)} files ({i + 1}~{i + len(batch)})")
            print(f"  커밋 {i // BATCH + 1}: 파일 {len(batch)}개")
    except Exception as e:                                            # noqa: BLE001
        if hf_orgs.is_no_access_error(e):
            print(f"⏭ 접근 불가({type(e).__name__}) — 개인 조직 올리기는 건너뛴다")
            return 0
        raise
    print("✅ 올림")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(description="개인 프로젝트용 코인 수집(Binance Vision) — 팀 러너 밖")
    ap.add_argument("--root", default=str(DEFAULT_ROOT))
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("--symbols", required=True)
    f.add_argument("--from", dest="frm", required=True, help="YYYY-MM")
    f.add_argument("--to", required=True, help="YYYY-MM")
    f.add_argument("--intervals", default="all")
    f.add_argument("--force", action="store_true")
    c = sub.add_parser("compile")
    c.add_argument("--symbols", required=True)
    c.add_argument("--years", required=True, help="잘게 쪼갠 주기용 해 목록(쉼표)")
    u = sub.add_parser("upload")
    u.add_argument("--repo", required=True)
    u.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    return {"fetch": cmd_fetch, "compile": cmd_compile, "upload": cmd_upload}[a.cmd](a)


if __name__ == "__main__":
    raise SystemExit(main())
