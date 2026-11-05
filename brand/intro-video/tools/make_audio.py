"""Synthesize the 28 s PythSol intro bed (no external samples).

Run from the project root:

    .\\.venv\\Scripts\\python.exe brand\\intro-video\\tools\\make_audio.py

Writes brand/intro-video/assets/bgm.wav; convert to MP3 with FFmpeg.
"""

from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

SR = 44100
DURATION = 28.0
N = int(SR * DURATION)
OUT = Path(__file__).resolve().parents[1] / "assets" / "bgm.wav"

# Am, F, C, G — root, third, fifth, sub
CHORDS = [
    (110.00, 261.63, 329.63, 55.00),
    (87.31, 220.00, 261.63, 43.65),
    (130.81, 329.63, 392.00, 65.41),
    (98.00, 246.94, 293.66, 49.00),
]


def env(t: float, start: float, length: float) -> float:
    local = t - start
    if local < 0 or local > length:
        return 0.0
    attack, release = 0.55, 0.75
    if local < attack:
        return local / attack
    if local > length - release:
        return max(0.0, (length - local) / release)
    return 1.0


def main() -> int:
    frames = bytearray()
    seed = 0x12345678
    low = 0.0
    for n in range(N):
        t = n / SR
        chord = min(int(t // 7.0), 3)
        root, third, fifth, sub = CHORDS[chord]
        e = env(t, chord * 7.0, 7.0)
        # Two detuned voices per note give the pad a little width.
        left = (
            math.sin(2 * math.pi * root * t)
            + 0.8 * math.sin(2 * math.pi * third * t + 0.4)
            + 0.6 * math.sin(2 * math.pi * fifth * t + 1.1)
        )
        right = (
            math.sin(2 * math.pi * (root + 0.25) * t + 0.2)
            + 0.8 * math.sin(2 * math.pi * (third + 0.2) * t + 0.8)
            + 0.6 * math.sin(2 * math.pi * (fifth - 0.2) * t + 1.6)
        )
        pad = 0.075 * e
        left *= pad
        right *= pad
        # Sub bass, softer and mono.
        bass = 0.055 * e * math.sin(2 * math.pi * sub * t)
        left += bass
        right += bass
        # Soft pulse at 100 BPM.
        beat = t % 0.6
        if beat < 0.2:
            f = 84.0 - 44.0 * (beat / 0.2)
            pulse = 0.055 * math.exp(-beat * 22.0) * math.sin(2 * math.pi * f * beat)
            left += pulse
            right += pulse
        # Deterministic filtered noise for air.
        seed = (1664525 * seed + 1013904223) & 0xFFFFFFFF
        noise = (seed / 0xFFFFFFFF) * 2.0 - 1.0
        low += 0.002 * (noise - low)
        left += low * 0.5
        right += low * 0.5
        # Global fade in/out.
        fade = min(1.0, t / 1.2, (DURATION - t) / 2.0)
        left *= fade
        right *= fade
        # Keep headroom.
        left = max(-0.95, min(0.95, left))
        right = max(-0.95, min(0.95, right))
        frames += struct.pack("<hh", int(left * 32767), int(right * 32767))
    with wave.open(str(OUT), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(SR)
        handle.writeframes(bytes(frames))
    print(f"wrote {OUT} ({OUT.stat().st_size / 1024 / 1024:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
