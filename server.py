import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from scraper import search_ug, fetch_ug_chords, fetch_top_100, fetch_by_genre, GENRES
from functools import lru_cache

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class SearchRequest(BaseModel):
    query: str

class SongRequest(BaseModel):
    title: str
    artist: str
    ug_url: str = None

class GenreRequest(BaseModel):
    genre: str

# ── Cached functions ─────────────────────────────────────

@lru_cache(maxsize=200)
def cached_search(query: str):
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
def cached_versions(title: str, artist: str):
    return search_ug(title, artist)

@lru_cache(maxsize=200)
def cached_chords(title: str, artist: str, ug_url: str = None):
    if ug_url:
        result = fetch_ug_chords(ug_url)
        if result and result.get("sections"):
            return {
                "title": title, "artist": artist,
                "key": result.get("key", ""),
                "bpm": result.get("bpm"),
                "source": "ultimate-guitar",
                "sections": result["sections"],
            }
    # Auto-search UG
    versions = search_ug(title, artist)
    if versions:
        best = versions[0]
        result = fetch_ug_chords(best["url"])
        if result and result.get("sections"):
            return {
                "title": title, "artist": artist,
                "key": result.get("key", ""),
                "bpm": result.get("bpm"),
                "source": "ultimate-guitar",
                "sections": result["sections"],
            }
    raise ValueError(f"Could not find chord sheet for {title} by {artist} on Ultimate Guitar.")

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
    scrapeops_key = os.environ.get("SCRAPEOPS_API_KEY", "")
    return {
        "scrapeops_key_set": bool(scrapeops_key),
        "scrapeops_key_prefix": scrapeops_key[:12] + "..." if scrapeops_key else "NOT SET",
        "search_cache": cached_search.cache_info()._asdict(),
        "versions_cache": cached_versions.cache_info()._asdict(),
        "chords_cache": cached_chords.cache_info()._asdict(),
    }

@app.post("/search")
async def search(req: SearchRequest):
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")
    try:
        return cached_search(req.query.strip().lower())
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/versions")
async def versions(req: SongRequest):
    try:
        vers = cached_versions(req.title, req.artist)
        return {"versions": vers}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/chords")
async def chords(req: SongRequest):
    if not req.title.strip():
        raise HTTPException(status_code=400, detail="Title cannot be empty")
    try:
        return cached_chords(req.title, req.artist, req.ug_url or None)
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
