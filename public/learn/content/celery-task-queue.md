---
slug: celery-task-queue
title: Celery 와 Redis — 웹 요청과 떼어 돌리는 작업 · 예약
section: tech
part: 7부 서버 · 운영
order: 7.6
status: skeleton
summary: 오래 걸리거나 정해진 때에 돌아야 하는 일을 웹 요청에서 떼어 작업 대기열(Celery · Redis)과 예약(Beat)으로 돌리는 구조를, 앱의 자동매매 주기 · 리밸런싱 판정 · 일일 기록 예약으로 익힙니다.
level: 기초
minutes: 35
owner: 이동원
prereq: batch-scheduling, docker-compose-dev
tags: Celery, Redis, 작업 대기열, Beat, 예약 작업
updated: 2026-10-20
---

> [!NOTE]
> 이 장은 아직 **뼈대**입니다. 다룰 질문과 참고 자료를 먼저 실었고, 본문은 이어서 채웁니다.

## 이 장에서 할 수 있게 되는 것

- 브로커 · 워커 · 결과 저장소 · Beat 가 각각 무엇을 맡는지 그림으로 그릴 수 있습니다.
- 오래 걸리는 일을 앱 안 스레드가 아니라 별도 워커에서 돌리는 까닭을 말할 수 있습니다.
- 같은 일이 두 번 돌지 않게 막는 장치(잠금 · 하루 한 번 기록 · 같은 요청 거르기)를 설명할 수 있습니다.

## 다룰 질문

1. 웹 요청 안에서 몇 분 걸리는 일을 돌리면 무엇이 멈추나요? 작업을 대기열에 넣으면 무엇이 달라지나요?
2. Beat 가 정해진 간격으로 자동매매 작업을 넣는데, 앞 회차가 끝나지 않았으면 어떻게 되나요?
3. Redis 가 꺼지면 무엇이 멈추고 무엇은 그대로인가요?
4. 매일 낮 수집은 Celery Beat 가 아니라 운영체제 작업 스케줄러로 돌립니다. 두 예약은 무엇이 다른가요?([2.4 정기 배치](#/p/batch-scheduling))
5. 워커와 Beat 가 살아 있는지는 어떻게 아나요?

## 보여 줄 코드

- 예약 표 `beat_schedule`(`app/celery_app.py`) — 자동매매 주기(`quant.auto_trade_cycle` · 설정 `QUANT_CYCLE_SEC`, 앱 기본 600초) · 리밸런싱 준비 확인(`rebalance.check_triggers` · 5분) · 모의 계좌 일일 기록(`paper.record_daily_snapshots` · 15:40) · 생존 신호(`beat.heartbeat` · 1분)
- 웹 요청이 작업을 넣고 바로 돌아오는 꼴(`POST /api/chat/async`)
- 같은 작업을 두 번 넣었을 때 한 번만 처리되는지 확인하기(직접 돌린 출력)

## 우리 프로젝트와 닿는 곳

- 도커 컴포즈의 `celery-worker` · `celery-beat` 두 서비스와 브로커 겸 결과 저장소인 `redis`
- 리밸런싱은 5분마다 준비를 확인하지만, 판정은 거래일마다 한 번만 기록합니다([11.2 리밸런싱 세 방식](#/p/rebalancing-methods)).
- 수집 러너는 도커 밖에서 작업 스케줄러로 돕니다. 컨테이너 안에 수집기 코드가 없어 Beat 예약이 실패했던 기록이 그렇게 나눈 까닭입니다.

## 먼저 읽을 1차 자료

- Celery 문서 「First Steps with Celery」 <https://docs.celeryq.dev/en/stable/getting-started/first-steps-with-celery.html>
- Celery 문서 「Periodic Tasks」 <https://docs.celeryq.dev/en/stable/userguide/periodic-tasks.html>
- Redis 문서 「SET」(NX · EX 선택지) <https://redis.io/docs/latest/commands/set/>
