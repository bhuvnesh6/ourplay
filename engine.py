"""OurPlay Ludo engine. Pure logic, no I/O.

Rules: 2 players (seat 0 red, seat 1 blue), 4 tokens each.
Token progress: -1 yard | 0..50 ring (relative to own start) | 51..55 home lane | 56 home.
Roll 1 or 6 unlocks a token. Extra roll on: a 6, a capture, or a token reaching home.
Capture = landing on an opponent token on a non-safe ring square (it returns to yard).
Safe squares (start squares + stars) protect. Exact roll needed to reach home. No-move = turn passes.
"""
import random

START = [0, 13]                      # absolute ring index of each seat's start
SAFE = {0, 8, 13, 21, 26, 34, 39, 47}
HOME = 56


def new_game():
    return {"tokens": [[-1] * 4, [-1] * 4], "turn": 0, "dice": None, "pending": False,
            "legal": [], "seq": 0, "status": "playing", "winner": None, "log": []}


def legal_moves(g, seat, d):
    return [i for i, p in enumerate(g["tokens"][seat]) if (d in (1, 6) if p < 0 else p + d <= HOME)]


def _log(g, **e):
    g["seq"] += 1
    e["n"] = g["seq"]
    g["log"] = (g["log"] + [e])[-30:]


def roll(g, seat, rng=random):
    if g["status"] != "playing":
        raise ValueError("Game is over - start a new one")
    if g["turn"] != seat:
        raise ValueError("It's not your turn")
    if g["pending"]:
        raise ValueError("Pick a token to move first")
    d = rng.randint(1, 6)
    g["dice"], g["legal"] = d, legal_moves(g, seat, d)
    if g["legal"]:
        g["pending"] = True
        _log(g, s=seat, d=d, m="roll")
    else:
        _log(g, s=seat, d=d, m="skip")
        g["turn"] = 1 - seat
    return d


def move(g, seat, i):
    if g["status"] != "playing" or g["turn"] != seat or not g["pending"]:
        raise ValueError("You can't move right now")
    if i not in g["legal"]:
        raise ValueError("That token can't move")
    d, t = g["dice"], g["tokens"][seat]
    was = t[i]
    new = 0 if was < 0 else was + d
    t[i] = new
    cap = False
    if new <= 50 and (START[seat] + new) % 52 not in SAFE:
        a, o = (START[seat] + new) % 52, g["tokens"][1 - seat]
        for j, q in enumerate(o):
            if 0 <= q <= 50 and (START[1 - seat] + q) % 52 == a:
                o[j], cap = -1, True
    g["pending"], g["legal"] = False, []
    _log(g, s=seat, d=d, m="cap" if cap else "home" if new == HOME else "unlock" if was < 0 else "move")
    if all(x == HOME for x in t):
        g["status"], g["winner"] = "won", seat
    elif not (d == 6 or cap or new == HOME):
        g["turn"] = 1 - seat
    return cap
