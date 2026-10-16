# OurPlay ♡ — private 2-player Ludo + chat + voice (PWA)

Flask + Flask-SocketIO (server-authoritative Ludo), SQLite, WebRTC voice (Socket.IO only does signaling), Docker. Listens on **4449**.

## 1. First deploy on the VPS (after `git clone`)

```bash
git clone <your-repo-url> ourplay && cd ourplay

# check port 4449 is free (no output = free)
sudo ss -tlnp | grep 4449

cp .env.example .env
nano .env        # set SECRET_KEY (python3 -c "import secrets;print(secrets.token_hex(32))") and PUBLIC_BASE_URL=https://your-domain

docker compose up -d --build
curl http://127.0.0.1:4449/health      # -> {"ok":true}
docker compose logs -f ourplay         # Ctrl+C to leave logs
```

The container is bound to `127.0.0.1:4449`, so it is NOT public — Nginx fronts it with HTTPS (required for microphone access on phones).

## 2. Domain / HTTPS

If you use **Nginx Proxy Manager**: put OurPlay on the same Docker network as NPM (`networks:` block in `compose.yaml`), then add a proxy host -> scheme `http`, forward host `ourplay`, port `4449`, **Websockets Support ON**, SSL certificate + Force SSL. No custom Nginx file needed.
Plain Nginx instead? Proxy to `http://127.0.0.1:4449` with `proxy_http_version 1.1`, `Upgrade`/`Connection "upgrade"` headers, `proxy_buffering off`, `Host` and `X-Forwarded-*` headers.

## 2b. Set up the two players (owner page)

1. In `.env` set `ADMIN_PASSWORD`, then `docker compose up -d --build`.
2. Open `https://your-domain/setup` (browser asks for a login: any username + your ADMIN_PASSWORD).
3. For Player 1 (red) and Player 2 (blue): set the name, pick an emoji or upload a photo, press **Save**.
4. Each card shows a **personal link**. Open yours on your laptop, send hers to her phone. That link is her login (the page remembers it afterwards). **New link** revokes the old one.
The game always has exactly these two players in one room. Rolling needs both of you online.

## 2c. Your images

- `static/bg/laptop.png` - background on laptop/desktop; `static/bg/phone.png` - background on phones.
- `static/memes/teas.png` (token cut), `static/memes/celebrate.png` (token home + final win), `static/memes/welcome.png` (welcome popup).
Missing images are fine (popups show text only). After adding/changing images: `git add . && git commit` (if using git) then on the VPS `docker compose up -d --build`.

## 2d. Sounds, dice, popups

Sounds are generated in the browser (no files): dice rattle, unlock, move ticks, cut, token home, win, chat, your-turn ding, welcome chime. 🔊 in the header mutes them. Browsers only allow sound after a tap/click, which is why the welcome popup has an **Enter** button. The dice is a real 3D cube; final win launches fireworks.

## 3. Update after new code (`git pull`)

```bash
cd ~/ourplay
cp .env .env.bak                 # optional safety copy
git pull
docker compose up -d --build     # rebuilds image, keeps the data volume
docker compose logs --tail=50 ourplay
```
Roll back: `git log --oneline` → `git checkout <old-commit>` → `docker compose up -d --build` (then `git checkout main` to return).

## 4. Everyday commands

```bash
docker compose ps                    # status
docker compose logs -f ourplay       # live logs
docker compose restart ourplay
docker compose down                  # stop (data volume is kept)
```
Never run `docker compose down -v` or `docker volume prune` — that deletes the database.

**Backup / restore the SQLite DB**
```bash
docker compose cp ourplay:/data/ourplay.db ./backup-$(date +%F).db
docker compose stop ourplay && docker compose cp ./backup-YYYY-MM-DD.db ourplay:/data/ourplay.db && docker compose start ourplay
```
**Change the port:** edit `compose.yaml` (`"127.0.0.1:NEW:4449"`) and your Nginx `proxy_pass`, then `docker compose up -d`.

## 5. How to play

1. Open your personal link (from `/setup`) on your laptop; she opens hers on her phone.
2. ⚙ in-game lets each player change their own name/emoji (synced live); photos are set in `/setup`.
4. 🎙 **Join voice** (both players) → **Mute / Resume** only toggles your mic; the call stays up. **Leave voice** ends it.
5. Phones: browser menu → *Add to Home Screen* / *Install* for the PWA.

## 6. Rules implemented

Red (Player 1) vs Blue (Player 2); 4 tokens each. **6 or 1 unlocks** a token. **Extra roll** on a 6, on a capture, or when a token reaches home. Landing on an opponent on a non-safe square **sends it back to the yard** (and gives you another roll). Start squares and ★ squares are safe. Exact roll needed to enter home. No legal move = turn passes. First to bring all 4 home wins. Dice and moves are validated on the server only.

## 7. Security / persistence

Each player has a private, unguessable link token (HMAC of SECRET_KEY); only those two seats exist, anyone else is rejected. `/setup` is password protected and rate limited. Every socket event is checked against the authenticated seat; chat is rendered as text (no HTML); same-origin check on Socket.IO; basic rate limits; no audio is ever recorded or stored. Rooms (game + chat) persist in SQLite and expire after `ROOM_TTL_DAYS` of inactivity. Refresh/reconnect restores your seat from the saved token.

## 8. Voice / TURN

Uses STUN by default. If voice stays on "connecting/failed" on some mobile networks, run a TURN server (coturn) and fill `TURN_URL/TURN_USERNAME/TURN_CREDENTIAL` in `.env`, then `docker compose up -d`.

## 9. Honest limitations (v1)

- Profile photos are center-cropped to a square in the setup page (no manual crop tool). Avatar images are served at `/avatar/0|1` without login.
- TURN credentials from `.env` are static (not short-lived) and are sent to joined clients.
- No Content-Security-Policy header yet (page uses inline script); Socket.IO client loads from cdn.socket.io.
- Code is condensed into `app.py` + `engine.py` rather than the full module tree; only engine tests (`pytest tests`) exist — no browser/E2E tests.
- Verified here: engine rules, room create/join/full, auth rejection, chat, turn enforcement. **Not yet verified:** real two-device play, WebRTC audio, Nginx/HTTPS on your VPS, PWA install. Test those after deploying.
- Single gunicorn worker by design (presence is in-memory); fine for 2 players.
