"""요구사항 추적표(RTM) 실측 스캐너.

RTM 은 「이 요구는 구현됐는가」에 **증거로** 답하는 문서다. 그런데 증거를 사람이
손으로 적어 두면, 코드가 바뀌어도 표는 그대로 남아 거짓이 된다. 한 달 뒤 그 표를
믿을 수 있으려면 **다시 돌려서 확인할 수 있어야** 한다.

그래서 요구마다 「이 요구가 구현됐다면 저장소에 무엇이 보여야 하는가」를 탐지
규칙으로 적어 두고, 이 스크립트가 실제로 훑어 센다. RTM 문서의 「코드」·「상태」
칸은 이 출력에서 온다.

    python scripts/rtm_scan.py            # 사람이 읽는 표
    python scripts/rtm_scan.py --md       # RTM 문서에 붙일 마크다운
    python scripts/rtm_scan.py --json     # 기계용

⚠️ **이 스캐너가 판정하는 것은 「흔적이 있는가」이지 「제대로 동작하는가」가 아니다.**
grep 이 잡는 것은 이름뿐이다. 실제 동작은 시험(TC)이 판정하고, RTM 은 그 둘을
나란히 놓는다 — 흔적은 있는데 시험이 없는 칸이 곧 위험한 칸이다.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 훑지 않을 곳. 가상환경·캐시·데이터·강의자료는 우리 구현이 아니다.
제외_디렉터리 = {
    ".git", "__pycache__", "node_modules", ".pytest_cache", ".serena",
    "data", "screenshots", ".playwright-mcp", ".venv", "venv",
}

# 훑을 확장자. 문서는 따로 센다(구현 증거가 아니므로).
코드_확장자 = {".py", ".html", ".js", ".yml", ".yaml", ".sql", ".toml", ".ini", ".cfg"}


@dataclass
class 요구:
    """요구 한 줄과, 그것이 구현됐다면 저장소에 보여야 할 흔적."""

    id: str
    이름: str
    출처: str          # 어느 문서 어느 절에서 왔는가
    파트: str          # #62 가 배정한 담당 파트
    패턴: list[str]     # 이 요구의 구현 흔적 (정규식)
    시험: list[str] = field(default_factory=list)   # 대응하는 TC ID
    비고: str = ""


# ─────────────────────────────────────────────────────────────────────
# B계열 — 강사님 목표기능표 29개 (#62 §3.1·§3.2 에 전재된 열거 기준)
#   머리글 합계는 27 이나 열거하면 29 다. RTM 은 **열거 기준 29** 를 정본으로 삼는다.
#   근거는 RTM 문서 §2 참조.
# ─────────────────────────────────────────────────────────────────────
B계열: list[요구] = [
    # ── PROJECT 01 — 로보 어드바이저 (14개)
    요구("P01-1-1", "용어사전·연관개념 탐색", "목표기능표 P01-①-1", "P-A",
        [r"glossary", r"용어\s*사전", r"연관\s*개념", r"related_term"]),
    요구("P01-1-2", "가격·거래량·재무·뉴스 수집·분류·전처리·검색(적재)", "목표기능표 P01-①-2", "P-A",
        [r"collector\.", r"from collector", r"def collect", r"news"]),
    요구("P01-1-3", "근거문서·출처 포함 RAG 질의응답", "목표기능표 P01-①-3", "P-A",
        [r"citations", r"qdrant", r"retriev"]),
    요구("P01-1-4", "갱신일·문서버전·캘린더·정기배치", "목표기능표 P01-①-4", "P-A",
        [r"beat_schedule", r"ingest_day", r"doc_version", r"문서\s*버전"]),
    요구("P01-1-5", "XAI 로 추천 이유를 쉬운 말로 설명", "목표기능표 P01-①-5", "P-D",
        [r"\bxai\b", r"explain(ab|ation)", r"추천\s*이유"]),
    요구("P01-2-1", "MA·RSI·MACD·볼린저·거래량 지표", "목표기능표 P01-②-1", "P-B",
        [r"\brsi\b", r"\bmacd\b", r"bollinger", r"moving_average"],
        비고="⚠️ ta_utils 6종은 강사님 원본과 바이트 동일 — 우리 공적으로 계상 금지(#62)"),
    요구("P01-2-2", "캔들패턴·지지·저항·돌파·골든크로스 탐지", "목표기능표 P01-②-2", "P-B",
        [r"candle_?pattern", r"support_?level", r"resistance", r"breakout", r"golden_?cross"]),
    요구("P01-2-3", "분·일·주봉 종합 → 신호 + 신뢰도", "목표기능표 P01-②-3", "P-B",
        [r"multi_?tf", r"timeframe", r"resample", r"confidence"]),
    요구("P01-3-1", "시간 기반 리밸런싱 (월·분기·연)", "목표기능표 P01-③-1", "P-C",
        [r"rebalanc"]),
    요구("P01-3-2", "이탈률 기반 리밸런싱", "목표기능표 P01-③-2", "P-C",
        [r"drift_?toleran", r"target_?weight", r"이탈률"]),
    요구("P01-3-3", "입출금·배당금 기반 리밸런싱", "목표기능표 P01-③-3", "P-C",
        [r"cash_?flow", r"deposit", r"withdraw", r"재투자"]),
    요구("P01-4-1", "거래비용·슬리피지 반영 수익률·MDD·샤프", "목표기능표 P01-④-1", "P-D",
        [r"slippage", r"\bmdd\b", r"sharpe", r"max_?drawdown"],
        비고="⚠️ 샤프 정의가 4개 공존(#62 P-D) — 흔적은 있으나 정합성 미확인"),
    요구("P01-4-2", "신호 → 매수·매도·보유 의견 변환", "목표기능표 P01-④-2", "P-C",
        [r"opinion", r"투자\s*의견", r"recommendation", r"signal_to_", r"decide_action"],
        비고="매수·매도·보유 문자열은 화면 버튼에도 널려 있어 변환 로직 쪽으로 좁혔다"),
    요구("P01-4-3", "모의 주문 체결·포트폴리오 운용", "목표기능표 P01-④-3", "P-E",
        [r"paper_?trading", r"place_order"],
        시험=["TC-LT-01~10"],
        비고="⚠️ 체결가 소스가 야후(#62) — TC-YH 봉인 대상"),

    # ── PROJECT 02 — 인디케이터·자동화 (15개)
    요구("P02-1-1", "기본 인디케이터 지표계산", "목표기능표 P02-①-1", "P-B",
        [r"ta_utils", r"\brsi\b", r"\bmacd\b"]),
    요구("P02-1-2", "조건조합·손절·익절·포지션크기", "목표기능표 P02-①-2", "P-B",
        [r"stop_?loss", r"take_?profit", r"position_?siz", r"손절", r"익절"]),
    요구("P02-1-3", "백테스트로 기준전략 선정", "목표기능표 P02-①-3", "P-D",
        [r"lean_?backtest", r"backtest"]),
    요구("P02-2-1", "커스텀 인디케이터 정규화 산식", "목표기능표 P02-②-1", "P-B",
        [r"custom_?indicator", r"normaliz", r"정규화\s*산식"]),
    요구("P02-2-2", "미래데이터 참조 방지·실시간갱신·단위테스트 ★", "목표기능표 P02-②-2", "P-B",
        [r"look_?ahead", r"lookahead", r"미래\s*데이터"],
        비고="★ 3차 채점 항목. 단위시험 존재 여부는 별도 칸에서 센다"),
    요구("P02-2-3", "인디케이터 API 제공·버전 저장", "목표기능표 P02-②-3", "P-B",
        [r"indicator_?version", r"/indicators?", r"indicator_?api"]),
    요구("P02-3-1", "Pine 지표·전략 구현", "목표기능표 P02-③-1", "P-B",
        [r"pine", r"//@version"],
        비고="⚠️ 생성기가 indicator() 라 Strategy Tester 안 켜짐(#61)"),
    요구("P02-3-2", "Strategy Tester → LEAN 교차검증", "목표기능표 P02-③-2", "P-D",
        [r"\blean\b", r"교차\s*검증", r"cross_?valid"]),
    요구("P02-3-3", "알림·Webhook", "목표기능표 P02-③-3", "P-B",
        [r"webhook", r"notification", r"알림"],
        비고="수신부는 약관 가름 보류(#62 §3.4)"),
    요구("P02-4-1", "동일 데이터·기간·수수료 조건 ★", "목표기능표 P02-④-1", "P-A+P-D",
        [r"commission", r"fee_?rate", r"요율"],
        시험=["TC-YH-01~02"],
        비고="★ lean_backtest.py 야후 직호출 제거 대상(#61 P1-1)"),
    요구("P02-4-2", "누적수익률·MDD·샤프·승률", "목표기능표 P02-④-2", "P-D",
        [r"win_?rate", r"cumulative_?return", r"profit_?factor", r"승률"]),
    요구("P02-4-3", "TradingView vs LEAN 비교", "목표기능표 P02-④-3", "P-D",
        [r"tradingview.*lean", r"lean.*tradingview", r"대조표"]),
    요구("P02-5-1", "신호 → 계좌·시세·주문", "목표기능표 P02-⑤-1", "P-E",
        [r"brokers?\.", r"get_broker_client", r"place_order"],
        시험=["TC-LT-01~10"]),
    요구("P02-5-2", "중복주문 방지·손실한도·비상정지 ★", "목표기능표 P02-⑤-2", "P-E",
        [r"idempot", r"dedup", r"loss_?limit", r"kill_?switch", r"비상\s*정지"],
        비고="★ 사고 방지 항목"),
    요구("P02-5-3", "실행일정·배포·로그·장애알림", "목표기능표 P02-⑤-3", "P-E",
        [r"beat_schedule", r"docker-compose", r"장애\s*알림", r"alert_", r"healthcheck"],
        비고="`logging.` 은 어느 파일에나 있어 뺐다 — 일정·배포·장애알림만 센다"),
]


# ─────────────────────────────────────────────────────────────────────
# A계열 — 저장소 안 제안요청서 `docs/rfp-2.md` 의 체크박스
#   B계열과 달리 **원문이 저장소에 있어 개수를 기계로 셀 수 있다.**
#   여기서는 개수만 세고, 항목별 매핑은 RTM 문서 §4 대응표에서 다룬다.
# ─────────────────────────────────────────────────────────────────────
def a계열_세기() -> dict:
    """rfp-2.md 의 체크박스를 절별로 센다. 요구 개수 논쟁의 한쪽 축."""
    본문 = (ROOT / "docs" / "rfp-2.md").read_text(encoding="utf-8").splitlines()
    현재절, 순서, 개수 = None, [], {}
    for 줄 in 본문:
        m = re.match(r"^(#{2,4})\s+(.*)", 줄)
        if m:
            현재절 = m.group(2).strip()
            if 현재절 not in 개수:
                개수[현재절] = 0
                순서.append(현재절)
        if 줄.startswith("- [ ]") and 현재절:
            개수[현재절] += 1
    return {"절별": [(k, 개수[k]) for k in 순서 if 개수[k]], "합계": sum(개수.values())}


# ─────────────────────────────────────────────────────────────────────
# 스캔
# ─────────────────────────────────────────────────────────────────────
def 훑을_파일들() -> list[Path]:
    결과 = []
    for p in ROOT.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in 코드_확장자:
            continue
        if any(부분 in 제외_디렉터리 for 부분 in p.parts):
            continue
        # 강의자료는 우리 구현이 아니다
        if p.parent == ROOT / "docs":
            continue
        # ⚠️ 스캐너 자신을 빼지 않으면 탐지 패턴 문자열이 그대로 흔적으로 잡힌다.
        #    「리밸런싱 코드 0건」이 「1건」으로 보이는 거짓 양성이 실제로 났다.
        if p.resolve() == Path(__file__).resolve():
            continue
        결과.append(p)
    return 결과


def 요구_스캔(요구목록: list[요구], 파일들: list[Path]) -> list[dict]:
    캐시: dict[Path, str] = {}
    출력 = []
    for r in 요구목록:
        정규식 = [re.compile(p, re.IGNORECASE) for p in r.패턴]
        적중: dict[str, int] = {}
        for f in 파일들:
            if f not in 캐시:
                try:
                    캐시[f] = f.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    캐시[f] = ""
            본문 = 캐시[f]
            코드수 = 주석수 = 0
            for 줄 in 본문.splitlines():
                if not any(x.search(줄) for x in 정규식):
                    continue
                # ⚠️ 주석 속 단어를 구현으로 세면 안 된다. 실제로 「중복주문 방지」의
                #    흔적 2건이 전부 주석 속 "idempotent" 였다 — 구현은 0건이다.
                if 주석_줄인가(줄, f.suffix):
                    주석수 += 1
                else:
                    코드수 += 1
            if 코드수 or 주석수:
                적중[f.relative_to(ROOT).as_posix()] = (코드수, 주석수)
        상위 = sorted(적중.items(), key=lambda kv: -(kv[1][0] * 100 + kv[1][1]))[:4]
        출력.append({
            "id": r.id, "이름": r.이름, "출처": r.출처, "파트": r.파트,
            "패턴": r.패턴, "시험": r.시험, "비고": r.비고,
            "파일수": sum(1 for v in 적중.values() if v[0]),   # 코드가 있는 파일만
            "코드줄": sum(v[0] for v in 적중.values()),
            "주석줄": sum(v[1] for v in 적중.values()),
            "상위": [(경로, v[0], v[1]) for 경로, v in 상위],
        })
    return 출력


def 주석_줄인가(줄: str, 확장자: str) -> bool:
    """주석·문서화 문자열로 보이는 줄인가.

    완벽한 판별은 파서가 필요하지만, RTM 의 목적에는 줄 앞머리만 봐도 충분하다.
    docstring 안쪽까지 잡으려고 상태를 들고 다니면 스캐너가 언어 파서가 된다 —
    여기서는 **거짓 양성을 줄이는 것**이 목적이지 완전성이 아니다.
    """
    s = 줄.strip()
    if 확장자 == ".py":
        return s.startswith("#") or s.startswith('"""') or s.startswith("'''")
    if 확장자 in {".js", ".html"}:
        return s.startswith("//") or s.startswith("/*") or s.startswith("*") or s.startswith("<!--")
    if 확장자 in {".yml", ".yaml", ".ini", ".cfg", ".toml"}:
        return s.startswith("#")
    if 확장자 == ".sql":
        return s.startswith("--")
    return False


