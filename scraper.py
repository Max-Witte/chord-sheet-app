import requests
import json
import re
from urllib.parse import quote

HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Referer": "https://www.ultimate-guitar.com/",
}


def search_ug(title, artist):
    """
    Search Ultimate Guitar and return a list of chord sheet versions.
    Returns list of {title, artist, url, votes, version} dicts.
    """
    query = quote(f"{title} {artist}")
    url = f"https://www.ultimate-guitar.com/search.php?title={query}&type=Chords"

    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        if not res.ok:
            print(f"UG search failed: {res.status_code}")
            return []

        # UG embeds JSON data in a <div class="js-store"> tag
        match = re.search(r'data-content="([^"]+)"', res.text)
        if not match:
            print("UG: no js-store data found")
            return []

        # The data is HTML-entity encoded JSON
        raw = match.group(1)
        raw = raw.replace("&quot;", '"').replace("&amp;", "&").replace("&#039;", "'")
        data = json.loads(raw)

        results = data.get("store", {}).get("page", {}).get("data", {}).get("results", [])
        versions = []

        for r in results:
            if r.get("type") != "Chords":
                continue
            versions.append({
                "title": r.get("song_name", title),
                "artist": r.get("artist_name", artist),
                "url": r.get("tab_url", ""),
                "votes": r.get("votes", 0),
                "rating": r.get("rating", 0),
                "version": r.get("version", 1),
            })

        # Sort by rating * votes (best verified versions first)
        versions.sort(key=lambda x: x["rating"] * x["votes"], reverse=True)
        print(f"UG search: found {len(versions)} chord versions")
        return versions[:6]

    except Exception as e:
        print(f"UG search error: {e}")
        return []


def fetch_ug_chords(tab_url):
    """
    Fetch a specific UG chord sheet page and extract the chord/lyric content.
    Returns parsed sections list or None on failure.
    """
    try:
        res = requests.get(tab_url, headers=HEADERS, timeout=10)
        if not res.ok:
            print(f"UG fetch failed: {res.status_code}")
            return None

        # Extract JSON from js-store
        match = re.search(r'data-content="([^"]+)"', res.text)
        if not match:
            print("UG: no js-store on chord page")
            return None

        raw = match.group(1)
        raw = raw.replace("&quot;", '"').replace("&amp;", "&").replace("&#039;", "'")
        data = json.loads(raw)

        tab_data = data.get("store", {}).get("page", {}).get("data", {}).get("tab_view", {})
        wiki_tab = tab_data.get("wiki_tab", {})
        content = wiki_tab.get("content", "")

        if not content:
            # Try alternative location
            content = tab_data.get("tab", {}).get("content", "")

        if not content:
            print("UG: no content found in tab data")
            return None

        print(f"UG: got content ({len(content)} chars)")

        # Extract key and BPM if available
        meta = tab_data.get("tab", {})
        key = meta.get("tonality_name", "")
        bpm = meta.get("tempo", None)

        sections = parse_ug_content(content)
        return {
            "sections": sections,
            "key": key,
            "bpm": bpm,
        }

    except Exception as e:
        print(f"UG fetch error: {e}")
        return None


def parse_ug_content(content):
    """
    Parse UG's chord sheet format into our sections format.
    UG uses [ch]X[/ch] for chords and [tab]...[/tab] for tabs.
    Converts to our [X]word inline format.
    """
    # Remove tab blocks (guitar tabs, not chord sheets)
    content = re.sub(r'\[tab\].*?\[/tab\]', '', content, flags=re.DOTALL)

    # Convert [ch]X[/ch] markers — place chord before next word
    # UG format: "I will [ch]C[/ch]leave my heart"
    # Our format: "I will [C]leave my heart"
    content = re.sub(r'\[ch\]([^\[]+?)\[/ch\]', r'[\1]', content)

    # Remove other UG tags
    content = re.sub(r'\[/?(?:verse|chorus|bridge|intro|outro|pre-chorus|tab|ch)[^\]]*\]',
                     lambda m: '\n' + _tag_to_label(m.group(0)) + '\n', content)

    lines = content.split('\n')
    sections = []
    current_label = "Verse 1"
    current_lines = []
    section_counters = {}

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Check if line is a section label we injected
        if line.startswith('__LABEL__:'):
            label = line.replace('__LABEL__:', '').strip()
            if current_lines:
                sections.append({"label": current_label, "lines": current_lines})
                current_lines = []
            current_label = label
            continue

        # Skip lines that are just chord names (no lyrics)
        # Keep them if they have chords — those are intro/instrumental lines
        current_lines.append(line)

    if current_lines:
        sections.append({"label": current_label, "lines": current_lines})

    # If no sections found, put everything in one section
    if not sections:
        all_lines = [l.strip() for l in content.split('\n') if l.strip()]
        sections = [{"label": "Verse 1", "lines": all_lines}]

    return sections


def _tag_to_label(tag):
    """Convert UG section tags to our label format."""
    tag_lower = tag.lower()
    if 'verse' in tag_lower:
        return '__LABEL__:Verse'
    if 'chorus' in tag_lower:
        return '__LABEL__:Chorus'
    if 'bridge' in tag_lower:
        return '__LABEL__:Bridge'
    if 'intro' in tag_lower:
        return '__LABEL__:Intro'
    if 'outro' in tag_lower:
        return '__LABEL__:Outro'
    if 'pre-chorus' in tag_lower or 'pre_chorus' in tag_lower:
        return '__LABEL__:Pre-Chorus'
    return '__LABEL__:Section'
