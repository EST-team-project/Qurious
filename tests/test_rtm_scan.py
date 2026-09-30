"""RTM 스캐너 시험 (TC-RT) — 요구사항 추적표가 대장 · 코드와 어긋나지 않는가.

무엇을 지키나 —
① 요구 대장: 사람이 적는 요구 한 줄(유형 · 출처 · 우선순위 · 상태 · 검증 방법 · 관련 요구)의
   빈 칸 · 겹친 ID · 정한 말 밖 · 대장에 없는 관련 요구를 가린다.
② 시험-요구 대장: 시험 파일 → 묶음 → 요구 대응에서 없는 파일 · 없는 요구 · 두 파일을 가리키는
   묶음을 가린다. 대장에 없는 시험 파일은 **문제가 아니라 알림**이다 — 팀원이 시험을 더하는 것은
   좋은 일인데 그때마다 시험이 깨지면 안 된다(API · 스키마 스캐너 시험과 같은 원칙). 그래서 실제
   저장소에는 대장 파일 자체의 형식만 건다.
③ 흔적의 거짓 양성: 여러 줄 문서화 문자열 가운데 줄의 낱말을 구현으로 세면 안 된다 —
   `collector/benchmark.py` docstring 의 「재실행 안전(idempotent)」 한 줄 때문에 코드가 0 인
   「중복 주문 방지」 가 흔적이 있는 것처럼 보였다(2026-09-29 · RTM v1.1 을 만들며 발견).
④ 설계 절 · 요구 × API · 시험 수 · 문서 채우기가 정한 규칙대로 읽고 쓴다.
"""
from __future__ import annotations

import pytest

from scripts import rtm_scan


def _요구(**덮어쓰기: str) -> dict[str, str]:
    q = {칸: "" for 칸 in rtm_scan.요구_칸}
    q.update(요구ID="P01-①-1", 계열="B", 차수="2차", 이름="이름", 내용="내용", 유형="FR",
             출처="원문", 우선순위="필수", 상태="확정", 검증방법="시험")
    q.update(덮어쓰기)
    return q


def _짝(묶음: str, 파일: str, 요구ID: str, 확실도: str = "🟢") -> dict[str, str]:
    return {"묶음": 묶음, "파일": 파일, "요구ID": 요구ID, "확실도": 확실도, "무엇을_확인": "확인"}


def test_rt01_요구_대장_점검이_겹친_ID_정한_말_밖_빈_칸_없는_관련_요구를_가린다():
    요구들 = [
        _요구(),
        _요구(),                                        # 겹친 ID
        _요구(요구ID="P01-①-2", 유형="XR"),             # 정한 말 밖
        _요구(요구ID="P01-①-3", 내용=""),                # 빈 필수 칸
        _요구(요구ID="P01-①-4", 검증방법="시험 · 감"),    # 검증 방법 밖
        _요구(요구ID="P01-①-5", 관련요구="P09-①-1"),     # 대장에 없는 관련 요구
    ]
    문제 = rtm_scan.요구대장_점검(요구들)
    합 = "\n".join(문제)
    assert "겹친다: P01-①-1" in 합
    assert "P01-①-2 — 「유형」" in 합
    assert "P01-①-3 — 「내용」 칸이 비었다" in 합
    assert "검증 방법 「감」" in 합
    assert "관련 요구 P09-①-1" in 합
    assert len(문제) == 5


def test_rt02_시험_대장_점검은_잘못된_줄을_가리고_대장에_없는_시험_파일은_알림으로만_돌려준다():
    짝들 = [
        _짝("TC-A", "tests/test_a.py", "P01-①-1"),
        _짝("TC-A", "tests/test_b.py", "P01-①-1"),       # 한 묶음이 두 파일
        _짝("TC-C", "tests/test_없음.py", "—", "—"),      # 없는 파일
        _짝("TC-D", "tests/test_d.py", "P09-①-1"),       # 요구 대장에 없는 요구
        _짝("TC-E", "tests/test_e.py", "P01-①-1", "◎"),  # 확실도 밖
    ]
    파일들 = ["tests/test_a.py", "tests/test_b.py", "tests/test_d.py", "tests/test_e.py", "tests/test_새.py"]
    문제, 빠진 = rtm_scan.시험대장_점검(짝들, {"P01-①-1"}, 파일들)
    합 = "\n".join(문제)
    assert "TC-A 이 두 파일을 가리킨다" in 합
    assert "시험 파일 tests/test_없음.py 이 없다" in 합
    assert "요구 P09-①-1 가 요구 대장에 없다" in 합
    assert "TC-E · P01-①-1 — 확실도" in 합
    assert len(문제) == 4
    assert 빠진 == ["tests/test_새.py"]      # 문제가 아니라 알림 — 팀원이 더한 새 시험


