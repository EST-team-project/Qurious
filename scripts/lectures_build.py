"""금융 강의 파일 만들기 — 통합본 사본(rag-lab/)의 강의 · 교재를 앱이 싣는 모양으로 public/lectures/ 에 옮긴다.

왜 스크립트인가
---------------
`rag-lab/` 은 원본과 같아야 하는 사본이라 고치지 않는다(`raglab_scan --check` 가 본다). 앱이 쓰는 판은
거기서 만들고, **무엇을 바꿨는지가 이 파일 한 곳에** 있게 한다 — 원본이 바뀌면 다시 돌리면 된다.
public/lectures/ 의 파일은 손으로 고치지 않는다(다음 빌드가 덮어쓴다).

무엇을 옮기나
-------------
- 강의 4일치  rag-lab/frontend/days/01~04.html · days/assets/ 전부 · ../hangul-scale.css · ../assets/ 의 두 스크립트
- 교재 단원  rag-lab/data/curriculum/unit01~10.md · manifest.json · 본문이 가리키는 그림 19장
  (6~9단원은 강의 4일치를 글로 옮긴 것이라 주제 화면은 강의를 싣는다 — 파일은 그대로 옮겨 둔다)
- 목록 파일  catalog.json — 강의실 화면이 읽는 과정 · 단원 목록과 절 · 용어 수(빌드가 센다)

무엇을 바꾸나
-------------
강의 HTML · 강의 스크립트
  ① 시세 주소: /market/… → /api/lectures/market/… · /health → /api/health · window.API_BASE = "/api/lectures"
  ② 앱 안에 실릴 때(iframe): 강의 사이트 자체의 머리 줄 · 학습 서랍 · 일차 목차 · 제목 줄을 숨긴다
     — 앱의 왼쪽 메뉴와 주제 화면의 머리가 같은 일을 한다
  ③ 일차 사이 링크(02.html 등) · 통합본 화면 링크(/?view=…)는 앱 화면 이동으로(부모 창에 메시지를 보낸다)
교재 md
  ④ 그림 주소 /images/… · /image/… · image-3.png → img/<이름> (뒤의 ?v= 는 뗀다)

사용
----
    python scripts/lectures_build.py            # 만든다(덮어쓴다)
    python scripts/lectures_build.py --check    # 지금 public/lectures 가 빌드 결과와 같은가 — 다르면 종료 코드 1
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "rag-lab"
DST = ROOT / "public" / "lectures"

DAYS = ("01", "02", "03", "04")
UNITS = tuple(f"{i:02d}" for i in range(1, 11))

HEAD_SNIPPET = """<script>/* Qurious: 시세 주소 · 앱 안 싣기 — scripts/lectures_build.py 가 넣음 */
window.API_BASE = "/api/lectures";
(function () {
  var embed = /[?&]embed=1/.test(location.search);
  try { embed = embed || window.top !== window; } catch (e) { embed = true; }
  if (embed) document.documentElement.classList.add("q-embed");
})();
</script>
<style>/* 앱 안에서는 강의 사이트 자체의 머리 줄 · 학습 서랍 · 일차 목차 · 제목 줄을 숨긴다 — 앱 화면이 같은 일을 한다 */
.q-embed .day-appbar, .q-embed .day-backdrop, .q-embed .day-offcanvas, .q-embed body > nav, .q-embed .lesson-head { display: none !important; }
/* 숨긴 머리 줄 자리의 위 여백(글 36 + 목록 20px)을 줄인다 */
.q-embed main#app > article { padding-top: 8px !important; }
.q-embed .lesson-list { margin-top: 0 !important; }
</style>
"""

BODY_SNIPPET = """<script>/* Qurious: 앱 안에 실렸을 때 일차 · 화면 링크를 앱 화면 이동으로 — scripts/lectures_build.py 가 넣음 */
(function () {
  if (!document.documentElement.classList.contains("q-embed")) return;
  document.addEventListener("click", function (e) {
    var a = e.target && e.target.closest ? e.target.closest("a[href]") : null;
    if (!a) return;
    var h = a.getAttribute("href") || "";
    var day = h.match(/^(0[1-4])\\.html(#[\\w-]*)?$/);
    var view = h.match(/^\\/\\?view=([a-z-]+)/);
    if (!day && !view && h !== "index.html") return;
    e.preventDefault();
    parent.postMessage({ type: "q-lecture-nav", day: day ? day[1] : null, hash: day && day[2] ? day[2] : "",
                         view: view ? view[1] : (h === "index.html" ? "index" : null) }, location.origin);
  }, true);
})();
</script>
"""

# 시세 주소 바꾸기 — 따옴표 · 백틱 바로 뒤의 /market/ 만(window.API_BASE 를 앞에 붙이는 곳은 API_BASE 가 맡는다)
_MARKET = re.compile(r"""(["'`])/market/""")
_HEALTH = re.compile(r"""(["'`])/health(["'`?])""")
# 강의 2일차 본문이 window.API_BASE 를 빈 값으로 다시 정한다 — 머리에 넣은 값이 이기게 「없을 때만」 으로 바꾼다
_API_BASE_RESET = re.compile(r"""window\.API_BASE\s*=\s*(['"])\1""")
# 강의 3일차의 국채 사료 그림 — 통합본 서버가 e뮤지엄에서 대신 받아 주던 주소를 우리 API 로
_BOND_IMAGE = ('src="/learning/historic-bond-image"', 'src="/api/lectures/historic-bond-image"')
# 한글 글꼴 — Pretendard 저장소 구조가 바뀌어 옛 경로가 404 다(2026-10-01 확인 · 새 경로 200)
_FONT_URL = ("pretendard@v1.3.9/dist/web/variable/woff2/PretendardVariable.woff2",
             "pretendard@v1.3.9/packages/pretendard/dist/web/variable/woff2/PretendardVariable.woff2")
# 강의 페이지가 ../assets/ 로 부르는 파일 — 목록을 하드코딩하지 않고 페이지에서 읽는다
_PARENT_ASSET = re.compile(r"""(?:src|href)="\.\./assets/([\w.\-]+?)(?:\?[^"]*)?\"""")
# 교재 그림 주소
_IMG = re.compile(r"""(!\[[^\]]*\]\()(/images/|/image/|)([\w.\-]+\.(?:png|jpe?g|gif|svg|webp))(\?[^)\s]*)?(\))""")


def _patch_api(text: str) -> tuple[str, int]:
    text, n1 = _MARKET.subn(r"\1/api/lectures/market/", text)
    text, n2 = _HEALTH.subn(r"\1/api/health\2", text)
    text, n3 = _API_BASE_RESET.subn("window.API_BASE = window.API_BASE || ''", text)
    return text, n1 + n2 + n3


def _patch_day(text: str, name: str) -> tuple[str, dict]:
    if "<head>" not in text or "</body>" not in text:
        raise SystemExit(f"{name}: <head> 또는 </body> 가 없다 — 원본 모양이 바뀌었다. 빌드 규칙을 다시 본다")
    text, n_api = _patch_api(text)
    n_api += text.count(_BOND_IMAGE[0])
    text = text.replace(*_BOND_IMAGE)
    text = text.replace("<head>", "<head>\n" + HEAD_SNIPPET, 1)
    i = text.rfind("</body>")
    text = text[:i] + BODY_SNIPPET + text[i:]
    sections = len(re.findall(r"<h2[\s>]", text))
    terms = len(re.findall(r"glossary-item", text))
    return text, {"api_rewrites": n_api, "sections": sections, "terms": terms}


def _questions(headings: list[str], n: int = 4) -> list[str]:
    """강의실 카드에 보일 「이 강의에서 답하는 질문」 — 물음표로 끝나는 절 제목을 앞에서부터, 모자라면 나머지 제목으로.

    60자가 넘는 「제목」 은 뺀다 — 원본 md 에 본문 문장이 제목 표시(##)로 잘못 들어간 줄이 있다(4단원).
    """
    headings = [h for h in headings if 0 < len(h) <= 60]
    asks = [h for h in headings if h.endswith("?")]
    rest = [h for h in headings if not h.endswith("?")]
    return (asks + rest)[:n]


def _index_blurb(front: Path, day: str, title: str) -> str:
    """과정 목록 페이지(days/index.html)의 그 일차 한 줄 설명 — 「01 선물과 옵션 <설명> 학습 시작」 모양.

    제목에 띄어쓰기가 있어(「선물과 옵션」 · 「펀드 · ETF」) 그 일차 페이지의 실제 제목으로 잘라 낸다. 페이지 위쪽 메뉴에도
    같은 「01 선물과 옵션」 이 있어서, 「학습 시작」 앞 덩어리마다 제목 뒤 글을 잘라 **가장 짧은 것**(카드 설명 한 줄)을 고른다.
    """
    text = re.sub(r"<[^>]+>", " ", (front / "days" / "index.html").read_text(encoding="utf-8"))
    text = re.sub(r"\s+", " ", text)
    key = f"{day} {title} "
    tails = [chunk[chunk.rfind(key) + len(key):].strip(" →") for chunk in text.split("학습 시작")[:-1] if key in chunk]
    return min(tails, key=len) if tails else ""


def _day_meta(text: str, blurb: str = "") -> dict:
    title = re.search(r"<h1>([^<]+)</h1>", text)
    head = re.search(r'<header class="lesson-head">(.*?)</header>', text, re.S)   # 제목 줄 안에서만 부제를 찾는다
    sub = re.search(r"<p>([^<]+)</p>", head.group(1)) if head else None
    heads = [re.sub(r"<[^>]+>", "", h).strip() for h in re.findall(r"<h2[^>]*>(.*?)</h2>", text, re.S)]
    return {"title": title.group(1).strip() if title else "", "subtitle": sub.group(1).strip() if sub else blurb,
            "questions": _questions([h for h in heads if h])}


def _unit_headings(text: str) -> list[str]:
    """교재 단원의 절 제목 — 「원문: …」 줄은 빼고 앞의 「1. 」 같은 번호는 뗀다."""
    out = []
    for h in re.findall(r"^## (.+)$", text, re.M):
        h = h.strip()
        if h.startswith("원문"):
            continue
        out.append(re.sub(r"^\d+\.\s*", "", h))
    return out


def _image_sources() -> dict[str, Path]:
    """교재가 가리키는 그림 이름 → 사본 안의 실제 파일."""
    out: dict[str, Path] = {}
    for base in (SRC / "frontend" / "analysis" / "images", SRC / "data" / "image", SRC / "data"):
        if base.is_dir():
            for p in base.iterdir():
                if p.is_file():
                    out.setdefault(p.name, p)
    return out


def build() -> tuple[dict[str, bytes], dict]:
    """만들 파일 {public/lectures 아래 경로: 내용} 과 요약."""
    files: dict[str, bytes] = {}
    report: dict = {"days": {}, "units": {}, "images": 0, "assets": 0}
    front = SRC / "frontend"

    # 강의 4일치
    catalog_days = []
    for d in DAYS:
        raw = (front / "days" / f"{d}.html").read_text(encoding="utf-8")
        text, info = _patch_day(raw, f"days/{d}.html")
        files[f"days/{d}.html"] = text.encode("utf-8")
        report["days"][d] = info
        meta = _day_meta(raw)
        blurb = _index_blurb(front, d, meta["title"])
        if not meta["subtitle"]:
            meta["subtitle"] = blurb
        catalog_days.append({"day": d, **meta, "blurb": blurb,
                             "file": f"days/{d}.html", "sections": info["sections"], "terms": info["terms"]})
    for p in sorted((front / "days" / "assets").rglob("*")):
        if not p.is_file():
            continue
        rel = "days/assets/" + p.relative_to(front / "days" / "assets").as_posix()
        data = p.read_bytes()
        if p.suffix == ".js":
            text, n = _patch_api(data.decode("utf-8"))
            if n:
                report.setdefault("asset_api_rewrites", {})[rel] = n
            data = text.encode("utf-8")
        files[rel] = data
        report["assets"] += 1
    files["hangul-scale.css"] = (front / "hangul-scale.css").read_text(encoding="utf-8").replace(*_FONT_URL).encode("utf-8")
    parent_assets = sorted({m for d in DAYS for m in _PARENT_ASSET.findall((front / "days" / f"{d}.html").read_text(encoding="utf-8"))})
    for name in parent_assets:
        files[f"assets/{name}"] = (front / "assets" / name).read_bytes()
    report["parent_assets"] = parent_assets

    # 교재 단원
    manifest = json.loads((SRC / "data" / "curriculum" / "manifest.json").read_text(encoding="utf-8"))
    images = _image_sources()
    wanted: set[str] = set()
    catalog_units = []
    for u in manifest["units"]:
        uid = f"{int(u['id']):02d}"
        text = (SRC / "data" / "curriculum" / f"unit{uid}.md").read_text(encoding="utf-8")

        def _img(m: re.Match) -> str:
            wanted.add(m.group(3))
            return f"{m.group(1)}img/{m.group(3)}{m.group(5)}"

        text, n_img = _IMG.subn(_img, text)
        files[f"curriculum/unit{uid}.md"] = text.encode("utf-8")
        sections = len(re.findall(r"^## ", text, re.M))
        report["units"][uid] = {"images": n_img, "sections": sections}
        catalog_units.append({"id": int(u["id"]), "title": u["title"], "goal": u.get("goal", ""),
                              "file": f"curriculum/unit{uid}.md", "sections": sections,
                              "day": u.get("domainDay"), "labs": u.get("labs", []),
                              "questions": _questions(_unit_headings(text))})
    missing = sorted(n for n in wanted if n not in images)
    if missing:
        raise SystemExit(f"교재 그림을 사본에서 못 찾았다: {missing}")
    for n in sorted(wanted):
        files[f"curriculum/img/{n}"] = images[n].read_bytes()
    report["images"] = len(wanted)
    files["curriculum/manifest.json"] = (SRC / "data" / "curriculum" / "manifest.json").read_bytes()

    catalog = {
        "about": "scripts/lectures_build.py 가 만든다 — 손으로 고치지 않는다",
        "days": catalog_days,
        "units": catalog_units,
    }
    files["catalog.json"] = (json.dumps(catalog, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
    return files, report


def _current() -> dict[str, bytes]:
    if not DST.is_dir():
        return {}
    return {p.relative_to(DST).as_posix(): p.read_bytes() for p in DST.rglob("*") if p.is_file()}


# 글 파일은 줄바꿈을 접고 견준다 — Windows 의 git(core.autocrlf=true)은 저장소의 LF 파일을 꺼낼 때 CRLF 로
# 바꾼다. 빌드는 글을 read_text 로 읽어 LF 로 쓰므로, 한 번 git 으로 다시 꺼낸 public/lectures 는
# 내용이 같아도 바이트가 다르다(2026-10-02 · 브랜치를 옮긴 뒤 TC-LC-01 이 실패한 원인). 그림 같은
# 바이너리는 그대로 견준다.
_TEXT_SUFFIXES = {".html", ".css", ".js", ".md", ".json", ".svg", ".txt"}


def same_content(rel: str, a: bytes | None, b: bytes | None) -> bool:
    """두 판이 같은가 — 글 파일은 CRLF 와 LF 를 같은 것으로 본다."""
    if a is None or b is None:
        return a is b
    if Path(rel).suffix.lower() in _TEXT_SUFFIXES:
        return a.replace(b"\r\n", b"\n") == b.replace(b"\r\n", b"\n")
    return a == b


def main(argv: list[str] | None = None) -> int:
    # git bash(mintty) · 한국어 Windows 콘솔은 표준출력이 cp949 다 → 「—」 한 글자에서 죽는다. 도움말보다 먼저 맞춘다.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="금융 강의 파일 만들기 (rag-lab/ → public/lectures/)")
    ap.add_argument("--check", action="store_true", help="쓰지 않고 지금 파일이 빌드 결과와 같은지만 본다")
    a = ap.parse_args(argv)
    files, report = build()
    now = _current()
    changed = sorted(k for k, v in files.items() if not same_content(k, now.get(k), v))
    extra = sorted(k for k in now if k not in files)
    if a.check:
        if changed or extra:
            print(f"다르다 — 바뀜 {len(changed)} · 남는 파일 {len(extra)}")
            for k in (changed + extra)[:20]:
                print("  ", k)
            return 1
        print(f"같다 — 파일 {len(files)}")
        return 0
    for k in changed:
        p = DST / k
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(files[k])
    for k in extra:
        (DST / k).unlink()
    total = sum(len(v) for v in files.values())
    print(f"public/lectures — 파일 {len(files)} · {total / 1e6:.1f} MB · 바뀜 {len(changed)} · 지움 {len(extra)}")
    for d, info in report["days"].items():
        print(f"  강의 {d}일차  절 {info['sections']} · 용어 {info['terms']} · 시세 주소 바꿈 {info['api_rewrites']}")
    for rel, n in report.get("asset_api_rewrites", {}).items():
        print(f"  {rel}  시세 주소 바꿈 {n}")
    print(f"  강의 부속 파일 {report['assets']} · 위 폴더 스크립트 {', '.join(report['parent_assets'])}")
    print(f"  교재 단원 {len(report['units'])} · 교재 그림 {report['images']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
