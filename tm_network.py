"""tm_network.py — TillyMagic multiplayer network layer.

Architecture:
  - one player is HOST, up to 3 others are CLIENTS.
  - host owns all authoritative game state: boss hp, damage resolution,
    collision, boss AI. clients send only inputs and receive state.
  - TCP port 7771: reliable in-game messages (damage, actions, death, sync).
  - UDP port 7772: discovery broadcasts. host announces; clients listen.
  - all messages are newline-delimited json for simplicity and debuggability.
  - a background thread handles all socket i/o; a queue delivers messages
    to the main game loop without blocking the render thread.

player symbols (fixed pool, assigned in join order):
  host = '@', first joiner = '$', second = '%', third = '&'

boss scaling by player count:
  hp multiplier:    2.5x / 3.5x / 4.5x (2 / 3 / 4 players)
  speed multiplier: 1.15x / 1.25x / 1.35x

revival time by player count (seconds to revive a downed player):
  2 players: 6s, 3 players: 8s, 4 players: 10s
"""

import socket, threading, queue, json, time, random, logging
from typing import Optional

# ── constants ─────────────────────────────────────────────────────────────────

NET_TCP_PORT      = 7771          # reliable game channel
NET_UDP_PORT      = 7772          # discovery broadcast
NET_BROADCAST     = "<broadcast>" # udp broadcast address
NET_DISCOVERY_INT = 1.5           # seconds between host broadcast announcements
NET_BUF           = 4096          # tcp recv buffer size
NET_MAX_PLAYERS   = 4

# timeouts
HOST_DROP_TIMEOUT   = 30.0   # seconds before clients give up on lost host
CLIENT_DROP_TIMEOUT = 60.0   # seconds before host drops a silent client
RECONNECT_GRACE     = 60.0   # how long a disconnected player's slot stays open

# player symbol pool — index = player slot (0=host, 1-3=joiners)
PLAYER_SYMBOLS = ['@', '$', '%', '&']

# boss scaling tables indexed by player_count-1 (index 0 = solo, unused by net layer)
BOSS_HP_MULT    = [1.0, 2.5, 3.5, 4.5]   # [solo, 2p, 3p, 4p]
BOSS_SPEED_MULT = [1.0, 1.15, 1.25, 1.35]

# revival seconds by player count
REVIVAL_TIME = [0, 0, 6, 8, 10]   # index = player_count

# ── message types ─────────────────────────────────────────────────────────────
# all messages are dicts with a "t" (type) field.
# clients send:  MOVE, ACTION, PING
# host sends:    SYNC, FLOATER, BOSS_HP, PLAYER_STATE, PLAYER_JOIN,
#                PLAYER_DROP, REVIVE_START, REVIVE_CANCEL, DOWNED,
#                SPECTATE, GAME_START, GAME_OVER, PONG

MSG_MOVE         = "MOVE"          # {t, pid, x, y}
MSG_ACTION       = "ACTION"        # {t, pid, move_num, bx, by}
MSG_PING         = "PING"          # {t, pid, ts}
MSG_PONG         = "PONG"          # {t, ts}
MSG_SYNC         = "SYNC"          # {t, boss_hp, boss_x, boss_y, players:[...]}
MSG_FLOATER      = "FLOATER"       # {t, x, y, amount, clr}
MSG_BOSS_HP      = "BOSS_HP"       # {t, hp, max_hp}
MSG_BOSS_STATE   = "BOSS_STATE"    # {t, x, y, hp, stun_until, flash_until}
MSG_PLAYER_STATE = "PLAYER_STATE"  # {t, pid, x, y, hp, max_hp, status}
MSG_PLAYER_JOIN  = "PLAYER_JOIN"   # {t, pid, symbol, cls_name, slot}
MSG_PLAYER_DROP  = "PLAYER_DROP"   # {t, pid, reason}
MSG_DOWNED       = "DOWNED"        # {t, pid}
MSG_SPECTATE     = "SPECTATE"      # {t, pid}
MSG_REVIVE_START = "REVIVE_START"  # {t, pid, by_pid}
MSG_REVIVE_DONE  = "REVIVE_DONE"   # {t, pid, hp}
MSG_REVIVE_FAIL  = "REVIVE_FAIL"   # {t, pid}  (timer ran out → spectator)
MSG_GAME_START   = "GAME_START"    # {t, boss_key, map_key, size_mult, players:[...]}
MSG_GAME_OVER    = "GAME_OVER"     # {t, reason}
MSG_CHAT         = "CHAT"          # {t, pid, text}  (future use)
MSG_HOST_MIGRATE = "HOST_MIGRATE"  # reserved — not implemented in v1

