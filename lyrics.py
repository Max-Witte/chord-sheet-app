import os
import lyricsgenius

GENIUS_TOKEN = "t3n7nhT8QdhpDvr2FMqA2O5N4EMu21q5AvdiDXZ4LlSnIjLDWw58MOtAhNsiMWxG"

def fetch_lyrics(title: str, artist: str) -> dict:
    try:
        genius = lyricsgenius.Genius(GENIUS_TOKEN, verbose=False, remove_section_headers=False)
        song = genius.search_song(title, artist)
        
        if not song:
            return _placeholder(title, artist)

        sections = _parse_lyrics(song.lyrics)
        return {
            "title": song.title,
            "artist": song.artist,
            "key": "C",
            "sections": sections,
        }
    except Exception as e:
        print(f"Lyrics error: {e}")
        return _placeholder(title, artist)


def _parse_lyrics(raw: str) -> list:
    sections = []
    current_label = "Verse"
    current_lines = []

    for raw_line in raw.split("\n"):
        line = raw_line.strip()
        if not line:
            continue

        # Skip the first line which is usually the song title
        if line.endswith("Lyrics"):
            continue

        # Section headers like [Verse 1] or [Chorus]
        if line.startswith("[") and line.endswith("]"):
            if current_lines:
                sections.append({"label": current_label, "lines": current_lines})
            current_label = line[1:-1]
            current_lines = []
            continue

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
    return {
        "title": title,
        "artist": artist,
        "key": "C",
        "sections": [{"label": "Error", "lines": [{"chords": [""], "words": ["Lyrics not found"]}]}],
    }


def _placeholder_sections() -> list:
    return [{"label": "Verse", "lines": [{"chords": [""], "words": ["(Lyrics unavailable)"]}]}]
