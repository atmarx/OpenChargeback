#!/usr/bin/env python3
"""Build the faculty-review storyboard for the OpenChargeback video catalog.

Each narration line sits beside the exact frame it plays over, so a reviewer can
judge wording, clarity, and overclaim from stills without watching five videos.
Every beat carries a citable reference (``02-4``) so notes can point at a line.

The output is one self-contained ``index.html``: fonts and images are inlined as
data URIs and the bytes are pure ASCII, so it renders identically from a file://
path, an nginx docroot, or a Claude Artifact.

Sources live in the IVaC rig, not in this repo:

    ~/Code/IVaC/video_ocb_*.py        the demo scripts (order of play)
    ~/Code/IVaC/output/ocb-*/         rendered stills and subtitle tracks

Run:

    python3 tools/review/build_ocb_review.py
    python3 tools/review/build_ocb_review.py --out /srv/www/ocb-review/index.html

Stdlib only, on purpose -- this has to run anywhere without a venv.
"""

from __future__ import annotations

import argparse
import ast
import base64
import difflib
import html
import os
import re
import sys
from pathlib import Path
from typing import Any

# A beat, a video, a metadata block: all string-keyed records whose values are
# deliberately mixed (text, counts, lists of frames).  Named once so the six
# annotations below say the same thing.
Record = dict[str, Any]

# ── Where things live ──────────────────────────────────────────────────
# IVaC is a sibling checkout, not a dependency.  Override for a different box.
IVAC_ROOT = Path(os.environ.get("IVAC_ROOT", Path.home() / "Code" / "IVaC"))

# Where review notes go.  One line to change if this moves to a shared inbox.
FEEDBACK_EMAIL = "amarx@xram.net"

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = REPO_ROOT / "tools" / "review" / "ocb-review" / "index.html"

# Narration is a serif -- it is the thing being read.  Chrome is the system
# sans.  References and counts are mono.  Found by path so the build fails
# loudly rather than silently falling back to a CDN we cannot reach anyway.
FONT_FILES = {
    "serif-regular": "/usr/share/fonts/truetype/noto/NotoSerif-Regular.ttf",
    "serif-bold": "/usr/share/fonts/truetype/noto/NotoSerif-Bold.ttf",
    "mono-regular": "/usr/share/fonts/truetype/firacode/FiraCode-Regular.ttf",
}

# Auto-captures the rig takes for its own bookkeeping.  A frame of the browser
# mid-navigation tells a reviewer nothing, so these never reach the storyboard.
# They are dropped by construction: only explicit screenshot() and
# _auto_capture() calls in the script are mapped to files.
MECHANICAL_LABELS = {"login", "navigate", "scroll", "type", "click", "glide"}

CAPTURE_CALLS = {"subtitle", "screenshot", "_auto_capture"}


# ── Reading the demo scripts ───────────────────────────────────────────