# player status values
STATUS_ALIVE     = "alive"
STATUS_DOWNED    = "downed"
STATUS_SPECTATE  = "spectate"


# ── helpers ───────────────────────────────────────────────────────────────────

def _encode(msg: dict) -> bytes:
    """encode a message dict to a newline-terminated utf-8 bytes object."""
    return (json.dumps(msg, separators=(',', ':')) + '\n').encode('utf-8')

def _decode(raw: str) -> Optional[dict]:
    """decode a single json line. returns None on parse error."""
    try:
        return json.loads(raw.strip())
    except json.JSONDecodeError:
        return None

def get_local_ip() -> str:
    """best-effort local LAN ip address (not 127.0.0.1)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

def boss_hp_multiplier(player_count: int) -> float:
    idx = max(0, min(player_count - 1, len(BOSS_HP_MULT) - 1))
    return BOSS_HP_MULT[idx]

def boss_speed_multiplier(player_count: int) -> float:
    idx = max(0, min(player_count - 1, len(BOSS_SPEED_MULT) - 1))
    return BOSS_SPEED_MULT[idx]

def revival_time(player_count: int) -> float:
    idx = max(0, min(player_count, len(REVIVAL_TIME) - 1))
    return float(REVIVAL_TIME[idx])


# ── player slot ───────────────────────────────────────────────────────────────

class PlayerSlot:
    """tracks one connected player's network state on the host side."""
    def __init__(self, slot: int, pid: str, symbol: str):
        self.slot        = slot          # 0 = host, 1-3 = joiners
        self.pid         = pid           # unique string id
        self.symbol      = symbol        # '@' '$' '%' '&'
        self.cls_name    = None          # chosen class
        self.x           = 0.0
        self.y           = 0.0
        self.hp          = 0
        self.max_hp      = 0
        self.status      = STATUS_ALIVE
        self.last_seen   = time.time()   # updated on every message received
        self.conn        = None          # socket (None for host's own slot)
        self.addr        = None          # (ip, port) for reconnect matching
        self.recv_buf    = ""            # partial line buffer for tcp framing
        self.downed_at   = None          # timestamp when downed, for revival timer
        self.revive_by   = None          # pid of player currently reviving this one

    def to_dict(self) -> dict:
        return {
            "slot":     self.slot,
            "pid":      self.pid,
            "symbol":   self.symbol,
            "cls_name": self.cls_name,
            "x":        round(self.x, 2),
            "y":        round(self.y, 2),
            "hp":       self.hp,
            "max_hp":   self.max_hp,
            "status":   self.status,
        }


# ── UDP discovery ─────────────────────────────────────────────────────────────

class DiscoveryBroadcaster:
    """host side: broadcasts game availability over UDP every NET_DISCOVERY_INT seconds."""

    def __init__(self, game_name: str, host_ip: str, player_count: int, max_players: int):
        self.game_name    = game_name
        self.host_ip      = host_ip
        self.player_count = player_count
        self.max_players  = max_players
        self._stop        = threading.Event()
        self._sock        = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._thread      = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()
        try: self._sock.close()
        except: pass

    def update_count(self, player_count: int):
        self.player_count = player_count

    def _run(self):
        payload = json.dumps({
            "t":            "ANNOUNCE",
            "game":         self.game_name,
            "ip":           self.host_ip,
            "port":         NET_TCP_PORT,
            "players":      self.player_count,
            "max_players":  self.max_players,
        }).encode('utf-8')
        while not self._stop.is_set():
            try:
                self._sock.sendto(payload, (NET_BROADCAST, NET_UDP_PORT))
            except Exception:
                pass
            self._stop.wait(NET_DISCOVERY_INT)


