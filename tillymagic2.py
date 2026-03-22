#!/usr/bin/env python3
"""TillyMagic — main entry point."""
import sys, time
from tm_core import *
from tm_menus import menu_main
from tm_game  import Game, process_input, update_game, render_game
from tm_updater import check_for_update
from tm_motd import start_motd_fetch


# ── singleplayer game loop ────────────────────────────────────────────────────

def run_game(inp, cls_name, boss_key, map_key, size_mult, size_coin_mult, save):
    g = Game(cls_name, boss_key, map_key, size_mult, size_coin_mult, save)

    sys.stdout.write(CLR + HIDE)
    sys.stdout.flush()

    last    = time.time()
    out_buf = []

    try:
        while g.running:
            now = time.time()
            dt  = min(now - last, 0.05)
            last = now

            inp.read()
            keys = inp.get()

            if g.game_over or g.victory:
                for k in keys:
                    if k in ('\x1b', '\x03', 'q'):
                        g.running = False
            else:
                process_input(g, keys, dt)
                update_game(g, dt)

            out_buf.clear()
            render_game(g, out_buf)
            sys.stdout.write("".join(out_buf))
            sys.stdout.flush()

            elapsed = time.time() - now
            time.sleep(max(0, 0.016 - elapsed))

    except KeyboardInterrupt:
        pass

    return g.earned_coins if g.victory else 0


# ── multiplayer game loop ─────────────────────────────────────────────────────

def run_game_mp(inp, net_state, is_host, cls_name, boss_key,
                map_key, size_mult, size_coin_mult, save,
                mp_pid, mp_symbol, player_count):
    """
    shared game loop for both host and joining clients.
    net_state: NetGameState with host or client already connected.
    calls g.setup_multiplayer() to apply scaling and wire up networking.
    handles the spectate-leave confirmation inline.
    returns earned_coins (0 if loss).
    """
    from tm_lobby      import menu_spectate_confirm
    from tm_network    import STATUS_SPECTATE

    g = Game(cls_name, boss_key, map_key, size_mult, size_coin_mult, save)
    g.setup_multiplayer(net_state, mp_pid, mp_symbol, is_host, player_count)

    sys.stdout.write(CLR + HIDE)
    sys.stdout.flush()

    last    = time.time()
    out_buf = []

    try:
        while g.running:
            now = time.time()
            dt  = min(now - last, 0.05)
            last = now

            inp.read()
            keys = inp.get()

            # check if spectating player pressed ESC → confirm leave
            if g._mp_spectate_wants_leave:
                g._mp_spectate_wants_leave = False
                should_leave = menu_spectate_confirm(inp)
                if should_leave:
                    g.running = False
                    if net_state.client:
                        net_state.client.disconnect()
                    if net_state.host:
                        net_state.host.stop()
                    return 0
                sys.stdout.write(CLR + HIDE)
                sys.stdout.flush()
                continue

            if g.game_over or g.victory:
                for k in keys:
                    if k in ('\x1b', '\x03', 'q'):
                        g.running = False
            else:
                process_input(g, keys, dt)
                update_game(g, dt)

            out_buf.clear()
            render_game(g, out_buf)
            sys.stdout.write("".join(out_buf))
            sys.stdout.flush()

            elapsed = time.time() - now
            time.sleep(max(0, 0.016 - elapsed))

    except KeyboardInterrupt:
        pass

    return g.earned_coins if g.victory else 0


# ── multiplayer host flow ─────────────────────────────────────────────────────

def run_multiplayer_host(inp, save):
    """
    full host flow: lobby → game → retry loop.
    returns coins earned across all rounds, or 0.
    """
    from tm_lobby import (menu_host_lobby, menu_host_collect_classes,
                          menu_retry_host)

    total_coins = 0

    lobby_result = menu_host_lobby(inp, save)
    if lobby_result is None:
        return 0

    net       = lobby_result['net']
    host      = lobby_result['host']
    cls_name  = lobby_result['cls']
    boss_key  = lobby_result['boss']
    map_key   = lobby_result['map_key']
    size_mult = lobby_result['size_mult']
    size_cmult= lobby_result['size_coin_mult']
    pid       = host.host_pid
    symbol    = '@'

    while True:
        # give joiners a moment to send their class selections
        menu_host_collect_classes(inp, host, timeout=15.0)

        player_count = host.player_count()

        coins = run_game_mp(
            inp, net, True, cls_name, boss_key,
            map_key, size_mult, size_cmult, save,
            pid, symbol, player_count
        )
        total_coins += coins

        # retry?
        retry_result = menu_retry_host(inp, host, save)
        if retry_result is None:
            break

        # unpack retry selection
        net       = retry_result['net']
        cls_name  = retry_result['cls']
        boss_key  = retry_result['boss']
        map_key   = retry_result['map_key']
        size_mult = retry_result['size_mult']
        size_cmult= retry_result['size_coin_mult']
        # collect joiner class selections for the new round too
        menu_host_collect_classes(inp, host, timeout=15.0)
        player_count = host.player_count()

    host.stop()
    return total_coins


