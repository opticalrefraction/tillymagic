#!/usr/bin/env python3
"""
tm_updater.py — auto-update logic for TillyMagic.

Checks ver.txt in the game directory against the remote version at
  https://raw.githubusercontent.com/opticalrefraction/tillymagic/refs/heads/master/ver.txt

If remote > local, shows an interactive prompt.
  a / s   — move cursor between Yes / No
  SPACE   — confirm selection

On Yes: downloads the zip, extracts it, replaces game files.
  save file (~/.tillymagic_save.json) is NEVER touched.

On any failure: shows a safe error screen.
"""

import os, sys, time, math, shutil, tempfile, pathlib, urllib.request, zipfile, threading
from tm_core import (
    Input, fg, bg, at, lerp, RST, BOLD, HIDE, SHOW, CLR,
    get_term_size,
)

# re-import the bits we actually need from tm_menus
from tm_menus import (
    write, box, center_text, animated_title,
    shimmer_bar, draw_particles, make_particles, tick_particles,
)

# ── constants ─────────────────────────────────────────────────────────────────

REMOTE_VER_URL  = "https://raw.githubusercontent.com/opticalrefraction/tillymagic/refs/heads/master/ver.txt"
REMOTE_ZIP_URL  = "https://github.com/opticalrefraction/tillymagic/archive/refs/heads/master.zip"
GAME_DIR        = pathlib.Path(__file__).parent.resolve()
LOCAL_VER_FILE  = GAME_DIR / "ver.txt"
SAVE_PATH       = pathlib.Path.home() / ".tillymagic_save.json"

# files/dirs that must never be touched during update
PROTECTED = {SAVE_PATH, LOCAL_VER_FILE}

# ── version helpers ───────────────────────────────────────────────────────────

def _parse_ver(s: str):
    """Parse '1.2.3' → (1,2,3). Returns (0,) on failure."""
    try:
        return tuple(int(x) for x in s.strip().split("."))
    except Exception:
        return (0,)

def read_local_version() -> str:
    try:
        return LOCAL_VER_FILE.read_text().strip()
    except Exception:
        return "0"

def fetch_remote_version(timeout=6) -> str | None:
    try:
        with urllib.request.urlopen(REMOTE_VER_URL, timeout=timeout) as r:
            return r.read().decode().strip()
    except Exception:
        return None

def update_needed(local: str, remote: str) -> bool:
    return _parse_ver(remote) > _parse_ver(local)

# ── palette shortcuts ─────────────────────────────────────────────────────────

_C_BORDER = (55, 55, 75)
_C_WARN   = (220, 140, 40)
_C_GOOD   = (100, 200, 120)
_C_BAD    = (200, 60, 60)
_C_DIM    = (60, 60, 75)
_C_GOLD   = (200, 170, 50)

# ── update prompt ─────────────────────────────────────────────────────────────

