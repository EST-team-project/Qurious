"""3차 발표 영상 모음 덱 원본 만들기 — 장면 파일(발표/P-*.yaml)마다 영상 한 장씩(2026-11-05 사용자 요구).

왜: 영상은 yaml(장면 파일)만이 아니라 실제 mp4 로도 있어야 하고, 발표 자료 한 파일만 다른 PC 로 옮겨도 그림 · 영상이 재생돼야 한다.
    이 도구가 만드는 것은 **고치는 원본**(전체-발표자료-원본.html · 영상을 상대 경로로 부름)이고, 한 파일 판은
    `tools/deck/bundle_deck.py` 가 이 원본에서 만든다(영상 · 포스터 · 글꼴을 파일 안에 넣는다).

틀: 2차 덱(docs/phase-2/06-retrospective/발표자료-원본.html)의 CSS · 넘기기 · 영상 로더를 그대로 쓰고 장만 새로 쓴다.
장: 표지 → (담당 순서대로) 영상 한 장씩. 장마다 발표자 노트(N 키)에 **자막(대사) 전문**을 실어 팀원이 대사를 검토할 수 있다.
영상 파일(`videos/파일/발표/<이름>.mp4`)이 아직 없으면 그 장은 「영상 파일을 찾지 못했습니다」 칸을 보인다(말없이 빈 칸이 되지 않게).

쓰는 법(저장소 뿌리에서):
  python tools/deck/build_video_deck.py            # 전체-발표자료-원본.html 을 다시 쓴다
  python tools/deck/build_video_deck.py --check    # 쓰지 않고 장 목록 · 영상 파일 유무만
  python tools/deck/bundle_deck.py --src docs/phase-3/06-retrospective/전체-발표자료-원본.html --out docs/phase-3/06-retrospective/전체-발표자료.html
"""
from __future__ import annotations

import argparse
import html
import sys
from pathlib import Path

import yaml

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[2]
RETRO = ROOT / "docs" / "phase-3" / "06-retrospective"
SCENES = RETRO / "videos" / "발표"
FILES = RETRO / "videos" / "파일" / "발표"
OUT = RETRO / "전체-발표자료-원본.html"
BASE = ROOT / "docs" / "phase-2" / "06-retrospective" / "발표자료-원본.html"   # CSS · 넘기기 · 영상 로더를 빌려 온다

ORDER = ["이동원", "신장환", "오준영", "강민석"]
COLORS = {"이동원": "#4f46e5", "신장환": "#b45309", "오준영": "#0f766e", "강민석": "#0369a1"}
ROLES = {"이동원": "데이터 · 신호 근거 · 대사", "신장환": "전략 카드 · 성과 검증", "오준영": "배분 · 리밸런싱 · 실행", "강민석": "LEAN 대사 · 모의투자"}


def esc(s) -> str:
  return html.escape(str(s), quote=True)


def load_scenes():
  rows = []
  for p in sorted(SCENES.glob("P-*.yaml")):
    sc = yaml.safe_load(p.read_text(encoding="utf-8"))
    says = [s["say"] for s in sc.get("steps", []) if isinstance(s, dict) and "say" in s]
    chapters = [s["chapter"] for s in sc.get("steps", []) if isinstance(s, dict) and "chapter" in s]
    rows.append({"stem": p.stem, "title": sc.get("title", p.stem), "owner": sc.get("owner", ""), "says": says, "chapters": chapters})
  rows.sort(key=lambda r: (ORDER.index(r["owner"]) if r["owner"] in ORDER else 99, r["stem"]))
  return rows


def video_slide(r) -> str:
  stem, owner = r["stem"], r["owner"]
  has = (FILES / f"{stem}.mp4").exists()
  ch = r["chapters"]
  purpose = (ch[0].get("text") if ch else "") or r["title"]
  tail = (ch[-1].get("text") if ch else "") or ""
  notes = "자막(대사): " + " / ".join(r["says"]) if r["says"] else "자막 없음"
  return f'''<section class="slide" data-title="{esc(owner)} · {esc(stem)}">
  <div class="kicker">{esc(owner)} · {esc(r["title"])}</div>
  <div class="video-wrap" data-video="{esc(stem)}">
    <video controls preload="metadata" poster="videos/파일/발표/{esc(stem)}.jpg" src="videos/파일/발표/{esc(stem)}.mp4"></video>
    <div class="missing">영상 파일을 찾지 못했습니다{'' if has else '(아직 내보내지 않았습니다)'}<br>docs/phase-3/06-retrospective/videos/파일/발표/ 를 받은 뒤 다시 열어 주세요</div>
  </div>
  <div class="video-side"><b>목적</b>{esc(purpose)}<br><br><b>마지막 장</b>{esc(tail)}</div>
  <div class="foot"><b>Qurious</b><span class="pg"></span></div>
  <aside class="notes">{esc(notes)}</aside>
</section>'''


