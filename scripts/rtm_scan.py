"""요구사항 추적표(RTM) 실측 스캐너.

RTM 은 「이 요구는 구현됐는가」에 **증거로** 답하는 문서다. 그런데 증거를 사람이
손으로 적어 두면, 코드가 바뀌어도 표는 그대로 남아 거짓이 된다. 한 달 뒤 그 표를
믿을 수 있으려면 **다시 돌려서 확인할 수 있어야** 한다.

그래서 사람이 적는 것과 스크립트가 재는 것을 나눈다.

- 사람이 적는다 — 요구의 정의(이름 · 내용 · 유형 · 출처 · 우선순위 · 상태 · 검증 방법 · 관련 요구)는
  `docs/요구사항/대장/요구-대장.tsv` 에, 시험 파일이 어느 요구를 재는지는 `docs/요구사항/대장/시험-요구대장.tsv` 에.
- 스크립트가 잰다 — ① 코드 흔적(이름 검색) ② 시험 건수(pytest 수집) ③ 설계 절(기능 설계서의
  가장 높은 판에서 요구 ID 가 제목인 절) ④ 받는 API(기능 설계서 부록 A 의 `<!-- req-api-map -->` 블록).

    python scripts/rtm_scan.py                     # 사람이 읽는 요약 + 대장 점검
    python scripts/rtm_scan.py --md                # RTM 문서에 붙일 표 전부
    python scripts/rtm_scan.py --json              # 기계용
    python scripts/rtm_scan.py --doc <RTM 문서>     # 문서의 <!-- rtm_scan:이름 --> 사이를 다시 채운다
    python scripts/rtm_scan.py --check <RTM 문서>   # 다시 채울 곳이 있으면 종료코드 1

⚠️ **흔적은 「이름이 보이는가」이지 「제대로 동작하는가」가 아니다.** grep 이 잡는 것은 이름뿐이다.
실제 동작은 시험(TC)이 판정하고, RTM 은 그 둘을 나란히 놓는다 — 흔적은 있는데 시험이 없는
칸이 곧 위험한 칸이다.
"""

from __future__ import annotations

import argparse
import ast
import csv
import json
import os
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
요구_대장 = ROOT / "docs" / "요구사항" / "대장" / "요구-대장.tsv"
시험_대장 = ROOT / "docs" / "요구사항" / "대장" / "시험-요구대장.tsv"
설계_폴더 = ROOT / "docs" / "설계"

요구_칸 = ("요구ID", "계열", "차수", "이름", "내용", "유형", "출처", "우선순위", "상태",
          "검증방법", "검사결과", "관련요구", "설계_추가", "제안시험", "비고",
          "주담당", "부담당", "담당상태")
요구_필수칸 = ("요구ID", "계열", "차수", "이름", "내용", "유형", "출처", "우선순위", "상태", "검증방법")
시험_칸 = ("묶음", "파일", "요구ID", "확실도", "무엇을_확인")
# 담당 칸에 쓸 수 있는 이름 — 2026-10-01 팀이 정한 역할(계획서 v2.0 4절). 「팀」 은 네 명이 함께 지는 공통 요구.
# 주담당 = 설계 · 산출물 · 코드를 맡는 사람 · 부담당 = 질문을 먼저 받는 사람(확인은 네 명 모두).
담당_이름 = ("이동원", "신장환", "오준영", "강민석", "팀")

계열_이름 = {"B": "강사님 원문", "A": "제안요청서", "C": "강사님 공식 일정표"}
# 대장 칸마다 쓸 수 있는 말 — 유형 기호는 「제안요청서의 요구사항 작성 가이드」(2011)를 따른다
정한말 = {
    "계열": ("A", "B", "C"),
    "차수": ("2차", "3차", "공통"),
    "유형": ("FR", "PR", "QR", "IR", "DR", "OR", "CO"),
    "우선순위": ("필수", "선택", "미정"),
    "상태": ("확정", "제안"),
    "담당상태": ("확정", "제안"),
}
검증_방법 = ("시험", "시연", "검사", "분석")
확실도_값 = ("🟢", "🟡", "—")
진행_차례 = ("검증 끝(검사)", "시험 있음", "시험 일부", "흔적 있음", "구현 전")

# 훑지 않을 곳. 가상환경 · 캐시 · 데이터는 우리 구현이 아니다.
제외_디렉터리 = {
    ".git", "__pycache__", "node_modules", ".pytest_cache", ".serena",
    "data", "screenshots", ".playwright-mcp", ".venv", "venv",
    # 시험은 「시험」 칸에서 따로 센다 — 흔적으로 세면 시험이 구현처럼 보인다
    "tests",
    # 통합본 반입 폴더 — 옮겨만 놓았고 Qurious 앱과 이어지지 않은 코드다(파이썬 60 · JS 80여 개).
    # 흔적으로 세면 아직 만들지 않은 요구(RAG 출처 · 퀴즈 · 세무 등)가 「흔적 있음」 으로 보인다.
    # 기능을 app/ · public/ 으로 옮긴 뒤에야 그 코드가 흔적으로 잡힌다.
    "rag-lab",
}
# 문서 · 기록 도구는 요구 이름을 글자로 들고 있다(화면 키 목록 · 탐지 규칙 · 스크린샷 대상).
# ⚠️ v1.0 에서 스캐너 자신의 탐지 패턴 `rebalanc` 가 흔적으로 잡혀 「리밸런싱 0줄」이 「1줄」로 보였다.
문서_도구 = ("*_scan.py", "post_check.py", "take_screenshots.py")

