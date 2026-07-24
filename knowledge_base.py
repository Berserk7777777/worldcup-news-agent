import hashlib
import json
import math
import re
import sqlite3
import time
import unicodedata
import xml.etree.ElementTree as ET
from array import array
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlunparse
from urllib.robotparser import RobotFileParser

import requests

from rag_sources import SOURCES, SourceConfig, sources_for_query
from siliconflow_client import SiliconFlowClient


DB_PATH = Path("data/worldcup_knowledge.db")
USER_AGENT = (
    "Mozilla/5.0 (compatible; WorldCupNewsKnowledgeBot/1.0; "
    "local educational research)"
)
WORLD_CUP_TERMS = (
    "world cup",
    "fifa world cup",
    "mundial",
    "copa del mundo",
    "世界杯",
    "世预赛",
    "world-cup",
)
LIVE_SEARCH_CUES = (
    "名场面",
    "具体比赛",
    "进球",
    "助攻",
    "关键时刻",
    "比赛表现",
    "赛果",
    "比分",
    "数据",
    "纪录",
    "记录",
    "盘点",
    "两个",
    "两场",
)
SEARCH_STOPWORDS = {
    "2026",
    "fifa",
    "world",
    "cup",
    "news",
    "best",
    "memorable",
    "moments",
    "about",
    "match",
    "matches",
    "report",
    "reports",
    "highlights",
    "goal",
    "goals",
    "assist",
    "assists",
    "record",
    "records",
    "stats",
    "statistics",
}
FIFA_SITEMAP_URL = "https://www.fifa.com/sitemap"
FIFA_SITEMAP_PREFIX = (
    "https://cxm-api.fifa.com/fifaplusweb/api/sitemaps/articles/"
)
_SITEMAP_CACHE = {"expires_at": 0.0, "entries": []}


@dataclass
class Article:
    source: SourceConfig
    url: str
    title: str
    published_at: str
    language: str
    content: str


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta = {}
        self.links = []
        self.paragraphs = []
        self.title_parts = []
        self._skip = 0
        self._tag = ""
        self._text = []
        self._href = ""
        self._script_type = ""
        self._scripts = []

    def handle_starttag(self, tag, attrs) -> None:
        attrs = dict(attrs)
        if tag in {"style", "noscript", "svg"}:
            self._skip += 1
        if tag == "script":
            self._script_type = attrs.get("type", "")
            if self._script_type != "application/ld+json":
                self._skip += 1
        if self._skip:
            return
        if tag == "meta":
            key = (
                attrs.get("property")
                or attrs.get("name")
                or attrs.get("itemprop")
                or ""
            ).lower()
            if key and attrs.get("content"):
                self.meta[key] = attrs["content"].strip()
        if tag in {"p", "h1", "h2", "title", "a", "time"}:
            self._tag = tag
            self._text = []
            self._href = attrs.get("href", "") if tag == "a" else ""
            if tag == "time" and attrs.get("datetime"):
                self.meta.setdefault("datetime", attrs["datetime"])

    def handle_endtag(self, tag) -> None:
        if tag in {"style", "noscript", "svg"} and self._skip:
            self._skip -= 1
            return
        if tag == "script":
            if self._script_type == "application/ld+json" and self._text:
                self._scripts.append(" ".join(self._text))
            elif self._skip:
                self._skip -= 1
            self._script_type = ""
            self._text = []
            return
        if self._skip or tag != self._tag:
            return
        text = re.sub(r"\s+", " ", " ".join(self._text)).strip()
        if tag == "title" and text:
            self.title_parts.append(text)
        elif tag == "a" and self._href and text:
            self.links.append((self._href, text))
        elif tag in {"p", "h1", "h2"} and len(text) >= 20:
            self.paragraphs.append(text)
        self._tag = ""
        self._text = []
        self._href = ""

    def handle_data(self, data) -> None:
        if not self._skip and (self._tag or self._script_type == "application/ld+json"):
            text = data.strip()
            if text:
                self._text.append(text)

    def article_body(self) -> str:
        for script in self._scripts:
            try:
                payload = json.loads(script)
            except json.JSONDecodeError:
                continue
            records = payload if isinstance(payload, list) else [payload]
            for record in records:
                if isinstance(record, dict) and record.get("articleBody"):
                    return re.sub(r"\s+", " ", str(record["articleBody"])).strip()
        unique = list(dict.fromkeys(self.paragraphs))
        return "\n\n".join(unique)


