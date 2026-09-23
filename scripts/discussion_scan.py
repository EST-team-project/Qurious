"""논의(GitHub Discussions) 반응·결론 상태 스캐너.

왜 만들었나 —
2026-09-21(S42) 에 "팀원이 16세션 연속 무반응"이라던 기록이 **계측 오류**였다고 드러났다.
마지막 댓글 작성자만 보고 있었는데, Discussion 댓글은 스레드 구조라 **답글은 댓글 목록에
안 들어온다.** 내가 답글을 달면 그 스레드는 영영 "내가 마지막"이 되고, 성실히 답할수록
지표가 0 으로 수렴했다. 실제로는 그 사이 팀원 답이 11건 있었다.

사람이 매번 기억해서 조회를 바르게 하는 대신, **바른 조회를 코드로 박아 둔다.**
댓글과 답글을 전부 받아 사람별로 세고, 각 논의 본문의 결론표를 읽어 안건 상태를 집계한다.

    GH_TOKEN=$(gh auth token --user devlee328288) python scripts/discussion_scan.py
    python scripts/discussion_scan.py --save 저장.json     # 받은 원본도 저장
    python scripts/discussion_scan.py --from 저장.json     # 저장본으로 (네트워크 없음)
    python scripts/discussion_scan.py --md                 # 결정 대장에 붙일 마크다운
    python scripts/discussion_scan.py --json               # 기계용

⚠️ **GitHub API 는 실행 1회당 GraphQL 1회만 부른다.** 반복 호출·폴링은 계정 정지 위험 때문에
금지다(CLAUDE.md 2.1). 이 스크립트를 반복문·예약 작업에 넣지 않는다.

결론표 형식 — 각 논의 본문의 결론 절에 아래 표지로 감싼 표를 둔다. 표지는 HTML 주석이라
GitHub 화면에는 보이지 않는다.

    <!-- 결론표:시작 -->
    | 안건 | 결론(초안) | 이동원 | 강민석 | 신장환 | 오준영 | 확정 규칙 | 상태 |
    |---|---|:-:|:-:|:-:|:-:|---|---|
    | ① … | … | 제안 | ✅ B (09-15) | — | — | 전원 명시 찬성 | ⏳ 전원 찬성 대기 3/4 |
    <!-- 결론표:끝 -->

상태 칸은 기호로 시작한다 — ✅ 확정 · 🟢 확정 예정 · ⏳ 대기 · 🟡 조건부 · ⏸️ 연기 · 🔴 이견.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))

저장소_주인 = "devlee328288"
저장소_이름 = "Qurious"

# 팀원 로그인 → 이름. 순서가 곧 출력 열 순서다.
팀원: dict[str, str] = {
    "devlee328288": "이동원",
    "rkdalstjr": "강민석",
    "janghwan-god": "신장환",
    "GoonGuMa": "오준영",
}
제안자 = "devlee328288"   # 모든 논의를 연 사람. "팀원 반응"을 셀 때는 뺀다.

# 논의 공통 기한 (D0~D7 · D8 모두 같은 날로 맞춰 두었다)
기본_기한 = "2026-09-27T23:59:00+09:00"

결론표_시작 = "<!-- 결론표:시작 -->"
결론표_끝 = "<!-- 결론표:끝 -->"

# 상태 칸 첫 기호 → 분류. ⏸️ 는 두 글자(⏸ + 변형 선택자)라 앞 글자만 본다.
상태_기호: dict[str, str] = {
    "✅": "확정",
    "🟢": "확정 예정",
    "⏳": "대기",
    "🟡": "조건부",
    "⏸": "연기",
    "🔴": "이견",
}

# 한 번에 받는 개수. 넘치면 잘렸다고 경고한다(조용히 덜 세는 것이 가장 나쁘다).
# GitHub GraphQL 은 한 질의의 노드 상한이 50만이다 — 논의 × 댓글 × 답글 = 40 × 100 × 100 = 40만.
# 논의가 40건을 넘으면 첫 값을 늘리지 말고 논의를 나눠 받는 쪽으로 바꾼다(곱이 상한을 넘는다).
질의 = """
query($owner: String!, $name: String!) {
  viewer { login }
  repository(owner: $owner, name: $name) {
    discussions(first: 40, orderBy: {field: CREATED_AT, direction: ASC}) {
      totalCount
      nodes {
        number title url body updatedAt
        category { name }
        comments(first: 100) {
          totalCount
          nodes {
            author { login } createdAt
            replies(first: 100) { totalCount nodes { author { login } createdAt } }
          }
        }
      }
    }
  }
}
"""


@dataclass
class 논의행:
    """논의 하나의 반응·결론 요약."""

    번호: int
    코드: str                 # "D0" 같은 논의 번호 (제목에서 뽑는다, 없으면 빈칸)
    제목: str
    댓글: int
    답글: int
    사람별: dict[str, int]     # 로그인 → 댓글+답글 수
    팀원_마지막: str           # 제안자 외 마지막 발언 시각(KST), 없으면 빈칸
    결론표: list[dict] = field(default_factory=list)
    상태_집계: dict[str, int] = field(default_factory=dict)
    잘림: list[str] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────
# 받기
# ─────────────────────────────────────────────────────────────────────
def 받기() -> dict:
    """GraphQL 을 **한 번** 부른다. 토큰은 환경변수 GH_TOKEN(또는 gh 활성 계정)을 쓴다."""
    요청 = json.dumps({
        "query": 질의,
        "variables": {"owner": 저장소_주인, "name": 저장소_이름},
    })
    결과 = subprocess.run(
        ["gh", "api", "graphql", "--input", "-"],
        input=요청, capture_output=True, text=True, encoding="utf-8",
    )
    if 결과.returncode != 0:
        raise SystemExit(
            "gh api graphql 실패 — 계정·토큰을 확인한다:\n"
            "  GH_TOKEN=$(gh auth token --user devlee328288) python scripts/discussion_scan.py\n"
            f"{결과.stderr.strip()}"
        )
    return json.loads(결과.stdout)


# ─────────────────────────────────────────────────────────────────────
# 세기
# ─────────────────────────────────────────────────────────────────────
def _kst(시각: str) -> datetime:
    return datetime.fromisoformat(시각.replace("Z", "+00:00")).astimezone(KST)


def _로그인(노드: dict) -> str:
    # 탈퇴한 계정은 author 가 null 로 온다. 세지 않고 버리면 "0건"이 거짓이 되므로 이름을 붙여 센다.
    작성자 = 노드.get("author")
    return 작성자["login"] if 작성자 else "(탈퇴한 계정)"


def 결론표_읽기(본문: str) -> list[dict]:
    """본문에서 결론표 표지 사이의 표를 읽어 행 목록으로 돌려준다.

    표지가 없으면 빈 목록이다. 칸 안의 ``\\|`` 는 구분자가 아니라 글자로 다룬다.
    """
    본문 = 본문.replace("\r\n", "\n")
    if 결론표_시작 not in 본문 or 결론표_끝 not in 본문:
        return []
    구간 = 본문.split(결론표_시작, 1)[1].split(결론표_끝, 1)[0]
    줄들 = [줄.strip() for 줄 in 구간.split("\n") if 줄.strip().startswith("|")]
    if len(줄들) < 2:
        return []

    def 칸나누기(줄: str) -> list[str]:
        임시 = 줄.replace("\\|", "\x00")
        return [칸.strip().replace("\x00", "|") for 칸 in 임시.strip("|").split("|")]

    머리 = 칸나누기(줄들[0])
    행들 = []
    for 줄 in 줄들[2:]:           # 0: 머리, 1: 정렬 줄(|---|)
        칸 = 칸나누기(줄)
        if len(칸) != len(머리):
            # 열 수가 어긋난 행은 조용히 넘기지 않는다 — 표가 깨졌다는 신호다.
            행들.append({"_깨진행": 줄})
            continue
        행들.append(dict(zip(머리, 칸)))
    return 행들


def 상태_분류(상태칸: str) -> str:
    칸 = 상태칸.strip()
    for 기호, 이름 in 상태_기호.items():
        if 칸.startswith(기호):
            return 이름
    return "미분류"


def 세기(원본: dict) -> tuple[list[논의행], dict]:
    """GraphQL 응답 → 논의별 행 + 전체 메타(조회 계정·잘림 여부)."""
    저장소 = 원본["data"]["repository"]
    논의들 = 저장소["discussions"]
    메타 = {
        "조회_계정": (원본["data"].get("viewer") or {}).get("login", ""),
        "논의_총수": 논의들["totalCount"],
        "받은_논의": len(논의들["nodes"]),
    }

    행들: list[논의행] = []
    for 논의 in 논의들["nodes"]:
        사람별: dict[str, int] = {로그인: 0 for 로그인 in 팀원}
        팀원_시각: list[datetime] = []
        잘림: list[str] = []
        댓글수 = 답글수 = 0

        댓글묶음 = 논의["comments"]
        if 댓글묶음["totalCount"] > len(댓글묶음["nodes"]):
            잘림.append(f"댓글 {len(댓글묶음['nodes'])}/{댓글묶음['totalCount']}")

        for 댓글 in 댓글묶음["nodes"]:
            댓글수 += 1
            작성자 = _로그인(댓글)
            사람별[작성자] = 사람별.get(작성자, 0) + 1
            if 작성자 != 제안자:
                팀원_시각.append(_kst(댓글["createdAt"]))

            # ★ 답글을 반드시 센다 — 이것을 빠뜨린 것이 16세션 "0건" 오류의 원인이었다.
            답글묶음 = 댓글["replies"]
            if 답글묶음["totalCount"] > len(답글묶음["nodes"]):
                잘림.append(f"답글 {len(답글묶음['nodes'])}/{답글묶음['totalCount']}")
            for 답글 in 답글묶음["nodes"]:
                답글수 += 1
                작성자 = _로그인(답글)
                사람별[작성자] = 사람별.get(작성자, 0) + 1
                if 작성자 != 제안자:
                    팀원_시각.append(_kst(답글["createdAt"]))

        결론표 = 결론표_읽기(논의.get("body") or "")
        집계: dict[str, int] = {}
        for 행 in 결론표:
            분류 = "깨진행" if "_깨진행" in 행 else 상태_분류(행.get("상태", ""))
            집계[분류] = 집계.get(분류, 0) + 1

        코드 = re.search(r"\bD(\d+)\b", 논의["title"])
        행들.append(논의행(
            번호=논의["number"],
            코드=f"D{코드.group(1)}" if 코드 else "",
            제목=논의["title"],
            댓글=댓글수,
            답글=답글수,
            사람별=사람별,
            팀원_마지막=max(팀원_시각).strftime("%m-%d %H:%M") if 팀원_시각 else "",
            결론표=결론표,
            상태_집계=집계,
            잘림=잘림,
        ))

    if 메타["논의_총수"] > 메타["받은_논의"]:
        메타["논의_잘림"] = f"{메타['받은_논의']}/{메타['논의_총수']}"
    return 행들, 메타


def 경고(행들: list[논의행], 메타: dict) -> list[str]:
    """극단값을 찾는다. "전부 0"·"전무"는 대상이 아니라 **조회를 먼저 의심하라**는 신호다."""
    알림: list[str] = []
    팀원_합 = sum(v for 행 in 행들 for k, v in 행.사람별.items() if k != 제안자)
    if 행들 and 팀원_합 == 0:
        알림.append("팀원 발언이 **전 논의에서 0건**이다 — 대상보다 조회(답글 누락·권한·계정)를 먼저 의심한다")
    if 행들 and sum(행.댓글 for 행 in 행들) > 0 and sum(행.답글 for 행 in 행들) == 0:
        알림.append("댓글은 있는데 답글이 **하나도** 없다 — 답글을 받지 못한 조회일 가능성이 크다")
    if 메타.get("논의_잘림"):
        알림.append(f"논의 목록이 잘렸다 ({메타['논의_잘림']}) — first 값을 늘린다")
    for 행 in 행들:
        if 행.잘림:
            알림.append(f"#{행.번호} 가 잘렸다 ({', '.join(행.잘림)}) — 덜 센 값이다")
        if 행.상태_집계.get("깨진행"):
            알림.append(f"#{행.번호} 결론표에 열 수가 어긋난 행이 {행.상태_집계['깨진행']}개 있다")
        if 행.상태_집계.get("미분류"):
            알림.append(f"#{행.번호} 결론표 상태 칸이 규정 기호로 시작하지 않는 행이 {행.상태_집계['미분류']}개 있다")
    if 메타.get("조회_계정") and 메타["조회_계정"] != 제안자:
        알림.append(f"조회 계정이 {메타['조회_계정']} 이다 — 팀 저장소는 {제안자} 로 조회한다")
    return 알림


def 남은_시간(기한: datetime, 지금: datetime) -> str:
    차 = 기한 - 지금
    if 차.total_seconds() <= 0:
        return "기한 지남"
    return f"{차.days}일 {차.seconds // 3600}시간"


# ─────────────────────────────────────────────────────────────────────
# 출력
# ─────────────────────────────────────────────────────────────────────
_상태_순서 = ["확정", "확정 예정", "대기", "조건부", "연기", "이견", "미분류", "깨진행"]


def _표칸(값: str) -> str:
    """읽을 때 글자로 풀어 둔 파이프를 표로 다시 낼 때 이스케이프한다."""
    return 값.replace("|", "\\|")


def _집계_문자(집계: dict[str, int]) -> str:
    if not 집계:
        return "결론표 없음"
    return " · ".join(f"{k} {집계[k]}" for k in _상태_순서 if 집계.get(k))


def 사람용_출력(행들: list[논의행], 메타: dict, 기한: datetime, 지금: datetime) -> None:
    print(f"― 논의 반응 전수 (댓글 + 답글) · 조회 {지금:%Y-%m-%d %H:%M} KST · 계정 {메타.get('조회_계정') or '?'} ―")
    print(f"  기한 {기한:%Y-%m-%d %H:%M} KST 까지 {남은_시간(기한, 지금)}")
    이름들 = list(팀원.values())
    print(f"  {'#':>3}  {'논의':<6} {'댓글':>4} {'답글':>4} │ " + " ".join(f"{n:>4}" for n in 이름들) + " │ 팀원 마지막")
    for 행 in 행들:
        수 = " ".join(f"{행.사람별.get(k, 0):>5}" for k in 팀원)
        print(f"  {행.번호:>3}  {행.코드 or '-':<6} {행.댓글:>5} {행.답글:>5} │ {수} │ {행.팀원_마지막 or '—'}")
    print()
    print("― 결론표 (본문의 결론 절) ―")
    for 행 in 행들:
        print(f"  #{행.번호:<3} {행.코드 or '-':<4} 안건 {len(행.결론표):>2} · {_집계_문자(행.상태_집계)}")
    알림 = 경고(행들, 메타)
    print()
    print("― 주의 ―")
    for 줄 in 알림 or ["없음"]:
        print(f"  ⚠️ {줄}" if 알림 else f"  {줄}")


def 마크다운_출력(행들: list[논의행], 메타: dict, 기한: datetime, 지금: datetime) -> None:
    이름들 = list(팀원.values())
    print(f"> 조회 {지금:%Y-%m-%d %H:%M} KST · `scripts/discussion_scan.py` · "
          f"기한 {기한:%m-%d %H:%M} 까지 {남은_시간(기한, 지금)}")
    print()
    print("| # | 논의 | 댓글 | 답글 | " + " | ".join(이름들) + " | 팀원 마지막 발언 |")
    print("|---:|---|---:|---:|" + "---:|" * len(이름들) + "---|")
    for 행 in 행들:
        수 = " | ".join(str(행.사람별.get(k, 0)) for k in 팀원)
        print(f"| [#{행.번호}](https://github.com/{저장소_주인}/{저장소_이름}/discussions/{행.번호}) "
              f"| {행.코드 or '—'} | {행.댓글} | {행.답글} | {수} | {행.팀원_마지막 or '—'} |")
    # 결론표가 있는 논의만 — 아직 한 곳도 없으면 빈 표 머리를 찍지 않는다.
    if any(행.결론표 for 행 in 행들):
        print()
        print("| # | 논의 | 안건 | " + " | ".join(_상태_순서[:6]) + " |")
        print("|---:|---|---:|" + "---:|" * 6)
        for 행 in 행들:
            if not 행.결론표:
                continue
            수 = " | ".join(str(행.상태_집계.get(k, 0)) for k in _상태_순서[:6])
            print(f"| #{행.번호} | {행.코드 or '—'} | {len(행.결론표)} | {수} |")

        # 안건별 모음 — 각 논의 결론표를 한 표로 잇는다. 결정 대장은 이 표를 그대로 싣는다.
        print()
        print("| 논의 | 안건 | 결론(초안) | 상태 |")
        print("|---|---|---|---|")
        for 행 in 행들:
            for 줄 in 행.결론표:
                if "_깨진행" in 줄:
                    continue
                print(f"| #{행.번호} {행.코드} | {_표칸(줄.get('안건', ''))} | "
                      f"{_표칸(줄.get('결론(초안)', ''))} | {_표칸(줄.get('상태', ''))} |")
    알림 = 경고(행들, 메타)
    if 알림:
        print()
        for 줄 in 알림:
            print(f"> ⚠️ {줄}")


def main() -> int:
    ap = argparse.ArgumentParser(description="논의 반응·결론 상태 스캐너 (GraphQL 1회)")
    ap.add_argument("--from", dest="원본", help="저장해 둔 GraphQL 응답 JSON 을 읽는다 (네트워크 없음)")
    ap.add_argument("--save", help="받은 GraphQL 응답을 이 경로에 저장한다")
    ap.add_argument("--md", action="store_true", help="마크다운 표로 출력")
    ap.add_argument("--json", action="store_true", help="JSON 으로 출력")
    ap.add_argument("--deadline", default=기본_기한, help=f"논의 기한 (ISO 8601, 기본 {기본_기한})")
    인자 = ap.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    원본 = json.loads(Path(인자.원본).read_text(encoding="utf-8")) if 인자.원본 else 받기()
    if 인자.save:
        Path(인자.save).write_text(json.dumps(원본, ensure_ascii=False, indent=1), encoding="utf-8")

    행들, 메타 = 세기(원본)
    기한 = datetime.fromisoformat(인자.deadline).astimezone(KST)
    지금 = datetime.now(KST)

    if 인자.json:
        print(json.dumps({
            "메타": 메타,
            "경고": 경고(행들, 메타),
            "논의": [asdict(행) for 행 in 행들],
        }, ensure_ascii=False, indent=1))
    elif 인자.md:
        마크다운_출력(행들, 메타, 기한, 지금)
    else:
        사람용_출력(행들, 메타, 기한, 지금)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