def _literal(node: ast.AST) -> str | None:
    """Return a string literal's value, or None if it isn't a plain literal."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _joined_str_source(node: ast.JoinedStr) -> str:
    """Flatten an f-string, showing interpolations as ``{expr}``.

    Only a fallback -- when the subtitle track lines up we prefer the words
    that were actually spoken.  See ``load_beats``.
    """
    parts: list[str] = []
    for value in node.values:
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            parts.append(value.value)
        elif isinstance(value, ast.FormattedValue):
            parts.append("{" + ast.unparse(value.value) + "}")
    return "".join(parts)


def collect_calls(tree: ast.AST) -> list[tuple[int, str, str]]:
    """Collect (lineno, kind, argument) for every capture call, in play order.

    Source order is play order.  Sorting by lineno rather than by a running
    counter is what keeps narration and frames interleaved correctly even
    though ``ast`` also walks branches that never execute.
    """
    found: list[tuple[int, str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in CAPTURE_CALLS:
            continue
        if not node.args:
            continue
        arg = node.args[0]
        text = _literal(arg)
        if text is None and isinstance(arg, ast.JoinedStr):
            text = _joined_str_source(arg)
        if text is None:
            continue
        found.append((node.lineno, node.func.attr, text))
    found.sort(key=lambda item: item[0])
    return found


def script_metadata(tree: ast.AST) -> Record:
    """Pull id / title / audience / duration / scenes off the VideoScript call."""
    meta: Record = {"id": "", "title": "", "audience": "", "duration": "", "scenes": []}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = node.func.id if isinstance(node.func, ast.Name) else None
        if name != "VideoScript":
            continue
        for kw in node.keywords:
            if kw.arg == "id":
                meta["id"] = _literal(kw.value) or ""
            elif kw.arg == "title":
                meta["title"] = _literal(kw.value) or ""
            elif kw.arg == "target_audience":
                meta["audience"] = _literal(kw.value) or ""
            elif kw.arg == "duration_estimate":
                meta["duration"] = _literal(kw.value) or ""
            elif kw.arg == "scenes" and isinstance(kw.value, ast.List):
                for item in kw.value.elts:
                    if isinstance(item, ast.Call) and item.args:
                        label = _literal(item.args[0])
                        detail = _literal(item.args[1]) if len(item.args) > 1 else ""
                        if label:
                            meta["scenes"].append((label, detail or ""))
        break
    return meta


# ── Reading the rendered subtitle track ────────────────────────────────


def parse_srt(path: Path) -> list[str]:
    """Return subtitle cue texts in order, whitespace collapsed."""
    if not path.exists():
        return []
    cues: list[str] = []
    for block in re.split(r"\n\s*\n", path.read_text(encoding="utf-8").strip()):
        lines = [ln for ln in block.splitlines() if ln.strip()]
        if len(lines) < 3:
            continue
        if not lines[0].strip().isdigit() or "-->" not in lines[1]:
            continue
        cues.append(re.sub(r"\s+", " ", " ".join(lines[2:])).strip())
    return cues


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def align_to_track(script_lines: list[str], cues: list[str]) -> list[str | None]:
    """Pair each script subtitle with the cue that was actually spoken.

    Not a zip.  ``ast`` reads branches the renderer never took, so a script can
    hold lines that reached no soundtrack -- ocb-03 has two.  Fuzzy matching
    also recovers f-string subtitles, whose rendered cue carries a real filename
    where the source carries an expression.

    Returns one entry per script line: the spoken cue, or None if that line
    never made it into the video.  Returns all-None if the alignment fails to
    account for every cue, so a bad match degrades to the script text rather
    than silently attributing the wrong words to a beat.
    """
    if not cues:
        return [None] * len(script_lines)

    paired: list[str | None] = []
    j = 0
    for line in script_lines:
        if j >= len(cues):
            paired.append(None)
            continue
        ratio = difflib.SequenceMatcher(None, _norm(line), _norm(cues[j])).ratio()
        if ratio >= 0.55:
            paired.append(cues[j])
            j += 1
        else:
            paired.append(None)

    if j != len(cues):
        return [None] * len(script_lines)
    return paired


# ── Resolving a shot label to a file on disk ───────────────────────────


def resolve_still(out_dir: Path, kind: str, label: str, used: set[Path]) -> Path | None:
    """Map a capture label to its rendered frame.

    By glob, never by a sequential counter.  ``ast`` walks branches that never
    ran, so a counter drifts out of step with what the renderer actually wrote
    -- and ocb-03 emits duplicate step numbers besides.  ``used`` makes a label
    that globs several frames take each one only once.
    """
    if kind == "screenshot":
        candidates = [out_dir / f"{label}.webp"]
    else:
        candidates = sorted(out_dir.glob(f"step_*_{label}.webp"))
    for path in candidates:
        resolved = path.resolve()
        if resolved in used or not path.exists():
            continue
        used.add(resolved)
        return path
    return None


# ── Assembling one video ───────────────────────────────────────────────


def load_beats(script_path: Path, out_dir: Path) -> Record:
    """Build a video's storyboard: metadata plus beats, each with its frames."""
    tree = ast.parse(script_path.read_text(encoding="utf-8"))
    meta = script_metadata(tree)
    calls = collect_calls(tree)

    narrations = [text for _, kind, text in calls if kind == "subtitle"]
    cues = parse_srt(out_dir / f"{meta['id']}.srt")

    # The rendered track is the ground truth for what was said.  Only claim a
    # line is missing from the video when the alignment actually held -- with
    # no track, or a failed match, we simply do not know.
    spoken = align_to_track(narrations, cues)
    verified = bool(cues) and any(cue is not None for cue in spoken)
    if cues and not verified:
        print(
            f"  note: {meta['id']} subtitle track would not align -- using script text",
            file=sys.stderr,
        )
    unspoken = [i + 1 for i, cue in enumerate(spoken) if cue is None] if verified else []
    if unspoken:
        print(
            f"  note: {meta['id']} beat(s) {', '.join(map(str, unspoken))} are in the "
            f"script but not in the rendered track",
            file=sys.stderr,
        )

    beats: list[Record] = []
    pending: list[Path] = []
    used: set[Path] = set()
    spoken_i = 0
    missing: list[str] = []

    for _, kind, value in calls:
        if kind == "subtitle":
            cue = spoken[spoken_i] if spoken_i < len(spoken) else None
            beats.append(
                {
                    "n": len(beats) + 1,
                    "text": cue if cue is not None else value,
                    "in_track": cue is not None or not verified,
                    "stills": pending,
                }
            )
            pending = []
            spoken_i += 1
            continue

        if value in MECHANICAL_LABELS:
            continue
        still = resolve_still(out_dir, kind, value, used)
        if still is None:
            missing.append(value)
            continue
        # A frame captured after a line was spoken belongs to that line.
        if beats:
            beats[-1]["stills"].append(still)
        else:
            pending.append(still)

    if pending and beats:
        beats[0]["stills"] = pending + beats[0]["stills"]
    if missing:
        print(f"  note: {meta['id']} has no frame for {', '.join(missing)}", file=sys.stderr)

    meta["beats"] = beats
    meta["num"] = meta["id"].split("-")[1] if "-" in meta["id"] else meta["id"]
    return meta


