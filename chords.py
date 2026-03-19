# chords.py
# Chord generation is now handled directly in lyrics.py via Claude API.
# This file is kept for backwards compatibility in case any imports reference it.

from lyrics import get_lyrics_and_chords_from_search, get_lyrics_and_chords_from_url

__all__ = ["get_lyrics_and_chords_from_search", "get_lyrics_and_chords_from_url"]
