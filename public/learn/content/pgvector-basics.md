---
slug: pgvector-basics
title: pgvector — PostgreSQL 안에 벡터를 두는 법
section: tech
part: 8부 AI 에이전트
order: 8.3
status: draft
summary: PostgreSQL 확장 pgvector 로 임베딩을 표의 칸에 두고 거리 연산자로 찾는 법, 근사 색인(HNSW)에 거르기를 더할 때 결과가 모자라는 함정을 직접 돌려 보고, 앱이 벡터를 Qdrant 에 두는 까닭과 견줍니다.
level: 기초
minutes: 35
owner: 이동원
prereq: embedding-vector-search
tags: pgvector, PostgreSQL, 벡터 검색, HNSW, Qdrant
updated: 2026-10-20
---

> [!GOAL]
> - 확장 켜기 · 벡터 칸 · 거리 연산자 셋으로 가까운 글을 찾을 수 있습니다.
> - 근사 색인(HNSW)에 `WHERE` 거르기를 더하면 결과가 모자랄 수 있는 까닭과, 그것을 메우는 방법을 설명할 수 있습니다.
> - 벡터를 업무 DB 안에 둘 때와 벡터 전용 DB(Qdrant)에 둘 때의 득실을 견줄 수 있습니다.

> [!NOTE]
> 이 장은 초안입니다. 출력은 2026-10-20 에 일회용 컨테이너(pgvector 0.8.6 · PostgreSQL 16.14)에서 직접 돌린 결과입니다. 그림과 확인 문제는 다음 판에 더합니다.

## pgvector 는 무엇인가요?

pgvector 는 PostgreSQL 에 벡터 자료형(`vector`)과 거리 연산자, 가까운 것을 빨리 찾는 근사 색인(HNSW · IVFFlat)을 더하는 확장입니다. 임베딩을 표의 한 칸으로 두고, 「질문 벡터와 가장 가까운 줄」 을 SQL 로 찾게 해 줍니다.

