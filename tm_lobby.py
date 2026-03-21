"""tm_lobby.py — TillyMagic multiplayer lobby screens.

flow:
  menu_main (tm_menus) → menu_multiplayer_root
      → menu_host_lobby   (host path)
      → menu_join_browse  (join path: UDP list + manual IP)
      → menu_waiting      (joiner waits for host to start)
  on game start:
      host:   runs full singleplayer-style menus (class, boss, map, size)
              then calls send_game_start() and launches the game
      joiner: runs menu_class_select_mp (class only)
              then menu_waiting until MSG_GAME_START arrives
  on game over / retry:
      menu_retry_host / menu_retry_join

spectate:
  pressing ESC / 'b' during spectate → menu_spectate_confirm
"""

import threading
from tm_core import *
from tm_menus  import (write, box, center_text, animated_title,
                        shimmer_bar, draw_particles, make_particles,
                        tick_particles, menu_class_select, menu_boss_select,
                        menu_map_select, menu_size_select)
from tm_network import (
    NetworkHost, NetworkClient, DiscoveryListener, NetGameState,
    PLAYER_SYMBOLS, NET_TCP_PORT,
    MSG_PLAYER_JOIN, MSG_PLAYER_DROP, MSG_GAME_START, MSG_GAME_OVER,
    STATUS_ALIVE, STATUS_DOWNED, STATUS_SPECTATE,
    get_local_ip,
)

# ── palette ───────────────────────────────────────────────────────────────────
_C_HOST   = (120, 200, 120)   # green — host actions
_C_JOIN   = (100, 160, 220)   # blue  — join actions
_C_WARN   = (220, 140,  40)   # amber — warnings
_C_DEAD   = (180,  40,  40)   # red   — dead/error
_C_DIM    = ( 60,  60,  75)   # dim   — inactive text
_C_GOLD   = (200, 170,  50)   # gold  — coins / highlights
_C_BORDER = ( 55,  55,  75)   # box borders (unselected)


# ── small shared helpers ──────────────────────────────────────────────────────

def _write(s):
    sys.stdout.write(s); sys.stdout.flush()

def _key_nav(keys, sel, n):
    """apply w/s / arrow navigation to sel within n items. returns new sel."""
    for k in keys:
        if k in ('w', 'UP'):   sel = (sel - 1) % n
        if k in ('s', 'DOWN'): sel = (sel + 1) % n
    return sel

def _confirmed(keys):
    return any(k in (' ', '\r', '\n') for k in keys)

def _cancelled(keys):
    return any(k in ('\x1b', '\x03') for k in keys)

def _slot_color(symbol: str) -> tuple:
    """return a distinct color for each player symbol."""
    return {
        '@': (120, 200, 120),
        '$': (100, 160, 220),
        '%': (220, 140,  40),
        '&': (200,  80, 180),
    }.get(symbol, (180, 180, 180))

def _status_str(status: str) -> str:
    return {'alive': 'ALIVE', 'downed': 'DOWNED', 'spectate': 'SPECTATING'}.get(status, status)


# ── menu_multiplayer_root ─────────────────────────────────────────────────────

