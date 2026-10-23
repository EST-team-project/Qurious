"""크롤링 서비스: GitHub docs, 금융 포털, Qdrant RAG 구축."""
import httpx
import logging  # Qurious: 저장 · 검색을 건너뛴 까닭을 남긴다(2026-10-23)
import re
from html.parser import HTMLParser
from bs4 import BeautifulSoup
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import settings
from app.lib.ollama import OllamaClient
from app.models import CrawledDoc
from app.services.crawl_points import crawl_point_id, prune_stale_points
from app.services import url_guard  # Qurious: 리다이렉트 홉마다 보내기 전에 주소 검사(규칙은 그 파일에)
from app.lib import vector_db  # Qurious: Qdrant 문지기 — 클라이언트 · 넣기 · 검색 · 「닿지 못함」 판정(DF-149 · 2026-10-23)


def _log():
    # Qurious: 쓸 때 만든다(모듈을 읽을 때 만든 로거는 앱 시작 때 alembic 로그 설정이 끈다 — rag_pipeline 과 같은 까닭)
    return logging.getLogger("qurious.crawl")


async def _upsert_crawled_doc(db: AsyncSession, url: str, title: str, content: str, source: str) -> None:
    stmt = pg_insert(CrawledDoc).values(
        url=url, title=title, content=content[:5000], source=source, crawled_at=func.now(),
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[CrawledDoc.url],
        set_={"title": title, "content": content[:5000], "source": source, "crawled_at": func.now()},
    )
    await db.execute(stmt)
    await db.commit()

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 150
GITHUB_API = "https://api.github.com"
GITHUB_RAW = "https://raw.githubusercontent.com"

CRAWL_TARGETS = [
    {
        "name": "python-quant docs (GitHub)",
        "type": "github_docs",
        "owner": "edumgt",
        "repo": "python-quant",
        "branch": "main",
        "path": "docs",
    },
]


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self._texts = []
        self._skip = False

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "nav", "footer", "header"):
            self._skip = True

    def handle_endtag(self, tag):
        if tag in ("script", "style", "nav", "footer", "header"):
            self._skip = False

    def handle_data(self, data):
        if not self._skip:
            t = data.strip()
            if t:
                self._texts.append(t)

    def get_text(self) -> str:
        return " ".join(self._texts)


def _extract_text(html: str) -> str:
    p = _TextExtractor()
    p.feed(html)
    return p.get_text()


def _chunk_text(text: str) -> list[str]:
    words = text.split()
    chunks, i = [], 0
    while i < len(words):
        chunk = " ".join(words[i:i + CHUNK_SIZE])
        if chunk:
            chunks.append(chunk)
        i += CHUNK_SIZE - CHUNK_OVERLAP
    return chunks


async def _store_qdrant(chunks: list[str], meta: dict, ollama: OllamaClient) -> int:
    """Qdrant에 임베딩 저장 (Qdrant 미연결 시 스킵)."""
    # Qurious(2026-10-23 · DF-149 같은 꼴): Qdrant 는 문지기(app/lib/vector_db.py)로 부르고, 건너뛰는 것은 「닿지 못함」
    # (Qdrant · 임베딩 서버)뿐이다 — 예전 `except Exception` 은 라이브러리 판이 바뀌어 난 AttributeError 까지 「0건」 으로 숨겼다.
    try:
        qm = vector_db.models()
        client = vector_db.async_client()
        collection = settings.QDRANT_COLLECTION
        try:
            async def _dim() -> int:
                test_emb = await ollama.embed(settings.EMBED_MODEL, "test")
                return len(test_emb) if test_emb else 768  # nomic-embed-text dimension

            await vector_db.ensure_collection(client, collection, _dim)

            points = []
            for i, chunk in enumerate(chunks):
                emb = await ollama.embed(settings.EMBED_MODEL, chunk)
                if not emb:
                    continue
                point_id = crawl_point_id(meta.get("url", ""), i)
                points.append(qm.PointStruct(
                    id=point_id,
                    vector=emb,
                    payload={**meta, "text": chunk, "chunk_index": i},
                ))

            if points:
                await vector_db.upsert(client, collection, points)
                await prune_stale_points(client, collection, meta.get("url", ""), [p.id for p in points])
        finally:
            await vector_db.aclose(client)
        return len(points)
    except (vector_db.VectorDBUnavailable, httpx.HTTPError) as e:  # Qurious: 닿지 못함만 건너뛴다 · 까닭은 남긴다
        _log().warning("크롤 조각 저장 건너뜀 (%s): %s", meta.get("url", ""), e)
        return 0  # silently skip if Qdrant unavailable


