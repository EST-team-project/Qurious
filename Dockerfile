# Qurious(2026-10-23 · 의존성 판 관리): 바탕도 「판 태그@다이제스트」 — 태그는 같은 이름으로 다시 올라와 빌드한 날마다 바탕이 달라진다.
# 올리는 법 · 주기는 docs/phase-3/05-deployment/로컬실행안내서.md 「의존성 잠금 · 갱신」(주 1회 보고서 scripts/personal/deps_report.py).
FROM python:3.12.14-slim-trixie@sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f

WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libgomp1 \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Python deps — 무엇을 깔지는 requirements.txt(강사님 판 · 하한만), 몇 판을 깔지는 requirements.lock(간접 의존까지
# 정확한 판 · uv 로 만듦)이 정한다. 예전엔 빌드한 날의 최신이 들어와 PC 마다 판이 달랐다(qdrant-client 가 `search` 를
# 지운 판이 들어와 번역 검색이 늘 0건 · DF-149). pip check 는 깔린 것끼리 판이 맞는지 본다. 잠금은 이미지 안에도 둔다
# (시험 test.ps1 이 「이 이미지가 지금 잠금으로 만든 것인가」 를 본다).
COPY requirements.txt requirements.lock ./
RUN pip install --no-cache-dir -r requirements.txt -c requirements.lock && pip check

# App source
COPY app/ ./app/
COPY public/ ./public/
COPY prompts/ ./prompts/
COPY alembic/ ./alembic/
COPY alembic.ini ./alembic.ini

# Data directory (CSV files mounted at runtime)
RUN mkdir -p data && chmod -R 777 data

EXPOSE 8000

ENV PYTHONUNBUFFERED=1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
