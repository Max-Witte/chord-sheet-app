import requests
import json
import re
from urllib.parse import quote
import time
import random

SESSION = requests.Session()

# Rotate through realistic user agents
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_2_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
]

def _get_headers():
    ua = random.choice(USER_AGENTS)
    return {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0",
    }


def _extract_store_data(html):
    """Extract the js-store JSON data from UG HTML."""
    # Try data-content attribute
    match = re.search(r'data-content="([^"]+)"', html)
    if match:
        raw = match.group(1)
        raw = (raw.replace("&quot;", '"')
                  .replace("&amp;", "&")
                  .replace("&#039;", "'")
                  .replace("&lt;", "<")
                  .replace("&gt;", ">"))
        try:
            return json.loads(raw)
        except Exception as e:
            print(f"JSON parse error: {e}")

    # Try window.UGAPP store
    match = re.search(r'window\.UGAPP\s*=\s*({.+?});\s*</script>', html, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except:
            pass

    return None


def _warm_up():
    """Visit UG homepage first to get cookies — helps bypass Cloudflare."""
    try:
        SESSION.get(
            "https://www.ultimate-guitar.com/",
            headers=_get_headers(),
            timeout=10
        )
        time.sleep(random.uniform(0.5, 1.2))
        print("UG warmup done")
    except Exception as e:
        print(f"UG warmup failed: {e}")


def search_ug(title, artist):
    """
    Search UG for chord sheets. Returns list of versions sorted by rating.
    """
    _warm_up()

    query = quote(f"{title} {artist}")
    url = f"https://www.ultimate-guitar.com/search.php?title={query}&type=Chords"

    try:
        time.sleep(random.uniform(0.3, 0.8))
        res = SESSION.get(url, headers=_get_headers(), timeout=12)
        print(f"UG search status: {res.status_code}")

        if res.status_code == 403:
            print("UG: Cloudflare blocked search")
            return []

        if not res.ok:
            print(f"UG search failed: {res.status_code}")
            return []

        data = _extract_store_data(res.text)
        if not data:
            print("UG: could not extract store data from search page")
            print("HTML snippet:", res.text[:300])
            return []

        results = (data.get("store", {})
                      .get("page", {})
                      .get("data", {})
                      .get("results", []))

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

        versions.sort(key=lambda x: float(x["rating"]) * int(x["votes"]), reverse=True)
        print(f"UG: found {len(versions)} chord versions")
        return versions[:8]

    except Exception as e:
        print(f"UG search error: {e}")
        return []


def fetch_ug_chords(tab_url):
    """
    Fetch a UG chord sheet and return parsed sections.
    """
    try:
        time.sleep(random.uniform(0.3, 0.7))
        res = SESSION.get(tab_url, headers={
            **_get_headers(),
            "Referer": "https://www.ultimate-guitar.com/search.php",
        }, timeout=12)

        print(f"UG chord page status: {res.status_code}")

        if res.status_code == 403:
            print("UG: Cloudflare blocked chord page")
            return None

        if not res.ok:
            return None

        data = _extract_store_data(res.text)
        if not data:
            print("UG: could not extract store data from chord page")
            return None

        tab_view = (data.get("store", {})
                       .get("page", {})
                       .get("data", {})
                       .get("tab_view", {}))

        # Try multiple content locations
        content = (tab_view.get("wiki_tab", {}).get("content", "") or
                   tab_view.get("tab", {}).get("content", ""))

        if not content:
            print("UG: no content found")
            print("Keys available:", list(tab_view.keys()))
            return None

        print(f"UG: got content ({len(content)} chars)")

        meta = tab_view.get("tab", {})
        key = meta.get("tonality_name", "")
        bpm = meta.get("tempo", None)

        return {
            "sections": parse_ug_content(content),
            "key": key,
            "bpm": bpm,
        }

    except Exception as e:
        print(f"UG fetch error: {e}")
        return None


def parse_ug_content(content):
    """
    Parse UG chord sheet format into our sections JSON.
    UG uses [ch]X[/ch] for chords and [tab]...[/tab] for tabs.
    Section headers: [verse], [chorus], [bridge] etc.
    """
    # Remove tab blocks
    content = re.sub(r'\[tab\].*?\[/tab\]', '', content, flags=re.DOTALL)

    # Convert [ch]X[/ch] to [X]
    content = re.sub(r'\[ch\]([^\[]+?)\[/ch\]', r'[\1]', content)

    # Split into lines
    raw_lines = content.split('\n')

    sections = []
    current_label = None
    current_lines = []
    verse_count = 0
    chorus_count = 0

    SECTION_TAGS = re.compile(
        r'^\[(verse|chorus|bridge|intro|outro|pre.?chorus|interlude|solo|hook)'
        r'(?:\s+\d+)?\]$', re.IGNORECASE
    )

    def flush():
        nonlocal current_lines
        clean = [l for l in current_lines if l.strip()]
        if clean and current_label:
            sections.append({"label": current_label, "lines": clean})
        current_lines = []

    for raw in raw_lines:
        line = raw.strip()
        if not line:
            continue

        m = SECTION_TAGS.match(line)
        if m:
            flush()
            tag = m.group(1).lower().replace('-', '').replace(' ', '')
            if tag == 'verse':
                verse_count += 1
                current_label = f"Verse {verse_count}"
            elif tag == 'chorus':
                chorus_count += 1
                current_label = "Chorus" if chorus_count == 1 else "Chorus"
            elif tag == 'prechorus' or tag == 'precchorus':
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
            continue

        # If no section label yet, assign one
        if current_label is None:
            current_label = "Intro"

        current_lines.append(line)

    flush()

    if not sections:
        all_lines = [l.strip() for l in content.split('\n') if l.strip()]
        sections = [{"label": "Verse 1", "lines": all_lines}]

    return sections