# ── Rendering ──────────────────────────────────────────────────────────


def data_uri(path: Path, mime: str) -> str:
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def font_face_css() -> str:
    """Inline the fonts.  An Artifact's CSP blocks font CDNs outright."""
    blocks: list[str] = []
    for key, raw in FONT_FILES.items():
        path = Path(raw)
        if not path.exists():
            print(f"  warning: font not found, falling back: {raw}", file=sys.stderr)
            continue
        family, weight = {
            "serif-regular": ("OCBSerif", "400"),
            "serif-bold": ("OCBSerif", "700"),
            "mono-regular": ("OCBMono", "400"),
        }[key]
        uri = data_uri(path, "font/ttf")
        blocks.append(
            f"@font-face{{font-family:'{family}';font-style:normal;"
            f"font-weight:{weight};font-display:swap;src:url({uri}) format('truetype');}}"
        )
    return "\n".join(blocks)


# The one bold moment: ocb-00 is the IS/ISN'T video, and its whole argument is
# a color grammar.  What the register affirms reads green; the two jobs it
# refuses read oxblood; the neighbouring systems it names are merely underlined,
# because they are neither promise nor refusal.
_AFFIRM = re.compile(
    r"\b(register|the honest record|attributes? every charge|balanced journal|"
    r"close package|impartial|to the cent)\b",
    re.I,
)
_REFUSE = re.compile(
    r"\b(will not [a-z ]+?(?=[.,;])|won't [a-z ]+?(?=[.,;])|refuses?d?|"
    r"refused ones|deliberately refuses)\b",
    re.I,
)
_NEUTRAL = re.compile(r"\b(gate|governor|budget caps?|funds check|pre-usage controls?)\b", re.I)


def apply_color_grammar(text: str) -> str:
    """Mark up affirm / refuse / neutral spans.  Escaped input, tags added after."""
    text = _REFUSE.sub(lambda m: f"<span class='refuse'>{m.group(0)}</span>", text)
    text = _AFFIRM.sub(lambda m: f"<span class='affirm'>{m.group(0)}</span>", text)
    text = _NEUTRAL.sub(lambda m: f"<span class='neutral'>{m.group(0)}</span>", text)
    return text


