import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.websockets import WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from lyrics import get_lyrics_and_chords, search_songs_gemini
from scraper import search_ug, fetch_ug_chords, fetch_top_100, fetch_by_genre, GENRES
import json
import random
import string
from functools import lru_cache

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Room management for share feature ───────────────────
rooms = {}  # room_code -> {host, clients: [ws], state: {song, scroll, playing}}

def make_room_code():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))

# ── Models ───────────────────────────────────────────────
class SearchRequest(BaseModel):
    query: str

class SongRequest(BaseModel):
    title: str
    artist: str
    ug_url: str = None

class GenreRequest(BaseModel):
    genre: str

# ── Cache charts (they don't change often) ───────────────
_top100_cache = None

@lru_cache(maxsize=20)
def _cached_genre(genre):
    return fetch_by_genre(genre)

# ── Routes ───────────────────────────────────────────────
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
        versions = search_ug(req.query, "")
        if not versions:
            return search_songs_gemini(req.query)
        seen = {}
        for v in versions:
            key = f"{v['artist'].lower()}|||{v['title'].lower()}"
            if key not in seen:
                seen[key] = {"title": v["title"], "artist": v["artist"], "versions_count": 1}
            else:
                seen[key]["versions_count"] += 1
        return {"type": "song", "artist_name": None, "results": list(seen.values())}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/versions")
async def versions(req: SongRequest):
    try:
        vers = search_ug(req.title, req.artist)
        return {"versions": vers}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/chords")
async def chords(req: SongRequest):
    if not req.title.strip():
        raise HTTPException(status_code=400, detail="Title cannot be empty")
    try:
        return get_lyrics_and_chords(req.title, req.artist, req.ug_url)
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
        songs = _cached_genre(req.genre)
        return {"songs": songs, "genre": req.genre}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── WebSocket for share/music night ─────────────────────
@app.post("/room/create")
async def create_room():
    code = make_room_code()
    while code in rooms:
        code = make_room_code()
    rooms[code] = {"clients": [], "state": {}}
    return {"code": code}

@app.websocket("/room/{code}")
async def room_ws(websocket: WebSocket, code: str):
    if code not in rooms:
        await websocket.close(code=4004)
        return

    await websocket.accept()
    room = rooms[code]
    room["clients"].append(websocket)

    # Send current state to new joiner
    if room["state"]:
        await websocket.send_text(json.dumps({"type": "state", **room["state"]}))

    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)

            # Update room state
            if msg.get("type") in ("song", "scroll", "playing", "transpose"):
                room["state"].update(msg)

            # Broadcast to all other clients
            dead = []
            for client in room["clients"]:
                if client != websocket:
                    try:
                        await client.send_text(data)
                    except:
                        dead.append(client)
            for d in dead:
                room["clients"].remove(d)

    except WebSocketDisconnect:
        room["clients"].remove(websocket)
        if not room["clients"]:
            del rooms[code]
