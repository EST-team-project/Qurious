"""법령 판 고르기 · 조문 쪼개기 · 조각 ID — 「문서 쪼개기와 법령 판 고르기」 장의 예제 (표준 라이브러리만).

실행    python legal_versions.py
자료    국가법령정보센터 Open API(law.go.kr)로 받은 판 목록 · 조문에서 설명에 필요한 줄만 옮겼다
        (판 목록 · 시행일 판 본문은 2026-10-02, 공포 때 본문은 2026-10-03 에 받았다).
        법령은 저작권 보호를 받지 않는다(저작권법 제7조) — 원문은 law.go.kr 에서 확인한다.

이 파일의 함수:
    by_promulgation(versions, as_of)            흔한 실수 — 시행일 ≤ 기준일 가운데 「공포일」 이 가장 늦은 판
    by_effective(versions, as_of)               맞는 규칙 — 시행일 ≤ 기준일 가운데 「시행일」 이 가장 늦은 판
    later_promulgated(versions, chosen, as_of)  고른 판보다 늦게 공포됐고 기준일까지 시행된 판(그 개정이 담겼는지 따로 대조)
    chunk(doc, part, label, title, body)        조 하나 → 조각(첫 줄 = 제목 사슬 · 본문 첫머리에 되풀이된 조 머리는 뺀다)
    chunk_id(doc, version, article, seq)        자리(문서 · 판 · 조 · 순번)로 만든 조각 ID — 실행마다 같다
"""
from __future__ import annotations

import hashlib
import re
from typing import NamedTuple, Optional


class Version(NamedTuple):
    no: str            # 공포번호
    promulgated: str   # 공포일
    effective: str     # 시행일

    def label(self) -> str:
        return f"제{self.no}호(공포 {self.promulgated} · 시행 {self.effective})"


# 판 목록 — 2026-10-02 에 받은 목록의 마지막 여섯 줄씩(시행일 차례).
STT_DECREE = [   # 증권거래세법 시행령
    Version("32430", "2022-02-15", "2022-07-01"),
    Version("32430", "2022-02-15", "2023-01-01"),   # 같은 공포에 시행일이 둘 — 판은 (공포번호, 시행일) 한 쌍이다
    Version("33209", "2022-12-31", "2023-01-01"),
    Version("35359", "2025-02-28", "2025-02-28"),
    Version("36001", "2025-12-31", "2026-01-01"),   # 세율을 바꾼 일부개정
    Version("35947", "2025-12-30", "2026-01-02"),   # 다른 법을 바꾸며 함께 고친 타법개정 — 하루 먼저 공포, 하루 늦게 시행
]
CAPMKT_DECREE = [   # 자본시장과 금융투자업에 관한 법률 시행령
    Version("36357", "2026-05-26", "2026-05-26"),
    Version("36484", "2026-06-30", "2026-06-30"),
    Version("36543", "2026-07-28", "2026-07-28"),
    Version("36543", "2026-07-28", "2026-08-04"),
    Version("36729", "2026-09-29", "2026-10-01"),   # 같은 날 공포된 두 판
    Version("36728", "2026-09-29", "2026-10-02"),
]


def _num(no: str) -> int:
    return int(re.sub(r"\D", "", no) or -1)


def by_promulgation(versions: list[Version], as_of: str) -> Optional[Version]:
    """흔한 실수 — 이미 시행된 판 가운데 가장 늦게 공포된 판(같은 날이면 공포번호가 큰 판)."""
    cands = [v for v in versions if v.effective <= as_of]
    return max(cands, key=lambda v: (v.promulgated, _num(v.no))) if cands else None


def by_effective(versions: list[Version], as_of: str) -> Optional[Version]:
    """맞는 규칙 — 이미 시행된 판 가운데 시행일이 가장 늦은 판(같으면 공포일 → 공포번호가 늦은 판)."""
    cands = [v for v in versions if v.effective <= as_of]
    return max(cands, key=lambda v: (v.effective, v.promulgated, _num(v.no))) if cands else None


def later_promulgated(versions: list[Version], chosen: Version, as_of: str) -> list[Version]:
    """고른 판보다 늦게 공포됐고 기준일까지 시행된 판 — 고른 판의 본문이 그 개정을 담았는지 조마다 대조할 대상."""
    key = (chosen.promulgated, _num(chosen.no))
    return [v for v in versions if v.effective <= as_of and (v.promulgated, _num(v.no)) > key and v.no != chosen.no]


