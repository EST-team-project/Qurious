"""TC-CTR — 글자 대비 지킴이(S166 · 사용자 피드백 10-30 「다크 모드로 바꿨을 때 글씨가 흐릿하게 보이지 않게」)

조사(배경조사/2026-10-30-다크모드-글자-대비)에서 앱의 보조 글(`--text-mute #94a3b8`)이 라이트에서도 흰 바탕 **2.56:1** 이고
Tailwind `text-slate-300/400`(약 190곳)이 어두운 테마용 글자색이라 밝은 바탕에서 거의 안 보임을 확인했다. 고친 내용이 다시 무너지지 않게
**숫자로** 지킨다(WCAG 1.4.3 AA — 글자 4.5:1).

1. 보조 글색 토큰이 그 화면의 모든 바탕에서 4.5:1 이상 — 앱 · 랜딩 · API 문서 · 학습. (TC-CTR-01)
2. 라이트만 만든 화면은 `color-scheme: only light` 를 선언하고, 다크를 가진 약관 · 처리방침은 `light dark`. (TC-CTR-02)
3. 앱의 Tailwind 글자색 클래스 가운데 밝은 바탕에서 안 보이는 것들(slate 200 ~ 500)은 토큰으로 되돌려 있고, 새 미지정 글자색 클래스가 늘지 않는다. (TC-CTR-03)
4. 약관 · 처리방침 — 라이트 · 다크 보조 글 모두 4.5:1 이상. (TC-CTR-04)
5. 밝은 바탕 위에 하드코딩된 보조 글색(데이터 안내 화면)이 토큰을 쓴다. (TC-CTR-05)
"""
from __future__ import annotations

import re
from pathlib import Path

PUB = Path(__file__).resolve().parents[1] / "public"
AA = 4.5


