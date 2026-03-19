import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from lyrics import get_lyrics_and_chords, search_songs

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
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")
    try:
        return search_songs(req.query)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/chords")
async def chords(req: SongRequest):
    if not req.title.strip():
        raise HTTPException(status_code=400, detail="Title cannot be empty")
    try:
        return get_lyrics_and_chords(req.title, req.artist)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
