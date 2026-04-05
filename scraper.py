import requests
import json
import re
from urllib.parse import quote
import os
from html import unescape

SCRAPEOPS_API_KEY = os.environ.get("SCRAPEOPS_API_KEY", "")


def _fetch(url):
    if not SCRAPEOPS_API_KEY:
        raise RuntimeError("SCRAPEOPS_API_KEY is not set.")
    proxy_url = "https://proxy.scrapeops.io/v1/"
    params = {"api_key": SCRAPEOPS_API_KEY, "url": url, "render_js": "false"}
    res = requests.get(proxy_url, params=params, timeout=30)
    print(f"ScrapeOps status for {url[:60]}: {res.status_code}")
    if not res.ok:
        print(f"ScrapeOps error: {res.text[:200]}")
        return None
    return res.text


def _extract_store_data(html):
    match = re.search(r'data-content="([^"]+)"', html)
    if match:
        raw = unescape(match.group(1).replace("&quot;", '"'))
        try:
            return json.loads(raw)
        except Exception as e:
            print(f"JSON parse error: {e}")
    match = re.search(r'window\.UGAPP\s*=\s*({.+?});\s*</script>', html, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except:
            pass
    return None


def _title_similarity(a: str, b: str) -> float:
    """Return a 0-1 similarity score between two strings (case-insensitive)."""
    a = re.sub(r"[^a-z0-9 ]", "", a.lower()).strip()
    b = re.sub(r"[^a-z0-9 ]", "", b.lower()).strip()
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    # Jaccard similarity on word sets
    sa, sb = set(a.split()), set(b.split())
    intersection = sa & sb
    union = sa | sb
    return len(intersection) / len(union) if union else 0.0


def search_ug(title, artist, pages=1):
    """
    Search UG for chord sheets.

    Fixes vs original:
    1. Passes title and artist as *separate* URL parameters so UG's own
       search engine can match them correctly — previously both were jammed
       into `title=`, which caused the wrong song to rank first.
    2. Fetches up to `pages` pages of results (default 2) so songs that
       only appear on page 2 (e.g. Christina Aguilera – Hurt) are found.
    3. After collecting all raw results, re-ranks them by:
         a. Title similarity to the requested title  (most important)
         b. Artist similarity to the requested artist
         c. UG rating × votes  (tiebreaker)
       This prevents a high-rated song by the same artist from jumping
       ahead of the actually requested song.
    """
    all_versions = []
    seen_urls = set()

    for page in range(1, pages + 1):
        # Use separate title= and artist= params — UG supports both
        params = f"title={quote(title)}&type=Chords"
        if artist:
            params += f"&artist={quote(artist)}"
        if page > 1:
            params += f"&page={page}"
        url = f"https://www.ultimate-guitar.com/search.php?{params}"

        html = _fetch(url)
        if not html:
            break
        data = _extract_store_data(html)
        if not data:
            print(f"UG: could not extract store data (page {page})")
            break

        results = data.get("store", {}).get("page", {}).get("data", {}).get("results", [])
        page_versions = []
        for r in results:
            if r.get("type") != "Chords":
                continue
            tab_url = r.get("tab_url", "")
            if tab_url in seen_urls:
                continue
            seen_urls.add(tab_url)
            page_versions.append({
                "title": r.get("song_name", title),
                "artist": r.get("artist_name", artist),
                "url": tab_url,
                "votes": r.get("votes", 0),
                "rating": r.get("rating", 0),
                "version": r.get("version", 1),
            })

        print(f"UG search page {page}: {len(page_versions)} chord results")
        all_versions.extend(page_versions)

        # Stop early if UG returned fewer results than a full page
        if len(results) < 20:
            break

    if not all_versions:
        print("UG: no chord versions found")
        return []

    # Re-rank: prioritise correct title+artist match, use rating×votes as tiebreaker
    def rank_score(v):
        title_sim = _title_similarity(v["title"], title)
        artist_sim = _title_similarity(v["artist"], artist) if artist else 0.5
        popularity = float(v.get("rating") or 0) * int(v.get("votes") or 0)
        # Weights: title match is most critical, artist second, popularity last
        return (title_sim * 10) + (artist_sim * 5) + (popularity / 100000)

    all_versions.sort(key=rank_score, reverse=True)
    print(f"UG: {len(all_versions)} total chord versions after {pages} page(s)")
    return all_versions[:8]


def fetch_ug_chords(tab_url):
    html = _fetch(tab_url)
    if not html:
        return None
    data = _extract_store_data(html)
    if not data:
        print("UG: could not extract store data from chord page")
        return None
    tab_view = data.get("store", {}).get("page", {}).get("data", {}).get("tab_view", {})
    content = (tab_view.get("wiki_tab", {}).get("content", "") or
               tab_view.get("tab", {}).get("content", ""))
    if not content:
        print("UG: no content found. Keys:", list(tab_view.keys()))
        return None
    print(f"UG: got content ({len(content)} chars)")
    print("UG content preview:", repr(content[:600]))
    meta = tab_view.get("tab", {})
    return {
        "sections": parse_ug_content(content),
        "key": meta.get("tonality_name", ""),
        "bpm": meta.get("tempo", None),
    }


def parse_ug_content(content):
    """
    UG chord sheets come in two formats:

    Format A — chord line above lyric line in [tab] block:
        [tab][ch]Am[/ch]           [ch]C[/ch]
        Same bed but it feels just a little bit bigger now[/tab]

    Format B — chord on its own line, lyric on next line in [tab] block:
        [tab][ch]Dm[/ch]
        The second someone mentioned you were all alone[/tab]

    Both need to produce: "[Am]Same bed but it [C]feels..."
    """

    SECTION_RE = re.compile(
        r'^\[(verse|chorus|bridge|intro|outro|pre.?chorus|interlude|solo|hook)'
        r'(?:\s*\d*)?\]$', re.IGNORECASE
    )

    sections = []
    current_label = None
    current_lines = []
    verse_count = 0

    def flush():
        nonlocal current_lines
        clean = [l for l in current_lines if l.strip()]
        if clean and current_label:
            sections.append({"label": current_label, "lines": clean})
        current_lines = []

    def set_label(tag):
        nonlocal current_label, verse_count
        tag = tag.lower().replace('-', '').replace(' ', '')
        if tag == 'verse':
            verse_count += 1
            current_label = f"Verse {verse_count}"
        elif tag == 'chorus':
            current_label = "Chorus"
        elif tag in ('prechorus', 'precchorus'):
            current_label = "Pre-Chorus"
        elif tag == 'bridge':
            current_label = "Bridge"
        elif tag == 'intro':
            current_label = "Intro"
        elif tag == 'outro':
            current_label = "Outro"
        elif tag == 'solo':
            current_label = "Solo"
        else:
            current_label = tag.capitalize()

    def process_tab_block(block):
        """Parse a single [tab]...[/tab] block into lyric lines with inline chords."""
        # Convert [ch]X[/ch] to [X]
        block = re.sub(r'\[ch\]([^\[]+?)\[/ch\]', r'[\1]', block)
        lines = block.split('\n')
        # Remove empty lines at start/end
        lines = [l for l in lines if l.rstrip()]
        if not lines:
            return []

        result = []
        i = 0
        while i < len(lines):
            line = lines[i]
            chord_markers = re.findall(r'\[([A-G][^\]]{0,6})\]', line)
            text_content = re.sub(r'\[[^\]]+\]', '', line).strip()

            if chord_markers and not text_content:
                # Pure chord line — look ahead for lyric line
                lyric_line = lines[i + 1].strip() if i + 1 < len(lines) else ""
                next_has_chords = bool(re.search(r'\[[A-G][^\]]{0,6}\]', lyric_line))

                if lyric_line and not next_has_chords:
                    # Merge: map chord positions onto lyric
                    merged = merge_chords_onto_lyric(line, lyric_line)
                    result.append(merged)
                    i += 2
                else:
                    # No lyric follows — show chords as chord-only line
                    chord_str = " ".join(f"[{c}]" for c in chord_markers)
                    result.append(chord_str)
                    i += 1
            else:
                # Line already has inline chords or is plain lyric
                if line.strip():
                    result.append(line.strip())
                i += 1

        return result

    def merge_chords_onto_lyric(chord_line, lyric_line):
        """
        Map chord markers from chord_line positions onto lyric_line text.
        Uses character position ratio to find where to insert each chord.
        """
        chord_hits = list(re.finditer(r'\[([A-G][^\]]{0,6})\]', chord_line))
        if not chord_hits:
            return lyric_line.strip()

        lyric = lyric_line  # preserve original spacing for position mapping
        lyric_len = len(lyric)
        chord_line_len = len(chord_line)

        # Build list of (lyric_pos, chord_name)
        insertions = []
        for m in chord_hits:
            ratio = m.start() / chord_line_len if chord_line_len else 0
            pos = int(ratio * lyric_len)
            pos = max(0, min(pos, lyric_len))
            # Snap forward to word start
            while pos < lyric_len and lyric[pos] == ' ':
                pos += 1
            insertions.append((pos, m.group(1)))

        # Insert from right to left to preserve positions
        insertions.sort(key=lambda x: x[0], reverse=True)
        result = lyric
        for pos, chord in insertions:
            result = result[:pos] + f"[{chord}]" + result[pos:]

        return result.strip()

    pending_chords = None

    # Split content on [tab]...[/tab] blocks
    parts = re.split(r'(\[tab\].*?\[/tab\])', content, flags=re.DOTALL)

    for part in parts:
        if part.startswith('[tab]') and part.endswith('[/tab]'):
            inner = part[5:-6]
            tab_lines = process_tab_block(inner)
            if current_label is None:
                current_label = "Intro"
            current_lines.extend(tab_lines)
        else:
            # Process line by line — look for section headers
            for raw in part.split('\n'):
                line = raw.strip()
                if not line:
                    continue

                # Section tag
                m = SECTION_RE.match(line)
                if m:
                    flush()
                    set_label(m.group(1))
                    continue

                # Skip closing tags
                if re.match(r'^\[/', line):
                    continue

                # Convert inline ch tags
                line = re.sub(r'\[ch\]([^\[]+?)\[/ch\]', r'[\1]', line)

                # Skip lines that are clearly preamble/metadata (no chords, before first section)
                if current_label is None:
                    continue

                # Skip bar lines (| | | |)
                if re.match(r'^[|\s]+$', line):
                    continue

                # Check if this is a chord-only line — hold it for next lyric
                chord_only = bool(re.findall(r'\[[A-G][^\]]{0,6}\]', line)) and                              not re.sub(r'\[[^\]]+\]', '', line).strip()

                if chord_only:
                    pending_chords = line
                else:
                    # Merge any pending chord line onto this lyric line
                    if pending_chords:
                        line = merge_chords_onto_lyric(pending_chords, line)
                        pending_chords = None
                    current_lines.append(line)

    # Flush any remaining pending chords as chord-only line
    if pending_chords and current_label:
        current_lines.append(pending_chords)

    flush()

    if not sections:
        plain = re.sub(r'\[ch\]([^\[]+?)\[/ch\]', r'[\1]', content)
        plain = re.sub(r'\[tab\]|\[/tab\]', '', plain)
        plain = re.sub(r'\[/?(?:verse|chorus|bridge|intro|outro)[^\]]*\]', '', plain, flags=re.IGNORECASE)
        all_lines = [l.strip() for l in plain.split('\n') if l.strip()]
        sections = [{"label": "Verse 1", "lines": all_lines}]

    return sections


# ── Charts & Categories ──────────────────────────────────

GENRES = [
    "Rock", "Pop", "Metal", "Blues", "Jazz", "Country",
    "Classical", "Folk", "Punk", "R&B", "Soul", "Reggae",
    "Alternative", "Indie", "Electronic"
]

def fetch_top_100(pages=1):
    """Fetch UG's top chord sheets across multiple pages."""
    all_songs = []
    seen = set()
    for page in range(1, pages + 1):
        url = f"https://www.ultimate-guitar.com/top?type=Chords&page={page}"
        html = _fetch(url)
        if not html:
            break
        songs = _parse_explore_results(html)
        if not songs:
            break
        for s in songs:
            key = s["title"].lower() + "|||" + s["artist"].lower()
            if key not in seen:
                seen.add(key)
                all_songs.append(s)
        print(f"Top100 page {page}: {len(songs)} songs, total {len(all_songs)}")
        if len(songs) < 25:
            break
    return all_songs


def fetch_by_genre(genre, pages=1):
    """Fetch chord sheets filtered by genre across multiple pages."""
    all_songs = []
    seen = set()
    for page in range(1, pages + 1):
        url = f"https://www.ultimate-guitar.com/explore?genres[]={genre}&type[]=Chords&order=rating_desc&page={page}"
        html = _fetch(url)
        if not html:
            break
        songs = _parse_explore_results(html)
        if not songs:
            break
        for s in songs:
            key = s["title"].lower() + "|||" + s["artist"].lower()
            if key not in seen:
                seen.add(key)
                all_songs.append(s)
        print(f"Genre {genre} page {page}: {len(songs)} songs, total {len(all_songs)}")
        if len(songs) < 25:
            break  # Last page
    return all_songs


def _parse_explore_results(html):
    """Parse UG explore/top page results from js-store data."""
    data = _extract_store_data(html)
    if not data:
        print("Charts: could not extract store data")
        print("HTML snippet:", html[:300])
        return []

    # Try different data paths UG uses
    page_data = data.get("store", {}).get("page", {}).get("data", {})
    results = (page_data.get("results") or
               page_data.get("tabs") or
               page_data.get("data", {}).get("tabs") or [])

    songs = []
    for r in results:
        if r.get("type") not in ("Chords", "chords"):
            continue
        songs.append({
            "title": r.get("song_name", ""),
            "artist": r.get("artist_name", ""),
            "url": r.get("tab_url", ""),
            "rating": r.get("rating", 0),
            "votes": r.get("votes", 0),
            "version": r.get("version", 1),
        })

    print(f"Charts: found {len(songs)} songs")
    return songs[:200]
