"""TC-HV — 사용법 영상 목록(public/js/helpvideosview.js · helpvideos.js · helpvideos.css) · 2026-10-20

결정(D132 둘째 단계 · Figma 「Qurious · 메뉴 개편 · 영상 보기 자리」 10-3 · 10-4 · 07 결정 기록):
개념 학습 묶음 첫 줄 「사용법 영상」 · 왼쪽 지금 편 · 오른쪽 차례 · 바닥 고지 · 영상이 없는 PC 에서는 메뉴 줄째 숨김.

무엇을 지키나
1. 목록 판단 — node 로 helpvideosview.js 를 그대로 돌린다: 여정(V) → 기능(F) · 번호 차례 · 묶음 안 차례 n ·
   꼴이 틀린 편(바깥 주소 · 편 이름 꼴)은 빠짐 · 빈 표(missing)는 빈 목록 · 「이 영상의 화면」 은 가장 앞 장의 화면 ·
   묶음 요약(「두 편 · 모두 1분 40초 · 한국어 자막」) · 다음 편은 묶음을 넘어간다 · 처음 편은 끝까지 안 본 첫 편. (TC-HV-01)
2. 그릴 HTML — 「이 화면 열기 →」 는 그 화면이 앱에 있을 때만 · 「다음: … →」 은 다음 편 · 차례의 지금 편 aria-current ·
   끝까지 본 편 ✓ · 바닥 고지 · 글은 글자로(꺾쇠 주입 막음). (TC-HV-02)
3. 연결 — 편 하나의 꼴은 howtoview.js 의 videoById 한 곳(videoOf 도 그것을 부른다) · 표 주소는 VIDEO_MANIFEST_URL 하나 ·
   볼 편이 없으면 CSS 가 메뉴 줄을 숨기고 js 는 <html> 의 q-help-videos 만 켜고 끈다 · 화면을 떠나면 영상을 멈춘다. (TC-HV-03)
화면 동작(1280 · 390 · 장 단추 · 「이 화면 열기」 → 사용법 창 · 빈 표)은 손 시험 tests/e2e/help_videos_list.py 가 본다.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PUB = ROOT / "public"
VIEWMOD = PUB / "js" / "helpvideosview.js"
DOM = PUB / "js" / "helpvideos.js"
HOWTOVIEW = PUB / "js" / "howtoview.js"
CSS = PUB / "css" / "helpvideos.css"

MEDIA = "/help/media/"


def _vid(title: str, n_ch: int = 2, src: str | None = None, captions: bool = True) -> dict:
  chs = [{"title": f"장{i + 1}", "start": i * 20.0, "end": (i + 1) * 20.0, "poster": f"{MEDIA}x.ch{i + 1}.jpg?v=abcdef"} for i in range(n_ch)]
  return {"title": title, "src": src or f"{MEDIA}x.webm?v=abcdef", "captions": f"{MEDIA}x.ko.vtt?v=abcdef" if captions else "",
          "chapters_src": f"{MEDIA}x.chapters.vtt?v=abcdef", "duration": n_ch * 20.0 + 10, "chapters": chs}


MANIFEST = {
  "format": 1,
  "videos": {
    "F02-기능둘": _vid("기능 둘"),
    "V02-여정둘": _vid("여정 <b>둘</b>"),
    "V01-여정하나": _vid("여정 하나", n_ch=3),
    "F01-기능하나": _vid("기능 하나"),
    "X09-다른꼴": _vid("다른 꼴"),
    "V03-바깥주소": _vid("바깥", src="https://example.com/a.webm"),
  },
  "views": {
    "robo-portfolio": {"video": "V01-여정하나", "chapter": 0},
    "robo-patterns": {"video": "V01-여정하나", "chapter": 1},
    "agent-products": {"video": "V02-여정둘", "chapter": 1},
    "data-status": {"video": "F01-기능하나", "chapter": 0},
    "crawl-auto": {"video": "F01-기능하나", "chapter": 0},
  },
}


def _node() -> str:
  node = shutil.which("node")
  if not node:
    pytest.skip("Node 가 없어 화면 함수를 돌릴 수 없다")
  return node


def _run(tmp_path: Path, body: str) -> dict:
  """helpvideosview.js 를 node 로 불러 body(그 안에서 out 을 채움)를 돌린다 — 화면 파일을 바꾸지 않는다."""
  script = tmp_path / "run.mjs"
  script.write_text(f'import * as hv from "{VIEWMOD.resolve().as_uri()}";\nconst M = {json.dumps(MANIFEST, ensure_ascii=False)};\n'
                    f"const out = {{}};\n{body}\nprocess.stdout.write(JSON.stringify(out));\n", encoding="utf-8")
  run = subprocess.run([_node(), str(script)], capture_output=True, text=True, encoding="utf-8", timeout=30)
  assert run.returncode == 0, run.stderr
  return json.loads(run.stdout)


def test_list_judgement(tmp_path):
  """TC-HV-01 · 차례 · 묶음 안 차례 · 빠지는 편 · 화면 · 요약 · 다음 편 · 처음 편"""
  out = _run(tmp_path, """
    const L = hv.listOf(M);
    out.ids = L.map(i => i.id); out.n = L.map(i => i.n); out.groups = L.map(i => i.group); out.views = L.map(i => i.view);
    out.missing = hv.listOf({ format: 1, missing: true }).length; out.none = hv.listOf(null).length;
    out.badFormat = hv.listOf({ ...M, format: 2 }).length;
    out.sumJ = hv.groupSummary(L, "journey"); out.sumF = hv.groupSummary(L, "feature");
    out.sumNoCap = hv.groupSummary([{ group: "journey", video: { durationSec: 61, captions: "" } }], "journey");
    out.next = L.map(i => hv.nextOf(L, i.id)?.id || null);
    out.first = hv.initialOf(L, null, new Set()).id;
    out.afterSeen = hv.initialOf(L, null, new Set(["V01-여정하나"])).id;
    out.allSeen = hv.initialOf(L, null, new Set(L.map(i => i.id))).id;
    out.want = hv.initialOf(L, "F01-기능하나", new Set()).id;
    out.wantGone = hv.initialOf(L, "V09-없음", new Set()).id;
    out.empty = hv.initialOf([], null, new Set());
  """)
  assert out["ids"] == ["V01-여정하나", "V02-여정둘", "F01-기능하나", "F02-기능둘"], "여정 → 기능 · 번호 차례 · 꼴이 틀린 편 빠짐"
  assert out["n"] == [1, 2, 1, 2] and out["groups"] == ["journey", "journey", "feature", "feature"]
  assert out["views"] == ["robo-portfolio", "agent-products", "crawl-auto", ""], "가장 앞 장의 화면 · 같으면 화면 키 글자 차례 · 없으면 빈 글"
  assert out["missing"] == 0 and out["none"] == 0 and out["badFormat"] == 0
  assert out["sumJ"] == "두 편 · 모두 2분 · 한국어 자막", out["sumJ"]          # 70 + 50 초
  assert out["sumF"] == "두 편 · 모두 1분 40초 · 한국어 자막", out["sumF"]
  assert out["sumNoCap"] == "한 편 · 모두 1분 1초"
  assert out["next"] == ["V02-여정둘", "F01-기능하나", "F02-기능둘", None], "다음 편은 묶음을 넘어간다 · 끝이면 없음"
  assert out["first"] == "V01-여정하나" and out["afterSeen"] == "V02-여정둘" and out["allSeen"] == "V01-여정하나"
  assert out["want"] == "F01-기능하나" and out["wantGone"] == "V01-여정하나" and out["empty"] is None


def test_html(tmp_path):
  """TC-HV-02 · 「이 화면 열기」 는 화면이 있을 때만 · 다음 단추 · 지금 편 · ✓ · 고지 · 글자로"""
  out = _run(tmp_path, """
    const L = hv.listOf(M);
    const v2 = L.find(i => i.id === "V02-여정둘");
    out.open = hv.stageHtml(v2, L, { pathLabel: "로보 어드바이저 › 투자 성향별 상품 안내", canOpen: true });
    out.noOpen = hv.stageHtml(v2, L, { pathLabel: "로보 어드바이저 › 투자 성향별 상품 안내", canOpen: false });
    out.last = hv.stageHtml(L[L.length - 1], L, {});
    out.queue = hv.queueHtml(L, "V02-여정둘", new Set(["V01-여정하나"]));
    out.note = hv.LIST_NOTE;
  """)
  assert 'data-hv-open="agent-products"' in out["open"] and "이 화면 열기 →" in out["open"]
  assert "data-hv-open" not in out["noOpen"], "그 화면이 앱에 없으면 「이 화면 열기」 를 그리지 않는다"
  assert 'data-hv-next="F01-기능하나"' in out["open"] and "다음: 기능 하나 →" in out["open"]
  assert "data-hv-next" not in out["last"] and "이 영상의 화면" not in out["last"], "마지막 편 · 화면 없는 편"
  assert "2 / 2 편" in out["open"] and "q-howto-chap" in out["open"], "편 차례 · 장 단추(사용법 창과 같은 재생 칸)"
  assert "<b>둘</b>" not in out["open"] + out["queue"] and "&lt;b&gt;둘&lt;/b&gt;" in out["queue"], "제목은 글자로"
  cur = re.findall(r'data-hv-id="([^"]+)" aria-current="true"', out["queue"])
  assert cur == ["V02-여정둘"]
  assert out["queue"].count("is-watched") == 1 and "fa-check" in out["queue"] and "끝까지 봄" in out["queue"]
  assert out["queue"].count('class="hv-group"') == 2 and out["note"] in out["queue"]
  assert out["note"] == "영상 속 주문은 모두 모의 계좌입니다 · 투자 권유가 아닙니다"


def test_wiring():
  """TC-HV-03 · 편 꼴 한 곳 · 표 주소 하나 · 메뉴 줄 숨김 · 떠나면 멈춤"""
  hv = HOWTOVIEW.read_text(encoding="utf-8")
  assert re.search(r"^export function videoById\(id, manifest, chapter = 0\)", hv, re.M)
  body = hv[hv.index("export function videoOf("):hv.index("/** 재생 시각이 든 장 차례")]
  assert "videoById(ref.video, manifest, ref.chapter)" in body and "helpUrl(" not in body, "videoOf 는 videoById 를 부른다(꼴을 두 번 만들지 않는다)"
  view = VIEWMOD.read_text(encoding="utf-8")
  assert 'from "./howtoview.js"' in view and "videoById(id, manifest, 0)" in view, "편 꼴은 howtoview.js 에서(node 는 상대 경로)"
  dom = DOM.read_text(encoding="utf-8")
  assert "fetch(VIDEO_MANIFEST_URL" in dom and not re.search(r"[\"'`]/help/videos\.json", dom), "표 주소는 howtoview.js 의 상수 하나(주석은 빼고 글자 값만 본다)"
  assert re.search(r'classList\.toggle\("q-help-videos", items\.length > 0\)', dom), "볼 편이 있을 때만 메뉴 줄"
  assert re.search(r'querySelector\("#hv-root video"\)\?\.pause\(\)', dom), "화면을 떠나면 영상을 멈춘다"
  assert "window.QHowto?.open(key)" in dom and "navigate(key)" in dom, "「이 화면 열기」 = 옮기고 사용법 창"
  css = CSS.read_text(encoding="utf-8")
  assert re.search(r':root:not\(\.q-help-videos\) button\[data-view="learn-videos"\] \{ display: none !important; \}', css)