# 다른 요구의 이름을 **자료로** 들고 있거나 낱말이 우연히 겹치는 파일 — 적힌 요구의 흔적으로만 센다.
# 빈 집합이면 어느 요구의 흔적으로도 세지 않는다. 경로는 저장소 루트 기준(/ 로 나눈다).
# 통째로 빼지(문서_도구) 않는 까닭: 앞의 둘은 자기 요구(용어사전)의 구현이라, 빼면 그 요구의 흔적이 준다.
# ⚠️ 용어사전 빌드 스크립트를 더한 날 요구 20개의 흔적이 한 파일씩 늘었다(2026-09-30) — 화면 용어 키 55개의
#    분류표(`"rsi": "technical"` · `"sharpe": "quant"` · `"backtest": "quant"` …)가 코드 줄이라서였다.
흔적_한정: dict[str, set[str]] = {
    "scripts/glossary_build.py": {"P01-①-1"},
    # `unicodedata.normalize` 가 「지표 정규화」(normaliz) 로 잡힌다 — 글자를 다듬는 것이지 지표 산식이 아니다
    "app/services/glossary_text.py": {"P01-①-1"},
    # 표시용 자료를 비공개 데이터셋과 주고받는 도구 — 수집기의 설정 읽기(.env)만 빌려 쓴다. 어느 요구의 구현도 아니다
    "scripts/raglab_data.py": set(),
    # 개념 학습(2026-10-01) — `normalize_body`(글 줄바꿈 다듬기)가 「지표 정규화」(normaliz · P02-②-1)로 잡힌다
    "app/services/learn_pages.py": {"P01-①-1"},
    # 교재 3.1 RAG 장의 예제 — `check_citations` 가 RAG 구현 흔적(citations · P01-①-3)으로 잡힌다. 설명용이지 구현이 아니다(W5 · W6)
    "public/learn/examples/rag_mini.py": set(),
    # HF 백업(2026-10-02 DF-40) — 분봉 표의 정렬 키 `"timeframe"` 이 여러 주기 지표 신호(P01-②-3)로 잡힌다.
    # 파일을 정렬할 칸 이름이지 신호 계산이 아니다. 전부터 세던 셋(수집 · 정기 배치 · 데이터 품질)만 센다
    "scripts/hf_dataset.py": {"P01-①-2", "P01-①-4", "SCH-DQ"},
    # 데이터 상태 · OHLCV 주소(2026-10-02) — 자료의 주기 칸 `timeframe` 이 여러 주기 신호(P01-②-3)로 잡힌다.
    # 주기별 자료를 내주는 것이지 신호를 계산하지 않는다(`data_status.py` 는 S78 부터 그렇게 세어지고 있었다)
    "app/services/data_ohlcv.py": {"P01-①-2", "P01-①-4"},
    "app/services/data_status.py": {"P01-①-2", "P01-①-4"},
    "app/routes/data.py": {"P01-①-2", "P01-①-4"},
}

# 훑을 확장자. 문서(.md)는 구현 증거가 아니라 뺀다.
코드_확장자 = {".py", ".html", ".js", ".yml", ".yaml", ".sql", ".toml", ".ini", ".cfg"}

# ─────────────────────────────────────────────────────────────────────
# 코드 흔적 — 요구가 구현됐다면 저장소에 보여야 할 이름 (정규식 · 대소문자 무시)
#   규칙이 없는 요구(검사로 보는 제약 · 문서화)는 흔적 칸이 「—」 다.
# ─────────────────────────────────────────────────────────────────────
탐지_패턴: dict[str, list[str]] = {
    # 원문 PROJECT 01 (2차)
    "P01-①-1": [r"glossary", r"용어\s*사전", r"연관\s*개념", r"related_term"],
    "P01-①-2": [r"collector\.", r"from collector", r"def collect", r"news"],
    "P01-①-3": [r"citations", r"qdrant", r"retriev"],
    "P01-①-4": [r"beat_schedule", r"ingest_day", r"doc_version", r"문서\s*버전"],
    "P01-①-5": [r"\bxai\b", r"explain(ab|ation)", r"추천\s*이유"],
    # ta_utils 6종은 강사님 원본과 바이트가 같다 — 흔적이 있어도 팀 작업으로 세지 않는다
    "P01-②-1": [r"\brsi\b", r"\bmacd\b", r"bollinger", r"moving_average"],
    "P01-②-2": [r"candle_?pattern", r"support_?level", r"resistance", r"breakout", r"golden_?cross"],
    "P01-②-3": [r"multi_?tf", r"timeframe", r"resample", r"confidence"],
    "P01-③-1": [r"rebalanc"],
    "P01-③-2": [r"drift_?toleran", r"target_?weight", r"이탈률"],
    "P01-③-3": [r"cash_?flow", r"deposit", r"withdraw", r"재투자"],
    "P01-④-1": [r"slippage", r"\bmdd\b", r"sharpe", r"max_?drawdown"],
    # 매수 · 매도 · 보유 글자는 화면 버튼에도 널려 있어 변환 로직 쪽으로 좁혔다
    "P01-④-2": [r"opinion", r"투자\s*의견", r"recommendation", r"signal_to_", r"decide_action"],
    "P01-④-3": [r"paper_?trading", r"place_order"],
    # 원문 PROJECT 02 (3차)
    "P02-①-1": [r"ta_utils", r"\brsi\b", r"\bmacd\b"],
    "P02-①-2": [r"stop_?loss", r"take_?profit", r"position_?siz", r"손절", r"익절"],
    "P02-①-3": [r"lean_?backtest", r"backtest"],
    "P02-②-1": [r"custom_?indicator", r"normaliz", r"정규화\s*산식"],
    "P02-②-2": [r"look_?ahead", r"lookahead", r"미래\s*데이터"],
    "P02-②-3": [r"indicator_?version", r"/indicators?", r"indicator_?api"],
    "P02-③-1": [r"pine", r"//@version"],
    "P02-③-2": [r"\blean\b", r"교차\s*검증", r"cross_?valid"],
    "P02-③-3": [r"webhook", r"notification", r"알림"],
    "P02-④-1": [r"commission", r"fee_?rate", r"요율"],
    "P02-④-2": [r"win_?rate", r"cumulative_?return", r"profit_?factor", r"승률"],
    "P02-④-3": [r"tradingview.*lean", r"lean.*tradingview", r"대조표"],
    "P02-⑤-1": [r"brokers?\.", r"get_broker_client", r"place_order"],
    "P02-⑤-2": [r"idempot", r"dedup", r"loss_?limit", r"kill_?switch", r"비상\s*정지"],
    # `logging.` 은 어느 파일에나 있어 뺐다 — 일정 · 배포 · 장애 알림만 센다
    "P02-⑤-3": [r"beat_schedule", r"docker-compose", r"장애\s*알림", r"alert_", r"healthcheck"],
    # 원문 UI/UX 요소 — 화면 키(view)와 화면 글자
    "U1": [r"성향\s*진단", r"risk_?survey"],
    "U2": [r"robo-portfolio", r"paper-dashboard"],
    "U3": [r"시뮬레이션"],
    "U4": [r"목표\s*수익률", r"target_?return"],
    "U5": [r"rebalanc"],
    "U6": [r"indicator-custom", r"indicator-strategy"],
    "U7": [r"trading-chart"],
    "U8": [r"indicator-backtest", r"quant-lean"],
    "U9": [r"성과\s*대시보드", r"performance-dashboard"],
    "U10": [r"robo-decision", r"quant-auto"],
    # 제안요청서 — 자산배분 · 스크리닝
    "RFP2-3.1.3-①": [r"markowitz", r"mean.?variance", r"efficient.?frontier", r"riskfolio",
                     r"pypfopt", r"cvxpy"],
    "RFP2-3.1.3-②": [r"risk.?parity", r"min(imum)?.?variance", r"최소\s*분산"],
    "RFP2-3.1.3-③": [r"black.?litterman", r"블랙.?리터만"],
    "RFP2-3.1.3-④": [r"market_?regime", r"국면", r"dynamic_?alloc"],
    "RFP2-3.1.4-①": [r"factor_?scor", r"value_?factor", r"quality_?factor", r"팩터"],
    # PER · PBR · ROE 는 영어 낱말(per)과 겹쳐 대문자만 센다
    "RFP2-3.1.4-②": [r"(?-i:\bPER\b|\bPBR\b|\bROE\b)", r"debt_?ratio", r"부채\s*비율"],
    "RFP2-3.1.4-③": [r"52.?week", r"52주", r"신고가", r"정배열"],
    "RFP2-3.1.4-④": [r"composite_?score", r"복합\s*점수", r"랭킹"],
    # 제안요청서 — 비기능 · 제외 범위 (이름으로 볼 수 있는 것만)
    "RFP2-3.2-③": [r"random_state", r"random\.seed", r"manual_seed"],
    "RFP2-4.2-①": [r"QURIOUS_ALLOW_LIVE_TRADING"],
    # 강사님 공식 일정표
    "SCH-STR": [r"stress_?test", r"스트레스\s*(테스트|검증|시나리오)"],
    "SCH-DQ": [r"SANITY_(LO|HI)", r"needs_review", r"게이트"],
    "SCH-ROB": [r"walk.?forward", r"워크\s*포워드", r"monte.?carlo", r"몬테\s*카를로", r"out.?of.?sample"],
    "SCH-ORD": [r"cancel_?order", r"modify_?order", r"정정\s*주문", r"주문\s*취소"],
    "SCH-RT": [r"websocket", r"웹소켓", r"stream_?quote"],
}