class DiscoveryListener:
    """client side: listens for UDP game announcements. non-blocking poll via found_games."""

    def __init__(self):
        self.found_games  = {}   # ip -> {game info dict, "last_seen": timestamp}
        self._stop        = threading.Event()
        self._sock        = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.settimeout(1.0)
        self._thread      = threading.Thread(target=self._run, daemon=True)

    def start(self):
        try:
            self._sock.bind(('', NET_UDP_PORT))
        except OSError:
            # port already in use (e.g. host on same machine) — still try
            pass
        self._thread.start()

    def stop(self):
        self._stop.set()
        try: self._sock.close()
        except: pass

    def games(self) -> list:
        """return list of recently seen game dicts (seen within last 5s)."""
        now = time.time()
        return [
            g for g in self.found_games.values()
            if now - g["last_seen"] < 5.0
        ]

    def _run(self):
        while not self._stop.is_set():
            try:
                data, addr = self._sock.recvfrom(1024)
                msg = json.loads(data.decode('utf-8'))
                if msg.get("t") == "ANNOUNCE":
                    ip = msg.get("ip", addr[0])
                    msg["last_seen"] = time.time()
                    self.found_games[ip] = msg
            except (socket.timeout, json.JSONDecodeError, OSError):
                pass


# ── network host ──────────────────────────────────────────────────────────────