STYLE = """
:root{
  --paper:#f7f4ec; --paper-2:#efeade; --rule:#d8d0bd;
  --ink:#1e1c17; --ink-2:#5c5648; --ink-3:#8a8271;
  --green:#1f5c3e; --oxblood:#7c2230; --accent:#1f5c3e;
  --shadow:rgba(30,28,23,.10);
}
@media (prefers-color-scheme:dark){
  :root{
    --paper:#15161a; --paper-2:#1c1e23; --rule:#2f333b;
    --ink:#e9e4d7; --ink-2:#a9a496; --ink-3:#77736a;
    --green:#6fbf94; --oxblood:#e08b93; --accent:#6fbf94;
    --shadow:rgba(0,0,0,.45);
  }
}
:root[data-theme="dark"]{
  --paper:#15161a; --paper-2:#1c1e23; --rule:#2f333b;
  --ink:#e9e4d7; --ink-2:#a9a496; --ink-3:#77736a;
  --green:#6fbf94; --oxblood:#e08b93; --accent:#6fbf94;
  --shadow:rgba(0,0,0,.45);
}
:root[data-theme="light"]{
  --paper:#f7f4ec; --paper-2:#efeade; --rule:#d8d0bd;
  --ink:#1e1c17; --ink-2:#5c5648; --ink-3:#8a8271;
  --green:#1f5c3e; --oxblood:#7c2230; --accent:#1f5c3e;
  --shadow:rgba(30,28,23,.10);
}

*{box-sizing:border-box}
body{
  margin:0; background:var(--paper); color:var(--ink);
  font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;
  font-size:16px; line-height:1.55; -webkit-text-size-adjust:100%;
}
.wrap{max-width:1180px; margin:0 auto; padding:0 20px 96px}

/* ── Masthead ─────────────────────────────────────────────── */
.masthead{padding:52px 0 28px; border-bottom:3px double var(--rule)}
.eyebrow{
  font-family:'OCBMono',ui-monospace,Menlo,Consolas,monospace;
  font-size:11px; letter-spacing:.18em; text-transform:uppercase;
  color:var(--ink-3); margin:0 0 14px;
}
h1{
  font-family:'OCBSerif',Georgia,serif; font-weight:700;
  font-size:clamp(30px,5vw,46px); line-height:1.12; margin:0 0 16px;
  letter-spacing:-.01em;
}
.standfirst{
  font-family:'OCBSerif',Georgia,serif; font-size:clamp(16px,2.2vw,19px);
  color:var(--ink-2); max-width:64ch; margin:0 0 24px;
}
.standfirst strong{color:var(--ink)}
.tally{
  display:flex; flex-wrap:wrap; gap:0; margin:0 0 26px;
  border:1px solid var(--rule); border-radius:3px; overflow:hidden;
  background:var(--paper-2);
}
.tally div{
  flex:1 1 88px; padding:10px 14px; border-right:1px solid var(--rule);
}
.tally div:last-child{border-right:none}
.tally b{
  display:block; font-family:'OCBMono',ui-monospace,monospace;
  font-size:20px; font-weight:400; color:var(--accent);
}
.tally span{
  font-size:10px; letter-spacing:.14em; text-transform:uppercase; color:var(--ink-3);
}
.actions{display:flex; flex-wrap:wrap; gap:10px; align-items:center}
.btn{
  display:inline-block; padding:10px 18px; border-radius:3px;
  background:var(--accent); color:var(--paper); text-decoration:none;
  font-size:14px; font-weight:600; border:1px solid var(--accent);
}
.btn:hover{opacity:.88}
.btn-ghost{background:transparent; color:var(--ink-2); border-color:var(--rule)}

/* ── Contents ─────────────────────────────────────────────── */
.toc{margin:30px 0 0; padding:0; list-style:none;
  display:grid; grid-template-columns:repeat(auto-fit,minmax(190px,1fr)); gap:10px}
.toc a{
  display:block; padding:12px 14px; border:1px solid var(--rule); border-radius:3px;
  background:var(--paper-2); text-decoration:none; color:var(--ink);
}
.toc a:hover{border-color:var(--accent)}
.toc .no{
  font-family:'OCBMono',ui-monospace,monospace; font-size:11px; color:var(--ink-3);
  display:block; margin-bottom:3px;
}
.toc .nm{font-family:'OCBSerif',Georgia,serif; font-size:15px; line-height:1.3}

/* ── Video sections ───────────────────────────────────────── */
.video{padding:56px 0 8px; border-top:1px solid var(--rule); margin-top:44px}
.video:first-of-type{border-top:none}
.vhead{margin-bottom:34px}
.vno{
  font-family:'OCBMono',ui-monospace,monospace; font-size:12px;
  letter-spacing:.16em; color:var(--accent); text-transform:uppercase;
}
.vtitle{
  font-family:'OCBSerif',Georgia,serif; font-weight:700;
  font-size:clamp(23px,3.4vw,31px); margin:6px 0 12px; line-height:1.18;
}
.vmeta{font-size:13px; color:var(--ink-2); margin:0 0 14px}
.vmeta b{color:var(--ink-3); font-weight:400}
.scenes{margin:0; padding:0; list-style:none; font-size:13px; color:var(--ink-2);
  display:flex; flex-wrap:wrap; gap:6px}
.scenes li{
  padding:4px 10px; border:1px solid var(--rule); border-radius:2px;
  background:var(--paper-2);
}
.scenes li b{font-weight:600; color:var(--ink)}

/* ── Beats ────────────────────────────────────────────────── */
.beat{
  display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1.15fr);
  gap:26px; padding:22px 0; border-bottom:1px solid var(--rule);
  align-items:start; scroll-margin-top:16px;
}
.beat:target{
  background:var(--paper-2); box-shadow:-14px 0 0 var(--paper-2),14px 0 0 var(--paper-2);
}
.beat:last-child{border-bottom:none}
.video.prose .beat{grid-template-columns:1fr}
.video.prose .say{font-size:18px; max-width:68ch}
.line{min-width:0}
.ref{
  font-family:'OCBMono',ui-monospace,monospace; font-size:11px;
  color:var(--ink-3); text-decoration:none; letter-spacing:.06em;
  border:1px solid var(--rule); border-radius:2px; padding:2px 7px;
  display:inline-block; margin-bottom:10px; background:var(--paper-2);
}
.ref:hover{color:var(--accent); border-color:var(--accent)}
.say{
  font-family:'OCBSerif',Georgia,serif; font-size:17px; line-height:1.62;
  margin:0; color:var(--ink);
}
.silent{color:var(--ink-3); font-style:italic}
.beat.cut .say{color:var(--ink-3)}
.tag-cut{
  display:inline-block; margin:0 0 8px 8px; padding:2px 8px; border-radius:2px;
  font-family:'OCBMono',ui-monospace,monospace; font-size:10px;
  letter-spacing:.08em; text-transform:uppercase;
  color:var(--oxblood); border:1px solid var(--oxblood);
}
.cutnote{font-size:12px; color:var(--ink-3); margin:8px 0 0; max-width:56ch}
.frames{display:flex; flex-direction:column; gap:12px; min-width:0}
.frame{margin:0}
.frame img{
  display:block; width:100%; height:auto; border:1px solid var(--rule);
  border-radius:3px; box-shadow:0 1px 5px var(--shadow); background:var(--paper-2);
}
.frame figcaption{
  font-family:'OCBMono',ui-monospace,monospace; font-size:10px;
  color:var(--ink-3); margin-top:5px; letter-spacing:.04em;
  overflow-wrap:anywhere;
}
.noframe{
  font-family:'OCBMono',ui-monospace,monospace; font-size:11px; color:var(--ink-3);
  border:1px dashed var(--rule); border-radius:3px; padding:14px; text-align:center;
}

/* ── ocb-00 color grammar ─────────────────────────────────── */
.affirm{color:var(--green); font-weight:700}
.refuse{color:var(--oxblood); font-weight:700}
.neutral{border-bottom:2px solid var(--ink-3)}
.legend{
  display:flex; flex-wrap:wrap; gap:16px; font-size:12px; color:var(--ink-2);
  margin:0 0 22px; padding:12px 14px; border:1px solid var(--rule);
  border-radius:3px; background:var(--paper-2);
}

/* ── Footer ───────────────────────────────────────────────── */
.foot{
  margin-top:56px; padding-top:22px; border-top:3px double var(--rule);
  font-size:13px; color:var(--ink-2);
}
.foot code{font-family:'OCBMono',ui-monospace,monospace; font-size:12px}

@media (max-width:820px){
  .beat{grid-template-columns:1fr; gap:14px}
  .wrap{padding:0 16px 64px}
  .masthead{padding:34px 0 22px}
}
"""


