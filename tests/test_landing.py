"""TC-LND — 랜딩(로그인 전 첫 화면 · IA N11) · 2026-10-29 · 시안: Figma 「Qurious · 랜딩」 · 사용자 결정 ① ~ ④

1. 첫 주소 `/` — 로그인한 사람은 앱으로, 아닌 사람은 랜딩. `/index.html` 은 `/` 로 보내 판정을 한 곳에 둔다. (TC-LND-01)
2. 이어지는 곳 — 로그인 · 가입 · 약관 · 처리방침 링크가 있고, 개발 중 카드에는 「로그인하고 써 보기」 가 없다. (TC-LND-02)
3. 문구 — 옛 문구(금융 AI Agent · 설치 명령 · 기술 이름 · 자동매매 · 실시간)가 없고, 코인 · 대안자산은 「개발 중」 으로만, AI 채팅은 안 넣는다. (TC-LND-03)
4. 카드 — 한 번에 하나만 펼치고 aria-expanded 로 읽어 주며, 스크립트가 없으면 글이 모두 보인다. (TC-LND-04)
5. 인트로 — 누를 때까지 머문다(2026-10-29 개정 · 전에는 2.6초) · 건너뛰기 · Esc · 이 탭에서 한 번만 · 움직임 줄이기면 생략 · 인트로 중에도 로그인 · 가입 링크. (TC-LND-05)
6. 바깥 자원 — 허용 목록 밖 스타일 · 스크립트를 부르지 않는다(Tailwind CDN 은 걷었다). 서비스 이름과 고지는 brand.js 한 곳. (TC-LND-06)
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUB = ROOT / "public"
INDEX = (PUB / "index.html").read_text(encoding="utf-8")
JS = (PUB / "js" / "landing.js").read_text(encoding="utf-8")
CSS = (PUB / "css" / "landing.css").read_text(encoding="utf-8")
MAIN = (ROOT / "app" / "main.py").read_text(encoding="utf-8")


def _cards() -> list[str]:
    """index.html 의 카드(article.card) 네 덩어리."""
    return re.findall(r'<article class="card.*?</article>', INDEX, re.S)


def test_root_serves_landing_to_logged_out_and_redirects_logged_in_to_app():
    """TC-LND-01 · `/` 는 로그인한 사람을 앱으로, 아닌 사람에게 랜딩을 준다 · `/index.html` 은 `/` 로 보낸다 · 로그인 · 가입 화면은 그대로다."""
    block = MAIN.split('@app.get("/", include_in_schema=False)', 1)[1].split("@app.get(", 1)[0]
    assert "_logged_in(fin_session)" in block
    assert 'RedirectResponse(url="/app.html")' in block
    assert 'FileResponse(os.path.join(_public, "index.html"))' in block
    assert '"/login.html"' not in block, "예전처럼 로그인 화면으로 보내면 랜딩이 첫 화면이 아니다"
    idx = MAIN.split('@app.get("/index.html", include_in_schema=False)', 1)[1].split("@app.get(", 1)[0]
    assert 'RedirectResponse(url="/")' in idx and "_logged_in" not in idx
    # 로그인 · 가입 화면의 이미-로그인 판정은 그대로
    login = MAIN.split('@app.get("/login.html"', 1)[1].split("@app.get(", 1)[0]
    assert "_logged_in" in login and 'RedirectResponse(url="/app.html")' in login


def test_links_to_login_signup_terms_privacy_and_no_login_button_on_the_coming_soon_card():
    """TC-LND-02 · 로그인 · 가입 · 약관 · 처리방침이 이어지고, 개발 중 카드(04)에는 「로그인하고 써 보기」 가 없다(가입하기만)."""
    for href in ("/login.html", "/register.html", "/terms.html", "/privacy.html"):
        assert f'href="{href}"' in INDEX, href
    cards = _cards()
    assert len(cards) == 4
    for c in cards[:3]:
        assert 'href="/login.html">로그인하고 써 보기' in c and 'href="/register.html">가입하기' in c
    soon = cards[3]
    assert "card--soon" in soon and "개발 중" in soon
    assert "로그인하고 써 보기" not in soon and 'href="/login.html"' not in soon
    assert 'href="/register.html">가입하기' in soon
    # 상단 · 첫 영역 · 마무리 띠 어디서든 로그인과 가입으로 갈 수 있다
    assert INDEX.count('href="/register.html"') >= 6 and INDEX.count('href="/login.html"') >= 6


def test_copy_matches_the_service_and_the_terms_not_the_old_page():
    """TC-LND-03 · 옛 랜딩의 이름 · 개발자 안내 · 과장 표현이 없고, 약관이 말하는 것만 쓴다 · 코인 · 대안자산은 「개발 중」."""
    for old in ("금융 AI Agent", "docker compose", "localhost:8000", "Qdrant", "Ollama", "FastAPI", "자동매매", "실시간", "Mockup", "💹"):
        assert old not in INDEX, f"옛 문구가 남았다 — {old}"
    assert "채팅" not in INDEX, "AI 채팅은 소개에 넣지 않기로 했다(국외 전송 안내가 필요해져서 · 사용자 결정 ②)"
    assert "가상 계좌(초기 현금 1억 원)" in INDEX
    terms = (PUB / "js" / "terms.js").read_text(encoding="utf-8")
    assert "모의 계좌의 초기 현금은 1억 원" in terms, "소개의 1억 원은 약관에 있는 말이어야 한다"
    assert "한국투자증권" in INDEX and "(선택)" in INDEX and "실제 돈이 오가지 않으며 투자 권유가 아닙니다" in INDEX
    assert "개발 중인 기능입니다. 범위와 일정은 바뀔 수 있습니다." in INDEX
    assert INDEX.count("개발 중") == 2, "「개발 중」 은 네 번째 카드의 표시와 펼친 글 한 곳뿐이다"


def test_cards_open_one_at_a_time_and_stay_readable_without_scripts():
    """TC-LND-04 · 카드는 한 번에 하나만 펼치고 aria-expanded 를 갱신한다 · 스크립트가 없으면 접지 않는다(글이 모두 보인다)."""
    for c in _cards():
        head = re.search(r'<button class="card-head"[^>]*>', c).group(0)
        assert 'aria-expanded="false"' in head and 'type="button"' in head
        pid = re.search(r'aria-controls="([^"]+)"', head).group(1)
        assert f'id="{pid}"' in c, f"aria-controls 가 가리키는 칸이 없다 — {pid}"
    assert "cards.forEach((c) => setOpen(c, false))" in JS and 'setAttribute("aria-expanded"' in JS
    assert "!card.classList.contains" in JS, "펼친 카드를 다시 누르면 접힌다"
    # 접는 규칙은 html.js 아래에서만 — 스크립트가 없으면(no-js) 패널이 그냥 보인다
    assert re.search(r"\.js \.panel\s*\{[^}]*visibility:\s*hidden", CSS)
    assert not re.search(r"(?<!\.js )\.panel\s*\{[^}]*visibility:\s*hidden", CSS)
    assert 'class="no-js"' in INDEX and 'classList.remove("no-js")' in INDEX


def test_intro_is_short_skippable_once_per_tab_and_off_for_reduced_motion():
    """TC-LND-05 · 인트로 — 누를 때까지 머문다(자동 넘김 없음 · 안내 글 · 머무는 동안 은은한 움직임) · 건너뛰기 · 화면 누르기 · Esc · 이 탭에서 한 번만 · 움직임 줄이기면 생략 · 인트로 중에도 로그인 · 가입."""
    # 2026-10-29 사용자 피드백 — 2.6초 뒤 저절로 넘어가던 것을 걷고, 누를 때까지 머문다
    assert "INTRO_MS" not in JS and "setTimeout(endIntro" not in JS, "인트로가 저절로 넘어가면 안 된다"
    assert 'class="intro-hint">화면을 눌러 시작' in INDEX
    assert "@keyframes intro-breathe" in CSS and re.search(r"\.intro-logo\s*\{[^}]*intro-breathe[^}]*infinite", CSS)
    assert re.search(r"\.intro-hint\s*\{[^}]*intro-blink[^}]*infinite", CSS)
    # 소개 화면에 머무는 동안의 움직임 — 장식 차트(읽는 도구가 읽지 않게 aria-hidden) · 선은 반복해서 그리고 끝점은 깜빡인다 · 숫자 · 시세를 흉내 내지 않는다
    chart = re.search(r'<svg class="hero-chart".*?</svg>', INDEX, re.S).group(0)
    assert 'aria-hidden="true"' in chart and "<text" not in chart, "장식 차트에 숫자 · 글자를 넣지 않는다(시세로 읽히면 안 된다)"
    assert re.search(r"\.hero-chart-line\s*\{[^}]*hero-draw[^}]*infinite", CSS)
    assert re.search(r"\.hero-chart-dot\s*\{[^}]*hero-dot[^}]*infinite", CSS)
    # 움직임 줄이기에서는 선이 다 그려진 채 보여야 한다 — 기본(애니메이션 없음)에서 offset 을 숨기지 않는다
    assert not re.search(r"\.hero-chart-line\s*\{[^}]*stroke-dashoffset\s*:\s*1", CSS)
    assert "prefers-reduced-motion: reduce" in INDEX and 'getItem("qurious-intro-seen")' in INDEX
    assert 'const SEEN_KEY = "qurious-intro-seen";' in JS and "sessionStorage.setItem(SEEN_KEY" in JS
    assert 'id="intro-skip"' in INDEX and "건너뛰기" in INDEX
    assert '"Escape"' in JS and 'intro.addEventListener("click", skip)' in JS
    intro = INDEX.split('id="intro"', 1)[1].split("<header", 1)[0]
    assert 'href="/login.html"' in intro and 'href="/register.html"' in intro, "인트로 중에도 로그인 · 가입이 눌려야 한다"
    assert 'role="dialog"' in INDEX and "aria-label" in intro
    # 인트로는 저장소를 못 써도 깨지지 않고(try/catch) 움직임 줄이기 설정이면 나머지 움직임도 끈다
    assert "catch (e)" in INDEX and "catch {" in JS
    assert re.search(r"@media \(prefers-reduced-motion: reduce\)\s*\{[^}]*animation:\s*none", CSS)
    assert ".intro-on .intro { display: flex; }" in CSS, "인트로는 html.intro-on 일 때만 보인다(기본은 숨김)"


def test_no_outside_resources_except_the_allowed_font_and_name_comes_from_brand_js():
    """TC-LND-06 · 바깥 스타일은 허용 목록(글꼴 한 줄)뿐 · Tailwind CDN 없음 · 서비스 이름 · 고지는 brand.js 의 자리표시."""
    hosts = set(re.findall(r'https?://([^/"\']+)', INDEX))
    assert hosts <= {"cdn.jsdelivr.net", "cdnjs.cloudflare.com"}, hosts
    assert "tailwind" not in INDEX.lower()
    assert "@import" not in CSS and "http" not in CSS
    assert 'src="/js/brand.js"' in INDEX
    for key in ("name", "tagline", "notice"):
        assert f'data-brand="{key}"' in INDEX
    brand = (PUB / "js" / "brand.js").read_text(encoding="utf-8")
    assert 'name: "Qurious"' in brand and "투자 자문이 아닌 정보 제공 목적입니다." in INDEX
    assert not re.search(r"googletagmanager|google-analytics|gtag\(|hotjar|fbq\(", INDEX)