# ─────────────────────────────────────────────────────────────────────
# 대장 — 사람이 적는 두 파일
# ─────────────────────────────────────────────────────────────────────
def 대장_읽기(경로: Path) -> list[dict[str, str]]:
    """TSV 대장을 줄마다 사전으로. 파일이 없으면 빈 목록(새 clone · 다른 파트 PC)."""
    if not 경로.exists():
        return []
    with 경로.open(encoding="utf-8", newline="") as f:
        return [{k: (v or "").strip() for k, v in 줄.items()}
                for 줄 in csv.DictReader(f, delimiter="\t")]


def 나누기(칸: str) -> list[str]:
    """「A · B · C」 모양의 칸을 목록으로. 비었거나 「—」 면 빈 목록."""
    return [x.strip() for x in 칸.split("·") if x.strip() and x.strip() != "—"]


def 요구대장_점검(요구들: list[dict[str, str]]) -> list[str]:
    """요구 대장의 형식 문제를 모은다 — 빈 필수 칸 · 겹친 ID · 정한 말 밖 · 없는 관련 요구."""
    문제: list[str] = []
    if 요구들 and tuple(요구들[0]) != 요구_칸:
        문제.append(f"요구 대장 머리 줄이 다르다 — {' · '.join(요구_칸)}")
    본 = set()
    for q in 요구들:
        qid = q.get("요구ID", "")
        if qid in 본:
            문제.append(f"요구 ID 가 겹친다: {qid}")
        본.add(qid)
        for 칸 in 요구_필수칸:
            if not q.get(칸):
                문제.append(f"{qid or '(ID 없음)'} — 「{칸}」 칸이 비었다")
        for 칸, 말들 in 정한말.items():
            if q.get(칸) and q[칸] not in 말들:
                문제.append(f"{qid} — 「{칸}」 은 {' · '.join(말들)} 중 하나 (지금 {q[칸]})")
        for 방법 in 나누기(q.get("검증방법", "")):
            if 방법 not in 검증_방법:
                문제.append(f"{qid} — 검증 방법 「{방법}」 은 {' · '.join(검증_방법)} 밖이다")
    for q in 요구들:
        for 관련 in 나누기(q.get("관련요구", "")):
            if 관련 not in 본:
                문제.append(f"{q['요구ID']} — 관련 요구 {관련} 가 대장에 없다")
    return 문제


def 담당_점검(요구들: list[dict[str, str]]) -> list[str]:
    """담당 칸의 문제를 모은다 — 정한 이름 밖 · 주담당과 상태가 짝이 안 맞음 · 주 · 부 겸임 ·
    주담당이 확정되지 않은 원문 세부 기능.

    형식 점검(`요구대장_점검`)과 나눈 까닭: 담당은 팀이 정하는 값이라, 형식 시험의 가짜 줄마다
    담당을 채우게 하면 형식 규칙과 역할 규칙이 한 시험에 엉킨다.
    """
    문제: list[str] = []
    for q in 요구들:
        qid = q.get("요구ID", "")
        주, 부 = 나누기(q.get("주담당", "")), 나누기(q.get("부담당", ""))
        for 이름 in 주 + 부:
            if 이름 not in 담당_이름:
                문제.append(f"{qid} — 담당 「{이름}」 은 {' · '.join(담당_이름)} 밖이다")
        if bool(주) != bool(q.get("담당상태")):
            문제.append(f"{qid} — 주담당과 담당상태는 함께 적거나 함께 비운다")
        for 이름 in set(주) & set(부):
            문제.append(f"{qid} — {이름} 이 주담당이면서 부담당이다")
        # 강사님 원문 세부 기능(P01 · P02)은 2026-10-01 에 모두 주담당이 정해졌다 — 빠지면 그날 결정이 대장에서 샌 것
        if q.get("계열") == "B" and qid.startswith("P0") and not (주 and q.get("담당상태") == "확정"):
            문제.append(f"{qid} — 원문 세부 기능인데 확정된 주담당이 없다")
    return 문제


