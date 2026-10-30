"""Hugging Face 조직별 쓰기 권한 사전 점검 — 개인 조직(`Finance-Data`) 업로드가 팀원 PC 에서 조용히 건너뛰게 (2026-10-30).

배경: 조직이 둘이다.
  · `qurious-quant`  — 팀원 전체가 읽고 쓴다(기존 수집 러너 · 앱의 백업 · 받기). **이 파일은 그쪽 로직을 바꾸지 않는다.**
  · `Finance-Data`   — 이동원 한 명만 권한이 있는 개인 조직(개인 프로젝트 · 확장용 대용량 데이터).
같은 저장소 코드를 팀원도 받아 쓰므로, 개인 조직에 올리는 코드는 **먼저 권한을 읽어 보고 없으면 에러 없이 건너뛴다.**
권한 없는 비공개 저장소는 Hub 가 403 이 아니라 404(RepositoryNotFoundError)로 답하는 경우가 있어 「저장소 없음」 과 구분이 안 되므로,
저장소를 두드려 보기 전에 `whoami` 의 조직 · 토큰 범위를 본다(읽기 호출 하나).

판별(순수 함수 — `whoami` 가 돌려주는 dict 만 본다 · 네트워크 없음):
  · 조직 소속이 아니면 → 건너뜀(팀원의 흔한 경우)
  · fine-grained 토큰 → 그 조직이 토큰 범위(scoped)에 있고 `repo.write` 가 있어야 한다
  · 일반(read · write) 토큰 → 토큰이 write 이고 조직 역할이 write · admin 이어야 한다
토큰 값은 어디에도 출력하지 않는다.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Any, Dict, Optional

TEAM_ORG = "qurious-quant"
PERSONAL_ORG = "Finance-Data"
#: 개인 조직용 토큰 환경변수 — 없으면 팀 토큰 변수(`HUGGINGFACE_ACCESS_TOKEN`)로 되돌아간다(이동원은 한 토큰에 두 조직 범위가 다 있다).
#: 팀원은 이 변수가 없고 팀 토큰에도 개인 조직 범위가 없으므로 사전 점검에서 건너뛴다. HF 에는 조직별 표준 변수가 없어 자체 이름을 쓴다.
PERSONAL_TOKEN_ENV = "FINANCE_DATA_HF_TOKEN"
TEAM_TOKEN_ENV = "HUGGINGFACE_ACCESS_TOKEN"
NEED_WRITE = "repo.write"
NEED_READ = "repo.content.read"


@dataclass(frozen=True)
class Access:
    org: str
    ok: bool            # 올릴 수 있나
    can_read: bool
    reason: str         # 건너뛸 때 · 안내할 때 쓰는 한국어 한 줄(토큰 값 없음)


def _orgs(whoami: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {o.get("name"): o for o in (whoami.get("orgs") or []) if o.get("name")}


def check_org_access(whoami: Optional[Dict[str, Any]], org: str) -> Access:
    """`whoami` 결과 한 번으로 그 조직에 쓸 수 있는지 — 모르면 안전한 쪽(쓸 수 없음)."""
    if not whoami:
        return Access(org, False, False, "토큰이 없거나 whoami 를 못 읽었다 — 개인 조직 단계는 건너뛴다")
    member = _orgs(whoami).get(org)
    if member is None:
        return Access(org, False, False, f"이 토큰의 계정은 {org} 조직 소속이 아니다 — 개인 조직 단계는 건너뛴다")
    token = (whoami.get("auth") or {}).get("accessToken") or {}
    fine = token.get("fineGrained")
    if fine is not None:                                           # fine-grained: 조직이 범위에 있어야 한다
        scoped = {s.get("entity", {}).get("name"): set(s.get("permissions") or []) for s in fine.get("scoped") or []}
        perms = scoped.get(org)
        if perms is None:
            return Access(org, False, False, f"토큰 범위에 {org} 가 없다 — 토큰 편집에서 Org permissions 에 {org} 를 더해야 한다")
        read = NEED_READ in perms or NEED_WRITE in perms
        if NEED_WRITE not in perms:
            return Access(org, False, read, f"토큰의 {org} 범위에 {NEED_WRITE} 가 없다 — 읽기만 된다")
        return Access(org, True, True, f"{org} 에 쓸 수 있다(토큰 범위 {NEED_WRITE})")
    role = token.get("role")                                       # 일반 토큰: read · write · (fineGrained 가 아닐 때)
    org_role = member.get("roleInOrg")
    if role != "write":
        return Access(org, False, role in ("read", "write"), f"토큰 종류가 {role!r} 라 쓸 수 없다(write 토큰이 필요하다)")
    if org_role not in ("write", "admin"):
        return Access(org, False, True, f"{org} 조직 역할이 {org_role!r} 라 쓸 수 없다(write · admin 이어야 한다)")
    return Access(org, True, True, f"{org} 에 쓸 수 있다(write 토큰 · 조직 역할 {org_role})")


def personal_token() -> Optional[str]:
    """개인 조직 단계가 쓸 토큰 — `FINANCE_DATA_HF_TOKEN` 이 먼저, 없으면 팀 토큰 변수. 값은 돌려주기만 하고 출력하지 않는다."""
    from collector import config
    return config.env(PERSONAL_TOKEN_ENV) or config.env(TEAM_TOKEN_ENV) or None


#: 「권한 없음」 으로 접을 예외 이름 — Hub 는 권한 없는 비공개 저장소를 403 이 아니라 404(RepositoryNotFoundError)로 답하기도 해서
#: 「없음」 과 「권한 없음」 이 구분되지 않는다(공식 문서). 그래서 둘을 같은 「건너뜀」 으로 다룬다. 상태 코드가 있으면 401 · 403 · 404 도 포함.
NO_ACCESS_EXC_NAMES = ("RepositoryNotFoundError", "GatedRepoError", "RevisionNotFoundError", "HfHubHTTPError", "HTTPError")
NO_ACCESS_STATUS = (401, 403, 404)


def is_no_access_error(exc: BaseException) -> bool:
    """업로드 · 조회가 던진 예외가 「이 토큰으로는 못 닿는다」 인가 — 그렇다면 개인 조직 단계를 건너뛰고 팀 작업은 계속한다."""
    names = {c.__name__ for c in type(exc).__mro__}
    if names & set(NO_ACCESS_EXC_NAMES[:3]):
        return True
    status = getattr(getattr(exc, "response", None), "status_code", None)
    return status in NO_ACCESS_STATUS and bool(names & set(NO_ACCESS_EXC_NAMES))


def check_with_api(api: Any, org: str) -> Access:
    """`HfApi` 로 `whoami` 한 번(읽기) 해서 판별 — 어떤 예외든 「쓸 수 없음」 으로 접고 까닭만 남긴다(팀 작업을 깨지 않는다)."""
    try:
        who = api.whoami()
    except Exception as e:                                         # noqa: BLE001 — 개인 조직 단계 때문에 팀 회차가 깨지면 안 된다
        return Access(org, False, False, f"whoami 실패({type(e).__name__}) — 개인 조직 단계는 건너뛴다")
    return check_org_access(who, org)


def main(argv=None) -> int:
    """`python -m collector.hf_orgs` — 두 조직의 권한을 읽기로 보여 준다(아무것도 바꾸지 않는다 · 토큰 값 비출력)."""
    from collector.console import utf8_stdio
    utf8_stdio()
    from collector import config
    tok = personal_token()
    if not tok:
        print(f"{TEAM_TOKEN_ENV} · {PERSONAL_TOKEN_ENV} 이 없다 — 개인 조직 단계는 건너뛴다")
        return 0
    from huggingface_hub import HfApi
    api = HfApi(token=tok)
    for org in (TEAM_ORG, PERSONAL_ORG):
        a = check_with_api(api, org)
        print(f"{'✅' if a.ok else '⏭'} {a.org:14} 쓰기 {'가능' if a.ok else '불가'} · 읽기 {'가능' if a.can_read else '불가'} — {a.reason}")
    return 0


if __name__ == "__main__":
    if __package__ in (None, ""):
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    raise SystemExit(main())
