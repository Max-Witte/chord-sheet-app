import requests
import json
import re
from urllib.parse import quote
import os
from html import unescape

SCRAPEOPS_API_KEY = os.environ.get("SCRAPEOPS_API_KEY", "")


def _fetch(url):
    """Fetch a URL through ScrapeOps proxy to bypass Cloudflare."""
    if not SCRAPEOPS_API_KEY:
        raise RuntimeError("SCRAPEOPS_API_KEY is not set in environment variables.")

    proxy_url = "https://proxy.scrapeops.io/v1/"
    params = {
        "api_key": SCRAPEOPS_API_KEY,
        "url": url,
        "render_js": "false",  # No JS rendering needed — UG embeds data in HTML
    }

    res = requests.get(proxy_url, params=params, timeout=30)
    print(f"ScrapeOps status for {url[:60]}: {res.status_code}")

    if not res.ok:
        print(f"ScrapeOps error: {res.text[:200]}")
        return None

    return res.text


def _extract_store_data(html):
    """Extract the js-store JSON blob from UG HTML."""
    match = re.search(r'data-content="([^"]+)"', html)
    if match:
        raw = unescape(match.group(1).replace("&quot;", '"'))
        try:
            return json.loads(raw)
        except Exception as e:
            print(f"JSON parse error on data-content: {e}")

    # Fallback: window.UGAPP
    match = re.search(r'window\.UGAPP\s*=\s*({.+?});\s*</script>', html, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except Exception as e:
            print(f"JSON parse error on UGAPP: {e}")

    return None


def search_ug(title, artist):
    """
    Search UG for chord sheets. Returns list of versions sorted by rating.
    """
    query = quote(f"{title} {artist}")
    url = f"https://www.ultimate-guitar.com/search.php?title={query}&type=Chords"

    html = _fetch(url)
    if not html:
        print("UG: no HTML returned from proxy")
        return []

    data = _extract_store_data(html)
    if not data:
        print("UG: could not extract store data")
        print("HTML snippet:", html[:400])
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

    versions.sort(key=lambda x: float(x.get("rating") or 0) * int(x.get("votes") or 0), reverse=True)
    print(f"UG: found {len(versions)} chord versions")
    return versions[:8]


def fetch_ug_chords(tab_url):
    """
    Fetch a UG chord sheet page and return parsed sections.
    """
    html = _fetch(tab_url)
    if not html:
        return None

    data = _extract_store_data(html)
    if not data:
        print("UG: could not extract store data from chord page")
        return None

    tab_view = (data.get("store", {})
                    .get("page", {})
                    .get("data", {})
                    .get("tab_view", {}))

    content = (tab_view.get("wiki_tab", {}).get("content", "") or
               tab_view.get("tab", {}).get("content", ""))

    if not content:
        print("UG: no content found. Keys:", list(tab_view.keys()))
        return None

    print(f"UG: got content ({len(content)} chars)")
    print("UG content preview:", repr(content[:800]))

    meta = tab_view.get("tab", {})
    return {
        "sections": parse_ug_content(content),
        "key": meta.get("tonality_name", ""),
        "bpm": meta.get("tempo", None),
    }


def parse_ug_content(content):
    """
    Parse UG chord sheet format into our sections JSON.
    UG uses [ch]X[/ch] for chords, [tab]...[/tab] for tabs,
    and [verse], [chorus] etc. for section headers.
    """
    # Remove tab blocks (guitar tab notation)
    content = re.sub(r'\[tab\].*?\[/tab\]', '', content, flags=re.DOTALL)

    # Convert [ch]X[/ch] to [X]
    content = re.sub(r'\[ch\]([^\[]+?)\[/ch\]', r'[\1]', content)

    # Remove any remaining UG tags like [/verse], [/chorus] etc.
    content = re.sub(r'\[/?(verse|chorus|bridge|intro|outro|pre.?chorus|interlude|solo|hook)[^\]]*\]', '', content, flags=re.IGNORECASE)

    raw_lines = content.split('\n')
    sections = []
    current_label = None
    current_lines = []
    verse_count = 0
    found_first_section = False

    SECTION_RE = re.compile(
        r'^\[(verse|chorus|bridge|intro|outro|pre.?chorus|interlude|solo|hook)'
        r'(?:\s*\d*)?\]$', re.IGNORECASE
    )

    # Patterns to skip — metadata lines and bar lines
    SKIP_RE = re.compile(
        r'^(artist|song|album|capo|tuning|key|bpm|provided|transcribed|chords used|note:|this is|difficulty)[\s:]',
        re.IGNORECASE
    )

    # Bar lines — lines that are ONLY pipes and spaces (e.g. "| | | |")
    BARLINE_RE = re.compile(r'^[|/\\ ]+$')

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

        # Skip metadata lines (only before first real section)
        if not found_first_section and SKIP_RE.match(line):
            continue

        # Skip pure bar lines
        if BARLINE_RE.match(line):
            continue

        m = SECTION_RE.match(line)
        if m:
            flush()
            found_first_section = True
            tag = m.group(1).lower().replace('-', '').replace(' ', '')
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
            continue

        if current_label is None:
            # Skip preamble text until we hit a real section tag
            # But if no section tags exist at all, capture everything
            current_label = "Intro"
            found_first_section = True

        current_lines.append(line)

    flush()

    if not sections:
        all_lines = [l.strip() for l in content.split('\n') if l.strip()
                     and not BARLINE_RE.match(l.strip())
                     and not SKIP_RE.match(l.strip())]
        sections = [{"label": "Verse 1", "lines": all_lines}]

    return sections