def 시험대장_점검(짝들: list[dict[str, str]], 요구ID들: set[str],
               시험파일들: list[str]) -> tuple[list[str], list[str]]:
    """(문제, 대장에 없는 시험 파일). 없는 파일은 문제가 아니라 알림이다 — 팀원이 시험을
    더하는 것은 좋은 일인데, 그때마다 시험이 깨지면 안 된다(API · 스키마 스캐너와 같은 원칙)."""
    문제: list[str] = []
    if 짝들 and tuple(짝들[0]) != 시험_칸:
        문제.append(f"시험 대장 머리 줄이 다르다 — {' · '.join(시험_칸)}")
    묶음_파일: dict[str, str] = {}
    for 짝 in 짝들:
        묶음, 파일, qid = 짝.get("묶음", ""), 짝.get("파일", ""), 짝.get("요구ID", "")
        if 묶음 in 묶음_파일 and 묶음_파일[묶음] != 파일:
            문제.append(f"{묶음} 이 두 파일을 가리킨다: {묶음_파일[묶음]} · {파일}")
        묶음_파일.setdefault(묶음, 파일)
        if 파일 not in 시험파일들:
            문제.append(f"{묶음} — 시험 파일 {파일} 이 없다")
        if qid != "—" and qid not in 요구ID들:
            문제.append(f"{묶음} — 요구 {qid} 가 요구 대장에 없다")
        if 짝.get("확실도") not in 확실도_값:
            문제.append(f"{묶음} · {qid} — 확실도는 {' · '.join(확실도_값)} 중 하나")
    빠진 = sorted(set(시험파일들) - {짝.get("파일", "") for 짝 in 짝들})
    return 문제, 빠진


# ─────────────────────────────────────────────────────────────────────
# 시험 — 파일마다 몇 건인가 (pytest 수집)
# ─────────────────────────────────────────────────────────────────────
def 수집_출력_해석(글: str) -> dict[str, int]:
    """`pytest --collect-only` 출력 → {시험 파일: 건수}.

    `pytest.ini` 의 `-q` 에 따라 모양이 둘로 갈린다 —
    `tests/test_x.py: 21` (조용한 모양) · `tests/test_x.py::test_이름` (노드 ID 한 줄씩).
    """
    건수: dict[str, int] = {}
    for 줄 in 글.splitlines():
        줄 = 줄.strip()
        m = re.match(r"^(\S+\.py):\s*(\d+)$", 줄)
        if m:
            건수[m.group(1)] = 건수.get(m.group(1), 0) + int(m.group(2))
            continue
        m = re.match(r"^(\S+\.py)::", 줄)
        if m:
            건수[m.group(1)] = 건수.get(m.group(1), 0) + 1
    return 건수


def 시험_파일별_건수() -> dict[str, int]:
    """pytest 로 실제 수집해 센다. 못 세면 빈 사전 — 요약이 「시험 수를 못 셌다」 고 알린다."""
    환경 = dict(os.environ, PYTHONIOENCODING="utf-8")
    try:
        결과 = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:warnings"],
            cwd=ROOT, capture_output=True, encoding="utf-8", errors="replace",
            env=환경, timeout=300,
        )
    except (subprocess.SubprocessError, OSError):
        return {}
    return 수집_출력_해석(결과.stdout)


def 시험_파일들() -> list[str]:
    return sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / "tests").glob("test_*.py"))


def 요구별_시험(짝들: list[dict[str, str]], 건수: dict[str, int]) -> dict[str, list[tuple[str, int, str]]]:
    """{요구 ID: [(묶음, 건수, 확실도)]}. 한 묶음이 요구 둘을 재면 둘 다에 센다."""
    out: dict[str, list[tuple[str, int, str]]] = {}
    for 짝 in 짝들:
        if 짝["요구ID"] == "—":
            continue
        out.setdefault(짝["요구ID"], []).append((짝["묶음"], 건수.get(짝["파일"], 0), 짝["확실도"]))
    return out


# ─────────────────────────────────────────────────────────────────────
# 설계 — 기능 설계서의 가장 높은 판
# ─────────────────────────────────────────────────────────────────────
def 가장_높은_판(폴더: Path, 머리: str) -> Path | None:
    # docs 정리(2026-10-07) 뒤에는 판 번호 없는 이름(`기능설계.md`)이 늘 최신이다 — 지난 판은 지난판/ 에 있다.
    판_없는_이름 = 폴더 / f"{머리}.md"
    if 판_없는_이름.exists():
        return 판_없는_이름
    판들 = []
    for p in 폴더.glob(f"{머리}_v*.md"):
        m = re.search(r"_v(\d+)\.(\d+)\.md$", p.name)
        if m:
            판들.append(((int(m.group(1)), int(m.group(2))), p))
    return max(판들)[1] if 판들 else None


_요구_ID = r"(?:P0[12]-[①-⑤]-\d|RFP2-[\d.]+-[①-④]|U\d+|SCH-[A-Z]+)"


def 설계_절(글: str) -> dict[str, str]:
    """{요구 ID: 절 번호}. 요구 ID 가 제목(`#### \\`P01-①-1\\` …`)인 곳의 위 절, 없으면 그 ID 로
    시작하는 표 줄이 있는 첫 절. 한눈 표(2절) · 부록은 요구의 설계 절이 아니라 세지 않는다."""
    절 = ""
    out: dict[str, str] = {}
    for 줄 in 글.splitlines():
        m = re.match(r"^#{2,3}\s+(\d+(?:\.\d+)?)[.\s]", 줄)
        if m:
            절 = m.group(1)
            continue
        if re.match(r"^#{2,3}\s+부록", 줄):
            절 = "부록"
            continue
        m = re.match(rf"^####\s+`({_요구_ID})`", 줄)
        if m and 절 and 절 != "부록":
            out[m.group(1)] = 절
            continue
        m = re.match(rf"^\|\s*`({_요구_ID})`", 줄)
        if m and 절 not in ("", "부록") and not 절.startswith("2") and m.group(1) not in out:
            out[m.group(1)] = 절
    return out


