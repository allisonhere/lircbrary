# lircbrary

Web UI + backend to search `irc.highway.net/#ebooks`, queue DCC downloads, and file ebooks to a target directory.

## Stack
- FastAPI API with RQ worker (Redis-backed)
- IRC/DCC placeholder client (replace with channel-specific logic)
- Vite + React frontend
- Docker Compose for api, worker, redis, frontend

## Quick start
1. Copy `.env.example` to `.env` and adjust paths/IRC creds.
2. `docker-compose up --build`
3. Open http://localhost:3000 (frontend) and hit Search to exercise the mock flow.

## Install on another machine
- Install Docker + Docker Compose.
- Clone this repo (or copy the folder) onto the target box.
- Copy `.env.example` to `.env` and fill in IRC creds plus local paths for `DOWNLOAD_DIR`, `LIBRARY_DIR`, and `TEMP_DIR`.
- Update the bind mounts in `docker-compose.yml` if the remote machine uses different paths (defaults: `/home/allie/temp` and `/home/allie/downloads`).
- From the repo root, run `docker-compose up --build -d`.
- Open `http://<host>:3000` in a browser (API at `http://<host>:8000`). Logs land in the `data` volume and the download/library folders you configured.

### Example docker-compose.yml (GHCR images, env baked in)
```yaml
version: "3.9"

services:
  redis:
    image: redis:7
    restart: unless-stopped
    ports:
      - "6379:6379"

  api:
    image: ghcr.io/allisonhere/lircbrary-backend:latest
    environment:
      - REDIS_URL=redis://redis:6379/0
      - IRC_SERVER=irc.highway.net
      - IRC_PORT=6667
      - IRC_CHANNEL=#ebooks
      - IRC_NICK=lircbrarybot
      - IRC_REALNAME=lircbrary
      - IRC_SSL=false
      - IRC_SSL_VERIFY=true
      - DOWNLOAD_DIR=/downloads
      - LIBRARY_DIR=/downloads
      - TEMP_DIR=/temp
      - QUEUE_NAME=lircbrary-jobs
      - CONFIG_FILE=/data/config.json
    volumes:
      - ./data:/data
      - /home/allie/temp:/temp
      - /home/allie/downloads:/downloads
    command: ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
    ports:
      - "8000:8000"

  worker:
    image: ghcr.io/allisonhere/lircbrary-backend:latest
    command: ["python", "-m", "worker"]
    environment:
      - REDIS_URL=redis://127.0.0.1:6379/0
      - IRC_SERVER=irc.highway.net
      - IRC_PORT=6667
      - IRC_CHANNEL=#ebooks
      - IRC_NICK=lircbrarybot
      - IRC_REALNAME=lircbrary
      - IRC_SSL=false
      - IRC_SSL_VERIFY=true
      - DOWNLOAD_DIR=/downloads
      - LIBRARY_DIR=/downloads
      - TEMP_DIR=/temp
      - QUEUE_NAME=lircbrary-jobs
      - CONFIG_FILE=/data/config.json
    volumes:
      - ./data:/data
      - /home/allie/temp:/temp
      - /home/allie/downloads:/downloads
    network_mode: host

  frontend:
    image: ghcr.io/allisonhere/lircbrary-frontend:latest
    environment:
      - VITE_API_URL=http://localhost:8000
    ports:
      - "3000:3000"
```

### Local build compose (dev)
If you prefer building locally instead of pulling from GHCR, use `docker-compose.local.yml`:
```bash
docker-compose -f docker-compose.local.yml up --build
```

### Prebuilt images (GHCR)
CI pushes images to GitHub Container Registry on every `master` push:
- Backend/worker: `ghcr.io/allisonhere/lircbrary-backend:latest` (also `:sha-<commit>`)
- Frontend: `ghcr.io/allisonhere/lircbrary-frontend:latest` (also `:sha-<commit>`)
If the GHCR package is private, `docker login ghcr.io -u <github-username> -p <PAT-with-packages-scope>` first.

## Configuration
Env vars (see `.env.example`):
- `IRC_SERVER`, `IRC_PORT`, `IRC_CHANNEL`, `IRC_NICK`, `IRC_REALNAME`
- `DOWNLOAD_DIR`, `LIBRARY_DIR`, `TEMP_DIR`
- `REDIS_URL`, `QUEUE_NAME`

## Implementing real IRC/DCC
`backend/app/irc_client.py` has stubbed `search` and `download_pack`. Replace with logic that:
- Connects to `irc.highway.net`, joins `#ebooks`, and issues the channel’s search command.
- Parses bot responses into `SearchResult`.
- Requests a pack and accepts the DCC SEND offer.
- Streams the file to `dest` and returns its path.

Jobs are enqueued via `/download`, processed by `backend/worker.py`, extracted, and saved to the library folder.

## Development without Docker
- API: `cd backend && pip install -r requirements.txt && uvicorn app.main:app --reload`
- Worker: `cd backend && python -m worker`
- Frontend: `cd frontend && npm install && npm run dev`

## Notes
- Archive extraction uses a simple traversal guard but you should still validate trusted senders and max sizes.
- Frontend polls `/jobs/{id}` every 2s; increase/back off as needed.