임베딩이 무엇이고 왜 가까운 벡터가 비슷한 뜻인지는 [3.2 임베딩과 벡터 검색](#/p/embedding-vector-search) 에서 다룹니다. 이 장은 그 벡터를 어디에 두느냐를 다룹니다.

## 벡터를 업무 DB 안에 두면 무엇이 좋은가요?

| | 업무 DB 안(pgvector) | 벡터 전용 DB(Qdrant 등) |
|---|---|---|
| 글과 벡터를 함께 저장 · 지우기 | 트랜잭션 하나로 묶임 | 두 저장소를 따로 맞춰야 함 |
| 사용자 · 권한 표와 함께 거르기 | SQL 조인 한 번 | 거를 정보를 점마다 따로 붙여 둠 |
| 백업 · 복구 · 운영할 서버 | 하나 | 하나 더 |
| 검색 부하 | 업무 질의와 같은 자원을 나눠 씀 | 따로 늘릴 수 있음 |
| 거르기와 근사 검색 | 아래 「직접 해 보기 2」 의 함정을 알고 써야 함 | 거르기를 색인 탐색 안에서 처리하도록 만든 곳이 많음 |

자료가 몇만 줄이고 이미 PostgreSQL 을 쓰고 있다면 pgvector 가 가장 짧은 길입니다. 검색이 서비스의 중심이고 거르기 조건이 많다면 전용 DB 를 따로 두는 쪽이 운영하기 쉽습니다.

## 직접 해 보기 1 — 거리 연산자 셋

포트를 열지 않은 일회용 컨테이너에 `docker exec` 로 SQL 을 넣어 돌렸습니다. 3차원 벡터 다섯 줄을 넣고 질문 벡터 `[1, 0, 0]` 과의 거리를 셋 다 찍습니다.

```sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE docs (id serial PRIMARY KEY, kind text, body text, embedding vector(3));
INSERT INTO docs (kind, body, embedding) VALUES
  ('법령', '증권거래세 세율',   '[0.9, 0.1, 0.0]'),
  ('법령', '농어촌특별세 세율', '[0.8, 0.3, 0.1]'),
  ('뉴스', '코스피 마감 시황',  '[0.1, 0.9, 0.2]'),
  ('뉴스', '반도체 수출 동향',  '[0.0, 0.7, 0.7]'),
  ('공시', '배당 기준일 공시',  '[0.3, 0.2, 0.9]');

SELECT body,
       round((embedding <-> '[1,0,0]')::numeric, 4) AS l2,
       round((embedding <=> '[1,0,0]')::numeric, 4) AS cosine,
       round((embedding <#> '[1,0,0]')::numeric, 4) AS neg_inner
FROM docs ORDER BY embedding <=> '[1,0,0]' LIMIT 3;
```

```output
       body        |   l2   | cosine | neg_inner 
-------------------+--------+--------+-----------
 증권거래세 세율   | 0.1414 | 0.0061 |   -0.9000
 농어촌특별세 세율 | 0.3742 | 0.0700 |   -0.8000
 배당 기준일 공시  | 1.1576 | 0.6906 |   -0.3000
```

| 연산자 | 뜻 | 색인을 만들 때 쓰는 연산자 계열 |
|---|---|---|
| `<->` | 유클리드 거리(L2) | `vector_l2_ops` |
| `<=>` | 코사인 거리 = 1 − 코사인 유사도 | `vector_cosine_ops` |
| `<#>` | 내적에 −1 을 곱한 값 | `vector_ip_ops` |

`<#>` 가 음수인 까닭은 「작을수록 가깝다」 로 맞춰 `ORDER BY … ASC` 한 가지로 쓰게 하려는 것입니다. 첫 줄의 코사인 거리 0.0061 은 0.9 ÷ √(0.9² + 0.1²) ≈ 0.9939 를 1 에서 뺀 값입니다.

## 직접 해 보기 2 — 거르기가 근사 색인을 만나면

이번에는 1만 줄 가운데 1% 만 종류가 「희귀」 인 표를 만들고, HNSW 색인을 건 뒤 「희귀 가운데 가까운 10개」 를 찾습니다. 표가 작아 PostgreSQL 이 색인 대신 표 전체 훑기를 고를 수 있어, 색인을 쓰는 질의에서는 `enable_seqscan = off` 로 색인을 쓰게 했습니다.

```sql
SELECT setseed(0.42);
CREATE TABLE many (id serial PRIMARY KEY, kind text, embedding vector(3));
INSERT INTO many (kind, embedding)
SELECT CASE WHEN i % 100 = 0 THEN '희귀' ELSE '흔함' END,
       ('[' || random() || ',' || random() || ',' || random() || ']')::vector
FROM generate_series(1, 10000) AS i;
CREATE INDEX ON many USING hnsw (embedding vector_cosine_ops);
SET hnsw.ef_search = 10;

SELECT count(*) FROM (SELECT id FROM many WHERE kind = '희귀'
                      ORDER BY embedding <=> '[1,0,0]' LIMIT 10) t;
```

같은 질의를 세 가지 방법으로 돌린 결과입니다. 실행 계획(`EXPLAIN (COSTS OFF)`)을 함께 찍었고, `SET` 알림 줄과 실행 계획의 머리 줄은 줄였습니다.

```output
[4-1] 색인 없이 정확히 셀 때 희귀 중 가까운 10개
 Limit
   ->  Sort
         Sort Key: ((embedding <=> '[1,0,0]'::vector))
         ->  Seq Scan on many
               Filter: (kind = '희귀'::text)
 exact_rows 
------------
         10

[4-2] HNSW 색인 · ef_search 10 · 거르기
 Limit
   ->  Index Scan using many_embedding_idx on many
         Order By: (embedding <=> '[1,0,0]'::vector)
         Filter: (kind = '희귀'::text)
 hnsw_rows 
-----------
         0

[4-3] 반복 색인 탐색 켜기(pgvector 0.8 부터)
 hnsw_iterative_rows 
---------------------
                  10
```

표 전체를 훑으면(4-1) 10줄이 나옵니다. 색인을 쓰면(4-2) 0줄입니다. HNSW 는 가까운 후보를 `hnsw.ef_search` 개(여기서는 10개)만큼 먼저 뽑고, `WHERE` 는 그 뒤에 거르기 때문입니다. 후보 10개 가운데 「희귀」 가 하나도 없으면 결과가 비고, 오류는 나지 않습니다.

pgvector 0.8 부터는 `SET hnsw.iterative_scan = relaxed_order;` 로 모자란 만큼 색인을 더 훑게 할 수 있습니다(4-3). 다른 방법으로는 `ef_search` 를 키우기, 자주 거르는 조건으로 부분 색인(`CREATE INDEX … WHERE kind = '희귀'`)을 따로 만들기, 종류마다 표를 나누기가 있습니다.

## 우리 서비스에서는 어떻게 쓰나요?

- 앱 본체는 pgvector 를 쓰지 않습니다. 근거 검색의 벡터는 Qdrant 에 두고, 점마다 붙인 종류 · 등급 · 시행일로 거릅니다([3.1 RAG](#/p/rag-basics) 의 표 7). 사용자 · 주문 · 모의 장부는 PostgreSQL 에 있습니다([7.5 저장소 다섯](#/p/storage-ports-adapters)).
- 저장소에 함께 든 RAG 실습 앱 `rag-lab/` 은 대화 장기 기억을 pgvector 표에 둡니다. 384차원 문장 임베딩을 칸 하나로 둡니다.

```python
# rag-lab/app/models/long_term_memory.py
# pgvector: sentence-transformer 임베딩 (384차원)
embedding = Column(Vector(settings.embedding_dim), nullable=False)
```

- 시험 스크립트는 pgvector 가 든 PostgreSQL 16 이미지로 일회용 시험 DB 를 띄웁니다(`scripts/personal/test.ps1`). 앱 모델이 벡터 칸을 쓰게 되어도 같은 시험 DB 로 돌릴 수 있게 맞춘 것입니다.

## 흔한 실수

1. **색인의 연산자 계열과 다른 연산자로 찾기.** `vector_cosine_ops` 로 만든 색인은 `<=>` 질의에만 쓰입니다. `<->` 로 찾으면 색인을 타지 않습니다.
2. **거르기를 더한 근사 검색의 결과 수를 믿기.** 위 4-2 처럼 오류 없이 결과가 모자랍니다. 결과 수를 확인하고, 반복 탐색이나 부분 색인을 씁니다.
3. **작은 표에서 색인을 확인하지 않기.** 줄이 적으면 PostgreSQL 이 표 전체 훑기를 고릅니다. `EXPLAIN` 으로 실제로 무엇을 쓰는지 봅니다.
4. **칸의 차원과 다른 벡터를 넣으려 하기.** `vector(3)` 칸에는 3차원 벡터만 들어갑니다. 임베딩 모델을 바꾸면 칸과 색인을 함께 바꿔야 합니다.

## 정리

1. pgvector 는 PostgreSQL 에 벡터 칸 · 거리 연산자 · 근사 색인을 더하는 확장입니다.
2. 근사 색인은 후보를 먼저 뽑고 거르기를 나중에 해서, 거르는 조건이 드물면 결과가 모자랄 수 있습니다.
3. 업무 DB 안에 두면 트랜잭션 · 조인 · 백업이 하나로 묶이고, 전용 DB 는 검색과 거르기를 따로 키우기 쉽습니다.

## 더 읽을거리

- Supabase 문서 「pgvector: Embeddings and vector similarity」 <https://supabase.com/docs/guides/database/extensions/pgvector>
- pgvector 프로젝트 안내(연산자 · 색인 · 반복 탐색) <https://github.com/pgvector/pgvector>
- PostgreSQL 문서 「CREATE EXTENSION」 <https://www.postgresql.org/docs/16/sql-createextension.html>
- Malkov · Yashunin, HNSW <https://arxiv.org/abs/1603.09320>