def 요구_API(글: str) -> dict[str, tuple[list[str], int]]:
    """부록 A `<!-- req-api-map -->` 블록 → {요구 ID: ([있는 API ID], 새 API 안 개수)}.

    API 명세 스캐너(`api_scan.load_requirement_map`)가 같은 블록을 거꾸로(API → 요구) 읽는다.
    블록 밖의 API ID 언급은 세지 않는다.
    """
    시작, 끝 = "<!-- req-api-map -->", "<!-- /req-api-map -->"
    if 시작 not in 글 or 끝 not in 글:
        return {}
    out: dict[str, tuple[list[str], int]] = {}
    for 줄 in 글.split(시작, 1)[1].split(끝, 1)[0].splitlines():
        칸들 = 줄.split("|")
        if len(칸들) < 3:
            continue
        m = re.search(rf"`({_요구_ID})`", 칸들[1])
        if not m:
            continue
        나머지 = "|".join(칸들[2:])
        out[m.group(1)] = (re.findall(r"\bAPI-[A-Z]+-\d{2,}\b", 나머지), 나머지.count("(새)"))
    return out


def API_줄이기(ids: list[str]) -> str:
    """API ID 목록을 짧게 — `API-STK-01 · 02 · 03 · 05` → `STK-01~03 · 05`."""
    묶음: dict[str, list[int]] = {}
    폭: dict[str, int] = {}
    for x in ids:
        m = re.match(r"API-([A-Z]+)-(\d+)$", x)
        if m:
            묶음.setdefault(m.group(1), []).append(int(m.group(2)))
            폭[m.group(1)] = len(m.group(2))
    조각: list[str] = []
    for 앞 in 묶음:
        수들 = sorted(set(묶음[앞]))
        구간: list[str] = []
        처음 = 이전 = 수들[0]
        for n in 수들[1:] + [None]:
            if n is not None and n == 이전 + 1:
                이전 = n
                continue
            w = 폭[앞]
            구간.append(f"{처음:0{w}d}" if 처음 == 이전 else f"{처음:0{w}d}~{이전:0{w}d}")
            if n is not None:
                처음 = 이전 = n
        조각.append(f"{앞}-" + " · ".join(구간))
    return " · ".join(조각)


# ─────────────────────────────────────────────────────────────────────
# 코드 흔적
# ─────────────────────────────────────────────────────────────────────
def 훑을_파일들() -> list[Path]:
    도구 = {p.resolve() for 무늬 in 문서_도구 for p in (ROOT / "scripts").glob(무늬)}
    도구.add(Path(__file__).resolve())
    결과 = []
    for p in ROOT.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in 코드_확장자:
            continue
        if any(부분 in 제외_디렉터리 for 부분 in p.relative_to(ROOT).parts):
            continue
        # 강의자료(제안요청서 원문)는 우리 구현이 아니다
        if p.parent == ROOT / "docs":
            continue
        if p.resolve() in 도구:
            continue
        결과.append(p)
    return 결과


