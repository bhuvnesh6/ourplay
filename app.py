import os, json, time, secrets, hashlib, sqlite3, threading
from flask import Flask, request, jsonify, send_from_directory
from werkzeug.middleware.proxy_fix import ProxyFix
from flask_socketio import SocketIO, emit, join_room
import engine

if not os.environ.get("SECRET_KEY"):
    raise SystemExit("SECRET_KEY is required - copy .env.example to .env and set it")
BASE = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
DB = os.environ.get("DB_PATH", "/data/ourplay.db")
TTL = float(os.environ.get("ROOM_TTL_DAYS", "14")) * 86400
STUN = os.environ.get("STUN_URL", "stun:stun.l.google.com:19302")
TURN = os.environ.get("TURN_URL", "")

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
app.config["SECRET_KEY"] = os.environ["SECRET_KEY"]
# cors_allowed_origins=None -> same-origin only (Origin must match Host)
sio = SocketIO(app, async_mode="threading", cors_allowed_origins=[BASE] if BASE else None)

lock = threading.RLock()
os.makedirs(os.path.dirname(DB) or ".", exist_ok=True)
con = sqlite3.connect(DB, check_same_thread=False)
con.execute("create table if not exists rooms(id text primary key, data text not null, updated real not null)")
con.execute("delete from rooms where updated<?", (time.time() - TTL,))
con.commit()

online, sess, hits = {}, {}, {}
h = lambda t: hashlib.sha256(t.encode()).hexdigest()


def limited(k, n, sec):
    now = time.time()
    l = [t for t in hits.get(k, []) if now - t < sec] + [now]
    hits[k] = l
    return len(l) > n


def load(rid):
    r = con.execute("select data from rooms where id=?", (rid,)).fetchone()
    return json.loads(r[0]) if r else None


def save(rid, room):
    con.execute("insert or replace into rooms values(?,?,?)", (rid, json.dumps(room), time.time()))
    con.commit()


def nm(s):
    return " ".join(str(s or "").split())[:20]


def newplayer(name, seat, tok):
    return {"name": nm(name) or ("You" if seat == 0 else "Starlight ♡"),
            "avatar": ["🦊", "🌸"][seat], "h": h(tok)}


@app.after_request
def headers(r):
    r.headers.update({"X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY",
                      "Referrer-Policy": "same-origin"})
    return r


@app.get("/")
def index():
    return send_from_directory("static", "index.html")


@app.get("/sw.js")
def sw():
    r = send_from_directory("static", "sw.js")
    r.headers["Cache-Control"] = "no-cache"
    return r


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/api/config")
def config():
    ice = [{"urls": STUN}]
    if TURN:
        ice.append({"urls": TURN, "username": os.environ.get("TURN_USERNAME", ""),
                    "credential": os.environ.get("TURN_CREDENTIAL", "")})
    return {"ice": ice}


def err(m, c):
    return jsonify(error=m), c


@app.post("/api/rooms")
def create():
    if limited(("mk", request.remote_addr), 10, 60):
        return err("Too many requests", 429)
    d = request.get_json(silent=True) or {}
    rid, tok = secrets.token_urlsafe(9), secrets.token_urlsafe(24)
    save(rid, {"players": [newplayer(d.get("name"), 0, tok)], "game": engine.new_game(), "chat": []})
    return {"room": rid, "token": tok}


@app.post("/api/rooms/join")
def join():
    if limited(("jn", request.remote_addr), 20, 60):
        return err("Too many requests", 429)
    d = request.get_json(silent=True) or {}
    with lock:
        rid = d.get("room")
        room = load(rid) if isinstance(rid, str) else None
        if not room:
            return err("Invalid or expired invitation", 404)
        if len(room["players"]) >= 2:
            return err("This room is full", 403)
        tok = secrets.token_urlsafe(24)
        room["players"].append(newplayer(d.get("name"), 1, tok))
        save(rid, room)
        push(rid, room)
    return {"room": rid, "token": tok}


def pub(rid, room):
    return {"room": rid, "game": room["game"],
            "players": [{"name": p["name"], "avatar": p["avatar"], "online": bool(online.get((rid, i)))}
                        for i, p in enumerate(room["players"])]}


def push(rid, room):
    sio.emit("state", pub(rid, room), to=rid)


@sio.on("connect")
def on_connect(auth):
    a = auth if isinstance(auth, dict) else {}
    rid, tok = a.get("room"), str(a.get("token") or "")
    with lock:
        room = load(rid) if isinstance(rid, str) else None
        seat = next((i for i, p in enumerate(room["players"]) if secrets.compare_digest(p["h"], h(tok))), None) if room else None
        if seat is None:
            return False
        sess[request.sid] = (rid, seat)
        online.setdefault((rid, seat), set()).add(request.sid)
        join_room(rid)
        emit("you", seat)
        emit("history", room["chat"][-100:])
        push(rid, room)


@sio.on("disconnect")
def on_disc(*_):
    with lock:
        s = sess.pop(request.sid, None)
        if s:
            online.get((s[0], s[1]), set()).discard(request.sid)
            room = load(s[0])
            if room:
                push(s[0], room)
            sio.emit("voice_leave", {}, to=s[0])


def act(fn):
    def w(data=None):
        s = sess.get(request.sid)
        if not s:
            return
        with lock:
            room = load(s[0])
            try:
                fn(s[0], s[1], room, data if isinstance(data, dict) else {})
            except (ValueError, TypeError) as e:
                emit("err", str(e))
    return w


def do_roll(rid, seat, room, d):
    if len(room["players"]) < 2:
        raise ValueError("Waiting for your partner to join")
    engine.roll(room["game"], seat)
    save(rid, room); push(rid, room)


def do_move(rid, seat, room, d):
    engine.move(room["game"], seat, int(d.get("i", -1)))
    save(rid, room); push(rid, room)


def do_chat(rid, seat, room, d):
    t = str(d.get("t", "")).strip()[:500]
    if not t:
        return
    if limited(("c", request.sid), 8, 10):
        raise ValueError("Slow down a little ♡")
    m = {"s": seat, "t": t, "ts": time.time()}
    room["chat"] = (room["chat"] + [m])[-500:]
    save(rid, room)
    sio.emit("chat", m, to=rid)


def do_profile(rid, seat, room, d):
    n = nm(d.get("name"))
    if not n:
        raise ValueError("Name can't be empty")
    p = room["players"][seat]
    p["name"], p["avatar"] = n, (str(d.get("avatar", ""))[:8] or p["avatar"])
    save(rid, room); push(rid, room)


def do_restart(rid, seat, room, d):
    room["game"] = engine.new_game()
    save(rid, room); push(rid, room)


for ev, fn in (("roll", do_roll), ("move", do_move), ("chat", do_chat),
               ("profile", do_profile), ("restart", do_restart)):
    sio.on_event(ev, act(fn))


def relay(ev):
    def w(data=None):
        s = sess.get(request.sid)
        if s and len(json.dumps(data or {})) < 20000:
            emit(ev, data or {}, to=s[0], include_self=False)
    return w


for ev in ("voice_join", "voice_leave", "sig"):
    sio.on_event(ev, relay(ev))

if __name__ == "__main__":  # local dev only
    sio.run(app, host="0.0.0.0", port=int(os.environ.get("APP_PORT", 4449)), allow_unsafe_werkzeug=True)