class NetworkHost:
    """
    runs on the hosting machine. accepts up to 3 client connections.
    owns the authoritative slot list. pumps received messages into
    self.inbox (a queue) for the game loop to consume.
    the game loop calls send_all() / send_to() to push state out.
    """

    def __init__(self, game_name: str = "TillyMagic"):
        self.game_name    = game_name
        self.local_ip     = get_local_ip()
        self.slots        : list[PlayerSlot] = []
        self.inbox        = queue.Queue()   # (pid, msg_dict) tuples
        self._stop        = threading.Event()
        self._lock        = threading.Lock()
        self._server_sock = None
        self._broadcaster : Optional[DiscoveryBroadcaster] = None
        self._accept_thread  = None
        self._watchdog_thread = None

        # create host's own slot
        host_pid    = self._new_pid()
        host_slot   = PlayerSlot(0, host_pid, PLAYER_SYMBOLS[0])
        self.slots.append(host_slot)
        self.host_pid = host_pid

    # ── public api ────────────────────────────────────────────────────────────

    def start(self):
        """open tcp server socket and begin broadcasting."""
        self._server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_sock.bind(('', NET_TCP_PORT))
        self._server_sock.listen(NET_MAX_PLAYERS - 1)
        self._server_sock.settimeout(1.0)

        self._broadcaster = DiscoveryBroadcaster(
            self.game_name, self.local_ip,
            len(self.slots), NET_MAX_PLAYERS
        )
        self._broadcaster.start()

        self._accept_thread   = threading.Thread(target=self._accept_loop, daemon=True)
        self._watchdog_thread = threading.Thread(target=self._watchdog_loop, daemon=True)
        self._accept_thread.start()
        self._watchdog_thread.start()

    def stop(self):
        """shut down all connections cleanly."""
        self._stop.set()
        if self._broadcaster:
            self._broadcaster.stop()
        try: self._server_sock.close()
        except: pass
        with self._lock:
            for slot in self.slots:
                if slot.conn:
                    try: slot.conn.close()
                    except: pass

    def send_all(self, msg: dict, exclude_pid: str = None):
        """send a message to all connected client slots."""
        data = _encode(msg)
        with self._lock:
            for slot in self.slots:
                if slot.pid == self.host_pid:
                    continue   # don't send to self
                if exclude_pid and slot.pid == exclude_pid:
                    continue
                if slot.conn:
                    self._send_raw(slot, data)

    def send_to(self, pid: str, msg: dict):
        """send a message to one specific player."""
        data = _encode(msg)
        with self._lock:
            for slot in self.slots:
                if slot.pid == pid and slot.conn:
                    self._send_raw(slot, data)
                    break

    def player_count(self) -> int:
        with self._lock:
            return len(self.slots)

    def alive_slots(self) -> list:
        with self._lock:
            return [s for s in self.slots if s.status == STATUS_ALIVE]

    def get_slot(self, pid: str) -> Optional[PlayerSlot]:
        with self._lock:
            for s in self.slots:
                if s.pid == pid:
                    return s
        return None

    def update_host_state(self, x: float, y: float, hp: int, max_hp: int):
        """game loop calls this to keep host slot state current."""
        with self._lock:
            s = self.slots[0]
            s.x = x; s.y = y; s.hp = hp; s.max_hp = max_hp
            s.last_seen = time.time()

    def broadcast_sync(self, boss_x: float, boss_y: float, boss_hp: int, boss_max_hp: int):
        """send a full state snapshot to all clients (called every ~2s as safety net)."""
        with self._lock:
            players = [s.to_dict() for s in self.slots]
        msg = {
            "t":          MSG_SYNC,
            "boss_x":     round(boss_x, 2),
            "boss_y":     round(boss_y, 2),
            "boss_hp":    boss_hp,
            "boss_max_hp":boss_max_hp,
            "players":    players,
        }
        self.send_all(msg)

    def broadcast_floater(self, x: float, y: float, amount: int, clr: tuple):
        """send a damage/heal floater to all clients so everyone sees -39 etc."""
        self.send_all({
            "t": MSG_FLOATER,
            "x": round(x, 1), "y": round(y, 1),
            "amount": amount,
            "clr": list(clr),
        })

    def broadcast_boss_hp(self, hp: int, max_hp: int):
        self.send_all({"t": MSG_BOSS_HP, "hp": hp, "max_hp": max_hp})

    def broadcast_boss_state(self, x: float, y: float, hp: int, stun_until: float, flash_until: float):
        self.send_all({
            "t":           MSG_BOSS_STATE,
            "x":           round(x, 2),
            "y":           round(y, 2),
            "hp":          hp,
            "stun_until":  round(stun_until, 3),
            "flash_until": round(flash_until, 3),
        })

    def broadcast_player_state(self, slot: PlayerSlot):
        self.send_all({
            "t":      MSG_PLAYER_STATE,
            "pid":    slot.pid,
            "x":      round(slot.x, 2),
            "y":      round(slot.y, 2),
            "hp":     slot.hp,
            "max_hp": slot.max_hp,
            "status": slot.status,
            "symbol": slot.symbol,
        })

    def notify_downed(self, pid: str):
        self.send_all({"t": MSG_DOWNED, "pid": pid})

    def notify_spectate(self, pid: str):
        self.send_all({"t": MSG_SPECTATE, "pid": pid})

    def notify_revive_start(self, pid: str, by_pid: str):
        self.send_all({"t": MSG_REVIVE_START, "pid": pid, "by_pid": by_pid})

    def notify_revive_done(self, pid: str, hp: int):
        self.send_all({"t": MSG_REVIVE_DONE, "pid": pid, "hp": hp})

    def notify_revive_fail(self, pid: str):
        self.send_all({"t": MSG_REVIVE_FAIL, "pid": pid})

    def send_game_start(self, boss_key: str, map_key: str, size_mult: float):
        with self._lock:
            players = [s.to_dict() for s in self.slots]
        msg = {
            "t":         MSG_GAME_START,
            "boss_key":  boss_key,
            "map_key":   map_key,
            "size_mult": size_mult,
            "players":   players,
        }
        self.send_all(msg)

    def send_game_over(self, reason: str = "all_dead"):
        self.send_all({"t": MSG_GAME_OVER, "reason": reason})

    # ── internal ──────────────────────────────────────────────────────────────

    def _accept_loop(self):
        """accept incoming client connections until stopped or at capacity."""
        while not self._stop.is_set():
            try:
                conn, addr = self._server_sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break

            with self._lock:
                occupied = len(self.slots)

            if occupied >= NET_MAX_PLAYERS:
                # full — reject with a message
                try:
                    conn.sendall(_encode({"t": "REJECT", "reason": "lobby_full"}))
                    conn.close()
                except: pass
                continue

            # check if this is a reconnecting player (same ip as a dropped slot)
            reconnect_slot = self._find_reconnect_slot(addr[0])
            if reconnect_slot:
                self._handle_reconnect(conn, addr, reconnect_slot)
            else:
                self._handle_new_join(conn, addr)

    def _handle_new_join(self, conn, addr):
        with self._lock:
            slot_index = len(self.slots)
            pid    = self._new_pid()
            symbol = PLAYER_SYMBOLS[slot_index]
            slot   = PlayerSlot(slot_index, pid, symbol)
            slot.conn = conn
            slot.addr = addr
            self.slots.append(slot)
            pc = len(self.slots)

        # tell the new player their identity
        conn.sendall(_encode({
            "t":      MSG_PLAYER_JOIN,
            "pid":    pid,
            "symbol": symbol,
            "slot":   slot_index,
        }))

        # tell everyone else a new player joined
        self.send_all({
            "t":      MSG_PLAYER_JOIN,
            "pid":    pid,
            "symbol": symbol,
            "slot":   slot_index,
        }, exclude_pid=pid)

        # update discovery broadcast count
        if self._broadcaster:
            self._broadcaster.update_count(pc)

        # start reading from this connection
        t = threading.Thread(target=self._recv_loop, args=(slot,), daemon=True)
        t.start()

        # notify game loop
        self.inbox.put((pid, {"t": MSG_PLAYER_JOIN, "pid": pid, "symbol": symbol, "slot": slot_index}))

    def _handle_reconnect(self, conn, addr, slot: PlayerSlot):
        """player reconnected — restore their slot."""
        with self._lock:
            slot.conn = conn
            slot.addr = addr
            slot.last_seen = time.time()

        # send them a sync so they have current state immediately
        # (game loop will call broadcast_sync shortly)
        conn.sendall(_encode({
            "t":      "RECONNECT_OK",
            "pid":    slot.pid,
            "symbol": slot.symbol,
            "slot":   slot.slot,
            "status": slot.status,
            "hp":     slot.hp,
        }))

        self.inbox.put((slot.pid, {"t": "RECONNECT", "pid": slot.pid}))

        t = threading.Thread(target=self._recv_loop, args=(slot,), daemon=True)
        t.start()

    def _recv_loop(self, slot: PlayerSlot):
        """read loop for one client connection. runs in its own thread."""
        slot.recv_buf = ""
        while not self._stop.is_set():
            try:
                data = slot.conn.recv(NET_BUF)
                if not data:
                    # clean disconnect
                    break
                slot.recv_buf += data.decode('utf-8', errors='replace')
                slot.last_seen = time.time()
                # process all complete lines
                while '\n' in slot.recv_buf:
                    line, slot.recv_buf = slot.recv_buf.split('\n', 1)
                    msg = _decode(line)
                    if msg:
                        self.inbox.put((slot.pid, msg))
            except (ConnectionResetError, BrokenPipeError, OSError):
                break

        # connection lost
        self._on_client_disconnect(slot)

    def _on_client_disconnect(self, slot: PlayerSlot):
        """called when a client's recv loop exits. marks slot as dropped."""
        with self._lock:
            slot.conn = None
            slot.last_seen = time.time()   # record disconnect time

        self.inbox.put((slot.pid, {
            "t":   MSG_PLAYER_DROP,
            "pid": slot.pid,
            "reason": "disconnect",
        }))

        # notify remaining players
        self.send_all({"t": MSG_PLAYER_DROP, "pid": slot.pid, "reason": "disconnect"})

    def _watchdog_loop(self):
        """periodically check for stale client slots and clean them up."""
        while not self._stop.is_set():
            now = time.time()
            with self._lock:
                for slot in self.slots:
                    if slot.pid == self.host_pid:
                        continue
                    if slot.conn is None:
                        # disconnected — check if reconnect window expired
                        elapsed = now - slot.last_seen
                        if elapsed > RECONNECT_GRACE:
                            # permanent drop: remove slot
                            self.slots = [s for s in self.slots if s.pid != slot.pid]
                            self.inbox.put((slot.pid, {
                                "t": "SLOT_EXPIRED",
                                "pid": slot.pid,
                            }))
                            if self._broadcaster:
                                self._broadcaster.update_count(len(self.slots))
            time.sleep(5.0)

    def _find_reconnect_slot(self, ip: str) -> Optional[PlayerSlot]:
        """check if an ip matches a recently disconnected slot within grace period."""
        now = time.time()
        with self._lock:
            for slot in self.slots:
                if (slot.conn is None
                        and slot.addr
                        and slot.addr[0] == ip
                        and now - slot.last_seen < RECONNECT_GRACE):
                    return slot
        return None

    def _send_raw(self, slot: PlayerSlot, data: bytes):
        """send raw bytes to a slot's connection. caller holds _lock."""
        if not slot.conn:
            return
        try:
            slot.conn.sendall(data)
        except (BrokenPipeError, OSError):
            slot.conn = None

    @staticmethod
    def _new_pid() -> str:
        return f"p{random.randint(10000,99999)}"