def 주석_줄인가(줄: str, 확장자: str) -> bool:
    """주석 · 문서화 문자열로 보이는 줄인가.

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


def 문서화_문자열_줄(본문: str) -> set[int]:
    """파이썬 소스에서 문서화 문자열(홀로 선 문자열 식)이 차지하는 줄 번호(1부터).

    줄 앞머리만 보면 여러 줄 docstring 의 가운데 줄은 코드로 보인다 — `collector/benchmark.py` 의
    docstring 가운데 「재실행 안전(idempotent)」 한 줄이 「중복 주문 방지」 의 흔적으로 잡혔다(v1.1).
    표준 라이브러리 `ast` 로 범위만 읽는다. 문법 오류가 나는 파일은 빈 집합(줄 앞머리 판별만 쓴다).
    """
    try:
        트리 = ast.parse(본문)
    except (SyntaxError, ValueError):
        return set()
    줄들: set[int] = set()
    for 노드 in ast.walk(트리):
        if (isinstance(노드, ast.Expr) and isinstance(노드.value, ast.Constant)
                and isinstance(노드.value.value, str)):
            줄들.update(range(노드.lineno, (노드.end_lineno or 노드.lineno) + 1))
    return 줄들


def 흔적_스캔(패턴표: dict[str, list[str]], 파일들: list[Path]) -> dict[str, dict]:
    """{요구 ID: {파일수 · 코드줄 · 주석줄 · 상위}}. 주석 속 낱말은 구현으로 세지 않는다 —
    「중복주문 방지」 흔적 2건이 전부 주석 속 "idempotent" 였던 일이 실제로 있었다."""
    본문: dict[Path, str] = {}
    문서줄: dict[Path, set[int]] = {}
    for f in 파일들:
        try:
            본문[f] = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            본문[f] = ""
        문서줄[f] = 문서화_문자열_줄(본문[f]) if f.suffix.lower() == ".py" else set()
    out: dict[str, dict] = {}
    for qid, 패턴 in 패턴표.items():
        정규식 = [re.compile(p, re.IGNORECASE) for p in 패턴]
        적중: dict[str, tuple[int, int]] = {}
        for f in 파일들:
            한정 = 흔적_한정.get(f.relative_to(ROOT).as_posix())
            if 한정 is not None and qid not in 한정:
                continue                  # 이 요구의 이름을 자료로만 들고 있는 파일이다
            코드 = 주석 = 0
            for 번호, 줄 in enumerate(본문[f].splitlines(), start=1):
                if any(x.search(줄) for x in 정규식):
                    if 번호 in 문서줄[f] or 주석_줄인가(줄, f.suffix.lower()):
                        주석 += 1
                    else:
                        코드 += 1
            if 코드 or 주석:
                적중[f.relative_to(ROOT).as_posix()] = (코드, 주석)
        상위 = sorted(적중.items(), key=lambda kv: (-kv[1][0], -kv[1][1], kv[0]))[:4]
        out[qid] = {
            "파일수": sum(1 for v in 적중.values() if v[0]),
            "코드줄": sum(v[0] for v in 적중.values()),
            "주석줄": sum(v[1] for v in 적중.values()),
            "상위": [(경로, v[0]) for 경로, v in 상위 if v[0]],
        }
    return out


def 흔적_판정(행: dict | None) -> str:
    """흔적의 양. **동작 여부가 아니다.** 파일이 한두 개면 어느 파일인지 붙인다 — 화면 설명
    글자(`public/app.html`)뿐인 흔적이 계산 코드처럼 읽히지 않게."""
    if 행 is None:
        return "—"
    if 행["코드줄"] == 0:
        return "주석뿐" if 행["주석줄"] else "없음"
    if 행["파일수"] >= 3:
        return f"있음 {행['파일수']}파일"
    어디 = " · ".join(Path(경로).name for 경로, _ in 행["상위"])
    return f"희소 {행['파일수']}파일 ({어디})"


def 진행_판정(요구: dict[str, str], 시험들: list[tuple[str, int, str]], 흔적: str) -> str:
    """구현 진행 — 상태(확정 · 제안)와 따로 본다. 제안 요구도 시험이 있으면 그대로 적는다.

    「검증 끝」 은 사람이 검사해 ✅ 를 적은 요구뿐이다. 시험이 붙었다고 끝이 아니다 — 인수 기준이
    아직 없어서 「무엇을 통과하면 끝인가」 를 시험이 다 덮는지 모른다.
    """
    if 요구.get("검사결과", "").startswith("✅"):
        return "검증 끝(검사)"
    if any(확실도 == "🟢" for _, _, 확실도 in 시험들):
        return "시험 있음"
    if 시험들:
        return "시험 일부"
    if 흔적.startswith(("있음", "희소")):
        return "흔적 있음"
    return "구현 전"


# ─────────────────────────────────────────────────────────────────────
# 측정 한 벌
# ─────────────────────────────────────────────────────────────────────
def 측정(요구들: list[dict[str, str]], 짝들: list[dict[str, str]], 건수: dict[str, int],
       설계글: str, 흔적: dict[str, dict]) -> list[dict]:
    절들, apis = 설계_절(설계글), 요구_API(설계글)
    요구시험 = 요구별_시험(짝들, 건수)
    행들 = []
    for q in 요구들:
        qid = q["요구ID"]
        시험 = 요구시험.get(qid, [])
        흔 = 흔적_판정(흔적.get(qid))
        있는, 새 = apis.get(qid, ([], 0))
        행들.append({
            **q,
            "설계절": 절들.get(qid, ""),
            "API": 있는, "새API": 새,
            "시험": 시험,
            "흔적": 흔,
            "흔적상위": (흔적.get(qid) or {}).get("상위", []),
            "진행": 진행_판정(q, 시험, 흔),
        })
    return 행들


# ─────────────────────────────────────────────────────────────────────
# 마크다운 — RTM 문서의 <!-- rtm_scan:이름 --> 블록
#   스캐너가 만든 표는 번호 없이 제목만 둔다(문서가 절 번호로 가리킨다 — 문서 작성 기준 부록 C).
# ─────────────────────────────────────────────────────────────────────
def _칸(글: str) -> str:
    return (글 or "—").replace("|", "\\|")


def _ids(칸: str) -> str:
    return " · ".join(f"`{x}`" for x in 나누기(칸)) or "—"


묶음_이름 = {
    "요구-P01": ("원문 PROJECT 01 로보 어드바이저 (2차) — 세부 기능", lambda q: q["요구ID"].startswith("P01-")),
    "요구-P02": ("원문 PROJECT 02 투자 인디케이터 (3차) — 세부 기능", lambda q: q["요구ID"].startswith("P02-")),
    "요구-U": ("원문 UI/UX 필요 요소", lambda q: re.match(r"U\d+$", q["요구ID"]) is not None),
    "요구-A": ("제안요청서(rfp-2) — 원문 세부 기능 표에 없는 것", lambda q: q["계열"] == "A"),
    "요구-C": ("강사님 공식 일정표 — 원문 · 제안요청서가 받지 않는 기능 칸", lambda q: q["계열"] == "C"),
}


def 요구_표(요구들: list[dict[str, str]], 제목: str) -> str:
    줄 = [f"**{제목} · {len(요구들)}개**", "",
          "| 요구 ID | 이름 | 내용 (검증할 수 있는 한 문장) | 유형 | 출처 | 우선 | 상태 | 관련 요구 |",
          "|---|---|---|:-:|---|:-:|:-:|---|"]
    for q in 요구들:
        줄.append(f"| `{q['요구ID']}` | {_칸(q['이름'])} | {_칸(q['내용'])} | {q['유형']} | "
                 f"{_칸(q['출처'])} | {q['우선순위']} | {q['상태']} | {_ids(q['관련요구'])} |")
    비고 = [q for q in 요구들 if q.get("비고")]
    if 비고:
        줄 += ["", "비고"]
        줄 += [f"- `{q['요구ID']}` — {q['비고']}" for q in 비고]
    return "\n".join(줄)


def _설계_칸(행: dict) -> str:
    조각 = [f"설계서 {행['설계절']}절"] if 행["설계절"] else []
    조각 += [x.replace("기능 설계서 ", "설계서 ") for x in 나누기(행.get("설계_추가", ""))]
    # 같은 절을 두 번 적지 않는다(대장에 적은 절 = 스캐너가 찾은 절)
    return " · ".join(dict.fromkeys(조각)) or "—"


def _API_칸(행: dict) -> str:
    if not 행["API"] and not 행["새API"]:
        return "—"
    글 = API_줄이기(행["API"]) if 행["API"] else ""
    if 행["새API"]:
        글 = f"{글} (새 {행['새API']})".strip()
    return 글


def _시험_칸(행: dict) -> str:
    조각 = []
    for 표시 in ("🟢", "🟡"):
        묶음들 = [f"{m} {n}" for m, n, c in 행["시험"] if c == 표시]
        if 묶음들:
            조각.append(f"{표시} " + " · ".join(묶음들))
    안 = 나누기(행.get("제안시험", ""))
    if 안:
        조각.append("안 " + " · ".join(안))
    return " · ".join(조각) or "—"


def 추적_표(행들: list[dict]) -> str:
    줄 = ["**요구 → 설계 → API → 시험 → 진행 · 전체 " + str(len(행들)) + "개**", "",
          "| 요구 ID | 설계 | 받는 API (`API-` 생략) | 시험 — 묶음 건수 (안 = 제안) | 검증 방법 | 코드 흔적 | 진행 |",
          "|---|---|---|---|---|---|---|"]
    for 키, (제목, 고름) in 묶음_이름.items():
        묶음 = [h for h in 행들 if 고름(h)]
        if not 묶음:
            continue
        줄.append(f"| **{제목.split(' — ')[0]}** | | | | | | |")
        for h in 묶음:
            줄.append(f"| `{h['요구ID']}` | {_설계_칸(h)} | {_API_칸(h)} | {_시험_칸(h)} | "
                     f"{h['검증방법']} | {h['흔적']} | {h['진행']} |")
    검사 = [h for h in 행들 if h.get("검사결과")]
    if 검사:
        줄 += ["", "검사 결과 (사람이 확인해 대장에 적은 것)"]
        줄 += [f"- `{h['요구ID']}` — {h['검사결과']}" for h in 검사]
    return "\n".join(줄)


def 시험_표(짝들: list[dict[str, str]], 건수: dict[str, int], 파일들: list[str]) -> str:
    줄 = ["**시험 묶음 → 요구 · 확실도 🟢 그 요구의 동작을 직접 잰다 · 🟡 전제나 일부만 잰다 · — 요구 없는 도구 시험**", "",
          "| 묶음 | 파일 | 건수 | 요구 | 확실도 | 무엇을 확인 |",
          "|---|---|--:|---|:-:|---|"]
    앞묶음 = None
    for 짝 in 짝들:
        같음 = 짝["묶음"] == 앞묶음
        파일 = "〃" if 같음 else f"`{짝['파일'].removeprefix('tests/')}`"
        n = "〃" if 같음 else str(건수.get(짝["파일"], 0))
        qid = "—" if 짝["요구ID"] == "—" else f"`{짝['요구ID']}`"
        줄.append(f"| {'〃' if 같음 else 짝['묶음']} | {파일} | {n} | {qid} | {짝['확실도']} | {_칸(짝['무엇을_확인'])} |")
        앞묶음 = 짝["묶음"]
    전체 = sum(건수.get(f, 0) for f in 파일들)
    파일_요구: dict[str, bool] = {}
    for 짝 in 짝들:
        파일_요구[짝["파일"]] = 파일_요구.get(짝["파일"], False) or 짝["요구ID"] != "—"
    붙음 = sum(건수.get(f, 0) for f, 있음 in 파일_요구.items() if 있음)
    도구 = sum(건수.get(f, 0) for f, 있음 in 파일_요구.items() if not 있음)
    빠진 = sorted(set(파일들) - set(파일_요구))
    줄 += ["", f"합계 — 시험 {전체}건 · {len(파일들)}파일 = 요구에 붙은 {붙음}건 + 요구 없는 도구 시험 {도구}건"
           + (f" + 대장에 없는 파일 {len(빠진)}개({' · '.join(빠진)})" if 빠진 else " · 대장에 없는 시험 파일 0개")]
    return "\n".join(줄)


def _너비(글: str) -> int:
    """고정폭 글꼴에서 차지하는 칸 수 — 한글 · 전각은 두 칸(문서 작성 기준 6.4)."""
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in 글)


def _채움(글: str, 폭: int) -> str:
    return 글 + " " * max(0, 폭 - _너비(글))


def _막대(n: int, 전체: int, 폭: int = 30) -> str:
    칸 = round(n / 전체 * 폭) if 전체 else 0
    return "█" * 칸 + " " * (폭 - 칸)


def 분포_그림(행들: list[dict]) -> str:
    전체 = len(행들)
    줄 = ["**진행 분포 — 요구 " + str(전체) + "개 · 막대 폭 30칸 = 전체**", "", "```"]
    for 진행 in 진행_차례:
        n = sum(1 for h in 행들 if h["진행"] == 진행)
        줄.append(f" {_채움(진행, 14)} {_막대(n, 전체)} {n:>3}")
    줄.append(" " + "─" * 50)
    for 키, (제목, 고름) in 묶음_이름.items():
        묶음 = [h for h in 행들 if 고름(h)]
        if not 묶음:
            continue
        세부 = " · ".join(f"{진행} {c}" for 진행 in 진행_차례
                        if (c := sum(1 for h in 묶음 if h["진행"] == 진행)))
        줄.append(f" {제목.split(' — ')[0]} {len(묶음)}개: {세부}")
    유형 = {}
    for h in 행들:
        유형[h["유형"]] = 유형.get(h["유형"], 0) + 1
    줄.append(" 유형: " + " · ".join(f"{k} {유형[k]}" for k in 정한말["유형"] if k in 유형))
    줄.append("```")
    return "\n".join(줄)


def 블록들(행들: list[dict], 짝들: list[dict[str, str]], 건수: dict[str, int],
        파일들: list[str]) -> dict[str, str]:
    out = {}
    for 키, (제목, 고름) in 묶음_이름.items():
        out[키] = 요구_표([h for h in 행들 if 고름(h)], 제목)
    out["추적"] = 추적_표(행들)
    out["시험"] = 시험_표(짝들, 건수, 파일들)
    out["분포"] = 분포_그림(행들)
    return out


def fill_doc(text: str, blocks: dict[str, str]) -> tuple[str, int]:
    """문서 안 `<!-- rtm_scan:이름 -->` … `<!-- /rtm_scan:이름 -->` 사이를 새 출력으로 바꾼다.

    표시 밖의 사람이 쓴 글은 건드리지 않고, 줄 끝은 문서가 쓰던 것(CRLF · LF)을 따른다
    (API 명세 · 스키마 스캐너의 `fill_doc` 과 같은 규칙).
    """
    nl = "\r\n" if "\r\n" in text else "\n"
    채운수 = 0
    for name, body in blocks.items():
        start, end = f"<!-- rtm_scan:{name} -->", f"<!-- /rtm_scan:{name} -->"
        if start not in text:
            continue
        if text.count(start) != 1 or text.count(end) != 1:
            raise SystemExit(f"문서에 {start} · {end} 표시가 한 쌍 있어야 한다")
        head, rest = text.split(start, 1)
        _old, tail = rest.split(end, 1)
        text = head + start + nl + body.replace("\n", nl) + nl + end + tail
        채운수 += 1
    if not 채운수:
        raise SystemExit("문서에 rtm_scan 표시가 없다 — "
                         f"{', '.join(f'<!-- rtm_scan:{n} -->' for n in blocks)} 중 하나를 둔다")
    return text, 채운수


# ─────────────────────────────────────────────────────────────────────
# A계열 — 저장소 안 제안요청서 `docs/rfp-2.md` 의 체크박스 (요구 개수 논쟁의 한쪽 축)
# ─────────────────────────────────────────────────────────────────────
def a계열_세기() -> dict:
    """rfp-2.md 의 체크박스를 절별로 센다."""
    경로 = ROOT / "docs" / "rfp-2.md"
    if not 경로.exists():
        return {"절별": [], "합계": 0}
    현재절, 순서, 개수 = None, [], {}
    for 줄 in 경로.read_text(encoding="utf-8").splitlines():
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
# 출력
# ─────────────────────────────────────────────────────────────────────
def 사람용_출력(행들: list[dict], 문제: list[str], 빠진: list[str], 건수: dict[str, int],
            설계경로: str, a: dict) -> None:
    print("― 요구사항 추적 실측 ―\n")
    계열수 = {k: sum(1 for h in 행들 if h["계열"] == k) for k in 계열_이름}
    print(f"  요구 대장 {len(행들)}개 · " + " · ".join(f"{계열_이름[k]} {n}" for k, n in 계열수.items()))
    print(f"  시험 {sum(건수.values())}건 · {len(건수)}파일" if 건수 else "  ⚠️ 시험 수를 못 셌다 (pytest 수집 실패)")
    print(f"  설계서 {설계경로 or '(없음)'} — 절을 찾은 요구 {sum(1 for h in 행들 if h['설계절'])} · "
          f"부록 A 에 API 가 있는 요구 {sum(1 for h in 행들 if h['API'] or h['새API'])}")
    print(f"  rfp-2 체크박스 {a['합계']}개 — " + " · ".join(f"{이름} {수}" for 이름, 수 in a["절별"]))
    주담당수: dict[str, int] = {}
    for h in 행들:
        for 이름 in 나누기(h.get("주담당", "")):
            주담당수[이름] = 주담당수.get(이름, 0) + 1
    if 주담당수:
        상태수 = {s: sum(1 for h in 행들 if h.get("담당상태") == s) for s in 정한말["담당상태"]}
        print("  주담당 — " + " · ".join(f"{n} {주담당수[n]}" for n in 담당_이름 if n in 주담당수)
              + " (" + " · ".join(f"담당 {s} {n}" for s, n in 상태수.items()) + ")")
    print()
    if 문제:
        print(f"  ⚠️ 대장 점검 {len(문제)}건")
        for x in 문제:
            print(f"     - {x}")
    else:
        print("  ✅ 대장 점검 — 문제 없음")
    if 빠진:
        print(f"  ℹ️ 시험-요구 대장에 없는 시험 파일 {len(빠진)}개 — 대장에 한 줄 더해 주세요: {' · '.join(빠진)}")
    print()
    print(f"  {_채움('요구', 15)}{_채움('유형', 5)}{_채움('진행', 15)}{_채움('흔적', 13)}시험")
    print("  " + "─" * 78)
    for h in 행들:
        시험 = " · ".join(f"{m}{c}" for m, _, c in h["시험"]) or "—"
        print(f"  {_채움(h['요구ID'], 15)}{_채움(h['유형'], 5)}{_채움(h['진행'], 15)}"
              f"{_채움(h['흔적'], 13)} {시험}")
    print()
    print("  ⚠️ 흔적은 「이름이 보이는가」이지 「제대로 동작하는가」가 아니다.")


def main(argv: list[str] | None = None) -> int:
    # git bash(mintty)에서는 표준출력이 파이프로 잡혀 cp949 가 된다 → ✅ · ⚠️ · — 한 글자에서 UnicodeEncodeError.
    # 도움말에도 그 글자가 있어 argparse 보다 먼저 맞춘다 (DF-11 · collector/console.py 머리말).
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="RTM 실측 스캐너 — 요구 대장 · 시험-요구 대장에 실측을 붙인다")
    ap.add_argument("--md", action="store_true", help="RTM 문서에 붙일 표 전부를 마크다운으로")
    ap.add_argument("--json", action="store_true", help="JSON 으로 출력")
    ap.add_argument("--doc", metavar="문서", help="문서의 <!-- rtm_scan:이름 --> 사이를 다시 채운다")
    ap.add_argument("--check", metavar="문서", help="다시 채울 곳이 있으면 종료코드 1 (문서는 그대로)")
    args = ap.parse_args(argv)

    요구들 = 대장_읽기(요구_대장)
    짝들 = 대장_읽기(시험_대장)
    파일들 = 시험_파일들()
    문제 = 요구대장_점검(요구들) + 담당_점검(요구들)
    요구ID들 = {q["요구ID"] for q in 요구들}
    시험문제, 빠진 = 시험대장_점검(짝들, 요구ID들, 파일들)
    문제 += 시험문제
    문제 += [f"탐지 규칙의 요구 {k} 가 요구 대장에 없다" for k in 탐지_패턴 if k not in 요구ID들]
    설계경로 = 가장_높은_판(설계_폴더, "기능설계")
    설계글 = 설계경로.read_text(encoding="utf-8") if 설계경로 else ""
    건수 = 시험_파일별_건수()
    흔적 = 흔적_스캔(탐지_패턴, 훑을_파일들())
    행들 = 측정(요구들, 짝들, 건수, 설계글, 흔적)
    설계표시 = 설계경로.relative_to(ROOT).as_posix() if 설계경로 else ""

    if args.doc or args.check:
        문서 = Path(args.doc or args.check)
        옛글 = 문서.read_bytes().decode("utf-8")
        새글, 채운수 = fill_doc(옛글, 블록들(행들, 짝들, 건수, 파일들))
        if args.check:
            if 새글 != 옛글:
                print(f"⚠️ {문서} — 표가 대장 · 코드와 다르다. `python scripts/rtm_scan.py --doc {문서}` 로 다시 채운다")
                return 1
            print(f"✅ {문서} — 블록 {채운수}개가 대장 · 코드와 같다")
            return 0
        문서.write_bytes(새글.encode("utf-8"))
        print(f"✅ {문서} — 블록 {채운수}개를 다시 채웠다" + (f" · ⚠️ 대장 점검 {len(문제)}건" if 문제 else ""))
        return 0
    if args.json:
        print(json.dumps({"요구": 행들, "시험_건수": 건수, "대장_점검": 문제, "대장에_없는_시험": 빠진,
                          "설계서": 설계표시, "a계열": a계열_세기()},
                         ensure_ascii=False, indent=2, default=list))
    elif args.md:
        for 이름, 본문 in 블록들(행들, 짝들, 건수, 파일들).items():
            print(f"<!-- rtm_scan:{이름} -->\n{본문}\n<!-- /rtm_scan:{이름} -->\n")
    else:
        사람용_출력(행들, 문제, 빠진, 건수, 설계표시, a계열_세기())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
