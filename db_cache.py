import os
import re
from contextlib import contextmanager
import psycopg
from psycopg.types.json import Jsonb  # Required for JSONB columns

DATABASE_URL = os.environ.get("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable is not set")


def normalize_text(value: str) -> str:
    """Normalize text for consistent caching keys."""
    if not value:
        return ""
    value = value.strip().lower()
    value = re.sub(r"\s+", " ", value)
    return value


@contextmanager
def get_conn():
    """Context manager for database connections with auto-close."""
    conn = None
    try:
        # psycopg 3.x connect – automatically uses SSL if ?sslmode= is present
        conn = psycopg.connect(DATABASE_URL, connect_timeout=15)
        yield conn
    except psycopg.Error as e:
        print(f"Database connection error: {e}")
        raise
    finally:
        if conn:
            conn.close()


def init_db():
    """Create cache tables if they don't exist."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            # search_cache – simple query → JSON response
            cur.execute("""
                CREATE TABLE IF NOT EXISTS search_cache (
                    id BIGSERIAL PRIMARY KEY,
                    query_normalized TEXT UNIQUE NOT NULL,
                    response_json JSONB NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                );
            """)

            # versions_cache – title/artist → list of versions
            cur.execute("""
                CREATE TABLE IF NOT EXISTS versions_cache (
                    id BIGSERIAL PRIMARY KEY,
                    title_normalized TEXT NOT NULL,
                    artist_normalized TEXT NOT NULL,
                    response_json JSONB NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE (title_normalized, artist_normalized)
                );
            """)

            # chords_cache – title/artist → parsed chords + metadata
            cur.execute("""
                CREATE TABLE IF NOT EXISTS chords_cache (
                    id BIGSERIAL PRIMARY KEY,
                    title_normalized TEXT NOT NULL,
                    artist_normalized TEXT NOT NULL,
                    ug_url TEXT,
                    response_json JSONB NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE (title_normalized, artist_normalized)
                );
            """)

        conn.commit()
        print("Database tables initialized (or already exist)")


def get_search_cache(query: str) -> dict | None:
    """Retrieve cached search results for a normalized query."""
    query_normalized = normalize_text(query)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT response_json
                FROM search_cache
                WHERE query_normalized = %s
            """, (query_normalized,))
            row = cur.fetchone()
            return row[0] if row else None


def set_search_cache(query: str, response: dict):
    """Cache search results (response must be JSON-serializable dict)."""
    query_normalized = normalize_text(query)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO search_cache (query_normalized, response_json, updated_at)
                VALUES (%s, %s, NOW())
                ON CONFLICT (query_normalized)
                DO UPDATE SET
                    response_json = EXCLUDED.response_json,
                    updated_at = NOW()
            """, (query_normalized, Jsonb(response)))
        conn.commit()


def get_versions_cache(title: str, artist: str) -> dict | None:
    """Get cached versions for a song."""
    title_n = normalize_text(title)
    artist_n = normalize_text(artist)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT response_json
                FROM versions_cache
                WHERE title_normalized = %s AND artist_normalized = %s
            """, (title_n, artist_n))
            row = cur.fetchone()
            return row[0] if row else None


def set_versions_cache(title: str, artist: str, response: dict):
    """Cache song versions list."""
    title_n = normalize_text(title)
    artist_n = normalize_text(artist)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO versions_cache (
                    title_normalized, artist_normalized, response_json, updated_at
                )
                VALUES (%s, %s, %s, NOW())
                ON CONFLICT (title_normalized, artist_normalized)
                DO UPDATE SET
                    response_json = EXCLUDED.response_json,
                    updated_at = NOW()
            """, (title_n, artist_n, Jsonb(response)))
        conn.commit()


def get_chords_cache(title: str, artist: str) -> dict | None:
    """Get cached chords for a song version."""
    title_n = normalize_text(title)
    artist_n = normalize_text(artist)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT response_json
                FROM chords_cache
                WHERE title_normalized = %s AND artist_normalized = %s
            """, (title_n, artist_n))
            row = cur.fetchone()
            return row[0] if row else None


def set_chords_cache(title: str, artist: str, ug_url: str | None, response: dict):
    """Cache parsed chords + metadata."""
    title_n = normalize_text(title)
    artist_n = normalize_text(artist)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO chords_cache (
                    title_normalized, artist_normalized, ug_url, response_json, updated_at
                )
                VALUES (%s, %s, %s, %s, NOW())
                ON CONFLICT (title_normalized, artist_normalized)
                DO UPDATE SET
                    ug_url = EXCLUDED.ug_url,
                    response_json = EXCLUDED.response_json,
                    updated_at = NOW()
            """, (title_n, artist_n, ug_url, Jsonb(response)))
        conn.commit()