def menu_multiplayer_root(inp):
    """
    first multiplayer screen: Host Game / Join Game / Back.
    returns 'host' | 'join' | None.
    """
    options = ["Host Game", "Join Game", "Back"]
    sel = 0
    particles = make_particles(30, *get_term_size())
    last = time.time()

    while True:
        now  = time.time()
        dt   = now - last; last = now
        tw, th = get_term_size()
        tick_particles(particles, dt, tw, th)

        inp.read(); keys = inp.get_single()
        sel = _key_nav(keys, sel, len(options))
        for k in keys:
            if k in (' ', '\r', '\n'):
                choice = options[sel]
                if choice == "Back":      return None
                if choice == "Host Game": return 'host'
                if choice == "Join Game": return 'join'
            if _cancelled([k]):           return None

        out = CLR + HIDE
        out += draw_particles(particles, tw, th)
        out += animated_title(now, th//2 - 7)
        out += center_text("── MULTIPLAYER ──", th//2 - 5, (120, 60, 180))

        colors = [_C_HOST, _C_JOIN, _C_DIM]
        for i, opt in enumerate(options):
            y = th//2 - 2 + i*2
            out += shimmer_bar(f"  {opt}  ", y,
                               colors[i], lerp(colors[i], (50,50,65), 0.65),
                               i == sel)

        out += center_text("W/S: navigate   SPACE: select   ESC: back",
                           th - 2, _C_DIM)
        _write(out)
        time.sleep(0.033)


# ── menu_host_lobby ───────────────────────────────────────────────────────────

def menu_host_lobby(inp, save) -> dict | None:
    """
    host waits for players to join. shows:
      - local IP for manual joins
      - live player list (symbol, slot, status)
      - [Start Game] and [Kick] options
      - [Back] cancels and stops the host

    returns a dict:
      {
        'net':      NetGameState,
        'host':     NetworkHost,
        'cls':      str,            # host's chosen class (picked after lobby)
        'boss':     str,
        'map_key':  str,
        'size_mult':float,
        'size_coin_mult': float,
      }
    or None on cancel.
    """
    host      = NetworkHost("TillyMagic")
    net_state = NetGameState(host=host)
    host.start()
    local_ip  = get_local_ip()

    particles = make_particles(25, *get_term_size())
    last = time.time()
    sel  = 0   # 0=Start, 1=Back; kick handled separately
    kick_sel = -1   # which player slot is selected for kick (-1 = none)
    msg  = ""
    msg_until = 0.0

    while True:
        now  = time.time()
        dt   = now - last; last = now
        tw, th = get_term_size()
        tick_particles(particles, dt, tw, th)

        # drain network inbox
        for item in net_state.poll():
            # host inbox yields (pid, msg) tuples
            pid, nmsg = item if isinstance(item, tuple) else (None, item)
            if nmsg.get("t") == MSG_PLAYER_JOIN:
                msg = f"Player {nmsg.get('symbol','')} joined!"
                msg_until = now + 2.5
            elif nmsg.get("t") == MSG_PLAYER_DROP:
                msg = f"Player {nmsg.get('pid','')} disconnected."
                msg_until = now + 2.5

        inp.read(); keys = inp.get_single()

        with host._lock:
            slots = list(host.slots)
        n_players = len(slots)

        # navigation between buttons
        for k in keys:
            if k in ('w', 'UP'):   sel = (sel - 1) % 2
            if k in ('s', 'DOWN'): sel = (sel + 1) % 2

        for k in keys:
            if _cancelled([k]):
                host.stop()
                return None

            if k in (' ', '\r', '\n'):
                if sel == 1:   # Back
                    host.stop()
                    return None

                if sel == 0:   # Start Game
                    if n_players < 1:
                        msg = "Need at least 1 player!"
                        msg_until = now + 2.0
                        break

                    # host picks class, boss, map, size
                    cls_name = menu_class_select(inp)
                    if cls_name is None:
                        continue

                    boss_key = menu_boss_select(inp)
                    if boss_key is None:
                        continue

                    map_key = menu_map_select(inp)
                    if map_key is None:
                        continue

                    size_mult, size_coin_mult = menu_size_select(inp, map_key)
                    if size_mult is None:
                        continue

                    # assign host's class to slot 0
                    with host._lock:
                        host.slots[0].cls_name = cls_name

                    # tell all clients the game is starting
                    host.send_game_start(boss_key, map_key, size_mult)

                    return {
                        'net':            net_state,
                        'host':           host,
                        'cls':            cls_name,
                        'boss':           boss_key,
                        'map_key':        map_key,
                        'size_mult':      size_mult,
                        'size_coin_mult': size_coin_mult,
                    }

        # ── render ────────────────────────────────────────────────────────────
        out = CLR + HIDE
        out += draw_particles(particles, tw, th)
        out += animated_title(now, 1)
        out += center_text("── HOST LOBBY ──", 3, _C_HOST)

        # IP panel
        ip_str = f"Your IP:  {local_ip}:{NET_TCP_PORT}"
        out += center_text(ip_str, 5, _C_GOLD)
        out += center_text("Other players can use this address to join manually.",
                           6, _C_DIM)

        # player list box
        list_h = max(6, n_players + 3)
        list_w = 46
        lx = max(1, (tw - list_w)//2)
        out += box(lx, 8, list_w, list_h, _C_BORDER, title=" Players ")

        for i, slot in enumerate(slots):
            sc = _slot_color(slot.symbol)
            sym_str = slot.symbol
            cls_str = (slot.cls_name or "—").ljust(12)
            status  = _status_str(slot.status)
            tag     = "[HOST]" if slot.slot == 0 else f"Slot {slot.slot+1}"
            conn_str = "connected" if (slot.conn or slot.slot == 0) else "reconnecting..."
            line = f"  {sym_str}  {cls_str}  {tag:<8}  {conn_str}"
            out += at(lx+1, 9+i) + fg(*sc) + line[:list_w-2] + RST

        # buttons
        btn_y = 8 + list_h + 1
        start_clr = lerp(_C_HOST, (255,255,255), 0.3*(math.sin(now*3)+1)/2) if sel==0 else _C_DIM
        back_clr  = lerp(_C_DEAD, (255,255,255), 0.2) if sel==1 else _C_DIM
        out += center_text("[ Start Game ]", btn_y,     start_clr, bold=(sel==0))
        out += center_text("[ Back ]",       btn_y + 2, back_clr,  bold=(sel==1))

        # hint
        p_count_str = f"{n_players}/{4} players"
        out += center_text(p_count_str, btn_y + 4, _C_DIM)

        # flash message
        if now < msg_until:
            fade = min(1.0, (msg_until - now) / 0.5)
            mc   = lerp((20,20,30), _C_WARN, fade)
            out += center_text(msg, btn_y + 6, mc)

        out += center_text("W/S: navigate   SPACE: confirm   ESC: cancel",
                           th - 2, _C_DIM)
        _write(out)
        time.sleep(0.033)


# ── menu_join_browse ──────────────────────────────────────────────────────────

def menu_join_browse(inp) -> dict | None:
    """
    client side: shows UDP-discovered games + manual IP entry.
    returns {'net': NetGameState, 'client': NetworkClient, 'symbol': str}
    or None on cancel.
    """
    listener = DiscoveryListener()
    listener.start()

    client    = None
    net_state = None
    particles = make_particles(25, *get_term_size())
    last      = time.time()
    sel       = 0    # index in game list; len = manual IP option
    manual_ip = ""
    typing_ip = False   # True when user is typing into the IP field
    msg       = ""
    msg_until = 0.0

    def _try_connect(ip: str):
        nonlocal client, net_state, msg, msg_until
        c = NetworkClient()
        msg = f"Connecting to {ip}..."
        msg_until = time.time() + 99
        if c.connect(ip):
            client    = c
            net_state = NetGameState(client=c)
            msg = "Connected! Waiting for host..."
            msg_until = time.time() + 99
            return True
        else:
            msg = f"Could not connect to {ip}"
            msg_until = time.time() + 3.0
            return False

    while True:
        now  = time.time()
        dt   = now - last; last = now
        tw, th = get_term_size()
        tick_particles(particles, dt, tw, th)

        # if already connected, drain inbox waiting for PLAYER_JOIN
        if client and net_state:
            for nmsg in net_state.poll():
                t = nmsg.get("t") if isinstance(nmsg, dict) else nmsg[1].get("t")
                if isinstance(nmsg, tuple): nmsg = nmsg[1]
                if nmsg.get("t") == MSG_PLAYER_JOIN and client.pid:
                    # successfully assigned a slot — move to waiting room
                    listener.stop()
                    return {
                        'net':    net_state,
                        'client': client,
                        'symbol': client.symbol or '?',
                        'pid':    client.pid,
                    }
                if nmsg.get("t") == "REJECT":
                    msg = "Lobby is full."
                    msg_until = now + 3.0
                    client.disconnect()
                    client = None; net_state = None

        games = listener.games()
        # list items: discovered games + "[Enter IP manually]"
        n_items = len(games) + 1
        manual_idx = len(games)

        inp.read(); keys = inp.get_single()

        if typing_ip:
            # capture keystrokes for manual IP entry
            for k in keys:
                if k in ('\r', '\n'):
                    typing_ip = False
                    if manual_ip.strip():
                        threading.Thread(
                            target=_try_connect,
                            args=(manual_ip.strip(),),
                            daemon=True
                        ).start()
                elif k == '\x7f':   # backspace
                    manual_ip = manual_ip[:-1]
                elif k == '\x1b':
                    typing_ip = False
                elif len(k) == 1 and k.isprintable():
                    manual_ip += k
        else:
            sel = _key_nav(keys, sel, n_items)
            for k in keys:
                if _cancelled([k]):
                    listener.stop()
                    if client: client.disconnect()
                    return None
                if k in (' ', '\r', '\n'):
                    if sel == manual_idx:
                        typing_ip = True
                    elif sel < len(games):
                        g = games[sel]
                        ip = g.get("ip", "")
                        threading.Thread(
                            target=_try_connect, args=(ip,), daemon=True
                        ).start()

        # ── render ────────────────────────────────────────────────────────────
        out = CLR + HIDE
        out += draw_particles(particles, tw, th)
        out += animated_title(now, 1)
        out += center_text("── JOIN A GAME ──", 3, _C_JOIN)

        list_h = max(8, n_items + 3)
        list_w = 56
        lx = max(1, (tw - list_w)//2)
        out += box(lx, 5, list_w, list_h, _C_BORDER, title=" Games on Network ")

        # discovered games
        for i, g in enumerate(games):
            is_sel = (i == sel and not typing_ip)
            pc = g.get("players", 0); mp = g.get("max_players", 4)
            name = g.get("game", "TillyMagic")
            ip   = g.get("ip", "?")
            line = f"  {name}  {ip}  [{pc}/{mp} players]"
            clr  = lerp(_C_JOIN, (255,255,255), 0.4) if is_sel else _C_DIM
            out += at(lx+1, 6+i) + fg(*clr) + (("▶ " if is_sel else "  ") + line)[:list_w-2] + RST

        if not games:
            out += at(lx+2, 7) + fg(*_C_DIM) + "  No games found on network..." + RST

        # manual IP row
        mi_y = 6 + max(1, len(games))
        is_mi_sel = (sel == manual_idx and not typing_ip) or typing_ip
        if typing_ip:
            cursor = "_" if int(now*3)%2==0 else " "
            ip_disp = f"  IP: {manual_ip}{cursor}"
            out += at(lx+1, mi_y) + fg(*_C_GOLD) + BOLD + ip_disp[:list_w-2] + RST
        else:
            mi_clr = lerp(_C_GOLD,(255,255,255),0.4) if is_mi_sel else _C_DIM
            out += at(lx+1, mi_y) + fg(*mi_clr) + ("▶ " if is_mi_sel else "  ") + "Enter IP manually..." + RST

        # status message
        btn_y = 5 + list_h + 1
        if now < msg_until and msg:
            fade = min(1.0, (msg_until-now)/0.4) if msg_until - now < 0.4 else 1.0
            # connecting message pulses
            if "Connecting" in msg or "Waiting" in msg:
                t_p = (math.sin(now*3)+1)/2
                mc  = lerp(_C_JOIN, (200,240,255), t_p)
            else:
                mc  = lerp((20,20,30), _C_WARN, fade)
            out += center_text(msg, btn_y, mc)

        hint = "SPACE: select   TYPE: enter IP   ESC: back"
        if typing_ip:
            hint = "Type IP address   ENTER: connect   ESC: cancel"
        out += center_text(hint, th-2, _C_DIM)
        _write(out)
        time.sleep(0.033)


# ── menu_waiting ──────────────────────────────────────────────────────────────

def menu_waiting(inp, net_state: NetGameState, symbol: str, pid: str) -> dict | None:
    """
    joiner waits after class select. host hasn't pressed Start yet.
    polls inbox for MSG_GAME_START.
    returns the GAME_START message dict, or None if cancelled / host gone.
    """
    client    = net_state.client
    particles = make_particles(20, *get_term_size())
    last      = time.time()
    dot_count = 0
    dot_timer = 0.0

    while True:
        now  = time.time()
        dt   = now - last; last = now
        tw, th = get_term_size()
        tick_particles(particles, dt, tw, th)

        # check inbox
        for nmsg in net_state.poll():
            if isinstance(nmsg, tuple): nmsg = nmsg[1]
            if nmsg.get("t") == MSG_GAME_START:
                return nmsg
            if nmsg.get("t") == "HOST_GONE":
                return None
            # keep remote_players updated while waiting
            if nmsg.get("t") == MSG_PLAYER_JOIN:
                net_state.remote_players[nmsg["pid"]] = nmsg

        inp.read(); keys = inp.get_single()
        if _cancelled(keys):
            client.disconnect()
            return None

        # ping keepalive
        net_state.tick_ping()

        # animated dots
        dot_timer += dt
        if dot_timer >= 0.4:
            dot_timer = 0.0
            dot_count = (dot_count + 1) % 4

        # host alive check
        host_ok = client.host_alive() if client else False

        # ── render ────────────────────────────────────────────────────────────
        out = CLR + HIDE
        out += draw_particles(particles, tw, th)
        out += animated_title(now, th//2 - 8)

        sc = _slot_color(symbol)
        out += center_text(f"Joined as  '{symbol}'", th//2 - 5, sc)

        dots = "." * dot_count + " " * (3 - dot_count)
        wait_clr = lerp(_C_JOIN, (200,240,255), (math.sin(now*2)+1)/2)
        out += center_text(f"Waiting for host{dots}", th//2 - 3, wait_clr)

        if not host_ok:
            t_w = (math.sin(now*4)+1)/2
            out += center_text("Host connection lost — reconnecting...",
                               th//2 - 1, lerp(_C_WARN,(255,200,80),t_w))

        # show other players already in the lobby
        others = list(net_state.remote_players.values())
        if others:
            out += center_text("── In lobby ──", th//2+1, _C_DIM)
            for i, p in enumerate(others[:4]):
                ps  = p.get("symbol","?")
                pc  = _slot_color(ps)
                cls = p.get("cls_name") or "selecting..."
                out += center_text(f"{ps}  {cls}", th//2+2+i, pc)

        out += center_text("ESC: leave lobby", th-2, _C_DIM)
        _write(out)
        time.sleep(0.033)


# ── menu_class_select_mp ──────────────────────────────────────────────────────

def menu_class_select_mp(inp, net_state: NetGameState, symbol: str) -> str | None:
    """
    multiplayer version of class select. after confirming, sends the choice
    to the host (or stores it locally for the host). identical visually to
    the singleplayer version but also broadcasts the selection.
    """
    cls = menu_class_select(inp)
    if cls is None:
        return None

    # client: tell host our class choice
    if net_state.client:
        net_state.client.send({
            "t":        "CLASS_SELECT",
            "pid":      net_state.client.pid,
            "cls_name": cls,
        })

    return cls


# ── menu_spectate_confirm ─────────────────────────────────────────────────────

def menu_spectate_confirm(inp) -> bool:
    """
    shown when a spectating player presses ESC / B.
    'Are you sure you want to leave? You can rejoin anytime.'
    returns True = exit, False = stay.
    """
    options = ["Stay", "Exit"]
    sel = 0
    particles = make_particles(15, *get_term_size())
    last = time.time()

    while True:
        now  = time.time()
        dt   = now - last; last = now
        tw, th = get_term_size()
        tick_particles(particles, dt, tw, th)

        inp.read(); keys = inp.get_single()
        sel = _key_nav(keys, sel, len(options))
        for k in keys:
            if k in (' ', '\r', '\n'):
                return (options[sel] == "Exit")
            if _cancelled([k]):
                return False   # default: stay

        out = CLR + HIDE
        out += draw_particles(particles, tw, th)

        # modal box
        bw, bh = 50, 9
        bx = (tw - bw)//2; by = th//2 - bh//2
        out += box(bx, by, bw, bh, _C_WARN, title=" Leave Game? ")

        out += at(bx+2, by+2) + fg(200,200,200) + "Are you sure you want to leave?" + RST
        out += at(bx+2, by+3) + fg(*_C_DIM) + "You can rejoin anytime as a spectator." + RST

        colors = [_C_HOST, _C_DEAD]
        for i, opt in enumerate(options):
            y   = by + 5 + i
            clr = lerp(colors[i],(255,255,255),0.35) if i==sel else _C_DIM
            prefix = "▶ " if i==sel else "  "
            out += center_text(prefix + opt, y, clr, bold=(i==sel))

        out += center_text("W/S: navigate   SPACE: confirm", th-2, _C_DIM)
        _write(out)
        time.sleep(0.033)


# ── menu_retry_host ───────────────────────────────────────────────────────────

def menu_retry_host(inp, host: NetworkHost, save) -> dict | None:
    """
    shown to host after game over. options: Retry / Back to Menu.
    on retry: host picks class/boss/map/size again, sends GAME_START.
    returns same structure as menu_host_lobby, or None for main menu.
    """
    options = ["Retry", "Back to Menu"]
    sel = 0
    particles = make_particles(20, *get_term_size())
    last = time.time()

    while True:
        now  = time.time()
        dt   = now - last; last = now
        tw, th = get_term_size()
        tick_particles(particles, dt, tw, th)

        inp.read(); keys = inp.get_single()
        sel = _key_nav(keys, sel, len(options))
        for k in keys:
            if _cancelled([k]):
                host.stop()
                return None
            if k in (' ', '\r', '\n'):
                if options[sel] == "Back to Menu":
                    host.stop()
                    return None

                # Retry: pick game options again
                cls_name = menu_class_select(inp)
                if cls_name is None: continue
                boss_key = menu_boss_select(inp)
                if boss_key is None: continue
                map_key  = menu_map_select(inp)
                if map_key is None: continue
                size_mult, size_coin_mult = menu_size_select(inp, map_key)
                if size_mult is None: continue

                with host._lock:
                    host.slots[0].cls_name = cls_name
                    # reset all player statuses for the new round
                    for sl in host.slots:
                        sl.status = STATUS_ALIVE
                        sl.downed_at = None
                        sl.revive_by = None

                host.send_game_start(boss_key, map_key, size_mult)

                return {
                    'net':            NetGameState(host=host),
                    'host':           host,
                    'cls':            cls_name,
                    'boss':           boss_key,
                    'map_key':        map_key,
                    'size_mult':      size_mult,
                    'size_coin_mult': size_coin_mult,
                }

        # ── render ────────────────────────────────────────────────────────────
        out = CLR + HIDE
        out += draw_particles(particles, tw, th)
        out += animated_title(now, th//2 - 6)
        out += center_text("── GAME OVER ──", th//2 - 4, _C_DEAD)

        colors = [_C_HOST, _C_DIM]
        for i, opt in enumerate(options):
            y = th//2 - 1 + i*2
            out += shimmer_bar(f"  {opt}  ", y,
                               colors[i], lerp(colors[i],(50,50,65),0.65),
                               i == sel)

        out += center_text("W/S: navigate   SPACE: confirm   ESC: main menu",
                           th-2, _C_DIM)
        _write(out)
        time.sleep(0.033)


# ── menu_retry_join ───────────────────────────────────────────────────────────

def menu_retry_join(inp, net_state: NetGameState, symbol: str, pid: str) -> dict | None:
    """
    shown to joiners after game over. they pick class again, then wait.
    returns MSG_GAME_START dict on new round, or None to quit.
    """
    options = ["Select Class & Wait", "Back to Menu"]
    sel = 0
    particles = make_particles(20, *get_term_size())
    last = time.time()

    while True:
        now  = time.time()
        dt   = now - last; last = now
        tw, th = get_term_size()
        tick_particles(particles, dt, tw, th)

        inp.read(); keys = inp.get_single()
        sel = _key_nav(keys, sel, len(options))
        for k in keys:
            if _cancelled([k]):
                net_state.client.disconnect()
                return None
            if k in (' ', '\r', '\n'):
                if options[sel] == "Back to Menu":
                    net_state.client.disconnect()
                    return None

                cls = menu_class_select_mp(inp, net_state, symbol)
                if cls is None: continue

                # wait for host to start
                start_msg = menu_waiting(inp, net_state, symbol, pid)
                return start_msg   # None if host gone, dict if game starting

        out = CLR + HIDE
        out += draw_particles(particles, tw, th)
        out += animated_title(now, th//2 - 6)
        out += center_text("── ROUND OVER ──", th//2 - 4, _C_DEAD)

        sc = _slot_color(symbol)
        out += center_text(f"You are playing as  '{symbol}'", th//2 - 2, sc)

        colors = [_C_JOIN, _C_DIM]
        for i, opt in enumerate(options):
            y = th//2 + i*2
            out += shimmer_bar(f"  {opt}  ", y,
                               colors[i], lerp(colors[i],(50,50,65),0.65),
                               i == sel)

        out += center_text("W/S: navigate   SPACE: confirm   ESC: main menu",
                           th-2, _C_DIM)
        _write(out)
        time.sleep(0.033)


# ── menu_host_waiting_for_join_class ─────────────────────────────────────────

def menu_host_collect_classes(inp, host: NetworkHost, timeout: float = 30.0):
    """
    called AFTER host sends GAME_START. waits for joiners to send CLASS_SELECT.
    only waits for non-host slots (slot index > 0). host already has cls_name set.
    exits early when all joiner slots have a class, or on ESC, or on timeout.
    """
    import queue as _queue

    particles = make_particles(15, *get_term_size())
    last      = time.time()
    deadline  = time.time() + timeout

    def _joiners_ready():
        with host._lock:
            # only check slots 1+ (slot 0 = host, already has cls_name)
            joiners = [s for s in host.slots if s.slot > 0]
            if not joiners:
                return True   # no joiners — nothing to wait for
            return all(s.cls_name for s in joiners)

    while time.time() < deadline and not _joiners_ready():
        now  = time.time()
        dt   = now - last; last = now
        tw, th = get_term_size()
        tick_particles(particles, dt, tw, th)

        # drain the entire inbox — process every pending message
        drained = []
        while True:
            try:
                drained.append(host.inbox.get_nowait())
            except _queue.Empty:
                break
        for pid, nmsg in drained:
            if nmsg.get("t") == "CLASS_SELECT":
                slot = host.get_slot(pid)
                if slot:
                    slot.cls_name = nmsg.get("cls_name", "wizard")

        if _joiners_ready():
            break

        inp.read(); keys = inp.get_single()
        if _cancelled(keys):
            break

        out = CLR + HIDE
        out += draw_particles(particles, tw, th)
        out += animated_title(now, th//2 - 5)

        with host._lock:
            slots = list(host.slots)

        t_p = (math.sin(now*2)+1)/2
        wc  = lerp(_C_HOST,(200,255,200),t_p)
        out += center_text("Waiting for players to select class...", th//2-3, wc)

        for i, s in enumerate(slots):
            sc    = _slot_color(s.symbol)
            ready = s.cls_name or "selecting..."
            tag   = "[HOST]" if s.slot == 0 else f"Slot {s.slot+1}"
            out  += center_text(f"{s.symbol}  {tag:<8}  {ready}", th//2-1+i, sc)

        out += center_text("ESC: start anyway", th-2, _C_DIM)
        _write(out)
        time.sleep(0.05)

    # fallback: assign wizard to any joiner slot still missing a class
    with host._lock:
        for s in host.slots:
            if not s.cls_name:
                s.cls_name = "wizard"
