import os
from functools import lru_cache

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from scraper import search_ug, fetch_ug_chords, fetch_top_100, fetch_by_genre, GENRES
from db_cache import (
    init_db, normalize_text,
    get_search_cache, set_search_cache,
    get_versions_cache, set_versions_cache,
    get_chords_cache, set_chords_cache,
)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class SearchRequest(BaseModel):
    query: str
    force_refresh: bool = False

class SongRequest(BaseModel):
    title: str
    artist: str
    ug_url: str = None
    force_refresh: bool = False

class GenreRequest(BaseModel):
    genre: str

@app.on_event("startup")
def startup_event():
    try:
        if os.environ.get("DATABASE_URL"):
            init_db()
            print("Database cache initialized")
        else:
            print("DATABASE_URL not set, running without persistent cache")
    except Exception as e:
        print(f"Database init failed: {e}")

# ── In-memory LRU cache (fast, session-only) ─────────────

@lru_cache(maxsize=200)
def _lru_search(query: str):
    versions = search_ug(query, "")
    if not versions:
        return {"type": "song", "artist_name": None, "results": []}
    seen = {}
    for v in versions:
        key = f"{v['artist'].lower()}|||{v['title'].lower()}"
        if key not in seen:
            seen[key] = {"title": v["title"], "artist": v["artist"], "versions_count": 1}
        else:
            seen[key]["versions_count"] += 1
    return {"type": "song", "artist_name": None, "results": list(seen.values())}

@lru_cache(maxsize=200)
def _lru_versions(title: str, artist: str):
    return search_ug(title, artist)

@lru_cache(maxsize=200)
def _lru_chords(title: str, artist: str, ug_url: str = None):
    if ug_url:
        result = fetch_ug_chords(ug_url)
        if result and result.get("sections"):
            return {"title": title, "artist": artist,
                    "key": result.get("key", ""), "bpm": result.get("bpm"),
                    "source": "ultimate-guitar", "sections": result["sections"]}
    versions = search_ug(title, artist)
    if versions:
        result = fetch_ug_chords(versions[0]["url"])
        if result and result.get("sections"):
            return {"title": title, "artist": artist,
                    "key": result.get("key", ""), "bpm": result.get("bpm"),
                    "source": "ultimate-guitar", "sections": result["sections"]}
    raise ValueError(f"Could not find chord sheet for {title} by {artist} on Ultimate Guitar.")

def invalidate_lru(title: str = None, artist: str = None, query: str = None):
    """Clear specific or all LRU cache entries on force refresh."""
    _lru_search.cache_clear()
    _lru_versions.cache_clear()
    _lru_chords.cache_clear()

_top100_cache = None

@lru_cache(maxsize=20)
def cached_genre(genre: str):
    return fetch_by_genre(genre)

# ── Routes ───────────────────────────────────────────────

@app.get("/")
def root():
    return {"status": "ok", "message": "Chord Sheet API is running"}

@app.get("/debug")
def debug():
    key = os.environ.get("SCRAPEOPS_API_KEY", "")
    return {
        "scrapeops_key_set": bool(key),
        "scrapeops_key_prefix": key[:12] + "..." if key else "NOT SET",
        "database_url_set": bool(os.environ.get("DATABASE_URL")),
        "lru_search": _lru_search.cache_info()._asdict(),
        "lru_versions": _lru_versions.cache_info()._asdict(),
        "lru_chords": _lru_chords.cache_info()._asdict(),
    }

@app.post("/search")
async def search(req: SearchRequest):
    query = normalize_text(req.query)
    if not query:
        raise HTTPException(status_code=400, detail="Query cannot be empty")
    try:
        if not req.force_refresh and os.environ.get("DATABASE_URL"):
            cached = get_search_cache(query)
            if cached is not None:
                return cached
        result = _lru_search(query)
        if os.environ.get("DATABASE_URL"):
            set_search_cache(query, result)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/versions")
async def versions(req: SongRequest):
    title = req.title.strip()
    artist = req.artist.strip()
    try:
        if not req.force_refresh and os.environ.get("DATABASE_URL"):
            cached = get_versions_cache(title, artist)
            if cached is not None:
                return {"versions": cached}
        if req.force_refresh:
            invalidate_lru()
        vers = _lru_versions(title, artist)
        if os.environ.get("DATABASE_URL"):
            set_versions_cache(title, artist, vers)
        return {"versions": vers}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/chords")
async def chords(req: SongRequest):
    title = req.title.strip()
    artist = req.artist.strip()
    if not title:
        raise HTTPException(status_code=400, detail="Title cannot be empty")
    try:
        if not req.force_refresh and os.environ.get("DATABASE_URL"):
            cached = get_chords_cache(title, artist)
            if cached is not None:
                return cached
        if req.force_refresh:
            invalidate_lru()
        result = _lru_chords(title, artist, req.ug_url or None)
        if os.environ.get("DATABASE_URL"):
            set_chords_cache(title, artist, req.ug_url or None, result)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/charts/top100")
async def top100():
    global _top100_cache
    if _top100_cache:
        return {"songs": _top100_cache}
    try:
        songs = fetch_top_100()
        if songs:
            _top100_cache = songs
        return {"songs": songs}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/charts/genres")
async def genres():
    return {"genres": GENRES}

@app.post("/charts/genre")
async def genre(req: GenreRequest):
    try:
        songs = cached_genre(req.genre)
        return {"songs": songs, "genre": req.genre}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
