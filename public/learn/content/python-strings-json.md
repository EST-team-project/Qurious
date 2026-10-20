---
slug: python-strings-json
title: 문자열이 코드가 될 때 — f-string · 바인딩 · JSON · 인코딩
section: tech
part: 6부 파이썬 중급
order: 6.6
status: skeleton
summary: 문자열을 만들어 다른 곳(SQL · 캐시 · 화면 · 터미널)에 넘길 때 생기는 문제 — f-string 으로 만든 SQL, JSON 왕복에서 바뀌는 값, Windows 터미널의 cp949 — 를 우리 캐시 · 스크립트에서 겪은 일로 익힙니다.
level: 기초
minutes: 35
owner: 이동원
feature: 공통
work: 3차 (사)
prereq: python-errors-cleanup
tags: 파이썬, f-string, SQL 바인딩, JSON, 인코딩
updated: 2026-10-20
---

> [!NOTE]
> 이 장은 아직 **뼈대**입니다. 다룰 질문과 참고 자료를 먼저 실었고, 본문은 이어서 채웁니다.

## 이 장에서 할 수 있게 되는 것

- SQL 에 값을 넣을 때 f-string 대신 바인딩(`?` · `:name`)을 쓰는 까닭을 말할 수 있습니다.
- `json.dumps` · `json.loads` 왕복에서 값이 바뀌는 경우(문자열 "123" · "null")를 찾을 수 있습니다.
- `ensure_ascii` 와 파일 · 터미널 인코딩(UTF-8 · cp949)이 한글을 어떻게 깨뜨리는지 설명할 수 있습니다.

## 다룰 질문

1. `f"SELECT … WHERE code = '{code}'"` 에 `' OR '1'='1` 이 들어오면 무엇이 일어나나요?
2. 캐시에 문자열 "null" 을 넣었다 꺼내면 왜 「값 없음」 과 구별되지 않나요?
3. 같은 파이썬 스크립트가 PowerShell 에서는 되고 Git Bash 에서는 한글 · 「—」 를 찍다 멈추는 까닭은?
4. 왕복 시험(넣은 값 = 꺼낸 값)은 어떤 값들로 짜야 하나요?

## 보여 줄 코드

- 바인딩 없이 만든 SQL 과 바인딩한 SQL 을 같은 입력으로 돌려 견주기(직접 돌린 출력)
- 캐시 왕복 시험 — 숫자 꼴 문자열 · "null" · "true" · 한글 · 이모지
- `sys.stdout.reconfigure(encoding="utf-8", errors="replace")` 를 넣기 전과 뒤

## 우리 프로젝트와 닿는 곳

- `app/lib/redis_cache.py` — 꺼낼 때 `json.loads` 를 먼저 해 보는 꼴이라 문자열 "123" 이 숫자 123 으로 돌아온다.
- 사용자가 Git Bash 에서 돌리는 도우미 스크립트는 첫 줄에 출력 인코딩을 UTF-8 로 맞춘다(Git Bash 의 파이썬은 cp949 로 연다).

## 먼저 읽을 1차 자료

- multi-db-lab 실습 저장소(2026-10-12 판)의 기술 노트 tech018(문자열 포매팅 — f-string · 파라미터 바인딩 · 인코딩) · tech007(`json` 모듈)
- 파이썬 문서 `sqlite3` 「How to use placeholders to bind values in SQL queries」 · `json`
