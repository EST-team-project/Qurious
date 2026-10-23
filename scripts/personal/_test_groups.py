"""시험 묶음 표 — test.ps1 이 자동 시험을 묶음 차례로 나눠 돌 때 쓰는 한 곳.

test.ps1 의 -Split · -Group 이 이 파일에서 「묶음 → 시험 파일」 을 받아 묶음마다 새 pytest
프로세스를 띄운다. 한 프로세스가 2,000건 넘게 안고 가며 메모리가 쌓이지 않게 하려는 것이다
(실측 한 프로세스 1.34 GB · 근거 docs/phase-3/01-analysis/research/배경조사/2026-10-21-스크립트-점검/결과.md 3.1절).
지킴이 시험(tests/test_test_groups.py)도 같은 함수를 부른다 — 묶는 규칙은 여기 한 곳에만 있다.

규칙 —
  * 묶음은 위에서부터 차례로 맞대고, **처음 맞는 묶음**이 그 파일을 가진다(글롭이 겹쳐도 한 묶음에만).
  * 어느 글롭에도 안 맞는 새 시험 파일은 「나머지」 묶음으로 간다 — 빠지는 파일은 없다.
  * 글롭은 tests/ 아래 파일 이름만 본다 · 대소문자는 가리지 않는다(PowerShell -like 와 같게).
  * 묶음마다 영어 열쇠를 둔다 — Git Bash 에서 PowerShell 로 한글 인자를 넘기면 깨질 수 있어서
    (-Group 화면 과 -Group ui 가 같다) · 결과 파일 이름(ui.xml)도 이 열쇠로 짓는다.
  * 「컨테이너(ctr)」 묶음만 호스트가 아니라 앱 이미지 일회용 컨테이너에서 돈다(2026-10-23 · runner = container).
    호스트 파이썬에는 RAG · 채팅 패키지가 없어 그 파일들이 통째로 건너뛰어지기 때문이다. 맞대기는 맨 먼저
    (지식 묶음의 test_rag_* · test_chat_* 와 겹쳐도 여기로) · 실행은 맨 끝(호스트 묶음이 다 돈 뒤).

쓰는 법::

    python scripts/personal/_test_groups.py            # 묶음마다 파일 수 · 나머지 이름
    python scripts/personal/_test_groups.py --json     # test.ps1 이 읽는 꼴(ASCII JSON)
"""
from __future__ import annotations

import fnmatch
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]   # <저장소>/scripts/personal/ 에서 두 단계 위
TESTS = ROOT / "tests"

