"""모델 비교 화면 시험 (TC-MVS) — `public/js/mlcompare.js` · `public/css/mlcompare.css` · 연결 줄(app.html · main.js · core.js) (2026-10-15).

여기서 지키는 것 —
1. 연결 — 진입 훅 글자 그대로(화면 스캐너가 읽는 꼴) · main.js 가 부름 · app.html 은 강사님 칸 자리에 뿌리 칸 하나(강사님 「모델별 특성」 카드는 그대로)
   · CSS 링크 · 메뉴 이름표에 「7종」 없음(모델 수는 응답에서).
2. 서버 한 곳 — 판정 글 · 짧은 이름표 · 기준선 이름 · 기간 이름표 · 「왜」 문장을 화면 코드에 적지 않는다(응답에서 읽는다).
3. 계산 길 — 화면은 새 길(작업 시작 · 진행 묻기)만 부르고 옛 강사님 길(/api/ml/compare)을 부르지 않는다 · 계산을 띄우는 POST 는 라우트가 요구하는
   화면 머리글을 단다 · 캡처용 손잡이가 남지 않는다 · CSS 에 color-mix 가 없다(Figma 캡처가 검게 그린다 — 2026-10-15 실측).
4. 다음 행동 — 「비교에 추가」 로 담은 것을 볼 트레이 자리가 이 화면에 있다(옛 칸과 함께 사라졌던 것 · 브라우저 확인에서 찾음).
DB · 네트워크 없음(파일만 읽는다).
"""
from __future__ import annotations

import pathlib
import re

from app.routes import model_compare as R
from app.services import model_compare as mc

ROOT = pathlib.Path(__file__).resolve().parents[1]
JS = (ROOT / "public/js/mlcompare.js").read_text(encoding="utf-8")
CSS = (ROOT / "public/css/mlcompare.css").read_text(encoding="utf-8")
HTML = (ROOT / "public/app.html").read_text(encoding="utf-8")
MAIN = (ROOT / "public/js/main.js").read_text(encoding="utf-8")
CORE = (ROOT / "public/js/core.js").read_text(encoding="utf-8")
CODE = JS.split("*/", 1)[1]                     # 머리 주석(옛 칸 설명)은 빼고 코드만


def test_mvs01_wiring_hook_root_css_and_menu_label():
    assert re.search(r'^\s+if \(view !== "ml-compare"\) return;', JS, re.M)      # 글자 그대로 — view_scan 이 읽는다
    assert 'import { onModelCompareViewActivated } from "/js/mlcompare.js";' in MAIN
    assert re.search(r"^\s+onModelCompareViewActivated\(view\);", MAIN, re.M)
    view = HTML.split('data-view="ml-compare">', 1)[1].split('data-view="ml-regression"', 1)[0]
    assert '<div class="mv-root' in view
    assert "모델별 특성" in view                                                   # 강사님 설명 카드는 그대로
    assert 'id="mlc-run-btn"' not in HTML and "/api/ml/compare" not in CODE        # 옛 칸 · 옛 길을 화면이 쓰지 않는다
    assert '<link rel="stylesheet" href="/css/mlcompare.css" />' in HTML
    label = re.search(r'key: "ml-compare",[^}]*label: "([^"]+)"', CORE).group(1)
    assert label == "모델 비교" and "7종" not in label


def test_mvs02_server_strings_are_not_written_in_screen_code():
    banned = list(mc.VERDICT_TEXT.values()) + list(mc.VERDICT_LABEL.values()) \
        + [v for k, v in mc.BASELINE_NAMES.items()] + [v["label"] for v in mc.PERIOD_SPEC.values()] \
        + ["정확도의 함정", "외움과 배움", mc.NOTICE, mc.TEXT_UNAVAILABLE, mc.SOURCE_LABEL, mc.ATTRIBUTION, "공공데이터포털"]
    found = [b for b in banned if b in CODE]
    assert found == [], found
    for key in ("verdict_labels", "verdict_texts", "insights", "headline", "notice", "limits", "definitions",
                "data.label", "data.attribution", "data.window"):
        assert f"d.{key}" in CODE, key                                             # 응답 칸을 그대로 읽는다


def test_mvs03_calls_new_routes_with_screen_header_and_polls():
    assert '"/api/model-compare/choices"' in CODE
    assert '"/api/model-compare/jobs"' in CODE and "/api/model-compare/jobs/${" in CODE
    m = re.search(r'const ACTION = \{ "([^"]+)": "([^"]+)" \};', CODE)
    assert m and (m.group(1), m.group(2)) == (R.ACTION_HEADER, R.ACTION_VALUE)
    assert re.search(r'api\("/api/model-compare/jobs", \{ method: "POST", body, headers: ACTION \}\)', CODE)
    assert "setTimeout(() => poll(" in CODE and "POLL_MS = 1000" in CODE        # 1초마다 진행을 묻는다(사용자 결정)
    assert "if (S.admin) { body.n_splits" in CODE                                 # 겹 수 · 간격은 관리자일 때만 보낸다


def test_mvs05_compare_tray_has_a_place_on_this_screen():
    """「비교에 추가」 단추가 있으면 담은 것을 볼 자리도 이 화면에 있어야 한다(옛 칸을 걷어 낼 때 트레이 자리도 함께 사라졌었다 · 2026-10-15)."""
    assert 'data-act="tray"' in CODE
    mounts = re.search(r"const COMPARE_TRAY_MOUNTS = \[([^\]]+)\]", CORE).group(1)
    assert '"mlc-compare-tray"' in mounts and '<div id="mlc-compare-tray"></div>' in CODE
    assert "renderCompareTrayAll();" in CODE                                      # 다시 그린 뒤 담아 둔 항목을 채운다


def test_mvs04_no_capture_hook_and_no_color_mix():
    assert "__mvLayout" not in JS and "S.layout" not in JS
    assert "color-mix" not in CSS.split("*/", 1)[1]
    assert re.search(r"^\.mv-", CSS, re.M) and not re.search(r"^(body|main|\.card)\b", CSS, re.M)   # mv- 로만 · 공통 칸을 건드리지 않음
