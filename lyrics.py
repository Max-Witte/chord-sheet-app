import os
import re
import requests

GENIUS_TOKEN = os.getenv("GENIUS_TOKEN", "")

# Chord-to-lyric alignment helpers
CHORD_PATTERNS = [
    r'\b([A-G][b#]?(?:maj|min|m|sus|aug|dim|add)?(?:\d+)?(?:\/[A-G][b#]?)?)\b'
]


def fetch_lyrics(title: str, artist: str) -> dict:
    """
    Fetches lyrics + basic chord info from Genius API.
    Falls back to a structured placeholder if not found.
    """
    if not GENIUS_TOKEN:
        return _placeholder(title, artist)

    try:
        song = _search_genius(title, artist)
        if not song:
            return _placeholder(title, artist)

        raw_lyrics = _scrape_lyrics(song["url"])
        sections = _parse_lyrics_to_sections(raw_lyrics)

        return {
            "title": song.get("title", title),
            "artist": song.get("primary_artist", {}).get("name", artist),
            "key": "C",  # Genius doesn't provide key — will come from audio analysis
            "sections": sections,
        }
    except Exception as e:
        print(f"Lyrics fetch error: {e}")
        return _placeholder(title, artist)


def _search_genius(title: str, artist: str) -> dict | None:
    query = f"{title} {artist}".strip()
    headers = {"Authorization": f"Bearer {GENIUS_TOKEN}"}
    resp = requests.get(
        "https://api.genius.com/search",
        params={"q": query},
        headers=headers,
        timeout=10,
    )
    resp.raise_for_status()
    hits = resp.json().get("response", {}).get("hits", [])
    if not hits:
        return None
    return hits[0]["result"]


def _scrape_lyrics(url: str) -> str:
    """
    Scrapes lyrics text from a Genius song page.
    Uses a simple approach — lyrics are in data-lyrics-container divs.
    """
    try:
        from bs4 import BeautifulSoup
        resp = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        soup = BeautifulSoup(resp.text, "html.parser")
        containers = soup.find_all("div", attrs={"data-lyrics-container": "true"})
        parts = []
        for container in containers:
            for br in container.find_all("br"):
                br.replace_with("\n")
            parts.append(container.get_text())
        return "\n".join(parts)
    except Exception as e:
        print(f"Scrape error: {e}")
        return ""


def _parse_lyrics_to_sections(raw: str) -> list:
    """
    Converts raw lyric text into sections like:
    [{ label: "Verse 1", lines: [{ chords: [...], words: [...] }] }]
    
    Genius marks sections with [Verse 1], [Chorus], etc.
    Chords will be added later via audio analysis (timeline overlay).
    For now each line is returned as plain lyric words with empty chords.
    """
    sections = []
    current_label = "Intro"
    current_lines = []

    for raw_line in raw.split("\n"):
        line = raw_line.strip()
        if not line:
            continue

        # Section header like [Verse 1] or [Chorus]
        if line.startswith("[") and line.endswith("]"):
            if current_lines:
                sections.append({"label": current_label, "lines": current_lines})
            current_label = line[1:-1]
            current_lines = []
            continue

        # Split line into words, each with an empty chord placeholder
        words = line.split()
        if words:
            current_lines.append({
                "chords": [""] * len(words),
                "words": words,
            })

    if current_lines:
        sections.append({"label": current_label, "lines": current_lines})

    return sections if sections else _placeholder_sections()


def _placeholder(title: str, artist: str) -> dict:
    """Returns a helpful message when lyrics aren't found."""
    return {
        "title": title,
        "artist": artist,
        "key": "C",
        "sections": [
            {
                "label": "Note",
                "lines": [
                    {"chords": [""], "words": ["Lyrics not found — try adding your GENIUS_TOKEN to .env"]}
                ]
            }
        ],
    }


def _placeholder_sections() -> list:
    return [{"label": "Verse", "lines": [{"chords": [""], "words": ["(Lyrics unavailable)"]}]}]