def render(videos: list[Record]) -> str:
    body: list[str] = []
    add = body.append

    total_beats = sum(len(v["beats"]) for v in videos)
    total_stills = sum(len(b["stills"]) for v in videos for b in v["beats"])

    subject = "OpenChargeback video review notes"
    intro = (
        "Notes below. Please reference beats by number, e.g. 02-4.%0D%0A%0D%0A"
    )
    mailto = f"mailto:{FEEDBACK_EMAIL}?subject={subject.replace(' ', '%20')}&body={intro}"

    add(f"<style>{font_face_css()}\n{STYLE}</style>")
    add('<div class="wrap">')

    # ── Masthead
    add('<header class="masthead">')
    add('<p class="eyebrow">OpenChargeback &middot; Video catalog &middot; Faculty review</p>')
    add("<h1>Read the videos before you watch them.</h1>")
    add(
        '<p class="standfirst">Every line of narration in the OpenChargeback video '
        "catalog, set beside the exact frame it plays over. It reads in about ten "
        "minutes &mdash; far less than watching all five &mdash; and it is the fastest way "
        "to catch a sentence that is unclear, wrong, or promises something the "
        "software does not do. <strong>What we need from you: anything that "
        "overclaims.</strong></p>"
    )
    add('<div class="tally">')
    add(f"<div><b>{len(videos)}</b><span>Videos</span></div>")
    add(f"<div><b>{total_beats}</b><span>Narration beats</span></div>")
    add(f"<div><b>{total_stills}</b><span>Frames</span></div>")
    add("</div>")
    add('<div class="actions">')
    add(f'<a class="btn" href="{mailto}">Send notes</a>')
    add('<a class="btn btn-ghost" href="#v00">Start reading</a>')
    add("</div>")
    add('<ul class="toc">')
    for v in videos:
        add(
            f'<li><a href="#v{v["num"]}"><span class="no">OCB-{v["num"]}</span>'
            f'<span class="nm">{html.escape(v["title"])}</span></a></li>'
        )
    add("</ul>")
    add("</header>")

    # ── Videos
    for v in videos:
        num = v["num"]
        # A card-deck video has no application frames at all, so the frame
        # column would be eight empty boxes.  Give the words the full measure.
        frameless = not any(b["stills"] for b in v["beats"])
        section_cls = "video prose" if frameless else "video"
        add(f'<section class="{section_cls}" id="v{num}">')
        add('<div class="vhead">')
        add(f'<div class="vno">OCB-{num}</div>')
        add(f'<h2 class="vtitle">{html.escape(v["title"])}</h2>')
        meta_bits = []
        if v["audience"]:
            meta_bits.append(f"<b>For</b> {html.escape(v['audience'])}")
        if v["duration"]:
            meta_bits.append(f"<b>Runs</b> {html.escape(v['duration'])}")
        meta_bits.append(f"<b>Beats</b> {len(v['beats'])}")
        add(f'<p class="vmeta">{" &middot; ".join(meta_bits)}</p>')
        if v["scenes"]:
            add('<ul class="scenes">')
            for label, detail in v["scenes"]:
                title_attr = f' title="{html.escape(detail, quote=True)}"' if detail else ""
                add(f"<li{title_attr}><b>{html.escape(label)}</b></li>")
            add("</ul>")
        add("</div>")

        if num == "00":
            add(
                '<p class="legend">'
                '<span><span class="affirm">Green</span> &mdash; what the register affirms</span>'
                '<span><span class="refuse">Oxblood</span> &mdash; what it refuses</span>'
                '<span><span class="neutral">Underline</span> &mdash; the '
                "neighbouring systems it names</span>"
                "</p>"
            )

        for beat in v["beats"]:
            ref = f"{num}-{beat['n']}"
            cls = "beat" if beat["in_track"] else "beat cut"
            add(f'<div class="{cls}" id="{ref}">')
            add('<div class="line">')
            add(f'<a class="ref" href="#{ref}">{ref}</a>')
            if not beat["in_track"]:
                add('<span class="tag-cut">not in the rendered video</span>')
            said = html.escape(beat["text"])
            if num == "00":
                said = apply_color_grammar(said)
            add(f'<p class="say">{said}</p>')
            if not beat["in_track"]:
                add(
                    '<p class="cutnote">This line exists in the demo script but was '
                    "never spoken &mdash; the branch that reaches it did not run during "
                    "the render. No need to review the wording; flagged so the gap is visible.</p>"
                )
            add("</div>")
            if not frameless:
                add('<div class="frames">')
                if beat["stills"]:
                    for still in beat["stills"]:
                        uri = data_uri(still, "image/webp")
                        add(
                            f'<figure class="frame"><img loading="lazy" alt="Frame: '
                            f'{html.escape(still.stem, quote=True)}" src="{uri}">'
                            f"<figcaption>{html.escape(still.name)}</figcaption></figure>"
                        )
                else:
                    add('<div class="noframe">no frame for this line</div>')
                add("</div>")
            add("</div>")
        add("</section>")

    # ── Footer
    add('<footer class="foot">')
    add(
        "<p>Generated from the IVaC demo scripts and their rendered output by "
        "<code>tools/review/build_ocb_review.py</code> in the OpenChargeback repo. "
        "Narration text is the rendered subtitle track &mdash; the words actually spoken. "
        "Frames are the review-worthy captures; navigation and typing frames are omitted.</p>"
    )
    add(f'<p>Notes to <a href="{mailto}">{FEEDBACK_EMAIL}</a>, citing beat numbers.</p>')
    add("</footer>")
    add("</div>")

    # Artifact pages cannot declare a charset -- the platform supplies the head.
    # So we do not rely on one: every non-ASCII character becomes a numeric
    # entity, and the file is byte-identical under any decoding.
    return "\n".join(body).encode("ascii", "xmlcharrefreplace").decode("ascii")


