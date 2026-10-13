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

## 2. Nginx (add a new server block; don't touch your other sites)

`/etc/nginx/sites-available/ourplay` (use your existing certificate paths / `certbot --nginx -d your-domain` if needed):

```nginx
server {
    listen 443 ssl http2;
    server_name your-domain.example;
    # ssl_certificate / ssl_certificate_key: same as your other sites, or let certbot add them

    location / {
        proxy_pass http://127.0.0.1:4449;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;      # WebSocket
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_buffering off;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }
}
```
```bash
sudo ln -s /etc/nginx/sites-available/ourplay /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

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

1. Open `https://your-domain` on your laptop → enter your name → **Create room**.
2. Tap **Copy invitation link**, send it to her. She opens it on her phone → name → **Join room**.
3. Settings (⚙) lets each player change their own name and avatar (synced live).
4. 🎙 **Join voice** (both players) → **Mute / Resume** only toggles your mic; the call stays up. **Leave voice** ends it.
5. Phones: browser menu → *Add to Home Screen* / *Install* for the PWA.

## 6. Rules implemented

Red (you / seat 1) vs Blue (seat 2); 4 tokens each. **6 or 1 unlocks** a token. **Extra roll** on a 6, on a capture, or when a token reaches home. Landing on an opponent on a non-safe square **sends it back to the yard** (and gives you another roll). Start squares and ★ squares are safe. Exact roll needed to enter home. No legal move = turn passes. First to bring all 4 home wins. Dice and moves are validated on the server only.

## 7. Security / persistence

Unguessable room id + per-player secret token (only a hash is stored); max 2 seats, a 3rd visitor gets "room full". Every socket event is checked against the authenticated seat; chat is rendered as text (no HTML); same-origin check on Socket.IO; basic rate limits; no audio is ever recorded or stored. Rooms (game + chat) persist in SQLite and expire after `ROOM_TTL_DAYS` of inactivity. Refresh/reconnect restores your seat from the saved token.

## 8. Voice / TURN

Uses STUN by default. If voice stays on "connecting/failed" on some mobile networks, run a TURN server (coturn) and fill `TURN_URL/TURN_USERNAME/TURN_CREDENTIAL` in `.env`, then `docker compose up -d`.

## 9. Honest limitations (v1)

- Avatars are emoji presets; **no custom image upload/cropping yet**.
- TURN credentials from `.env` are static (not short-lived) and are sent to joined clients.
- No Content-Security-Policy header yet (page uses inline script); Socket.IO client loads from cdn.socket.io.
- Code is condensed into `app.py` + `engine.py` rather than the full module tree; only engine tests (`pytest tests`) exist — no browser/E2E tests.
- Verified here: engine rules, room create/join/full, auth rejection, chat, turn enforcement. **Not yet verified:** real two-device play, WebRTC audio, Nginx/HTTPS on your VPS, PWA install. Test those after deploying.
- Single gunicorn worker by design (presence is in-memory); fine for 2 players.