def menu_update_prompt(inp: Input, local_ver: str, remote_ver: str) -> bool:
    """
    Show the 'new version available' dialog.
    Returns True if user chose to update, False to skip.
    """
    options = ["Yes, update now", "No, skip"]
    sel     = 0
    particles = make_particles(25, *get_term_size())
    last    = time.time()

    while True:
        now = time.time()
        dt  = now - last; last = now
        tw, th = get_term_size()
        tick_particles(particles, dt, tw, th)

        inp.read()
        keys = inp.get_single()
        for k in keys:
            if k in ('a', 'w', 'UP'):   sel = (sel - 1) % len(options)
            if k in ('s', 'd', 'DOWN'): sel = (sel + 1) % len(options)
            if k in (' ', '\r', '\n'):
                return sel == 0
            if k in ('\x1b', '\x03'):
                return False

        out = CLR + HIDE
        out += draw_particles(particles, tw, th)
        out += animated_title(now, th // 2 - 9)

        # version badge
        out += center_text(
            f"local: {local_ver}   →   remote: {remote_ver}",
            th // 2 - 6, _C_GOLD
        )

        # modal box
        bw, bh = 58, 10
        bx = (tw - bw) // 2
        by = th // 2 - 4
        out += box(bx, by, bw, bh, _C_WARN, title=" Update Available ")

        out += at(bx + 2, by + 2) + fg(*_C_WARN) + BOLD + \
               "A new version of TillyMagic is available." + RST
        out += at(bx + 2, by + 3) + fg(180, 180, 180) + \
               "Would you like to update?" + RST
        out += at(bx + 2, by + 4) + fg(*_C_DIM) + \
               "Your save file will not be touched." + RST

        colors = [_C_GOOD, _C_BAD]
        for i, opt in enumerate(options):
            y2 = by + 6 + i
            out += shimmer_bar(
                f"  {'▶ ' if i == sel else '  '}{opt}  ",
                y2,
                colors[i],
                lerp(colors[i], (50, 50, 65), 0.65),
                i == sel,
            )

        out += center_text("A / S: navigate   SPACE: confirm", th - 2, _C_DIM)
        write(out)
        time.sleep(0.033)


# ── update progress screen ────────────────────────────────────────────────────

class _ProgressState:
    def __init__(self):
        self.status   = "Connecting..."
        self.detail   = ""
        self.percent  = 0          # 0-100, or -1 for indeterminate
        self.done     = False
        self.error    = None       # None or error message string
        self.lock     = threading.Lock()

    def set(self, status, detail="", percent=-1):
        with self.lock:
            self.status  = status
            self.detail  = detail
            self.percent = percent

    def fail(self, msg):
        with self.lock:
            self.error = msg
            self.done  = True

    def succeed(self):
        with self.lock:
            self.done = True


def _do_update(state: _ProgressState):
    """Runs in a background thread. Downloads and installs the update."""
    tmp_dir = None
    try:
        tmp_dir = tempfile.mkdtemp(prefix="tillymagic_update_")
        zip_path = os.path.join(tmp_dir, "update.zip")

        # ── step 1: download via urllib with redirect following ───────────────
        state.set("Downloading update...", REMOTE_ZIP_URL, 0)
        try:
            req = urllib.request.Request(
                REMOTE_ZIP_URL,
                headers={"User-Agent": "TillyMagic-Updater/1.0"}
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                total = int(resp.headers.get("Content-Length", 0))
                downloaded = 0
                chunk_size = 65536
                with open(zip_path, "wb") as f:
                    while True:
                        chunk = resp.read(chunk_size)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total > 0:
                            pct = min(99, int(downloaded * 100 / total))
                            state.set("Downloading update...",
                                      f"{downloaded//1024} / {total//1024} KB", pct)
                        else:
                            state.set("Downloading update...",
                                      f"{downloaded//1024} KB", -1)
        except Exception as e:
            state.fail(f"Download failed: {e}")
            return

        if not os.path.exists(zip_path) or os.path.getsize(zip_path) < 1000:
            state.fail("Downloaded file is missing or too small — network error?")
            return

        # ── step 2: verify and extract ────────────────────────────────────────
        state.set("Extracting archive...", "", -1)
        extract_dir = os.path.join(tmp_dir, "extracted")
        os.makedirs(extract_dir, exist_ok=True)
        try:
            with zipfile.ZipFile(zip_path, 'r') as zf:
                bad = zf.testzip()
                if bad:
                    state.fail(f"Zip file is corrupt (first bad file: {bad})")
                    return
                zf.extractall(extract_dir)
        except zipfile.BadZipFile as e:
            state.fail(f"Extraction failed — bad zip: {e}")
            return
        except Exception as e:
            state.fail(f"Extraction failed: {e}")
            return

        # ── step 3: locate game folder (GitHub unpacks to repo-branch/) ───────
        state.set("Locating game files...", "", -1)
        # find the first directory in the extract root
        src_dir = None
        for entry in os.listdir(extract_dir):
            candidate = os.path.join(extract_dir, entry)
            if os.path.isdir(candidate):
                src_dir = candidate
                break
        if src_dir is None:
            state.fail("Could not find game folder inside zip.")
            return
        # sanity check: should contain tillymagic2.py or tm_core.py
        marker_files = {"tillymagic2.py", "tm_core.py", "tm_game.py"}
        found = set(os.listdir(src_dir))
        if not marker_files.intersection(found):
            state.fail(
                f"Unexpected zip contents (no game files found in {os.path.basename(src_dir)}). "
                f"Got: {', '.join(sorted(found)[:6])}"
            )
            return

        # ── step 4: copy files, skipping protected ────────────────────────────
        state.set("Collecting file list...", "", -1)
        all_files = []
        for root, dirs, files in os.walk(src_dir):
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            for fname in files:
                all_files.append(os.path.join(root, fname))

        state.set("Installing files...", "", 0)
        for i, src_file in enumerate(all_files):
            rel     = os.path.relpath(src_file, src_dir)
            dst     = GAME_DIR / rel
            dst_abs = dst.resolve()

            # never overwrite save file or local version stamp
            if dst_abs == SAVE_PATH.resolve():
                continue
            if dst_abs == LOCAL_VER_FILE.resolve():
                # update ver.txt LAST — only if everything else succeeded
                continue
            # skip hidden files (.gitignore etc.)
            if any(part.startswith('.') for part in pathlib.Path(rel).parts):
                continue

            pct = int(i * 100 / max(1, len(all_files)))
            state.set("Installing files...", rel, pct)
            dst.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(src_file, dst)
            except PermissionError as e:
                state.fail(f"Permission denied copying {rel}: {e}")
                return
            except Exception as e:
                state.fail(f"Failed to copy {rel}: {e}")
                return

        # ── step 5: update ver.txt last (marks update as complete) ───────────
        state.set("Finalising...", "writing ver.txt", 99)
        src_ver = os.path.join(src_dir, "ver.txt")
        if os.path.exists(src_ver):
            try:
                shutil.copy2(src_ver, LOCAL_VER_FILE)
            except Exception as e:
                state.fail(f"Could not update ver.txt: {e}")
                return

        state.set("Done!", "", 100)
        state.succeed()

    except Exception as e:
        state.fail(f"Unexpected error: {e}")
    finally:
        if tmp_dir and os.path.exists(tmp_dir):
            try:
                shutil.rmtree(tmp_dir)
            except Exception:
                pass


def menu_updating(inp: Input) -> bool:
    """
    Show the 'Updating...' progress screen while the background thread works.
    Returns True on success, False on failure.
    """
    state = _ProgressState()
    thread = threading.Thread(target=_do_update, args=(state,), daemon=True)
    thread.start()

    particles = make_particles(20, *get_term_size())
    last = time.time()
    spin_chars = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
    spin_i = 0

    while True:
        now = time.time()
        dt  = now - last; last = now
        tw, th = get_term_size()
        tick_particles(particles, dt, tw, th)

        with state.lock:
            status   = state.status
            detail   = state.detail
            percent  = state.percent
            done     = state.done
            error    = state.error

        if done:
            return (error is None, error or "")

        inp.read()
        keys = inp.get_single()
        # no input accepted — intentional; update can't be cancelled
        _ = keys

        spin_i = (spin_i + 1) % len(spin_chars)

        out = CLR + HIDE
        out += draw_particles(particles, tw, th)
        out += animated_title(now, th // 2 - 9)

        bw, bh = 62, 12
        bx = (tw - bw) // 2
        by = th // 2 - 5
        out += box(bx, by, bw, bh, _C_GOOD, title=" Updating TillyMagic ")

        # spinner + status
        t2 = (math.sin(now * 2) + 1) / 2
        sc = lerp(_C_GOOD, (200, 255, 200), t2)
        out += at(bx + 2, by + 2) + fg(*sc) + BOLD + \
               f"{spin_chars[spin_i]}  {status}" + RST

        # detail / file path
        if detail:
            trunc = detail[-bw + 8:] if len(detail) > bw - 8 else detail
            out += at(bx + 2, by + 3) + fg(*_C_DIM) + trunc + RST

        # progress bar
        bar_w = bw - 6
        if percent >= 0:
            filled = int(bar_w * percent / 100)
            bar    = "█" * filled + "░" * (bar_w - filled)
            pct_clr = lerp(_C_GOOD, (200, 255, 180), percent / 100)
            out += at(bx + 3, by + 5) + fg(*pct_clr) + bar + RST
            out += at(bx + 3, by + 6) + fg(*_C_DIM) + f"{percent}%" + RST
        else:
            # indeterminate snake
            snake_pos = int(now * 20) % (bar_w * 2)
            bar = ["░"] * bar_w
            for j in range(6):
                p2 = (snake_pos - j) % (bar_w * 2)
                if p2 < bar_w:
                    bar[p2] = "█"
            t3 = (math.sin(now * 3) + 1) / 2
            out += at(bx + 3, by + 5) + fg(*lerp(_C_GOOD, (200, 255, 200), t3)) + \
                   "".join(bar) + RST

        # safety notice
        out += at(bx + 2, by + 8) + fg(*_C_DIM) + \
               "Do not terminate the process." + RST
        out += at(bx + 2, by + 9) + fg(*_C_DIM) + \
               "Save data is safe even if the update fails." + RST

        write(out)
        time.sleep(0.033)


def menu_update_error(inp: Input, error_msg: str):
    """Show the update failure screen. Press any key to continue."""
    particles = make_particles(20, *get_term_size())
    last = time.time()

    while True:
        now = time.time()
        dt  = now - last; last = now
        tw, th = get_term_size()
        tick_particles(particles, dt, tw, th)

        inp.read()
        keys = inp.get_single()
        for k in keys:
            if k:
                return  # any key dismisses

        out = CLR + HIDE
        out += draw_particles(particles, tw, th)
        out += animated_title(now, th // 2 - 10)

        bw, bh = 64, 14
        bx = (tw - bw) // 2
        by = th // 2 - 6
        out += box(bx, by, bw, bh, _C_BAD, title=" Update Failed ")

        out += at(bx + 2, by + 2) + fg(*_C_BAD) + BOLD + \
               "Update failed! Your save file is still safe." + RST

        # error detail
        err_lines = [error_msg[i:i+bw-6] for i in range(0, min(len(error_msg), (bw-6)*2), bw-6)]
        for li, line in enumerate(err_lines[:2]):
            out += at(bx + 2, by + 4 + li) + fg(*_C_WARN) + line + RST

        # next steps
        out += at(bx + 2, by + 7) + fg(180, 180, 180) + "Next steps:" + RST
        out += at(bx + 2, by + 8) + fg(*_C_DIM) + \
               "Reinstall TillyMagic from the official repository:" + RST
        repo_url = "https://github.com/opticalrefraction/tillymagic"
        out += at(bx + 2, by + 9) + fg(*_C_GOLD) + BOLD + repo_url + RST

        out += at(bx + 2, by + 11) + fg(*_C_DIM) + \
               "The existing game files have not been modified." + RST

        out += center_text("Press any key to continue", th - 2, _C_DIM)
        write(out)
        time.sleep(0.033)


def menu_update_success(inp: Input, new_ver: str):
    """Show the update success screen."""
    particles = make_particles(20, *get_term_size())
    last = time.time()

    while True:
        now = time.time()
        dt  = now - last; last = now
        tw, th = get_term_size()
        tick_particles(particles, dt, tw, th)

        inp.read()
        keys = inp.get_single()
        for k in keys:
            if k:
                return

        out = CLR + HIDE
        out += draw_particles(particles, tw, th)
        out += animated_title(now, th // 2 - 8)

        bw, bh = 54, 8
        bx = (tw - bw) // 2
        by = th // 2 - 3
        out += box(bx, by, bw, bh, _C_GOOD, title=" Update Complete ")

        t2 = (math.sin(now * 2) + 1) / 2
        gc = lerp(_C_GOOD, (200, 255, 200), t2)
        out += at(bx + 2, by + 2) + fg(*gc) + BOLD + \
               f"TillyMagic updated to v{new_ver}!" + RST
        out += at(bx + 2, by + 3) + fg(180, 180, 180) + \
               "Restart the game to play the new version." + RST
        out += at(bx + 2, by + 5) + fg(*_C_DIM) + \
               "Your save file was not modified." + RST

        out += center_text("Press any key to exit", th - 2, _C_DIM)
        write(out)
        time.sleep(0.033)


# ── main entry point — call this from tillymagic2.main() ─────────────────────

def check_for_update(inp: Input) -> bool:
    """
    Check for an update and run the full flow if one is available.
    Returns True if the game was updated (caller should exit/restart).
    Returns False if no update, skipped, or failed (caller continues normally).
    """
    # 1. read local version
    local_ver = read_local_version()

    # 2. fetch remote (silently fail — no network = no update check)
    remote_ver = fetch_remote_version(timeout=5)
    if remote_ver is None:
        return False   # couldn't reach server — carry on

    # 3. compare
    if not update_needed(local_ver, remote_ver):
        return False   # already up to date

    # 4. prompt user
    sys.stdout.write(CLR + HIDE)
    sys.stdout.flush()

    want_update = menu_update_prompt(inp, local_ver, remote_ver)
    if not want_update:
        return False

    # 5. run update
    success, err_msg = menu_updating(inp)

    if success:
        menu_update_success(inp, remote_ver)
        return True
    else:
        menu_update_error(inp, err_msg or "Unknown error.")
        return False
