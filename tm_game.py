"""TillyMagic gameplay engine."""
from tm_core import *

# ── Game objects ───────────────────────────────────────────────────────────────
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

class BossString:  # Marionette
    def __init__(self): self.born=time.time(); self.lt=8.0
    def alive(self): return (time.time()-self.born)<self.lt

class CharTile:    # Cartographer
    def __init__(self,x,y): self.x=x;self.y=y; self.born=time.time()

# ── Boss ───────────────────────────────────────────────────────────────────────
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
        # Boss2 state
        self.armor = 150 if key=="boss2" else 0
        self.phase2 = False
        self.charge_target = None; self.charge_start = None
        # Boss3 state
        self.submerged_until = 0
        self.current_offset = (0,0)  # map drift
        # Boss4 beat bar
        self.beat_interval = 2.0; self.last_beat = time.time()
        self.beat_phase = 0.0
        self.turrets = []  # [(x,y,type,hp,last_fire)]
        self.turrets_spawned = False

    def is_stunned(self): return time.time()<self.stun_until
    def stun(self,d): self.stun_until=max(self.stun_until,time.time()+d)
    def is_submerged(self): return time.time()<self.submerged_until

    def get_cells(self):
        cx,cy=int(self.x),int(self.y)
        cells=[]
        for ang in range(0,360,20):
            bx2=cx+round(2*math.cos(math.radians(ang))*1.8)
            by2=cy+round(2*math.sin(math.radians(ang))*0.9)
            if (bx2,by2) not in cells: cells.append((bx2,by2))
        return cells

# ── Map geometry ───────────────────────────────────────────────────────────────
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
        if self.key=="ossuary":
            pad=5
            for cx,cy in [(pad,pad),(w-pad,pad),(pad,h-pad),(w-pad,h-pad)]:
                self.pillars.append((cx,cy,2))
        elif self.key=="forge":
            h1=h//3; h2=(h*2)//3
            for y in [h1,h2]:
                self.lava.append((y, 2, w-3))
            for x in [2,w-3]:
                self.furnace_cols.append(x)
        elif self.key=="mirror":
            pass  # no extra geometry; clone handled in game logic

    def is_blocked(self,x,y):
        for (cx,cy,r) in self.pillars:
            if math.hypot(x-cx,y-cy)<=r: return True
        for (ly,x1,x2) in self.lava:
            if y==ly and x1<=x<=x2: return True
        return False

    def is_lava(self,x,y):
        for (ly,x1,x2) in self.lava:
            if y==ly and x1<=x<=x2: return True
        return False