# ── Entry point ────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="output index.html")
    parser.add_argument(
        "--ivac", type=Path, default=IVAC_ROOT, help="path to the IVaC checkout"
    )
    args = parser.parse_args()

    ivac: Path = args.ivac
    scripts = sorted(ivac.glob("video_ocb_*.py"))
    if not scripts:
        print(f"No video_ocb_*.py found under {ivac}", file=sys.stderr)
        print("Set IVAC_ROOT or pass --ivac.", file=sys.stderr)
        return 1

    videos: list[Record] = []
    for script_path in scripts:
        tree = ast.parse(script_path.read_text(encoding="utf-8"))
        video_id = script_metadata(tree)["id"]
        out_dir = ivac / "output" / video_id
        if not out_dir.is_dir():
            print(f"  skipping {script_path.name}: no output at {out_dir}", file=sys.stderr)
            continue
        video = load_beats(script_path, out_dir)
        videos.append(video)
        stills = sum(len(b["stills"]) for b in video["beats"])
        print(f"  {video['id']}: {len(video['beats'])} beats, {stills} frames")

    if not videos:
        print("Nothing to build.", file=sys.stderr)
        return 1

    doc = render(videos)
    if not doc.isascii():
        print("Output is not pure ASCII -- refusing to write.", file=sys.stderr)
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(doc, encoding="ascii")
    size = args.out.stat().st_size
    beats = sum(len(v["beats"]) for v in videos)
    stills = sum(len(b["stills"]) for v in videos for b in v["beats"])
    print(
        f"\nWrote {args.out} -- {len(videos)} videos, {beats} beats, "
        f"{stills} frames, {size / 1_048_576:.2f} MB, pure ASCII."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