async def crawl_github_docs(
    owner: str, repo: str, branch: str, path: str,
    db: AsyncSession, ollama: OllamaClient, log: list[str],
) -> int:
    """GitHub 레포의 markdown docs를 크롤링하여 Qdrant에 저장."""
    total = 0
    api_url = f"{GITHUB_API}/repos/{owner}/{repo}/contents/{path}?ref={branch}"

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        try:
            resp = await client.get(api_url, headers={"Accept": "application/vnd.github.v3+json"})
            resp.raise_for_status()
            files = resp.json()
        except Exception as e:
            log.append(f"[ERROR] GitHub API 실패: {e}")
            return 0

        for f in files:
            if not (isinstance(f, dict) and f.get("type") == "file"
                    and f.get("name", "").endswith(".md")):
                continue

            raw_url = f"{GITHUB_RAW}/{owner}/{repo}/{branch}/{path}/{f['name']}"
            try:
                r = await client.get(raw_url)
                r.raise_for_status()
                content = r.text
            except Exception as e:
                log.append(f"  [SKIP] {f['name']}: {e}")
                continue

            # Remove markdown syntax for cleaner text
            text = re.sub(r"```[\s\S]*?```", "", content)
            text = re.sub(r"`[^`]+`", "", text)
            text = re.sub(r"#+\s+", "", text)
            text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)
            text = re.sub(r"[*_~]{1,3}", "", text)
            text = " ".join(text.split())

            if len(text) < 50:
                continue

            chunks = _chunk_text(text)
            url = f"https://github.com/{owner}/{repo}/blob/{branch}/{path}/{f['name']}"
            meta = {"url": url, "title": f["name"], "source": f"github:{owner}/{repo}"}

            stored = await _store_qdrant(chunks, meta, ollama)
            await _upsert_crawled_doc(db, url, f["name"], content, f"github:{owner}/{repo}")
            log.append(f"  ✓ {f['name']} → {len(chunks)}청크 (Qdrant {stored}건)")
            total += len(chunks)

    return total


async def crawl_url(
    url: str, db: AsyncSession, ollama: OllamaClient, log: list[str],
) -> int:
    """임의 URL 크롤링."""
    async with httpx.AsyncClient(
        timeout=30.0,
        follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0 (compatible; FinAgent/1.0)"},
        event_hooks={"request": [url_guard.guard_request]},  # Qurious: 리다이렉트로 옮겨 갈 주소도 보내기 전에 검사
    ) as client:
        try:
            resp = await client.get(url)
            resp.raise_for_status()
            html = resp.text
        except url_guard.BlockedHop:  # Qurious: 막힌 홉은 400 으로 — 아래가 삼켜 「0청크 · 성공」 이 되지 않게
            raise
        except Exception as e:
            log.append(f"[ERROR] {url}: {e}")
            return 0

    text = _extract_text(html)
    if len(text) < 100:
        log.append(f"[SKIP] 텍스트 추출 실패: {url}")
        return 0

    chunks = _chunk_text(text)
    title = re.search(r"<title[^>]*>([^<]+)</title>", html, re.I)
    title_text = title.group(1).strip() if title else url

    meta = {"url": url, "title": title_text, "source": "web"}
    stored = await _store_qdrant(chunks, meta, ollama)
    await _upsert_crawled_doc(db, url, title_text, text, "web")
    log.append(f"✓ {title_text[:50]} → {len(chunks)}청크 (Qdrant {stored}건)")
    return len(chunks)