def _lin(c: float) -> float:
    c /= 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def _lum(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def ratio(fg: str, bg: str) -> float:
    a, b = _lum(fg), _lum(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


def tokens(text: str) -> dict[str, str]:
    """첫 선언만 — 같은 이름을 뒤에서 다시 선언해도 :root 의 첫 값을 본다."""
    out: dict[str, str] = {}
    for m in re.finditer(r"--([a-z0-9-]+)\s*:\s*(#[0-9a-fA-F]{3,6})\b", text):
        out.setdefault(m.group(1), m.group(2).lower())
    return out


def _read(rel: str) -> str:
    return (PUB / rel).read_text(encoding="utf-8")


def test_text_mute_token_meets_aa_on_every_surface():
    """TC-CTR-01 · `--text-mute` 가 그 화면의 모든 바탕(surf · surf2 · surf3 · bg)에서 4.5:1 이상이다."""
    for rel in ("css/app.css", "css/landing.css", "api-docs/api-docs.css", "learn/learn.css"):
        tok = tokens(_read(rel))
        assert "text-mute" in tok, f"{rel} 에 --text-mute 가 없다"
        surfaces = {k: tok[k] for k in ("surf", "surf2", "surf3", "bg") if k in tok}
        assert surfaces, f"{rel} 에 바탕 토큰이 없다"
        for name, color in surfaces.items():
            r = ratio(tok["text-mute"], color)
            assert r >= AA, f"{rel}: --text-mute {tok['text-mute']} on --{name} {color} = {r:.2f} (< {AA})"
    # 옛 값으로 되돌아가지 않는다 — 흰 바탕 2.56:1 이었다
    assert tokens(_read("css/app.css"))["text-mute"] != "#94a3b8"


def test_light_only_pages_declare_color_scheme():
    """TC-CTR-02 · 라이트만 만든 화면은 only light(브라우저 자동 다크의 공식 옵트아웃) · 다크를 가진 약관 · 처리방침은 light dark."""
    only_light = ("app.html", "index.html", "login.html", "register.html", "api-docs/index.html", "learn/index.html")
    for rel in only_light:
        assert re.search(r'<meta name="color-scheme" content="only light"\s*/?>', _read(rel)), f"{rel} 에 color-scheme only light 가 없다"
    for rel in ("terms.html", "privacy.html"):
        html = _read(rel)
        assert re.search(r'<meta name="color-scheme" content="light dark"\s*/?>', html), f"{rel} 에 color-scheme light dark 가 없다"
        assert "prefers-color-scheme: dark" in html, f"{rel} 의 다크 선언이 사라졌다 — 메타만 남으면 안 된다"


def test_tailwind_dark_theme_text_classes_are_mapped_and_not_growing():
    """TC-CTR-03 · text-slate-200 ~ 500(어두운 테마용 · 밝은 바탕에서 1.5 ~ 4:1)은 app.css 에서 토큰으로 되돌려 있고, 다른 팔레트의 옅은 글자색이 새로 들어오지 않는다."""
    css = _read("css/app.css")
    assert re.search(r"body \.text-slate-200,\s*body \.text-slate-300\s*\{\s*color:\s*var\(--text-dim\)", css)
    assert re.search(r"body \.text-slate-400,\s*body \.text-slate-500\s*\{\s*color:\s*var\(--text-mute\)", css)
    # 토큰이 되돌려 놓은 색의 대비(본문급 · 보조급) — 가장 어두운 앱 바탕 surf3 에서도 AA
    tok = tokens(css)
    assert ratio(tok["text-dim"], tok["surf3"]) >= AA and ratio(tok["text-mute"], tok["surf3"]) >= AA
    # 새 글자색 클래스 — 매핑에 안 걸리는 옅은 색(다른 팔레트 · slate 100)이 늘면 같은 흐림이 되풀이된다
    used = (PUB / "app.html").read_text(encoding="utf-8") + "".join(p.read_text(encoding="utf-8") for p in (PUB / "js").glob("*.js"))
    pale = sorted(set(re.findall(r"(?<![\w-])text-(?:gray|zinc|neutral|stone)-(?:50|100|200|300|400|500)\b|(?<![\w-])text-slate-(?:50|100)\b", used)))
    assert not pale, f"밝은 바탕에서 안 보이는 글자색 클래스가 새로 들어왔다 — {pale} (토큰 --text-dim · --text-mute 를 쓴다)"


def test_terms_and_privacy_tokens_meet_aa_in_light_and_dark():
    """TC-CTR-04 · 약관 · 처리방침의 보조 글(mute · faint)이 라이트 · 다크 모두 자기 바탕(bg · card)에서 4.5:1 이상."""
    for rel in ("terms.html", "privacy.html"):
        html = _read(rel)
        light_block = re.search(r":root\s*\{([^}]*)\}", html).group(1)
        dark_block = re.search(r"prefers-color-scheme: dark\)\s*\{\s*:root\s*\{([^}]*)\}", html).group(1)
        for label, block in (("라이트", light_block), ("다크", dark_block)):
            tok = tokens(block)
            for fg in ("mute", "faint"):
                for bg in ("bg", "card"):
                    r = ratio(tok[fg], tok[bg])
                    assert r >= AA, f"{rel} {label}: --{fg} {tok[fg]} on --{bg} {tok[bg]} = {r:.2f} (< {AA})"


def test_dataguide_light_surface_text_uses_the_token():
    """TC-CTR-05 · 데이터 안내 화면의 밝은 바탕 위 보조 글(눈금 · 작은 설명 · 이름 칸)이 하드코딩 #94a3b8(2.5:1)이 아니라 토큰을 쓴다."""
    css = _read("css/dataguide.css")
    for selector in (".dg-l0", ".dg-axis", ".dg-d-tile small", ".dg-dev dt"):
        rule = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css).group(1)
        assert "var(--text-mute" in rule and "#94a3b8" not in rule, f"{selector} 가 하드코딩된 옅은 색을 쓴다"
