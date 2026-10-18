"""TC-RPL — 오준영 님 화면 잠정 반영 둘(D124 · 2026-10-18 · 시연 영상을 찍다가 찾음 · 사전 알림 #244 01)

1. 자산배분 · 최적화 — 투자 성향 진단 결과 글(public/js/robo.js)
   서버가 주는 성향 값(conservative · moderate · aggressive)은 프로그램이 쓰는 낱말이다. 진단 결과 줄과 알림은 그 값 대신
   바로 아래 「투자 성향」 선택 칸(public/app.html #robo-risk)의 글(「중립 (위험중립형)」)을 보인다 — 결과 줄 · 알림에
   「moderate」 가 그대로 보였다(영상 기준표 「내부 영어 낱말」). 되돌리려면 profileLabel 대신 r.risk_profile. (TC-RPL-01)
2. 리밸런싱 엔진 — 처음 계획 저장(public/js/rebalance.js)
   계획이 아직 없는 사람은 「현금흐름 재배분 기준 금액」 칸이 비어 있는데 고르기 칸은 「금액 무관」 으로 보여, 저장이
   「설정 금액과 이탈률을 입력하세요」 로 막혔다(주문 산출도 「가져온 목표를 먼저 플랜에 저장하세요」). 화면을 열 때 비어 있는
   칸만 보이는 고르기 값으로 채운다 — 저장 검사 규칙은 그대로. 되돌리려면 그 한 줄을 지운다. (TC-RPL-02)
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROBO = ROOT / "public" / "js" / "robo.js"
REBALANCE = ROOT / "public" / "js" / "rebalance.js"
APP = ROOT / "public" / "app.html"


def test_profile_result_uses_the_select_label():
    """TC-RPL-01 · 결과 줄 · 알림은 선택 칸 글 — 서버 낱말을 그대로 넣지 않는다 · 선택 칸 세 값은 한국어 글"""
    src = ROBO.read_text(encoding="utf-8")
    i = src.index('api("/api/ml/robo/risk-profile"')
    block = src[i:src.index("} catch (e)", i)]
    assert 'document.querySelector(`#robo-risk option[value="${r.risk_profile}"]`)?.textContent' in block, "선택 칸 글을 읽는다"
    assert "${escHtml(profileLabel)}" in block, "결과 줄은 선택 칸 글"
    assert "${profileLabel}" in block.split("setToast(", 1)[1], "알림도 선택 칸 글"
    assert "${escHtml(r.risk_profile)}" not in block and "${r.risk_profile}로" not in block, "서버 낱말(moderate 등)이 화면 글에"
    html = APP.read_text(encoding="utf-8")
    for v in ("conservative", "moderate", "aggressive"):
        m = re.search(rf'<option value="{v}"[^>]*>([^<]+)</option>', html)
        assert m, f"선택 칸에 {v} 가 없다 — 결과 줄이 서버 낱말로 돌아간다"
        assert not re.search(r"[A-Za-z]{3,}", m.group(1)), f"선택 칸 {v} 글이 한국어가 아니다 — {m.group(1)!r}"


def test_first_plan_save_is_not_blocked_by_empty_preset_fields():
    """TC-RPL-02 · 처음 계획 저장 — 비어 있는 이탈률 · 현금흐름 칸은 보이는 고르기 값으로 채운다(저장 검사는 그대로)"""
    src = REBALANCE.read_text(encoding="utf-8")
    init = src[src.index("export function initRebalanceView()"):]
    loop = init[:init.index('on("rb-add", "click", addTarget);')]
    assert '[["rb-drift-preset", "rb-drift"], ["rb-cf-preset", "rb-cf-min"]]' in loop, "두 짝을 모두 본다"
    assert ('if ($(inputId) && $(inputId).value === "" && $(selectId)?.value !== "custom") $(inputId).value = $(selectId).value;'
            in loop), "빈 칸만 고르기 값으로 — 저장된 계획 값은 덮지 않는다"
    save = src[src.index("async function savePlan()"):src.index("/* ── 현황")]
    assert "every(Number.isFinite)" in save and "설정 금액과 이탈률을 입력하세요." in save, "저장 검사 규칙은 그대로(주인 코드)"
    html = APP.read_text(encoding="utf-8")
    for sel in ("rb-drift-preset", "rb-cf-preset"):
        m = re.search(rf'<select id="{sel}"[^>]*>\s*<option value="([^"]+)"', html)
        assert m and re.fullmatch(r"\d+(\.\d+)?", m.group(1)), f"{sel} 의 처음 고르기 값이 숫자가 아니면 빈 칸이 숫자로 안 채워진다"
