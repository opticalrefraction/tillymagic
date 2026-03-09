#!/usr/bin/env python3
"""TillyMagic — main entry point."""
import sys, time
from tm_core import *
from tm_menus import menu_main
from tm_game import Game, process_input, update_game, render_game

def run_game(inp, cls_name, boss_key, map_key, size_mult, save):
    g = Game(cls_name, boss_key, map_key, size_mult, save)

    sys.stdout.write(CLR + HIDE)
    sys.stdout.flush()

    last = time.time()
    frame = 0
    out_buf = []

    try:
        while g.running:
            now = time.time()
            dt = min(now - last, 0.05)
            last = now

            inp.read()
            keys = inp.get()

            # Quit on ESC once game is over
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

            frame += 1
            elapsed = time.time() - now
            sleep = max(0, 0.016 - elapsed)
            time.sleep(sleep)

    except KeyboardInterrupt:
        pass

    return g.earned_coins if g.victory else 0


def main():
    inp = Input()
    try:
        save = load_save()

        while True:
            result = menu_main(inp, save)
            if result is None:
                break

            _, cls_name, boss_key, map_key, size_mult = result
            coins = run_game(inp, cls_name, boss_key, map_key, size_mult, save)

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
