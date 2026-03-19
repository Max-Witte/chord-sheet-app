import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from lyrics import get_lyrics_and_chords_from_search, get_lyrics_and_chords_from_url
import anthropic

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")


class SearchRequest(BaseModel):
    query: str

class UrlRequest(BaseModel):
    url: str


@app.get("/")
def root():
    return {"status": "ok", "message": "Chord Sheet API is running"}


@app.get("/debug")
def debug():
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    return {
        "anthropic_key_set": bool(key),
        "anthropic_key_prefix": key[:12] + "..." if key else "NOT SET",
        "env_vars": [k for k in os.environ.keys() if "ANTHROPIC" in k or "API" in k],
    }


@app.post("/from-search")
async def from_search(req: SearchRequest):
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")
    try:
        result = get_lyrics_and_chords_from_search(req.query)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/from-url")
async def from_url(req: UrlRequest):
    if not req.url.strip():
        raise HTTPException(status_code=400, detail="URL cannot be empty")
    try:
        result = get_lyrics_and_chords_from_url(req.url)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
