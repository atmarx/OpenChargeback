# Video review storyboard

`build_ocb_review.py` renders the OpenChargeback video catalog as a **storyboard**:
every line of narration beside the exact frame it plays over. Faculty and finance
reviewers judge wording, clarity, and overclaim far faster from stills plus lines
than from five videos — and every beat carries a citable reference (`03-14`) so
notes can point at one sentence.

## Build

```sh
python3 tools/review/build_ocb_review.py
```

Writes `tools/review/ocb-review/index.html` (git-ignored — it is a build artifact).
Stdlib only, no venv required.

```sh
python3 tools/review/build_ocb_review.py --out /srv/www/ocb-review/index.html
IVAC_ROOT=/path/to/IVaC python3 tools/review/build_ocb_review.py
```

## Sources

Inputs live in the IVaC rig, not in this repo:

| Path | Role |
| --- | --- |
| `~/Code/IVaC/video_ocb_*.py` | demo scripts — order of play |
| `~/Code/IVaC/output/ocb-*/*.webp` | rendered frames |
| `~/Code/IVaC/output/ocb-*/*.srt` | subtitle track — the words actually spoken |

If IVaC is elsewhere, set `IVAC_ROOT` or pass `--ivac`.

## The output is self-contained

One HTML file, no external requests. Fonts and images are inlined as data URIs,
and the bytes are **pure ASCII** — every typographic character is a numeric HTML
entity. It renders identically from a `file://` path, an nginx docroot, or a
Claude Artifact. Delivery is a choice made at publish time, not at build time.

## Four things that are easy to get wrong

These were paid for once. Don't re-learn them.

1. **Map shots to files by glob, never by a sequential counter.** `ast` reads
   branches the renderer never took, so a counter drifts out of step with what
   was actually written — and `ocb-03` emits duplicate step numbers besides.
   `screenshot("x")` → `x.webp`; `_auto_capture("y")` → `step_*_y.webp`, each
   resolved path claimed once.

2. **The subtitle track is the ground truth for narration, but it is not a
   `zip`.** Same reason: a script can hold lines that reached no soundtrack
   (`ocb-03` has two). Alignment is fuzzy and self-checking — it must account
   for every cue or it degrades to the script text rather than quietly
   attributing the wrong words to a beat. Lines that never made the render are
   labelled *not in the rendered video* instead of being silently reviewed.
   This also recovers f-string subtitles, whose cue carries a real filename
   where the source carries an expression.

3. **Emit pure ASCII.** An Artifact page cannot declare a charset — the platform
   supplies the `<head>` and there is no way to add one. Without this the first
   render is mojibake (`â€"`, `Â·`). The fix is
   `.encode("ascii", "xmlcharrefreplace")`, and the builder refuses to write a
   file that isn't ASCII.

4. **Inline the fonts.** An Artifact's CSP blocks font CDNs outright, so
   `@font-face` reads from `data:` URIs sourced off `/usr/share/fonts`.

## Feedback path

The CSP also blocks `fetch`/XHR, so there is no backend form — notes come back
by `mailto:`, addressed to `FEEDBACK_EMAIL` at the top of the builder. One line
to change if this moves to a shared inbox.