def 판정(행: dict) -> str:
    """흔적의 양으로 상태를 어림한다. **동작 여부가 아니다.**

    주석은 구현으로 세지 않는다 — 「중복주문 방지」의 흔적 2건이 전부 주석 속
    "idempotent" 였던 일이 실제로 있었다. 말이 있다고 장치가 있는 것은 아니다.
    """
    if 행["코드줄"] == 0:
        return "🔴 없음(주석뿐)" if 행["주석줄"] else "🔴 흔적 없음"
    if 행["시험"]:
        return "🟢 코드+시험"
    if 행["파일수"] >= 3:
        return "🟡 코드 있음(시험 없음)"
    return "🟠 코드 희소(시험 없음)"


def 시험_현황() -> dict:
    """시험이 몇 건이고 무엇을 덮는지. RTM 의 「시험」 축."""
    테스트 = sorted((ROOT / "tests").glob("test_*.py")) if (ROOT / "tests").is_dir() else []
    건수 = 0
    try:
        결과 = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:warnings"],
            cwd=ROOT, capture_output=True, text=True, timeout=180,
        )
        for 줄 in 결과.stdout.splitlines():
            # pytest.ini 설정에 따라 요약 형식이 둘로 갈린다.
            #   "23 tests collected"           (기본)
            #   "tests/test_x.py: 21"          (이 저장소의 형식)
            m = re.search(r"(\d+) tests? collected", 줄)
            if m:
                건수 = int(m.group(1))
                break
            m = re.match(r"^\S+\.py:\s*(\d+)\s*$", 줄.strip())
            if m:
                건수 += int(m.group(1))
    except (subprocess.SubprocessError, OSError):
        pass
    if not 건수:  # 수집 요약을 못 읽으면 파일별 def 수로 대신한다
        # ⚠️ parametrize 가 있으면 실제 수집 건수보다 적게 나온다 (12 vs 23)
        건수 = sum(
            len(re.findall(r"^def test_", f.read_text(encoding="utf-8"), re.M))
            for f in 테스트
        )
    return {"파일": [f.name for f in 테스트], "건수": 건수}


