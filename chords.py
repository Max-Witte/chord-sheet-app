import subprocess
import json
import os

def detect_chords(audio_path: str) -> dict:
    """
    Detects chords and BPM from an audio file.
    Uses Essentia (open-source Music Information Retrieval library).
    Falls back to a basic librosa approach if Essentia isn't installed.
    """
    try:
        return _detect_with_essentia(audio_path)
    except ImportError:
        print("Essentia not found, falling back to librosa...")
        return _detect_with_librosa(audio_path)
    except Exception as e:
        print(f"Chord detection error: {e}")
        return {"key": "C", "bpm": None, "timeline": []}


def _detect_with_essentia(audio_path: str) -> dict:
    """
    Uses Essentia's chord recognition and key detection.
    Most accurate option.
    """
    import essentia.standard as es
    import numpy as np

    # Load audio
    loader = es.MonoLoader(filename=audio_path, sampleRate=44100)
    audio = loader()

    # Detect BPM
    rhythm_extractor = es.RhythmExtractor2013()
    bpm, _, _, _, _ = rhythm_extractor(audio)

    # Detect key
    key_extractor = es.KeyExtractor()
    key, scale, _ = key_extractor(audio)
    key_str = f"{key} {scale}" if scale != "major" else key

    # Detect chords over time
    chord_detector = es.ChordsDetectionBeats()
    # Use frames approach
    frame_size = 8192
    hop_size = 2048
    frames = []
    for frame in es.FrameGenerator(audio, frameSize=frame_size, hopSize=hop_size):
        frames.append(frame)

    # HPCP (Harmonic Pitch Class Profile) for each frame
    w = es.Windowing(type="blackmanharris62")
    spectrum = es.Spectrum()
    spectral_peaks = es.SpectralPeaks()
    hpcp = es.HPCP()
    chords_detection = es.ChordsDetection()

    hpcps = []
    for frame in frames:
        windowed = w(frame)
        spec = spectrum(windowed)
        freqs, mags = spectral_peaks(spec)
        h = hpcp(freqs, mags)
        hpcps.append(h)

    import numpy as np
    hpcps_array = np.array(hpcps)
    chords, strengths = chords_detection(hpcps_array)

    # Build timeline: [{ time_seconds, chord }]
    timeline = []
    seconds_per_frame = hop_size / 44100
    prev_chord = None
    for i, chord in enumerate(chords):
        if chord != prev_chord:
            timeline.append({
                "time": round(i * seconds_per_frame, 2),
                "chord": chord,
            })
            prev_chord = chord

    return {
        "key": key_str,
        "bpm": round(bpm),
        "timeline": timeline,
    }


def _detect_with_librosa(audio_path: str) -> dict:
    """
    Fallback using librosa for BPM and key.
    Chord detection is more limited here — uses chromagram.
    """
    import librosa
    import numpy as np

    y, sr = librosa.load(audio_path, sr=None, mono=True)

    # BPM
    tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
    bpm = round(float(tempo))

    # Key via chromagram
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
    mean_chroma = chroma.mean(axis=1)
    keys = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    key = keys[np.argmax(mean_chroma)]

    # Simple chord detection from chroma frames
    hop_length = 4096
    chroma_frames = librosa.feature.chroma_cqt(y=y, sr=sr, hop_length=hop_length)
    timeline = []
    prev_chord = None

    CHORD_TEMPLATES = _build_chord_templates()

    for i in range(chroma_frames.shape[1]):
        frame = chroma_frames[:, i]
        chord = _match_chord(frame, CHORD_TEMPLATES)
        if chord != prev_chord:
            time = librosa.frames_to_time(i, sr=sr, hop_length=hop_length)
            timeline.append({"time": round(float(time), 2), "chord": chord})
            prev_chord = chord

    return {
        "key": key,
        "bpm": bpm,
        "timeline": timeline,
    }


def _build_chord_templates() -> dict:
    """Builds major and minor chord templates for all 12 keys."""
    notes = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    import numpy as np
    templates = {}

    for i, note in enumerate(notes):
        # Major: root, major third (4 semitones), perfect fifth (7 semitones)
        major = np.zeros(12)
        major[i % 12] = 1
        major[(i + 4) % 12] = 1
        major[(i + 7) % 12] = 1
        templates[note] = major

        # Minor: root, minor third (3 semitones), perfect fifth (7 semitones)
        minor = np.zeros(12)
        minor[i % 12] = 1
        minor[(i + 3) % 12] = 1
        minor[(i + 7) % 12] = 1
        templates[f"{note}m"] = minor

    return templates


def _match_chord(frame, templates: dict) -> str:
    """Returns the best-matching chord name for a chroma frame."""
    import numpy as np
    best_chord = "C"
    best_score = -1
    norm = np.linalg.norm(frame)
    if norm < 0.01:
        return best_chord
    frame_norm = frame / norm

    for chord_name, template in templates.items():
        score = np.dot(frame_norm, template / np.linalg.norm(template))
        if score > best_score:
            best_score = score
            best_chord = chord_name

    return best_chord