def test_rt03_한_묶음이_요구_둘을_재면_둘_다에_세고_도구_묶음은_요구에_붙지_않는다():
    짝들 = [
        _짝("TC-A", "tests/test_a.py", "R1", "🟢"),
        _짝("TC-A", "tests/test_a.py", "R2", "🟡"),
        _짝("TC-T", "tests/test_t.py", "—", "—"),
    ]
    건수 = {"tests/test_a.py": 5, "tests/test_t.py": 3}
    assert rtm_scan.요구별_시험(짝들, 건수) == {"R1": [("TC-A", 5, "🟢")], "R2": [("TC-A", 5, "🟡")]}
    표 = rtm_scan.시험_표(짝들, 건수, ["tests/test_a.py", "tests/test_t.py", "tests/test_x.py"])
    assert "시험 8건 · 3파일 = 요구에 붙은 5건 + 요구 없는 도구 시험 3건 + 대장에 없는 파일 1개" in 표
    assert "| 〃 | 〃 | 〃 | `R2` | 🟡 |" in 표      # 같은 묶음의 둘째 줄은 되풀이 표시


def test_rt04_pytest_수집_출력은_두_모양_모두_파일별로_센다():
    조용한 = "tests/test_a.py: 21\ntests/test_b.py: 3\n\n"
    노드 = ("tests/test_a.py::test_x\ntests/test_a.py::test_y[1]\n"
            "tests/test_b.py::TestK::test_z\n\n3 tests collected in 0.10s\n")
    assert rtm_scan.수집_출력_해석(조용한) == {"tests/test_a.py": 21, "tests/test_b.py": 3}
    assert rtm_scan.수집_출력_해석(노드) == {"tests/test_a.py": 2, "tests/test_b.py": 1}


def test_rt05_설계_절은_요구_제목의_절이고_한눈_표와_부록은_세지_않으며_가장_높은_판을_읽는다(tmp_path):
    글 = "\n".join([
        "## 2. 한눈에", "### 2.3 한눈 표", "| `P01-①-1` | 한눈 표 줄 |",
        "## 4. 2차", "### 4.1 목표 기능 ①", "#### `P01-①-1` 용어사전 — P-A", "#### `P01-①-2` 수집",
        "## 6. 새로 드러난 것", "### 6.1 사각지대", "| `RFP2-3.1.3-①` | 평균-분산 |",
        "## 부록 A — 요구 × API", "<!-- req-api-map -->",
        "| 요구 ID | 받는 API (기존 ID · (새) 경로) |", "|---|---|",
        "| `P01-①-1` | API-GRPH-01 · API-GRPH-02 · (새) `GET /api/glossary` |",
        "| `RFP2-3.1.3-①` | API-ML-04 |",
        "<!-- /req-api-map -->",
        "### B.2 새 표 안", "| `P01-①-5` | T1 |",
    ])
    assert rtm_scan.설계_절(글) == {"P01-①-1": "4.1", "P01-①-2": "4.1", "RFP2-3.1.3-①": "6.1"}
    assert rtm_scan.요구_API(글) == {"P01-①-1": (["API-GRPH-01", "API-GRPH-02"], 1),
                                    "RFP2-3.1.3-①": (["API-ML-04"], 0)}
    for 이름 in ("기능설계_v0.1.md", "기능설계_v0.10.md", "기능설계_v0.2.md", "기능설계_초안.md"):
        (tmp_path / 이름).write_text("x", encoding="utf-8")
    assert rtm_scan.가장_높은_판(tmp_path, "기능설계").name == "기능설계_v0.10.md"