def _canonical_url(url: str) -> str:
    parsed = urlparse(url)
    return urlunparse(
        (parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/"), "", "", "")
    )


def _allowed_url(url: str, source: SourceConfig) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    source_host = source.domain.lower()
    if parsed.scheme not in {"http", "https"}:
        return False
    if not (
        host == source_host
        or host.endswith("." + source_host)
        or source_host.endswith("." + host)
    ):
        return False
    return not parsed.path.lower().endswith(
        (".pdf", ".jpg", ".jpeg", ".png", ".webp", ".mp4", ".zip")
    )


def _is_relevant(text: str, query: str = "") -> bool:
    lowered = text.lower()
    if any(term in lowered for term in WORLD_CUP_TERMS):
        return True
    query_terms = [
        term.lower()
        for term in re.findall(r"[A-Za-z0-9]{3,}|[\u4e00-\u9fff]{2,}", query)
        if not term.isdigit()
    ]
    return any(term in lowered for term in query_terms)


def _search_words(value: str) -> list[str]:
    normalized = unicodedata.normalize("NFKD", value).encode(
        "ascii", "ignore"
    ).decode("ascii").lower()
    return [
        word
        for word in re.findall(r"[a-z0-9]{3,}", normalized)
        if word not in SEARCH_STOPWORDS
    ]


def _rank_sitemap_entries(
    entries: list[tuple[str, str]], search_query: str, limit: int = 4
) -> list[str]:
    words = list(dict.fromkeys(_search_words(search_query)))
    ranked = []
    for url, last_modified in entries:
        searchable = unicodedata.normalize("NFKD", url).encode(
            "ascii", "ignore"
        ).decode("ascii").lower()
        score = sum(word in searchable for word in words)
        if score:
            ranked.append((score, last_modified, url))
    ranked.sort(reverse=True)
    return [url for _, _, url in ranked[:limit]]


def _should_search_live(query: str, items: list[dict]) -> bool:
    if len(items) < 3 or (items and items[0]["retrieval_score"] < 0.45):
        return True
    return any(cue in query for cue in LIVE_SEARCH_CUES)


def _prioritize_urls(items: list[dict], preferred_urls: set[str]) -> list[dict]:
    if not preferred_urls:
        return items
    items.sort(
        key=lambda item: (
            item["source_url"] in preferred_urls,
            item["retrieval_score"],
        ),
        reverse=True,
    )
    for rank, item in enumerate(items, 1):
        item["rank"] = rank
    return items


def _detect_language(text: str, configured: str) -> str:
    if configured == "zh":
        return "zh"
    chinese = len(re.findall(r"[\u4e00-\u9fff]", text[:2000]))
    return "zh" if chinese > 80 else configured


def _normalize_date(value: str, text: str = "") -> str:
    candidates = [value, text[:200000]]
    patterns = [
        r"(20(?:2[4-9]|3\d))[-/.年](\d{1,2})[-/.月](\d{1,2})",
        r"(20(?:2[4-9]|3\d))-(\d{2})-(\d{2})T",
    ]
    for candidate in candidates:
        for pattern in patterns:
            match = re.search(pattern, candidate or "")
            if match:
                year, month, day = (int(part) for part in match.groups())
                try:
                    return datetime(year, month, day).date().isoformat()
                except ValueError:
                    pass
        for date_format, pattern in (
            ("%d %B %Y", r"\b(\d{1,2} [A-Z][a-z]+ 20\d{2})\b"),
            ("%B %d, %Y", r"\b([A-Z][a-z]+ \d{1,2}, 20\d{2})\b"),
        ):
            match = re.search(pattern, candidate or "")
            if match:
                try:
                    return datetime.strptime(match.group(1), date_format).date().isoformat()
                except ValueError:
                    pass
    return ""


def _parse_page(source: SourceConfig, url: str, html_text: str) -> tuple[Article, list]:
    parser = _PageParser()
    parser.feed(html_text)
    title = (
        parser.meta.get("og:title")
        or parser.meta.get("twitter:title")
        or (parser.title_parts[0] if parser.title_parts else "")
    )
    content = parser.article_body()
    date_value = next(
        (
            parser.meta[key]
            for key in (
                "article:published_time",
                "datepublished",
                "publishdate",
                "date",
                "datetime",
            )
            if parser.meta.get(key)
        ),
        "",
    )
    published_at = _normalize_date(date_value, html_text)
    article = Article(
        source=source,
        url=_canonical_url(url),
        title=re.sub(r"\s+", " ", title).strip()[:500],
        published_at=published_at,
        language=_detect_language(content, source.language),
        content=content,
    )
    links = [
        (_canonical_url(urljoin(url, href)), text)
        for href, text in parser.links
        if _allowed_url(urljoin(url, href), source)
    ]
    return article, links


def split_text(text: str, max_chars: int = 1200, overlap: int = 150) -> list[str]:
    paragraphs = [part.strip() for part in re.split(r"\n{2,}", text) if part.strip()]
    chunks = []
    current = ""
    for paragraph in paragraphs:
        pieces = [
            paragraph[index : index + max_chars]
            for index in range(0, len(paragraph), max_chars)
        ]
        for piece in pieces:
            candidate = f"{current}\n\n{piece}".strip() if current else piece
            if len(candidate) <= max_chars:
                current = candidate
                continue
            if current:
                chunks.append(current)
                current = f"{current[-overlap:]}\n\n{piece}".strip()
            else:
                chunks.append(piece)
    if current:
        chunks.append(current)
    return chunks


def _vector_blob(values: list[float]) -> bytes:
    return array("f", values).tobytes()


def _blob_vector(value: bytes) -> array:
    vector = array("f")
    vector.frombytes(value)
    return vector


def _cosine(left, right) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    norm_left = math.sqrt(sum(value * value for value in left))
    norm_right = math.sqrt(sum(value * value for value in right))
    return dot / (norm_left * norm_right) if norm_left and norm_right else 0.0


class KnowledgeBase:
    def __init__(self, path: Path = DB_PATH) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=30000")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS documents (
                    id INTEGER PRIMARY KEY,
                    source_key TEXT NOT NULL,
                    source_name TEXT NOT NULL,
                    source_level TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    language TEXT NOT NULL,
                    url TEXT NOT NULL UNIQUE,
                    title TEXT NOT NULL,
                    published_at TEXT,
                    content TEXT NOT NULL,
                    summary_zh TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS chunks (
                    id INTEGER PRIMARY KEY,
                    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                    chunk_index INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    embedding BLOB NOT NULL,
                    embedding_model TEXT NOT NULL,
                    UNIQUE(document_id, chunk_index)
                );
                CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
                    chunk_id UNINDEXED,
                    title,
                    content,
                    summary_zh,
                    tokenize='trigram'
                );
                CREATE INDEX IF NOT EXISTS idx_documents_source ON documents(source_key);
                CREATE INDEX IF NOT EXISTS idx_documents_published ON documents(published_at);
                CREATE INDEX IF NOT EXISTS idx_chunks_document ON chunks(document_id);
                """
            )

    def status(self) -> dict:
        with self.connect() as connection:
            documents = connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
            chunks = connection.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
            last_row = connection.execute(
                "SELECT value FROM metadata WHERE key='last_updated'"
            ).fetchone()
            levels = {
                row["source_level"]: row["count"]
                for row in connection.execute(
                    "SELECT source_level, COUNT(*) AS count FROM documents GROUP BY source_level"
                )
            }
        return {
            "documents": documents,
            "chunks": chunks,
            "last_updated": last_row["value"] if last_row else "",
            "level_a": levels.get("A", 0),
            "level_b": levels.get("B", 0),
        }

    def existing_hash(self, url: str) -> str:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT content_hash FROM documents WHERE url=?", (_canonical_url(url),)
            ).fetchone()
        return row["content_hash"] if row else ""

    def refresh_article_metadata(self, article: Article) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE documents SET title=?, published_at=?, fetched_at=?
                WHERE url=?
                """,
                (
                    article.title,
                    article.published_at,
                    datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    article.url,
                ),
            )

    def save_article(
        self,
        article: Article,
        summary_zh: str,
        chunks: list[str],
        embeddings: list[list[float]],
        embedding_model: str,
    ) -> str:
        content_hash = hashlib.sha256(article.content.encode("utf-8")).hexdigest()
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self.connect() as connection:
            existing = connection.execute(
                "SELECT id, content_hash FROM documents WHERE url=?", (article.url,)
            ).fetchone()
            if existing and existing["content_hash"] == content_hash:
                connection.execute(
                    "UPDATE documents SET fetched_at=? WHERE id=?", (now, existing["id"])
                )
                return "skipped"
            if existing:
                document_id = existing["id"]
                chunk_ids = [
                    row["id"]
                    for row in connection.execute(
                        "SELECT id FROM chunks WHERE document_id=?", (document_id,)
                    )
                ]
                connection.executemany(
                    "DELETE FROM chunks_fts WHERE chunk_id=?",
                    [(str(chunk_id),) for chunk_id in chunk_ids],
                )
                connection.execute("DELETE FROM chunks WHERE document_id=?", (document_id,))
                connection.execute(
                    """
                    UPDATE documents SET source_key=?, source_name=?, source_level=?,
                    source_type=?, language=?, title=?, published_at=?, content=?,
                    summary_zh=?, content_hash=?, fetched_at=?, updated_at=? WHERE id=?
                    """,
                    (
                        article.source.key,
                        article.source.name,
                        article.source.level,
                        article.source.source_type,
                        article.language,
                        article.title,
                        article.published_at,
                        article.content,
                        summary_zh,
                        content_hash,
                        now,
                        now,
                        document_id,
                    ),
                )
                state = "updated"
            else:
                cursor = connection.execute(
                    """
                    INSERT INTO documents (
                        source_key, source_name, source_level, source_type, language,
                        url, title, published_at, content, summary_zh, content_hash,
                        fetched_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        article.source.key,
                        article.source.name,
                        article.source.level,
                        article.source.source_type,
                        article.language,
                        article.url,
                        article.title,
                        article.published_at,
                        article.content,
                        summary_zh,
                        content_hash,
                        now,
                        now,
                    ),
                )
                document_id = cursor.lastrowid
                state = "new"
            for index, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
                cursor = connection.execute(
                    """
                    INSERT INTO chunks (
                        document_id, chunk_index, content, embedding, embedding_model
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        document_id,
                        index,
                        chunk,
                        _vector_blob(embedding),
                        embedding_model,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO chunks_fts (chunk_id, title, content, summary_zh)
                    VALUES (?, ?, ?, ?)
                    """,
                    (str(cursor.lastrowid), article.title, chunk, summary_zh),
                )
        return state

    def mark_updated(self) -> str:
        value = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO metadata(key, value) VALUES('last_updated', ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """,
                (value,),
            )
        return value

    def search(self, query: str, client: SiliconFlowClient, limit: int = 6) -> list[dict]:
        with self.connect() as connection:
            count = connection.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        if not count:
            return []

        query_vector = client.embed_texts([query])[0]
        keyword_scores = {}
        cleaned = re.sub(r"[^\w\u4e00-\u9fff ]+", " ", query).strip()
        if len(cleaned) >= 3:
            try:
                with self.connect() as connection:
                    rows = connection.execute(
                        """
                        SELECT chunk_id, bm25(chunks_fts) AS score
                        FROM chunks_fts WHERE chunks_fts MATCH ? ORDER BY score LIMIT 30
                        """,
                        (f'"{cleaned}"',),
                    )
                    keyword_scores = {
                        int(row["chunk_id"]): 1 / (1 + abs(row["score"])) for row in rows
                    }
            except sqlite3.OperationalError:
                keyword_scores = {}

        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT c.id AS chunk_id, c.content, c.embedding, d.*
                FROM chunks c JOIN documents d ON d.id=c.document_id
                """
            ).fetchall()

        now = datetime.now(timezone.utc).date()
        ranked = []
        for row in rows:
            semantic = max(0.0, _cosine(query_vector, _blob_vector(row["embedding"])))
            keyword = keyword_scores.get(row["chunk_id"], 0.0)
            source_score = 1.0 if row["source_level"] == "A" else 0.7
            recency = 0.35
            if row["published_at"]:
                try:
                    age = max(0, (now - datetime.fromisoformat(row["published_at"]).date()).days)
                    recency = max(0.0, 1 - age / 900)
                except ValueError:
                    pass
            total = 0.55 * semantic + 0.25 * keyword + 0.12 * source_score + 0.08 * recency
            ranked.append((total, semantic, keyword, row))
        ranked.sort(key=lambda item: item[0], reverse=True)

        results = []
        seen_documents = set()
        for score, semantic, keyword, row in ranked:
            if semantic < 0.42 and keyword == 0:
                continue
            if row["id"] in seen_documents:
                continue
            seen_documents.add(row["id"])
            results.append(
                {
                    "document_id": str(row["id"]),
                    "document_title": row["title"],
                    "source_name": row["source_name"],
                    "source_level": row["source_level"],
                    "source_type": (
                        "official"
                        if row["source_type"]
                        in {"official", "federation", "confederation"}
                        else "government"
                        if row["source_type"] in {"host_city", "statistics"}
                        else "news_agency"
                        if row["source_name"] in {"Associated Press", "Reuters"}
                        else "sports_media"
                    ),
                    "source_url": row["url"],
                    "published_at": row["published_at"],
                    "language": row["language"],
                    "summary_zh": row["summary_zh"],
                    "chunk_preview": row["content"][:1800],
                    "retrieval_score": round(score, 4),
                    "rerank_score": round(semantic, 4),
                    "keyword_score": round(keyword, 4),
                    "used_in_answer": True,
                    "metadata": {"source_level": row["source_level"]},
                }
            )
            if len(results) >= limit:
                break
        for rank, item in enumerate(results, 1):
            item["rank"] = rank
        return results


class KnowledgeUpdater:
    def __init__(
        self,
        settings,
        database: KnowledgeBase | None = None,
        progress_callback=None,
        session: requests.Session | None = None,
    ) -> None:
        self.settings = settings
        self.database = database or KnowledgeBase()
        self.progress_callback = progress_callback
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        self.client = SiliconFlowClient(settings)
        self._discovery_failures = 0
        self._robots = {}

    def _notify(self, source: str, message: str, state: str) -> None:
        if self.progress_callback:
            self.progress_callback(source, message, state)

    def _fetch(self, url: str) -> tuple[str, str]:
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin not in self._robots:
            parser = RobotFileParser()
            try:
                response = self.session.get(
                    f"{origin}/robots.txt",
                    timeout=min(self.settings.request_timeout, 15),
                )
                parser.parse(response.text.splitlines() if response.ok else [])
            except requests.RequestException:
                parser.parse([])
            self._robots[origin] = parser
        if not self._robots[origin].can_fetch(USER_AGENT, url):
            raise PermissionError("robots.txt 不允许抓取此页面")
        response = self.session.get(url, timeout=min(self.settings.request_timeout, 30))
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "")
        if "html" not in content_type.lower() and not response.text.lstrip().startswith("<"):
            raise ValueError("页面不是HTML")
        if not response.encoding or response.encoding.lower() == "iso-8859-1":
            response.encoding = response.apparent_encoding or "utf-8"
        return response.url, response.text

    def _recent_fifa_entries(self) -> list[tuple[str, str]]:
        if _SITEMAP_CACHE["expires_at"] > time.time():
            return list(_SITEMAP_CACHE["entries"])

        response = self.session.get(
            FIFA_SITEMAP_URL,
            timeout=min(self.settings.request_timeout, 30),
        )
        response.raise_for_status()
        root = ET.fromstring(response.content)
        sitemap_urls = [
            node.text
            for node in root.findall(".//{*}loc")
            if node.text and node.text.startswith(FIFA_SITEMAP_PREFIX)
        ]
        sitemap_urls.sort(
            key=lambda url: int(url.removeprefix(FIFA_SITEMAP_PREFIX))
        )

        source = next(item for item in SOURCES if item.key == "fifa_world_cup")
        entries = []
        for sitemap_url in sitemap_urls[:5]:
            response = self.session.get(
                sitemap_url,
                timeout=min(self.settings.request_timeout, 30),
            )
            response.raise_for_status()
            child_root = ET.fromstring(response.content)
            for node in child_root.findall(".//{*}url"):
                location = node.findtext("{*}loc", "")
                last_modified = node.findtext("{*}lastmod", "")
                if location and _allowed_url(location, source):
                    entries.append((location, last_modified))

        # ponytail: process-local TTL is enough; use persistent sitemap cache only if needed.
        _SITEMAP_CACHE.update(
            expires_at=time.time() + 900,
            entries=entries,
        )
        return list(entries)

    def search_official(self, query: str, max_articles: int = 4) -> dict:
        stats = {
            "new": 0,
            "updated": 0,
            "skipped": 0,
            "failed": 0,
            "found": 0,
            "urls": [],
        }
        source = next(item for item in SOURCES if item.key == "fifa_world_cup")
        self._notify("实时搜索", "正在搜索 FIFA 官方最新文章", "running")
        try:
            search_query = self.client.build_search_query(query)
            entries = self._recent_fifa_entries()
            urls = _rank_sitemap_entries(entries, search_query, max_articles)
        except Exception as error:
            stats["failed"] += 1
            self._notify(
                "实时搜索",
                f"FIFA 官方搜索失败：{str(error)[:120]}",
                "failed",
            )
            return stats

        articles = []
        for url in urls:
            try:
                article_url, article_html = self._fetch(
                    f"{url}?_escaped_fragment_="
                )
                if not _allowed_url(article_url, source):
                    raise ValueError("文章跳转到白名单域名之外")
                article, _ = _parse_page(source, article_url, article_html)
                if len(article.content) >= 300 and article.title:
                    articles.append(article)
            except Exception as error:
                stats["failed"] += 1
                self._notify(
                    source.name,
                    f"搜索结果抓取失败：{str(error)[:120]}",
                    "failed",
                )

        stats["found"] = len(articles)
        stats["urls"] = [article.url for article in articles]
        self._save_articles(articles, stats)
        if articles:
            stats["last_updated"] = self.database.mark_updated()
        self._notify(
            "实时搜索",
            f"FIFA 官方搜索完成，找到 {len(articles)} 篇相关文章",
            "completed",
        )
        return stats

    def _discover(
        self, source: SourceConfig, max_articles: int, query: str
    ) -> list[Article]:
        self._discovery_failures = 0
        final_url, html_text = self._fetch(source.seed_url)
        if not _allowed_url(final_url, source):
            raise ValueError("入口页面跳转到白名单域名之外")
        seed_article, links = _parse_page(source, final_url, html_text)
        candidates = []
        if source.source_type in {"statistics", "host_city"} and len(seed_article.content) >= 300:
            candidates.append(seed_article)
        relevant_links = [
            (url, text)
            for url, text in links
            if _is_relevant(f"{url} {text}", query)
        ]
        for url, _ in list(dict.fromkeys(relevant_links))[:max_articles]:
            try:
                article_url, article_html = self._fetch(url)
                if not _allowed_url(article_url, source):
                    raise ValueError("文章跳转到白名单域名之外")
                article, _ = _parse_page(source, article_url, article_html)
            except Exception as error:
                self._discovery_failures += 1
                self._notify(
                    source.name,
                    f"文章抓取失败：{str(error)[:120]}",
                    "failed",
                )
                continue
            if len(article.content) < 300 or not article.title:
                continue
            if article.published_at and article.published_at < "2024-01-01":
                continue
            if not _is_relevant(
                f"{article.title} {article.content[:1500]}", query
            ) and source.source_type != "statistics":
                continue
            candidates.append(article)
        deduplicated = {}
        for article in candidates:
            deduplicated[article.url] = article
        return list(deduplicated.values())[:max_articles]

    def _save_articles(self, articles: list[Article], stats: dict) -> None:
        for article in articles:
            content_hash = hashlib.sha256(article.content.encode("utf-8")).hexdigest()
            if self.database.existing_hash(article.url) == content_hash:
                self.database.refresh_article_metadata(article)
                stats["skipped"] += 1
                continue
            try:
                summary = (
                    article.content[:350]
                    if article.language == "zh"
                    else self.client.summarize_to_chinese(
                        article.title, article.content
                    )
                )
                chunks = split_text(article.content)
                embeddings = []
                for index in range(0, len(chunks), 16):
                    embeddings.extend(
                        self.client.embed_texts(chunks[index : index + 16])
                    )
                state = self.database.save_article(
                    article,
                    summary,
                    chunks,
                    embeddings,
                    self.settings.embedding_model,
                )
                stats[state] += 1
            except Exception as error:
                stats["failed"] += 1
                self._notify(
                    article.source.name,
                    f"{article.title[:40]} 处理失败：{error}",
                    "failed",
                )

    def update(
        self,
        sources: list[SourceConfig] | None = None,
        max_articles_per_source: int = 4,
        query: str = "",
    ) -> dict:
        stats = {"new": 0, "updated": 0, "skipped": 0, "failed": 0}
        selected_sources = sources or SOURCES
        for source in selected_sources:
            self._notify(source.name, f"正在抓取 {source.name}", "running")
            try:
                articles = self._discover(source, max_articles_per_source, query)
            except Exception as error:
                stats["failed"] += 1
                self._notify(source.name, f"{source.name} 抓取失败：{error}", "failed")
                continue
            stats["failed"] += self._discovery_failures
            self._save_articles(articles, stats)
            self._notify(
                source.name,
                f"{source.name} 完成，发现 {len(articles)} 篇相关文章",
                "completed",
            )
        stats["last_updated"] = self.database.mark_updated()
        return stats


def format_retrieval_context(items: list[dict]) -> str:
    if not items:
        return ""
    sections = ["以下是从白名单知识库检索到的证据。正文事实必须使用对应编号引用："]
    for index, item in enumerate(items, 1):
        sections.append(
            f"[{index}] 来源等级：{item['source_level']}\n"
            f"来源：{item['source_name']}\n"
            f"标题：{item['document_title']}\n"
            f"发布日期：{item['published_at'] or '未标注'}\n"
            f"原始链接：{item['source_url']}\n"
            f"中文摘要：{item['summary_zh']}\n"
            f"原文摘录：{item['chunk_preview']}"
        )
    sections.append(
        "引用清单格式：[编号] 来源，《文章标题》，发布日期，原始链接。"
    )
    return "\n\n".join(sections)


def retrieve_for_topic(
    query: str,
    settings,
    limit: int = 6,
    realtime: bool = True,
    progress_callback=None,
) -> tuple[list[dict], bool]:
    database = KnowledgeBase()
    client = SiliconFlowClient(settings)
    items = database.search(query, client, limit)
    refreshed = False
    preferred_urls = set()
    if realtime and _should_search_live(query, items):
        updater = KnowledgeUpdater(settings, database, progress_callback)
        search_stats = updater.search_official(query)
        preferred_urls.update(search_stats.get("urls", []))
        available = sum(
            search_stats[key] for key in ("new", "updated", "skipped")
        )
        if not available:
            updater.update(
                sources=sources_for_query(query),
                max_articles_per_source=2,
                query=query,
            )
        items = database.search(query, client, limit)
        refreshed = True
    return _prioritize_urls(items, preferred_urls), refreshed
