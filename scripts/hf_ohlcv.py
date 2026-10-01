"""HF ``qurious-quant/krx-ohlcv`` (private) — ``ohlcv-v1`` 파케이 올리기 · 확인.

    python scripts/hf_ohlcv.py status                 원격 공개 범위 · 파일 수 (읽기만)
    python scripts/hf_ohlcv.py upload                 dry-run — 무엇을 어디로 올릴지 보여 주기만
    python scripts/hf_ohlcv.py upload --yes           실제로 올린다 (관문 넷 통과 시)
    python scripts/hf_ohlcv.py upload-contrib <폴더> --yes   검사를 통과한 팀원 자료(contrib/<아이디>/<날짜>/)

``krx-daily-market``(수집 DB 백업 · `scripts/hf_dataset.py`)과 따로 둔다 — 그쪽은 DB 를 통째로
되살리는 용도이고, 이쪽은 분석하는 사람이 바로 읽는 규격 자료다(설계서 11절).

관문 넷 (`scripts/hf_dataset.py` 와 같은 원칙)
  1. ``QURIOUS_RAW_SHARING`` 이 켜져 있다 — 원자료 공유는 팀 결정을 확인한 흔적이 있어야 한다
  2. 매니페스트가 있고 반쪽(.part) 파일이 없다
  3. hf_xet 이 켜져 있다 — 바뀐 청크만 올라간다
  4. 원격이 **실제로 private** 이다 — ``create_repo(private=True, exist_ok=True)`` 는 이미 있는 저장소의
     공개 범위를 바꾸지 않으므로, 만들고 나서 ``repo_info`` 로 다시 확인한다
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

for _s in (sys.stdout, sys.stderr):           # git bash(cp949)에서 줄표 · 그림 글자로 죽지 않게
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from collector import config  # noqa: E402
from collector import manifest as collector_manifest  # noqa: E402
from collector.ohlcv import KST  # noqa: E402
from collector.ohlcv_export import NOTES, OUT_DIR  # noqa: E402

REPO_ID = "qurious-quant/krx-ohlcv"


def _token(required: bool = True) -> Optional[str]:
    """HF 토큰. 절대 출력하지 않는다."""
    if required:
        return config.require("HUGGINGFACE_ACCESS_TOKEN", "Hugging Face 접근 토큰 (write 권한)")
    return config.env("HUGGINGFACE_ACCESS_TOKEN") or None


def _sharing_on() -> bool:
    return bool(collector_manifest.RAW_SHARING) or os.environ.get("QURIOUS_RAW_SHARING", "").lower() in ("1", "true", "yes")


def _assert_private(api, create: bool) -> bool:
    if create:
        api.create_repo(REPO_ID, repo_type="dataset", private=True, exist_ok=True)
    try:
        info = api.repo_info(REPO_ID, repo_type="dataset")
    except Exception as e:
        print(f"  🔴 공개 범위를 확인하지 못했다({type(e).__name__}) — 확인 못 한 것은 통과가 아니다. 올리지 않는다.")
        return False
    if info.private:
        print("  ✅ 원격이 private 임을 확인했다")
        return True
    print(f"  🔴 원격이 public 이다 — 올리지 않는다. https://huggingface.co/datasets/{REPO_ID}/settings 에서 Private 로.")
    return False


def _readme(man: dict) -> str:
    rows = man.get("rows", {})
    lines = [
        "---", "license: other", "language: [ko]", "pretty_name: KRX OHLCV (ohlcv-v1)", "viewer: false", "---", "",
        "# KRX OHLCV — `ohlcv-v1`", "",
        "🔴 **이 저장소는 private 이어야 한다.** 원자료의 이용 조건(공공데이터포털 공공누리 제4유형 · 제3자 재배포 금지)"
        " 때문에 팀(private Organization) 안에서 학습 목적으로만 쓰고 밖으로 내보내지 않는다.", "",
        f"- 기준일 **{man.get('as_of')}** · 만든 시각 {man.get('built_at')} · 수집기 `{man.get('collector_commit')}`",
        f"- 행 수 " + " · ".join(f"{k} {v:,}" for k, v in rows.items() if v),
        f"- 분봉 유니버스 `{man.get('universe_version')}` (`meta/universe.csv` — 고른 근거 칸 포함)",
        f"- 진행 중인 주(주봉 partial): {', '.join(man.get('partial_weeks', [])) or '없음'}", "",
        "## 칸", "", "| 칸 | 뜻 |", "|---|---|",
        "| symbol | 주식 · ETF 단축코드 6자리 · 지수는 `KOSPI:코스피 200` 처럼 시리즈:이름 |",
        "| market | KOSPI · KOSDAQ · KONEX · ETF · INDEX |",
        "| timeframe | 1d · 1w · 60m · 5m |",
        "| trade_date · bar_start | 거래일(KST) · 분봉의 봉 시작 시각(KST, +09:00) |",
        "| open · high · low · close · volume · value | 원(지수는 포인트) · 주 · 거래대금(원) |",
        "| adjusted · price_basis · adj_factor | 수정 여부 · raw / adj_base(기준가 계수) / adj_split(분할 비율) · 원 가격 × 계수 = 수정 가격 |",
        "| session | 분봉의 장 구간 — regular · close_auction · pre_open · outside |",
        "| source · fetched_at · contract | 출처 · 받은 시각 · `ohlcv-v1` |", "",
        "## 읽는 법", "", "```python",
        "import pandas as pd",
        f"df = pd.read_parquet('hf://datasets/{REPO_ID}/ohlcv/timeframe=1d/basis=adj_base/market=KOSPI/year=2026/part-0.parquet')",
        "```", "", "## 알아 둘 것 (실측 2026-10-01)", "",
    ] + [f"- {n}" for n in NOTES] + ["", "## 팀원 자료", "",
        "검사를 통과한 팀원 자료는 `contrib/<깃허브 아이디>/<날짜>/` 에 보고서(`*.report.json`)와 함께 둔다. "
        "원래 자료와 합치지 않고 `source=contrib:<아이디>` 로 고른다."]
    return "\n".join(lines) + "\n"


def status() -> int:
    from huggingface_hub import HfApi
    man_p = OUT_DIR / "manifest.json"
    if man_p.exists():
        man = json.loads(man_p.read_text(encoding="utf-8"))
        print(f"― 로컬 내보내기 · 기준 {man['as_of']} · 파일 {len(man['files'])}개 · "
              f"{sum(f['bytes'] for f in man['files']) / 1e6:,.1f} MB · 행 {man['rows']}")
    else:
        print("― 로컬 내보내기 없음 — `python -m collector.ohlcv_export` 를 먼저 돌린다")
    tok = _token(required=False)
    if not tok:
        print("  토큰 없음 — 원격은 보지 않았다")
        return 0
    try:
        info = HfApi(token=tok).repo_info(REPO_ID, repo_type="dataset", files_metadata=False)
        print(f"― 원격 {REPO_ID} · {'private ✅' if info.private else '🔴 public'} · 파일 {len(info.siblings or [])}개 · "
              f"마지막 커밋 {str(info.sha)[:8]}")
    except Exception as e:
        print(f"― 원격 {REPO_ID} · 아직 없거나 권한이 없다({type(e).__name__})")
    return 0


def upload(yes: bool, folder: Optional[Path] = None, path_in_repo: str = "") -> int:
    src = folder or OUT_DIR
    man_p = src / "manifest.json"
    if folder is None and not man_p.exists():
        print("올릴 것이 없다 — `python -m collector.ohlcv_export` 를 먼저 돌린다.")
        return 1
    parts = sorted(src.rglob("*.part"))
    files = [p for p in src.rglob("*") if p.is_file() and p.suffix != ".part"]
    total = sum(p.stat().st_size for p in files)
    try:
        from huggingface_hub.utils._runtime import is_xet_available
        xet = is_xet_available()
    except Exception:
        xet = False
    print(f"― 업로드 {'(실행)' if yes else '(dry-run — 아무것도 올리지 않는다)'} ―")
    print(f"  대상   {REPO_ID}{'/' + path_in_repo if path_in_repo else ''} (dataset · private 이어야 한다)")
    print(f"  원본   {src}")
    print(f"  파일   {len(files):,}개 · {total / 1e6:,.1f} MB")
    print(f"  관문 1 공유 스위치 {'✅ 켜짐' if _sharing_on() else '🔴 꺼짐 — 실제 업로드는 막힌다'}")
    print(f"  관문 2 반쪽 파일 {'✅ 없음' if not parts else f'🔴 {len(parts)}개'}")
    print(f"  관문 3 hf_xet {'✅ 켜짐' if xet else '⚠️ 없음 — 파일 전체가 다시 올라간다'}")
    if not yes:
        tok = _token(required=False)
        if tok:
            from huggingface_hub import HfApi
            try:
                info = HfApi(token=tok).repo_info(REPO_ID, repo_type="dataset")
                print(f"  관문 4 원격 {'✅ private' if info.private else '🔴 public — 이대로면 올리지 않는다'} (읽기만)")
            except Exception as e:
                print(f"  관문 4 원격 아직 없다({type(e).__name__}) — `--yes` 가 private 으로 만든다")
        print("  실제로 올리려면 `--yes` 를 준다.")
        return 0
    if not _sharing_on():
        print("  🔴 QURIOUS_RAW_SHARING 이 꺼져 있다 — PowerShell `$env:QURIOUS_RAW_SHARING=\"1\"` · bash `export QURIOUS_RAW_SHARING=1`")
        return 1
    if parts:
        print("  🔴 반쪽 파일이 있다 — 내보내기를 다시 돌린다")
        return 1
    from huggingface_hub import HfApi
    api = HfApi(token=_token())
    if not _assert_private(api, create=True):
        return 1
    today = datetime.now(KST).strftime("%Y-%m-%d")
    if folder is None:
        man = json.loads(man_p.read_text(encoding="utf-8"))
        (src / "README.md").write_text(_readme(man), encoding="utf-8")
        msg = f"ohlcv-v1 스냅샷 {today}(KST) · 기준일 {man['as_of']} · " + " · ".join(
            f"{k} {v:,}" for k, v in man["rows"].items() if v)
    else:
        msg = f"팀원 자료 {path_in_repo} · {today}(KST)"
    info = api.upload_folder(repo_id=REPO_ID, repo_type="dataset", folder_path=str(src),
                             path_in_repo=path_in_repo or None, commit_message=msg,
                             ignore_patterns=["*.part", "*.tmp"])
    print(f"  ✅ 올렸다 — {getattr(info, 'oid', '')[:8] if hasattr(info, 'oid') else info}")
    if folder is None:
        tag = f"ohlcv-{today}"
        try:
            api.create_tag(REPO_ID, repo_type="dataset", tag=tag, tag_message=msg)
            print(f"  태그 {tag}")
        except Exception as e:
            print(f"  태그 {tag} 는 그대로 둔다({type(e).__name__} — 같은 날 두 번째 업로드)")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python scripts/hf_ohlcv.py", description=f"HF {REPO_ID} (private) 올리기 · 확인")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    p = sub.add_parser("upload")
    p.add_argument("--yes", action="store_true")
    p = sub.add_parser("upload-contrib")
    p.add_argument("folder", help="data/collector/contrib/<아이디>/<날짜>")
    p.add_argument("--yes", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "status":
        return status()
    if a.cmd == "upload":
        return upload(a.yes)
    folder = Path(a.folder).resolve()
    rel = folder.relative_to((config.DATA_DIR / "contrib").resolve()).as_posix()
    return upload(a.yes, folder, f"contrib/{rel}")


if __name__ == "__main__":
    sys.exit(main())
