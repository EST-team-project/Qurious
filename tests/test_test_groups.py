"""시험 묶음 표(scripts/personal/_test_groups.py) 지킴이 — TC-TB.

test.ps1 -Split · -Group 은 이 표로 묶음마다 새 pytest 프로세스를 띄운다. 표가 시험 파일을 빠뜨리면
그 파일은 묶음 실행에서 아무도 돌리지 않고, 두 번 넣으면 합이 한 프로세스 실행과 달라진다.
근거 — docs/phase-3/01-analysis/research/배경조사/2026-10-21-스크립트-점검/결과.md 3.1절(지킴이 하나).
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MOD_PATH = ROOT / "scripts" / "personal" / "_test_groups.py"


def _load():
    spec = importlib.util.spec_from_file_location("_test_groups", MOD_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


tg = _load()


def test_every_test_file_lands_in_exactly_one_group():
    names = tg.test_files()
    seen = [f for g in tg.assign(names) for f in g["files"]]
    assert len(seen) == len(set(seen)), "한 파일이 두 묶음에 들었다"
    assert sorted(seen) == names, "묶음 실행에서 빠지는 시험 파일이 있다"


def test_group_names_and_keys_are_unique_and_keys_ascii():
    labels = [g[0] for g in tg.GROUPS] + [tg.REST[0], tg.CONTAINER[0]]
    keys = [g[1] for g in tg.GROUPS] + [tg.REST[1], tg.CONTAINER[1]]
    assert len(set(labels)) == len(labels)
    assert len(set(keys)) == len(keys)
    # 영어 열쇠는 Git Bash → PowerShell 인자 · 결과 파일 이름(ui.xml)에 쓴다
    assert all(k.isascii() and k.isidentifier() for k in keys)


def test_no_named_group_is_empty():
    # 이름 붙인 묶음이 비면 그 묶음 글롭이 모두 빗나간 것이다(파일 이름이 바뀌어 다른 묶음 · 나머지로 샜다).
    keys = {g["key"] for g in tg.assign(tg.test_files())}
    for label, key, _ in tg.GROUPS:
        assert key in keys, f"{label}({key}) 묶음에 든 시험 파일이 없다"


def test_first_match_wins_and_unknown_goes_to_rest():
    assert tg.group_of("test_data_screens.py") == ("화면", "ui")       # data_ 보다 화면이 먼저
    assert tg.group_of("test_chat_stock_card.py") == ("화면", "ui")    # chat_ 보다 화면이 먼저
    assert tg.group_of("TEST_KB_SEARCH.PY") == ("지식", "kb")          # 대소문자 무시(PowerShell -like 와 같게)
    assert tg.group_of("test_zz_new_feature.py") == tg.REST            # 맞는 글롭이 없으면 나머지


def test_json_output_is_ascii_and_matches_assign():
    # test.ps1(PowerShell 5.1)은 파이썬 출력을 콘솔 코드 페이지로 읽는다 → 한글이 깨지지 않게 ASCII 여야 한다
    out = subprocess.run([sys.executable, str(MOD_PATH), "--json"], capture_output=True, check=True)
    assert out.stdout.isascii()
    data = json.loads(out.stdout.decode("ascii"))
    want = tg.assign(tg.test_files())
    assert [g["key"] for g in data["groups"]] == [g["key"] for g in want]
    assert [g["name"] for g in data["groups"]] == [g["name"] for g in want]
    assert all(f.startswith("tests/test_") for g in data["groups"] for f in g["files"])


def test_test_ps1_reads_this_table():
    # 표만 맞고 test.ps1 이 다른 길로 묶음을 고르면 이 지킴이가 헛돈다 — 부르는 줄 · 묶음마다 결과 파일을 본다
    src = (ROOT / "scripts" / "personal" / "test.ps1").read_text(encoding="utf-8-sig")
    assert "_test_groups.py') --json" in src
    assert '"--junit-xml=$xml") + @($g.files)' in src


def test_container_group_takes_rag_chat_isolation_first_and_runs_last():
    # 호스트에 RAG · 채팅 패키지가 없어 통째로 건너뛰던 셋(TC-VS · TC-CM · TC-DI)을 앱 이미지 컨테이너 묶음이 가진다(2026-10-23)
    label, key, names = tg.CONTAINER
    for n in names:
        assert (tg.TESTS / n).is_file(), f"컨테이너 묶음의 {n} 이 tests/ 에 없다(이름이 바뀌었으면 표도 고친다)"
        assert tg.group_of(n) == (label, key)                              # 지식 묶음의 test_rag_* · test_chat_* 보다 먼저
    assert tg.group_of("test_chat_answer_cache.py") == ("지식", "kb")      # 이름을 적은 셋만 — 글롭이 아니다
    groups = tg.assign(tg.test_files())
    assert groups[-1]["key"] == key and groups[-1]["runner"] == "container" and groups[-1]["image"] == tg.CONTAINER_IMAGE
    assert all(g["runner"] == "host" for g in groups[:-1])                 # 실행은 맨 끝 · 나머지는 모두 호스트


def test_test_ps1_runs_container_group_read_only_without_host_install():
    # 컨테이너 묶음 — 저장소는 읽기 전용 · 결과만 /out · 이미지 · Docker 가 없으면 실패가 아니라 건너뜀 + 까닭
    # · pip 는 컨테이너 명령 안에만(호스트 파이썬에 패키지를 깔지 않는다)
    src = (ROOT / "scripts" / "personal" / "test.ps1").read_text(encoding="utf-8-sig")
    assert "if ($g.runner -eq 'container')" in src and "Invoke-QContainerGroup $g $RunDir" in src
    assert '-v "${repo}:/w:ro"' in src and '-v "${out}:/out"' in src and "--junit-xml=/out/{1}.xml" in src
    assert "docker image inspect $g.image" in src and "skipped_reason" in src
    run_pip = [ln for ln in src.splitlines() if "pip install" in ln and "Write-Q" not in ln]   # 안내 글은 뺀다
    assert len(run_pip) == 1 and "|| exit 97" in run_pip[0]                  # 컨테이너 명령 글 하나뿐
    assert "& pip" not in src and "-m pip" not in src and "'-m', 'pip'" not in src
