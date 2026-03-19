from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import yt_dlp
import os
import uuid
import asyncio
from lyrics import fetch_lyrics
from chords import detect_chords

app = FastAPI()

# Allow requests from your phone on the local network
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

AUDIO_DIR = "audio_cache"
os.makedirs(AUDIO_DIR, exist_ok=True)


class YouTubeRequest(BaseModel):
    url: str

class SearchRequest(BaseModel):
    query: str  # e.g. "Let Her Go Passenger"


@app.get("/")
def root():
    return {"status": "Chord Sheet backend is running!"}


@app.get("/debug")
def debug():
    import os
    token = os.getenv("GENIUS_TOKEN", "")
    return {
        "token_set": bool(token),
        "token_preview": token[:6] + "..." if token else "MISSING"
    }


@app.post("/from-url")
async def process_youtube_url(req: YouTubeRequest):
    """
    Takes a YouTube URL, downloads audio, detects chords, fetches lyrics.
    """
    audio_path = None
    try:
        # 1. Extract video title/artist from YouTube metadata
        meta = get_youtube_meta(req.url)
        title = meta.get("title", "Unknown Title")
        artist = meta.get("artist") or meta.get("uploader", "Unknown Artist")

        # 2. Download audio
        audio_path = download_audio(req.url)

        # 3. Run chord detection and lyrics fetch in parallel
        chords_task = asyncio.to_thread(detect_chords, audio_path)
        lyrics_task = asyncio.to_thread(fetch_lyrics, title, artist)
        chords_result, lyrics_result = await asyncio.gather(chords_task, lyrics_task)

        return {
            "title": title,
            "artist": artist,
            "key": chords_result.get("key", "C"),
            "bpm": chords_result.get("bpm", None),
            "sections": lyrics_result.get("sections", []),
            "chords_timeline": chords_result.get("timeline", []),
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # Clean up downloaded audio file
        if audio_path and os.path.exists(audio_path):
            os.remove(audio_path)


@app.post("/from-search")
async def process_search(req: SearchRequest):
    """
    Takes a song name + artist query, fetches lyrics and looks up chords.
    No audio download needed for search — uses chord lookup instead.
    """
    try:
        # Parse "Song Name - Artist" or "Song Name Artist"
        parts = req.query.split(" - ", 1)
        title = parts[0].strip()
        artist = parts[1].strip() if len(parts) > 1 else ""

        lyrics_task = asyncio.to_thread(fetch_lyrics, title, artist)
        lyrics_result = await lyrics_task

        return {
            "title": lyrics_result.get("title", title),
            "artist": lyrics_result.get("artist", artist),
            "key": lyrics_result.get("key", "C"),
            "bpm": None,
            "sections": lyrics_result.get("sections", []),
            "chords_timeline": [],
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def get_youtube_meta(url: str) -> dict:
    ydl_opts = {"quiet": True, "skip_download": True}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        return info


def download_audio(url: str) -> str:
    """Downloads audio from YouTube URL, returns path to .wav file."""
    filename = os.path.join(AUDIO_DIR, str(uuid.uuid4()))
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": filename,
        "quiet": True,
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "wav",
        }],
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])
    return filename + ".wav"
