"""발표 자료 한 파일 판 만들기 — 덱 HTML 이 부르는 그림 · 포스터 · 영상 · 글꼴을 HTML 한 파일 안에 넣는다.

왜: 발표 PC 가 바뀌어 HTML 한 파일만 옮겨도 영상 · 그림이 모두 보여야 한다(2026-10-21 사용자).
    원본 덱은 `그림/` · `../../영상/파일/발표/` 를 상대 경로로 불러, HTML 만 옮기면 그림 · 영상이 빈 칸이 된다.

무엇을 넣나:
  - 그림(`<img src>` · 인라인 `url(...)`) · 영상 포스터 → `data:` 주소(base64). 같은 그림을 여러 번 부르면
    한 번만 넣고 CSS 변수(`--emb-N`)로 나눠 쓴다(파일 크기).
  - 영상(mp4) → `<script type="text/plain">` 안의 base64 → 페이지를 연 뒤 하나씩 Blob 주소로 풀어 `video.src` 에 넣는다.
    data: 주소를 video 에 바로 넣지 않는 까닭: 브라우저마다 주소 길이 한도 · 되감기(seek) 동작이 달라서.
    풀지 못하면 덱의 원래 「영상 없음」 칸(`.nofile`)을 그대로 쓴다(말없이 빈 칸이 되지 않게).
  - 글꼴 → 덱에 쓰인 글자만 뽑은 Noto Sans KR 가변 글꼴(woff2 · SIL OFL 1.1 — 문서에 넣어 배포 가능)을
    `@font-face` 로 넣고 구글 글꼴 링크는 뺀다. 인터넷이 없는 PC 에서도 같은 글꼴이어야 1920×1080 장의
    줄바꿈이 원본과 같다(글꼴이 바뀌면 넘칠 수 있다). 글꼴 파일이 없으면 구글 링크를 그대로 두고 알린다.

고치는 원본은 `발표자료-원본.html`(상대 경로 그대로 · 작은 파일)이고, 발표 · 배포용 `발표자료.html` 은 이 도구가
만든 결과다(2026-10-21 사용자 「발표자료.html 만 내려받아도 영상 · 그림이 다 보여야」). 결과를 손으로 고치지 않고
원본을 고친 뒤 다시 만든다 — 같은 원본 · 같은 그림이면 같은 결과(만든 시각을 넣지 않는다).

쓰는 법(저장소 뿌리에서):
  python tools/deck/bundle_deck.py                       # docs/2차/발표/발표자료-원본.html → 같은 폴더 발표자료.html
  python tools/deck/bundle_deck.py --src <원본> --out <경로>  # 다른 덱 · 다른 곳에 쓰기
  python tools/deck/bundle_deck.py --check               # 쓰지 않고 부르는 파일 · 예상 크기만
  python tools/deck/bundle_deck.py --font <ttf|otf>      # 다른 글꼴 파일(기본: Windows 의 NotoSansKR-VF.ttf)
  python tools/deck/bundle_deck.py --no-font             # 글꼴은 넣지 않음(구글 링크 그대로)
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import mimetypes
import os
import re
import sys
from pathlib import Path
from urllib.parse import unquote

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SRC = ROOT / "docs" / "2차" / "발표" / "발표자료-원본.html"
DEFAULT_OUT = ROOT / "docs" / "2차" / "발표" / "발표자료.html"
DEFAULT_FONT_CANDIDATES = [
  Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "NotoSansKR-VF.ttf",
  Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Windows" / "Fonts" / "NotoSansKR-VF.ttf",
]
FONT_FAMILY = "Noto Sans KR"
# GitHub 는 50 MiB 넘는 파일에 경고 · 100 MiB 넘으면 거부 — 저장소에 담을지 판단할 때 쓴다
GITHUB_WARN = 50 * 2**20
GITHUB_LIMIT = 100 * 2**20

MIME = {
  ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
  ".svg": "image/svg+xml", ".webp": "image/webp", ".mp4": "video/mp4", ".webm": "video/webm",
}
SKIP = ("http:", "https:", "data:", "blob:", "#", "//", "mailto:", "javascript:")

VIDEO_TAG = re.compile(r"<video\b[^>]*>", re.I)
ATTR = re.compile(r'(\s)(src|poster)="([^"]+)"', re.I)
CSS_URL = re.compile(r"""url\(\s*(['"]?)([^'")]+)\1\s*\)""", re.I)
GOOGLE_FONT_LINK = re.compile(r'[ \t]*<link\b[^>]*fonts\.(?:googleapis|gstatic)\.com[^>]*>\r?\n?', re.I)
MISSING_DIV = re.compile(r'(<div class="missing">)(.*?)(</div>)', re.S)


def is_local(ref: str) -> bool:
  return not ref.strip().lower().startswith(SKIP)


def note_skip(stats: dict, ref: str) -> None:
  """바깥 주소(http · https)만 짧게 남긴다 — 이미 넣은 data: 주소는 세지 않는다."""
  if ref.strip().lower().startswith(("http:", "https:", "//")):
    stats["skipped"].append(ref[:120])


def resolve(base: Path, ref: str) -> Path:
  return (base / unquote(ref.split("#")[0].split("?")[0])).resolve()


def mime_of(p: Path) -> str:
  return MIME.get(p.suffix.lower()) or mimetypes.guess_type(p.name)[0] or "application/octet-stream"


def data_uri(p: Path) -> str:
  return f"data:{mime_of(p)};base64," + base64.b64encode(p.read_bytes()).decode("ascii")


def font_face_css(font_path: Path, text: str) -> tuple[str, int, int]:
  """덱에 쓰인 글자만 뽑은 woff2 를 @font-face 글로. 돌려줌: (CSS, 글자 수, woff2 바이트)."""
  from fontTools import subset  # 가져오기를 여기서 — 글꼴을 안 넣을 때는 fonttools 가 없어도 된다
  from fontTools.ttLib import TTFont

  chars = sorted(set(text) | set(" 0123456789"))
  opts = subset.Options()
  opts.flavor = "woff2"
  opts.layout_features = ["*"]
  opts.name_IDs = ["*"]          # 이름 · 라이선스 표(OFL 고지)를 지킨다
  opts.name_languages = ["*"]
  opts.notdef_outline = True
  opts.glyph_names = False
  # recalcTimestamp=False — 저장할 때 head.modified 에 지금 시각을 넣지 않게(같은 원본이면 같은 결과)
  font = TTFont(str(font_path), recalcTimestamp=False)
  axes = [a.axisTag for a in font["fvar"].axes] if "fvar" in font else []
  sub = subset.Subsetter(options=opts)
  sub.populate(text="".join(chars))
  sub.subset(font)
  buf = io.BytesIO()
  font.flavor = "woff2"
  font.save(buf)
  woff2 = buf.getvalue()
  weight = "100 900" if "wght" in axes else "400"
  css = (
    "@font-face { font-family: '" + FONT_FAMILY + "'; font-style: normal; font-weight: " + weight + "; "
    "font-display: block; src: url(data:font/woff2;base64," + base64.b64encode(woff2).decode("ascii") + ") format('woff2'); }"
  )
  return css, len(chars), len(woff2)


LOADER_JS = r"""
<script>
/* 한 파일 판 — 파일 안의 영상(base64)을 Blob 주소로 풀어 넣는다. 하나씩 차례로(처음 화면을 막지 않게). */
(() => {
  const vids = [...document.querySelectorAll('video[data-embed]')];
  const fail = (v) => { const w = v.closest('.video-wrap'); if (w) w.classList.add('nofile'); };
  const one = (v) => {
    const el = document.getElementById(v.dataset.embed);
    if (!el) return fail(v);
    try {
      const bin = atob(el.textContent.replace(/\s+/g, ''));
      const bytes = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
      v.src = URL.createObjectURL(new Blob([bytes], { type: el.dataset.mime || 'video/mp4' }));
      el.textContent = '';
    } catch (e) { fail(v); }
  };
  let k = 0;
  const step = () => { if (k < vids.length) { one(vids[k++]); setTimeout(step, 0); } };
  if (document.readyState === 'loading') addEventListener('DOMContentLoaded', () => setTimeout(step, 0));
  else setTimeout(step, 0);
})();
</script>
"""


def build(src: Path, font_path: Path | None) -> tuple[str, dict]:
  raw = src.read_bytes()
  html = raw.decode("utf-8")
  base = src.parent
  # 출처 지문은 줄 끝을 접어서(CRLF → LF) — autocrlf 로 받은 PC 와 아닌 PC 가 같은 값을 내게
  stats = {"img": 0, "poster": 0, "css_url": 0, "video": 0, "missing": [], "skipped": [], "bytes_in": 0,
           "font": None, "src_sha256": hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest()}
  seen_bytes: dict[Path, int] = {}

  def count(p: Path) -> None:
    if p not in seen_bytes:
      seen_bytes[p] = p.stat().st_size

  # 1) 영상 태그 — src(mp4) 는 파일 안 script 로, poster 는 data: 로
  embeds: list[tuple[str, Path]] = []

  def video_tag(m: re.Match) -> str:
    tag = m.group(0)

    def attr(a: re.Match) -> str:
      sp, name, ref = a.group(1), a.group(2).lower(), a.group(3)
      if not is_local(ref):
        note_skip(stats, ref)
        return a.group(0)
      p = resolve(base, ref)
      if not p.is_file():
        stats["missing"].append(ref)
        return a.group(0)
      count(p)
      if name == "poster":
        stats["poster"] += 1
        return f'{sp}poster="{data_uri(p)}"'
      eid = f"emb-video-{len(embeds) + 1}"
      embeds.append((eid, p))
      stats["video"] += 1
      return f'{sp}data-embed="{eid}"'

    return ATTR.sub(attr, tag)

  html = VIDEO_TAG.sub(video_tag, html)

  # 2) 나머지 src(그림)
  def img_attr(a: re.Match) -> str:
    sp, name, ref = a.group(1), a.group(2).lower(), a.group(3)
    if not is_local(ref):
      note_skip(stats, ref)
      return a.group(0)
    if name != "src":
      return a.group(0)
    p = resolve(base, ref)
    if not p.is_file():
      stats["missing"].append(ref)
      return a.group(0)
    count(p)
    stats["img"] += 1
    return f'{sp}src="{data_uri(p)}"'

  html = ATTR.sub(img_attr, html)

  # 3) 인라인 · <style> 의 url(...) — 같은 그림은 CSS 변수 하나로 나눠 쓴다
  var_of: dict[Path, str] = {}

  def css_url(m: re.Match) -> str:
    ref = m.group(2).strip()
    if not is_local(ref):
      return m.group(0)
    p = resolve(base, ref)
    if not p.is_file():
      stats["missing"].append(ref)
      return m.group(0)
    count(p)
    stats["css_url"] += 1
    if p not in var_of:
      var_of[p] = f"--emb-{len(var_of) + 1}"
    return f"var({var_of[p]})"

  html = CSS_URL.sub(css_url, html)

  # 4) 영상 칸의 「영상 없음」 글 — git pull 안내는 한 파일 판에 맞지 않는다
  html = MISSING_DIV.sub(lambda m: m.group(1) + "영상을 열지 못했습니다<br>이 파일을 Chrome · Edge 최신판으로 다시 열어 주세요" + m.group(3), html)

  # 5) 머리에 넣을 것 — 글꼴 · CSS 변수 · 이 판의 출처
  head_bits = []
  if font_path is not None:
    text_for_font = re.sub(r"<script\b.*?</script>", " ", html, flags=re.S | re.I)
    text_for_font = re.sub(r"data:[^\"')\s]+", " ", text_for_font)
    css, nchars, nbytes = font_face_css(font_path, text_for_font)
    stats["font"] = {"file": font_path.name, "chars": nchars, "woff2_bytes": nbytes}
    html, n_links = GOOGLE_FONT_LINK.subn("", html)
    stats["font"]["google_links_removed"] = n_links
    head_bits.append(css)
  if var_of:
    head_bits.append(":root { " + " ".join(f'{v}: url("{data_uri(p)}");' for p, v in var_of.items()) + " }")
  note = (
    "<!-- 한 파일 판 — tools/deck/bundle_deck.py 가 " + src.name + " 에서 만들었다(원본 sha256 "
    + stats["src_sha256"][:16] + "). 그림 · 영상 · 글꼴이 이 파일 안에 있어 HTML 하나만 옮겨도 된다. "
    "고치지 말고 원본을 고친 뒤 다시 만든다. -->\n"
  )
  style = "<style>\n" + "\n".join(head_bits) + "\n</style>\n" if head_bits else ""
  if "</head>" not in html:
    raise SystemExit("멈춤: </head> 가 없다")
  html = html.replace("</head>", note + style + "</head>", 1)

  # 6) 영상 본문 · 풀어 넣는 스크립트 — </body> 바로 앞
  blobs = "".join(
    f'<script type="text/plain" id="{eid}" data-mime="{mime_of(p)}">' + base64.b64encode(p.read_bytes()).decode("ascii") + "</script>\n"
    for eid, p in embeds
  )
  if "</body>" not in html:
    raise SystemExit("멈춤: </body> 가 없다")
  html = html.replace("</body>", blobs + LOADER_JS + "</body>", 1)

  stats["bytes_in"] = sum(seen_bytes.values())
  stats["files"] = len(seen_bytes)
  return html, stats


def main() -> int:
  ap = argparse.ArgumentParser(description="발표 자료 한 파일 판 만들기(그림 · 영상 · 글꼴을 HTML 안에)")
  ap.add_argument("--src", type=Path, default=DEFAULT_SRC)
  ap.add_argument("--out", type=Path, default=None)
  ap.add_argument("--font", type=Path, default=None)
  ap.add_argument("--no-font", action="store_true")
  ap.add_argument("--check", action="store_true", help="쓰지 않고 부르는 파일 · 예상 크기만")
  a = ap.parse_args()

  src = a.src.resolve()
  out = (a.out or (DEFAULT_OUT if src == DEFAULT_SRC.resolve() else src.with_name(src.stem + "-한파일.html"))).resolve()
  if out == src:
    raise SystemExit("멈춤: 결과가 원본과 같은 파일이다 — --out 을 다른 곳으로")
  font_path = None
  if not a.no_font:
    cands = [a.font] if a.font else DEFAULT_FONT_CANDIDATES
    font_path = next((p for p in cands if p and Path(p).is_file()), None)
    if font_path is None:
      print("⚠️  글꼴 파일이 없어 글꼴은 넣지 않는다 — 구글 글꼴 링크를 그대로 둔다(인터넷이 없으면 다른 글꼴로 보임)")

  html, st = build(src, font_path)
  size = len(html.encode("utf-8"))
  print(f"원본 {src.relative_to(ROOT) if src.is_relative_to(ROOT) else src} · sha256 {st['src_sha256'][:16]}")
  print(f"넣은 것: 그림 {st['img']} · 인라인 그림 {st['css_url']} · 포스터 {st['poster']} · 영상 {st['video']} · 파일 {st['files']}개 {st['bytes_in'] / 1e6:.1f} MB")
  if st["font"]:
    f = st["font"]
    print(f"글꼴: {f['file']} → 글자 {f['chars']} 개만 woff2 {f['woff2_bytes'] / 1e6:.2f} MB · 구글 글꼴 링크 {f['google_links_removed']} 줄 뺌")
  if st["skipped"]:
    print("바깥 주소(그대로 둠):", ", ".join(sorted(set(st["skipped"]))))
  print(f"한 파일 판 크기 {size / 1e6:.1f} MB ({size / 2**20:.1f} MiB)"
        + (" — GitHub 거부 한도(100 MiB) 넘음" if size > GITHUB_LIMIT else " — GitHub 경고(50 MiB) 넘음" if size > GITHUB_WARN else ""))
  if st["missing"]:
    print("❌ 찾지 못한 파일:", *sorted(set(st["missing"])), sep="\n   ")
    return 1
  if a.check:
    print("(--check — 쓰지 않았다)")
    return 0
  out.parent.mkdir(parents=True, exist_ok=True)
  with open(out, "w", encoding="utf-8", newline="") as fh:
    fh.write(html)
  print(f"✅ 썼다: {out}")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
