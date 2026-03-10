"""TillyMagic gameplay engine."""
from tm_core import *

# game objects
class Particle:
    def __init__(self,x,y,vx,vy,ch,clr,lt):
        self.x=float(x);self.y=float(y);self.vx=vx;self.vy=vy
        self.ch=ch;self.clr=clr;self.lt=lt;self.born=time.time()
    def alive(self): return (time.time()-self.born)<self.lt
    def update(self,dt): self.x+=self.vx*dt; self.y+=self.vy*dt

class Projectile:
    def __init__(self,x,y,tx,ty,speed,ch,clr,dmg,owner):
        self.x=float(x);self.y=float(y)
        d=math.hypot(tx-x,ty-y) or 1
        self.vx=(tx-x)/d*speed; self.vy=(ty-y)/d*speed
        self.ch=ch;self.clr=clr;self.dmg=dmg;self.owner=owner
        self.trail=deque(maxlen=5)
    def update(self,dt):
        self.trail.append((int(self.x),int(self.y)))
        self.x+=self.vx*dt; self.y+=self.vy*dt

class Ripple:
    def __init__(self,cx,cy,max_r,dur,c1,c2):
        self.cx=cx;self.cy=cy;self.max_r=max_r;self.dur=dur
        self.c1=c1;self.c2=c2;self.born=time.time()
    def alive(self): return (time.time()-self.born)<self.dur
    def prog(self): return min(1.0,(time.time()-self.born)/self.dur)

class Afterimage:
    def __init__(self,x,y):
        self.x=x;self.y=y;self.born=time.time()
        self.lt=2.0;self.exploded=False;self.grace=0.5
    def alive(self): return (time.time()-self.born)<self.lt
    def should_explode(self): return not self.exploded and (time.time()-self.born)>=self.grace

class GraveMark:
    def __init__(self,x,y):
        self.x=x;self.y=y;self.born=time.time()
        self.grace=1.0;self.pulled=False;self.lt=3.0
    def alive(self): return (time.time()-self.born)<self.lt
    def should_pull(self): return not self.pulled and (time.time()-self.born)>=self.grace

class Landmine:
    def __init__(self,x,y):
        self.x=x;self.y=y;self.born=time.time()
        self.triggered=False;self.trigger_t=None;self.exploded=False;self.lt=30.0
    def alive(self): return not self.exploded and (time.time()-self.born)<self.lt
    def trigger(self):
        if not self.triggered: self.triggered=True; self.trigger_t=time.time()
    def should_explode(self): return self.triggered and not self.exploded and (time.time()-self.trigger_t)>=0.4

class FissureRing:
    def __init__(self,cx,cy,max_r):
        self.cx=cx;self.cy=cy;self.max_r=max_r;self.born=time.time()
        self.dur=1.8;self.hit_boss=False
    def alive(self): return (time.time()-self.born)<self.dur
    def prog(self): return min(1.0,(time.time()-self.born)/self.dur)

class BossString:  # marionette
    def __init__(self): self.born=time.time(); self.lt=8.0
    def alive(self): return (time.time()-self.born)<self.lt

class CharTile:    # cartographer
    def __init__(self,x,y): self.x=x;self.y=y; self.born=time.time()

# boss
class Boss:
    def __init__(self, key, bx, by):
        bd = BOSS_DATA[key]
        self.key = key
        self.x = float(bx); self.y = float(by)
        self.hp = bd["hp"]; self.max_hp = bd["hp"]
        self.damage = bd["damage"]
        self.hit_cd = bd["hit_cd"]
        self.move_interval = bd["move_interval"]
        self.hit_range = bd["hit_range"]
        self.color = bd["color"]
        self.stun_until = 0; self.flash_until = 0
        self.last_move = time.time(); self.last_hit = 0
        self.hit_windup = None; self.hit_target = None; self.hit_landing = None
        self.alive = True
        # boss2 state
        self.armor = 150 if key=="boss2" else 0
        self.phase2 = False
        self.charge_target = None; self.charge_start = None
        # boss3 state
        self.submerged_until = 0
        self.current_offset = (0,0)  # map drift
        # boss4 beat and rhythm state.
        # beat_interval shrinks as hp falls, creating a crescendo effect.
        # base interval is 2.0s. at 0 hp it would reach 0.6s.
        self.beat_interval = 2.0; self.last_beat = time.time()
        self.beat_phase = 0.0
        # beat_locked controls whether a hit windup can only start on a beat boundary.
        self.beat_pending_hit = False  # set true on a beat, cleared when windup begins
        # turrets list: each entry is [x, y, kind, hp, last_fire_time]
        self.turrets = []
        self.turrets_spawned = False
        # trill state. a trill is a rapid multi-hit move where the boss closes in,
        # vibrates in place dealing small repeated hits, then pulls back for a big final strike.
        # only triggers when boss hp is below 50% and a random chance fires on a beat.
        self.trill_active = False
        self.trill_phase = None   # 'advance', 'vibrate', 'retreat', 'slam'
        self.trill_start = 0.0
        self.trill_origin = (0.0, 0.0)   # where the boss started the trill from
        self.trill_target = (0.0, 0.0)   # player position locked at trill start
        self.trill_hit_count = 0         # how many vibrate ticks have landed
        self.trill_last_tick = 0.0       # last vibrate damage tick time
        self.trill_advance_dur = 0.6     # seconds to close the distance
        self.trill_vibrate_dur = 1.8     # seconds of rapid buzzing hits
        self.trill_retreat_dur = 0.5     # seconds to pull back
        self.trill_slam_dur   = 0.4      # final lunging slam
        # attack animation
        self.atk_anim = None  # 'slam','stomp','thrust','baton' etc
        self.atk_anim_start = 0
        # boss3 water jets
        self.water_jets = []
        self.last_jet = 0

        # boss5 pale architect state.
        # architect_walls: list of [(x,y)] wall segments it has raised.
        # last_wall_raise: timestamp of last wall raise.
        # cage_trap: (cx,cy,born) or None - schematic cage building at a point.
        self.architect_walls = []
        self.last_wall_raise = time.time()
        self.cage_trap = None

        # boss6 sovereign hound state.
        # hunt_until: timestamp when hunt phase ends.
        # rest_until: timestamp when rest phase ends.
        # pounce: dict with state or None.
        # puppies: list of (x, y, hp) shadow pups spawned during rest.
        self.hunt_until = time.time() + 15.0
        self.rest_until = 0.0
        self.hound_pounce = None  # {'start','origin','target','landed'}
        self.hound_puppies = []

        # boss7 liminal state.
        # light_hp and void_hp are the two independent halves.
        # merge_active: True during the 5s merge animation.
        # convergence_beams: list of active beam attacks.
        self.light_hp = 350 if key=="boss7" else 0
        self.void_hp  = 350 if key=="boss7" else 0
        self.merge_active = False
        self.merge_start = 0.0
        self.merge_interrupt_dmg = 0
        self.convergence_beams = []  # [(x1,y1,x2,y2,born,dur)]
        self.last_convergence = 0.0

    def is_stunned(self): return time.time()<self.stun_until
    def stun(self,d): self.stun_until=max(self.stun_until,time.time()+d)
    def is_submerged(self): return time.time()<self.submerged_until

    def get_cells(self):
        """Returns (x, y, char) tuples for the boss body based on its unique shape."""
        cx,cy=int(self.x),int(self.y)
        cells=[]
        if self.key=="boss1":
            # the warden: a hulking 5x3 humanoid torso
            # head
            cells+=[(cx,cy-2,'O'),(cx-1,cy-2,'('),(cx+1,cy-2,')')]
            # shoulders/arms
            cells+=[(cx-3,cy-1,'/'),(cx-2,cy-1,'['),(cx-1,cy-1,'|'),(cx,cy-1,'|'),(cx+1,cy-1,'|'),(cx+2,cy-1,']'),(cx+3,cy-1,'\\')]
            # chest
            cells+=[(cx-2,cy,'{'),(cx-1,cy,'#'),(cx,cy,'@'),(cx+1,cy,'#'),(cx+2,cy,'}')]
            # legs
            cells+=[(cx-1,cy+1,'|'),(cx,cy+1,'|'),(cx+1,cy+1,'|')]
            cells+=[(cx-2,cy+2,'/'),(cx-1,cy+2,'|'),(cx+1,cy+2,'|'),(cx+2,cy+2,'\\')]
        elif self.key=="boss2":
            # the stonewarden: a wide rocky golem, 9x5 boxy frame
            # top edge
            for dx in range(-4,5): cells+=[(cx+dx,cy-2,'#')]
            # middle rows with armour plates
            for dy in [-1,0,1]:
                cells+=[(cx-4,cy+dy,'|'),(cx+4,cy+dy,'|')]
                for dx in [-3,-2,-1,0,1,2,3]:
                    ch = {'boss2_armor': '▓'}.get('x','▓') if self.armor>0 else '░'
                    cells+=[(cx+dx,cy+dy,ch)]
            # bottom edge
            for dx in range(-4,5): cells+=[(cx+dx,cy+2,'#')]
            # corner bolts
            cells+=[(cx-4,cy-2,'╔'),(cx+4,cy-2,'╗'),(cx-4,cy+2,'╚'),(cx+4,cy+2,'╝')]
        elif self.key=="boss3":
            # the tide caller: a flowing aquatic form, 7x5 wavy
            cells+=[(cx,cy-3,'V'),(cx-1,cy-3,'~'),(cx+1,cy-3,'~')]
            cells+=[(cx-3,cy-2,'~'),(cx-2,cy-2,')'),(cx-1,cy-2,'O'),(cx,cy-2,'|'),(cx+1,cy-2,'O'),(cx+2,cy-2,'('),(cx+3,cy-2,'~')]
            cells+=[(cx-4,cy-1,'~'),(cx-3,cy-1,'{'),(cx-2,cy-1,'~'),(cx,cy-1,'#'),(cx+2,cy-1,'~'),(cx+3,cy-1,'}'),(cx+4,cy-1,'~')]
            cells+=[(cx-4,cy,'≈'),(cx-3,cy,'~'),(cx-1,cy,'('),(cx,cy,'@'),(cx+1,cy,')'),(cx+3,cy,'~'),(cx+4,cy,'≈')]
            cells+=[(cx-3,cy+1,'~'),(cx-2,cy+1,'}'),(cx-1,cy+1,'~'),(cx+1,cy+1,'~'),(cx+2,cy+1,'{'),(cx+3,cy+1,'~')]
            cells+=[(cx-2,cy+2,'~'),(cx-1,cy+2,'v'),(cx,cy+2,'~'),(cx+1,cy+2,'v'),(cx+2,cy+2,'~')]
            cells+=[(cx-1,cy+3,'~'),(cx,cy+3,'v'),(cx+1,cy+3,'~')]
        elif self.key=="boss4":
            # the hollow conductor: skeletal figure with baton, 7x7
            # skull
            cells+=[(cx-1,cy-4,'('),(cx,cy-4,'Ω'),(cx+1,cy-4,')')]
            # cape/robe upper
            cells+=[(cx-2,cy-3,'/'),(cx-1,cy-3,'▓'),(cx,cy-3,'|'),(cx+1,cy-3,'▓'),(cx+2,cy-3,'\\')]
            # baton arm extended right
            cells+=[(cx+3,cy-3,'─'),(cx+4,cy-3,'─'),(cx+5,cy-3,'♪')]
            # torso
            cells+=[(cx-3,cy-2,'('),(cx-2,cy-2,'█'),(cx-1,cy-2,'║'),(cx,cy-2,'♦'),(cx+1,cy-2,'║'),(cx+2,cy-2,'█'),(cx+3,cy-2,')')]
            cells+=[(cx-3,cy-1,'|'),(cx-2,cy-1,'▓'),(cx-1,cy-1,'░'),(cx,cy-1,'|'),(cx+1,cy-1,'░'),(cx+2,cy-1,'▓'),(cx+3,cy-1,'|')]
            cells+=[(cx-2,cy,'('),(cx-1,cy,'█'),(cx,cy,'@'),(cx+1,cy,'█'),(cx+2,cy,')')]
            # robes
            cells+=[(cx-3,cy+1,'/'),(cx-2,cy+1,'▓'),(cx-1,cy+1,'░'),(cx,cy+1,'▒'),(cx+1,cy+1,'░'),(cx+2,cy+1,'▓'),(cx+3,cy+1,'\\')]
            cells+=[(cx-4,cy+2,'/'),(cx-3,cy+2,'▓'),(cx-2,cy+2,'░'),(cx-1,cy+2,'▒'),(cx,cy+2,'░'),(cx+1,cy+2,'▒'),(cx+2,cy+2,'░'),(cx+3,cy+2,'▓'),(cx+4,cy+2,'\\')]
            cells+=[(cx-4,cy+3,'|'),(cx-3,cy+3,'░'),(cx,cy+3,'▓'),(cx+3,cy+3,'░'),(cx+4,cy+3,'|')]
        elif self.key=="boss5":
            # the pale architect: a tall robed figure holding a t-square ruler.
            # crown of drafting-pin shapes, long coat, extending ruler arm.
            cells+=[(cx,cy-4,'A'),(cx-1,cy-4,'/'),(cx+1,cy-4,chr(92))]
            cells+=[(cx-1,cy-3,'|'),(cx,cy-3,'T'),(cx+1,cy-3,'|')]
            cells+=[(cx-2,cy-2,'('),(cx-1,cy-2,'█'),(cx,cy-2,'◈'),(cx+1,cy-2,'█'),(cx+2,cy-2,')')]
            cells+=[(cx-3,cy-1,'/'),(cx-2,cy-1,'▓'),(cx-1,cy-1,'|'),(cx,cy-1,'|'),(cx+1,cy-1,'▓'),(cx+2,cy-1,'|'),(cx+3,cy-1,'─'),(cx+4,cy-1,'─'),(cx+5,cy-1,'⊤')]
            cells+=[(cx-3,cy,'|'),(cx-2,cy,'░'),(cx-1,cy,'░'),(cx,cy,'@'),(cx+1,cy,'░'),(cx+2,cy,'░'),(cx+3,cy,'|')]
            cells+=[(cx-2,cy+1,'▓'),(cx-1,cy+1,'|'),(cx,cy+1,'|'),(cx+1,cy+1,'▓')]
            cells+=[(cx-3,cy+2,'/'),(cx-2,cy+2,'░'),(cx-1,cy+2,'|'),(cx,cy+2,'|'),(cx+1,cy+2,'░'),(cx+2,cy+2,chr(92))]
        elif self.key=="boss6":
            # the sovereign hound: wide four-legged beast, low to ground.
            # broad head with ears, muscular body, four splayed legs.
            cells+=[(cx-2,cy-3,'/'),(cx-1,cy-3,'▲'),(cx,cy-3,'W'),(cx+1,cy-3,'▲'),(cx+2,cy-3,chr(92))]
            cells+=[(cx-3,cy-2,'('),(cx-2,cy-2,'█'),(cx-1,cy-2,'O'),(cx,cy-2,'@'),(cx+1,cy-2,'O'),(cx+2,cy-2,'█'),(cx+3,cy-2,')')]
            cells+=[(cx-4,cy-1,'|'),(cx-3,cy-1,'▓'),(cx-2,cy-1,'█'),(cx-1,cy-1,'▓'),(cx,cy-1,'▓'),(cx+1,cy-1,'▓'),(cx+2,cy-1,'█'),(cx+3,cy-1,'▓'),(cx+4,cy-1,'|')]
            cells+=[(cx-5,cy,'/'),(cx-4,cy,'▓'),(cx-3,cy,'█'),(cx-2,cy,'▓'),(cx-1,cy,'▓'),(cx,cy,'▓'),(cx+1,cy,'▓'),(cx+2,cy,'█'),(cx+3,cy,'▓'),(cx+4,cy,chr(92))]
            cells+=[(cx-4,cy+1,'|'),(cx-2,cy+1,'|'),(cx,cy+1,'▓'),(cx+2,cy+1,'|'),(cx+4,cy+1,'|')]
            cells+=[(cx-4,cy+2,'/'),(cx-3,cy+2,chr(92)),(cx-2,cy+2,'/'),(cx-1,cy+2,chr(92)),(cx+1,cy+2,'/'),(cx+2,cy+2,chr(92)),(cx+3,cy+2,'/'),(cx+4,cy+2,chr(92))]
        elif self.key=="boss7":
            # the liminal: two fused humanoid halves, one bright one dark.
            # left half is light (/ chars, bright), right is void (\ chars, dark).
            # center seam where they join is shown as a bright crackling line.
            cells+=[(cx-2,cy-4,'('),(cx-1,cy-4,'O'),(cx,cy-4,'|'),(cx+1,cy-4,'O'),(cx+2,cy-4,')')]
            cells+=[(cx-3,cy-3,'/'),(cx-2,cy-3,'▓'),(cx-1,cy-3,'|'),(cx,cy-3,'╫'),(cx+1,cy-3,'█'),(cx+2,cy-3,'▓'),(cx+3,cy-3,chr(92))]
            cells+=[(cx-4,cy-2,'/'),(cx-3,cy-2,'▒'),(cx-2,cy-2,'░'),(cx-1,cy-2,'|'),(cx,cy-2,'╪'),(cx+1,cy-2,'█'),(cx+2,cy-2,'▓'),(cx+3,cy-2,'█'),(cx+4,cy-2,chr(92))]
            cells+=[(cx-4,cy-1,'/'),(cx-3,cy-1,'░'),(cx-2,cy-1,'▒'),(cx-1,cy-1,'░'),(cx,cy-1,'║'),(cx+1,cy-1,'▓'),(cx+2,cy-1,'█'),(cx+3,cy-1,'▓'),(cx+4,cy-1,chr(92))]
            cells+=[(cx-3,cy,'/'),(cx-2,cy,'▒'),(cx-1,cy,'░'),(cx,cy,'@'),(cx+1,cy,'█'),(cx+2,cy,'▓'),(cx+3,cy,chr(92))]
            cells+=[(cx-3,cy+1,'/'),(cx-2,cy+1,'░'),(cx-1,cy+1,'▒'),(cx,cy+1,'╫'),(cx+1,cy+1,'▓'),(cx+2,cy+1,'█'),(cx+3,cy+1,chr(92))]
            cells+=[(cx-2,cy+2,'/'),(cx-1,cy+2,'|'),(cx,cy+2,'|'),(cx+1,cy+2,'|'),(cx+2,cy+2,chr(92))]
        return cells

    def get_body_set(self):
        """Fast set of (x,y) occupied by this boss's body for collision."""
        return {(x,y) for x,y,_ in self.get_cells()}

    def body_dist(self, px, py):
        """Min distance from point (px,py) to any body cell."""
        bset = self.get_body_set()
        if not bset: return math.hypot(self.x-px, self.y-py)
        return min(math.hypot(x-px, y-py) for x,y in bset)

