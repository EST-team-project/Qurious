---
slug: python-errors-cleanup
title: 실패와 정리 — 예외 계층 · 로깅 · with · 제너레이터
section: tech
part: 6부 파이썬 중급
order: 6.5
status: skeleton
summary: 실패를 어디서 잡고 어떻게 바꿔 알릴지(예외 계층 · raise … from · HTTP 응답으로 번역)와, 열었으면 반드시 닫는 법(with · 컨텍스트 매니저 · 제너레이터), print 대신 logging 을 쓰는 까닭을 우리 수집 DB 연결 · 데이터 라우트로 익힙니다.
level: 기초
minutes: 40
owner: 이동원
feature: 공통
work: 3차 (사)
prereq: python-functions-as-values
tags: 파이썬, 예외, logging, with, 제너레이터
updated: 2026-10-20
---

> [!NOTE]
> 이 장은 아직 **뼈대**입니다. 다룰 질문과 참고 자료를 먼저 실었고, 본문은 이어서 채웁니다.

## 이 장에서 할 수 있게 되는 것

- `try` 의 네 절(`except` · `else` · `finally`)이 각각 언제 도는지 말할 수 있습니다.
- 드라이버 예외를 우리 예외로 바꾸고(`raise … from`) HTTP 응답으로 바꾸는 일은 한 곳에서 한다는 원칙을 설명할 수 있습니다.
- 「열었으면 닫는다」 를 `with` 로 지키고, 직접 컨텍스트 매니저(`@contextmanager`)를 만들 수 있습니다.
- `print` 와 `logging` 의 차이(수준 · 어디로 · 누가 찍었나)를 말할 수 있습니다.

## 다룰 질문

1. 모든 예외를 잡는 `except Exception: pass` 는 왜 위험한가요(말없는 실패)?
2. 같은 `except XError → HTTPException` 을 라우트마다 적으면 무엇이 어긋나나요?
3. SQLite 연결을 `with sqlite3.connect(…) as con:` 으로 열면 연결이 닫히나요? 닫히지 않는다면 `with` 가 끝내는 것은 무엇인가요?
4. 큰 결과를 한 번에 목록으로 만들지 않고 제너레이터로 흘려보내면 무엇이 달라지나요?

## 보여 줄 코드

- 네 절이 도는 차례를 찍는 예(직접 돌린 출력)
- 드라이버 예외 → 우리 예외 → HTTP 응답을 한 곳(예외 처리기)에서 바꾸는 꼴
- `contextlib.closing` 으로 SQLite 연결을 닫는 예와 닫지 않았을 때 남는 것

## 우리 프로젝트와 닿는 곳

- `app/routes/data.py` 가 라우트마다 `except … → HTTPException` 을 되풀이한다.
- 수집 DB 를 읽기 전용(`mode=ro`)으로 여는 줄이 여러 파일에 따로 있다. 연결 하나를 잘못 닫아 보조 파일이 지워지고 앱의 데이터 API 가 500 을 낸 일이 이 장의 실제 사례다.
- `app/main.py` 가 끝날 때 연결을 닫는 차례. 하나가 실패하면 뒤의 것이 닫히지 않는다.

## 먼저 읽을 1차 자료

- multi-db-lab 실습 저장소(2026-10-12 판)의 기술 노트 tech006(예외 처리) · tech014(`logging`) · tech009(컨텍스트 매니저) · tech011(제너레이터와 이터레이터)
- 파이썬 문서 「Errors and Exceptions」 · `contextlib` · `logging` 「HOWTO」