# ── multiplayer client flow ───────────────────────────────────────────────────

def run_multiplayer_client(inp, save):
    """
    full client flow: browse → class select → wait → game → retry loop.
    returns coins earned, or 0.
    """
    from tm_lobby import (menu_join_browse, menu_class_select_mp,
                          menu_waiting, menu_retry_join)

    total_coins = 0

    # browse for a game
    join_result = menu_join_browse(inp)
    if join_result is None:
        return 0

    net    = join_result['net']
    client = join_result['client']
    symbol = join_result['symbol']
    pid    = join_result['pid']

    while True:
        # pick class
        cls_name = menu_class_select_mp(inp, net, symbol)
        if cls_name is None:
            client.disconnect()
            return 0

        # wait for host to start
        start_msg = menu_waiting(inp, net, symbol, pid)
        if start_msg is None:
            # host gone or cancelled
            client.disconnect()
            return 0

        boss_key  = start_msg.get('boss_key',  'boss1')
        map_key   = start_msg.get('map_key',   'standard')
        size_mult = start_msg.get('size_mult',  1.0)

        # how many players in this round (from GAME_START players list)
        player_count = len(start_msg.get('players', [])) or 2

        coins = run_game_mp(
            inp, net, False, cls_name, boss_key,
            map_key, size_mult, 1.0, save,
            pid, symbol, player_count
        )
        total_coins += coins

        # retry?
        retry_msg = menu_retry_join(inp, net, symbol, pid)
        if retry_msg is None:
            break
        if isinstance(retry_msg, dict) and retry_msg.get('t') == 'GAME_START':
            # host already sent next game start — loop will handle it
            start_msg = retry_msg
            boss_key  = start_msg.get('boss_key', 'boss1')
            map_key   = start_msg.get('map_key',  'standard')
            size_mult = start_msg.get('size_mult',  1.0)
            player_count = len(start_msg.get('players', [])) or 2
            # pick class again then go straight to game
            cls_name = menu_class_select_mp(inp, net, symbol)
            if cls_name is None:
                client.disconnect()
                break
            coins = run_game_mp(
                inp, net, False, cls_name, boss_key,
                map_key, size_mult, 1.0, save,
                pid, symbol, player_count
            )
            total_coins += coins

    client.disconnect()
    return total_coins


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    inp = Input()
    try:
        # ── update check (runs before menu, silently skips on no network) ────
        try:
            updated = check_for_update(inp)
            if updated:
                sys.stdout.write(SHOW + RST + CLR)
                sys.stdout.flush()
                print("Update installed. Please restart TillyMagic.")
                return
        except Exception:
            pass   # never let updater crash the game

        save = load_save()
        start_motd_fetch()   # kick off background MOTD fetch

        while True:
            result = menu_main(inp, save)
            if result is None:
                break

            mode = result[0]

            if mode == 'singleplayer':
                _, cls_name, boss_key, map_key, size_mult, size_coin_mult = result
                coins = run_game(inp, cls_name, boss_key,
                                 map_key, size_mult, size_coin_mult, save)
                if coins > 0:
                    save["coins"] += coins
                    write_save(save)

            elif mode == 'multiplayer':
                _, mp_choice = result   # mp_choice = 'host' | 'join'
                if mp_choice == 'host':
                    coins = run_multiplayer_host(inp, save)
                elif mp_choice == 'join':
                    coins = run_multiplayer_client(inp, save)
                else:
                    coins = 0
                if coins > 0:
                    save["coins"] += coins
                    write_save(save)

    finally:
        inp.restore()
        sys.stdout.write(SHOW + RST + CLR)
        sys.stdout.flush()
        print("Thanks for playing TillyMagic!")


if __name__ == "__main__":
    main()
