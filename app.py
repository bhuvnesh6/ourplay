import os, re, json, time, hmac, base64, hashlib, sqlite3, threading
from functools import wraps
from flask import Flask, request, jsonify, send_from_directory, Response
from werkzeug.middleware.proxy_fix import ProxyFix
from flask_socketio import SocketIO, emit, join_room
import engine

SECRET = os.environ.get("SECRET_KEY", "")
if not SECRET:
    raise SystemExit("SECRET_KEY is required - copy .env.example to .env and set it")
ADMIN = os.environ.get("ADMIN_PASSWORD", "")
BASE = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
DB = os.environ.get("DB_PATH", "/data/ourplay.db")
STUN = os.environ.get("STUN_URL", "stun:stun.l.google.com:19302")
TURN = os.environ.get("TURN_URL", "")
ROOM = "main"  # there is always exactly one room with two fixed players

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
app.config["SECRET_KEY"] = SECRET
# cors_allowed_origins=None -> same-origin only
sio = SocketIO(app, async_mode="threading", cors_allowed_origins=[BASE] if BASE else None)

lock = threading.RLock()
os.makedirs(os.path.dirname(DB) or ".", exist_ok=True)
con = sqlite3.connect(DB, check_same_thread=False)
con.execute("create table if not exists rooms(id text primary key, data text not null, updated real not null)")
con.execute("delete from rooms where id!=?", (ROOM,))  # drop rooms from older versions
con.commit()

online, sess, hits = {}, {}, {}


def limited(k, n, sec):
    now = time.time()
    l = [t for t in hits.get(k, []) if now - t < sec] + [now]
    hits[k] = l
    return len(l) > n


def load(rid=ROOM):
    r = con.execute("select data from rooms where id=?", (rid,)).fetchone()
    return json.loads(r[0]) if r else None


def save(room, rid=ROOM):
    con.execute("insert or replace into rooms values(?,?,?)", (rid, json.dumps(room), time.time()))
    con.commit()


def nm(s):
    return " ".join(str(s or "").split())[:20]


def tok(seat, gen):  # personal link token; changes only when "New link" is pressed in /setup
    return hmac.new(SECRET.encode(), f"ourplay:{seat}:{gen}".encode(), hashlib.sha256).hexdigest()[:40]


def seat_of(token, room):
    t = str(token or "")
    return next((s for s in (0, 1) if hmac.compare_digest(tok(s, room["gen"][s]), t)), None)


if not load():
    save({"players": [{"name": "You", "avatar": "🦊", "img": None, "v": 0},
                      {"name": "Starlight ♡", "avatar": "🌸", "img": None, "v": 0}],
          "gen": [0, 0], "game": engine.new_game(), "chat": []})


@app.after_request
def headers(r):
    r.headers.update({"X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY",
                      "Referrer-Policy": "same-origin"})
    return r


# ---------- pages ----------
@app.get("/")
def index():
    return send_from_directory("static", "index.html")


@app.get("/p/<token>")
def personal(token):
    if seat_of(token, load()) is None:
        return "This link is no longer valid ♡", 404
    return send_from_directory("static", "index.html")


@app.get("/p/<token>/manifest.webmanifest")
def pmanifest(token):  # makes the installed PWA open straight into this player's seat
    if seat_of(token, load()) is None:
        return "", 404
    with open(os.path.join(app.static_folder, "manifest.webmanifest"), encoding="utf-8") as f:
        m = json.load(f)
    m["start_url"] = f"/p/{token}"
    return Response(json.dumps(m, ensure_ascii=False), mimetype="application/manifest+json")


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


@app.get("/avatar/<int:seat>")
def avatar(seat):
    room = load()
    img = room["players"][seat]["img"] if seat in (0, 1) else None
    if not img:
        return "", 404
    head, b64 = img.split(",", 1)
    return Response(base64.b64decode(b64), mimetype=head[5:head.index(";")],
                    headers={"Cache-Control": "public, max-age=86400"})


# ---------- owner setup (HTTP Basic auth, password = ADMIN_PASSWORD) ----------
def admin(fn):
    @wraps(fn)
    def w(*a, **k):
        if not ADMIN:
            return "Set ADMIN_PASSWORD in .env and restart the container", 503
        au = request.authorization
        if not (au and hmac.compare_digest((au.password or "").encode(), ADMIN.encode())):
            if limited(("adm", request.remote_addr), 10, 60):
                return "Too many attempts", 429
            return Response("Login required", 401, {"WWW-Authenticate": 'Basic realm="OurPlay setup"'})
        return fn(*a, **k)
    return w


def err(m, c):
    return jsonify(error=m), c


def links(room):
    base = BASE or request.host_url.rstrip("/")
    return [{"seat": s, "name": p["name"], "avatar": p["avatar"], "img": p["v"] if p["img"] else 0,
             "link": f"{base}/p/{tok(s, room['gen'][s])}"} for s, p in enumerate(room["players"])]


