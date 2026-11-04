"""데이터셋 판 — 파일별 지문으로 「같은 판인가」를 확인하고, 커밋 머리(parent_commit)로 동시 쓰기를 막는 것을 보이는 예제.

실행    python dataset_versions.py        (표준 라이브러리만 · 네트워크 없음 · huggingface_hub 를 쓰지 않는다)
자료    모두 합성 — 임시 폴더에 작은 CSV 를 만들어 쓴다(실제 시세가 아니다)
흐름    ① 폴더를 파일별 (행 수 · sha256) 지문으로 만든다(= 매니페스트)
        ② 두 폴더의 지문을 견줘 어느 파일이 다른지 찾는다
        ③ 지문이 같아도 「원격 머리가 같은가」는 다른 질문이다
        ④ 두 PC 가 같은 머리를 읽고 parent 를 주어 쓰면 먼저 쓴 쪽만 성공한다(HF 의 parent_commit 과 같은 규칙의 흉내)
"""
from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path


def fingerprint(folder: Path) -> dict[str, dict]:
    """폴더 안 CSV 마다 행 수와 sha256 — 매니페스트의 한 줄과 같은 꼴."""
    out = {}
    for p in sorted(folder.rglob("*.csv")):
        data = p.read_bytes()
        out[p.relative_to(folder).as_posix()] = {"rows": data.count(b"\n") - 1,
                                                  "sha256": hashlib.sha256(data).hexdigest()}
    return out


def compare(mine: dict, theirs: dict) -> dict:
    a, b = set(mine), set(theirs)
    return {"only_mine": sorted(a - b), "only_theirs": sorted(b - a),
            "differ": sorted(k for k in a & b if mine[k]["sha256"] != theirs[k]["sha256"])}


class FakeRepo:
    """원격 저장소의 머리(main)만 흉내 낸다. 커밋은 parent 가 지금 머리와 같을 때만 받는다."""

    def __init__(self) -> None:
        self.head = "c1"
        self._n = 1

    def create_commit(self, parent: str) -> str:
        if parent != self.head:
            raise RuntimeError(f"거절 — 내가 본 머리 {parent} 인데 지금 머리는 {self.head}")
        self._n += 1
        self.head = f"c{self._n}"
        return self.head


def write(folder: Path, rel: str, rows: list[str]) -> None:
    p = folder / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(("date,close\n" + "\n".join(rows) + "\n").encode("utf-8"))


def main() -> None:
    with tempfile.TemporaryDirectory() as t:
        mine, theirs = Path(t, "mine"), Path(t, "theirs")
        for d in (mine, theirs):
            write(d, "year=2025.csv", ["2025-12-30,100"])
        write(mine, "year=2026/price.csv", ["2026-01-02,101"])
        write(theirs, "year=2026/price.csv", ["2026-01-02,101", "2026-01-05,102"])   # 한쪽에 행이 하나 더 있다

        fm, ft = fingerprint(mine), fingerprint(theirs)
        print("① 행 수  내 쪽:", {k: v["rows"] for k, v in fm.items()}, " 저쪽:", {k: v["rows"] for k, v in ft.items()})
        print("② 견주기:", compare(fm, ft))
        print("  같은 폴더끼리:", compare(fm, fingerprint(mine)))

    print("③ 파일 지문이 같아도 커밋 머리가 같다는 뜻은 아니다(카드 · 메타만 바뀐 커밋이 있을 수 있다)")

    repo = FakeRepo()
    head_a = head_b = repo.head                      # 두 PC 가 같은 머리를 읽는다
    print("④ PC-A 가 머리", head_a, "를 부모로 커밋 →", repo.create_commit(head_a))
    try:
        repo.create_commit(head_b)
    except RuntimeError as e:
        print("  PC-B 가 같은 머리", head_b, "를 부모로 커밋 →", e)
        print("  PC-B 는 올리지 않고 멈춘다 — 먼저 맞춘 뒤 다시")


if __name__ == "__main__":
    main()
