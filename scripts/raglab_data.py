"""통합본의 화면 표시용 시세 자료를 비공개 데이터셋에 올리고 받는다.

무엇을 다루나
    `rag-lab/` 을 옮겨 올 때 **git 에 넣지 않은 파일 셋**이다(반입 대장의 「HF 보관」 줄).
    네이버 금융 · 토스증권 · 야후에서 모은 시세 값이라 공개 저장소에 커밋하지 않고,
    팀의 비공개 데이터셋(Hugging Face)에 둔다. 통합본의 몇몇 화면(강의 사이트의 ETF 목록,
    분석 화면의 차트 예시)은 이 파일이 있어야 그려진다 — 그 화면을 볼 사람만 받으면 된다.

왜 git 이 아니라 비공개 데이터셋인가
    팀 규칙은 「외부에서 받은 시세를 **저장소에 적재하지 않는다**」 이다(화면에 보여 주는 것은 된다).
    이 저장소는 공개라 한 번 커밋하면 이력에서 뺄 수 없다. 데이터셋은 비공개로 두고, 올리기 전에
    원격이 정말 비공개인지 **확인한 뒤에만** 올린다.

쓰는 법
    python scripts/raglab_data.py status                 # 내 PC · 원격에 무엇이 있나
    python scripts/raglab_data.py pull                   # 비공개 데이터셋에서 받아 rag-lab/ 에 둔다
    python scripts/raglab_data.py push --from <폴더>      # <폴더>(통합본 원본)의 세 파일을 올린다

    토큰은 `.env` 의 HUGGINGFACE_ACCESS_TOKEN 을 쓴다(수집 데이터 백업과 같은 토큰 · 화면에 찍지 않는다).
    받은 파일은 .gitignore 에 적혀 있어 커밋되지 않는다 — `python scripts/raglab_scan.py --check` 가 지킨다.
"""
from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:             # `python scripts/raglab_data.py` 로 바로 돌릴 때 저장소 모듈을 찾게
    sys.path.insert(0, str(ROOT))

from collector import config                                  # noqa: E402 — .env 읽기(환경변수 먼저)
from scripts import raglab_scan as scan                       # noqa: E402 — 대장 · blob 계산을 같이 쓴다

#: 비공개 데이터셋 이름. 수집 데이터 백업(`qurious-quant/krx-daily-market`)과 **따로** 둔다 —
#: 그쪽은 공식 출처(공공데이터포털 · KRX)에서 받은 값이고, 이쪽은 화면 표시용으로 모은 값이라 성격이 다르다.
REPO_ID = "qurious-quant/rag-lab-display-data"

CARD = """---
license: other
pretty_name: 통합본 화면 표시용 시세 자료 (비공개)
---

# 통합본 화면 표시용 시세 자료

Qurious 저장소의 `rag-lab/`(통합본 investment-rag-lab 반입 폴더)이 화면을 그릴 때 읽는 시세 자료 셋이다.
**저장소(git)에는 넣지 않았다.** 이 데이터셋은 비공개로만 둔다 — 공개로 바꾸지 않는다.

| 파일 | 내용 | 모은 곳 |
|---|---|---|
| `frontend/days/assets/etf-catalog.json` | 국내 상장 ETF 목록 · 3개월 수익률 · 구성종목 | 네이버 금융 목록 · 토스증권 화면의 구성종목 응답 |
| `frontend/days/assets/leverage-etf-volume.json` | 레버리지 · 인버스 ETF 2종의 월 거래대금 합계 | 네이버 금융 월봉에서 계산 |
| `frontend/analysis/data/samsung-cup-with-handle-2025.json` | 삼성전자 일봉(차트 패턴 예시) | 야후 파이낸스 |

- 쓰임: 팀 안에서 통합본 화면을 띄워 보는 데만 쓴다. 상업적으로 쓰지 않는다.
- 값은 모은 날짜 기준이다(파일 안 `updatedAt` · `retrieved_at`). 투자 판단에 쓰지 않는다.
- 받기: Qurious 저장소에서 `python scripts/raglab_data.py pull`
- 파일 내용은 Qurious 의 `docs/설계/대장/통합본-반입대장.tsv` 「HF 보관」 줄의 blob 과 같아야 한다.
"""


def held_rows() -> list[dict[str, str]]:
    """반입 대장에서 「HF 보관」 으로 적힌 줄 — 이 도구가 다루는 파일의 전부다."""
    ledger = scan.read_tsv(scan.IMPORT_LEDGER, scan.IMPORT_COLUMNS)
    return [r for r in ledger if r["상태"] == scan.STATE_HF]


def _matches_ledger(path: Path, row: dict[str, str]) -> bool:
    return path.is_file() and row["blob"] in scan.git_blob_ids(path.read_bytes())


def _api(required: bool):
    """(HfApi, 토큰 있음 여부). 토큰은 어디에도 찍지 않는다."""
    token = config.require("HUGGINGFACE_ACCESS_TOKEN", "Hugging Face 접근 토큰") if required \
        else (config.env("HUGGINGFACE_ACCESS_TOKEN") or None)
    if not token:
        return None
    from huggingface_hub import HfApi     # 토큰이 있을 때만 가져온다 — 없는 PC 에서도 status 는 돈다
    return HfApi(token=token)


