# 각자 맞는 PR 둘이 합치면 head 가 둘이었다 — 병합 리비전과, `git pull` 로는 오지 않는 파일

| 칸 | 내용 |
|---|---|
| 날짜 | 2026-11-07 (S211 · 토 · 집 PC) |
| PR | [#604](https://github.com/EST-team-project/Qurious/pull/604) 병합 리비전 `0046_merge_notif_paper_kis` · `paper.js` 「(회차 +1)」 두 곳 삭제 · 문서 |
| 이슈 | [#603](https://github.com/EST-team-project/Qurious/issues/603) alembic head 둘 (사용자가 올림 · 해결됨) |
| 코드 | `alembic/versions/0046_merge_notif_paper_kis.py` · `paper.js` · 시험은 기존 `tests/test_migration_heads.py` |
| 비고 | **복원본** — 11-09 S214 에 뒤늦게 썼다(S211~S213 TIL 이 비어 있었다). 세부는 그때 남긴 메모리·기록에 있던 것만 적었고, 회고 칸은 이동원이 확인 후 고칠 수 있다 |

---

## 개념 정리

### 1. PR 하나씩은 맞는데, 합치면 head 가 둘이었다

강민석 님 PR #602(Paper↔KIS 대사)를 읽는 중에 alembic 리비전이 둘로 갈라진 것을 찾았다.

| 리비전 | 부모 |
|---|---|
| `0044_notification_secrets` (알림 비밀 암호화) | `0043` |
| `0045_paper_kis_track` (PR #602) | `0043` |

둘 다 `0043` 에서 갈라졌다. 각 PR 은 자기 브랜치에서 `upgrade head` 가 통과했을 것이다. main 에서 합쳐지는 순간 head 가 둘이 된다. 이 PC 의 앱 로그에는 `Multiple head revisions` 가 찍혀 있었다.

**각 PR 이 맞아도 합친 결과는 따로 확인해야 한다.** 병합 리비전(`0046`)은 두 head 를 부모로 갖는 빈 리비전이다.

### 2. 고쳤다는 증거는 「원본이 실패하는 것」을 먼저 보이는 것

일회용 PostgreSQL(45432 포트)로 세 가지를 확인했다.

- 원본 `upgrade head` 는 **실패**한다 (고치기 전을 재현).
- 병합본은 빈 DB 에서 끝까지 적용된다.
- 두 갈래 중 하나만 적용된 DB 는 `0046` 만 더 기록한다.

기존 `tests/test_migration_heads.py` 는 PR #602 가 들어온 뒤로 main 에서 이미 실패하고 있었고, 병합 리비전을 넣으면 통과한다. 새 시험을 만들 필요가 없었다 — 이미 있던 검사가 구멍을 알고 있었다.

`downgrade -1` 은 병합 리비전에서 `Ambiguous walk` 가 난다. alembic 의 표준 동작이다.

### 3. `git pull` 은 git 밖 파일을 가져오지 않는다

이 PC 는 S193(11-02)에 멈춰 있었다. `git pull` 로 코드는 맞췄지만 `_git-drafts` · 기억 · 설정은 git 밖이라 오지 않았다. `from-drive -Apply -Force` 를 해야 하는데 미리보기만 하고 넘어갔다가 사용자가 지적했다.

- 이 PC 가 하드보다 커밋이 앞서거나 미커밋이 있으면 `-Force` 가 필요하다(더 새 파일은 `/XO` 때문에 안 덮인다).
- 하드의 `MEMORY.md` 가 정본 색인이다. 내가 압축해 둔 판은 S194~210 항목이 빠져 있어서 하드 판 기준으로 되돌렸다.

**세션 시작은 `git pull` 뒤 `from-drive -Apply` 까지가 한 세트다.**

### 4. 줄바꿈 노이즈가 올리기 전 검사를 멈췄다

`alembic.ini` · `start.sh` 가 늘 M 으로 보이는 것은 LF/CRLF 차이일 뿐이다(내용 차이 없음). `1_after_merge.sh` 의 미커밋 검사가 이것을 오탐해 멈췄다. `git diff --ignore-cr-at-eol` 로 고쳤고, 다음 git 블록에도 같은 검사를 쓴다.

---

## 오늘의 작업 메모

- PR #604 머지 11-07 13:42(`26347ac3`) · main = origin = GitLab 0 0 확인 · 하드 `to-drive` 13:48 끝.
- #559 「(회차 +1)」 두 곳 삭제: 백테스트 계좌에는 회차가 없어 문구가 사실과 어긋났다. `node --check` 통과.
- 일지 `paper_journal.py status`(13:50): 두 규칙 모두 44행 · 마지막 11-05 · 지문 ✅. 11-06 행은 수집 DB 에 11-06 종가가 없어 아직 없다(11-09 12:30 수집 뒤).
- P3-4(차트 확정 종가 수평선) · P3-6(보유표 근거 입구)은 조사 문서 권고가 「발표 후 또는 phase-4」였고, 공용 차트 회귀 위험과 영상·동결 직전이라 보류했다.

## 막힌 것 · 남은 것

- 오준영 님 운영(복제) DB 에 `upgrade head`(0045 · 0046) 확인 — 11-09 에 완료 답을 받았다.
- 실제 KIS 연동 E2E 는 #602 에서 수행되지 않았다(강민석 님 답글).

## 배운 것

- 갈라짐은 PR 읽기에서 찾았다. 팀 PR 을 「읽기 검토」로만 훑어도 이런 결함이 나온다.
- 상태를 맞추는 일(pull · from-drive)은 한 번에 끝까지 한다. 미리보기에서 멈추면 한 단계가 빠진다.
