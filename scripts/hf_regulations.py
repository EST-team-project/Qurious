"""HF ``qurious-quant/product-guide-regulations`` (private) — 상품 안내의 규제 근거 원문 보관 (2026-10-12).

    PYTHONPATH=. python scripts/hf_regulations.py build <받은 폴더>   받은 원문(HTML)을 원문마다 폴더 · 본문 글자 · 메타 · 색인 · 매니페스트로
    PYTHONPATH=. python scripts/hf_regulations.py status             로컬 · 마지막 올리기 · 대조 기록 (읽기만)
    PYTHONPATH=. python scripts/hf_regulations.py upload [--yes]     dry-run(기본) · 실제로 올리고 태그 ``regulations-<날짜>``
    PYTHONPATH=. python scripts/hf_regulations.py verify             올린 판을 임시 폴더에 받아 sha256 대조

무엇을 두나
- 상품 안내 「실제로 사려면」 요건 상수표(`app/services/etp_requirements.py`)가 근거로 삼는 금융위원회 · 금융감독원 보도자료의
  원문 사본. 상수표의 `SOURCES` 열쇠와 같은 열쇠로 묶는다 — 규제가 바뀌어 상수표를 고칠 때 그날 읽은 원문을 다시 볼 수 있게.
  제목 · 주소는 상수표에서 읽는다(같은 글을 두 곳에 적지 않는다). 상수표에 없는 조사용 원문만 이 파일의 `EXTRA` 에 둔다.
- 증권사 공지 · 법령 · 행정규칙은 사본을 두지 않고 주소만 색인에 적는다(증권사 글은 그 회사 저작물 · 법령은 국가법령정보센터가
  판을 관리한다).
- 팀 데이터셋은 모두 private 다(관문 4) — 보도자료도 원 게시처의 이용 조건을 따른다. 관문 넷은 `hf_sector_laws.py` 와 같다.
폴더: data/collector/hf_regulations/ (커밋에서 빠진다)
  sources/<발행처>/<해>/<날짜>_<열쇠>/{page.html, text.txt, meta.json} · index.tsv · README.md · meta/manifest.json
받기는 사람이 한다(보도자료 쪽을 내려받아 한 폴더에) — 이 스크립트는 받은 파일을 정리 · 올리기만 한다(수집 단계가 아니다).
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from app.services import etp_requirements as etp  # noqa: E402  — 제목 · 주소 · 쓰는 곳의 정본

REPO_ID = "qurious-quant/product-guide-regulations"
OUT_DIR = ROOT / "data" / "collector" / "hf_regulations"
META_DIR = OUT_DIR / "meta"
MANIFEST_PATH = META_DIR / "manifest.json"
LAST_UPLOAD = META_DIR / "last_upload.json"
LAST_VERIFY = META_DIR / "last_verify.json"
UPLOAD_IGNORE = ["*.part", "*.tmp", "meta/last_*.json"]
KST = timezone(timedelta(hours=9))
ISSUERS = {"fsc": "금융위원회", "fss": "금융감독원"}

#: 받은 파일 이름(<발행처>-<YYYY-MM-DD>-<꼬리>.html) → 상수표의 열쇠. 꼬리는 사람이 붙인 이름이라 열쇠로 다시 맞춘다.
FILE_KEYS = {
    "fsc-2020-05-18-etp.html": "fsc_2020_05_18",
    "fsc-2023-01-25-riskgrade.html": "fsc_2023_01_25",
    "fsc-2026-01-30-asym.html": "fsc_2026_01_30",
    "fss-2026-03-18-warning.html": "fss_2026_03_18",
    "fsc-2026-05-15-single.html": "fsc_2026_05_15",
    "fsc-2026-07-16-single-fix.html": "fsc_2026_07_16",
    "fsc-2026-07-24-deposit.html": "fsc_2026_07_24",
    "fsc-2026-07-28-meeting.html": "fsc_2026_07_28",
}
#: 상수표에는 없지만 조사서가 근거로 쓴 원문(위험 표시 · 단일종목 허용 배경)
EXTRA = {
    "fsc_2023_01_25": {"title": "금융위원회 보도자료 「투자성 상품 위험등급 산정 가이드라인 마련」(2023-01-25)",
                       "url": "https://www.fsc.go.kr/no010101/79327",
                       "used_by": ["ETF 범위 조사서 3절 — 공식 위험등급 대신 숫자만 보이는 까닭"]},
    "fsc_2026_01_30": {"title": "금융위원회 보도참고 「국내-해외상장 ETF 간 비대칭 규제 해소를 위한 자본시장법 시행령 및 규정 개정 예고 등 추진」(2026-01-30)",
                       "url": "https://www.fsc.go.kr/no010101/86178",
                       "used_by": ["ETF 범위 조사서 2절 — 배율 상한 ±2배 · 단일종목 허용 배경"]},
}


def _now_kst() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _used_by() -> dict[str, list[str]]:
    """상수표의 출처 열쇠 → 그 출처를 쓰는 요건(「leveraged_2x · 레버리지 · 인버스 2배」)."""
    out: dict[str, list[str]] = {}
    for rk, r in etp.REQUIREMENTS.items():
        for s in r["sources"]:
            out.setdefault(s, []).append(f"etp_requirements.{rk} · {r['label']}")
    return out


def _text(raw: str) -> str:
    """보도자료 쪽 HTML → 본문 글자(스크립트 · 스타일 · 태그를 빼고 빈칸을 줄인다). 사이트 머리 · 메뉴 글자도 섞인다."""
    t = re.sub(r"(?is)<script.*?</script>|<style.*?</style>", " ", raw)
    t = html.unescape(re.sub(r"<[^>]+>", " ", t))
    return re.sub(r"[ \t\r\f\v]+", " ", re.sub(r"\n\s*\n+", "\n", t)).strip() + "\n"


def build(src_dir: Path) -> int:
    used = _used_by()
    known = {**{k: {"title": v["title"], "url": v["url"], "used_by": used.get(k, [])} for k, v in etp.SOURCES.items()}, **EXTRA}
    missing = [n for n in FILE_KEYS if not (src_dir / n).exists()]
    if missing:
        print(f"🔴 받은 폴더에 없는 원문: {' · '.join(missing)} — 받은 폴더를 확인할 것")
        return 1
    if (OUT_DIR / "sources").exists():
        shutil.rmtree(OUT_DIR / "sources")          # 다시 돌려도 같은 결과(멱등) — 옛 폴더를 지우고 새로 짠다
    rows = []
    for name, key in FILE_KEYS.items():
        issuer, date = name[:3], name[4:14]
        meta = known[key]
        d = OUT_DIR / "sources" / issuer / date[:4] / f"{date}_{key}"
        d.mkdir(parents=True, exist_ok=True)
        raw_path = src_dir / name
        shutil.copyfile(raw_path, d / "page.html")
        raw = (d / "page.html").read_bytes().decode("utf-8", "replace")
        (d / "text.txt").write_text(_text(raw), encoding="utf-8")
        fetched = datetime.fromtimestamp(raw_path.stat().st_mtime, KST).isoformat(timespec="seconds")
        m = {"key": key, "issuer": ISSUERS[issuer], "published": date, "title": meta["title"], "url": meta["url"],
             "fetched_at": fetched, "sha256": _sha256(d / "page.html"), "bytes": (d / "page.html").stat().st_size,
             "used_by": meta["used_by"], "copy": True}
        _write_json(d / "meta.json", m)
        rows.append({**m, "path": str((d / "page.html").relative_to(OUT_DIR)).replace("\\", "/")})
    # 사본 없이 주소만 — 상수표 출처 가운데 받은 원문이 아닌 것(증권사 공지 · 감독규정)
    for key, meta in known.items():
        if key in FILE_KEYS.values():
            continue
        rows.append({"key": key, "issuer": "", "published": "", "title": meta["title"], "url": meta["url"], "fetched_at": "",
                     "sha256": "", "bytes": 0, "used_by": meta["used_by"], "copy": False, "path": ""})
    rows.sort(key=lambda r: (not r["copy"], r["published"], r["key"]))
    cols = ["key", "issuer", "published", "title", "url", "path", "sha256", "bytes", "fetched_at", "copy", "used_by"]
    lines = ["\t".join(cols)]
    for r in rows:
        lines.append("\t".join(str(" | ".join(r[c]) if c == "used_by" else r[c]).replace("\t", " ") for c in cols))
    (OUT_DIR / "index.tsv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (OUT_DIR / "README.md").write_text(_readme(rows), encoding="utf-8")
    files = sorted(p for p in OUT_DIR.rglob("*") if p.is_file() and "meta" not in p.relative_to(OUT_DIR).parts[:1])
    man = {"repo_id": REPO_ID, "as_of": etp.AS_OF, "built_at": _now_kst(), "copies": sum(r["copy"] for r in rows),
           "links": sum(not r["copy"] for r in rows),
           "files": [{"path": str(p.relative_to(OUT_DIR)).replace("\\", "/"), "sha256": _sha256(p), "bytes": p.stat().st_size}
                     for p in files]}
    _write_json(MANIFEST_PATH, man)
    print(f"✅ 정리함 · 원문 사본 {man['copies']} · 주소만 {man['links']} · 파일 {len(man['files'])} · {OUT_DIR}")
    return 0


def _readme(rows: list[dict]) -> str:
    lines = [
        "---", "pretty_name: Qurious 상품 안내 규제 근거 원문", "license: other", "language:", "- ko", "---", "",
        "# 상품 안내 규제 근거 원문 (private)", "",
        f"Qurious 로보 어드바이저 「투자 성향별 상품 안내」 의 「실제로 사려면」 요건 상수표(`app/services/etp_requirements.py` · "
        f"기준일 {etp.AS_OF})가 근거로 삼은 금융위원회 · 금융감독원 보도자료의 원문 사본입니다.", "",
        "- 원문마다 `sources/<발행처>/<해>/<날짜>_<열쇠>/` 에 받은 쪽(`page.html`) · 본문 글자(`text.txt`) · 메타(`meta.json`).",
        "- `index.tsv` 한 줄 = 원문 하나. `copy=False` 줄은 사본 없이 주소만 적은 것(증권사 공지 · 법령).",
        "- 열쇠는 상수표의 `SOURCES` 열쇠와 같습니다. 규제가 바뀌면 상수표를 고치고 새 원문을 받아 새 태그로 올립니다.",
        "- 각 원문의 이용 조건은 원 게시처를 따릅니다. 팀 데이터셋이라 private 로만 둡니다.", "",
        "| 열쇠 | 발행 | 날짜 | 제목 | 쓰는 곳 |", "|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(f"| `{r['key']}` | {r['issuer'] or '—'} | {r['published'] or '—'} | [{r['title']}]({r['url']}) | "
                     f"{' · '.join(r['used_by']) or '—'} |")
    return "\n".join(lines) + "\n"


def status() -> int:
    man, up, ver = _read_json(MANIFEST_PATH), _read_json(LAST_UPLOAD), _read_json(LAST_VERIFY)
    print(f"― {REPO_ID}")
    local = ("없음 — build 를 먼저" if not man else
             f"{man['built_at']} · 사본 {man['copies']} · 주소만 {man['links']} · 파일 {len(man['files'])}")
    print(f"  로컬   {local}")
    print(f"  올리기 {up.get('at', '없음')} · 태그 {up.get('tag', '—')}")
    print(f"  대조   {ver.get('at', '없음')} · {'✅' if ver.get('ok') else ('🔴' if ver else '—')}")
    return 0


def _assert_private(api) -> bool:
    api.create_repo(REPO_ID, repo_type="dataset", private=True, exist_ok=True)
    try:
        info = api.repo_info(REPO_ID, repo_type="dataset")
    except Exception as e:
        print(f"  🔴 공개 범위를 확인하지 못했다({type(e).__name__}) — 올리지 않는다")
        return False
    if not info.private:
        print(f"  🔴 원격이 public 이다 — 올리지 않는다. https://huggingface.co/datasets/{REPO_ID}/settings")
        return False
    print("  ✅ 관문 4 원격이 private 임을 확인했다")
    return True


def upload(yes: bool) -> int:
    import hf_dart as _dart  # 토큰 · 공유 스위치 · hf_xet 관문을 같이 쓴다(늦게 불러 build · status 는 가볍게)
    man = _read_json(MANIFEST_PATH)
    if not man:
        print("올릴 것이 없다 — build 를 먼저")
        return 1
    bad = [f["path"] for f in man["files"] if not (OUT_DIR / f["path"]).exists()
           or _sha256(OUT_DIR / f["path"]) != f["sha256"]]
    tag = f"regulations-{datetime.now(KST).strftime('%Y-%m-%d')}"
    print(f"― 업로드 {'(실행)' if yes else '(dry-run)'} · {REPO_ID} · 태그 {tag} · 파일 {len(man['files'])}")
    print(f"  관문 1 공유 스위치 {'✅' if _dart._sharing_on() else '🔴 꺼짐'} · 관문 2 로컬 {'✅' if not bad else '🔴 ' + ' · '.join(bad[:3])}"
          f" · 관문 3 hf_xet {'✅' if _dart._xet_on() else '⚠️ 없음'}")
    if not yes:
        print("  실제로 올리려면 `--yes`")
        return 0
    if not _dart._sharing_on() or bad:
        print("  🔴 관문을 넘지 못했다 — 올리지 않는다")
        return 1
    from huggingface_hub import HfApi
    api = HfApi(token=_dart._token())
    if not _assert_private(api):
        return 1
    msg = f"상품 안내 규제 근거 원문 · 기준일 {man['as_of']} · 사본 {man['copies']} · 주소만 {man['links']}"
    info = api.upload_folder(repo_id=REPO_ID, repo_type="dataset", folder_path=str(OUT_DIR), commit_message=msg,
                             ignore_patterns=UPLOAD_IGNORE)
    commit = str(getattr(info, "oid", "") or "")
    try:
        api.create_tag(REPO_ID, repo_type="dataset", tag=tag, tag_message=msg, revision=commit or None)
        note = "새로 닮"
    except Exception as e:
        note = f"이미 있어 그대로 둠({type(e).__name__})"
    print(f"  ✅ 올렸다 · 커밋 {commit[:8]} · 태그 {tag} {note}")
    _write_json(LAST_UPLOAD, {"at": _now_kst(), "commit": commit, "tag": tag, "tag_note": note,
                              "files": {f["path"]: f["sha256"] for f in man["files"]}})
    return 0


def verify() -> int:
    import hf_dart as _dart
    from huggingface_hub import snapshot_download
    last = _read_json(LAST_UPLOAD)
    if not last:
        print("올린 기록이 없다 — upload --yes 를 먼저")
        return 1
    with tempfile.TemporaryDirectory() as td:
        snapshot_download(repo_id=REPO_ID, repo_type="dataset", revision=last["commit"], local_dir=td, token=_dart._token())
        bad = [p for p, h in last["files"].items() if not (Path(td) / p).exists() or _sha256(Path(td) / p) != h]
    ok = not bad
    _write_json(LAST_VERIFY, {"at": _now_kst(), "revision": last["commit"], "ok": ok, "bad": bad[:20]})
    print(f"{'✅' if ok else '🔴'} 대조 · 파일 {len(last['files'])} · 어긋남 {len(bad)}{' · ' + ' · '.join(bad[:3]) if bad else ''}")
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("src", type=Path)
    sub.add_parser("status")
    u = sub.add_parser("upload")
    u.add_argument("--yes", action="store_true")
    sub.add_parser("verify")
    a = ap.parse_args(argv)
    if a.cmd == "build":
        return build(a.src)
    if a.cmd == "status":
        return status()
    if a.cmd == "upload":
        return upload(a.yes)
    return verify()


if __name__ == "__main__":
    sys.exit(main())