# ── Game state ─────────────────────────────────────────────────────────────────
class Game:
    def __init__(self, cls_name, boss_key, map_key, size_mult, save):
        self.cls_name = cls_name
        self.boss_key = boss_key
        self.map_key = map_key
        self.size_mult = size_mult

        # Map dimensions
        self.mw = max(40, int(BASE_MAP_W * size_mult))
        self.mh = max(18, int(BASE_MAP_H * size_mult))
        # Clamp to terminal
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
        self.dash_dist = base["dash_dist"]
        self.dmg_mult = base["dmg_mult"]
        self.cd_mult = base["cd_mult"]
        self.absorb = base["absorb"]
        self.hit_range_bonus = base["hit_range_bonus"]

        # Move cooldowns
        self.move_cds = {k:v for k,v in cd["move_cds"].items()}
        self.move_cds_end = {k:0 for k in range(1,6)}
        self.selected = 1
        self.stun_until = 0

        # Dash
        self.dash_ready = 0; self.dash_trail = []

        # Combo states
        self.combo_state = 0; self.combo_ready = 0   # shared for move1

        # Wizard
        self.whirlpool_chars = list("@#$%&*!?~^+=<>|\\/`.,;:abcdefABCDEF0123456789")
        self.ult_active = False; self.ult_start = 0; self.ult_dur = 5.0
        self.ult_dmg_tick = 0; self.ult_proc = None

        # Gravedigger
        self.landmines = []; self.max_mines = 3
        self.fissure_rings = []; self.gd_invincible_until = 0
        self.gd_ult_active = False; self.gd_ult_start = 0

        # Marionette
        self.strings = []        # BossString list
        self.redirect_ready = False; self.redirect_expires = 0

        # Cartographer
        self.charted = set()     # set of (x,y)
        self.char_fire = {}      # (x,y)->fire_until
        self.quicksand_zones = [] # [(x,y,r,expires)]
        self.terrain_walls = []   # [(x,y,expires)]

        # Revenant
        self.lives = 5; self.rage_stacks = 0
        self.bone_shield_active = False; self.bone_shield_ready = 0
        self.rev_ult_active = False; self.rev_ult_end = 0

        # Effects/objects
        self.particles = []; self.projectiles = []
        self.ripples = []; self.afterimages = []
        self.gravemarks = []
        self.messages = []    # [text,born,dur,x,y,clr]

        # Boss
        bx = self.mw - max(8, int(self.mw*0.2))
        boss = Boss(boss_key, bx, self.mh//2)
        boss.damage = int(boss.damage * (1 + 0.3*(size_mult-1)))
        self.boss = boss

        # Boss2 clone (mirror map)
        self.mirror_clone_hp = 200 if map_key=="mirror" else 0
        self.mirror_clone_regen = 0

        self.game_over = False; self.victory = False
        self.coin_mult = MAP_DATA[map_key]["coin_mult"]
        self.earned_coins = 0

    def cd(self, move):
        return self.move_cds.get(move, 1.0) * self.cd_mult

    def dist_boss(self):
        return math.hypot(self.boss.x-self.px, self.boss.y-self.py)

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

# ── Input/action dispatch ──────────────────────────────────────────────────────
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
        spd = g.speed*dt
        # Cartographer: quicksand slow
        for (qx,qy,qr,qe) in g.quicksand_zones:
            if time.time()<qe and math.hypot(g.px-qx,g.py-qy)<qr:
                spd *= 0.4
                break
        norm=math.hypot(mx,my) or 1
        nx=max(1,min(g.mw-2, g.px+(mx/norm)*spd))
        ny=max(1,min(g.mh-2, g.py+(my/norm)*spd))
        # Check map blocks
        if not g.geo.is_blocked(int(nx),int(ny)):
            # Lava check
            if g.geo.is_lava(int(nx),int(ny)):
                g.take_damage(g.max_hp)  # instant death
            else:
                g.px=nx; g.py=ny
                # Cartographer: chart tile
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
    dispatch={
        "wizard":       [do_scepter,do_arcane_snap,do_gravemark,do_blink_scatter,do_wiz_ult],
        "gravedigger":  [do_shovel,do_dig,do_bury,do_exhume,do_gd_ult],
        "marionette":   [do_silk_strike,do_plant_string,do_puppet_pull,do_redirect,do_mar_ult],
        "cartographer": [do_ink_stab,do_flare,do_quicksand,do_terrain_wall,do_cart_ult],
        "revenant":     [do_death_blow,do_rage_strike,do_bone_shield,do_self_destruct,do_rev_ult],
    }
    fn=dispatch.get(g.cls_name,[])[move-1]
    fn(g)

# ── Wizard ─────────────────────────────────────────────────────────────────────
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
    else:
        play(SND_HIT); g.combo_state+=1; g.combo_ready=now+0.25*g.cd_mult

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
    for i in range(1,4):
        t=i/4.0
        g.afterimages.append(Afterimage(int(ox+(tx-ox)*t),int(oy+(ty-oy)*t)))
    ang=random.uniform(0,math.pi*2)
    g.px=max(1,min(g.mw-2,tx+math.cos(ang)*2))
    g.py=max(1,min(g.mh-2,ty+math.sin(ang)))

def do_wiz_ult(g):
    if not g.can_ult(): g.add_msg("Need <50% HP!",1.0,g.mw//2,g.mh//2,(255,80,80)); return
    if g.ult_active: return
    g.ult_active=True; g.ult_start=time.time(); g.ult_dmg_tick=time.time()
    g.stun_until=time.time()+g.ult_dur+0.1
    if g.boss.alive: g.boss.stun(g.ult_dur)
    try: g.ult_proc=subprocess.Popen(["afplay",SND_ULT],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    except: pass

# ── Gravedigger ────────────────────────────────────────────────────────────────
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
    else:
        dmg=int(8*g.dmg_mult)
        g.boss.hp-=dmg; g.boss.flash_until=now+0.2; play(SND_HIT)
        for _ in range(3):
            ang=random.uniform(math.pi,math.pi*2)
            g.particles.append(Particle(g.boss.x,g.boss.y,math.cos(ang)*4,math.sin(ang)*2-2,",",(120,90,50),0.4))
        _dmg_msg(g,dmg,(180,140,60))
        g.combo_state+=1; g.combo_ready=now+0.3*g.cd_mult

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
    g.gd_ult_active=True; g.gd_ult_start=time.time()
    g.gd_invincible_until=time.time()+1.5
    g.fissure_rings.append(FissureRing(int(g.px),int(g.py),max(g.mw,g.mh)))
    for ang in range(0,360,8):
        g.particles.append(Particle(g.px,g.py,math.cos(math.radians(ang))*15,math.sin(math.radians(ang))*7,
            random.choice(['/','\\','|','-','#']),(200,100,30),1.0))
    try: subprocess.Popen(["afplay",SND_ULT],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    except: pass

# ── Marionette ─────────────────────────────────────────────────────────────────
def do_silk_strike(g):
    now=time.time()
    if now<g.combo_ready or not g.boss.alive: return
    if g.dist_boss()>2+g.hit_range_bonus:
        g.add_msg("Out of range!",0.8,g.mw//2,g.mh//2-1,(200,200,100)); return
    s=g.combo_state; final=(s==4)
    dmg=int((12 if final else 6)*g.dmg_mult)
    g.boss.hp-=dmg; g.boss.flash_until=now+(0.4 if final else 0.2)
    play(SND_FINAL if final else SND_HIT); _dmg_msg(g,dmg,(200,60,120))
    # String reflect
    reflect=int(dmg*0.3*len(g.strings))
    if reflect>0:
        g.boss.hp-=reflect; _dmg_msg(g,reflect,(255,100,200))
    if final: g.combo_state=0; g.combo_ready=now+0.7; g.boss.stun(0.5)
    else: g.combo_state+=1; g.combo_ready=now+0.3*g.cd_mult

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

# ── Cartographer ───────────────────────────────────────────────────────────────
def do_ink_stab(g):
    now=time.time()
    if now<g.combo_ready or not g.boss.alive: return
    if g.dist_boss()>2+g.hit_range_bonus:
        g.add_msg("Out of range!",0.8,g.mw//2,g.mh//2-1,(200,200,100)); return
    s=g.combo_state; final=(s==4); dmg=int((10 if final else 5)*g.dmg_mult)
    g.boss.hp-=dmg; g.boss.flash_until=now+(0.4 if final else 0.2)
    play(SND_FINAL if final else SND_HIT); _dmg_msg(g,dmg,(60,200,140))
    if final: g.combo_state=0; g.combo_ready=now+0.7; g.boss.stun(0.5)
    else: g.combo_state+=1; g.combo_ready=now+0.25*g.cd_mult
    # Mark current tile
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
    # Place a wall of 5 tiles in front of player facing boss
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

# ── Revenant ───────────────────────────────────────────────────────────────────
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
    if final: g.combo_state=0; g.combo_ready=now+0.7; g.boss.stun(0.6)
    else: g.combo_state+=1; g.combo_ready=now+0.28*g.cd_mult

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
    g.rev_ult_active=True; g.rev_ult_end=time.time()+4.0
    try: subprocess.Popen(["afplay",SND_ULT],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    except: pass
    g.add_msg("BERSERK!",1.2,g.mw//2,g.mh//2-1,(255,50,50))

def _dmg_msg(g, dmg, clr):
    g.add_msg(f"-{dmg}",0.7,int(g.boss.x),int(g.boss.y)-1,clr)

# ── Update ─────────────────────────────────────────────────────────────────────
def update_game(g, dt):
    now=time.time()
    if g.game_over or g.victory: return

    # Dash trail
    g.dash_trail=[(x,y,t) for x,y,t in g.dash_trail if now-t<0.3]

    # Particles
    for p in g.particles: p.update(dt)
    g.particles=[p for p in g.particles if p.alive()]

    # Ripples
    g.ripples=[r for r in g.ripples if r.alive()]

    # Strings (Marionette)
    g.strings=[s for s in g.strings if s.alive()]
    if g.redirect_ready and now>g.redirect_expires: g.redirect_ready=False

    # Quicksand/terrain walls
    g.quicksand_zones=[(x,y,r,e) for x,y,r,e in g.quicksand_zones if now<e]
    g.terrain_walls=[(x,y,e) for x,y,e in g.terrain_walls if now<e]

    # Char fire
    g.char_fire={k:v for k,v in g.char_fire.items() if now<v}

    # Revenant trail
    if g.rev_ult_active:
        if now>=g.rev_ult_end: g.rev_ult_active=False
        else:
            g.char_fire[(int(g.px),int(g.py))]=now+1.5

    # Afterimages
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

    # Gravemarks
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

    # Cartographer charted tile damage
    if g.boss.alive:
        bt=(int(g.boss.x),int(g.boss.y))
        if bt in g.charted and not bt in g.char_fire:
            if random.random()<0.05:  # 5% per frame ~3 dps
                g.boss.hp-=3; g.boss.flash_until=now+0.1

    # Landmines
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

    # Fissure rings
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

    # Mirror clone
    if g.map_key=="mirror" and g.boss.alive:
        if g.mirror_clone_hp<=0:
            g.mirror_clone_regen=max(g.mirror_clone_regen,now+5.0)
        if now>=g.mirror_clone_regen and g.mirror_clone_hp<=0:
            g.mirror_clone_hp=200

    # Projectiles
    new_projs=[]
    for proj in g.projectiles:
        proj.update(dt)
        px2,py2=int(proj.x),int(proj.y)
        if px2<0 or px2>=g.mw or py2<0 or py2>=g.mh: continue
        hit=False
        if proj.owner=='player' and g.boss.alive:
            if math.hypot(g.boss.x-proj.x,g.boss.y-proj.y)<2.5:
                dmg=proj.dmg
                # Stonewarden armor
                if g.boss.key=="boss2" and g.boss.armor>0:
                    absorbed_armor=min(dmg,g.boss.armor)
                    g.boss.armor-=absorbed_armor; dmg-=absorbed_armor
                    if g.boss.armor<=0 and not g.boss.phase2:
                        g.boss.phase2=True
                        g.add_msg("SHELL CRACKED!",1.5,g.mw//2,g.mh//2,(255,200,50))
                if dmg>0: g.boss.hp-=dmg; g.boss.flash_until=now+0.25; _dmg_msg(g,int(dmg),proj.clr)
                # Marionette string reflect
                if g.strings:
                    reflect=int(proj.dmg*0.3*len(g.strings))
                    g.boss.hp-=reflect
                for _ in range(4):
                    ang=random.uniform(0,math.pi*2)
                    g.particles.append(Particle(proj.x,proj.y,math.cos(ang)*4,math.sin(ang)*2,'.',proj.clr,0.25))
                hit=True
        if not hit: new_projs.append(proj)
    g.projectiles=new_projs

    # Wizard ultimate
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

    # Boss update
    if not g.boss.alive:
        return
    if g.boss.hp<=0:
        g.boss.alive=False; g.victory=True
        coins=int(BOSS_DATA[g.boss_key]["coins"]*g.coin_mult)
        g.earned_coins=coins
        return

    if not g.boss.is_stunned() and not g.boss.is_submerged():
        # Movement
        if now-g.boss.last_move>=g.boss.move_interval:
            g.boss.last_move=now
            # Boss-specific movement
            if g.boss.key=="boss3":  # Tide Caller drift
                drift_x=math.sin(now*0.5)*0.5
                g.px=max(1,min(g.mw-2,g.px+drift_x))
            if g.dist_boss()>g.boss.hit_range:
                dx=g.px-g.boss.x; dy=g.py-g.boss.y
                d=math.hypot(dx,dy) or 1
                spd=1.8*(1+0.3*(g.size_mult-1))
                if g.boss.key=="boss3":  # Tide Caller: submerge periodically
                    if random.random()<0.05:
                        g.boss.submerged_until=now+2.0
                g.boss.x=max(2,min(g.mw-4,g.boss.x+(dx/d)*spd))
                g.boss.y=max(2,min(g.mh-3,g.boss.y+(dy/d)*spd*0.5))
                # Boss2 phase2 charge
                if g.boss.key=="boss2" and g.boss.phase2 and random.random()<0.1:
                    g.boss.charge_target=(g.px,g.py); g.boss.charge_start=now

        # Stonewarden charge
        if g.boss.key=="boss2" and g.boss.charge_target and g.boss.charge_start:
            if now-g.boss.charge_start<0.5:
                cx,cy=g.boss.charge_target
                dx=cx-g.boss.x; dy=cy-g.boss.y; d=math.hypot(dx,dy) or 1
                g.boss.x=max(2,min(g.mw-4,g.boss.x+(dx/d)*8*dt))
                g.boss.y=max(2,min(g.mh-3,g.boss.y+(dy/d)*4*dt))
            else:
                g.boss.charge_target=None; g.boss.charge_start=None

        # Boss4 beat
        if g.boss.key=="boss4":
            g.boss.beat_phase=(now-g.boss.last_beat)/g.boss.beat_interval
            if g.boss.beat_phase>=1.0:
                g.boss.last_beat=now; g.boss.beat_phase=0.0
                # Spawn turret occasionally
                if not g.boss.turrets_spawned and g.boss.hp<g.boss.max_hp*0.7:
                    g.boss.turrets_spawned=True
                    for tx2,ty2 in [(10,5),(g.mw-10,5),(10,g.mh-5),(g.mw-10,g.mh-5)]:
                        g.boss.turrets.append([tx2,ty2,'violin',30,0])
            # Turret fire
            for turret in g.boss.turrets[:]:
                if turret[2]=='dead': continue
                if now-turret[4]>2.0:
                    turret[4]=now
                    g.projectiles.append(Projectile(turret[0],turret[1],g.px,g.py,10,'♪',(200,200,80),10,'boss'))

        # Hit logic
        if g.boss.hit_windup is None and now-g.boss.last_hit>=g.boss.hit_cd:
            if g.dist_boss()<=g.boss.hit_range+2:
                g.boss.hit_windup=now
                g.boss.hit_target=(g.px,g.py)
                g.boss.hit_landing=now+2.5

        if g.boss.hit_windup is not None:
            if now<g.boss.hit_windup+2.0:
                g.boss.hit_target=(g.px,g.py)
            if now>=g.boss.hit_landing:
                if g.boss.hit_target:
                    if math.hypot(g.px-g.boss.hit_target[0],g.py-g.boss.hit_target[1])<1.5:
                        if g.redirect_ready:
                            # Marionette redirect
                            g.redirect_ready=False
                            g.boss.hp-=g.boss.damage*2
                            g.boss.flash_until=now+0.5
                            _dmg_msg(g,g.boss.damage*2,(255,100,200))
                            g.add_msg("REDIRECTED!",1.0,g.mw//2,g.mh//2,(220,100,180))
                        elif not g.is_stunned() and now>g.gd_invincible_until and not g.rev_ult_active:
                            g.take_damage(g.boss.damage)
                g.boss.hit_windup=None; g.boss.hit_target=None
                g.boss.hit_landing=None; g.boss.last_hit=now

    # Projectiles from boss hit player
    new_projs2=[]
    for proj in g.projectiles:
        if proj.owner=='boss':
            if math.hypot(g.px-proj.x,g.py-proj.y)<1.5:
                if now>g.gd_invincible_until and not g.rev_ult_active:
                    g.take_damage(proj.dmg)
                continue
        new_projs2.append(proj)
    g.projectiles=new_projs2

    # Mirror clone attack
    if g.map_key=="mirror" and g.mirror_clone_hp>0:
        cx2=g.mw-1-int(g.boss.x); cy2=int(g.boss.y)
        if math.hypot(g.px-cx2,g.py-cy2)<1.5 and random.random()<0.02:
            g.take_damage(g.boss.damage//2)

    # Clean messages
    g.messages=[m for m in g.messages if now-m[1]<m[2]]

# ── Render ─────────────────────────────────────────────────────────────────────
def render_game(g, out_buf):
    now=time.time()
    mw,mh=g.mw,g.mh
    buf={}  # (x,y)->(ch,fg_clr,bg_clr)

    def put(x,y,ch,clr=(180,180,180),b=None):
        xi,yi=int(x),int(y)
        if 0<=xi<mw and 0<=yi<mh: buf[(xi,yi)]=(ch,clr,b)

    # Background based on map
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

    # Border
    for x in range(mw):
        put(x,0,'#',(60,60,80)); put(x,mh-1,'#',(60,60,80))
    for y in range(mh):
        put(0,y,'#',(60,60,80)); put(mw-1,y,'#',(60,60,80))

    # Map decoration
    if g.map_key=="ossuary":
        # Skull motifs on walls
        for x in range(3,mw-3,8):
            put(x,0,'☠',(120,100,60)); put(x,mh-1,'☠',(120,100,60))
        # Ribcage sides
        for y in range(2,mh-2,3):
            put(0,y,')',(80,60,40)); put(mw-1,y,'(',(80,60,40))
        # Pillars
        for (cx,cy,r) in g.geo.pillars:
            for ang in range(0,360,15):
                px2=cx+round(r*math.cos(math.radians(ang))*1.8)
                py2=cy+round(r*math.sin(math.radians(ang))*0.9)
                put(px2,py2,'@',(150,120,70))
            put(cx,cy,'#',(180,150,90))

    elif g.map_key=="forge":
        # Lava channels
        for (ly,x1,x2) in g.geo.lava:
            for x in range(x1,x2+1):
                t=(math.sin(now*3+x*0.3)+1)/2
                clr=lerp((180,60,0),(255,140,20),t)
                put(x,ly,'≈',clr)
                # Ember particles occasionally
                if random.random()<0.005:
                    g.particles.append(Particle(x,ly,random.uniform(-1,1),-2,'.',lerp((200,100,0),(255,200,0),random.random()),0.4))
        # Furnaces
        for fx in g.geo.furnace_cols:
            put(fx,1,'▓',(160,80,30)); put(fx,mh-2,'▓',(160,80,30))
            fire_active=g.geo.furnace_fire.get(fx,0)
            if now<fire_active:
                for fy in range(2,mh-2):
                    t=(math.sin(now*5+fy*0.4)+1)/2
                    put(fx,fy,'|',lerp((200,80,0),(255,220,50),t))
            elif random.random()<0.01:
                g.geo.furnace_fire[fx]=now+1.5

    elif g.map_key=="mirror":
        # Box drawing mirror frames
        for y in range(2,mh-2,4):
            for x in range(2,mw-2,10):
                t=(math.sin(now*0.5+x*0.1+y*0.1)+1)/2
                c=lerp((150,160,180),(220,230,255),t)
                put(x,y,'╔',c); put(x+3,y,'╗',c)
                put(x,y+2,'╚',c); put(x+3,y+2,'╝',c)
                put(x+1,y,'═',c); put(x+2,y,'═',c)
                put(x+1,y+2,'═',c); put(x+2,y+2,'═',c)
                put(x,y+1,'║',c); put(x+3,y+1,'║',c)

    # Charted tiles (Cartographer)
    for (tx,ty) in g.charted:
        if (tx,ty) in g.char_fire:
            t=(math.sin(now*6)+1)/2
            put(tx,ty,'▲',lerp((200,100,20),(255,200,50),t))
        else:
            put(tx,ty,',',lerp((30,60,50),(60,120,90),(math.sin(now+tx*0.3)+1)/2))

    # Quicksand zones
    for (qx,qy,qr,qe) in g.quicksand_zones:
        if now<qe:
            for ang in range(0,360,15):
                sx=qx+int(qr*math.cos(math.radians(ang))*1.8)
                sy=qy+int(qr*math.sin(math.radians(ang))*0.9)
                put(sx,sy,'~',(160,140,60))
            put(qx,qy,'*',(180,160,80))

    # Terrain walls
    for (wx,wy,we) in g.terrain_walls:
        if now<we:
            put(wx,wy,'▓',(80,100,60))

    # Gravemark circles
    for gm in g.gravemarks:
        age=now-gm.born
        for ang in range(0,360,10):
            gx=gm.x+int(6*math.cos(math.radians(ang))*1.8)
            gy=gm.y+int(6*math.sin(math.radians(ang))*0.9)
            put(gx,gy,'+',lerp((100,0,180),(200,100,255),abs(math.sin(age*3))))
        put(gm.x,gm.y,'◈',(200,100,255))

    # Dash trail
    for x,y,t in g.dash_trail:
        alpha=1.0-(now-t)/0.3
        put(x,y,'~',lerp((30,30,50),(100,200,255),alpha))

    # Afterimages
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

    # Ripples
    for rip in g.ripples:
        p=rip.prog(); r=rip.max_r*p; fade=1.0-p
        for ang in range(0,360,8):
            rx=rip.cx+r*math.cos(math.radians(ang))*1.8
            ry=rip.cy+r*math.sin(math.radians(ang))*0.9
            c=lerp(rip.c1,rip.c2,p); c=lerp((0,0,0),c,fade)
            put(int(rx),int(ry),'o' if p<0.5 else '.',c)

    # Fissure rings
    for ring in g.fissure_rings:
        prog=ring.prog(); r=(max(mw,mh)*0.7)*prog
        for ang in range(0,360,6):
            rx=ring.cx+r*math.cos(math.radians(ang))*1.5
            ry=ring.cy+r*math.sin(math.radians(ang))*0.75
            glow=abs(math.sin(prog*math.pi*2+ang*0.05))
            put(int(rx),int(ry),random.choice(['#','|','\\','/']) if random.random()<0.3 else '#',
                lerp((100,40,0),(255,140,30),glow))

    # Landmines
    for m in g.landmines:
        if not m.alive(): continue
        if m.triggered and not m.exploded:
            ft=(now-m.trigger_t)/0.4
            put(m.x,m.y,'!',lerp((180,120,0),(255,220,0),abs(math.sin(ft*math.pi*4))))
        elif not m.triggered:
            d2=math.hypot(g.boss.x-m.x,g.boss.y-m.y) if g.boss.alive else 99
            put(m.x,m.y,'x' if d2<3 else '.',(80,60,30) if d2<3 else (50,40,25))

    # Marionette strings (draw line from player to boss)
    if g.cls_name=="marionette" and g.strings:
        dx=g.boss.x-g.px; dy=g.boss.y-g.py; d=max(1,math.hypot(dx,dy))
        for step in range(1,int(d),2):
            sx=int(g.px+dx/d*step); sy=int(g.py+dy/d*step)
            t=(math.sin(now*5+step*0.3)+1)/2
            put(sx,sy,'─' if abs(dx)>abs(dy) else '│',lerp((180,40,100),(255,100,180),t))

    # Particles
    for p in g.particles:
        put(int(p.x),int(p.y),p.ch,p.clr)

    # Projectiles
    for proj in g.projectiles:
        for i,(tx,ty) in enumerate(proj.trail):
            fade=(i+1)/(len(proj.trail)+1)
            put(tx,ty,'.',lerp((20,0,40),proj.clr,fade))
        put(int(proj.x),int(proj.y),proj.ch,proj.clr)

    # Boss turrets (boss4)
    for turret in g.boss.turrets:
        if turret[2]!='dead':
            put(turret[0],turret[1],'♪',(200,200,80))

    # Mirror clone
    if g.map_key=="mirror" and g.mirror_clone_hp>0 and g.boss.alive:
        cx2=mw-1-int(g.boss.x); cy2=int(g.boss.y)
        t=(math.sin(now*2)+1)/2
        put(cx2,cy2,'@',lerp((100,100,200),(180,180,255),t))

    # Boss hit warning
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

    # Boss (Stonewarden armor visual)
    if g.boss.alive:
        flashing=now<g.boss.flash_until
        for (cx2,cy2) in g.boss.get_cells():
            if flashing:
                prog=max(0,(now-(g.boss.flash_until-0.25))/0.25)
                clr=lerp((255,80,0),(200,100,100),prog)
            elif g.boss.key=="boss2" and g.boss.armor>0:
                clr=lerp((100,100,80),(200,190,140),g.boss.armor/150)
            elif g.boss.key=="boss3":
                t=(math.sin(now*2)+1)/2
                clr=lerp((40,80,180),(80,140,255),t)
            else:
                clr=g.boss.color
            put(cx2,cy2,'O',clr)
        bch='@' if not flashing else '!'
        bc=lerp(g.boss.color,(255,255,100),0.4 if flashing else 0)
        put(int(g.boss.x),int(g.boss.y),bch,bc)
        # Submerged boss
        if g.boss.is_submerged():
            t=(math.sin(now*4)+1)/2
            put(int(g.boss.x),int(g.boss.y),'~',lerp((40,80,160),(80,140,255),t))

    # Wizard ultimate whirlpool
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

    # GD ultimate grey overlay
    if g.gd_ult_active:
        intensity=min(1.0,(now-g.gd_ult_start)/0.3)
        for y in range(1,mh-1):
            for x in range(1,mw-1):
                if (x,y) in buf:
                    ch2,fc,bc=buf[(x,y)]
                    avg=int((fc[0]+fc[1]+fc[2])/3)
                    buf[(x,y)]=(ch2,lerp(fc,(avg,avg,avg),intensity*0.7),bc)

    # Player
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

    # Revenant: burning trail on last life
    if g.cls_name=="revenant" and g.lives==1:
        if random.random()<0.3:
            g.particles.append(Particle(g.px,g.py,random.uniform(-0.5,0.5),-1,'▲',(220,100,30),0.4))

    # ── Build output string ────────────────────────────────────────────────────
    tw,th=get_term_size()
    offset_x=max(0,(tw-mw)//2)
    offset_y=1  # leave row 0 for title/HP

    out=HIDE

    # HP bar row
    hp_ratio=max(0,g.hp/g.max_hp)
    hp_clr=lerp((255,50,50),(50,220,80),hp_ratio)

    # Player HP
    if g.cls_name=="revenant":
        php=f"HP:{g.hp}/{60}  Lives:{'♥'*g.lives}{'♡'*(5-g.lives)}  Rage:{g.rage_stacks}"
    else:
        php=f"HP:{g.hp}/{g.max_hp}"

    # Boss HP — fixed width to avoid bleed
    if g.boss.alive:
        bhp=f"BOSS:{g.boss.hp}/{g.boss.max_hp}"
        if g.boss.key=="boss2" and g.boss.armor>0:
            bhp+=f"  Armor:{g.boss.armor}"
    else:
        bhp="BOSS: DEFEATED"

    out+=at(offset_x,0)+fg(*hp_clr)+BOLD+php+RST
    # Right-align boss HP
    boss_x=offset_x+mw-len(bhp)
    out+=at(boss_x,0)+fg(*lerp((255,100,100),(100,220,80),g.boss.hp/max(1,g.boss.max_hp)))+BOLD+bhp+RST
    # Blank the rest of the HP row to prevent bleeding
    out+=at(offset_x+len(php),0)+fg(0,0,0)+" "*(boss_x-offset_x-len(php))+RST

    # Map rows
    for row in range(mh):
        line=""
        for col in range(mw):
            ch2,fc,_=buf.get((col,row),('.',floor_clr,None))
            line+=fg(*fc)+ch2
        line+=RST
        out+=at(offset_x,offset_y+row)+line

    # HUD rows (below map)
    hud_y=offset_y+mh
    # Clear HUD area first (prevents ghosting)
    for i in range(4):
        out+=at(0,hud_y+i)+" "*tw+RST

    # Move bar
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

    # Dash CD
    dcd=g.dash_ready-now2
    if dcd>0:
        out+=at(offset_x,hud_y+1)+fg(70,70,70)+f"[Q:Dash {dcd:.1f}s]"+RST
    else:
        out+=at(offset_x,hud_y+1)+fg(100,200,100)+f"[Q:Dash ready]"+RST

    # Boss4 beat bar
    if g.boss.key=="boss4" and g.boss.alive:
        blen=30; bfill=int(blen*g.boss.beat_phase)
        beat_bar="BEAT:[" + "█"*bfill + "░"*(blen-bfill)+"]"
        bc2=lerp((100,100,80),(255,220,50),g.boss.beat_phase)
        out+=at(offset_x+mw-len(beat_bar)-2,hud_y+1)+fg(*bc2)+beat_bar+RST

    # Mid-screen messages
    for msg in g.messages:
        text,born,dur,mx2,my2,mc=msg
        age=now2-born; fade=1.0-age/dur
        if fade>0:
            c=lerp((20,20,30),mc,fade)
            sy=offset_y+my2; sx=offset_x+mx2-len(text)//2
            if 0<=sy<th and 0<=sx<tw:
                out+=at(sx,sy)+fg(*c)+BOLD+text+RST

    # Game over / victory
    if g.game_over:
        msg2="GAME OVER  —  press ESC"
        cx2=offset_x+mw//2-len(msg2)//2
        out+=at(cx2,offset_y+mh//2)+fg(255,50,50)+BOLD+msg2+RST
    elif g.victory:
        msg2=f"VICTORY!  +{g.earned_coins} coins  —  press ESC"
        cx2=offset_x+mw//2-len(msg2)//2
        out+=at(cx2,offset_y+mh//2)+fg(50,255,100)+BOLD+msg2+RST

    out_buf.append(out)