def test_rt06_API_ID_는_묶음별로_이어진_번호를_줄여_적는다():
    ids = ["API-STK-01", "API-STK-02", "API-STK-03", "API-STK-05", "API-STK-06", "API-ING-12", "API-ING-01"]
    assert rtm_scan.API_줄이기(ids) == "STK-01~03 · 05~06 · ING-01 · 12"


def test_rt07_여러_줄_문서화_문자열_안의_낱말은_흔적이_아니다(tmp_path, monkeypatch):
    """옛 판별(줄 앞머리)로는 실패한다 — docstring 가운데 줄이 코드로 잡혔다."""
    p = tmp_path / "m.py"
    p.write_text('def f():\n    """설명 첫 줄\n    재실행 안전(idempotent)이 보장된다\n    """\n'
                 '    return 1\n# idempotent 주석\nx = "dedup"\n', encoding="utf-8")
    monkeypatch.setattr(rtm_scan, "ROOT", tmp_path)
    out = rtm_scan.흔적_스캔({"R": [r"idempot", r"dedup"]}, [p])["R"]
    assert (out["코드줄"], out["주석줄"]) == (1, 2)      # 코드는 x = "dedup" 한 줄뿐
    assert rtm_scan.흔적_판정(out) == "희소 1파일 (m.py)"
    # 주석뿐이면 「주석뿐」 — 말이 있다고 장치가 있는 것은 아니다
    p.write_text('"""중복 주문 방지(dedup) 는 아직 없다"""\n# idempotent\n', encoding="utf-8")
    assert rtm_scan.흔적_판정(rtm_scan.흔적_스캔({"R": [r"idempot", r"dedup"]}, [p])["R"]) == "주석뿐"


def test_rt08_진행은_검사_확인_시험_확실도_흔적_순서로_정한다():
    빈 = {"검사결과": ""}
    assert rtm_scan.진행_판정({"검사결과": "✅ 2026-09-29 — 확인"}, [], "없음") == "검증 끝(검사)"
    assert rtm_scan.진행_판정({"검사결과": "🟡 2026-09-29 — 일부"}, [("TC-A", 3, "🟢")], "—") == "시험 있음"
    assert rtm_scan.진행_판정(빈, [("TC-A", 3, "🟡")], "있음 3파일") == "시험 일부"
    assert rtm_scan.진행_판정(빈, [], "희소 1파일 (app.html)") == "흔적 있음"
    assert rtm_scan.진행_판정(빈, [], "주석뿐") == "구현 전"
    assert rtm_scan.진행_판정(빈, [], "—") == "구현 전"


def test_rt09_추적_표는_계열별로_묶고_설계_API_시험_칸을_채운다():
    행 = {**_요구(요구ID="P01-①-2", 설계_추가="기능 설계서 3절 C1", 제안시험="TC-GL"),
         "설계절": "4.1", "API": ["API-STK-01", "API-STK-02"], "새API": 1,
         "시험": [("TC-CD", 22, "🟢"), ("TC-DU", 15, "🟡")],
         "흔적": "있음 3파일", "흔적상위": [], "진행": "시험 있음"}
    표 = rtm_scan.추적_표([행])
    assert "| **원문 PROJECT 01 로보 어드바이저 (2차)** |" in 표
    assert ("| `P01-①-2` | 설계서 4.1절 · 설계서 3절 C1 | STK-01~02 (새 1) | "
            "🟢 TC-CD 22 · 🟡 TC-DU 15 · 안 TC-GL | 시험 | 있음 3파일 | 시험 있음 |") in 표


def test_rt10_문서_채우기는_표시_사이만_바꾸고_줄_끝을_지키며_표시가_없으면_멈춘다():
    글 = "머리\r\n<!-- rtm_scan:추적 -->\r\n옛 표\r\n<!-- /rtm_scan:추적 -->\r\n꼬리\r\n"
    새글, 채운수 = rtm_scan.fill_doc(글, {"추적": "새 표\n둘째 줄", "시험": "이 문서엔 없는 블록"})
    assert 채운수 == 1
    assert 새글 == "머리\r\n<!-- rtm_scan:추적 -->\r\n새 표\r\n둘째 줄\r\n<!-- /rtm_scan:추적 -->\r\n꼬리\r\n"
    with pytest.raises(SystemExit):
        rtm_scan.fill_doc("표시 없는 문서\n", {"추적": "x"})


