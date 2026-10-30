"""TC-HFO — Hugging Face 조직별 쓰기 권한 사전 점검 (collector/hf_orgs.py · 2026-10-30)

개인 조직(`Finance-Data` — 이동원만)에 올리는 단계가 팀원 PC 에서 에러 없이 건너뛰게 하는 부품. `whoami` 모양의 dict 로만 시험한다(네트워크 없음).
1. 팀원(조직 소속 아님) · 토큰 없음 → 건너뜀. (TC-HFO-01)
2. fine-grained 토큰 — 조직이 범위에 없음 · 읽기만 · 쓰기 있음. (TC-HFO-02)
3. 일반 토큰 — read 토큰 · 조직 역할 낮음 · write + 역할 write. (TC-HFO-03)
4. 어떤 예외도 팀 작업을 깨지 않는다 · 토큰 값은 출력하지 않는다 · 기존 팀 로직 파일을 안 건드린다. (TC-HFO-04)
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collector import hf_orgs as ho  # noqa: E402


def _who(orgs, *, fine=None, role="fineGrained"):
    tok = {"role": role}
    if fine is not None:
        tok["fineGrained"] = {"scoped": fine}
    return {"name": "someone", "orgs": [{"name": n, "roleInOrg": r} for n, r in orgs], "auth": {"accessToken": tok}}


def _scoped(name, perms):
    return {"entity": {"type": "org", "name": name}, "permissions": perms}


def test_teammate_and_missing_token_are_skipped():
    """TC-HFO-01 · 조직 소속이 아닌 팀원 · 토큰이 없을 때는 개인 조직 단계를 건너뛴다(에러 아님)."""
    teammate = _who([("qurious-quant", "write")], fine=[_scoped("qurious-quant", ["repo.write", "repo.content.read"])])
    a = ho.check_org_access(teammate, ho.PERSONAL_ORG)
    assert not a.ok and not a.can_read and "소속이 아니다" in a.reason and "건너뛴다" in a.reason
    assert ho.check_org_access(teammate, ho.TEAM_ORG).ok, "팀 조직은 그대로 쓸 수 있다"
    assert not ho.check_org_access(None, ho.PERSONAL_ORG).ok and "건너뛴다" in ho.check_org_access({}, ho.PERSONAL_ORG).reason


def test_fine_grained_token_needs_the_org_in_scope_with_write():
    """TC-HFO-02 · 소속이어도 토큰 범위에 조직이 없으면 못 쓴다 · 읽기만 있으면 못 쓴다 · repo.write 가 있어야 쓴다."""
    orgs = [("qurious-quant", "admin"), ("Finance-Data", "admin")]
    no_scope = _who(orgs, fine=[_scoped("qurious-quant", ["repo.write"])])
    a = ho.check_org_access(no_scope, ho.PERSONAL_ORG)
    assert not a.ok and "토큰 범위에 Finance-Data 가 없다" in a.reason and "Org permissions" in a.reason
    read_only = _who(orgs, fine=[_scoped("Finance-Data", ["repo.content.read"])])
    b = ho.check_org_access(read_only, ho.PERSONAL_ORG)
    assert not b.ok and b.can_read and "repo.write 가 없다" in b.reason
    full = _who(orgs, fine=[_scoped("Finance-Data", ["repo.content.read", "repo.write"]), _scoped("qurious-quant", ["repo.write"])])
    c = ho.check_org_access(full, ho.PERSONAL_ORG)
    assert c.ok and c.can_read and "쓸 수 있다" in c.reason


def test_classic_tokens_need_write_token_and_write_role():
    """TC-HFO-03 · 일반 토큰 — read 토큰 · 낮은 조직 역할은 못 쓰고, write 토큰 + write · admin 역할이면 쓴다."""
    assert not ho.check_org_access(_who([("Finance-Data", "admin")], role="read"), "Finance-Data").ok
    low = ho.check_org_access(_who([("Finance-Data", "contributor")], role="write"), "Finance-Data")
    assert not low.ok and low.can_read and "contributor" in low.reason
    for r in ("write", "admin"):
        assert ho.check_org_access(_who([("Finance-Data", r)], role="write"), "Finance-Data").ok


class _Boom:
    def whoami(self):
        raise RuntimeError("네트워크 끊김")


class _Fine:
    def whoami(self):
        return _who([("Finance-Data", "admin")], fine=[_scoped("Finance-Data", ["repo.write"])])


def test_exceptions_never_break_the_team_round_and_no_token_is_printed(capsys, monkeypatch):
    """TC-HFO-04 · whoami 가 터져도 「쓸 수 없음」 으로 접는다 · 점검 명령은 토큰 값을 출력하지 않는다 · 기존 팀 로직 파일은 이 부품을 안 부른다."""
    a = ho.check_with_api(_Boom(), "Finance-Data")
    assert not a.ok and "whoami 실패(RuntimeError)" in a.reason
    assert ho.check_with_api(_Fine(), "Finance-Data").ok
    from collector import config
    secret = "hf_SECRET_TOKEN_VALUE_123"
    monkeypatch.setattr(config, "env", lambda k, *a, **kw: secret if k == ho.TEAM_TOKEN_ENV else None)
    import types
    fake = types.ModuleType("huggingface_hub")
    fake.HfApi = lambda token=None: _Fine()
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake)
    assert ho.main() == 0
    out = capsys.readouterr().out
    assert secret not in out and "Finance-Data" in out and "쓰기" in out
    for rel in ("scripts/hf_dataset.py", "scripts/hf_sync.py", "scripts/daily_update.py"):
        src = (ROOT / rel).read_text(encoding="utf-8")
        assert "hf_orgs" not in src, f"{rel} 이 개인 조직 점검을 부른다 — 팀 로직은 그대로여야 한다"


def test_no_access_errors_are_recognised_and_personal_token_falls_back(monkeypatch):
    """TC-HFO-05 · 권한 없는 비공개 저장소는 404(RepositoryNotFoundError)로도 온다 — 둘을 같은 「건너뜀」 으로 접는다 · 개인 토큰 변수가 없으면 팀 토큰 변수."""
    class RepositoryNotFoundError(Exception):
        pass

    class GatedRepoError(Exception):
        pass

    class HfHubHTTPError(Exception):
        def __init__(self, code):
            self.response = type("R", (), {"status_code": code})()

    assert ho.is_no_access_error(RepositoryNotFoundError()) and ho.is_no_access_error(GatedRepoError())
    for code in (401, 403, 404):
        assert ho.is_no_access_error(HfHubHTTPError(code)), code
    assert not ho.is_no_access_error(HfHubHTTPError(500)), "서버 오류는 권한 문제가 아니다 — 숨기지 않는다"
    assert not ho.is_no_access_error(RuntimeError("x")) and not ho.is_no_access_error(KeyError("k"))
    from collector import config
    env = {ho.TEAM_TOKEN_ENV: "team-tok"}
    monkeypatch.setattr(config, "env", lambda k, *a, **kw: env.get(k))
    assert ho.personal_token() == "team-tok", "개인 토큰 변수가 없으면 팀 토큰 변수"
    env[ho.PERSONAL_TOKEN_ENV] = "personal-tok"
    assert ho.personal_token() == "personal-tok", "개인 토큰 변수가 있으면 그것이 먼저"
    env.clear()
    assert ho.personal_token() is None
