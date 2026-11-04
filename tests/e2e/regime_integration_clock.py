"""과거 수집 스냅샷 재현용 앱 진입점. 운영 이미지/설정에는 포함하지 않는다.

API·준비 판정·계산 결과를 대체하지 않고, 리밸런싱의 현재 시각 입력만 고정한다.
내부 Docker 네트워크와 읽기 전용 수집 스냅샷에서 사용한다.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import os
from pathlib import Path


def reference_time(path: Path) -> datetime:
    value = datetime.fromisoformat(path.read_text(encoding="utf-8").strip())
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("시험 기준 시각에는 시간대가 필요합니다.")
    return value


def install_clock(database_url: str, path: Path) -> None:
    from sqlalchemy.engine import make_url

    url = make_url(database_url)
    if url.database != "regime_live_test" or not (url.host or "").startswith("qurious-regime-live-"):
        raise ValueError("국면 통합 시험 전용 Docker DB에서만 시각을 고정할 수 있습니다.")
    reference_time(path)  # 잘못된 시각은 서버 시작 전에 거부한다.

    class ReferenceClock(datetime):
        @classmethod
        def now(cls, tz=None):
            value = reference_time(path)
            return value.astimezone(tz) if tz is not None else value.astimezone().replace(tzinfo=None)

    from app.services import allocation_data, rebalance, rebalance_daily

    allocation_data.datetime = ReferenceClock
    rebalance.datetime = ReferenceClock
    rebalance_daily.datetime = ReferenceClock


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--clock-file", type=Path, required=True)
    args = parser.parse_args()
    install_clock(os.environ.get("DATABASE_URL", ""), args.clock_file)
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