def _remote_state(api) -> tuple[str, set[str]]:
    """(원격 상태 글자, 원격에 있는 파일 경로들). 저장소가 없거나 못 읽으면 빈 집합."""
    try:
        info = api.repo_info(REPO_ID, repo_type="dataset")
    except Exception as e:               # 없음(404) · 권한 없음 · 네트워크 — 무엇이든 「확인 못 함」 이다
        return f"못 읽음({type(e).__name__})", set()
    files = {s.rfilename for s in (info.siblings or [])}
    return ("비공개" if info.private else "공개"), files


def status() -> int:
    rows = held_rows()
    print(f"대상 {len(rows)}개 — 반입 대장의 「{scan.STATE_HF}」 줄")
    api = _api(required=False)
    state, remote = _remote_state(api) if api else ("토큰 없음 — 원격은 보지 않았다", set())
    print(f"원격 {REPO_ID}: {state}")
    for r in rows:
        local = scan.FOLDER / r["경로"]
        here = "있음(대장과 같음)" if _matches_ledger(local, r) else ("있음(대장과 다름)" if local.exists() else "없음")
        there = "있음" if r["경로"] in remote else ("없음" if api and not state.startswith("못 읽음") else "—")
        print(f"  {r['경로']}\n      내 PC {here} · 원격 {there} · {int(r['크기']) / 1024:.0f} KB")
    return 0


def push(source: Path) -> int:
    rows = held_rows()
    # 1) 올릴 파일이 대장에 적힌 그 내용인지 먼저 본다 — 다른 판을 올리면 받는 쪽 검사가 깨진다.
    for r in rows:
        if not _matches_ledger(source / r["경로"], r):
            print(f"🔴 {source / r['경로']} 가 없거나 반입 대장의 blob 과 다르다 — 올리지 않는다.")
            return 1
    api = _api(required=True)
    # 2) 만들고 → 정말 비공개인지 확인하고 → 그다음에 올린다.
    #    create_repo(private=True, exist_ok=True) 는 **이미 있는 저장소의 공개 범위를 바꾸지 않는다.**
    #    누가 먼저 공개로 만들어 뒀다면 그대로 공개에 올라가므로, 만드는 것과 확인하는 것을 따로 한다.
    api.create_repo(REPO_ID, repo_type="dataset", private=True, exist_ok=True)
    state, _ = _remote_state(api)
    if state != "비공개":
        print(f"🔴 원격이 비공개임을 확인하지 못했다({state}). 확인 못 한 것은 통과가 아니다 — 올리지 않는다.\n"
              f"   할 일: https://huggingface.co/datasets/{REPO_ID}/settings 에서 Private 인지 본다.")
        return 1
    print(f"✅ 원격이 비공개다: {REPO_ID}")
    with tempfile.TemporaryDirectory() as tmp:
        card = Path(tmp) / "README.md"
        card.write_text(CARD, encoding="utf-8", newline="\n")
        api.upload_file(path_or_fileobj=str(card), path_in_repo="README.md", repo_id=REPO_ID,
                        repo_type="dataset", commit_message="안내문")
    for r in rows:
        api.upload_file(path_or_fileobj=str(source / r["경로"]), path_in_repo=r["경로"], repo_id=REPO_ID,
                        repo_type="dataset", commit_message=f"화면 표시용 시세 자료: {Path(r['경로']).name}")
        print(f"  올림 {r['경로']}")
    state, remote = _remote_state(api)
    missing = [r["경로"] for r in rows if r["경로"] not in remote]
    print(f"원격 확인: {state} · 파일 {len(remote)}개" + (f" · 빠진 것 {missing}" if missing else " · 세 파일 모두 있음"))
    return 1 if missing or state != "비공개" else 0


def pull() -> int:
    rows = held_rows()
    api = _api(required=True)
    from huggingface_hub import hf_hub_download

    failed = 0
    for r in rows:
        target = scan.FOLDER / r["경로"]
        if _matches_ledger(target, r):
            print(f"  이미 있음 {r['경로']}")
            continue
        got = hf_hub_download(REPO_ID, r["경로"], repo_type="dataset", token=api.token)
        if not _matches_ledger(Path(got), r):
            print(f"🔴 받은 파일이 반입 대장의 blob 과 다르다 — 두지 않는다: {r['경로']}")
            failed += 1
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(got, target)
        print(f"  받음 {r['경로']}")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    # git bash(mintty)에서는 표준출력이 cp949 가 된다 → ✅ · — 한 글자에서 죽는다. 도움말보다 먼저 맞춘다.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="통합본 화면 표시용 시세 자료 — 비공개 데이터셋에 올리고 받는다")
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="내 PC 와 원격에 무엇이 있는지 본다(토큰이 없으면 내 PC 만)")
    sub.add_parser("pull", help="비공개 데이터셋에서 받아 rag-lab/ 에 둔다")
    p = sub.add_parser("push", help="원본 폴더의 세 파일을 비공개 데이터셋에 올린다")
    p.add_argument("--from", dest="source", required=True, metavar="폴더",
                   help="통합본 원본(investment-rag-lab) 폴더 — 그 안의 같은 경로에서 파일을 읽는다")
    args = ap.parse_args(argv)
    if args.command == "status":
        return status()
    if args.command == "pull":
        return pull()
    return push(Path(args.source))


if __name__ == "__main__":
    raise SystemExit(main())
