#!/usr/bin/env python3
"""
tm_motd.py — Message of the Day fetcher and renderer for TillyMagic.

Fetches MOTD from:
  https://raw.githubusercontent.com/opticalrefraction/tm-motd/refs/heads/main/motd.txt

The MOTD is rendered as a bordered box (═ ║ ╔ ╗ ╚ ╝) on the main menu.
  • Fixed interior height: 8 lines.
  • Box expands horizontally to fit content if needed.
  • Label "MOTD:" sits one row above the top border.
  • Text colour is a random bright colour, re-rolled each launch.
  • Occasionally individual characters get the shimmer/shine sweep.
  • Fetched once at startup in a background thread — never blocks.
"""

import time, math, random, threading, urllib.request
from tm_core import fg, at, lerp, RST, BOLD, get_term_size

# ── constants ─────────────────────────────────────────────────────────────────

MOTD_URL = (
    "https://raw.githubusercontent.com/opticalrefraction/"
    "tm-motd/refs/heads/main/motd.txt"
)

INNER_H = 8          # interior lines (not counting ╔╗ and ╚╝ border rows)
BOX_H   = INNER_H + 2  # total box height including top/bottom border
MIN_W   = 44         # minimum interior width
MAX_W   = 110        # cap so it never overflows a wide terminal
FETCH_TIMEOUT = 6    # seconds

# bright colours the MOTD can pick from — never dark, always readable
_BRIGHT_PALETTES = [
    (255, 200,  80),   # gold
    (100, 220, 255),   # sky blue
    (180, 255, 120),   # lime
    (255, 140, 200),   # pink
    (160, 120, 255),   # lavender
    (255, 180,  80),   # amber
    ( 80, 255, 200),   # teal
    (255, 110, 110),   # coral
    (200, 255, 255),   # ice
    (255, 230, 140),   # pale yellow
]

# ── state (populated by background thread) ───────────────────────────────────

_motd_lines: list[str] = []      # wrapped lines ready to render
_motd_raw:   str        = ""     # raw fetched text
_motd_color: tuple      = (255, 200, 80)
_motd_ready: bool       = False
_motd_lock = threading.Lock()


def _fetch_motd():
    global _motd_lines, _motd_raw, _motd_color, _motd_ready
    try:
        req = urllib.request.Request(
            MOTD_URL,
            headers={"User-Agent": "TillyMagic-MOTD/1.0"}
        )
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
            raw = resp.read().decode("utf-8", errors="replace").strip()
    except Exception:
        raw = ""   # silently fail — MOTD is cosmetic

    with _motd_lock:
        _motd_raw   = raw
        _motd_color = random.choice(_BRIGHT_PALETTES)
        _motd_ready = True
        # wrap will be computed at render time when we know terminal width


def start_motd_fetch():
    """Kick off the background fetch. Call once at startup."""
    t = threading.Thread(target=_fetch_motd, daemon=True)
    t.start()


def _wrap_text(text: str, max_w: int) -> list[str]:
    """
    Wrap text into lines of at most max_w chars.
    Preserves explicit newlines.  Returns up to INNER_H lines.
    """
    lines = []
    for para in text.splitlines():
        para = para.rstrip()
        if not para:
            lines.append("")
            continue
        while len(para) > max_w:
            # break at last space within max_w, or hard-break if no space
            cut = para.rfind(" ", 0, max_w)
            if cut == -1:
                cut = max_w
            lines.append(para[:cut])
            para = para[cut:].lstrip()
        lines.append(para)
    return lines[:INNER_H]


# ── renderer ──────────────────────────────────────────────────────────────────

# shimmer state — a sweep position that drifts across the text
_shimmer_pos  = 0.0
_shimmer_last = time.time()
_shimmer_on   = False           # toggled randomly
_shimmer_next = time.time() + random.uniform(4, 10)


def render_motd_at(now: float, top_row: int = 1) -> str:
    """
    Build and return the ANSI string for the MOTD block.
    Returns "" if the MOTD isn't ready or is empty.
    Call once per frame from menu_main's render loop.
    """
    global _shimmer_pos, _shimmer_last, _shimmer_on, _shimmer_next

    with _motd_lock:
        ready = _motd_ready
        raw   = _motd_raw
        color = _motd_color

    if not ready or not raw:
        return ""

    tw, th = get_term_size()

    # compute inner width to fit longest wrapped line
    max_avail = min(MAX_W, tw - 6)
    test_lines = _wrap_text(raw, max_avail)
    inner_w    = max(MIN_W, max(len(l) for l in test_lines) if test_lines else MIN_W)
    inner_w    = min(inner_w, max_avail)
    lines      = _wrap_text(raw, inner_w)
    while len(lines) < INNER_H:
        lines.append("")

    box_w = inner_w + 2
    bx    = max(1, (tw - box_w) // 2)
    # top_row is where the MOTD: label goes; box starts one row below
    by    = top_row + 1

    if by + BOX_H >= th - 1:
        return ""   # no room

    # ── shimmer ticker ────────────────────────────────────────────────────────
    dt2 = now - _shimmer_last
    _shimmer_last = now

    if _shimmer_on:
        _shimmer_pos += dt2 * 28.0          # speed: chars per second
        total_chars = sum(len(l) for l in lines)
        if _shimmer_pos > total_chars + inner_w:
            _shimmer_on   = False
            _shimmer_next = now + random.uniform(3, 9)
    elif now >= _shimmer_next:
        _shimmer_on  = True
        _shimmer_pos = -inner_w * 0.5       # start off the left edge

    # ── box draw ──────────────────────────────────────────────────────────────
    out = ""

    # border colour: slightly dimmed version of the text colour
    bc = lerp(color, (30, 30, 40), 0.45)

    # "MOTD:" label
    label_x = bx
    t_label = (math.sin(now * 1.4) * 0.5 + 0.5)
    label_c = lerp(color, (255, 255, 255), t_label * 0.35)
    out += at(label_x, top_row) + fg(*label_c) + BOLD + "MOTD:" + RST

    # top border  ╔═══...═══╗
    out += at(bx, by) + fg(*bc) + "╔" + "═" * inner_w + "╗" + RST

    # inner lines
    char_offset = 0   # global character counter for shimmer position
    for row, line in enumerate(lines):
        out += at(bx, by + 1 + row) + fg(*bc) + "║" + RST

        # render each character with optional shimmer
        col_x = bx + 1
        for ci, ch in enumerate(line):
            global_ci = char_offset + ci
            dist = abs(global_ci - _shimmer_pos)
            if _shimmer_on and dist < 6:
                intensity = max(0.0, 1.0 - dist / 6.0)
                c = lerp(color, (255, 255, 255), intensity * 0.85)
            else:
                # subtle per-character flicker using position as phase offset
                flicker = (math.sin(now * 0.6 + global_ci * 0.17) * 0.5 + 0.5)
                c = lerp(color, lerp(color, (255, 255, 255), 0.2), flicker * 0.25)
            out += at(col_x + ci, by + 1 + row) + fg(*c) + ch + RST

        # pad remainder of line to inner_w and close border
        pad = inner_w - len(line)
        out += at(col_x + len(line), by + 1 + row) + " " * pad
        out += at(bx + inner_w + 1, by + 1 + row) + fg(*bc) + "║" + RST

        char_offset += len(line) + 1   # +1 for the implicit newline

    # bottom border  ╚═══...═══╝
    out += at(bx, by + 1 + INNER_H) + fg(*bc) + "╚" + "═" * inner_w + "╝" + RST

    return out

# backwards-compat alias
def render_motd(now: float) -> str:
    return render_motd_at(now, 1)