def cover(rows) -> str:
  chips = "".join(f'<span class="chip"><i style="background:{COLORS[o]}"></i>{o} · {ROLES[o]}</span>' for o in ORDER)
  return f'''<section class="slide cover" data-title="표지">
  <div class="bar"></div>
  <div class="in">
    <div class="logo"><div class="mark"></div><div class="name">Qurious</div></div>
    <p class="one">3차 프로젝트 — 주요 기능 시연 영상</p>
    <p class="two">담당자별로 핵심 기능을 목적 → 실행 과정 → 결과 순서로 보여 줍니다. 영상 {len(rows)}편 · 편마다 3분 안</p>
  </div>
  <div class="team">{chips}</div>
  <div class="date" style="bottom:200px">3차 프로젝트 발표 · 영상 모음 · 초안 v0.1 (팀원 피드백 전)</div>
  <aside class="notes">팀원 확인용 초안입니다. 장마다 N 키(발표자 노트)에 자막 전문이 있습니다. 자막이 화면과 맞는지, 숫자 · 표현이 맞는지 확인해 주세요.</aside>
</section>'''


def build() -> str:
  base = BASE.read_text(encoding="utf-8").replace("\r\n", "\n")
  head = base[: base.index("<body>")]
  tail = base[base.index("<script>"):]                      # 넘기기 · 영상 로더 스크립트와 </body></html>
  head = head.replace('<meta name="doc-version" content="1.2">', '<meta name="doc-version" content="0.1">', 1)
  head = head.replace("<title>Qurious 2차 발표</title>", "<title>Qurious 3차 발표 영상 모음</title>", 1)
  a, b = head.index("<!--\n"), head.index("-->\n") + 4
  head = head[:a] + ("<!--\n  3차 발표 영상 모음 v0.1 (2026-11-05 초안) — 이 파일은 tools/deck/build_video_deck.py 가 장면 파일(videos/발표/P-*.yaml)에서 만든 원본.\n"
                     "  넘기기: ← → · Space · N 말할 거리(자막 전문) · F 전체 화면. 영상: videos/파일/발표/ mp4 를 상대 경로로 재생.\n"
                     "  한 파일 판: python tools/deck/bundle_deck.py --src <이 파일> --out <전체-발표자료.html> — 영상 · 그림 · 글꼴을 파일 안에 넣어 HTML 하나만 옮겨도 재생된다.\n"
                     "  원본을 손으로 고치지 않는다 — 장면 파일을 고치고 이 도구를 다시 돌린다.\n-->\n") + head[b:]
  rows = load_scenes()
  slides = "\n\n".join([cover(rows)] + [video_slide(r) for r in rows])
  return head + "<body>\n<div class=\"deck\" id=\"deck\">\n\n" + slides + "\n\n</div>\n<div id=\"notes-panel\"></div>\n<div id=\"hint\">← → 넘기기 · N 말할 거리 · F 전체 화면</div>\n" + tail


def main() -> int:
  ap = argparse.ArgumentParser(description="3차 발표 영상 모음 덱 원본")
  ap.add_argument("--check", action="store_true", help="쓰지 않고 장 목록 · 영상 파일 유무만")
  args = ap.parse_args()
  rows = load_scenes()
  for r in rows:
    ok = (FILES / f"{r['stem']}.mp4").exists()
    print(f"{'✅' if ok else '·'} {r['owner']:<4} {r['stem']:<34} {'mp4 있음' if ok else 'mp4 없음'} · 자막 {len(r['says'])}줄")
  if args.check:
    return 0
  OUT.write_bytes(build().encode("utf-8"))
  print(f"썼습니다 {OUT.relative_to(ROOT).as_posix()} · 장 {len(rows) + 1}")
  return 0


if __name__ == "__main__":
  sys.exit(main())
