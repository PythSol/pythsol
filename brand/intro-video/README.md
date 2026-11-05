# PythSol intro film

A 28-second, 1920×1080, 30 fps launch film for PythSol 0.1.1.

- `index.html` — the composition and the paused GSAP timeline.
- `assets/` — the real playground screenshot, the brand mark, and the
  generated music bed.
- `tools/make_audio.py` — synthesizes the 28 s bed without samples.
- `pythsol-intro.mp4` — the rendered file (H.264 + AAC, 9.7 MB).

The proof beat uses a real screenshot of `pythsol.com/playground` with
`counter.py` and the emitted C, not a mockup. The code, terminal output, and
version are from the live 0.1.1 tree.

## Check and render

FFmpeg must be on `PATH` (the project was rendered with Gyan FFmpeg 9.0.2).

```powershell
npx hyperframes@0.9.12 check
npx hyperframes@0.9.12 render --quality looks -o pythsol-intro.mp4
```

`check` reports the six `nested_structure_needs_subcomposition` warnings
(the scenes live in one file for a one-off film) and one type-floor warning
for the small code/terminal labels; there are no errors. The film is silent
only if `assets/bgm.mp3` is removed.

## Music

`tools/make_audio.py` writes a 28 s stereo WAV. Normalize it before rendering:

```powershell
python tools/make_audio.py
ffmpeg -y -i assets/bgm.wav -af "loudnorm=I=-14:TP=-1.5:LRA=11" `
  -codec:a libmp3lame -b:a 192k assets/bgm.mp3
```

The render is deterministic; no network fetches or random values are used at
render time.
