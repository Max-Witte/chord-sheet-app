import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from lyrics import get_lyrics_and_chords, search_songs_gemini
from scraper import search_ug, fetch_ug_chords

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

@app.get("/")
def root():
    return {"status": "ok", "message": "Chord Sheet API is running"}

@app.get("/debug")
def debug():
    key = os.environ.get("GEMINI_API_KEY", "")
    return {
        "gemini_key_set": bool(key),
        "gemini_key_prefix": key[:12] + "..." if key else "NOT SET",
        "env_vars": [k for k in os.environ.keys() if "GEMINI" in k or "API" in k],
    }

@app.post("/search")
async def search(req: SearchRequest):
    """Search UG directly for songs/artists."""
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")
    try:
        versions = search_ug(req.query, "")
        if not versions:
            # Fall back to Gemini if UG returns nothing
            return search_songs_gemini(req.query)

        # Group results by artist+title, deduplicate
        seen = {}
        for v in versions:
            key = f"{v['artist'].lower()}|||{v['title'].lower()}"
            if key not in seen:
                seen[key] = {
                    "title": v["title"],
                    "artist": v["artist"],
                    "versions_count": 1,
                }
            else:
                seen[key]["versions_count"] += 1

        results = list(seen.values())
        return {"type": "song", "artist_name": None, "results": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/versions")
async def versions(req: SongRequest):
    """Get all UG versions for a specific song."""
    try:
        vers = search_ug(req.title, req.artist)
        return {"versions": vers}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/chords")
async def chords(req: SongRequest):
    """Get chord sheet — from UG URL if provided, else auto-search UG."""
    if not req.title.strip():
        raise HTTPException(status_code=400, detail="Title cannot be empty")
    try:
        return get_lyrics_and_chords(req.title, req.artist, req.ug_url)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