def 사람용_출력(행들: list[dict], a: dict, 시험: dict) -> None:
    print("― 요구사항 추적 실측 ―\n")
    print(f"  A계열 (docs/rfp-2.md 체크박스)  {a['합계']:>2}개")
    for 이름, 수 in a["절별"]:
        print(f"      {수:>2}  {이름}")
    print()
    print(f"  B계열 (강사님 목표기능표 · 열거 기준)  {len(행들)}개")
    print(f"  시험  {시험['건수']}건 · {', '.join(시험['파일']) or '없음'}")
    print()
    print(f"  {'요구':<10} {'파트':<7} {'상태':<20} {'파일':>4} {'코드':>5} {'주석':>5}  상위 흔적")
    print("  " + "─" * 104)
    for 행 in 행들:
        상위 = " · ".join(f"{p}({c})" for p, c, _ in 행["상위"][:2] if c) or "—"
        print(f"  {행['id']:<10} {행['파트']:<7} {판정(행):<20} "
              f"{행['파일수']:>4} {행['코드줄']:>5} {행['주석줄']:>5}  {상위[:52]}")
    print()
    집계: dict[str, int] = {}
    for 행 in 행들:
        집계[판정(행)] = 집계.get(판정(행), 0) + 1
    print("  판정 분포")
    for k in ("🟢 코드+시험", "🟡 코드 있음(시험 없음)", "🟠 코드 희소(시험 없음)",
              "🔴 없음(주석뿐)", "🔴 흔적 없음"):
        if k in 집계:
            print(f"      {집계[k]:>2}개  {k}")
    print()
    print("  ⚠️ 이 판정은 「흔적이 있는가」이지 「제대로 동작하는가」가 아니다.")