# 증권거래세법 시행령 제5조 제1호 — 같은 판(제35947호)을 두 길로 불러 받은 글(2026-10-02)
ART5_BY_PROMULGATION = ("1. 유가증권시장(…)에서 양도되는 주권: 영(零). 다만, 2021년 1월 1일부터 2022년 12월 31일까지는 "
                        "1만분의 8로 하고, 2023년 1월 1일부터 2023년 12월 31일까지는 1만분의 5로 하며, …")
ART5_BY_EFFECTIVE = "1. 유가증권시장(…)에서 양도되는 주권: 1만분의 5"


def chunk_header(doc: str, part: str, label: str, title: str) -> str:
    """첫 줄 — 「문서 > 편 > 장 > 절 > 제○조(제목)」. 경로의 <개정 …> 꼬리표는 뺀다(그 머리를 고친 날이지 이름이 아니다)."""
    path = " > ".join(s.strip() for s in re.sub(r"\s*<[^<>]*>", "", part).split(">") if s.strip())
    return " > ".join(s for s in (doc, path, f"{label}({title})" if title else label) if s)


def strip_heading(text: str, label: str, title: str) -> str:
    """본문 첫머리가 같은 조 머리를 되풀이하면 뺀다(공백 차이는 접어서 견준다)."""
    head = re.sub(r"\s+", "", f"{label}({title})" if title else label)
    i = j = 0
    while i < len(text) and j < len(head):
        if text[i].isspace():
            i += 1
            continue
        if text[i] != head[j]:
            return text
        i, j = i + 1, j + 1
    return text[i:].lstrip() if j == len(head) else text


def chunk(doc: str, part: str, label: str, title: str, body: str) -> str:
    return chunk_header(doc, part, label, title) + "\n" + strip_heading(body, label, title)


def chunk_id(doc: str, version: str, article: str, seq: int) -> str:
    """sha256(문서 · 판 · 조 · 순번) 앞 32자 — 내용이 아니라 자리로 만든다. 같은 자리는 언제 다시 만들어도 같은 ID."""
    raw = "\x1f".join((doc, version, article, str(seq)))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def main() -> None:
    print("1) 판 고르기 — 증권거래세법 시행령 · 기준일 2026-10-02")
    wrong = by_promulgation(STT_DECREE, "2026-10-02")
    right = by_effective(STT_DECREE, "2026-10-02")
    print(f"   공포일 순: {wrong.label()}")
    print(f"   시행일 순: {right.label()}")
    print(f"   고른 판보다 늦게 공포된 판: {[v.label() for v in later_promulgated(STT_DECREE, right, '2026-10-02')]}")
    print("   같은 제35947호 제5조 제1호를 두 길로 부르면:")
    print(f"     공포 때 본문  → {ART5_BY_PROMULGATION}")
    print(f"     시행일 판 본문 → {ART5_BY_EFFECTIVE}")
    print("2) 판 고르기 — 자본시장법 시행령 · 같은 날(2026-09-29) 공포된 두 판")
    for day in ("2026-09-30", "2026-10-01", "2026-10-02"):
        w, r = by_promulgation(CAPMKT_DECREE, day), by_effective(CAPMKT_DECREE, day)
        mark = "같다" if w == r else "다르다 ←"
        print(f"   기준일 {day} · 공포일 순 제{w.no}호({w.effective} 시행) · 시행일 순 제{r.no}호({r.effective} 시행) · {mark}")
    print("3) 조문 쪼개기 — 첫 줄은 제목 사슬, 본문의 되풀이된 머리는 뺀다")
    c1 = chunk("상법", "제4편 보험 > 제1장 통칙", "제638조", "보험계약의 의의",
               "제638조(보험계약의 의의) 보험계약은 당사자 일방이 약정한 보험료를 지급하고 …")
    c2 = chunk("상법", "제3편 회사 > 제4장 주식회사 > 제7절 회사의 회계 <개정 2011.4.14>", "제464조의2", "이익배당의 지급시기",
               "① 회사는 제464조에 따른 이익배당을 …의 결의를 한 날부터 1개월 내에 하여야 한다. …")
    for c in (c1, c2):
        for line in c.splitlines():
            print(f"   | {line}")
    print("4) 조각 ID — 자리로 만들면 몇 번을 다시 만들어도 같다")
    a = chunk_id("commercial_act", "법률 제21044호 · 2026-09-10 시행", "제464조의2", 0)
    b = chunk_id("commercial_act", "법률 제21044호 · 2026-09-10 시행", "제464조의2", 0)
    c = chunk_id("commercial_act", "법률 제21044호 · 2026-09-10 시행", "제464조의2", 1)
    print(f"   첫째 {a}")
    print(f"   둘째 {b} · 같다 {a == b}")
    print(f"   순번 1 {c} · 같다 {a == c}")


if __name__ == "__main__":
    main()