async def crawl_naver_stock(
    code: str, db: AsyncSession, ollama: OllamaClient, log: list[str],
) -> int:
    """네이버 금융 종목 메인 페이지 전용 크롤링."""
    stock_code = re.sub(r"[^0-9]", "", code or "")
    if len(stock_code) != 6:
        log.append("[ERROR] 종목코드는 6자리 숫자여야 합니다. (예: 005930)")
        return 0

    url = f"https://finance.naver.com/item/main.naver?code={stock_code}"
    async with httpx.AsyncClient(
        timeout=20.0,
        follow_redirects=True,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; FinAgent/1.0)",
            "Referer": "https://finance.naver.com/",
        },
    ) as client:
        try:
            resp = await client.get(url)
            resp.raise_for_status()
            html = resp.text
        except Exception as e:
            log.append(f"[ERROR] 네이버 금융 요청 실패: {e}")
            return 0

    soup = BeautifulSoup(html, "html.parser")
    name = ""
    h2 = soup.select_one("div.wrap_company h2 a")
    if h2:
        name = h2.get_text(strip=True)

    current = ""
    no_today = soup.select_one("p.no_today span.blind")
    if no_today:
        current = no_today.get_text(strip=True)

    news_items = []
    for a in soup.select("div.section.new_bbs ul li a")[:10]:
        t = a.get("title") or a.get_text(strip=True)
        if t:
            news_items.append(t.strip())

    if not name and not news_items:
        log.append("[ERROR] 네이버 페이지 파싱 실패")
        return 0

    text = f"종목명: {name}\n현재가: {current}\n"
    if news_items:
        text += "주요 뉴스:\n" + "\n".join(f"- {n}" for n in news_items)

    chunks = _chunk_text(text)
    meta = {
        "url": url,
        "title": f"{name or stock_code} 네이버금융",
        "source": f"naver:stock:{stock_code}",
        "stock_code": stock_code,
    }
    stored = await _store_qdrant(chunks, meta, ollama)
    await _upsert_crawled_doc(db, url, meta["title"], text, meta["source"])
    log.append(f"✓ {meta['title']} → {len(chunks)}청크 (Qdrant {stored}건)")
    return len(chunks)


async def run_auto_crawl(db: AsyncSession, ollama: OllamaClient, log: list[str]) -> dict:
    """자동 크롤링 실행."""
    total_chunks = 0
    for target in CRAWL_TARGETS:
        log.append(f"\n[크롤링] {target['name']}")
        if target["type"] == "github_docs":
            n = await crawl_github_docs(
                target["owner"], target["repo"], target["branch"], target["path"],
                db, ollama, log,
            )
            total_chunks += n

    return {"total_chunks": total_chunks, "sources": len(CRAWL_TARGETS)}


async def qdrant_search(query: str, ollama: OllamaClient, top_k: int = 5) -> list[dict]:
    """Qdrant 벡터 검색."""
    # Qurious(2026-10-23 · DF-149 같은 꼴): 예전 `client.search` 는 qdrant-client 1.16 에서 없어져 늘 AttributeError → 빈 목록이었다.
    # 지금 부르는 곳은 없다(채팅 근거는 rag_pipeline.rag_search). 고쳐 두는 까닭 — 강사님 기초 코드의 함수라 되살아날 수 있다.
    # 모음이 없거나(아직 모은 글 없음) 닿지 못하면 빈 목록 + 기록(채팅 근거 검색과 같은 규칙) · 우리 코드 잘못은 올린다.
    try:
        qemb = await ollama.embed(settings.EMBED_MODEL, query)
        if not qemb:
            return []
        client = vector_db.async_client()
        try:
            if not await vector_db.exists(client, settings.QDRANT_COLLECTION):
                return []
            hits = await vector_db.query(client, settings.QDRANT_COLLECTION, qemb, limit=top_k)
        finally:
            await vector_db.aclose(client)
        return [{"text": h.payload.get("text", ""), "url": h.payload.get("url", ""),
                 "title": h.payload.get("title", ""), "score": h.score}
                for h in hits]
    except (vector_db.VectorDBUnavailable, vector_db.CollectionMissing, httpx.HTTPError) as e:
        _log().warning("크롤 조각 검색 실패: %s", e)
        return []