# ── network client ─────────────────────────────────────────────────────────────

class NetworkClient:
    """
    runs on joining machines. connects to a host via tcp.
    received messages go into self.inbox queue.
    game loop calls send() to push inputs to host.
    handles automatic reconnect on drop (within HOST_DROP_TIMEOUT).
    """

    def __init__(self):
        self.inbox       = queue.Queue()   # msg_dict items from host
        self.pid         = None            # assigned by host on join
        self.symbol      = None
        self.slot        = None
        self._host_ip    = None
        self._sock       = None
        self._recv_buf   = ""
        self._stop       = threading.Event()
        self._connected  = threading.Event()
        self._recv_thread = None
        self._last_host_msg = time.time()

    # ── public api ────────────────────────────────────────────────────────────

    def connect(self, host_ip: str, timeout: float = 5.0) -> bool:
        """connect to a host. returns True on success."""
        self._host_ip = host_ip
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            sock.connect((host_ip, NET_TCP_PORT))
            sock.settimeout(None)   # blocking after connect
            self._sock = sock
            self._connected.set()
            self._last_host_msg = time.time()
            self._recv_thread = threading.Thread(target=self._recv_loop, daemon=True)
            self._recv_thread.start()
            return True
        except (socket.timeout, ConnectionRefusedError, OSError):
            return False

    def disconnect(self):
        self._stop.set()
        try:
            if self._sock: self._sock.close()
        except: pass

    def send(self, msg: dict):
        """send a message to the host. fire-and-forget."""
        if not self._sock:
            return
        try:
            self._sock.sendall(_encode(msg))
        except (BrokenPipeError, OSError):
            self._on_host_drop()

    def send_move(self, x: float, y: float):
        self.send({"t": MSG_MOVE, "pid": self.pid, "x": round(x,2), "y": round(y,2)})

    def send_action(self, move_num: int, bx: float, by: float):
        self.send({"t": MSG_ACTION, "pid": self.pid,
                   "move_num": move_num, "bx": round(bx,2), "by": round(by,2)})

    def send_ping(self):
        self.send({"t": MSG_PING, "pid": self.pid, "ts": time.time()})

    def is_connected(self) -> bool:
        return self._connected.is_set() and self._sock is not None

    def host_alive(self) -> bool:
        """true if we've heard from the host recently."""
        return (time.time() - self._last_host_msg) < HOST_DROP_TIMEOUT

    # ── internal ──────────────────────────────────────────────────────────────

    def _recv_loop(self):
        self._recv_buf = ""
        while not self._stop.is_set():
            try:
                data = self._sock.recv(NET_BUF)
                if not data:
                    break
                self._last_host_msg = time.time()
                self._recv_buf += data.decode('utf-8', errors='replace')
                while '\n' in self._recv_buf:
                    line, self._recv_buf = self._recv_buf.split('\n', 1)
                    msg = _decode(line)
                    if msg:
                        # extract our pid/symbol from join messages
                        if msg.get("t") == MSG_PLAYER_JOIN and self.pid is None:
                            self.pid    = msg.get("pid")
                            self.symbol = msg.get("symbol")
                            self.slot   = msg.get("slot")
                        elif msg.get("t") == "RECONNECT_OK":
                            self.pid    = msg.get("pid")
                            self.symbol = msg.get("symbol")
                            self.slot   = msg.get("slot")
                        self.inbox.put(msg)
            except (ConnectionResetError, BrokenPipeError, OSError):
                break

        if not self._stop.is_set():
            self._on_host_drop()

    def _on_host_drop(self):
        """host connection lost. notify game loop and attempt reconnect."""
        self._connected.clear()
        self._sock = None
        self.inbox.put({"t": MSG_PLAYER_DROP, "pid": "host", "reason": "host_disconnect"})

        # attempt reconnect for up to HOST_DROP_TIMEOUT seconds
        deadline = time.time() + HOST_DROP_TIMEOUT
        while time.time() < deadline and not self._stop.is_set():
            time.sleep(2.0)
            if self.connect(self._host_ip, timeout=3.0):
                # resend our identity so host can match our slot
                if self.pid:
                    self.send({"t": "RECONNECT_CLAIM", "pid": self.pid})
                self.inbox.put({"t": "RECONNECT", "pid": self.pid})
                return

        # gave up
        self.inbox.put({"t": "HOST_GONE"})


