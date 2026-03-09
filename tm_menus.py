"""TillyMagic menus."""
from tm_core import *

# ── Drawing helpers ────────────────────────────────────────────────────────────
def clear_screen():
    sys.stdout.write(CLR+HIDE); sys.stdout.flush()

def write(s):
    sys.stdout.write(s); sys.stdout.flush()

def box(x,y,w,h, color=(80,80,100), title=""):
    """Draw a box with optional title."""
    out = ""
    clr = fg(*color)
    out += at(x,y) + clr + "╔" + "═"*(w-2) + "╗" + RST
    for row in range(1,h-1):
        out += at(x,y+row) + clr + "║" + " "*(w-2) + "║" + RST
    out += at(x,y+h-1) + clr + "╚" + "═"*(w-2) + "╝" + RST
    if title:
        tx = x + (w - len(title))//2
        out += at(tx, y) + clr + " " + title + " " + RST
    return out

def center_text(text, y, color=(200,200,200), bold=False):
    tw,th = get_term_size()
    x = max(0, (tw - len(text))//2)
    b = BOLD if bold else ""
    return at(x,y) + fg(*color) + b + text + RST

def animated_title(now, y):
    """Animated TillyMagic title with colour sweep."""
    title = "✦  T I L L Y M A G I C  ✦"
    tw,_ = get_term_size()
    cx = max(0,(tw-len(title))//2)
    out = at(cx,y)
    for i,c in enumerate(title):
        phase = (now*1.5 - i*0.12) % (math.pi*2)
        t = (math.sin(phase)+1)/2
        clr = lerp((120,40,200),(255,160,255),t)
        out += fg(*clr)+c
    return out+RST

def shimmer_bar(text, y, sel_color, unsel_color, selected):
    """A menu item that glows when selected."""
    now = time.time()
    tw,_ = get_term_size()
    cx = max(0,(tw-len(text))//2)
    out = at(cx,y)
    if selected:
        for i,c in enumerate(text):
            phase = (now*3 - i*0.2) % (math.pi*2)
            t = (math.sin(phase)+1)/2
            clr = lerp(sel_color, (255,255,255), t*0.4)
            out += fg(*clr)+BOLD+c+RST
    else:
        out += fg(*unsel_color)+text+RST
    return out

def draw_particles(particles, tw, th):
    """Floating background particles (pure aesthetic)."""
    out = ""
    for p in particles:
        px,py,char,clr,_ = p
        xi,yi = int(px)%tw, int(py)%th
        if 2<=xi<tw-2 and 2<=yi<th-4:
            out += at(xi,yi)+fg(*clr)+char+RST
    return out

def make_particles(n, tw, th):
    chars = list("·∙•◦°*+✦✧")
    return [[random.uniform(0,tw), random.uniform(2,th-4),
             random.choice(chars),
             (random.randint(40,100), random.randint(20,80), random.randint(80,160)),
             (random.uniform(-2,2), random.uniform(-1,1))] for _ in range(n)]

def tick_particles(particles, dt, tw, th):
    for p in particles:
        p[0] = (p[0]+p[4][0]*dt) % tw
        p[1] = (p[1]+p[4][1]*dt) % (th-4)
        if p[1] < 2: p[1] = 2

# ── Tips content ──────────────────────────────────────────────────────────────
TIPS_TABS = ["Controls","Classes","Bosses","Maps","Upgrades","Tips"]
TIPS_CONTENT = {
    "Controls": [
        "─── Movement ───────────────────────────────────────",
        "  WASD           Move your character",
        "  Q              Dash (away from boss, 10s cooldown)",
        "  1-5            Select a move/ability",
        "  SPACE          Use the currently selected move",
        "  ESC            Quit game",
        "",
        "─── Combat ─────────────────────────────────────────",
        "  Moves auto-target the closest enemy in range.",
        "  Melee range is ~2 units, ranged varies by move.",
        "  If a move is on cooldown, pressing SPACE shows",
        "  a 'Cooldown!' flash in the middle of the screen.",
        "",
        "─── HUD ────────────────────────────────────────────",
        "  Bottom-left: move list. Selected move = red.",
        "  Cooldown moves show a countdown timer in grey.",
        "  When ultimate is ready (HP < 50%), move 5 glows",
        "  with an animated orange sweep effect.",
        "  Top: player HP (left) and boss HP (right).",
    ],
    "Classes": [
        "─── Wizard ──────────────────────────────────────────",
        "  1: Scepter       5-hit ranged combo (range 6)",
        "                   5th hit stuns. Purple projectiles.",
        "  2: Arcane Snap   AOE ripple, stuns all (range 10)",
        "  3: Gravemark     Rune pulls boss (range 8, 30 dmg)",
        "  4: Blink Scatter Teleport + 3 exploding afterimages",
        "  5: Wizard's Downfall (ULT) Whirlpool across map,",
        "     pulls enemies, 20 dmg/0.5s for 5s. <50% HP only.",
        "",
        "─── Gravedigger ─────────────────────────────────────",
        "  1: Shovel       Melee combo (range 2), 8 dmg x4,",
        "                  5th: 20 dmg spinning slam + knockback",
        "  2: Dig          Plant landmine at your feet (40 dmg)",
        "                  Up to 3 mines. Triggered by proximity.",
        "  3: Bury         Root + 15 dmg (range 5, 2.5s stun)",
        "  4: Exhume       Recall and detonate ALL active mines",
        "  5: Six Feet Under (ULT) 1.5s invincible, fissure",
        "     ring tears outward: 50 dmg + 3s stun. <50% HP.",
        "",
        "─── Marionette ──────────────────────────────────────",
        "  1: Silk Strike  Melee combo (range 2), 6 dmg each",
        "  2: Plant String Attach string to boss. Strings",
        "                  reflect 30% damage back. Max 3.",
        "  3: Puppet Pull  Drag boss toward you (range 10)",
        "  4: Redirect     Next boss attack hits itself",
        "  5: Cut All Strings (ULT) Burst all strings,",
        "     15 dmg per string active. <50% HP only.",
        "",
        "─── Cartographer ────────────────────────────────────",
        "  1: Ink Stab     Melee combo, marks tiles walked on",
        "                  Marked tiles deal 3 dmg to enemies",
        "  2: Flare        Blind boss for 2s (range 8)",
        "  3: Quicksand    Slow zone at cursor (range 8)",
        "  4: Terrain Wall Raise impassable wall (2s)",
        "  5: Map Ignition (ULT) All charted tiles ignite,",
        "     5 dmg per tile. Massive if you've moved lots.",
        "",
        "─── Revenant ────────────────────────────────────────",
        "  Has 5 LIVES instead of a single HP bar.",
        "  Each life = 60 HP. Gets +15% dmg per death.",
        "  Final life: leaves burning floor trails.",
        "  1: Death Blow   Heavy melee, 12 dmg (range 2)",
        "  2: Rage Strike  Fast light hit, 6 dmg (range 2)",
        "  3: Bone Shield  Absorb next hit (8s cd)",
        "  4: Self-Destruct Sacrifice current life for 80 dmg",
        "  5: Berserk (ULT) Full invincible frenzy, all moves",
        "     cost 0 cd for 4s, +50% dmg. <50% HP only.",
        "",
        "─── Siphon ──────────────────────────────────────────",
        "  Stores up to 3 CHARGES from absorbed boss attacks.",
        "  1: Hijack        3s cd. Opens a 1.5s reflect window.",
        "                   If boss attacks during window, hit is",
        "                   absorbed as a charge. 50% reflects now.",
        "                   Press again to cancel early.",
        "  2: Overload      Detonate all charges for burst dmg.",
        "                   More charges = much more damage.",
        "  3: Null Field    Zone that blocks boss buffs for 8s.",
        "  4: Leech         Steal boss speed/armor. +15 dmg drain.",
        "  5: Void Surge (ULT) Expanding ring of void energy.",
        "     More charges = more waves and damage. <50% HP.",
        "  TIP: Hijack has a 3s cd. Run and survive the gaps!",
    ],
    "Bosses": [
        "─── The Warden (Boss 1) ─────────────────────────────",
        "  HP: 300  Damage: 15  Reward: 50 coins",
        "  Tracks you down and telegraphs attacks with a",
        "  red '#' that brightens over 2 seconds, then",
        "  locks in position. 0.5s plummet before hit lands.",
        "  You have time to move — watch the colour!",
        "",
        "─── The Stonewarden (Boss 2) ────────────────────────",
        "  HP: 300  Damage: 25  Reward: 80 coins",
        "  Phase 1: Stone shell halves all damage until",
        "  you deal 150 to crack it. Slow but relentless.",
        "  Phase 2: Shell breaks. Fast erratic charges,",
        "  rubble walls, and stone pillars erupt from floor.",
        "",
        "─── The Tide Caller (Boss 3) ────────────────────────",
        "  HP: 450  Damage: 20 (x2 bursts)  Reward: 150",
        "  Spreads ~ water pools that slow movement.",
        "  Fires long water jets in 4 cardinal directions.",
        "  Submerges periodically — untargetable for 2s.",
        "  Map current drifts your character sideways.",
        "",
        "─── The Hollow Conductor (Boss 4) ───────────────────",
        "  HP: 600  Damage: 30  Reward: 300 coins",
        "  ALL attacks follow a visible beat bar at bottom.",
        "  Learn the rhythm — it's the only way to survive.",
        "  Below 50% HP: performs Trill. Watch for phases:",
        "  Advance (closes in), Vibrate (rapid chip hits),",
        "  Retreat (pulls back), Slam (lunges for 125% dmg).",
        "",
        "─── The Pale Architect (Boss 5) ─────────────────────",
        "  HP: 450  Damage: 22  Reward: 300 coins",
        "  Raises new wall segments every 12s between you.",
        "  Can phase through its own walls. You cannot.",
        "  Schematic projectile: cage builds around where",
        "  it lands. Move out within 1.5s or take big damage.",
        "",
        "─── The Sovereign Hound (Boss 6) ────────────────────",
        "  HP: 550  Damage: 28  Reward: 400 coins",
        "  Cycles: Hunt (15s fast, aggressive) then Rest (8s).",
        "  During Rest: summons 2 shadow puppies. Ignore them.",
        "  Pounce: 2s crouch telegraph then extreme-speed lunge.",
        "  Miss = 1.5s stun window. Hit = massive damage + rebound.",
        "  Immune to ALL knockback and repositioning effects.",
        "",
        "─── The Liminal (Boss 7) ────────────────────────────",
        "  HP: 700 (350 Light + 350 Void)  Reward: 500 coins",
        "  Two halves: damaging one heals the other at 50%.",
        "  Focus one half, then swap before recovery catches up.",
        "  Convergence beams fire from both edges toward center.",
        "  Safe gap is the 6-tile zone in the middle.",
        "  Below 40% HP: attempts a 5s Merge (full heal + enrage).",
        "  Deal 80 dmg during the merge animation to interrupt.",
    ],
    "Maps": [
        "─── Standard Arena  (1.0x coins) ────────────────────",
        "  A plain open arena. No hazards or restrictions.",
        "  Full space to move and fight freely.",
        "  Good for learning classes and boss patterns.",
        "",
        "─── The Ossuary  (1.2x coins) ───────────────────────",
        "  Bone-lined crypt. Skull and ribcage wall motifs.",
        "  Four indestructible bone pillars in the corners",
        "  constrict the safe movement space significantly.",
        "  Boss attacks have less room to telegraph.",
        "",
        "─── The Molten Forge  (1.6x coins) ──────────────────",
        "  Two horizontal lava channels split the arena",
        "  into three lanes. Lava is instant death.",
        "  Cross only with Dash, Blink Scatter, or similar.",
        "  Corner furnaces blast fire columns periodically.",
        "",
        "─── The Mirror Vault  (2.5x coins) ──────────────────",
        "  High-contrast silver ASCII architecture.",
        "  Boss has a mirrored clone on the opposite side",
        "  that mimics every move for half damage.",
        "  Clone reforms 5s after being shattered.",
        "  NOTE: Procedural size scaling disabled on this map.",
        "",
        "─── The Shattered Clock  (1.8x coins) ───────────────",
        "  Gear segments embedded in the floor block movement.",
        "  A pendulum swings at the bottom — pure decoration.",
        "  Clock Hand sweeps the full map every 20s (40 dmg).",
        "  3s warning arc appears before each sweep.",
        "  TIP: watch the boss Y position — sweep follows it.",
        "",
        "─── The Sunken Reliquary  (2.2x coins) ──────────────",
        "  Water rises every 45s. Full flood at 2:15 in.",
        "  Water slows movement 30%. Deep water: silent mode.",
        "  6 chests scattered around. Stand on one for 1s.",
        "  Chests give: heal, +damage, +speed, or boss blind.",
        "  Boss can also smash chests as it walks over them.",
        "",
        "─── The Inverted Spire  (3.0x coins) ────────────────",
        "  Arena wraps: leaving the left edge reappears right.",
        "  Same for top and bottom. Boss also wraps.",
        "  Boss shortest path may cut through the seam.",
        "  Spire Spikes erupt every 12s (50 dmg). 2s warning.",
        "  3.0x coins — highest risk map in the game.",
    ],
    "Upgrades": [
        "─── How Upgrades Work ───────────────────────────────",
        "  Access the Store from the main menu.",
        "  Each class has its own upgrade track (level 1-10).",
        "  Upgrading only affects the class you are playing.",
        "  Each level randomly assigns one stat bonus.",
        "",
        "─── Stats ───────────────────────────────────────────",
        "  Strength          +10% damage per point",
        "  Cooldown Reduction -8% all cooldowns per point",
        "  Speed              +2 movement speed per point",
        "  Dash Range         +1 dash distance per point",
        "  Absorbency         +5% damage absorbed (shield)",
        "  Hit Range          +0.5 melee/ranged reach",
        "",
        "─── Costs ───────────────────────────────────────────",
        "  Level 1→2:  ~30 coins    Level 5→6:  ~120 coins",
        "  Level 2→3:  ~50 coins    Level 7→8:  ~180 coins",
        "  Level 3→4:  ~75 coins    Level 9→10: ~250 coins",
        "  Coins are earned by defeating bosses.",
        "  Harder bosses and riskier maps give more coins.",
    ],
    "Tips": [
        "─── General Tips ─────────────────────────────────────",
        "  Watch the red # warning before boss attacks.",
        "  The hash brightens gradually — darker = more time.",
        "  Use Dash (Q) to escape combos, not just to reposition.",
        "",
        "  Stun-locking the boss with combos is very effective.",
        "  Chain Arcane Snap or Bury into damage moves.",
        "",
        "─── Class Tips ───────────────────────────────────────",
        "  Wizard:       Stay at max range. Never let Scepter",
        "                fall off — its 5-hit cycle is your DPS.",
        "  Gravedigger:  Pre-place mines before engaging.",
        "                Bury → Exhume is your core combo.",
        "  Marionette:   Stack 3 strings before using Redirect",
        "                for triple-reflected damage.",
        "  Cartographer: Move constantly to chart tiles.",
        "                Save Ignition for dense fought areas.",
        "  Revenant:     Don't fear death — it powers you up.",
        "                Use Self-Destruct strategically.",
        "",
        "─── Map Tips ─────────────────────────────────────────",
        "  Ossuary: Use pillars as body-blocks vs boss charges.",
        "  Forge:   Pick a lane and own it. Don't lane-hop.",
        "  Mirror:  Kill the clone first — it disrupts focus.",
        "  Clock:   Learn the sweep Y before committing.",
        "  Reliquary: Open chests early before water rises.",
        "  Spire:   Use the wrap to escape being cornered.",
        "",
        "─── Siphon Tips ──────────────────────────────────────",
        "  You have no real damage of your own. Move constantly.",
        "  Hijack has a 3s cooldown — you will have dead time.",
        "  Time Hijack JUST before a boss swing for easy grabs.",
        "  Overload with 3 charges does enormous burst damage.",
        "  Null Field + Leech combo makes you briefly faster",
        "  than the boss. Use that window for positioning.",
        "",
        "─── Liminal Tips ─────────────────────────────────────",
        "  Never split damage equally — always focus one half.",
        "  Interrupt the Merge or the fight resets to 60% HP.",
        "  Convergence beams always target your current Y row.",
        "  Dash vertically away — not sideways — to dodge beams.",
    ],
}

# ── Menu screens ──────────────────────────────────────────────────────────────

def menu_class_select(inp):
    classes = list(CLASS_DATA.keys())
    sel = 0
    particles = make_particles(30, *get_term_size())
    last = time.time()

    while True:
        now = time.time()
        dt = now - last; last = now
        tw, th = get_term_size()
        tick_particles(particles, dt, tw, th)

        inp.read()
        keys = inp.get_single()
        for k in keys:
            if k in ('w','\x1b[A') and not k in 'wasd': sel=(sel-1)%len(classes)
            if k == 'w': sel=(sel-1)%len(classes)
            if k == 's': sel=(sel+1)%len(classes)
            if k in (' ','\r','\n'): return classes[sel]
            if k in ('\x03','\x1b'): return None

        out = CLR + HIDE
        out += draw_particles(particles, tw, th)
        out += animated_title(now, 1)
        out += center_text("── SELECT YOUR CLASS ──", 3, (120,80,160))

        box_w = 56
        bx = (tw - box_w)//2

        for i, cls in enumerate(classes):
            cd = CLASS_DATA[cls]
            row_start = 5 + i * 6
            selected = (i == sel)
            clr = cd["color"]
            border_clr = lerp(clr,(255,255,255),0.3) if selected else (50,50,60)

            out += box(bx, row_start, box_w, 5, border_clr)
            name = cls.upper()
            if selected:
                t = (math.sin(now*3)+1)/2
                name_clr = lerp(clr,(255,255,255),t*0.5)
                prefix = "▶ "
            else:
                name_clr = lerp(clr,(80,80,80),0.5)
                prefix = "  "
            out += at(bx+2, row_start+1) + fg(*name_clr)+BOLD+prefix+name+RST
            out += at(bx+2, row_start+2) + fg(120,120,120) + cd["desc"][0][:box_w-4] + RST
            out += at(bx+2, row_start+3) + fg(100,100,100) + cd["desc"][1][:box_w-4] + RST

        out += center_text("W/S to navigate   SPACE to confirm   ESC to quit", th-2, (70,70,90))
        write(out)
        time.sleep(0.033)


def menu_boss_select(inp):
    bosses = list(BOSS_DATA.keys())
    sel = 0
    particles = make_particles(25, *get_term_size())
    last = time.time()

    while True:
        now = time.time()
        dt = now - last; last = now
        tw, th = get_term_size()
        tick_particles(particles, dt, tw, th)

        inp.read()
        keys = inp.get_single()
        for k in keys:
            if k == 'w': sel=(sel-1)%len(bosses)
            if k == 's': sel=(sel+1)%len(bosses)
            if k in (' ','\r','\n'): return bosses[sel]
            if k in ('\x03','\x1b'): return None

        out = CLR + HIDE
        out += draw_particles(particles, tw, th)
        out += animated_title(now, 1)
        out += center_text("── SELECT YOUR BOSS ──", 3, (160,60,60))

        box_w = 60
        bx = (tw - box_w)//2

        for i, boss_key in enumerate(bosses):
            bd = BOSS_DATA[boss_key]
            row_start = 5 + i * 7
            selected = (i == sel)
            clr = bd["color"]
            border_clr = lerp(clr,(255,255,255),0.4) if selected else (50,50,60)

            out += box(bx, row_start, box_w, 6, border_clr)
            name = bd["name"]
            coins = bd["coins"]
            if selected:
                t=(math.sin(now*3)+1)/2
                name_clr = lerp(clr,(255,255,255),t*0.4)
                prefix = "▶ "
            else:
                name_clr = lerp(clr,(80,80,80),0.5)
                prefix = "  "
            out += at(bx+2, row_start+1)+fg(*name_clr)+BOLD+prefix+name+RST
            out += at(bx+2+box_w-18, row_start+1)+fg(200,170,50)+f"Reward: {coins} coins"+RST
            stats = f"HP:{bd['hp']}  DMG:{bd['damage']}  HIT CD:{bd['hit_cd']}s"
            out += at(bx+2, row_start+2)+fg(130,130,130)+stats+RST
            out += at(bx+2, row_start+3)+fg(110,110,110)+bd["desc"][0][:box_w-4]+RST
            out += at(bx+2, row_start+4)+fg(90,90,90)+bd["desc"][1][:box_w-4]+RST

        out += center_text("W/S to navigate   SPACE to confirm   ESC to go back", th-2, (70,70,90))
        write(out)
        time.sleep(0.033)


def menu_map_select(inp):
    maps = list(MAP_DATA.keys())
    sel = 0
    particles = make_particles(20, *get_term_size())
    last = time.time()

    while True:
        now = time.time()
        dt = now - last; last = now
        tw, th = get_term_size()
        tick_particles(particles, dt, tw, th)

        inp.read()
        keys = inp.get_single()
        for k in keys:
            if k == 'w': sel=(sel-1)%len(maps)
            if k == 's': sel=(sel+1)%len(maps)
            if k in (' ','\r','\n'): return maps[sel]
            if k in ('\x03','\x1b'): return None

        out = CLR + HIDE
        out += draw_particles(particles, tw, th)
        out += animated_title(now, 1)
        out += center_text("── SELECT YOUR MAP ──", 3, (60,160,140))

        box_w = 60
        bx = (tw - box_w)//2

        for i, map_key in enumerate(maps):
            md = MAP_DATA[map_key]
            row_start = 5 + i * 7
            selected = (i == sel)
            clr = md["color"]
            border_clr = lerp(clr,(255,255,255),0.4) if selected else (50,50,60)

            out += box(bx, row_start, box_w, 6, border_clr)
            name = md["name"]
            mult = md["coin_mult"]
            if selected:
                t=(math.sin(now*3)+1)/2
                name_clr = lerp(clr,(255,255,255),t*0.4)
                prefix = "▶ "
            else:
                name_clr = lerp(clr,(80,80,80),0.5)
                prefix = "  "
            out += at(bx+2, row_start+1)+fg(*name_clr)+BOLD+prefix+name+RST
            mult_clr = lerp((100,200,100),(255,200,50),(mult-1.0)/1.5)
            out += at(bx+2+box_w-18, row_start+1)+fg(*mult_clr)+f"x{mult:.1f} coins"+RST
            if not md["procedural"]:
                out += at(bx+2, row_start+2)+fg(100,100,100)+"[Fixed geometry — size scaling unavailable]"+RST
            else:
                out += at(bx+2, row_start+2)+fg(130,130,130)+md["desc"][0][:box_w-4]+RST
            out += at(bx+2, row_start+3)+fg(110,110,110)+md["desc"][1][:box_w-4]+RST
            out += at(bx+2, row_start+4)+fg(90,90,90)+md["desc"][2][:box_w-4]+RST

        out += center_text("W/S to navigate   SPACE to confirm   ESC to go back", th-2, (70,70,90))
        write(out)
        time.sleep(0.033)


def menu_size_select(inp, map_key):
    """Map size selection. Greyed out if map doesn't support procedural."""
    md = MAP_DATA[map_key]
    proc = md["procedural"]
    sizes = [
        ("Fullscreen  (fills terminal)",    1.5,  0.7),
        ("Large       (100x27)",            1.25, 1.0),
        ("Default     (80x22)",             1.0,  1.2),
    ]
    sel = 0
    particles = make_particles(20, *get_term_size())
    last = time.time()

    while True:
        now = time.time()
        dt = now - last; last = now
        tw, th = get_term_size()
        tick_particles(particles, dt, tw, th)

        inp.read()
        keys = inp.get_single()
        for k in keys:
            if k in ('w','UP'):    sel = max(0, sel-1)
            elif k in ('s','DOWN'): sel = min(len(sizes)-1, sel+1)
            elif k in (' ','\r','\n'):
                if not proc and sizes[sel][1] > 1.0:
                    pass  # greyed, ignore
                else:
                    return sizes[sel][1], sizes[sel][2]
            elif k in ('\x03','\x1b'): return None, None

        out = CLR + HIDE
        out += draw_particles(particles, tw, th)
        out += animated_title(now, 1)
        out += center_text("\u2500\u2500 MAP SIZE \u2500\u2500", 3, (80,180,160))
        out += center_text("Smaller maps = more challenge = more coins", 4, (120,130,100))

        if not proc:
            out += center_text("This map uses fixed geometry — only Default size available.", 6, (160,100,100))

        box_w = 58
        bx = (tw - box_w)//2
        row_start = 7

        for i,(label,size_mult,coin_m) in enumerate(sizes):
            selected = (i == sel)
            greyed = (not proc and size_mult > 1.0)
            border_c = (70,70,80) if greyed else ((120,180,160) if selected else (50,50,60))
            out += box(bx, row_start+i*4, box_w, 3, border_c)

            if greyed:
                txt = fg(55,55,55)+label+" [NOT AVAILABLE]"+RST
                coin_txt = ""
            elif selected:
                t=(math.sin(now*4)+1)/2
                clr=lerp((60,160,140),(180,255,220),t)
                txt = fg(*clr)+BOLD+"\u25b6 "+label+RST
                coin_m_clr = lerp((180,180,80),(100,220,100),(coin_m-0.7)/0.5)
                coin_txt = fg(*coin_m_clr)+BOLD+f"x{coin_m:.1f} coins"+RST
            else:
                txt = fg(140,140,140)+label+RST
                coin_m_clr = lerp((100,100,60),(80,160,80),(coin_m-0.7)/0.5)
                coin_txt = fg(*coin_m_clr)+f"x{coin_m:.1f} coins"+RST

            out += at(bx+3, row_start+i*4+1)+txt
            if coin_txt:
                out += at(bx+box_w-14, row_start+i*4+1)+coin_txt

        note = "Larger maps increase player & boss speed for fairness."
        out += center_text(note, row_start+len(sizes)*4+1, (90,110,100))
        out += center_text("W/S / \u2191\u2193 to navigate   SPACE to confirm   ESC to go back", th-2, (70,70,90))
        write(out)
        write(out)
        time.sleep(0.033)


def menu_tips(inp):
    tab_idx = 0
    scroll = 0
    particles = make_particles(15, *get_term_size())
    last = time.time()

    while True:
        now = time.time()
        dt = now - last; last = now
        tw, th = get_term_size()
        tick_particles(particles, dt, tw, th)

        inp.read()
        keys = inp.get_single()
        for k in keys:
            if k in ('a','LEFT'):    tab_idx=(tab_idx-1)%len(TIPS_TABS); scroll=0
            elif k in ('d','RIGHT'): tab_idx=(tab_idx+1)%len(TIPS_TABS); scroll=0
            elif k in ('w','UP'):    scroll=max(0,scroll-1)
            elif k in ('s','DOWN'):  scroll+=1
            elif k in ('\x03','\x1b'): return

        content = TIPS_CONTENT[TIPS_TABS[tab_idx]]
        max_scroll = max(0, len(content)-(th-8))
        scroll = min(scroll, max_scroll)

        out = CLR + HIDE
        out += draw_particles(particles, tw, th)
        out += animated_title(now, 1)
        out += center_text("── PLAYING TIPS ──", 3, (100,180,140))

        # Tab bar
        tab_str = ""
        for i, tab in enumerate(TIPS_TABS):
            if i == tab_idx:
                t=(math.sin(now*3)+1)/2
                clr=lerp((60,180,120),(160,255,180),t)
                tab_str += fg(*clr)+BOLD+f"[ {tab} ]"+RST
            else:
                tab_str += fg(70,70,80)+f"  {tab}  "+RST
        tab_x = max(0,(tw-len(tab_str)//4*3-10)//2)  # rough center
        # simpler: just place it
        actual_len = sum(len(t)+6 for t in TIPS_TABS)
        tab_x2 = max(0,(tw-actual_len)//2)
        out += at(tab_x2, 4)+tab_str

        # Divider
        out += at(0, 5)+fg(60,60,70)+"─"*tw+RST

        # Content
        visible = content[scroll:scroll+(th-8)]
        for i,line in enumerate(visible):
            x = max(0,(tw-60)//2)
            if line.startswith("─"):
                clr=(100,180,140)
            elif line.startswith("  ") and ":" in line:
                clr=(180,180,100)
            else:
                clr=(160,160,160)
            out += at(x, 6+i)+fg(*clr)+line[:tw-x-1]+RST

        # Scroll indicator
        if max_scroll > 0:
            pct = scroll/max_scroll
            out += at(tw-4, 6+int(pct*(th-10)))+fg(80,80,100)+"◈"+RST

        out += at(0,th-2)+fg(70,70,90)+"  A/D: switch tabs   W/S: scroll   ESC: back"+RST
        write(out)
        time.sleep(0.033)


def menu_store(inp, save):
    """Upgrade store. Returns updated save."""
    classes = list(CLASS_DATA.keys())
    cls_idx = 0
    particles = make_particles(20, *get_term_size())
    last = time.time()
    msg = ""
    msg_until = 0

    while True:
        now = time.time()
        dt = now - last; last = now
        tw, th = get_term_size()
        tick_particles(particles, dt, tw, th)

        inp.read()
        keys = inp.get_single()
        for k in keys:
            if k in ('a','LEFT'):    cls_idx=(cls_idx-1)%len(classes)
            elif k in ('d','RIGHT'): cls_idx=(cls_idx+1)%len(classes)
            elif k in (' ','\r','\n'):
                cls = classes[cls_idx]
                lvl = save["class_levels"].get(cls,1)
                if lvl >= 10:
                    msg="Already at max level!"; msg_until=now+2
                else:
                    cost = upgrade_cost(lvl)
                    if save["coins"] < cost:
                        msg=f"Need {cost} coins! (have {save['coins']})"; msg_until=now+2
                    else:
                        save["coins"] -= cost
                        save["class_levels"][cls] = lvl+1
                        stat = random.choice(UPGRADE_STATS)
                        cs = save.setdefault("class_stats",{}).setdefault(cls,{})
                        cs[stat] = cs.get(stat,0)+1
                        msg=f"Level up! +{UPGRADE_DESCS[stat]}"; msg_until=now+2.5
                        write_save(save)
            elif k in ('\x03','\x1b'): return save

        cls = classes[cls_idx]
        cd = CLASS_DATA[cls]
        lvl = save["class_levels"].get(cls,1)
        coins = save["coins"]
        cost = upgrade_cost(lvl) if lvl < 10 else 0

        out = CLR + HIDE
        out += draw_particles(particles, tw, th)
        out += animated_title(now, 1)
        out += center_text("── UPGRADE STORE ──", 3, (200,160,50))
        coin_str = f"✦ {coins} coins"
        out += center_text(coin_str, 4, (220,190,60))

        # Class tabs
        actual_len = sum(len(c)+6 for c in classes)
        tab_x = max(0,(tw-actual_len)//2)
        out += at(tab_x, 5)
        tab_str=""
        for i,c in enumerate(classes):
            clv = save["class_levels"].get(c,1)
            if i==cls_idx:
                t=(math.sin(now*3)+1)/2
                tc=lerp(CLASS_DATA[c]["color"],(255,255,200),t*0.4)
                tab_str+=fg(*tc)+BOLD+f"[ {c.upper()} Lv{clv} ]"+RST
            else:
                tab_str+=fg(70,70,80)+f"  {c} Lv{clv}  "+RST
        out+=tab_str

        # Class info box
        box_w=60; bx=(tw-box_w)//2
        out+=box(bx,7,box_w,5,lerp(cd["color"],(30,30,40),0.6))
        out+=at(bx+2,8)+fg(*cd["color"])+BOLD+cls.upper()+RST
        out+=at(bx+2,9)+fg(150,150,150)+" | ".join(cd["desc"][:2][:box_w//2])+RST

        # Level bar
        bar_filled = min(lvl,10)
        bar = "█"*bar_filled+"░"*(10-bar_filled)
        lv_clr = lerp((100,200,100),(255,100,50),(lvl-1)/9)
        out+=at(bx+2,10)+fg(*lv_clr)+f"Level {lvl}/10  "+fg(150,150,80)+bar+RST

        # Existing stats
        cs = save.get("class_stats",{}).get(cls,{})
        stat_row=13
        out+=center_text("── Acquired Upgrades ──", stat_row, (120,120,80))
        if cs:
            stat_items=list(cs.items())
            for i,(stat,count) in enumerate(stat_items):
                dots="●"*count+"○"*(10-count) if count<=10 else "●"*10
                line=f"{stat:<22} {dots}  +{count}"
                out+=center_text(line, stat_row+1+i, (160,160,100))
        else:
            out+=center_text("No upgrades yet.", stat_row+1,(80,80,80))

        # Upgrade button
        btn_row=stat_row+max(1,len(cs))+3
        if lvl>=10:
            out+=center_text("✦ MAX LEVEL REACHED ✦", btn_row, (200,170,50))
        else:
            t=(math.sin(now*4)+1)/2
            btn_clr=lerp((100,200,100),(200,255,150),t) if coins>=cost else (80,60,60)
            out+=center_text(f"[ UPGRADE  —  {cost} coins ]  (SPACE)", btn_row, btn_clr, bold=True)

        # Message
        if now<msg_until:
            fade=min(1.0,(msg_until-now)/0.5)
            mc=lerp((20,20,30),(200,220,100),fade)
            out+=center_text(msg, btn_row+2, mc)

        out+=center_text("A/D: switch class   SPACE: upgrade   ESC: back", th-2,(70,70,90))
        write(out)
        time.sleep(0.033)


def menu_main(inp, save):
    """Main menu. Returns ('play', cls, boss, map_key, size_mult) or None."""
    options = ["Play","Store","Tips","Quit"]
    sel = 0
    particles = make_particles(40, *get_term_size())
    last = time.time()

    while True:
        now = time.time()
        dt = now-last; last=now
        tw,th = get_term_size()
        tick_particles(particles, dt, tw, th)

        inp.read()
        keys = inp.get_single()
        for k in keys:
            if k=='w': sel=(sel-1)%len(options)
            if k=='s': sel=(sel+1)%len(options)
            if k in (' ','\r','\n'):
                choice = options[sel]
                if choice=="Quit": return None
                if choice=="Tips":
                    menu_tips(inp); break
                if choice=="Store":
                    menu_store(inp,save); break
                if choice=="Play":
                    cls = menu_class_select(inp)
                    if cls is None: break
                    boss = menu_boss_select(inp)
                    if boss is None: break
                    map_key = menu_map_select(inp)
                    if map_key is None: break
                    size, size_coin_mult = menu_size_select(inp, map_key)
                    if size is None: break
                    return ('play', cls, boss, map_key, size, size_coin_mult)
            if k in ('\x03','\x1b'): return None

        out = CLR+HIDE
        out += draw_particles(particles, tw, th)

        # Big animated title
        out += animated_title(now, th//2-6)

        subtitle = "A real-time ASCII dungeon brawler"
        out += center_text(subtitle, th//2-4, (100,70,140))

        # Coin display
        coin_str = f"✦  {save['coins']} coins"
        out += center_text(coin_str, th//2-2, (200,170,50))

        # Menu items
        item_colors = [(160,80,220),(200,160,50),(60,180,140),(180,60,60)]
        for i,opt in enumerate(options):
            y = th//2 + i*2
            out += shimmer_bar(f"  {opt}  ", y,
                               item_colors[i], lerp(item_colors[i],(60,60,70),0.6),
                               i==sel)

        # Version tag
        out += at(tw-18, th-1)+fg(50,50,60)+"TillyMagic v2.0"+RST
        write(out)
        time.sleep(0.033)