# (이름, 영어 열쇠, 글롭들) — 위에서부터 맞댄다. 「화면」 을 맨 앞에 두는 까닭: data_screens · chat_stock_card
# 처럼 다른 묶음 앞머리(data_ · chat_)와 겹치는 화면 시험을 먼저 가져가게.
GROUPS: list[tuple[str, str, tuple[str, ...]]] = [
    ("화면", "ui", (
        "test_*_screen.py", "test_*_screens.py", "test_*_view.py", "test_help*.py", "test_howto.py",
        "test_video_export.py", "test_nav_*.py", "test_brand.py", "test_completion_badge.py",
        "test_term_chips.py", "test_team_front_reflect.py", "test_view_scan.py", "test_chat_stock_card.py",
        "test_dashboard_*.py", "test_learn.py", "test_stock_hub.py",
    )),
    ("데이터", "data", (
        "test_collect*.py", "test_daily_update.py", "test_data_*.py", "test_hf_*.py", "test_backfill_*.py",
        "test_backup_*.py", "test_calendar_*.py", "test_market_calendar.py", "test_corp_schedule.py",
        "test_dart_*.py", "test_disclosure.py", "test_ecos_*.py", "test_event_sources.py", "test_fetch_plan.py",
        "test_financials.py", "test_gdelt_*.py", "test_policy_news.py", "test_ohlcv.py", "test_preprocess_*.py",
        "test_weekly_rehearsal.py", "test_beat_health.py", "test_fx_*.py", "test_crawl_points.py",
        "test_etf_classify.py", "test_intake.py", "test_universe_and_schedule.py", "test_schema_scan.py",
        "test_migration_heads.py", "test_no_yahoo_regression.py", "test_url_guard.py", "test_route_cache_*.py",
    )),
    ("지식", "kb", (
        "test_kb_*.py", "test_glossary*.py", "test_lecture*.py", "test_docs_scan.py", "test_rtm_scan.py",
        "test_api_*.py", "test_post_check.py", "test_discussion_scan.py", "test_raglab_scan.py", "test_rag_*.py",
        "test_chat_*.py", "test_opinion.py", "test_tagging.py", "test_console_encoding.py",
        "test_test_groups.py",
    )),
    ("매매", "trade", (
        "test_account_*.py", "test_aggressive_*.py", "test_asset_*.py", "test_auto_*.py", "test_broker_*.py",
        "test_execution_*.py", "test_kis_*.py", "test_lean_*.py", "test_legacy_*.py", "test_live_*.py",
        "test_order_*.py", "test_paper_*.py", "test_rebalance*.py", "test_reconciliation*.py", "test_risk_*.py",
        "test_robo_*.py", "test_session_*.py", "test_stock_coin_*.py", "test_stop_*.py", "test_task_*.py",
        "test_trading_*.py", "test_us_*.py", "test_quant_*.py", "test_qfrs_*.py", "test_fss_*.py",
        "test_product*.py", "test_quote*.py", "test_base_code_merge_guard.py",
    )),
    ("분석", "analysis", (
        "test_agent_*.py", "test_backtest_*.py", "test_company_*.py", "test_formula*.py", "test_indicator_*.py",
        "test_macro_*.py", "test_model_*.py", "test_mtf_*.py", "test_pattern*.py", "test_seasonal*.py",
        "test_signal_*.py", "test_spec_*.py", "test_strategy_*.py", "test_ta_*.py", "test_tradingview*.py",
        "test_xai*.py", "test_stock_*.py", "test_clusters*.py",
    )),
]
REST = ("나머지", "rest")
# 앱 이미지 일회용 컨테이너에서 도는 묶음 — 호스트 파이썬엔 qdrant-client · langchain-qdrant · langchain-ollama · langgraph 가
# 없어 이 파일들이 importorskip 으로 통째로 건너뛰어지고, 전체 시험이 RAG · 채팅 · 올린 문서 격리 회귀를 못 잡았다(2026-10-23 실측).
# 글롭이 아니라 이름을 그대로 적는다 — 새 시험이 호스트에서 돌 수 있으면 여기 넣지 않는다(컨테이너는 시험 DB 가 없다).
CONTAINER: tuple[str, str, tuple[str, ...]] = ("컨테이너", "ctr", (
    "test_rag_pipeline.py", "test_chat_modes.py", "test_doc_isolation.py",
))
#: docker compose 가 만든 앱 이미지 — 없으면 test.ps1 이 실패가 아니라 「건너뜀」 과 까닭을 남긴다(호스트에 패키지를 깔지 않는다)
CONTAINER_IMAGE = "qurious-app:latest"


def test_files(tests_dir: Path = TESTS) -> list[str]:
    """tests/ 바로 아래 test_*.py 이름(정렬). pytest 가 모으는 꼴(python_files 기본값)과 같다."""
    return sorted(p.name for p in tests_dir.glob("test_*.py"))


def group_of(name: str) -> tuple[str, str]:
    """파일 이름 하나가 드는 (묶음 이름, 열쇠). 컨테이너 묶음 이름이 먼저 · 맞는 글롭이 없으면 나머지."""
    low = name.lower()
    if low in {n.lower() for n in CONTAINER[2]}:
        return CONTAINER[0], CONTAINER[1]
    for label, key, globs in GROUPS:
        if any(fnmatch.fnmatchcase(low, g.lower()) for g in globs):
            return label, key
    return REST


def assign(names: list[str]) -> list[dict]:
    """묶음 차례대로 [{name, key, files, runner(, image)}] — 파일이 없는 묶음(대개 나머지)은 빼서 빈 pytest 실행이 없게.

    runner 는 host(호스트 파이썬) · container(앱 이미지 일회용 컨테이너 · 맨 끝).
    """
    order = [(label, key) for label, key, _ in GROUPS] + [REST] + [CONTAINER[:2]]
    buckets: dict[str, list[str]] = {key: [] for _, key in order}
    for n in names:
        buckets[group_of(n)[1]].append(n)
    out = []
    for label, key in order:
        if buckets[key]:
            g = {"name": label, "key": key, "files": buckets[key], "runner": "host"}
            if key == CONTAINER[1]:
                g.update(runner="container", image=CONTAINER_IMAGE)
            out.append(g)
    return out


def main(argv: list[str]) -> int:
    groups = assign(test_files())
    if "--json" in argv:
        # ASCII 로만 낸다 — PowerShell 5.1 이 파이썬 출력을 콘솔 코드 페이지로 읽어도 한글이 깨지지 않게
        out = {"groups": [{**g, "files": [f"tests/{f}" for f in g["files"]]} for g in groups]}
        print(json.dumps(out, ensure_ascii=True))
        return 0
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    total = sum(len(g["files"]) for g in groups)
    for g in groups:
        where = f" · 앱 이미지 컨테이너({g['image']})" if g["runner"] == "container" else ""
        print(f"{g['name']}({g['key']}) {len(g['files'])}{where}")
        if g["key"] == REST[1]:
            print("  " + " ".join(g["files"]))
    print(f"합계 {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