# map geometry
class MapGeometry:
    def __init__(self, key, w, h):
        self.key = key
        self.w = w; self.h = h
        self.pillars = []   # [(cx,cy,r)]  — circular blocked zones
        self.lava = []      # [(y, x1, x2)]  — horizontal lava strips
        self.walls = []     # set of (x,y)
        self.furnace_cols = []  # x positions
        self.furnace_fire = {}  # x -> fire_until
        self._build()

    def _build(self):
        w,h=self.w,self.h
        random.seed(42)  # deterministic layout
        if self.key=="ossuary":
            # corner bone pillars
            pad=5
            for cx,cy in [(pad,pad),(w-pad,pad),(pad,h-pad),(w-pad,h-pad)]:
                self.pillars.append((cx,cy,2))
            # scattered mid pillars (2 extra)
            for cx,cy in [(w//3, h//3),(w*2//3, h*2//3)]:
                self.pillars.append((cx,cy,1))
            # sarcophagi scatter: collidable single cells
            for _ in range(8):
                sx=random.randint(8,w-9); sy=random.randint(4,h-5)
                blocked=any(math.hypot(sx-cx,sy-cy)<=r+3 for cx,cy,r in self.pillars)
                if not blocked:
                    self.walls.append((sx,sy,'▓',(100,80,50)))
                    self.walls.append((sx+1,sy,'▓',(100,80,50)))
        elif self.key=="forge":
            h1=h//3; h2=(h*2)//3
            for y in [h1,h2]:
                self.lava.append((y, 2, w-3))
            for x in [2,w-3]:
                self.furnace_cols.append(x)
            # anvil/crate obstacles in each lane
            for lane_y in [h//6, h//2, h*5//6]:
                for ox in [w//4, w//2, w*3//4]:
                    if not self.is_lava(ox, lane_y):
                        self.walls.append((ox,lane_y,'▓',(120,80,30)))
            # cooling vats (collidable 2-wide)
            for vx,vy in [(w//5, h//2),(w*4//5, h//2)]:
                if not self.is_lava(vx, vy):
                    self.walls.append((vx,vy,'O',(80,60,30)))
                    self.walls.append((vx+1,vy,'O',(80,60,30)))
        elif self.key=="standard":
            # scattered broken pillars for cover
            for pos in [(w//4,h//3),(w*3//4,h//3),(w//4,h*2//3),(w*3//4,h*2//3),(w//2,h//2)]:
                self.pillars.append((pos[0],pos[1],1))
        elif self.key=="mirror":
            # crystal pillars in each quadrant
            for cx,cy in [(w//4,h//3),(w*3//4,h//3),(w//4,h*2//3),(w*3//4,h*2//3)]:
                self.pillars.append((cx,cy,1))

        elif self.key=="clocktower":
            # large gear segments scattered across the floor as collidable terrain.
            # gears are elliptical: wider horizontally due to char aspect ratio.
            random.seed(77)
            gear_centers = [(w//4, h//3),(w*3//4, h//3),(w//2, h//2),
                            (w//4, h*2//3),(w*3//4, h*2//3)]
            for gx, gy in gear_centers:
                # gear rim: ring of # chars
                for ang in range(0, 360, 15):
                    rx = gx + round(3 * math.cos(math.radians(ang)) * 2)
                    ry = gy + round(3 * math.sin(math.radians(ang)) * 0.9)
                    if 2 <= rx < w-2 and 2 <= ry < h-2:
                        self.walls.append((rx, ry, '#', (140, 120, 60)))
                # gear teeth at cardinal points
                for ang in range(0, 360, 45):
                    tx = gx + round(4 * math.cos(math.radians(ang)) * 2)
                    ty = gy + round(4 * math.sin(math.radians(ang)) * 0.9)
                    if 2 <= tx < w-2 and 2 <= ty < h-2:
                        self.walls.append((tx, ty, '+', (160, 140, 70)))
            # clock hand sweep: stored as metadata, handled in update
            self.clock_last_sweep = 0.0
            self.clock_sweep_active = False
            self.clock_sweep_start = 0.0

        elif self.key=="reliquary":
            # 6 sealed chests scattered around the map
            random.seed(33)
            self.chests = []  # [(x,y,open,effect)]
            positions = [(w//5,h//4),(w*2//5,h*3//4),(w*3//4,h//4),
                         (w//6,h//2),(w*5//6,h//2),(w//2,h*3//4)]
            for cx,cy in positions:
                self.chests.append([cx, cy, False, None])
            # water level: rises in stages (0=dry, 1=partial, 2=full)
            self.water_level = 0
            self.water_last_rise = 0.0  # set at game start

        elif self.key=="spire":
            # no walls: arena wraps at all edges.
            # spire spike sites are random, refreshed every 12s in update.
            self.spike_sites = []     # [(x,y,born)] pending spikes
            self.spike_last = 0.0
        random.seed()

    def is_blocked(self,x,y):
        for (cx,cy,r) in self.pillars:
            if math.hypot(x-cx,y-cy)<=r: return True
        for (ly,x1,x2) in self.lava:
            if y==ly and x1<=x<=x2: return True
        for wall in self.walls:
            if wall[0]==x and wall[1]==y: return True
        # architect walls from boss5 are stored on the boss object at runtime;
        # checked separately in process_input via the boss-aware path, so no
        # reference to g here. instead the movement code checks architect_walls directly.
        return False

    def is_lava(self,x,y):
        for (ly,x1,x2) in self.lava:
            if y==ly and x1<=x<=x2: return True
        return False

# game state
class Game:
    def __init__(self, cls_name, boss_key, map_key, size_mult, size_coin_mult, save):
        self.cls_name = cls_name
        self.boss_key = boss_key
        self.map_key = map_key
        self.size_mult = size_mult

        # map dimensions
        self.mw = max(40, int(BASE_MAP_W * size_mult))
        self.mh = max(18, int(BASE_MAP_H * size_mult))
        # clamp to terminal
        tw,th = get_term_size()
        self.mw = min(self.mw, tw-2)
        self.mh = min(self.mh, th-6)

        self.geo = MapGeometry(map_key, self.mw, self.mh)

        cd = CLASS_DATA[cls_name]
        base = {"hp": cd["hp"], "speed": cd["speed"], "dash_dist": cd["dash_dist"],
                "dmg_mult":1.0, "cd_mult":1.0, "absorb":0.0, "hit_range_bonus":0.0}
        apply_upgrades(cls_name, save, base)

        self.running = True
        self.px = float(self.mw//4)
        self.py = float(self.mh//2)
        self.hp = base["hp"]; self.max_hp = base["hp"]
        self.speed = base["speed"] * (1 + 0.3*(size_mult-1))
        self.base_speed = self.speed  # base_speed is the unmodified reference, used by reliquary water slow
        self.dash_dist = base["dash_dist"]
        self.dmg_mult = base["dmg_mult"]
        self.cd_mult = base["cd_mult"]
        self.absorb = base["absorb"]
        self.hit_range_bonus = base["hit_range_bonus"]

        # move cooldowns
        self.move_cds = {k:v for k,v in cd["move_cds"].items()}
        self.move_cds_end = {k:0 for k in range(1,6)}
        self.selected = 1
        self.stun_until = 0

        # dash
        self.dash_ready = 0; self.dash_trail = []

        # combo states
        self.combo_state = 0; self.combo_ready = 0
        self.combo_lockout_until = 0
        self.combo_last_hit = 0.0  # timestamp of last hit on move 1, used for 2s idle reset
        self.chest_stand_start = None  # reliquary chest interaction timer

        # wizard
        self.whirlpool_chars = list("@#$%&*!?~^+=<>|\\/`.,;:abcdefABCDEF0123456789")
        self.ult_active = False; self.ult_start = 0; self.ult_dur = 5.0
        self.ult_dmg_tick = 0; self.ult_proc = None

        # gravedigger
        self.landmines = []; self.max_mines = 3
        self.fissure_rings = []; self.gd_invincible_until = 0
        self.gd_ult_active = False; self.gd_ult_start = 0

        # marionette
        self.strings = []        # bossstring list
        self.redirect_ready = False; self.redirect_expires = 0

        # cartographer
        self.charted = set()     # set of (x,y)
        self.char_fire = {}      # (x,y)->fire_until
        self.quicksand_zones = [] # [(x,y,r,expires)]
        self.terrain_walls = []   # [(x,y,expires)]

        # revenant
        self.lives = 5; self.rage_stacks = 0
        self.bone_shield_active = False; self.bone_shield_ready = 0
        self.rev_ult_active = False; self.rev_ult_end = 0

        # siphon. hijack opens a 1.5s reflect window on move 1.
        # charges store absorbed boss energy (up to 3).
        # each charge is a dict with type and damage value.
        # null_field blocks boss speed/armor buffs in a radius.
        # leech temporarily applies the boss's own buff to the player.
        self.siphon_charges = []
        self.hijack_active = False
        self.hijack_start = 0.0
        self.siphon_null_field = None
        self.siphon_leech_active = False
        self.siphon_leech_expires = 0.0

        # undertaker. sentence stacks build on boss, reset on execution.
        # total_sentences accumulates all stacks ever landed (for guillotine scaling).
        # execution_ready fires automatically at 5 stacks.
        # parry_window: True for 0.8s after pressing parry — next boss hit counters.
        self.sentence_stacks = 0
        self.total_sentences = 0
        self.execution_ready = False
        self.parry_window = False
        self.parry_window_start = 0.0

        # glasswright. panes are placed as solid terrain (up to 4 active).
        # each pane is [x, y, hp, shard_born] where shard_born is set on shatter.
        # shards linger as bleed zones for 3s after a pane breaks.
        self.glass_panes = []   # [[x, y, hp, shatter_time_or_None]]
        self.glass_shards = []  # [(x, y, expires)]

        # bellwether. followers are positioned agents that act on commands.
        # each follower: [x, y, state, target_x, target_y, hp]
        # states: 'idle', 'wall', 'charging', 'dead'
        self.followers = []
        self.wall_mode = False

        # ashwalker. ember_tiles: dict of (x,y)->expires. intensity doubles during ignition.
        # ignition_active: True for 2s after pressing move 2.
        self.ember_tiles = {}       # (x,y) -> expiry timestamp
        self.ignition_active = False
        self.ignition_until = 0.0

        # effects/objects
        self.particles = []; self.projectiles = []
        self.ripples = []; self.afterimages = []
        self.gravemarks = []
        self.messages = []    # [text,born,dur,x,y,clr]

        # boss
        bx = self.mw - max(8, int(self.mw*0.2))
        boss = Boss(boss_key, bx, self.mh//2)
        boss.damage = int(boss.damage * (1 + 0.3*(size_mult-1)))
        self.boss = boss

        # boss2 clone (mirror map)
        self.mirror_clone_hp = 200 if map_key=="mirror" else 0
        self.mirror_clone_regen = 0

        self.game_over = False; self.victory = False
        self.coin_mult = MAP_DATA[map_key]["coin_mult"] * size_coin_mult
        self.earned_coins = 0

    def cd(self, move):
        return self.move_cds.get(move, 1.0) * self.cd_mult

    def dist_boss(self):
        """Distance from player to nearest boss body cell."""
        if not self.boss.alive: return 999
        return self.boss.body_dist(self.px, self.py)

    def can_ult(self): return self.hp < self.max_hp//2

    def is_stunned(self): return time.time()<self.stun_until

    def add_msg(self, text, dur=1.0, x=None, y=None, clr=(255,255,255)):
        if x is None: x=int(self.px)
        if y is None: y=int(self.py)
        self.messages.append([text,time.time(),dur,x,y,clr])

    def take_damage(self, dmg):
        if self.is_stunned() and self.cls_name=="revenant" and self.bone_shield_active:
            self.bone_shield_active=False
            self.add_msg("BLOCKED!", 0.8, clr=(100,200,255))
            return
        absorbed = min(dmg, dmg*self.absorb)
        actual = int(dmg - absorbed)
        self.hp -= actual
        self.add_msg(f"-{actual}", 0.7, int(self.px), int(self.py)-1, (255,80,80))
        if self.hp <= 0:
            if self.cls_name=="revenant" and self.lives>1:
                self.lives -= 1; self.rage_stacks += 1
                self.hp = 60; self.stun_until = time.time()+0.5
                self.add_msg("RESPAWN!", 1.0, int(self.px), int(self.py)-2, (255,100,100))
            else:
                self.hp=0; self.game_over=True

# input/action dispatch
def process_input(g, keys, dt):
    if g.game_over or g.victory:
        return
    if g.ult_active or g.rev_ult_active:
        return  # locked during ultimate

    mx=my=0.0
    for k in keys:
        if k=='w': my-=1
        elif k=='s': my+=1
        elif k=='a': mx-=1
        elif k=='d': mx+=1
        elif k in '12345': g.selected=int(k)
        elif k=='q': do_dash(g)
        elif k==' ': do_action(g)
        elif k in('\x03','\x1b'): g.running=False

    if not g.is_stunned() and (mx or my):
        # reliquary water slow: speed_override set when player is in water
        effective_speed = getattr(g, 'speed_override', None) or g.speed
        spd = effective_speed*dt
        # cartographer: quicksand slow
        for (qx,qy,qr,qe) in g.quicksand_zones:
            if time.time()<qe and math.hypot(g.px-qx,g.py-qy)<qr:
                spd *= 0.4
                break
        norm=math.hypot(mx,my) or 1
        # for spire: let position overflow the border freely, then wrap.
        # for all other maps: clamp to arena bounds as normal.
        raw_nx = g.px + (mx/norm)*spd
        raw_ny = g.py + (my/norm)*spd
        if g.map_key == "spire":
            # wrap by treating the playable area as 1..mw-2 wide and 1..mh-2 tall.
            # shift into 0-based space, modulo the playable width/height, shift back.
            # this makes left-edge and top-edge wrap correctly just like right and bottom.
            pw = g.mw - 2  # playable width (cols 1..mw-2)
            ph = g.mh - 2  # playable height (rows 1..mh-2)
            nx = ((raw_nx - 1) % pw) + 1
            ny = ((raw_ny - 1) % ph) + 1
        else:
            nx = max(1, min(g.mw-2, raw_nx))
            ny = max(1, min(g.mh-2, raw_ny))
        # check map blocks
        boss_body = g.boss.get_body_set() if g.boss.alive else set()
        # architect walls (boss5) block the player but not the boss itself
        arch_blocked = False
        if g.boss.alive and g.boss.key == "boss5":
            for seg in g.boss.architect_walls:
                if (int(nx), int(ny)) in [(ax, ay) for ax, ay in seg]:
                    arch_blocked = True
                    break
        if not g.geo.is_blocked(int(nx),int(ny)) and (int(nx),int(ny)) not in boss_body and not arch_blocked:
            # lava check
            if g.geo.is_lava(int(nx),int(ny)):
                g.take_damage(g.max_hp)  # instant death
            else:
                g.px=nx; g.py=ny
                # cartographer: chart tile
                if g.cls_name=="cartographer":
                    g.charted.add((int(nx),int(ny)))

def do_dash(g):
    now=time.time()
    if now<g.dash_ready or g.is_stunned(): return
    g.dash_ready=now+10.0*(g.cd_mult)
    dx=g.px-g.boss.x; dy=g.py-g.boss.y
    d=math.hypot(dx,dy) or 1
    ndx=dx/d; ndy=dy/d
    dist=g.dash_dist
    trail=[]
    for i in range(dist):
        tx=g.px+ndx*i; ty=g.py+ndy*i
        tx=max(1,min(g.mw-2,tx)); ty=max(1,min(g.mh-2,ty))
        trail.append((int(tx),int(ty),now))
    g.px=max(1,min(g.mw-2,g.px+ndx*dist))
    g.py=max(1,min(g.mh-2,g.py+ndy*dist))
    g.dash_trail=trail

def do_action(g):
    if g.is_stunned(): return
    move=g.selected; now=time.time()
    if now<g.move_cds_end.get(move,0):
        g.add_msg("Cooldown!",1.0,g.mw//2,g.mh//2,(255,80,80)); return
    # post-combo lockout blocks moves 2-4 (move 1 is always the combo/basic)
    if move in (2,3,4) and now < g.combo_lockout_until:
        remaining = g.combo_lockout_until - now
        g.add_msg(f"Recovering... {remaining:.1f}s",0.8,g.mw//2,g.mh//2,(200,140,50)); return
    dispatch={
        "wizard":       [do_scepter,do_arcane_snap,do_gravemark,do_blink_scatter,do_wiz_ult],
        "gravedigger":  [do_shovel,do_dig,do_bury,do_exhume,do_gd_ult],
        "marionette":   [do_silk_strike,do_plant_string,do_puppet_pull,do_redirect,do_mar_ult],
        "cartographer": [do_ink_stab,do_flare,do_quicksand,do_terrain_wall,do_cart_ult],
        "revenant":     [do_death_blow,do_rage_strike,do_bone_shield,do_self_destruct,do_rev_ult],
        "siphon":       [do_hijack,do_overload,do_null_field,do_leech,do_void_surge],
        "undertaker":   [do_axe,do_parry,do_chain_drag,do_execution,do_guillotine],
        "glasswright":  [do_glass_shiv,do_place_pane,do_shatter,do_prism_blast,do_grand_facade],
        "bellwether":   [do_summon,do_rally_cry,do_dispatch,do_martyrdom,do_the_charge],
        "ashwalker":    [do_cinder_strike,do_ignition,do_backdraft,do_ember_step,do_conflagration],
    }
    fn=dispatch.get(g.cls_name,[])[move-1]
    # if firing any move other than the basic combo, reset the combo state immediately
    if move != 1 and g.combo_state > 0:
        g.combo_state = 0
        g.combo_ready = 0
    fn(g)

# wizard
def do_scepter(g):
    now=time.time()
    if now<g.combo_ready or not g.boss.alive: return
    if g.dist_boss()>6+g.hit_range_bonus:
        g.add_msg("Out of range!",0.8,g.mw//2,g.mh//2-1,(200,200,100)); return
    s=g.combo_state; dmg=int([5,5,5,5,10][s]*g.dmg_mult)
    final=(s==4)
    g.projectiles.append(Projectile(g.px,g.py,g.boss.x,g.boss.y,18,'*',(160,80,220),dmg,'player'))
    if final:
        play(SND_FINAL); g.combo_state=0; g.combo_ready=now+0.7; g.boss.stun(0.7)
        g.combo_lockout_until = now + 3.5; g.combo_last_hit=now  # post-combo recovery
    else:
        play(SND_HIT); g.combo_state+=1; g.combo_ready=now+0.35*g.cd_mult; g.combo_last_hit=now

def do_arcane_snap(g):
    g.move_cds_end[2]=time.time()+g.cd(2)
    g.ripples.append(Ripple(g.px,g.py,10,0.6,(220,100,255),(100,0,180)))
    if g.boss.alive and g.dist_boss()<=10:
        d=g.dist_boss(); dmg=int(max(5,20*(1-d/10))*g.dmg_mult)
        g.boss.hp-=dmg; g.boss.stun(1.5); g.boss.flash_until=time.time()+0.3
        _dmg_msg(g,dmg,(220,100,255))

def do_gravemark(g):
    if not g.boss.alive or g.dist_boss()>8+g.hit_range_bonus:
        g.add_msg("Out of range!",0.8,g.mw//2,g.mh//2-1,(200,200,100)); return
    g.move_cds_end[3]=time.time()+g.cd(3)
    g.gravemarks.append(GraveMark(int(g.boss.x),int(g.boss.y)))

def do_blink_scatter(g):
    if not g.boss.alive or g.dist_boss()>10+g.hit_range_bonus:
        g.add_msg("Out of range!",0.8,g.mw//2,g.mh//2-1,(200,200,100)); return
    g.move_cds_end[4]=time.time()+g.cd(4)
    ox,oy=g.px,g.py; tx,ty=g.boss.x,g.boss.y
    # spawn afterimages along the path
    for i in range(1,4):
        t=i/4.0
        g.afterimages.append(Afterimage(int(ox+(tx-ox)*t),int(oy+(ty-oy)*t)))
    # find a free landing tile near the boss but outside its body and map geometry.
    # try increasing radii in random angle order until a clear cell is found.
    boss_body = g.boss.get_body_set()
    landed = False
    for radius in [4, 5, 6, 7, 3]:
        # shuffle angles so we don't always end up on the same side
        angles = list(range(0, 360, 20))
        random.shuffle(angles)
        for deg in angles:
            rad = math.radians(deg)
            # x offset is wider than y due to char aspect ratio
            cx2 = tx + math.cos(rad) * radius * 1.6
            cy2 = ty + math.sin(rad) * radius * 0.8
            cx2 = int(max(1, min(g.mw-2, cx2)))
            cy2 = int(max(1, min(g.mh-2, cy2)))
            if (cx2, cy2) not in boss_body and not g.geo.is_blocked(cx2, cy2):
                g.px = float(cx2); g.py = float(cy2)
                landed = True
                break
        if landed:
            break
    # fallback: if no clear tile found at any radius, just step back from boss
    if not landed:
        dx = ox - tx; dy = oy - ty
        d = math.hypot(dx, dy) or 1
        g.px = max(1, min(g.mw-2, tx + (dx/d)*5))
        g.py = max(1, min(g.mh-2, ty + (dy/d)*2.5))

def do_wiz_ult(g):
    if not g.can_ult(): g.add_msg("Need <50% HP!",1.0,g.mw//2,g.mh//2,(255,80,80)); return
    if g.ult_active: return
    g.move_cds_end[5]=time.time()+g.cd(5)
    g.ult_active=True; g.ult_start=time.time(); g.ult_dmg_tick=time.time()
    g.stun_until=time.time()+g.ult_dur+0.1
    if g.boss.alive: g.boss.stun(g.ult_dur)
    try: g.ult_proc=subprocess.Popen(["afplay",SND_ULT],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    except: pass

# gravedigger
def do_shovel(g):
    now=time.time()
    if now<g.combo_ready or not g.boss.alive: return
    if g.dist_boss()>2+g.hit_range_bonus:
        g.add_msg("Out of range!",0.8,g.mw//2,g.mh//2-1,(200,200,100)); return
    s=g.combo_state; final=(s==4)
    if final:
        dmg=int(20*g.dmg_mult)
        g.boss.hp-=dmg; g.boss.flash_until=now+0.4; g.boss.stun(0.7)
        dx=g.boss.x-g.px; dy=g.boss.y-g.py; d=math.hypot(dx,dy) or 1
        g.boss.x=max(2,min(g.mw-4,g.boss.x+(dx/d)*4))
        g.boss.y=max(2,min(g.mh-3,g.boss.y+(dy/d)*2))
        for ang in range(0,360,20):
            g.particles.append(Particle(g.px,g.py,math.cos(math.radians(ang))*6,math.sin(math.radians(ang))*3,'+',(230,230,200),0.35))
        play(SND_FINAL); _dmg_msg(g,dmg,(200,160,80))
        g.combo_state=0; g.combo_ready=now+0.7
        g.combo_lockout_until = now + 4.0
    else:
        dmg=int(8*g.dmg_mult)
        g.boss.hp-=dmg; g.boss.flash_until=now+0.2; play(SND_HIT)
        for _ in range(3):
            ang=random.uniform(math.pi,math.pi*2)
            g.particles.append(Particle(g.boss.x,g.boss.y,math.cos(ang)*4,math.sin(ang)*2-2,",",(120,90,50),0.4))
        _dmg_msg(g,dmg,(180,140,60))
        g.combo_state+=1; g.combo_ready=now+0.3*g.cd_mult; g.combo_last_hit=now

def do_dig(g):
    active=[m for m in g.landmines if m.alive() and not m.triggered]
    if len(active)>=g.max_mines:
        g.add_msg("Max mines!",0.8,g.mw//2,g.mh//2,(200,160,60)); return
    g.move_cds_end[2]=time.time()+g.cd(2)
    g.landmines.append(Landmine(int(g.px),int(g.py)))
    for _ in range(5):
        ang=random.uniform(0,math.pi*2)
        g.particles.append(Particle(g.px,g.py,math.cos(ang)*3,math.sin(ang)*1.5-1,",",(100,75,40),0.5))

def do_bury(g):
    if not g.boss.alive or g.dist_boss()>5+g.hit_range_bonus:
        g.add_msg("Out of range!",0.8,g.mw//2,g.mh//2-1,(200,200,100)); return
    g.move_cds_end[3]=time.time()+g.cd(3)
    dmg=int(15*g.dmg_mult); g.boss.hp-=dmg; g.boss.stun(2.5)
    g.boss.flash_until=time.time()+0.5; _dmg_msg(g,dmg,(140,100,60))
    for _ in range(16):
        ang=random.uniform(0,math.pi*2); r=random.uniform(1,3)
        g.particles.append(Particle(g.boss.x+math.cos(ang)*r*2,g.boss.y+math.sin(ang)*r,
            math.cos(ang)*2,math.sin(ang)-0.5,random.choice(['#','+','X']),(100,75,40),0.8))

def do_exhume(g):
    g.move_cds_end[4]=time.time()+g.cd(4)
    active=[m for m in g.landmines if m.alive() and not m.triggered]
    if not active: g.add_msg("No mines!",0.8,g.mw//2,g.mh//2,(200,160,60)); return
    for m in active: m.trigger()
    g.add_msg("EXHUME!",0.6,g.mw//2,g.mh//2-1,(200,140,50))

def do_gd_ult(g):
    if not g.can_ult(): g.add_msg("Need <50% HP!",1.0,g.mw//2,g.mh//2,(255,80,80)); return
    if g.gd_ult_active: return
    g.move_cds_end[5]=time.time()+g.cd(5)
    g.gd_ult_active=True; g.gd_ult_start=time.time()
    g.gd_invincible_until=time.time()+1.5
    g.fissure_rings.append(FissureRing(int(g.px),int(g.py),max(g.mw,g.mh)))
    for ang in range(0,360,8):
        g.particles.append(Particle(g.px,g.py,math.cos(math.radians(ang))*15,math.sin(math.radians(ang))*7,
            random.choice(['/','\\','|','-','#']),(200,100,30),1.0))
    try: subprocess.Popen(["afplay",SND_ULT],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    except: pass

# marionette
def do_silk_strike(g):
    now=time.time()
    if now<g.combo_ready or not g.boss.alive: return
    if g.dist_boss()>2+g.hit_range_bonus:
        g.add_msg("Out of range!",0.8,g.mw//2,g.mh//2-1,(200,200,100)); return
    s=g.combo_state; final=(s==4)
    dmg=int((12 if final else 6)*g.dmg_mult)
    g.boss.hp-=dmg; g.boss.flash_until=now+(0.4 if final else 0.2)
    play(SND_FINAL if final else SND_HIT); _dmg_msg(g,dmg,(200,60,120))
    # string reflect
    reflect=int(dmg*0.3*len(g.strings))
    if reflect>0:
        g.boss.hp-=reflect; _dmg_msg(g,reflect,(255,100,200))
    if final:
        g.combo_state=0; g.combo_ready=now+0.7; g.boss.stun(0.5)
        g.combo_lockout_until = now + 3.0
    else: g.combo_state+=1; g.combo_ready=now+0.4*g.cd_mult; g.combo_last_hit=now

def do_plant_string(g):
    if not g.boss.alive or g.dist_boss()>8+g.hit_range_bonus:
        g.add_msg("Out of range!",0.8,g.mw//2,g.mh//2-1,(200,200,100)); return
    if len(g.strings)>=3:
        g.add_msg("Max strings!",0.8,g.mw//2,g.mh//2,(200,60,120)); return
    g.move_cds_end[2]=time.time()+g.cd(2)
    g.strings.append(BossString())
    g.add_msg(f"String #{len(g.strings)} planted!",0.8,int(g.boss.x),int(g.boss.y)-1,(220,100,180))

def do_puppet_pull(g):
    if not g.boss.alive or g.dist_boss()>10+g.hit_range_bonus: return
    g.move_cds_end[3]=time.time()+g.cd(3)
    d=g.dist_boss() or 1
    dx=(g.px-g.boss.x)/d; dy=(g.py-g.boss.y)/d
    g.boss.x=max(2,min(g.mw-4,g.boss.x+dx*5))
    g.boss.y=max(2,min(g.mh-3,g.boss.y+dy*2.5))
    g.add_msg("PULLED!",0.7,int(g.boss.x),int(g.boss.y)-1,(200,60,120))

def do_redirect(g):
    if not g.boss.alive: return
    g.move_cds_end[4]=time.time()+g.cd(4)
    g.redirect_ready=True; g.redirect_expires=time.time()+3.0
    g.add_msg("Redirect ready!",0.8,g.mw//2,g.mh//2,(220,100,180))

def do_mar_ult(g):
    if not g.can_ult(): g.add_msg("Need <50% HP!",1.0,g.mw//2,g.mh//2,(255,80,80)); return
    if not g.strings: g.add_msg("No strings!",1.0,g.mw//2,g.mh//2,(200,60,120)); return
    g.move_cds_end[5]=time.time()+g.cd(5)
    dmg=int(15*len(g.strings)*g.dmg_mult)
    if g.boss.alive: g.boss.hp-=dmg; g.boss.flash_until=time.time()+0.5; _dmg_msg(g,dmg,(255,50,150))
    for _ in range(len(g.strings)*8):
        ang=random.uniform(0,math.pi*2)
        g.particles.append(Particle(g.boss.x,g.boss.y,math.cos(ang)*10,math.sin(ang)*5,'*',(220,80,160),0.6))
    g.strings.clear()
    g.add_msg("CUT ALL STRINGS!",1.2,g.mw//2,g.mh//2-1,(255,100,180))

# cartographer
def do_ink_stab(g):
    now=time.time()
    if now<g.combo_ready or not g.boss.alive: return
    if g.dist_boss()>2+g.hit_range_bonus:
        g.add_msg("Out of range!",0.8,g.mw//2,g.mh//2-1,(200,200,100)); return
    s=g.combo_state; final=(s==4); dmg=int((10 if final else 5)*g.dmg_mult)
    g.boss.hp-=dmg; g.boss.flash_until=now+(0.4 if final else 0.2)
    play(SND_FINAL if final else SND_HIT); _dmg_msg(g,dmg,(60,200,140))
    if final:
        g.combo_state=0; g.combo_ready=now+0.7; g.boss.stun(0.5)
        g.combo_lockout_until = now + 3.5
    else: g.combo_state+=1; g.combo_ready=now+0.35*g.cd_mult; g.combo_last_hit=now
    # mark current tile
    g.charted.add((int(g.px),int(g.py)))

def do_flare(g):
    if not g.boss.alive or g.dist_boss()>8+g.hit_range_bonus: return
    g.move_cds_end[2]=time.time()+g.cd(2)
    g.boss.stun(2.0); g.boss.flash_until=time.time()+0.4
    g.ripples.append(Ripple(g.boss.x,g.boss.y,5,0.5,(255,255,100),(200,200,50)))
    g.add_msg("BLINDED!",0.8,int(g.boss.x),int(g.boss.y)-1,(240,240,80))

def do_quicksand(g):
    if not g.boss.alive or g.dist_boss()>8+g.hit_range_bonus: return
    g.move_cds_end[3]=time.time()+g.cd(3)
    g.quicksand_zones.append((int(g.boss.x),int(g.boss.y),4,time.time()+4.0))
    g.add_msg("QUICKSAND!",0.8,int(g.boss.x),int(g.boss.y)-1,(160,140,60))

def do_terrain_wall(g):
    g.move_cds_end[4]=time.time()+g.cd(4)
    # place a wall of 5 tiles in front of player facing boss
    bx=g.boss.x-g.px; by=g.boss.y-g.py
    d=math.hypot(bx,by) or 1; perp=(-by/d,bx/d)
    wx=g.px+bx/d*2; wy=g.py+by/d*2
    exp=time.time()+2.0
    for off in range(-2,3):
        tx=int(wx+perp[0]*off); ty=int(wy+perp[1]*off)
        if 0<tx<g.mw-1 and 0<ty<g.mh-1:
            g.terrain_walls.append((tx,ty,exp))

def do_cart_ult(g):
    if not g.can_ult(): g.add_msg("Need <50% HP!",1.0,g.mw//2,g.mh//2,(255,80,80)); return
    if not g.charted: g.add_msg("No charted tiles!",1.0,g.mw//2,g.mh//2,(60,200,140)); return
    g.move_cds_end[5]=time.time()+g.cd(5)
    now=time.time()
    for tx,ty in g.charted:
        g.char_fire[(tx,ty)]=now+2.0
        if g.boss.alive and math.hypot(g.boss.x-tx,g.boss.y-ty)<1.5:
            dmg=int(5*g.dmg_mult); g.boss.hp-=dmg
        g.particles.append(Particle(tx,ty,random.uniform(-1,1),random.uniform(-2,0),'▲',(255,140,30),0.8))
    g.add_msg("MAP IGNITION!",1.2,g.mw//2,g.mh//2-1,(255,180,50))

# revenant
def do_death_blow(g):
    now=time.time()
    if now<g.combo_ready or not g.boss.alive: return
    if g.dist_boss()>2+g.hit_range_bonus:
        g.add_msg("Out of range!",0.8,g.mw//2,g.mh//2-1,(200,200,100)); return
    s=g.combo_state; final=(s==4)
    base_dmg=20 if final else 12
    dmg=int(base_dmg*g.dmg_mult*(1+0.15*g.rage_stacks))
    g.boss.hp-=dmg; g.boss.flash_until=now+(0.4 if final else 0.2)
    play(SND_FINAL if final else SND_HIT); _dmg_msg(g,dmg,(220,50,50))
    if final:
        g.combo_state=0; g.combo_ready=now+0.7; g.boss.stun(0.6)
        g.combo_lockout_until = now + 3.0
    else: g.combo_state+=1; g.combo_ready=now+0.45*g.cd_mult; g.combo_last_hit=now

def do_rage_strike(g):
    now=time.time()
    if now<g.combo_ready or not g.boss.alive: return
    if g.dist_boss()>2+g.hit_range_bonus: return
    dmg=int(6*g.dmg_mult*(1+0.15*g.rage_stacks))
    g.boss.hp-=dmg; g.boss.flash_until=now+0.15; play(SND_HIT); _dmg_msg(g,dmg,(180,30,30))
    g.combo_ready=now+0.2*g.cd_mult

def do_bone_shield(g):
    g.move_cds_end[3]=time.time()+g.cd(3)
    g.bone_shield_active=True
    g.add_msg("SHIELD UP!",0.8,int(g.px),int(g.py)-2,(100,200,255))

def do_self_destruct(g):
    if not g.boss.alive: return
    g.move_cds_end[4]=time.time()+g.cd(4)
    if g.lives<=1: g.add_msg("Last life!",0.8,g.mw//2,g.mh//2,(255,80,80)); return
    g.lives-=1; g.rage_stacks+=1; g.hp=60
    dmg=int(80*g.dmg_mult*(1+0.15*g.rage_stacks))
    g.boss.hp-=dmg; g.boss.flash_until=time.time()+0.6; _dmg_msg(g,dmg,(255,50,50))
    for _ in range(20):
        ang=random.uniform(0,math.pi*2)
        g.particles.append(Particle(g.px,g.py,math.cos(ang)*12,math.sin(ang)*6,random.choice(['*','#','!']),(220,80,80),0.7))
    g.add_msg("SELF-DESTRUCT!",1.0,g.mw//2,g.mh//2-1,(255,80,80))

def do_rev_ult(g):
    if not g.can_ult(): g.add_msg("Need <50% HP!",1.0,g.mw//2,g.mh//2,(255,80,80)); return
    if g.rev_ult_active: return
    g.move_cds_end[5]=time.time()+g.cd(5)
    g.rev_ult_active=True; g.rev_ult_end=time.time()+4.0
    try: subprocess.Popen(["afplay",SND_ULT],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    except: pass
    g.add_msg("BERSERK!",1.2,g.mw//2,g.mh//2-1,(255,50,50))


# siphon class abilities.
# the siphon steals energy from the boss and reflects or detonates it.
# hijack is the core move: open a 1.5s reflect window. if the boss attacks
# during that window, the hit is absorbed as a charge instead of damaging you.
# up to 3 charges can be stored. all other moves spend or manipulate charges.

def do_hijack(g):
    now = time.time()
    if g.hijack_active:
        # pressing again cancels the window early
        g.hijack_active = False
        g.add_msg("Hijack cancelled.", 0.5, g.mw//2, g.mh//2, (100, 180, 160))
        return
    if len(g.siphon_charges) >= 3:
        g.add_msg("Charges full! Use Overload first.", 1.0, g.mw//2, g.mh//2, (200, 100, 80))
        return
    g.move_cds_end[1] = now + g.cd(1)
    g.hijack_active = True
    g.hijack_start = now
    g.add_msg("HIJACK window open...", 1.5, g.mw//2, g.mh//2 - 1, (80, 220, 200))

def do_overload(g):
    # detonate all stored charges simultaneously for burst damage.
    # damage scales with number of charges and their stored values.
    now = time.time()
    if not g.siphon_charges:
        g.add_msg("No charges stored!", 1.0, g.mw//2, g.mh//2, (200, 100, 80)); return
    g.move_cds_end[2] = now + g.cd(2)
    total_dmg = 0
    for ch in g.siphon_charges:
        dmg = int(ch["value"] * 1.5 * g.dmg_mult)
        total_dmg += dmg
    if g.boss.alive:
        g.boss.hp -= total_dmg
        g.boss.flash_until = now + 0.5
        _dmg_msg(g, total_dmg, (80, 230, 210))
    # explosion ring for each charge
    for ch in g.siphon_charges:
        for _ in range(8):
            ang = random.uniform(0, math.pi * 2)
            g.particles.append(Particle(g.boss.x, g.boss.y,
                math.cos(ang)*6, math.sin(ang)*3, chr(9835), (80,220,200), 0.5))
    g.siphon_charges.clear()
    g.add_msg(f"OVERLOAD! {total_dmg} dmg", 1.0, g.mw//2, g.mh//2, (80,230,210))

def do_null_field(g):
    # place a null field at current position. boss inside radius cannot gain
    # speed boosts or armor buffs for the duration.
    now = time.time()
    g.move_cds_end[3] = now + g.cd(3)
    g.siphon_null_field = (g.px, g.py, now + 8.0)
    g.add_msg("Null Field placed.", 0.8, g.mw//2, g.mh//2, (60,180,160))

def do_leech(g):
    # steal the boss current speed advantage or armor and apply it to self.
    # if leech active, using it again refreshes the duration.
    now = time.time()
    g.move_cds_end[4] = now + g.cd(4)
    g.siphon_leech_active = True
    g.siphon_leech_expires = now + 6.0
    # drain a small hit as flavor
    if g.boss.alive:
        dmg = int(15 * g.dmg_mult)
        g.boss.hp -= dmg
        g.boss.flash_until = now + 0.2
        _dmg_msg(g, dmg, (60, 200, 180))
    g.add_msg("LEECH active!", 0.8, g.mw//2, g.mh//2, (60, 200, 180))

def do_void_surge(g):
    # ultimate: release all stored charges in an expanding ring of void energy.
    # each charge adds 2 additional ring waves. minimum 1 ring even with no charges.
    now = time.time()
    if not g.can_ult():
        g.add_msg("Need <50% HP!", 1.0, g.mw//2, g.mh//2, (255,80,80)); return
    g.move_cds_end[5] = now + g.cd(5)
    charge_count = len(g.siphon_charges)
    waves = 1 + charge_count * 2
    base_dmg = int((30 + charge_count * 20) * g.dmg_mult)
    for w in range(waves):
        delay_r = (w + 1) * 3
        # ripple for each wave, slightly offset in radius
        g.ripples.append(Ripple(g.px, g.py, delay_r, 0.6 + w*0.1,
                                (40, 180, 160), (20, 80, 120)))
    if g.boss.alive:
        g.boss.hp -= base_dmg
        g.boss.stun(1.5)
        g.boss.flash_until = now + 0.8
        _dmg_msg(g, base_dmg, (80,230,200))
    g.siphon_charges.clear()
    g.add_msg("VOID SURGE!", 1.5, g.mw//2, g.mh//2 - 1, (80, 230, 200))
    play(SND_ULT)


# ── undertaker ────────────────────────────────────────────────────────────────
# slow axe executioner. builds sentence stacks on every hit.
# at 5 stacks, execution fires automatically for big damage.
# parry counters the next boss hit. chain drag repositions the boss.
# guillotine ult: damage = 8 * total stacks accumulated this entire run.

def do_axe(g):
    now = time.time()
    if not g.boss.alive or g.dist_boss() > 2.5 + g.hit_range_bonus:
        g.add_msg("Out of range!", 0.8, g.mw//2, g.mh//2-1, (200,200,100)); return
    g.move_cds_end[1] = now + g.cd(1)
    dmg = int(18 * g.dmg_mult)
    g.boss.hp -= dmg; g.boss.flash_until = now + 0.3
    play(SND_HIT); _dmg_msg(g, dmg, (140,80,220))
    # build a sentence stack on the boss
    g.sentence_stacks += 1
    g.total_sentences += 1
    g.add_msg(f"Sentence {g.sentence_stacks}/5", 0.5, int(g.boss.x), int(g.boss.y)-2, (140,80,220))
    # auto-fire execution at 5 stacks
    if g.sentence_stacks >= 5:
        _do_execution_burst(g, now)

def _do_execution_burst(g, now):
    # internal: fires execution damage and resets stacks.
    g.sentence_stacks = 0
    ex_dmg = int(80 * g.dmg_mult)
    g.boss.hp -= ex_dmg; g.boss.stun(1.2); g.boss.flash_until = now + 0.8
    play(SND_FINAL)
    _dmg_msg(g, ex_dmg, (200,100,255))
    g.add_msg("EXECUTION!", 1.2, g.mw//2, g.mh//2-1, (180,80,240))
    for _ in range(12):
        ang = random.uniform(0, math.pi*2)
        g.particles.append(Particle(g.boss.x, g.boss.y,
            math.cos(ang)*5, math.sin(ang)*2.5, chr(9670), (180,80,240), 0.6))

def do_parry(g):
    # opens a 0.8s counter window. next boss hit: reflect full damage + stun.
    now = time.time()
    g.move_cds_end[2] = now + g.cd(2)
    g.parry_window = True
    g.parry_window_start = now
    g.add_msg("PARRY ready...", 0.8, g.mw//2, g.mh//2-1, (200,160,255))

def do_chain_drag(g):
    # drag boss to within melee range (3 units away from player).
    now = time.time()
    if not g.boss.alive:
        g.add_msg("No target!", 0.8, g.mw//2, g.mh//2-1, (200,200,100)); return
    g.move_cds_end[3] = now + g.cd(3)
    dx = g.px - g.boss.x; dy = g.py - g.boss.y
    d = math.hypot(dx, dy) or 1
    # pull boss to exactly 2 units away
    g.boss.x = g.px - (dx/d)*2.2
    g.boss.y = g.py - (dy/d)*1.1
    g.boss.stun(0.5); g.boss.flash_until = now + 0.2
    dmg = int(10 * g.dmg_mult)
    g.boss.hp -= dmg; _dmg_msg(g, dmg, (140,80,220))
    g.add_msg("DRAGGED!", 0.7, g.mw//2, g.mh//2, (140,80,220))
    for _ in range(6):
        ang = random.uniform(0, math.pi*2)
        g.particles.append(Particle(g.boss.x, g.boss.y,
            math.cos(ang)*3, math.sin(ang)*1.5, '+', (120,60,180), 0.4))

def do_execution(g):
    # manual execution — only usable if sentence_stacks > 0.
    now = time.time()
    if not g.boss.alive:
        g.add_msg("No target!", 0.8, g.mw//2, g.mh//2-1, (200,200,100)); return
    if g.sentence_stacks == 0:
        g.add_msg("No stacks!", 0.8, g.mw//2, g.mh//2, (200,100,80)); return
    # no cooldown on move 4 — it's gated by stacks instead
    _do_execution_burst(g, now)

def do_guillotine(g):
    # ult: deals 8 * total_sentences damage — scales with every stack ever landed.
    now = time.time()
    if not g.can_ult():
        g.add_msg("Need <50% HP!", 1.0, g.mw//2, g.mh//2, (255,80,80)); return
    if not g.boss.alive:
        g.add_msg("No target!", 0.8, g.mw//2, g.mh//2-1, (200,200,100)); return
    g.move_cds_end[5] = now + g.cd(5)
    dmg = int(8 * max(1, g.total_sentences) * g.dmg_mult)
    g.boss.hp -= dmg; g.boss.stun(2.0); g.boss.flash_until = now + 1.0
    _dmg_msg(g, dmg, (200,80,255))
    g.add_msg(f"GUILLOTINE! ({g.total_sentences} stacks)", 1.5, g.mw//2, g.mh//2-1, (200,80,255))
    play(SND_ULT)
    for _ in range(20):
        ang = random.uniform(0, math.pi*2)
        g.particles.append(Particle(g.boss.x, g.boss.y,
            math.cos(ang)*7, math.sin(ang)*3.5, chr(9670), (180,60,240), 0.9))


# ── glasswright ───────────────────────────────────────────────────────────────
# places stained glass panes as solid terrain (up to 4).
# shattering a pane creates a bleed shard zone.
# prism blast fires projectiles through every active pane.
# grand facade ult: coat the arena border in panes.

def do_glass_shiv(g):
    now = time.time()
    if not g.boss.alive or g.dist_boss() > 2.5 + g.hit_range_bonus:
        g.add_msg("Out of range!", 0.8, g.mw//2, g.mh//2-1, (200,200,100)); return
    g.move_cds_end[1] = now + g.cd(1)
    dmg = int(10 * g.dmg_mult)
    # bonus damage if boss is standing in a shard zone
    in_shard = any(math.hypot(g.boss.x-sx, g.boss.y-sy) < 2 for sx,sy,_ in g.glass_shards)
    if in_shard:
        dmg = int(dmg * 1.5)
        g.add_msg("BLEEDING!", 0.5, int(g.boss.x), int(g.boss.y)-2, (180,230,255))
    g.boss.hp -= dmg; g.boss.flash_until = now + 0.15
    play(SND_HIT); _dmg_msg(g, dmg, (160,220,240))

def do_place_pane(g):
    now = time.time()
    if len(g.glass_panes) >= 4:
        g.add_msg("Max 4 panes!", 0.8, g.mw//2, g.mh//2, (200,180,80)); return
    g.move_cds_end[2] = now + g.cd(2)
    # place pane 3 units ahead of player toward boss
    if g.boss.alive:
        dx = g.boss.x - g.px; dy = g.boss.y - g.py
        d = math.hypot(dx, dy) or 1
        px2 = int(max(2, min(g.mw-3, g.px + (dx/d)*3)))
        py2 = int(max(2, min(g.mh-3, g.py + (dy/d)*1.5)))
    else:
        px2 = int(g.px) + 3; py2 = int(g.py)
    g.glass_panes.append([px2, py2, 30, None])  # 30 hp before shattering
    g.add_msg("Pane placed.", 0.6, g.mw//2, g.mh//2, (160,220,240))

def do_shatter(g):
    # manually shatter the nearest pane for shard splash.
    now = time.time()
    if not g.glass_panes:
        g.add_msg("No panes!", 0.8, g.mw//2, g.mh//2, (200,180,80)); return
    g.move_cds_end[3] = now + g.cd(3)
    # find closest pane to player
    closest = min(g.glass_panes, key=lambda p: math.hypot(g.px-p[0], g.py-p[1]))
    g.glass_panes.remove(closest)
    px2, py2 = closest[0], closest[1]
    # bleed zone lasts 3s
    g.glass_shards.append((px2, py2, now + 3.0))
    # burst particles
    for _ in range(10):
        ang = random.uniform(0, math.pi*2)
        g.particles.append(Particle(px2, py2, math.cos(ang)*4, math.sin(ang)*2,
                                    '+', (160,220,240), 0.5))
    # immediate dmg if boss nearby
    if g.boss.alive and math.hypot(g.boss.x-px2, g.boss.y-py2) < 3:
        dmg = int(20 * g.dmg_mult)
        g.boss.hp -= dmg; g.boss.flash_until = now + 0.3
        _dmg_msg(g, dmg, (160,220,240))

def do_prism_blast(g):
    # fires a beam from the player through every active pane toward the boss.
    now = time.time()
    if not g.glass_panes:
        g.add_msg("No panes to refract!", 0.8, g.mw//2, g.mh//2, (200,180,80)); return
    if not g.boss.alive:
        g.add_msg("No target!", 0.8, g.mw//2, g.mh//2-1, (200,200,100)); return
    g.move_cds_end[4] = now + g.cd(4)
    hit_count = 0
    for pane in g.glass_panes:
        px2, py2 = pane[0], pane[1]
        # fire projectile from pane toward boss
        g.projectiles.append(Projectile(px2, py2, g.boss.x, g.boss.y,
                                         20, '*', (160,230,255),
                                         int(15*g.dmg_mult), 'player'))
        hit_count += 1
    if hit_count:
        g.add_msg(f"PRISM x{hit_count}!", 0.8, g.mw//2, g.mh//2, (160,230,255))

def do_grand_facade(g):
    # ult: place panes around the entire arena border, trapping boss inside ring of glass.
    now = time.time()
    if not g.can_ult():
        g.add_msg("Need <50% HP!", 1.0, g.mw//2, g.mh//2, (255,80,80)); return
    g.move_cds_end[5] = now + g.cd(5)
    g.glass_panes.clear()
    # place 8 panes evenly spaced around the border
    border_pts = []
    for i in range(8):
        ang = i * math.pi / 4
        bx = int(g.mw//2 + math.cos(ang) * (g.mw//2 - 4) * 0.8)
        by = int(g.mh//2 + math.sin(ang) * (g.mh//2 - 3) * 0.7)
        bx = max(2, min(g.mw-3, bx)); by = max(2, min(g.mh-3, by))
        border_pts.append([bx, by, 30, None])
    g.glass_panes = border_pts
    play(SND_ULT)
    g.add_msg("GRAND FACADE!", 1.5, g.mw//2, g.mh//2-1, (180,240,255))


# ── bellwether ────────────────────────────────────────────────────────────────
# summons ghostly followers (up to 5). rally cry sends them charging at the boss.
# dispatch toggles wall mode (followers form a line between player and boss).
# martyrdom sacrifices the lowest-hp follower for burst damage.
# the charge ult: all followers rush simultaneously, each dealing full damage.

_FOLLOWER_SPEED = 5.0
_FOLLOWER_DMG   = 12

def _tick_followers(g, dt, now):
    # called from update_game. advance follower positions and handle attacks.
    for f in g.followers:
        if f[2] == 'dead': continue
        if f[2] == 'charging' and g.boss.alive:
            dx = g.boss.x - f[0]; dy = g.boss.y - f[1]
            d = math.hypot(dx, dy) or 1
            if d < 1.5:
                # melee hit
                dmg = int(_FOLLOWER_DMG * g.dmg_mult)
                g.boss.hp -= dmg; g.boss.flash_until = now + 0.15
                _dmg_msg(g, dmg, (200,180,80))
                f[2] = 'idle'
                f[0] = g.px + random.uniform(-4, 4)
                f[1] = g.py + random.uniform(-2, 2)
            else:
                f[0] += (dx/d) * _FOLLOWER_SPEED * dt
                f[1] += (dy/d) * _FOLLOWER_SPEED * dt * 0.5
        elif f[2] == 'wall':
            # drift toward a position between player and boss
            if g.boss.alive:
                idx = g.followers.index(f)
                n = max(1, len(g.followers))
                t_wall = (idx + 1) / (n + 1)
                wx = g.px + (g.boss.x - g.px) * t_wall
                wy = g.py + (g.boss.y - g.py) * t_wall
                dx = wx - f[0]; dy = wy - f[1]
                d = math.hypot(dx, dy) or 1
                if d > 0.5:
                    f[0] += (dx/d) * _FOLLOWER_SPEED * dt
                    f[1] += (dy/d) * _FOLLOWER_SPEED * dt * 0.5
        elif f[2] == 'idle':
            # loosely orbit the player
            idx = g.followers.index(f)
            ang = now * 0.8 + idx * (math.pi * 2 / max(1, len(g.followers)))
            tx = g.px + math.cos(ang) * 3
            ty = g.py + math.sin(ang) * 1.5
            dx = tx - f[0]; dy = ty - f[1]
            d = math.hypot(dx, dy) or 1
            if d > 0.3:
                f[0] += (dx/d) * _FOLLOWER_SPEED * 0.5 * dt
                f[1] += (dy/d) * _FOLLOWER_SPEED * 0.5 * dt

def do_summon(g):
    now = time.time()
    if len([f for f in g.followers if f[2]!='dead']) >= 5:
        g.add_msg("Max 5 followers!", 0.8, g.mw//2, g.mh//2, (200,180,80)); return
    g.move_cds_end[1] = now + g.cd(1)
    fx = g.px + random.uniform(-3, 3)
    fy = g.py + random.uniform(-1.5, 1.5)
    g.followers.append([fx, fy, 'idle', 0.0, 0.0, 20])
    count = len([f for f in g.followers if f[2]!='dead'])
    g.add_msg(f"Follower summoned ({count}/5)", 0.7, g.mw//2, g.mh//2, (200,180,80))

def do_rally_cry(g):
    # send all idle followers charging at the boss.
    now = time.time()
    if not g.boss.alive:
        g.add_msg("No target!", 0.8, g.mw//2, g.mh//2-1, (200,200,100)); return
    g.move_cds_end[2] = now + g.cd(2)
    rallied = 0
    for f in g.followers:
        if f[2] != 'dead':
            f[2] = 'charging'
            rallied += 1
    if rallied:
        g.add_msg(f"RALLY! ({rallied} charging)", 0.9, g.mw//2, g.mh//2, (220,200,80))
    else:
        g.add_msg("No followers!", 0.8, g.mw//2, g.mh//2, (180,100,80))

def do_dispatch(g):
    # toggle wall mode: followers form a barrier between player and boss.
    now = time.time()
    g.move_cds_end[3] = now + g.cd(3)
    g.wall_mode = not g.wall_mode
    mode = 'wall' if g.wall_mode else 'idle'
    for f in g.followers:
        if f[2] != 'dead':
            f[2] = mode
    g.add_msg("Wall!" if g.wall_mode else "Stand down.", 0.7, g.mw//2, g.mh//2, (200,180,80))

def do_martyrdom(g):
    # sacrifice the lowest-hp follower for burst damage.
    now = time.time()
    alive = [f for f in g.followers if f[2]!='dead']
    if not alive:
        g.add_msg("No followers!", 0.8, g.mw//2, g.mh//2, (180,100,80)); return
    if not g.boss.alive:
        g.add_msg("No target!", 0.8, g.mw//2, g.mh//2-1, (200,200,100)); return
    g.move_cds_end[4] = now + g.cd(4)
    victim = min(alive, key=lambda f: f[5])
    victim[2] = 'dead'
    dmg = int(50 * g.dmg_mult)
    g.boss.hp -= dmg; g.boss.flash_until = now + 0.5; g.boss.stun(0.6)
    _dmg_msg(g, dmg, (220,200,80))
    g.add_msg("MARTYRDOM!", 1.0, g.mw//2, g.mh//2, (220,200,80))
    for _ in range(10):
        ang = random.uniform(0, math.pi*2)
        g.particles.append(Particle(victim[0], victim[1],
                                    math.cos(ang)*5, math.sin(ang)*2.5, '*', (220,200,80), 0.6))
    g.followers = [f for f in g.followers if f[2]!='dead']

def do_the_charge(g):
    # ult: all followers rush boss simultaneously, each dealing full execution damage.
    now = time.time()
    if not g.can_ult():
        g.add_msg("Need <50% HP!", 1.0, g.mw//2, g.mh//2, (255,80,80)); return
    if not g.boss.alive:
        g.add_msg("No target!", 0.8, g.mw//2, g.mh//2-1, (200,200,100)); return
    g.move_cds_end[5] = now + g.cd(5)
    alive = [f for f in g.followers if f[2]!='dead']
    total_dmg = 0
    for f in alive:
        f[2] = 'charging'
        dmg = int(35 * g.dmg_mult)
        total_dmg += dmg
    if total_dmg > 0:
        g.boss.hp -= total_dmg; g.boss.stun(2.0); g.boss.flash_until = now + 1.0
        _dmg_msg(g, total_dmg, (220,200,80))
        g.add_msg(f"THE CHARGE! {total_dmg} dmg", 1.5, g.mw//2, g.mh//2-1, (240,220,80))
    else:
        g.add_msg("No followers to charge!", 0.8, g.mw//2, g.mh//2, (180,100,80))
    play(SND_ULT)


# ── ashwalker ─────────────────────────────────────────────────────────────────
# every tile the player occupies becomes an ember (expires after 2s).
# ignition doubles burn damage on all active tiles for 2s.
# backdraft fires ember particles radially, scattering burning tiles.
# ember step (move 4) is a passive toggle — always active, no cd.
# conflagration ult: reignite ALL charted ember tiles for 4s simultaneously.

_EMBER_DURATION = 2.0   # seconds a tile stays hot
_EMBER_DMG      = 3     # damage per tick to boss standing on ember
_EMBER_TICK     = 0.5   # how often ember deals damage

def _tick_embers(g, dt, now):
    # expire old embers, then deal tick damage to boss if it overlaps any ember.
    g.ember_tiles = {pos: exp for pos, exp in g.ember_tiles.items() if exp > now}
    if not g.boss.alive: return
    bpos = (int(g.boss.x), int(g.boss.y))
    # check a small radius around boss body
    for (ex, ey), exp in list(g.ember_tiles.items()):
        if math.hypot(g.boss.x - ex, g.boss.y - ey) < 1.5:
            if not hasattr(g, '_ember_dmg_next'): g._ember_dmg_next = {}
            key = (ex, ey)
            if now >= g._ember_dmg_next.get(key, 0):
                g._ember_dmg_next[key] = now + _EMBER_TICK
                mult = 2.0 if g.ignition_active else 1.0
                dmg = int(_EMBER_DMG * mult * g.dmg_mult)
                g.boss.hp -= dmg
                g.boss.flash_until = now + 0.05

def _place_ember(g, x, y, now, duration=None):
    dur = duration or _EMBER_DURATION
    if g.ignition_active:
        dur *= 2
    g.ember_tiles[(int(x), int(y))] = now + dur

def do_cinder_strike(g):
    now = time.time()
    if not g.boss.alive or g.dist_boss() > 2.5 + g.hit_range_bonus:
        g.add_msg("Out of range!", 0.8, g.mw//2, g.mh//2-1, (200,200,100)); return
    g.move_cds_end[1] = now + g.cd(1)
    dmg = int(12 * g.dmg_mult)
    # bonus if boss is standing on an ember
    bpos = (int(g.boss.x), int(g.boss.y))
    on_ember = any(math.hypot(g.boss.x-ex, g.boss.y-ey) < 1.5
                   for ex,ey in g.ember_tiles)
    if on_ember:
        dmg = int(dmg * 1.4)
    g.boss.hp -= dmg; g.boss.flash_until = now + 0.2
    play(SND_HIT); _dmg_msg(g, dmg, (220,120,40))
    # leave ember at boss position
    _place_ember(g, g.boss.x, g.boss.y, now)

def do_ignition(g):
    # double the damage and duration of all active embers for 2s.
    now = time.time()
    g.move_cds_end[2] = now + g.cd(2)
    g.ignition_active = True
    g.ignition_until = now + 2.0
    g.add_msg("IGNITION!", 0.8, g.mw//2, g.mh//2, (255,140,40))
    # also refresh all existing ember durations
    for pos in list(g.ember_tiles.keys()):
        g.ember_tiles[pos] = max(g.ember_tiles[pos], now + _EMBER_DURATION)

def do_backdraft(g):
    # scatter embers radially: fire 8 ember projectiles from player position.
    now = time.time()
    g.move_cds_end[3] = now + g.cd(3)
    for i in range(8):
        ang = i * math.pi / 4 + random.uniform(-0.1, 0.1)
        vx = math.cos(ang) * 6; vy = math.sin(ang) * 3
        # create a particle that also plants an ember at its landing spot
        tx = int(max(1, min(g.mw-2, g.px + math.cos(ang)*5)))
        ty = int(max(1, min(g.mh-2, g.py + math.sin(ang)*2.5)))
        _place_ember(g, tx, ty, now)
        g.particles.append(Particle(g.px, g.py, vx, vy, '*', (220,120,40), 0.5))
    g.add_msg("Backdraft!", 0.6, g.mw//2, g.mh//2, (220,120,40))

def do_ember_step(g):
    # move 4 is a manual ember drop at current position (no passive auto-place yet).
    now = time.time()
    _place_ember(g, g.px, g.py, now, duration=_EMBER_DURATION * 2)
    g.add_msg("Ember dropped.", 0.4, g.mw//2, g.mh//2, (180,90,30))

def do_conflagration(g):
    # ult: reignite ALL current ember tiles simultaneously for 4s.
    now = time.time()
    if not g.can_ult():
        g.add_msg("Need <50% HP!", 1.0, g.mw//2, g.mh//2, (255,80,80)); return
    g.move_cds_end[5] = now + g.cd(5)
    if not g.ember_tiles:
        g.add_msg("No embers on the map!", 1.0, g.mw//2, g.mh//2, (200,120,60)); return
    tile_count = len(g.ember_tiles)
    # reignite every tile for 4s
    for pos in list(g.ember_tiles.keys()):
        g.ember_tiles[pos] = now + 4.0
    # also lay embers on a ring around player for extra area
    for i in range(12):
        ang = i * math.pi / 6
        tx = int(max(1, min(g.mw-2, g.px + math.cos(ang)*4)))
        ty = int(max(1, min(g.mh-2, g.py + math.sin(ang)*2)))
        _place_ember(g, tx, ty, now, 4.0)
        g.particles.append(Particle(g.px, g.py,
                                    math.cos(ang)*5, math.sin(ang)*2.5,
                                    chr(9733), (255,140,40), 0.7))
    play(SND_ULT)
    g.add_msg(f"CONFLAGRATION! {tile_count} tiles", 1.5, g.mw//2, g.mh//2-1, (255,140,40))

def _dmg_msg(g, dmg, clr):
    g.add_msg(f"-{dmg}",0.7,int(g.boss.x),int(g.boss.y)-1,clr)

# update
def update_game(g, dt):
    now=time.time()
    if g.game_over or g.victory: return

    # 2 second idle resets combo back to state 0 (hit 1)
    if g.combo_state > 0 and now - g.combo_last_hit >= 2.0:
        g.combo_state = 0

    # dash trail
    g.dash_trail=[(x,y,t) for x,y,t in g.dash_trail if now-t<0.3]

    # particles
    for p in g.particles: p.update(dt)
    g.particles=[p for p in g.particles if p.alive()]

    # ripples
    g.ripples=[r for r in g.ripples if r.alive()]

    # strings (marionette)
    g.strings=[s for s in g.strings if s.alive()]

    # undertaker: expire parry window after 0.8s
    if g.cls_name=="undertaker" and g.parry_window and now - g.parry_window_start >= 0.8:
        g.parry_window = False
        g.add_msg("Parry missed.", 0.4, g.mw//2, g.mh//2, (120,80,160))

    # bellwether: tick followers every frame
    if g.cls_name=="bellwether":
        _tick_followers(g, dt, now)

    # ashwalker: auto-place ember on current tile, tick ember damage, expire ignition
    if g.cls_name=="ashwalker":
        _place_ember(g, g.px, g.py, now)
        _tick_embers(g, dt, now)
        if g.ignition_active and now >= g.ignition_until:
            g.ignition_active = False

    # glasswright: expire shards, apply shard damage if boss walks over them
    if g.cls_name=="glasswright":
        g.glass_shards = [(sx,sy,exp) for sx,sy,exp in g.glass_shards if exp>now]
        if g.boss.alive:
            for sx,sy,_ in g.glass_shards:
                if math.hypot(g.boss.x-sx, g.boss.y-sy) < 1.5:
                    if not hasattr(g,'_shard_dmg_next'): g._shard_dmg_next = {}
                    key=(sx,sy)
                    if now >= g._shard_dmg_next.get(key,0):
                        g._shard_dmg_next[key]=now+0.5
                        dmg=int(5*g.dmg_mult)
                        g.boss.hp-=dmg; g.boss.flash_until=now+0.05
    if g.redirect_ready and now>g.redirect_expires: g.redirect_ready=False

    # quicksand/terrain walls
    g.quicksand_zones=[(x,y,r,e) for x,y,r,e in g.quicksand_zones if now<e]
    g.terrain_walls=[(x,y,e) for x,y,e in g.terrain_walls if now<e]

    # char fire
    g.char_fire={k:v for k,v in g.char_fire.items() if now<v}

    # revenant trail
    if g.rev_ult_active:
        if now>=g.rev_ult_end: g.rev_ult_active=False
        else:
            g.char_fire[(int(g.px),int(g.py))]=now+1.5

    # afterimages
    for ai in g.afterimages:
        if ai.should_explode():
            ai.exploded=True
            if g.boss.alive and math.hypot(g.boss.x-ai.x,g.boss.y-ai.y)<=3:
                dmg=int(15*g.dmg_mult); g.boss.hp-=dmg
                g.boss.flash_until=now+0.2; _dmg_msg(g,dmg,(255,180,0))
            for _ in range(6):
                ang=random.uniform(0,math.pi*2)
                g.particles.append(Particle(ai.x,ai.y,math.cos(ang)*5,math.sin(ang)*2,'.', (255,200,50),0.3))
    g.afterimages=[ai for ai in g.afterimages if ai.alive()]

    # gravemarks
    for gm in g.gravemarks:
        if gm.should_pull():
            gm.pulled=True
            if g.boss.alive and math.hypot(g.boss.x-gm.x,g.boss.y-gm.y)<=6:
                dmg=int(30*g.dmg_mult); g.boss.hp-=dmg
                g.boss.flash_until=now+0.4
                d=math.hypot(gm.x-g.boss.x,gm.y-g.boss.y) or 1
                g.boss.x=max(2,min(g.mw-4,g.boss.x+(gm.x-g.boss.x)/d*3))
                g.boss.y=max(2,min(g.mh-3,g.boss.y+(gm.y-g.boss.y)/d*1.5))
                _dmg_msg(g,dmg,(180,50,255))
    g.gravemarks=[gm for gm in g.gravemarks if gm.alive()]

    # cartographer charted tile damage
    if g.boss.alive:
        bt=(int(g.boss.x),int(g.boss.y))
        if bt in g.charted and not bt in g.char_fire:
            if random.random()<0.05:  # 5% per frame ~3 dps
                g.boss.hp-=3; g.boss.flash_until=now+0.1

    # landmines
    for m in g.landmines:
        if m.alive() and not m.triggered and g.boss.alive:
            if math.hypot(g.boss.x-m.x,g.boss.y-m.y)<1.5: m.trigger()
        if m.should_explode():
            m.exploded=True
            if g.boss.alive and math.hypot(g.boss.x-m.x,g.boss.y-m.y)<=2.5:
                dmg=int(40*g.dmg_mult); g.boss.hp-=dmg
                g.boss.flash_until=now+0.5; _dmg_msg(g,dmg,(220,160,30))
            for _ in range(12):
                ang=random.uniform(0,math.pi*2)
                g.particles.append(Particle(m.x,m.y,math.cos(ang)*8,math.sin(ang)*4,'*',(220,160,30),0.5))
    g.landmines=[m for m in g.landmines if m.alive()]

    # fissure rings
    for ring in g.fissure_rings:
        if ring.alive() and not ring.hit_boss:
            r=ring.max_r*ring.prog()
            if g.boss.alive and abs(math.hypot(g.boss.x-ring.cx,g.boss.y-ring.cy)-r)<3:
                ring.hit_boss=True; dmg=int(50*g.dmg_mult)
                g.boss.hp-=dmg; g.boss.stun(3.0); g.boss.flash_until=now+0.6
                _dmg_msg(g,dmg,(255,120,30))
                g.add_msg("SIX FEET UNDER!",1.5,g.mw//2,g.mh//2,(220,120,40))
    g.fissure_rings=[r for r in g.fissure_rings if r.alive()]
    if g.gd_ult_active and now-g.gd_ult_start>=3.0: g.gd_ult_active=False

    # mirror clone
    if g.map_key=="mirror" and g.boss.alive:
        if g.mirror_clone_hp<=0:
            g.mirror_clone_regen=max(g.mirror_clone_regen,now+5.0)
        if now>=g.mirror_clone_regen and g.mirror_clone_hp<=0:
            g.mirror_clone_hp=200

    # projectiles
    new_projs=[]
    for proj in g.projectiles:
        proj.update(dt)
        px2,py2=int(proj.x),int(proj.y)
        if px2<0 or px2>=g.mw or py2<0 or py2>=g.mh: continue
        hit=False
        if proj.owner=='player' and g.boss.alive:
            if g.boss.body_dist(proj.x, proj.y)<2.0:
                dmg=proj.dmg
                # stonewarden armor
                if g.boss.key=="boss2" and g.boss.armor>0:
                    absorbed_armor=min(dmg,g.boss.armor)
                    g.boss.armor-=absorbed_armor; dmg-=absorbed_armor
                    if g.boss.armor<=0 and not g.boss.phase2:
                        g.boss.phase2=True
                        g.add_msg("SHELL CRACKED!",1.5,g.mw//2,g.mh//2,(255,200,50))
                if dmg>0: g.boss.hp-=dmg; g.boss.flash_until=now+0.25; _dmg_msg(g,int(dmg),proj.clr)
                # marionette string reflect
                if g.strings:
                    reflect=int(proj.dmg*0.3*len(g.strings))
                    g.boss.hp-=reflect
                for _ in range(4):
                    ang=random.uniform(0,math.pi*2)
                    g.particles.append(Particle(proj.x,proj.y,math.cos(ang)*4,math.sin(ang)*2,'.',proj.clr,0.25))
                hit=True
        if not hit: new_projs.append(proj)
    g.projectiles=new_projs

    # wizard ultimate
    if g.ult_active:
        if now-g.ult_start>=g.ult_dur:
            g.ult_active=False
            if g.ult_proc:
                try: g.ult_proc.terminate()
                except: pass
        else:
            if now-g.ult_dmg_tick>=0.5:
                g.ult_dmg_tick=now
                if g.boss.alive:
                    g.boss.hp-=int(20*g.dmg_mult); g.boss.flash_until=now+0.2
                    _dmg_msg(g,int(20*g.dmg_mult),(255,50,200))
            if g.boss.alive:
                d=g.dist_boss() or 1
                g.boss.x=max(2,min(g.mw-4,g.boss.x+(g.px-g.boss.x)/d*3*dt))
                g.boss.y=max(2,min(g.mh-3,g.boss.y+(g.py-g.boss.y)/d*1.5*dt))

    # siphon: expire hijack window after 1.5s
    if g.hijack_active and now - g.hijack_start >= 1.5:
        g.hijack_active = False
        g.add_msg("Hijack missed.", 0.6, g.mw//2, g.mh//2, (140, 100, 90))

    # clocktower: sweep the clock hand every 20s, 3s warning arc first
    if g.map_key == "clocktower":
        geo = g.geo
        if not hasattr(geo, 'clock_last_sweep'): geo.clock_last_sweep = now
        if not hasattr(geo, 'clock_sweep_active'): geo.clock_sweep_active = False
        if not hasattr(geo, 'clock_sweep_start'): geo.clock_sweep_start = 0.0
        if not geo.clock_sweep_active and now - geo.clock_last_sweep >= 20.0:
            geo.clock_sweep_active = True
            geo.clock_sweep_start = now
            g.add_msg("Clock hand sweeping!", 1.2, g.mw//2, 2, (180,160,80))
        if geo.clock_sweep_active:
            sweep_age = now - geo.clock_sweep_start
            if sweep_age >= 3.0:  # actual sweep after 3s warning
                # hand sweeps a full-width horizontal band at boss y level
                sweep_y = int(g.boss.y if g.boss.alive else g.mh//2)
                if abs(g.py - sweep_y) < 1.5:
                    if not g.is_stunned() and now > g.gd_invincible_until:
                        g.take_damage(40)
            if sweep_age >= 4.0:
                geo.clock_sweep_active = False
                geo.clock_last_sweep = now

    # reliquary: rise water level every 45s
    if g.map_key == "reliquary":
        geo = g.geo
        if not hasattr(geo, 'water_last_rise'): geo.water_last_rise = now
        if not hasattr(geo, 'water_level'): geo.water_level = 0
        if not hasattr(geo, 'chests'): geo.chests = []
        if geo.water_level < 2 and now - geo.water_last_rise >= 45.0:
            geo.water_level += 1
            geo.water_last_rise = now
            g.add_msg(f"Water rises! Level {geo.water_level}/2", 1.5, g.mw//2, 2, (60,120,200))
        # water movement penalty
        # player is in water when their Y is at or below the water surface row.
        # water_top = mh-2 - water_rows + 1 where water_rows = water_level * mh//3
        if geo.water_level > 0:
            wrows = min(g.mh-4, max(1, geo.water_level * (g.mh//3)))
            wtop = g.mh-2 - wrows + 1
            in_water = g.py >= wtop
        else:
            in_water = False
        if in_water:
            g.speed_override = g.base_speed * 0.7
        else:
            g.speed_override = None
        # chest interaction: stand on chest for 1s to open
        for ch in geo.chests:
            if not ch[2] and math.hypot(g.px - ch[0], g.py - ch[1]) < 1.0:
                if not hasattr(g, 'chest_stand_start') or g.chest_stand_start is None:
                    g.chest_stand_start = now
                elif now - g.chest_stand_start >= 1.0:
                    effect = random.choice(['speed','damage','heal','blind'])
                    ch[2] = True; ch[3] = effect
                    g.chest_stand_start = None
                    if effect == 'heal':
                        g.hp = min(g.max_hp, g.hp + 30)
                        g.add_msg("Chest: +30 HP!", 1.0, g.mw//2, g.mh//2, (100,220,100))
                    elif effect == 'damage':
                        g.dmg_mult *= 1.3
                        g.add_msg("Chest: +30% damage!", 1.0, g.mw//2, g.mh//2, (220,180,60))
                    elif effect == 'speed':
                        g.base_speed += 3
                        g.add_msg("Chest: +speed!", 1.0, g.mw//2, g.mh//2, (100,200,220))
                    elif effect == 'blind':
                        g.boss.stun(2.0)
                        g.add_msg("Chest: Boss blinded!", 1.0, g.mw//2, g.mh//2, (220,220,80))
            else:
                if hasattr(g, 'chest_stand_start'): g.chest_stand_start = None

    # spire: spawn spike warnings every 12s
    if g.map_key == "spire":
        geo = g.geo
        if not hasattr(geo, 'spike_sites'): geo.spike_sites = []
        if not hasattr(geo, 'spike_last'): geo.spike_last = now
        if now - geo.spike_last >= 12.0:
            geo.spike_last = now
            sx = random.randint(3, g.mw-4)
            sy = random.randint(2, g.mh-3)
            geo.spike_sites.append([sx, sy, now])
        # fire spikes that have warned for 2s
        new_sites = []
        for site in geo.spike_sites:
            sx, sy, sborn = site
            if now - sborn >= 2.0:
                if math.hypot(g.px - sx, g.py - sy) < 1.5:
                    if not g.is_stunned() and now > g.gd_invincible_until:
                        g.take_damage(50)
                for _ in range(6):
                    ang = random.uniform(0, math.pi*2)
                    g.particles.append(Particle(sx, sy,
                        math.cos(ang)*4, math.sin(ang)*2, '*', (180,80,220), 0.4))
            else:
                new_sites.append(site)
        geo.spike_sites = new_sites
        # boss also wraps on spire map
        if g.boss.alive:
            g.boss.x = g.boss.x % g.mw
            g.boss.y = g.boss.y % g.mh

    # siphon: expire null field
    if g.siphon_null_field and now >= g.siphon_null_field[2]:
        g.siphon_null_field = None

    # siphon: expire leech
    if g.siphon_leech_active and now >= g.siphon_leech_expires:
        g.siphon_leech_active = False

    # boss update
    if not g.boss.alive:
        return
    if g.boss.hp<=0:
        g.boss.alive=False; g.victory=True
        coins=int(BOSS_DATA[g.boss_key]["coins"]*g.coin_mult)
        g.earned_coins=coins
        return

    if not g.boss.is_stunned() and not g.boss.is_submerged():
        # movement
        if now-g.boss.last_move>=g.boss.move_interval:
            g.boss.last_move=now
            # boss-specific movement
            if g.boss.key=="boss3":  # tide caller drift
                drift_x=math.sin(now*0.5)*0.5
                g.px=max(1,min(g.mw-2,g.px+drift_x))
            if g.dist_boss()>g.boss.hit_range:
                dx=g.px-g.boss.x; dy=g.py-g.boss.y
                d=math.hypot(dx,dy) or 1
                spd=1.8*(1+0.3*(g.size_mult-1))
                if g.boss.key=="boss3":  # tide caller: submerge + water jets
                    if random.random()<0.05:
                        g.boss.submerged_until=now+2.0
                    # shoot water jet in random cardinal direction every 4s
                    if now-g.boss.last_jet>=4.0:
                        g.boss.last_jet=now
                        dirs=[(1,0),(-1,0),(0,1),(0,-1)]
                        dx2,dy2=random.choice(dirs)
                        g.boss.water_jets.append([int(g.boss.x),int(g.boss.y),dx2,dy2,now,1.5])
                g.boss.x=max(2,min(g.mw-4,g.boss.x+(dx/d)*spd))
                g.boss.y=max(2,min(g.mh-3,g.boss.y+(dy/d)*spd*0.5))
                # boss2 phase2 charge
                if g.boss.key=="boss2" and g.boss.phase2 and random.random()<0.1:
                    g.boss.charge_target=(g.px,g.py); g.boss.charge_start=now

        # stonewarden charge
        if g.boss.key=="boss2" and g.boss.charge_target and g.boss.charge_start:
            if now-g.boss.charge_start<0.5:
                cx,cy=g.boss.charge_target
                dx=cx-g.boss.x; dy=cy-g.boss.y; d=math.hypot(dx,dy) or 1
                g.boss.x=max(2,min(g.mw-4,g.boss.x+(dx/d)*8*dt))
                g.boss.y=max(2,min(g.mh-3,g.boss.y+(dy/d)*4*dt))
            else:
                g.boss.charge_target=None; g.boss.charge_start=None

        # boss5 pale architect: raises walls periodically and fires cage traps.
        # it phases through its own architect_walls but the player cannot.
        if g.boss.key=="boss5":
            if now - g.boss.last_wall_raise >= 12.0:
                g.boss.last_wall_raise = now
                # raise a 3-tile wall segment between boss and player
                mx = (int(g.boss.x) + g.px) // 2
                my = (int(g.boss.y) + g.py) // 2
                seg = [(mx+dx, my) for dx in range(-1, 2)]
                g.boss.architect_walls.append(seg)
                if len(g.boss.architect_walls) > 6:
                    g.boss.architect_walls.pop(0)
                g.add_msg("Schematic raised!", 0.8, g.mw//2, g.mh//2-2, (200,210,230))
            # cage trap lands: deal damage and spawn visual
            if g.boss.cage_trap:
                cx2, cy2, cage_born = g.boss.cage_trap
                if now - cage_born >= 1.5:
                    if math.hypot(g.px - cx2, g.py - cy2) < 2:
                        if not g.is_stunned() and now > g.gd_invincible_until:
                            g.take_damage(int(g.boss.damage * 1.2))
                        g.add_msg("CAGED!", 1.0, g.mw//2, g.mh//2, (200,210,230))
                    g.boss.cage_trap = None

        # boss6 sovereign hound: hunt/rest phase loop with pounce.
        if g.boss.key=="boss6":
            in_hunt = now < g.boss.hunt_until
            in_rest = not in_hunt and now < g.boss.rest_until
            # phase transitions
            if not in_hunt and not in_rest:
                if g.boss.hunt_until > g.boss.rest_until:
                    # just finished hunt, start rest
                    g.boss.rest_until = now + 8.0
                    g.boss.hunt_until = 0
                    # howl: spawn 2 puppies at random positions
                    for _ in range(2):
                        px2 = random.randint(5, g.mw-6)
                        py2 = random.randint(3, g.mh-4)
                        g.boss.hound_puppies.append([float(px2), float(py2), 30])
                    g.add_msg("HOWL!", 1.0, g.mw//2, g.mh//2-2, (80,50,120))
                else:
                    # just finished rest, start hunt
                    g.boss.hunt_until = now + 15.0
                    g.boss.rest_until = 0
                    g.boss.hound_puppies.clear()
                    g.add_msg("HUNT!", 0.8, g.mw//2, g.mh//2-2, (120,60,180))
            # pounce logic: telegraph for 2s then lunge in hunt phase
            if in_hunt and g.boss.hound_pounce is None and random.random() < 0.008:
                g.boss.hound_pounce = {
                    'start': now, 'origin': (g.boss.x, g.boss.y),
                    'target': (g.px, g.py), 'landed': False
                }
                g.add_msg("Pouncing...", 0.8, int(g.boss.x), int(g.boss.y)-2, (120,60,180))
            if g.boss.hound_pounce:
                p = g.boss.hound_pounce
                age = now - p['start']
                if age < 2.0:
                    # telegraph: nothing happens, boss crouches (visual only via color)
                    pass
                elif not p['landed']:
                    # lunge at extreme speed toward target
                    progress = min(1.0, (age - 2.0) / 0.3)
                    ox, oy = p['origin']
                    tx2, ty2 = p['target']
                    g.boss.x = ox + (tx2 - ox) * progress
                    g.boss.y = oy + (ty2 - oy) * progress
                    if progress >= 1.0:
                        p['landed'] = True
                        # hit check
                        if math.hypot(g.px - tx2, g.py - ty2) < 2.0:
                            if not g.is_stunned() and now > g.gd_invincible_until:
                                g.take_damage(int(g.boss.damage * 1.5))
                                # rebound: shoot past the player in the same direction
                                dx_rb = tx2 - p['origin'][0]; dy_rb = ty2 - p['origin'][1]
                                d_rb = math.hypot(dx_rb, dy_rb) or 1
                                p['rebound_target'] = (
                                    max(2, min(g.mw-4, tx2 + (dx_rb/d_rb)*8)),
                                    max(2, min(g.mh-3, ty2 + (dy_rb/d_rb)*4))
                                )
                                p['rebound_start'] = now
                            else:
                                # miss: stun the hound briefly
                                g.boss.stun(1.5)
                                g.add_msg("MISSED!", 1.0, g.mw//2, g.mh//2, (180,140,220))
                        else:
                            g.boss.stun(1.5)
                elif p.get('rebound_target'):
                    # execute the rebound slide
                    rb_progress = min(1.0, (now - p['rebound_start']) / 0.25)
                    ox2, oy2 = p['origin']
                    rtx, rty = p['rebound_target']
                    g.boss.x = tx2 + (rtx - tx2) * rb_progress
                    g.boss.y = ty2 + (rty - ty2) * rb_progress
                    if rb_progress >= 1.0:
                        g.boss.hound_pounce = None
                else:
                    g.boss.hound_pounce = None
            # puppies drift toward player and chip damage
            for pup in g.boss.hound_puppies[:]:
                if pup[2] <= 0:
                    g.boss.hound_puppies.remove(pup)
                    continue
                dx2 = g.px - pup[0]; dy2 = g.py - pup[1]
                d2 = math.hypot(dx2, dy2) or 1
                pup[0] += (dx2/d2) * 1.5 * dt
                pup[1] += (dy2/d2) * 0.75 * dt
                if math.hypot(g.px - pup[0], g.py - pup[1]) < 1.5 and random.random() < 0.02:
                    if not g.is_stunned() and now > g.gd_invincible_until:
                        g.take_damage(5)

        # boss7 liminal: two hp bars, cross-healing, convergence beams, merge attempt.
        if g.boss.key=="boss7":
            # track hp at start of frame to detect damage dealt this tick.
            # used to credit merge_interrupt_dmg without patching every damage callsite.
            liminal_hp_before = g.boss.light_hp + g.boss.void_hp
            # sync combined hp for death check
            g.boss.hp = g.boss.light_hp + g.boss.void_hp
            # convergence beams every 5s: two beams from opposite sides meeting in the middle
            if now - g.boss.last_convergence >= 5.0 and not g.boss.merge_active:
                g.boss.last_convergence = now
                safe_gap = g.mw // 2
                g.boss.convergence_beams.append([0, g.py, safe_gap-3, g.py, now, 2.0])
                g.boss.convergence_beams.append([g.mw-1, g.py, safe_gap+3, g.py, now, 2.0])
            # expire old beams
            g.boss.convergence_beams = [b for b in g.boss.convergence_beams if now-b[4]<b[5]]
            # beam damage
            for beam in g.boss.convergence_beams:
                bx1,by1,bx2,by2,bborn,bdur = beam
                bprog = (now - bborn) / bdur
                # beam extends from edges toward center over first half of duration
                if bprog > 0.3:  # give player time to dodge
                    tip_x = int(bx1 + (bx2-bx1) * min(1.0,(bprog-0.3)/0.4))
                    if abs(g.py - by1) < 1 and (min(bx1,tip_x) <= g.px <= max(bx1,tip_x)):
                        if not g.is_stunned() and now > g.gd_invincible_until:
                            g.take_damage(int(g.boss.damage * 0.4))
            # merge attempt below 40% total hp
            total_hp = g.boss.light_hp + g.boss.void_hp
            if total_hp < g.boss.max_hp * 0.4 and not g.boss.merge_active and random.random() < 0.001:
                g.boss.merge_active = True
                g.boss.merge_start = now
                g.boss.merge_interrupt_dmg = 0
                g.add_msg("MERGE INCOMING! Deal 80 dmg to interrupt!", 2.0,
                          g.mw//2, g.mh//2-3, (200,100,255))
            # credit any damage dealt this frame toward merge interrupt
            liminal_hp_after = g.boss.light_hp + g.boss.void_hp
            if g.boss.merge_active and liminal_hp_after < liminal_hp_before:
                g.boss.merge_interrupt_dmg += liminal_hp_before - liminal_hp_after

            # merge in progress
            if g.boss.merge_active:
                if g.boss.merge_interrupt_dmg >= 80:
                    g.boss.merge_active = False
                    g.add_msg("Merge interrupted!", 1.5, g.mw//2, g.mh//2, (150,255,150))
                elif now - g.boss.merge_start >= 5.0:
                    # merge completed: heal to 60% and speed boost
                    g.boss.light_hp = int(g.boss.max_hp * 0.3)
                    g.boss.void_hp  = int(g.boss.max_hp * 0.3)
                    g.boss.hp = g.boss.light_hp + g.boss.void_hp
                    g.boss.merge_active = False
                    g.boss.hit_cd = max(0.4, g.boss.hit_cd * 0.5)
                    g.add_msg("MERGED! The Liminal is enraged!", 2.0,
                              g.mw//2, g.mh//2, (200,100,255))

        # boss4 rhythm system.
        # the beat_interval shrinks as hp falls: at full hp it is 2.0s,
        # at 50% hp it is 1.4s, at 0 hp it would be 0.6s. this creates
        # a natural crescendo as the fight progresses.
        # all attacks by the conductor can only start on a beat boundary,
        # making the rhythm learnable and giving the player a window to act.
        if g.boss.key=="boss4":
            hp_frac = g.boss.hp / max(1, g.boss.max_hp)
            g.boss.beat_interval = 0.6 + 1.4 * hp_frac  # 2.0s at full, ~0.6s near death

            g.boss.beat_phase = (now - g.boss.last_beat) / g.boss.beat_interval
            if g.boss.beat_phase >= 1.0:
                g.boss.last_beat = now
                g.boss.beat_phase = 0.0
                # on every beat: flag that a hit can begin this beat
                g.boss.beat_pending_hit = True

                # turrets spawn once when hp drops below 70%
                if not g.boss.turrets_spawned and g.boss.hp < g.boss.max_hp * 0.7:
                    g.boss.turrets_spawned = True
                    for tx2, ty2 in [(10, 5), (g.mw-10, 5), (10, g.mh-5), (g.mw-10, g.mh-5)]:
                        g.boss.turrets.append([tx2, ty2, 'violin', 30, 0])

                # all turrets fire simultaneously on the beat (not individually timed).
                # this makes dodging predictable: you know exactly when shots come.
                for turret in g.boss.turrets:
                    if turret[2] != 'dead':
                        turret[4] = now
                        g.projectiles.append(
                            Projectile(turret[0], turret[1], g.px, g.py, 10, chr(9835),
                                       (200, 200, 80), 10, 'boss'))

                # trill chance: only when hp below 50%, 30% chance per beat.
                # a trill is a multi-phase move: advance -> vibrate -> retreat -> slam.
                # the boss closes in fast, buzzes the player with rapid small hits,
                # then backs off and lunges for one heavy strike.
                if (not g.boss.trill_active
                        and g.boss.hp < g.boss.max_hp * 0.5
                        and g.boss.hit_windup is None
                        and random.random() < 0.30):
                    g.boss.trill_active = True
                    g.boss.trill_phase = 'advance'
                    g.boss.trill_start = now
                    g.boss.trill_origin = (g.boss.x, g.boss.y)
                    g.boss.trill_target = (g.px, g.py)
                    g.boss.trill_hit_count = 0
                    g.boss.trill_last_tick = now
                    g.add_msg("TRILL!", 0.6, g.mw//2, g.mh//2 - 2, (255, 220, 60))

            # trill phase state machine.
            # each phase has a fixed duration. transitions happen automatically.
            if g.boss.trill_active:
                phase_age = now - g.boss.trill_start
                b = g.boss

                if b.trill_phase == 'advance':
                    # glide toward the locked target position
                    tx2, ty2 = b.trill_target
                    progress = min(1.0, phase_age / b.trill_advance_dur)
                    ox, oy = b.trill_origin
                    b.x = ox + (tx2 - ox) * progress
                    b.y = oy + (ty2 - oy) * progress
                    if phase_age >= b.trill_advance_dur:
                        b.trill_phase = 'vibrate'
                        b.trill_start = now
                        b.trill_last_tick = now

                elif b.trill_phase == 'vibrate':
                    # buzz back and forth in place and deal rapid small hits.
                    # vibrate frequency doubles the beat interval speed.
                    vib_freq = 8.0
                    vib_amp_x = 1.2
                    vib_amp_y = 0.5
                    tx2, ty2 = b.trill_target
                    b.x = tx2 + math.sin(now * vib_freq * math.pi) * vib_amp_x
                    b.y = ty2 + math.cos(now * vib_freq * math.pi) * vib_amp_y
                    # deal a small tick of damage every 0.25s while vibrating
                    tick_cd = 0.25
                    if now - b.trill_last_tick >= tick_cd:
                        b.trill_last_tick = now
                        b.trill_hit_count += 1
                        if g.dist_boss() < b.hit_range + 1:
                            dmg = max(1, int(b.damage * 0.25))
                            if not g.is_stunned() and now > g.gd_invincible_until and not g.rev_ult_active:
                                g.take_damage(dmg)
                            # spawn brief note particles so the player can see each tick
                            for _ in range(3):
                                ang = random.uniform(0, math.pi * 2)
                                g.particles.append(
                                    Particle(b.x, b.y,
                                             math.cos(ang) * 4, math.sin(ang) * 2,
                                             chr(9835), (255, 230, 80), 0.4))
                    if phase_age >= b.trill_vibrate_dur:
                        b.trill_phase = 'retreat'
                        b.trill_start = now
                        b.trill_origin = (b.x, b.y)  # retreat from current vibrate position

                elif b.trill_phase == 'retreat':
                    # pull back to roughly where the boss started the whole trill,
                    # giving the player a visual cue that the slam is coming.
                    progress = min(1.0, phase_age / b.trill_retreat_dur)
                    ox2, oy2 = b.trill_origin
                    ex = g.boss.x + (ox2 - g.boss.x)  # just interpolate back a bit
                    # actually store retreat destination at start of phase
                    # we use trill_origin as start, aim for 6 units behind boss relative to player
                    dx2 = b.x - g.px; dy2 = b.y - g.py
                    d2 = math.hypot(dx2, dy2) or 1
                    rx = b.trill_origin[0] + (dx2 / d2) * 6
                    ry = b.trill_origin[1] + (dy2 / d2) * 3
                    rx = max(2, min(g.mw - 4, rx))
                    ry = max(2, min(g.mh - 3, ry))
                    b.x = b.trill_origin[0] + (rx - b.trill_origin[0]) * progress
                    b.y = b.trill_origin[1] + (ry - b.trill_origin[1]) * progress
                    if phase_age >= b.trill_retreat_dur:
                        b.trill_phase = 'slam'
                        b.trill_start = now
                        b.trill_origin = (b.x, b.y)
                        b.trill_target = (g.px, g.py)  # re-lock onto current player pos
                        g.add_msg("SLAM!", 0.5, g.mw//2, g.mh//2 - 2, (255, 100, 50))

                elif b.trill_phase == 'slam':
                    # lunge at high speed toward the re-locked player position and deal full damage
                    progress = min(1.0, phase_age / b.trill_slam_dur)
                    ox2, oy2 = b.trill_origin
                    tx2, ty2 = b.trill_target
                    b.x = ox2 + (tx2 - ox2) * progress
                    b.y = oy2 + (ty2 - oy2) * progress
                    # check hit at end of slam
                    if phase_age >= b.trill_slam_dur:
                        if math.hypot(g.px - b.x, g.py - b.y) < b.hit_range:
                            if not g.is_stunned() and now > g.gd_invincible_until and not g.rev_ult_active:
                                # full damage, slightly amplified as a reward for surviving the trill
                                g.take_damage(int(b.damage * 1.25))
                        b.trill_active = False
                        b.trill_phase = None
                        b.last_hit = now  # reset hit cooldown so it doesnt immediately attack again
                        b.flash_until = now + 0.4
                        for _ in range(10):
                            ang = random.uniform(0, math.pi * 2)
                            g.particles.append(
                                Particle(b.x, b.y,
                                         math.cos(ang) * 6, math.sin(ang) * 3,
                                         chr(9835), lerp((220, 180, 40), (255, 230, 80), random.random()), 0.5))

        # hit logic.
        # for boss4 the hollow conductor, a hit can only begin when beat_pending_hit
        # is true (i.e. right on a beat boundary) and no trill is already running.
        # all other bosses use the normal cooldown-based approach.
        can_start_hit = (g.boss.hit_windup is None and now - g.boss.last_hit >= g.boss.hit_cd)
        if g.boss.key == "boss4":
            can_start_hit = (can_start_hit
                             and g.boss.beat_pending_hit
                             and not g.boss.trill_active)
            g.boss.beat_pending_hit = False  # consume the pending flag regardless

        if can_start_hit:
            if g.dist_boss() <= g.boss.hit_range + 2:
                g.boss.hit_windup = now
                g.boss.hit_target = (g.px, g.py)
                g.boss.hit_landing = now + 2.5
                # trigger per-boss attack animation
                anim_map = {'boss1': 'slam', 'boss2': 'stomp', 'boss3': 'surge', 'boss4': 'baton'}
                g.boss.atk_anim = anim_map.get(g.boss.key, 'slam')
                g.boss.atk_anim_start = now

        if g.boss.hit_windup is not None:
            if now<g.boss.hit_windup+2.0:
                g.boss.hit_target=(g.px,g.py)
            if now>=g.boss.hit_landing:
                if g.boss.hit_target:
                    if math.hypot(g.px-g.boss.hit_target[0],g.py-g.boss.hit_target[1])<1.5:
                        if g.parry_window and g.cls_name=="undertaker":
                            # undertaker parry: full counter-reflect + stun
                            g.parry_window = False
                            counter_dmg = int(g.boss.damage * 2.0 * g.dmg_mult)
                            g.boss.hp -= counter_dmg
                            g.boss.stun(1.5); g.boss.flash_until = now + 0.6
                            _dmg_msg(g, counter_dmg, (180,80,240))
                            g.add_msg("PARRY COUNTER!", 1.2, g.mw//2, g.mh//2, (180,80,240))
                            # bonus: add a sentence stack from the counter
                            g.sentence_stacks += 1
                            g.total_sentences += 1
                            if g.sentence_stacks >= 5:
                                _do_execution_burst(g, now)
                        elif g.hijack_active:
                            # siphon hijack: absorb the hit as a stored charge
                            g.hijack_active = False
                            if len(g.siphon_charges) < 3:
                                ch_type = "melee"
                                g.siphon_charges.append({"type": ch_type, "value": g.boss.damage})
                                g.add_msg(f"HIJACKED! ({len(g.siphon_charges)}/3 charges)",
                                          1.2, g.mw//2, g.mh//2, (80, 230, 200))
                                # partial reflect: send 50% back immediately
                                reflect_dmg = int(g.boss.damage * 0.5 * g.dmg_mult)
                                g.boss.hp -= reflect_dmg
                                g.boss.flash_until = now + 0.4
                                _dmg_msg(g, reflect_dmg, (80, 200, 180))
                        elif g.redirect_ready:
                            # marionette redirect
                            g.redirect_ready=False
                            g.boss.hp-=g.boss.damage*2
                            g.boss.flash_until=now+0.5
                            _dmg_msg(g,g.boss.damage*2,(255,100,200))
                            g.add_msg("REDIRECTED!",1.0,g.mw//2,g.mh//2,(220,100,180))
                        elif not g.is_stunned() and now>g.gd_invincible_until and not g.rev_ult_active:
                            g.take_damage(g.boss.damage)
                g.boss.hit_windup=None; g.boss.hit_target=None
                g.boss.hit_landing=None; g.boss.last_hit=now

    # boss3 water jets: extend each frame
    new_jets=[]
    for jet in g.boss.water_jets if g.boss.alive else []:
        jx,jy,jdx,jdy,jborn,jdur=jet
        if now-jborn<jdur:
            # extend jet tip outward
            tip_len=int((now-jborn)/jdur * (g.mw//2))
            tip_x=jx+jdx*tip_len
            tip_y=jy+jdy*tip_len
            if math.hypot(g.px-tip_x,g.py-tip_y)<2.0 or                any(math.hypot(g.px-(jx+jdx*s),g.py-(jy+jdy*s))<1.0 for s in range(1,tip_len+1)):
                if now>g.gd_invincible_until and not g.rev_ult_active:
                    g.take_damage(int(g.boss.damage*0.6))
            new_jets.append(jet)
    if g.boss.alive: g.boss.water_jets=new_jets

    # projectiles from boss hit player
    new_projs2=[]
    for proj in g.projectiles:
        if proj.owner=='boss':
            if math.hypot(g.px-proj.x,g.py-proj.y)<1.5:
                if now>g.gd_invincible_until and not g.rev_ult_active:
                    g.take_damage(proj.dmg)
                continue
        new_projs2.append(proj)
    g.projectiles=new_projs2

    # mirror clone attack
    if g.map_key=="mirror" and g.mirror_clone_hp>0:
        cx2=g.mw-1-int(g.boss.x); cy2=int(g.boss.y)
        if math.hypot(g.px-cx2,g.py-cy2)<1.5 and random.random()<0.02:
            g.take_damage(g.boss.damage//2)

    # clean messages
    g.messages=[m for m in g.messages if now-m[1]<m[2]]

# render
def render_game(g, out_buf):
    now=time.time()
    mw,mh=g.mw,g.mh
    buf={}  # (x,y)->(ch,fg_clr,bg_clr)

    def put(x,y,ch,clr=(180,180,180),b=None):
        xi,yi=int(x),int(y)
        if 0<=xi<mw and 0<=yi<mh: buf[(xi,yi)]=(ch,clr,b)

    # background based on map
    if g.map_key=="ossuary":
        floor_clr=(35,30,25)
    elif g.map_key=="forge":
        floor_clr=(40,25,20)
    elif g.map_key=="mirror":
        floor_clr=(25,25,35)
    else:
        floor_clr=(25,25,35)

    for y in range(mh):
        for x in range(mw):
            buf[(x,y)]=('.',floor_clr,None)

    # border
    for x in range(mw):
        put(x,0,'#',(60,60,80)); put(x,mh-1,'#',(60,60,80))
    for y in range(mh):
        put(0,y,'#',(60,60,80)); put(mw-1,y,'#',(60,60,80))

    # map decoration
    if g.map_key=="ossuary":
        # skull carvings on top/bottom walls
        for x in range(3,mw-3,6):
            put(x,0,'☠',(120,100,60)); put(x,mh-1,'☠',(120,100,60))
        # ribcage carvings on side walls
        for y in range(2,mh-2,2):
            put(0,y,')',(90,70,45)); put(mw-1,y,'(',(90,70,45))
        # cross-bone floor motif every 12 tiles
        for fy in range(3,mh-3,6):
            for fx in range(4,mw-4,12):
                put(fx,fy,'x',(45,35,28))
        # bone pillars (collidable)
        for (cx,cy,r) in g.geo.pillars:
            for ang in range(0,360,10):
                px2=cx+round((r+0.5)*math.cos(math.radians(ang))*2)
                py2=cy+round((r+0.5)*math.sin(math.radians(ang))*0.9)
                t=(math.sin(now*0.8+ang*0.05)+1)/2
                put(px2,py2,'▓',lerp((90,70,45),(140,115,70),t))
            put(cx,cy,'@',(180,150,90))
        # scattered wall objects (sarcophagi etc)
        for wx2,wy2,wch,wclr in g.geo.walls:
            t2=(math.sin(now*0.3+wx2*0.2)+1)/2
            put(wx2,wy2,wch,lerp(wclr,tuple(min(255,v+40) for v in wclr),t2*0.3))
        # dripping blood on random wall cells
        for x in range(1,mw-1):
            if random.random()<0.0003:
                g.particles.append(Particle(x,0,0,1,'|',(160,20,20),0.8))
                g.particles.append(Particle(mw-1,random.randint(1,mh-2),0,0.5,'|',(160,20,20),1.0))
        # candles in corners
        for cx2,cy2 in [(3,2),(mw-4,2),(3,mh-3),(mw-4,mh-3)]:
            t2=(math.sin(now*4+cx2)+1)/2
            put(cx2,cy2,'i',lerp((200,140,30),(255,220,80),t2))
            put(cx2,cy2-1,'.',lerp((120,80,20),(180,140,40),t2))

    elif g.map_key=="forge":
        # lava channels
        for (ly,x1,x2) in g.geo.lava:
            for x in range(x1,x2+1):
                t=(math.sin(now*3+x*0.3)+1)/2
                clr=lerp((180,60,0),(255,140,20),t)
                put(x,ly,'≈',clr)
                if random.random()<0.005:
                    g.particles.append(Particle(x,ly,random.uniform(-1,1),-2,'.',lerp((200,100,0),(255,200,0),random.random()),0.4))
        # char floor near lava edges
        for (ly,x1,x2) in g.geo.lava:
            for x in range(x1,x2+1):
                for off in [-1,1]:
                    t=(math.sin(now*0.5+x*0.1)+1)/2
                    put(x,ly+off,'.',lerp((35,20,10),(55,35,15),t))
        # furnaces with fire columns
        for fx in g.geo.furnace_cols:
            put(fx,1,'▓',(180,90,30)); put(fx,mh-2,'▓',(180,90,30))
            put(fx,0,'╬',(200,110,40)); put(fx,mh-1,'╬',(200,110,40))
            fire_active=g.geo.furnace_fire.get(fx,0)
            if now<fire_active:
                for fy in range(2,mh-2):
                    t=(math.sin(now*6+fy*0.5)+1)/2
                    put(fx,fy,random.choice(['|','!','i']),lerp((200,80,0),(255,240,60),t))
                if random.random()<0.3:
                    g.particles.append(Particle(fx,random.randint(2,mh-3),random.uniform(-0.5,0.5),-1.5,'*',lerp((220,100,10),(255,220,50),random.random()),0.4))
            elif random.random()<0.012:
                g.geo.furnace_fire[fx]=now+1.8
        # forge obstacles with glow
        for wx2,wy2,wch,wclr in g.geo.walls:
            t2=(math.sin(now*2+wx2*0.3)+1)/2
            put(wx2,wy2,wch,lerp(wclr,lerp(wclr,(255,150,50),0.4),t2*0.5))
        # pipe/chain decoration on walls
        for y in range(3,mh-3,4):
            put(0,y,'=',(80,55,25)); put(mw-1,y,'=',(80,55,25))
        for x in range(5,mw-5,8):
            put(x,0,'-',(90,60,30)); put(x,mh-1,'-',(90,60,30))
        # smoke from furnace
        for fx in g.geo.furnace_cols:
            if random.random()<0.02:
                g.particles.append(Particle(fx,2,random.uniform(-0.3,0.3),-0.8,'░',(60,55,50),1.5))

    elif g.map_key=="standard":
        # subtle grid lines (faint)
        for y in range(4,mh-2,5):
            for x in range(3,mw-3,1):
                if buf.get((x,y),('.',None,None))[0]=='.':
                    put(x,y,'·',(30,30,40))
        # collidable broken pillars
        for (cx,cy,r) in g.geo.pillars:
            for ang in range(0,360,20):
                px2=cx+round((r+0.3)*math.cos(math.radians(ang))*1.8)
                py2=cy+round((r+0.3)*math.sin(math.radians(ang))*0.9)
                put(px2,py2,'#',(70,70,80))
            put(cx,cy,'+',(90,90,100))
        # faint corner runes
        for rx,ry in [(2,1),(mw-3,1),(2,mh-2),(mw-3,mh-2)]:
            t2=(math.sin(now*0.4+rx)+1)/2
            put(rx,ry,'◈',lerp((40,40,60),(80,80,110),t2))

    elif g.map_key=="mirror":
        # silver-white checkerboard floor
        for y in range(1,mh-1):
            for x in range(1,mw-1):
                if (x+y)%2==0:
                    put(x,y,'·',(35,35,50))
        # animated mirror frames
        for y in range(2,mh-2,5):
            for x in range(3,mw-3,14):
                t=(math.sin(now*0.8+x*0.08+y*0.1)+1)/2
                mc=lerp((130,140,170),(220,235,255),t)
                for dx2,dy2,ch2 in [(0,0,'╔'),(3,0,'╗'),(0,2,'╚'),(3,2,'╝'),
                                    (1,0,'═'),(2,0,'═'),(1,2,'═'),(2,2,'═'),
                                    (0,1,'║'),(3,1,'║')]:
                    put(x+dx2,y+dy2,ch2,mc)
                # reflection shimmer inside frame
                t2=(math.sin(now*2+x*0.2)+1)/2
                put(x+1,y+1,'·',lerp((80,80,120),(180,190,220),t2))
                put(x+2,y+1,'·',lerp((80,80,120),(180,190,220),1-t2))
        # crystal pillar obstacles
        for (cx,cy,r) in g.geo.pillars:
            t2=(math.sin(now*1.5+cx*0.3)+1)/2
            put(cx,cy,'◆',lerp((180,190,220),(220,235,255),t2))
            for ddx,ddy in [(-1,0),(1,0),(0,-1),(0,1)]:
                put(cx+ddx,cy+ddy,'░',lerp((100,110,140),(170,180,210),t2))
        # wall scatter
        for wx2,wy2,wch,wclr in g.geo.walls:
            t2=(math.sin(now*1.0+wx2*0.15)+1)/2
            put(wx2,wy2,wch,lerp(wclr,(230,240,255),t2*0.3))

    # clocktower map rendering
    elif g.map_key=="clocktower":
        # dark stone floor with subtle tile cracks
        for y in range(1,mh-1):
            for x in range(1,mw-1):
                if (x+y*3)%11==0:
                    put(x,y,'-',(45,40,30))
        # gear wall segments
        for wx2,wy2,wch,wclr in g.geo.walls:
            t2=(math.sin(now*0.5+wx2*0.15+wy2*0.1)+1)/2
            gear_clr=lerp(wclr,(200,180,80),t2*0.4)
            put(wx2,wy2,wch,gear_clr)
        # gear center glow
        for wx2,wy2,wch,wclr in g.geo.walls:
            if wch=='+':
                t2=(math.sin(now*2+wx2*0.3)+1)/2
                put(wx2,wy2,'*',lerp((120,100,40),(220,200,80),t2))
        # clock hand sweep warning and effect
        geo=g.geo
        if hasattr(geo,'clock_sweep_active') and geo.clock_sweep_active:
            sweep_age=now-geo.clock_sweep_start
            sweep_y=int(g.boss.y if g.boss.alive else mh//2)
            if sweep_age<3.0:
                # warning arc: faint yellow line
                t2=(math.sin(now*4)+1)/2
                for x in range(1,mw-1):
                    put(x,sweep_y,'~',lerp((80,60,10),(200,180,60),t2))
            else:
                # actual sweep: bright destructive line
                t2=(math.sin(now*10)+1)/2
                for x in range(1,mw-1):
                    put(x,sweep_y,'=',lerp((200,180,40),(255,230,80),t2))
        # wall decorations: roman numerals on border
        numerals=['I','II','III','IV','V','VI','VII','VIII','IX','X','XI','XII']
        for i,num in enumerate(numerals[:min(len(numerals),mw//7)]):
            put(3+i*7, 0, num[0], (140,120,60))
        # pendulum bob swings at bottom center
        pend_x=mw//2+int(math.sin(now*1.5)*(mw//6))
        put(pend_x, mh-2, 'O', lerp((120,100,40),(200,180,80),(math.sin(now*1.5)+1)/2))
        for x in range(mw//2-1,pend_x+1 if pend_x>=mw//2 else pend_x-1,-1 if pend_x<mw//2 else 1):
            put(x,mh-2,'.',(80,70,30))

    # reliquary map rendering
    elif g.map_key=="reliquary":
        geo=g.geo
        wl=getattr(geo,'water_level',0)
        # stone floor with moss
        for y in range(1,mh-1):
            for x in range(1,mw-1):
                if (x*7+y*3)%13==0:
                    put(x,y,',',lerp((30,40,35),(50,65,45),(math.sin(now*0.2+x*0.1)+1)/2))
        # water rising from the bottom of the map upward.
        # level 1 fills the bottom third, level 2 fills the bottom two thirds.
        # water_top is the highest row the water occupies (inclusive).
        # the surf row is drawn on top with a brighter animated wave line.
        if wl>0:
            water_rows = min(mh-4, max(1, wl * (mh//3)))
            water_top = mh-2 - water_rows + 1
            for wy in range(water_top, mh-1):
                for wx in range(1,mw-1):
                    # depth 0.0 = surface, 1.0 = deepest
                    depth = (wy - water_top) / max(1, water_rows-1)
                    t2 = (math.sin(now*2 + wx*0.2 + wy*0.1)+1)/2
                    wclr = lerp((50,100,200),(30,60,140),depth)
                    wclr = lerp(wclr, lerp(wclr,(80,160,255),0.3), t2*(1.0-depth))
                    put(wx, wy, chr(8776) if (wx+wy)%3==0 else '~', wclr)
            # surface row: brighter animated sparkle
            for wx in range(1,mw-1):
                t2=(math.sin(now*4+wx*0.35)+1)/2
                put(wx, water_top, '~' if t2>0.5 else chr(8776),
                    lerp((80,160,240),(180,230,255),t2))
        # chests: closed=treasure box, open=scattered loot
        for ch in getattr(geo,'chests',[]):
            cx2,cy2,is_open,effect=ch
            if not is_open:
                t2=(math.sin(now*1.5+cx2*0.3)+1)/2
                put(cx2,cy2,'[',lerp((120,90,40),(180,140,60),t2))
                put(cx2+1,cy2,']',lerp((120,90,40),(180,140,60),t2))
            else:
                put(cx2,cy2,'*',(200,180,80))
                put(cx2+1,cy2,'.',(160,140,60))
        # reliquary alcoves on walls
        for x in range(5,mw-5,8):
            put(x,0,'[',( 80,70,50)); put(x+1,0,']',(80,70,50))
            put(x,mh-1,'[',(80,70,50)); put(x+1,mh-1,']',(80,70,50))
        # bubbles rising from deep water
        if wl>0 and random.random()<0.05:
            bx=random.randint(2,mw-3)
            g.particles.append(Particle(bx,mh-3,random.uniform(-0.3,0.3),-1.5,
                                        'o',(80,140,220),1.2))

    # spire map rendering
    elif g.map_key=="spire":
        # dark exterior stone with ancient carvings
        for y in range(1,mh-1):
            for x in range(1,mw-1):
                if (x*5+y*7)%17==0:
                    put(x,y,'.',( 30,25,40))
        # spiral motif carved into floor
        for ang in range(0,720,8):
            r=ang/720*min(mw,mh)*0.3
            sx=mw//2+int(r*math.cos(math.radians(ang))*1.5)
            sy=mh//2+int(r*math.sin(math.radians(ang))*0.7)
            if 1<=sx<mw-1 and 1<=sy<mh-1:
                t2=(math.sin(now*0.5+ang*0.02)+1)/2
                put(sx,sy,'.',lerp((40,30,55),(70,55,90),t2))
        # edge glow indicating wrap portals
        for x in range(mw):
            t2=(math.sin(now*2+x*0.1)+1)/2
            edge_clr=lerp((40,20,80),(100,60,160),t2)
            put(x,0,chr(9552),edge_clr)
            put(x,mh-1,chr(9552),edge_clr)
        for y in range(mh):
            t2=(math.sin(now*2+y*0.15)+1)/2
            edge_clr=lerp((40,20,80),(100,60,160),t2)
            put(0,y,chr(9553),edge_clr)
            put(mw-1,y,chr(9553),edge_clr)
        # spike warning sites
        geo=g.geo
        for site in getattr(geo,'spike_sites',[]):
            sx,sy,sborn=site
            warn_age=now-sborn
            t2=warn_age/2.0
            sc=lerp((80,30,120),(255,100,200),t2)
            put(sx,sy,'X',sc)
            put(sx-1,sy,'/',lerp((40,20,60),sc,t2*0.5))
            put(sx+1,sy,chr(92),lerp((40,20,60),sc,t2*0.5))
            put(sx,sy-1,'^',lerp((40,20,60),sc,t2*0.5))
            put(sx,sy+1,'v',lerp((40,20,60),sc,t2*0.5))

    # undertaker: show sentence stacks above boss as tally marks
    if g.cls_name=="undertaker" and g.sentence_stacks>0 and g.boss.alive:
        tally = "I"*g.sentence_stacks
        bxi=int(g.boss.x)-len(tally)//2
        put(bxi, int(g.boss.y)-3, tally[0] if len(tally)==1 else tally[:5], (160,80,220))

    # glasswright: draw panes as [ ] and shard zones as , clusters
    if g.cls_name=="glasswright":
        for pane in g.glass_panes:
            px2,py2=pane[0],pane[1]
            t2=(math.sin(now*2+px2*0.3)+1)/2
            pc=lerp((100,180,210),(200,240,255),t2)
            put(px2,py2,'[',pc); put(px2+1,py2,']',pc)
        for sx,sy,exp in g.glass_shards:
            age_frac = 1.0-(exp-now)/3.0
            sc=lerp((140,200,240),(60,80,100),age_frac)
            put(sx,sy,',',sc)
            if sx+1<mw: put(sx+1,sy,'.',sc)

    # bellwether: draw followers as ghostly @ symbols orbiting player
    if g.cls_name=="bellwether":
        for f in g.followers:
            if f[2]=='dead': continue
            fx,fy=int(f[0]),int(f[1])
            if 1<=fx<mw-1 and 1<=fy<mh-1:
                t2=(math.sin(now*2+f[0]*0.5)+1)/2
                fc2=lerp((120,100,40),(220,200,80),t2)
                if f[2]=='charging':
                    fc2=(255,200,50)
                elif f[2]=='wall':
                    fc2=(200,180,60)
                put(fx,fy,'@',fc2)

    # ashwalker: draw ember tiles as glowing floor
    if g.cls_name=="ashwalker":
        for (ex,ey),exp in g.ember_tiles.items():
            if 1<=ex<mw-1 and 1<=ey<mh-1:
                age = 1.0 - (exp-now)/_EMBER_DURATION
                age = max(0.0,min(1.0,age))
                t2=(math.sin(now*4+ex*0.2+ey*0.15)+1)/2
                base_clr=lerp((200,80,20),(255,160,40),t2)
                ec=lerp(base_clr,(40,20,10),age*0.6)
                if getattr(g,'ignition_active',False):
                    ec=lerp(ec,(255,220,80),0.5)
                put(ex,ey,chr(9632) if t2>0.6 else '.',ec)

    # charted tiles (cartographer)
    for (tx,ty) in g.charted:
        if (tx,ty) in g.char_fire:
            t=(math.sin(now*6)+1)/2
            put(tx,ty,'▲',lerp((200,100,20),(255,200,50),t))
        else:
            put(tx,ty,',',lerp((30,60,50),(60,120,90),(math.sin(now+tx*0.3)+1)/2))

    # quicksand zones
    for (qx,qy,qr,qe) in g.quicksand_zones:
        if now<qe:
            for ang in range(0,360,15):
                sx=qx+int(qr*math.cos(math.radians(ang))*1.8)
                sy=qy+int(qr*math.sin(math.radians(ang))*0.9)
                put(sx,sy,'~',(160,140,60))
            put(qx,qy,'*',(180,160,80))

    # terrain walls
    for (wx,wy,we) in g.terrain_walls:
        if now<we:
            put(wx,wy,'▓',(80,100,60))

    # gravemark circles
    for gm in g.gravemarks:
        age=now-gm.born
        for ang in range(0,360,10):
            gx=gm.x+int(6*math.cos(math.radians(ang))*1.8)
            gy=gm.y+int(6*math.sin(math.radians(ang))*0.9)
            put(gx,gy,'+',lerp((100,0,180),(200,100,255),abs(math.sin(age*3))))
        put(gm.x,gm.y,'◈',(200,100,255))

    # dash trail
    for x,y,t in g.dash_trail:
        alpha=1.0-(now-t)/0.3
        put(x,y,'~',lerp((30,30,50),(100,200,255),alpha))

    # afterimages
    for ai in g.afterimages:
        age=now-ai.born
        if not ai.exploded:
            put(ai.x,ai.y,'@',lerp((255,200,50),(255,100,0),age/ai.grace))
        else:
            prog=(age-ai.grace)/(ai.lt-ai.grace)
            r=int(prog*3)+1
            for ang in range(0,360,30):
                put(ai.x+int(r*math.cos(math.radians(ang))*1.8),
                    ai.y+int(r*math.sin(math.radians(ang))*0.9),
                    '*',lerp((255,200,50),(200,100,0),prog))

    # ripples
    for rip in g.ripples:
        p=rip.prog(); r=rip.max_r*p; fade=1.0-p
        for ang in range(0,360,8):
            rx=rip.cx+r*math.cos(math.radians(ang))*1.8
            ry=rip.cy+r*math.sin(math.radians(ang))*0.9
            c=lerp(rip.c1,rip.c2,p); c=lerp((0,0,0),c,fade)
            put(int(rx),int(ry),'o' if p<0.5 else '.',c)

    # fissure rings
    for ring in g.fissure_rings:
        prog=ring.prog(); r=(max(mw,mh)*0.7)*prog
        for ang in range(0,360,6):
            rx=ring.cx+r*math.cos(math.radians(ang))*1.5
            ry=ring.cy+r*math.sin(math.radians(ang))*0.75
            glow=abs(math.sin(prog*math.pi*2+ang*0.05))
            put(int(rx),int(ry),random.choice(['#','|','\\','/']) if random.random()<0.3 else '#',
                lerp((100,40,0),(255,140,30),glow))

    # landmines
    for m in g.landmines:
        if not m.alive(): continue
        if m.triggered and not m.exploded:
            ft=(now-m.trigger_t)/0.4
            put(m.x,m.y,'!',lerp((180,120,0),(255,220,0),abs(math.sin(ft*math.pi*4))))
        elif not m.triggered:
            d2=math.hypot(g.boss.x-m.x,g.boss.y-m.y) if g.boss.alive else 99
            put(m.x,m.y,'x' if d2<3 else '.',(80,60,30) if d2<3 else (50,40,25))

    # marionette strings (draw line from player to boss)
    if g.cls_name=="marionette" and g.strings:
        dx=g.boss.x-g.px; dy=g.boss.y-g.py; d=max(1,math.hypot(dx,dy))
        for step in range(1,int(d),2):
            sx=int(g.px+dx/d*step); sy=int(g.py+dy/d*step)
            t=(math.sin(now*5+step*0.3)+1)/2
            put(sx,sy,'─' if abs(dx)>abs(dy) else '│',lerp((180,40,100),(255,100,180),t))

    # particles
    for p in g.particles:
        put(int(p.x),int(p.y),p.ch,p.clr)

    # projectiles
    for proj in g.projectiles:
        for i,(tx,ty) in enumerate(proj.trail):
            fade=(i+1)/(len(proj.trail)+1)
            put(tx,ty,'.',lerp((20,0,40),proj.clr,fade))
        put(int(proj.x),int(proj.y),proj.ch,proj.clr)

    # boss turrets (boss4)
    for turret in g.boss.turrets:
        if turret[2]!='dead':
            put(turret[0],turret[1],'♪',(200,200,80))

    # mirror clone
    if g.map_key=="mirror" and g.mirror_clone_hp>0 and g.boss.alive:
        cx2=mw-1-int(g.boss.x); cy2=int(g.boss.y)
        t=(math.sin(now*2)+1)/2
        put(cx2,cy2,'@',lerp((100,100,200),(180,180,255),t))

    # boss hit warning
    if g.boss.alive and g.boss.hit_windup is not None and g.boss.hit_target:
        we=now-g.boss.hit_windup; locked=we>=2.0
        if locked:
            pt=(now-(g.boss.hit_windup+2.0))/0.5
            c=lerp((180,0,0),(255,50,50),pt)
        else:
            c=lerp((60,0,0),(200,50,50),we/2.0)
        tx2,ty2=int(g.boss.hit_target[0]),int(g.boss.hit_target[1])
        for ddx in range(-1,2):
            for ddy in range(-1,2):
                put(tx2+ddx,ty2+ddy,'#',c)

    # boss3 water jets rendering
    if g.boss.alive and g.boss.key=="boss3":
        for jet in g.boss.water_jets:
            jx,jy,jdx,jdy,jborn,jdur=jet
            age=now-jborn
            if age<jdur:
                tip_len=max(1,int(age/jdur*(mw//2)))
                for s in range(1,min(tip_len+1, mw)):
                    wx2=jx+jdx*s; wy2=jy+jdy*s
                    if 0<=wx2<mw and 0<=wy2<mh:
                        t=(math.sin(now*6+s*0.4)+1)/2
                        ch2='»' if jdx==1 else ('«' if jdx==-1 else ('v' if jdy==1 else '^'))
                        put(wx2,wy2,ch2,lerp((60,100,220),(120,200,255),t))
                    else: break
                # splash at tip
                tx2=jx+jdx*tip_len; ty2=jy+jdy*tip_len
                if 0<=tx2<mw and 0<=ty2<mh:
                    put(tx2,ty2,'*',(180,220,255))
                    if random.random()<0.3:
                        g.particles.append(Particle(tx2,ty2,random.uniform(-2,2),random.uniform(-1,1),'~',(100,160,255),0.3))

    # boss rendering - unique per-boss shape
    if g.boss.alive:
        flashing=now<g.boss.flash_until
        flash_prog=max(0,(now-(g.boss.flash_until-0.3))/0.3) if flashing else 0
        cells=g.boss.get_cells()
        for cell in cells:
            cx2,cy2,bch=cell
            if flashing:
                clr=lerp((255,220,50),g.boss.color,flash_prog)
            elif g.boss.key=="boss1":
                # warden: deep crimson, pulses darker when winding up
                wind=1.0 if g.boss.hit_windup is None else min(1,(now-g.boss.hit_windup)/2.0)
                clr=lerp((180,20,20),(240,80,60),wind)
            elif g.boss.key=="boss2":
                if g.boss.armor>0:
                    # armoured: stone grey-brown
                    clr=lerp((80,75,60),(200,190,140),g.boss.armor/150)
                else:
                    # phase 2: hot orange cracks
                    t=(math.sin(now*4)+1)/2
                    clr=lerp((200,80,20),(255,160,50),t)
            elif g.boss.key=="boss3":
                # tide caller: flowing blue-teal animated
                t=(math.sin(now*2+cx2*0.3+cy2*0.2)+1)/2
                clr=lerp((30,80,200),(80,200,255),t)
            elif g.boss.key=="boss4":
                # hollow conductor: sickly gold with beat-pulse
                beat_t=(math.sin(g.boss.beat_phase*math.pi*2)+1)/2
                clr=lerp((120,100,20),(255,230,60),beat_t)
            else:
                clr=g.boss.color
            put(cx2,cy2,bch,clr)
        # submerged: overlay ~ over entire shape
        if g.boss.is_submerged():
            t=(math.sin(now*5)+1)/2
            for cell in cells:
                put(cell[0],cell[1],'~',lerp((20,60,160),(60,160,255),t))

        # attack animation overlay
        if g.boss.atk_anim is not None:
            aage=now-g.boss.atk_anim_start
            adur={'slam':2.5,'stomp':2.5,'surge':2.5,'baton':2.5}.get(g.boss.atk_anim,2.5)
            if aage<adur:
                aprog=aage/adur
                cx2,cy2=int(g.boss.x),int(g.boss.y)
                if g.boss.atk_anim=='slam':
                    # warden: arms reach outward then slam down
                    reach=int(aprog*6)
                    for side in [-1,1]:
                        for ext in range(1,reach+1):
                            ax2=cx2+side*ext; ay2=cy2-1
                            tc=lerp((220,60,60),(255,30,30),aprog)
                            put(ax2,ay2,'─' if aprog<0.5 else 'X',tc)
                    if aprog>0.7:
                        for dx2 in range(-3,4):
                            tc=lerp((200,40,40),(255,100,100),(aprog-0.7)/0.3)
                            put(cx2+dx2,cy2+2,'▼',tc)
                        if random.random()<0.2:
                            g.particles.append(Particle(cx2+random.randint(-3,3),cy2+2,random.uniform(-2,2),2,'.',( 220,80,80),0.3))
                elif g.boss.atk_anim=='stomp':
                    # stonewarden: screen shakes, cracks radiate outward
                    crack_r=int(aprog*5)
                    for ang2 in range(0,360,45):
                        for dist2 in range(1,crack_r+1):
                            crx=cx2+int(dist2*math.cos(math.radians(ang2))*1.8)
                            cry=cy2+int(dist2*math.sin(math.radians(ang2))*0.9)
                            tc=lerp((140,110,60),(255,200,80),aprog)
                            put(crx,cry,'/' if ang2%90==45 else chr(92),tc)
                    if aprog>0.6 and random.random()<0.15:
                        for _ in range(3):
                            g.particles.append(Particle(cx2+random.randint(-5,5),cy2+random.randint(-3,3),random.uniform(-3,3),random.uniform(-2,2),'#',(180,150,80),0.4))
                elif g.boss.atk_anim=='surge':
                    # tide caller: tidal wave expands from body
                    wave_r=aprog*8
                    for ang2 in range(0,360,12):
                        wx2=cx2+wave_r*math.cos(math.radians(ang2))*1.6
                        wy2=cy2+wave_r*math.sin(math.radians(ang2))*0.8
                        tc=lerp((60,100,220),(120,200,255),math.sin(aprog*math.pi))
                        put(int(wx2),int(wy2),'~',tc)
                    if aprog<0.5:
                        for ang2 in range(0,360,30):
                            wx2=cx2+wave_r*0.5*math.cos(math.radians(ang2))*1.6
                            wy2=cy2+wave_r*0.5*math.sin(math.radians(ang2))*0.8
                            put(int(wx2),int(wy2),'≈',(80,140,240))
                elif g.boss.atk_anim=='baton':
                    # hollow conductor: baton sweeps in a wide arc
                    sweep_ang=aprog*180-90  # -90 to +90
                    baton_len=7
                    for bl in range(1,baton_len+1):
                        bax=cx2+int(bl*math.cos(math.radians(sweep_ang))*1.8)
                        bay=cy2-3+int(bl*math.sin(math.radians(sweep_ang))*0.9)
                        fade_t=(baton_len-bl)/baton_len
                        tc=lerp((80,60,10),(255,230,80),fade_t)
                        put(bax,bay,'─' if abs(math.cos(math.radians(sweep_ang)))>0.5 else '|',tc)
                    # musical notes fly off tip
                    if random.random()<0.25:
                        tip_x=cx2+int(baton_len*math.cos(math.radians(sweep_ang))*1.8)
                        tip_y=cy2-3+int(baton_len*math.sin(math.radians(sweep_ang))*0.9)
                        g.particles.append(Particle(tip_x,tip_y,random.uniform(-2,2),-1.5,'♪',(220,210,60),0.6))
            else:
                g.boss.atk_anim=None

        # trill visual overlay. each phase has a distinct look so the player can
        # read what is coming without watching the hud.
        if g.boss.trill_active and g.boss.trill_phase:
            phase = g.boss.trill_phase
            phase_age = now - g.boss.trill_start

            if phase == 'advance':
                # leading chevrons pointing toward the player
                dx2 = g.px - g.boss.x; dy2 = g.py - g.boss.y
                d2 = math.hypot(dx2, dy2) or 1
                for step in range(1, 5):
                    ax2 = int(g.boss.x + (dx2 / d2) * step * 1.5)
                    ay2 = int(g.boss.y + (dy2 / d2) * step * 0.8)
                    t_fade = 1.0 - step / 5.0
                    put(ax2, ay2, '>', lerp((80, 60, 10), (255, 220, 60), t_fade))

            elif phase == 'vibrate':
                # rapid pulsing rings and note chars around the boss
                vib_r = abs(math.sin(now * 16)) * 3 + 1
                for ang2 in range(0, 360, 20):
                    rx2 = int(g.boss.x + vib_r * math.cos(math.radians(ang2)) * 1.8)
                    ry2 = int(g.boss.y + vib_r * math.sin(math.radians(ang2)) * 0.9)
                    t2 = (math.sin(now * 20 + ang2 * 0.1) + 1) / 2
                    put(rx2, ry2, chr(9835), lerp((180, 140, 20), (255, 230, 80), t2))
                # flash body on every vibrate tick
                tick_flash = (now * 8) % 1.0 < 0.5
                if tick_flash:
                    for cell in g.boss.get_cells():
                        put(cell[0], cell[1], cell[2], (255, 240, 100))

            elif phase == 'retreat':
                # motion blur trail behind the boss
                dx2 = g.boss.x - g.px; dy2 = g.boss.y - g.py
                d2 = math.hypot(dx2, dy2) or 1
                for step in range(1, 5):
                    tx2 = int(g.boss.x - (dx2 / d2) * step)
                    ty2 = int(g.boss.y - (dy2 / d2) * step * 0.5)
                    t_fade = step / 5.0
                    put(tx2, ty2, chr(9835), lerp((200, 160, 30), (60, 50, 10), t_fade))

            elif phase == 'slam':
                # bright converging impact lines
                progress = min(1.0, phase_age / g.boss.trill_slam_dur)
                tx2, ty2 = g.boss.trill_target
                for step in range(1, 8):
                    frac = step / 8.0
                    sx2 = int(g.boss.trill_origin[0] + (tx2 - g.boss.trill_origin[0]) * frac * progress)
                    sy2 = int(g.boss.trill_origin[1] + (ty2 - g.boss.trill_origin[1]) * frac * progress * 0.5)
                    tc = lerp((100, 80, 10), (255, 220, 50), progress)
                    put(sx2, sy2, '!', tc)
                if progress > 0.8:
                    t_imp = (progress - 0.8) / 0.2
                    for ddx in range(-2, 3):
                        for ddy in range(-1, 2):
                            put(int(tx2) + ddx, int(ty2) + ddy, '*',
                                lerp((200, 160, 30), (255, 250, 150), t_imp))

    # wizard ultimate whirlpool
    if g.ult_active:
        elapsed=now-g.ult_start
        wchars=g.whirlpool_chars
        for y in range(1,mh-1):
            for x in range(1,mw-1):
                d=math.hypot(x-g.px,y-g.py)
                ang=math.atan2(y-g.py,x-g.px)+elapsed*3
                intensity=max(0,min(1,1-d/(mw*0.5)))
                if intensity>0.05:
                    ci=int((ang*5+d-elapsed*5)%len(wchars))
                    ch2=wchars[abs(ci)%len(wchars)]
                    hs=(ang+elapsed)%(math.pi*2)/(math.pi*2)
                    clr=lerp((180,0,200),(255,100,255),hs) if hs<0.5 else lerp((255,100,255),(100,0,180),(hs-0.5)*2)
                    put(x,y,ch2,clr)

    # gd ultimate grey overlay
    if g.gd_ult_active:
        intensity=min(1.0,(now-g.gd_ult_start)/0.3)
        for y in range(1,mh-1):
            for x in range(1,mw-1):
                if (x,y) in buf:
                    ch2,fc,bc=buf[(x,y)]
                    avg=int((fc[0]+fc[1]+fc[2])/3)
                    buf[(x,y)]=(ch2,lerp(fc,(avg,avg,avg),intensity*0.7),bc)

    # player
    px2,py2=int(g.px),int(g.py)
    if now<g.gd_invincible_until:
        flash=abs(math.sin(now*20))
        put(px2,py2,'@',lerp((200,150,0),(255,255,100),flash))
    elif g.ult_active: put(px2,py2,'@',(0,200,255))
    elif g.rev_ult_active:
        t=(math.sin(now*8)+1)/2; put(px2,py2,'@',lerp((200,30,30),(255,120,50),t))
    elif g.is_stunned(): put(px2,py2,'@',(150,150,255))
    elif g.bone_shield_active: put(px2,py2,'@',(100,180,255))
    else:
        clr=CLASS_DATA[g.cls_name]["color"]
        put(px2,py2,'@',lerp(clr,(200,255,200),0.3))

    # revenant: burning trail on last life
    if g.cls_name=="revenant" and g.lives==1:
        if random.random()<0.3:
            g.particles.append(Particle(g.px,g.py,random.uniform(-0.5,0.5),-1,'▲',(220,100,30),0.4))

    # build output string
    tw,th=get_term_size()
    offset_x=max(0,(tw-mw)//2)
    offset_y=1  # leave row 0 for title/hp

    out=HIDE

    # hp bar row
    hp_ratio=max(0,g.hp/g.max_hp)
    hp_clr=lerp((255,50,50),(50,220,80),hp_ratio)

    # player hp
    if g.cls_name=="revenant":
        php=f"HP:{g.hp}/{60}  Lives:{'♥'*g.lives}{'♡'*(5-g.lives)}  Rage:{g.rage_stacks}"
    else:
        php=f"HP:{g.hp}/{g.max_hp}"

    # boss7 liminal: show two separate hp bars for light and void halves.
    # colors are fully static — no time-based animation to prevent flickering.
    if g.boss.key=="boss7" and g.boss.alive:
        liminal_hud_y = offset_y + mh
        lhp = max(0, g.boss.light_hp); vhp = max(0, g.boss.void_hp)
        bar_len = 20
        l_fill = int(bar_len * lhp / max(1, g.boss.max_hp // 2))
        v_fill = int(bar_len * vhp / max(1, g.boss.max_hp // 2))
        l_bar = fg(220,200,80) + "LIGHT[" + fg(200,180,60) + "█"*l_fill + fg(60,55,30) + "░"*(bar_len-l_fill) + fg(220,200,80) + "]" + RST
        v_bar = fg(140,80,220) + "VOID["  + fg(120,60,200) + "█"*v_fill  + fg(40,25,65) + "░"*(bar_len-v_fill)  + fg(140,80,220) + "]" + RST
        bx_r = offset_x + mw - 52
        out += at(bx_r, liminal_hud_y+1) + l_bar + "  " + v_bar
        if g.boss.merge_active:
            # slow pulse (1.5 Hz) so the warning is readable, not seizure-inducing
            t2 = (math.sin(now*1.5)+1)/2
            mc = lerp((160,80,210),(220,140,255),t2)
            prog = min(1.0, (now - g.boss.merge_start) / 5.0)
            prog_bar = "█"*int(prog*20) + "░"*(20-int(prog*20))
            out += at(bx_r, liminal_hud_y+2) + fg(*mc) + BOLD + f"MERGING [{prog_bar}] Deal 80 dmg!" + RST

    # boss hp — fixed width to avoid bleed
    if g.boss.alive:
        bhp=f"BOSS:{g.boss.hp}/{g.boss.max_hp}"
        if g.boss.key=="boss2" and g.boss.armor>0:
            bhp+=f"  Armor:{g.boss.armor}"
    else:
        bhp="BOSS: DEFEATED"

    out+=at(offset_x,0)+fg(*hp_clr)+BOLD+php+RST
    # right-align boss hp
    boss_x=offset_x+mw-len(bhp)
    out+=at(boss_x,0)+fg(*lerp((255,100,100),(100,220,80),g.boss.hp/max(1,g.boss.max_hp)))+BOLD+bhp+RST
    # blank the rest of the hp row to prevent bleeding
    out+=at(offset_x+len(php),0)+fg(0,0,0)+" "*(boss_x-offset_x-len(php))+RST

    # map rows
    for row in range(mh):
        line=""
        for col in range(mw):
            ch2,fc,_=buf.get((col,row),('.',floor_clr,None))
            line+=fg(*fc)+ch2
        line+=RST
        out+=at(offset_x,offset_y+row)+line

    # hud rows (below map)
    hud_y=offset_y+mh
    # clear hud area first (prevents ghosting)
    for i in range(4):
        out+=at(0,hud_y+i)+" "*tw+RST

    # move bar
    now2=time.time()
    move_names=CLASS_DATA[g.cls_name]["move_names"]
    move_str=""
    for i in range(1,6):
        on_cd=now2<g.move_cds_end.get(i,0)
        sel=(i==g.selected)
        name=move_names[i]

        if i==5 and g.can_ult() and not g.ult_active and not g.rev_ult_active and not g.gd_ult_active:
            t_shine=now2*2; shine_pos=t_shine%(len(name)+4)
            chars=f"[5:{name}]"; shined=""
            for ci,ch2 in enumerate(chars):
                dist_shine=abs(ci-shine_pos)
                intensity=max(0,1-dist_shine/3)
                shined+=fg(*lerp((200,80,0),(255,220,50),intensity))+ch2
            move_str+=shined+RST+"  "
        elif on_cd:
            cd_left=g.move_cds_end[i]-now2
            c=(180,0,0) if sel else (70,70,70)
            move_str+=fg(*c)+f"[{i}:{name} {cd_left:.1f}s]"+RST+"  "
        elif sel:
            move_str+=fg(255,50,50)+BOLD+f"[{i}:{name}]"+RST+"  "
        else:
            move_str+=fg(180,180,180)+f"[{i}:{name}]"+RST+"  "

    out+=at(offset_x,hud_y)+move_str

    # dash cd
    dcd=g.dash_ready-now2
    if dcd>0:
        out+=at(offset_x,hud_y+1)+fg(70,70,70)+f"[Q:Dash {dcd:.1f}s]"+RST
    else:
        out+=at(offset_x,hud_y+1)+fg(100,200,100)+f"[Q:Dash ready]"+RST


    # siphon class hud: shows stored charges and hijack window state
    if g.cls_name=="siphon":
        charge_str = "CHARGES: " + chr(9672)*len(g.siphon_charges) + "o"*(3-len(g.siphon_charges))
        charge_clr = lerp((60,120,110),(80,230,200),len(g.siphon_charges)/3)
        out += at(offset_x+2, hud_y+1) + fg(*charge_clr) + charge_str + RST
        if g.hijack_active:
            window_left = max(0.0, 1.5 - (now2 - g.hijack_start))
            t2 = window_left / 1.5
            hj_clr = lerp((80,80,80),(80,240,220),t2)
            out += at(offset_x+2, hud_y+2) + fg(*hj_clr) + BOLD + f"HIJACK: {window_left:.1f}s" + RST
        if g.siphon_leech_active:
            leech_left = max(0.0, g.siphon_leech_expires - now2)
            out += at(offset_x+2, hud_y+3) + fg(60,180,160) + f"LEECH: {leech_left:.1f}s" + RST

    # undertaker hud: sentence stack counter and total lifetime stacks
    if g.cls_name=="undertaker":
        stk_str = "SENTENCE: " + chr(9632)*g.sentence_stacks + chr(9633)*(5-g.sentence_stacks)
        stk_clr = lerp((100,60,160),(200,100,255), g.sentence_stacks/5)
        out += at(offset_x+2, hud_y+1) + fg(*stk_clr) + stk_str + RST
        out += at(offset_x+2, hud_y+2) + fg(80,60,100) + f"Total sentenced: {g.total_sentences}" + RST
        if g.parry_window:
            t2=(math.sin(now2*6)+1)/2
            pc=lerp((140,80,200),(220,160,255),t2)
            out += at(offset_x+2, hud_y+3) + fg(*pc) + BOLD + "PARRY WINDOW!" + RST

    # glasswright hud: pane count and shard count
    if g.cls_name=="glasswright":
        pane_str = "PANES: " + chr(9632)*len(g.glass_panes) + chr(9633)*(4-len(g.glass_panes))
        out += at(offset_x+2, hud_y+1) + fg(140,210,230) + pane_str + RST
        if g.glass_shards:
            out += at(offset_x+2, hud_y+2) + fg(80,140,160) + f"Shards: {len(g.glass_shards)} active" + RST

    # bellwether hud: follower count and state
    if g.cls_name=="bellwether":
        alive_f = [f for f in g.followers if f[2]!='dead']
        f_str = f"FOLLOWERS: {len(alive_f)}/5"
        f_clr = lerp((100,80,30),(220,200,70), len(alive_f)/5)
        out += at(offset_x+2, hud_y+1) + fg(*f_clr) + f_str + RST
        if g.wall_mode:
            out += at(offset_x+2, hud_y+2) + fg(180,160,50) + "WALL MODE" + RST

    # ashwalker hud: ember tile count and ignition status
    if g.cls_name=="ashwalker":
        e_count = len(g.ember_tiles)
        e_str = f"EMBERS: {e_count}"
        e_clr = lerp((120,60,20),(255,160,40), min(1.0, e_count/20))
        out += at(offset_x+2, hud_y+1) + fg(*e_clr) + e_str + RST
        if g.ignition_active:
            t2=(math.sin(now2*3)+1)/2
            ic=lerp((200,100,30),(255,200,50),t2)
            out += at(offset_x+2, hud_y+2) + fg(*ic) + BOLD + "IGNITION!" + RST

    # beat bar for the hollow conductor. shows the current beat phase as a fill bar.
    # the bar fills faster as hp drops due to crescendo. when a trill is active,
    # the label changes to show which phase the trill is currently in.
    if g.boss.key=="boss4" and g.boss.alive:
        blen = 28
        bfill = int(blen * g.boss.beat_phase)
        # color shifts from muted gold to bright white-yellow as the bar nears a beat
        bc2 = lerp((120, 100, 30), (255, 235, 80), g.boss.beat_phase)
        # bar flashes white right on the beat boundary
        if g.boss.beat_phase < 0.08:
            bc2 = lerp((255, 255, 200), (255, 235, 80), g.boss.beat_phase / 0.08)

        if g.boss.trill_active and g.boss.trill_phase:
            phase_labels = {
                'advance':  'TRILL: ADVANCE ',
                'vibrate':  'TRILL: VIBRATE ',
                'retreat':  'TRILL: RETREAT ',
                'slam':     'TRILL: SLAM!!! ',
            }
            label = phase_labels.get(g.boss.trill_phase, 'TRILL')
            # trill label pulses rapidly
            t_pulse = (math.sin(now * 12) + 1) / 2
            trill_clr = lerp((200, 140, 20), (255, 240, 80), t_pulse)
            beat_bar = label + "[" + "█" * bfill + "░" * (blen - bfill) + "]"
            out += at(offset_x + mw - len(beat_bar) - 2, hud_y + 1) + fg(*trill_clr) + BOLD + beat_bar + RST
        else:
            # show bpm hint: faster interval = higher bpm displayed
            bpm = int(60.0 / max(0.1, g.boss.beat_interval))
            beat_bar = f"BEAT {bpm}bpm [" + "█" * bfill + "░" * (blen - bfill) + "]"
            out += at(offset_x + mw - len(beat_bar) - 2, hud_y + 1) + fg(*bc2) + beat_bar + RST

    # mid-screen messages
    for msg in g.messages:
        text,born,dur,mx2,my2,mc=msg
        age=now2-born; fade=1.0-age/dur
        if fade>0:
            c=lerp((20,20,30),mc,fade)
            sy=offset_y+my2; sx=offset_x+mx2-len(text)//2
            if 0<=sy<th and 0<=sx<tw:
                out+=at(sx,sy)+fg(*c)+BOLD+text+RST

    # game over / victory
    if g.game_over:
        msg2="GAME OVER  —  press ESC"
        cx2=offset_x+mw//2-len(msg2)//2
        out+=at(cx2,offset_y+mh//2)+fg(255,50,50)+BOLD+msg2+RST
    elif g.victory:
        msg2=f"VICTORY!  +{g.earned_coins} coins  —  press ESC"
        cx2=offset_x+mw//2-len(msg2)//2
        out+=at(cx2,offset_y+mh//2)+fg(50,255,100)+BOLD+msg2+RST

    out_buf.append(out)