# ── net game state — shared between host game loop and network layer ──────────

class NetGameState:
    """
    lightweight container the game loop populates and the network layer reads.
    keeps all multiplayer-relevant state in one place so tm_game.py doesn't
    need to import network internals directly.

    usage on host:
        net = NetGameState(host=NetworkHost())
        net.host.start()
        ...each frame: net.tick(g)   # syncs state, flushes inbox to g
    usage on client:
        net = NetGameState(client=NetworkClient())
        net.client.connect(ip)
    """

    def __init__(self,
                 host:   Optional[NetworkHost]   = None,
                 client: Optional[NetworkClient] = None):
        self.host   = host
        self.client = client
        self.is_host = host is not None

        # remote players: pid -> dict with x,y,hp,max_hp,symbol,status,cls_name
        self.remote_players : dict[str, dict] = {}

        # pending floaters to render this frame: list of (x,y,amount,clr)
        self.pending_floaters : list = []

        # last sync timestamp (host sends full sync every 2s)
        self._last_sync = 0.0

        # ping tracking
        self._last_ping = 0.0

    def poll(self) -> list:
        """
        drain the inbox queue and return all pending messages as a list.
        call once per game frame from the main loop.
        """
        msgs = []
        inbox = self.host.inbox if self.is_host else self.client.inbox
        while True:
            try:
                item = inbox.get_nowait()
                # host inbox yields (pid, msg) tuples; client just msg dicts
                msgs.append(item)
            except queue.Empty:
                break
        return msgs

    def apply_sync(self, msg: dict):
        """update remote_players from a SYNC message."""
        for p in msg.get("players", []):
            pid = p.get("pid")
            if pid:
                self.remote_players[pid] = p

    def apply_player_state(self, msg: dict):
        pid = msg.get("pid")
        if pid:
            if pid not in self.remote_players:
                self.remote_players[pid] = {}
            self.remote_players[pid].update(msg)

    def queue_floater(self, x: float, y: float, amount: int, clr: tuple):
        self.pending_floaters.append((x, y, amount, clr))

    def flush_floaters(self) -> list:
        out = list(self.pending_floaters)
        self.pending_floaters.clear()
        return out

    def send_move(self, x: float, y: float):
        if self.client:
            self.client.send_move(x, y)

    def send_action(self, move_num: int, bx: float, by: float):
        if self.client:
            self.client.send_action(move_num, bx, by)

    def tick_ping(self):
        """send a keepalive ping every 5s (client side only)."""
        if self.client and time.time() - self._last_ping > 5.0:
            self._last_ping = time.time()
            self.client.send_ping()