IMG = re.compile(r"^data:image/(png|jpeg|webp);base64,([A-Za-z0-9+/=]+)$")
MAGIC = {"png": b"\x89PNG", "jpeg": b"\xff\xd8", "webp": b"RIFF"}


def valid_img(s):
    m = IMG.match(s) if isinstance(s, str) and len(s) < 150000 else None
    if not m:
        return False
    try:
        return base64.b64decode(m.group(2), validate=True).startswith(MAGIC[m.group(1)])
    except Exception:
        return False


@app.get("/setup")
@admin
def setup_page():
    return send_from_directory("static", "setup.html")


@app.get("/api/setup")
@admin
def setup_get():
    return {"players": links(load())}


@app.post("/api/setup/<int:seat>")
@admin
def setup_save(seat):
    if seat not in (0, 1):
        return err("Bad seat", 404)
    d = request.get_json(silent=True) or {}
    with lock:
        room = load()
        p = room["players"][seat]
        if "name" in d:
            if not nm(d["name"]):
                return err("Name can't be empty", 400)
            p["name"] = nm(d["name"])
        if d.get("clearImg"):
            p["img"], p["v"] = None, p["v"] + 1
        if d.get("avatar"):
            p["avatar"], p["img"], p["v"] = str(d["avatar"])[:8], None, p["v"] + 1
        if d.get("img"):
            if not valid_img(d["img"]):
                return err("Image must be a small PNG, JPEG or WebP", 400)
            p["img"], p["v"] = d["img"], p["v"] + 1
        if d.get("regen"):
            room["gen"][seat] += 1
            for sid in list(online.get((ROOM, seat), ())):  # revoke: kick the old sessions
                try:
                    sio.server.disconnect(sid)
                except Exception:
                    pass
        save(room)
        push(room)
        return {"players": links(room)}


# ---------- realtime ----------
def pub(room):
    return {"game": room["game"],
            "players": [{"name": p["name"], "avatar": p["avatar"], "img": p["v"] if p["img"] else 0,
                         "online": bool(online.get((ROOM, i)))} for i, p in enumerate(room["players"])]}


def push(room):
    sio.emit("state", pub(room), to=ROOM)


@sio.on("connect")
def on_connect(auth):
    token = auth.get("token") if isinstance(auth, dict) else ""
    with lock:
        room = load()
        seat = seat_of(token, room)
        if seat is None:
            return False
        sess[request.sid] = seat
        online.setdefault((ROOM, seat), set()).add(request.sid)
        join_room(ROOM)
        emit("you", seat)
        emit("history", room["chat"][-100:])
        push(room)


@sio.on("disconnect")
def on_disc(*_):
    with lock:
        seat = sess.pop(request.sid, None)
        if seat is not None:
            online.get((ROOM, seat), set()).discard(request.sid)
            push(load())
            sio.emit("voice_leave", {}, to=ROOM)


def act(fn):
    def w(data=None):
        seat = sess.get(request.sid)
        if seat is None:
            return
        with lock:
            room = load()
            try:
                fn(seat, room, data if isinstance(data, dict) else {})
            except (ValueError, TypeError) as e:
                emit("err", str(e))
    return w


def do_roll(seat, room, d):
    if not all(online.get((ROOM, s)) for s in (0, 1)):
        raise ValueError("Waiting for your partner to be online")
    engine.roll(room["game"], seat)
    save(room); push(room)


def do_move(seat, room, d):
    engine.move(room["game"], seat, int(d.get("i", -1)))
    save(room); push(room)


def do_chat(seat, room, d):
    t = str(d.get("t", "")).strip()[:500]
    if not t:
        return
    if limited(("c", request.sid), 8, 10):
        raise ValueError("Slow down a little ♡")
    m = {"s": seat, "t": t, "ts": time.time()}
    room["chat"] = (room["chat"] + [m])[-500:]
    save(room)
    sio.emit("chat", m, to=ROOM)


def do_profile(seat, room, d):  # a player editing their own name / emoji from in-game settings
    n = nm(d.get("name"))
    if not n:
        raise ValueError("Name can't be empty")
    p = room["players"][seat]
    p["name"] = n
    a = str(d.get("avatar") or "")[:8]
    if a:
        p["avatar"], p["img"], p["v"] = a, None, p["v"] + 1
    save(room); push(room)


def do_restart(seat, room, d):
    room["game"] = engine.new_game()
    save(room); push(room)


for ev, fn in (("roll", do_roll), ("move", do_move), ("chat", do_chat),
               ("profile", do_profile), ("restart", do_restart)):
    sio.on_event(ev, act(fn))


def relay(ev):
    def w(data=None):
        if request.sid in sess and len(json.dumps(data or {})) < 20000:
            emit(ev, data or {}, to=ROOM, include_self=False)
    return w


for ev in ("voice_join", "voice_leave", "sig"):
    sio.on_event(ev, relay(ev))

if __name__ == "__main__":  # local dev only
    sio.run(app, host="0.0.0.0", port=int(os.environ.get("APP_PORT", 4449)), allow_unsafe_werkzeug=True)