def 마크다운_출력(행들: list[dict], a: dict, 시험: dict) -> None:
    print(f"> 실측: `python scripts/rtm_scan.py` · 시험 {시험['건수']}건 · "
          f"A계열 체크박스 {a['합계']}개 · B계열 요구 {len(행들)}개\n")
    print("| 요구 ID | 요구 내용 | 파트 | 상태 | 파일 | 코드줄 | 주석줄 | 대표 위치 | 시험 |")
    print("|---------|-----------|:----:|------|-----:|-------:|-------:|-----------|------|")
    for 행 in 행들:
        코드있는곳 = [x for x in 행["상위"] if x[1]]
        대표 = f"`{코드있는곳[0][0]}`" if 코드있는곳 else "—"
        시험칸 = ", ".join(행["시험"]) or "—"
        print(f"| `{행['id']}` | {행['이름']} | {행['파트']} | {판정(행)} | "
              f"{행['파일수']} | {행['코드줄']} | {행['주석줄']} | {대표} | {시험칸} |")


def main() -> int:
    ap = argparse.ArgumentParser(description="RTM 실측 스캐너")
    ap.add_argument("--md", action="store_true", help="마크다운 표로 출력")
    ap.add_argument("--json", action="store_true", help="JSON 으로 출력")
    args = ap.parse_args()

    파일들 = 훑을_파일들()
    행들 = 요구_스캔(B계열, 파일들)
    a = a계열_세기()
    시험 = 시험_현황()

    if args.json:
        print(json.dumps({"a계열": a, "b계열": 행들, "시험": 시험},
                         ensure_ascii=False, indent=2))
    elif args.md:
        마크다운_출력(행들, a, 시험)
    else:
        사람용_출력(행들, a, 시험)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