def test_rt11_실제_대장은_정한_형식이고_탐지_규칙의_요구가_모두_대장에_있다():
    """실제 저장소에 거는 것 — 대장 파일 자체의 형식만. 시험 파일이 모두 대장에 있는지는
    스캐너 요약 출력이 알린다(새 시험 파일을 더했다고 이 시험이 깨지지 않게)."""
    요구들 = rtm_scan.대장_읽기(rtm_scan.요구_대장)
    짝들 = rtm_scan.대장_읽기(rtm_scan.시험_대장)
    assert 요구들 and 짝들
    assert rtm_scan.요구대장_점검(요구들) == []
    적힌_파일 = sorted({짝["파일"] for 짝 in 짝들})       # 파일이 있는지는 여기서 보지 않는다
    문제, _ = rtm_scan.시험대장_점검(짝들, {q["요구ID"] for q in 요구들}, 적힌_파일)
    assert 문제 == []
    assert set(rtm_scan.탐지_패턴) <= {q["요구ID"] for q in 요구들}
    # 흔적을 한정하는 줄이 낡지 않았다 — 파일 이름이 바뀌면 규칙이 말없이 꺼지고 거짓 흔적이 되살아난다
    for 경로, 한정 in rtm_scan.흔적_한정.items():
        assert (rtm_scan.ROOT / 경로).is_file(), f"흔적_한정 이 없는 파일을 가리킨다: {경로}"
        assert 한정 <= set(rtm_scan.탐지_패턴), f"흔적_한정 이 탐지 규칙에 없는 요구를 적었다: {경로}"


def test_rt12_이름을_자료로_든_파일은_적힌_요구의_흔적으로만_센다(tmp_path, monkeypatch):
    """옛 코드(한정 없음)로는 실패한다 — 용어 분류표 한 줄이 「지표」 요구의 흔적으로 잡혔다.

    용어사전 빌드 스크립트는 화면 용어 키(`rsi` · `sharpe` · `backtest` …)의 분류표를 코드 줄로 들고 있다.
    그 파일을 더한 날 요구 20개의 흔적이 한 파일씩 늘었다(2026-09-30). 자기 요구(용어사전)의 흔적은 그대로 센다.
    """
    (tmp_path / "scripts").mkdir()
    표 = tmp_path / "scripts" / "glossary_build.py"
    표.write_text('CATEGORY = {"rsi": "technical", "sharpe": "quant"}\nOUT = "glossary_data"\n', encoding="utf-8")
    계산 = tmp_path / "calc.py"
    계산.write_text("def rsi(x):\n    return x\n", encoding="utf-8")
    monkeypatch.setattr(rtm_scan, "ROOT", tmp_path)
    규칙 = {"용어": [r"glossary"], "지표": [r"\brsi\b"]}

    monkeypatch.setattr(rtm_scan, "흔적_한정", {"scripts/glossary_build.py": {"용어"}})
    out = rtm_scan.흔적_스캔(규칙, [표, 계산])
    assert out["용어"]["파일수"] == 1                                   # (보존 확인) 자기 요구의 흔적은 그대로
    assert [경로 for 경로, _ in out["지표"]["상위"]] == ["calc.py"]        # 분류표 줄은 「지표」 의 흔적이 아니다

    # 빈 집합 = 어느 요구의 흔적으로도 세지 않는다
    monkeypatch.setattr(rtm_scan, "흔적_한정", {"scripts/glossary_build.py": set()})
    assert rtm_scan.흔적_스캔(규칙, [표, 계산])["용어"]["파일수"] == 0

    # (보존 확인) 한정이 없는 파일은 예전처럼 모든 요구에 센다
    monkeypatch.setattr(rtm_scan, "흔적_한정", {})
    assert rtm_scan.흔적_스캔(규칙, [표, 계산])["지표"]["파일수"] == 2
