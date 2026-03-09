# !/usr/bin/env python3
"""TillyMagic - core constants, terminal helpers, input handler."""
import sys, os, time, math, random, subprocess, json
from collections import deque
try:
    import termios, tty, fcntl, select
except ImportError:
    print("Requires Unix/macOS terminal."); sys.exit(1)

# terminal size
def get_term_size():
    import shutil
    s = shutil.get_terminal_size((120, 35))
    return s.columns, s.lines

TERM_W, TERM_H = get_term_size()
BASE_MAP_W, BASE_MAP_H = 80, 22

# ansi
def fg(r,g,b):   return f"\033[38;2;{r};{g};{b}m"
def bg(r,g,b):   return f"\033[48;2;{r};{g};{b}m"
def at(x,y):     return f"\033[{y+1};{x+1}H"
def lerp(a,b,t): return tuple(int(a[i]+(b[i]-a[i])*max(0,min(1,t))) for i in range(3))
RST  = "\033[0m"
BOLD = "\033[1m"
HIDE = "\033[?25l"
SHOW = "\033[?25h"
CLR  = "\033[2J\033[H"

def play(path):
    try: subprocess.Popen(["afplay",path],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    except: pass

SND_HIT   = "/System/Library/Components/CoreAudio.component/Contents/SharedSupport/SystemSounds/system/head_gestures_partial_shake.caf"
SND_FINAL = "/System/Library/Components/CoreAudio.component/Contents/SharedSupport/SystemSounds/system/head_gestures_partial_nod.caf"
SND_ULT   = "/System/Library/PrivateFrameworks/ToneLibrary.framework/Versions/A/Resources/AlertTones/EncoreInfinitum/Welcome-EncoreInfinitum.caf"

# input
class Input:
    def __init__(self):
        self.fd = sys.stdin.fileno()
        self.old = termios.tcgetattr(self.fd)
        ns = termios.tcgetattr(self.fd)
        ns[3] &= ~(termios.ECHO|termios.ICANON)
        ns[6][termios.VMIN]=0; ns[6][termios.VTIME]=0
        termios.tcsetattr(self.fd, termios.TCSANOW, ns)
        self._buf = deque()
        self._held = {}   # key -> last seen time

    def read(self):
        try:
            r,_,_ = select.select([self.fd],[],[],0)
            if not r: return
            data = os.read(self.fd, 64)
            i = 0
            while i < len(data):
                b = data[i]
                # esc sequence: read ahead for [ + letter
                if b == 0x1b and i+2 < len(data) and data[i+1] == ord('['):
                    code = chr(data[i+2])
                    seq = {'A':'UP','B':'DOWN','C':'RIGHT','D':'LEFT'}.get(code)
                    if seq:
                        self._buf.append(seq)
                        i += 3
                        continue
                    else:
                        # unknown esc seq, emit raw esc
                        self._buf.append('\x1b')
                        i += 1
                        continue
                elif b == 0x1b:
                    # lone esc with nothing following - real escape key
                    self._buf.append('\x1b')
                    i += 1
                    continue
                c = chr(b)
                self._buf.append(c)
                if c in 'wasd': self._held[c] = time.time()
                i += 1
        except: pass

    def get(self):
        pressed = list(self._buf); self._buf.clear()
        now = time.time()
        self._held = {k:t for k,t in self._held.items() if now-t<0.06}
        out = list(pressed)
        for k in self._held:
            if k not in out: out.append(k)
        return out

    def get_single(self):
        # returns only freshly pressed keys - no held repeats. for menus.
        self._held.clear()
        pressed = list(self._buf); self._buf.clear()
        return pressed

    def restore(self):
        termios.tcsetattr(self.fd, termios.TCSADRAIN, self.old)

# save/load
SAVE_PATH = os.path.expanduser("~/.tillymagic_save.json")

def load_save():
    default = {
        "coins": 0,
        "class_levels": {"wizard":1,"gravedigger":1,"marionette":1,"cartographer":1,"revenant":1,"siphon":1},
        "class_stats": {}   # class -> {stat: bonus}
    }
    try:
        with open(SAVE_PATH) as f: d = json.load(f)
        for k,v in default.items():
            if k not in d: d[k]=v
        return d
    except: return default

def write_save(d):
    try:
        with open(SAVE_PATH,'w') as f: json.dump(d,f)
    except: pass

# class definitions
CLASS_DATA = {
    "wizard": {
        "color": (160,80,220),
        "hp": 100, "speed": 20.0, "dash_dist": 4,
        "move_names": {1:"Scepter",2:"Arcane Snap",3:"Gravemark",4:"Blink Scatter",5:"Wizard's Downfall"},
        "move_cds":   {1:0.35, 2:14.0, 3:26.0, 4:12.0, 5:60.0},
        "desc": ["A mobile arcane caster.",
                 "Combo projectiles, AOE stuns,",
                 "gravity traps and teleport bursts.",
                 "Ultimate: Whirlpool that pulls and shreds."],
    },
    "gravedigger": {
        "color": (140,100,50),
        "hp": 120, "speed": 15.0, "dash_dist": 4,
        "move_names": {1:"Shovel",2:"Dig",3:"Bury",4:"Exhume",5:"Six Feet Under"},
        "move_cds":   {1:0.5, 2:8.0, 3:18.0, 4:14.0, 5:60.0},
        "desc": ["A slow, methodical arena controller.",
                 "Lay mines, bury the boss, recall explosions.",
                 "Ultimate: Cracks the earth open beneath them."],
    },
    "marionette": {
        "color": (200,60,120),
        "hp": 90, "speed": 18.0, "dash_dist": 4,
        "move_names": {1:"Silk Strike",2:"Plant String",3:"Puppet Pull",4:"Redirect",5:"Cut All Strings"},
        "move_cds":   {1:0.4, 2:9.0, 3:16.0, 4:11.0, 5:60.0},
        "desc": ["A puppeteer who weaponizes the boss.",
                 "Plant strings to reflect damage,",
                 "control boss movement, summon puppets.",
                 "Ultimate: Cut all strings in a massive burst."],
    },
    "cartographer": {
        "color": (60,180,140),
        "hp": 100, "speed": 22.0, "dash_dist": 5,
        "move_names": {1:"Ink Stab",2:"Flare",3:"Quicksand",4:"Terrain Wall",5:"Map Ignition"},
        "move_cds":   {1:0.35, 2:11.0, 3:16.0, 4:20.0, 5:60.0},
        "desc": ["A scholar who maps and traps the arena.",
                 "Charted tiles deal passive damage.",
                 "Blind, slow, and wall off the boss.",
                 "Ultimate: Every charted tile ignites at once."],
    },
    "revenant": {
        "color": (200,30,30),
        "hp": 60, "speed": 17.0, "dash_dist": 4,
        "move_names": {1:"Death Blow",2:"Rage Strike",3:"Bone Shield",4:"Self-Destruct",5:"Berserk"},
        "move_cds":   {1:0.45, 2:0.38, 3:14.0, 4:20.0, 5:60.0},
        "desc": ["5 lives, 60 HP each. Gets stronger each death.",
                 "Rage builds damage with every respawn.",
                 "Final life unlocks burning movement trails.",
                 "Ultimate: Voluntary self-destruct for huge damage."],
    },
    "siphon": {
        "color": (80,200,180),
        "hp": 95, "speed": 19.0, "dash_dist": 5,
        # hijack: 3s cd. window opens, reflects next boss attack. no personal combo.
        # overload: detonate all stored charges for burst damage.
        # null field: zone that blocks boss buffs/speed boosts for 8s.
        # leech: steal boss current speed/armor buff and apply to self.
        # ult: siphon everything, emit all at once in a ring explosion.
        "move_names": {1:"Hijack",2:"Overload",3:"Null Field",4:"Leech",5:"Void Surge"},
        "move_cds":   {1:3.0, 2:12.0, 3:16.0, 4:10.0, 5:60.0},
        "desc": ["A void mage who steals and reflects boss energy.",
                 "Hijack opens a 1.5s window: reflects the next attack.",
                 "Stores up to 3 charges. Overload detonates them all.",
                 "Ultimate: Void Surge - unleash a ring of all stolen power."],
    },
}

# boss definitions
BOSS_DATA = {
    "boss1": {
        "name": "The Warden",
        "hp": 300, "damage": 15, "hit_cd": 2.0, "move_interval": 0.6,
        "hit_range": 3, "coins": 50,
        "color": (200,80,80),
        "desc": ["A relentless brute that tracks you down.",
                 "Telegraphs attacks with a red hash warning.",
                 "2 second windup then a 0.5s plummet."],
    },
    "boss2": {
        "name": "The Stonewarden",
        "hp": 300, "damage": 25, "hit_cd": 1.8, "move_interval": 0.8,
        "hit_range": 4, "coins": 80,
        "color": (160,140,100),
        "desc": ["A golem with a stone shell (150 dmg to crack).",
                 "Phase 2: fast charges that leave rubble walls.",
                 "Stone pillars periodically erupt from the floor."],
    },
    "boss3": {
        "name": "The Tide Caller",
        "hp": 450, "damage": 20, "hit_cd": 1.0, "move_interval": 0.4,
        "hit_range": 6, "coins": 150,
        "color": (60,120,220),
        "desc": ["Floods the map with slowing water pools.",
                 "Fires long water jets in cardinal directions.",
                 "Submerges briefly to reposition — untargetable."],
    },
    "boss4": {
        "name": "The Hollow Conductor",
        "hp": 600, "damage": 30, "hit_cd": 1.5, "move_interval": 0.3,
        "hit_range": 7, "coins": 300,
        "color": (180,180,80),
        "desc": ["Attacks follow a visible rhythm beat bar.",
                 "Summons violin, drum, and horn turrets.",
                 "Crescendo phase: all turrets fire simultaneously."],
    },
    "boss5": {
        "name": "The Pale Architect",
        "hp": 450, "damage": 22, "hit_cd": 2.2, "move_interval": 0.8,
        "hit_range": 5, "coins": 300,
        "color": (200,210,230),
        "desc": ["Reshapes the arena every 12s with new wall segments.",
                 "Phases through its own walls. You cannot.",
                 "Schematic projectile builds a cage around you on landing.",
                 "Phase 2: walls rotate, rubble tiles slow movement."],
    },
    "boss6": {
        "name": "The Sovereign Hound",
        "hp": 550, "damage": 28, "hit_cd": 1.6, "move_interval": 0.35,
        "hit_range": 4, "coins": 400,
        "color": (80,50,120),
        "desc": ["Cycles Hunt (15s fast charges) and Rest (8s calm) phases.",
                 "Rest: howls to summon shadow puppies. Ignore them.",
                 "Telegraphs Pounce for 2s. Miss = 1.5s stun window.",
                 "Immune to knockback. Cannot be repositioned."],
    },
    "boss7": {
        "name": "The Liminal",
        "hp": 700, "damage": 35, "hit_cd": 1.2, "move_interval": 0.25,
        "hit_range": 8, "coins": 500,
        "color": (200,100,255),
        "desc": ["Two halves: light (left) and void (right). Damage one heals the other.",
                 "Focus one half to make progress, then swap before recovery.",
                 "Convergence beams from both sides meet in the middle.",
                 "Below 40% HP: attempts a full Merge heal. Interrupt with 80 dmg."],
    },
}

# map definitions
MAP_DATA = {
    "standard": {
        "name": "Standard Arena",
        "coin_mult": 1.0,
        "color": (100,100,120),
        "procedural": True,
        "desc": ["A plain open arena. No hazards.",
                 "Full space to move and fight.",
                 "1.0x coin multiplier."],
    },
    "ossuary": {
        "name": "The Ossuary",
        "coin_mult": 1.2,
        "color": (180,160,100),
        "procedural": True,
        "desc": ["A bone-lined crypt with 4 corner pillars.",
                 "Skulls and ribcage patterns on the walls.",
                 "Pillars reduce your safe movement area.",
                 "1.2x coin multiplier."],
    },
    "forge": {
        "name": "The Molten Forge",
        "coin_mult": 1.6,
        "color": (220,100,30),
        "procedural": True,
        "desc": ["Two lava channels divide the map into 3 lanes.",
                 "Crossing lava requires dash or blink.",
                 "Corner furnaces blast periodic fire columns.",
                 "1.6x coin multiplier."],
    },
    "mirror": {
        "name": "The Mirror Vault",
        "coin_mult": 2.5,
        "color": (200,220,255),
        "procedural": False,
        "desc": ["High-contrast silver and white arena.",
                 "Boss has a mirrored clone on the far side.",
                 "Clone reforms 5s after being shattered.",
                 "2.5x coin multiplier. PROCEDURAL DISABLED."],
    },
    "clocktower": {
        "name": "The Shattered Clock",
        "coin_mult": 1.8,
        "color": (180,160,100),
        "procedural": True,
        "desc": ["Gear segments embedded in the floor block movement.",
                 "A Clock Hand sweeps the full map every 20s (40 dmg).",
                 "3s arc warning appears before each sweep.",
                 "1.8x coin multiplier."],
    },
    "reliquary": {
        "name": "The Sunken Reliquary",
        "coin_mult": 2.2,
        "color": (60,100,180),
        "procedural": True,
        "desc": ["Water rises every 45s. Full flood at 2:15.",
                 "Water slows you 30%. Deep water makes you silent.",
                 "6 chests scattered around. Boss can smash them too.",
                 "2.2x coin multiplier."],
    },
    "spire": {
        "name": "The Inverted Spire",
        "coin_mult": 3.0,
        "color": (120,60,200),
        "procedural": True,
        "desc": ["Arena wraps: exit left, appear on right. Same for top/bottom.",
                 "Boss also wraps. Shortest path can cut through the seam.",
                 "Spire Spikes erupt every 12s from random tiles (50 dmg).",
                 "3.0x coin multiplier. Highest risk, highest reward."],
    },
}

# upgrade system
UPGRADE_STATS = ["strength","cooldown_reduction","speed","dash_range","absorbency","hit_range"]
UPGRADE_DESCS = {
    "strength":           "+10% damage on all attacks",
    "cooldown_reduction": "-8% cooldown on all moves",
    "speed":              "+2 movement speed",
    "dash_range":         "+1 dash distance",
    "absorbency":         "+5% damage absorbed (shield)",
    "hit_range":          "+0.5 melee/ranged reach",
}

def upgrade_cost(current_level):
    return int(30 * (current_level ** 1.4))

def apply_upgrades(cls_name, save, base):
    """Apply saved upgrade stats to a base stats dict. Modifies in place."""
    stats = save.get("class_stats", {}).get(cls_name, {})
    for stat, count in stats.items():
        if stat == "strength":          base["dmg_mult"]    = base.get("dmg_mult",1.0) * (1.1**count)
        elif stat == "cooldown_reduction": base["cd_mult"]  = base.get("cd_mult",1.0)  * (0.92**count)
        elif stat == "speed":           base["speed"]       = base.get("speed",15.0)   + 2*count
        elif stat == "dash_range":      base["dash_dist"]   = base.get("dash_dist",4)  + count
        elif stat == "absorbency":      base["absorb"]      = base.get("absorb",0.0)   + 0.05*count
        elif stat == "hit_range":       base["hit_range_bonus"] = base.get("hit_range_bonus",0.0) + 0.5*count
    return base
