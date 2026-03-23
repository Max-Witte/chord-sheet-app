import os
import re
from contextlib import contextmanager
import psycopg


DATABASE_URL = os.environ.get("DATABASE_URL")


def normalize_text(value: str) -> str:
    if not value:
        return ""
    value = value.strip().lower()
    value = re.sub(r"\s+", " ", value)
    return value


@contextmanager
def get_conn():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set")
    conn = psycopg.connect(DATABASE_URL)
    try:
        yield conn
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS search_cache (
                    id BIGSERIAL PRIMARY KEY,
                    query_normalized TEXT UNIQUE NOT NULL,
                    response_json JSONB NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS versions_cache (
                    id BIGSERIAL PRIMARY KEY,
                    title_normalized TEXT NOT NULL,
                    artist_normalized TEXT NOT NULL,
                    response_json JSONB NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE (title_normalized, artist_normalized)
                )
            """)

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
                )
            """)
        conn.commit()


def get_search_cache(query: str):
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


def set_search_cache(query: str, response):
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
            """, (query_normalized, response))
        conn.commit()


def get_versions_cache(title: str, artist: str):
    title_normalized = normalize_text(title)
    artist_normalized = normalize_text(artist)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT response_json
                FROM versions_cache
                WHERE title_normalized = %s AND artist_normalized = %s
            """, (title_normalized, artist_normalized))
            row = cur.fetchone()
            return row[0] if row else None


def set_versions_cache(title: str, artist: str, response):
    title_normalized = normalize_text(title)
    artist_normalized = normalize_text(artist)
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
            """, (title_normalized, artist_normalized, response))
        conn.commit()


def get_chords_cache(title: str, artist: str):
    title_normalized = normalize_text(title)
    artist_normalized = normalize_text(artist)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT response_json
                FROM chords_cache
                WHERE title_normalized = %s AND artist_normalized = %s
            """, (title_normalized, artist_normalized))
            row = cur.fetchone()
            return row[0] if row else None


def set_chords_cache(title: str, artist: str, ug_url: str, response):
    title_normalized = normalize_text(title)
    artist_normalized = normalize_text(artist)
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
            """, (title_normalized, artist_normalized, ug_url, response))
        conn.commit()
