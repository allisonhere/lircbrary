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

### Example docker-compose.yml
```yaml
version: "3.9"

services:
  redis:
    image: redis:7
    restart: unless-stopped
    ports:
      - "6379:6379"

  api:
    build:
      context: ./backend
      dockerfile: Dockerfile
    env_file: .env
    environment:
      - REDIS_URL=redis://redis:6379/0
    volumes:
      - ./data:/data
      - /home/allie/temp:/temp
      - /home/allie/downloads:/downloads
    command: ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
    ports:
      - "8000:8000"

  worker:
    build:
      context: ./backend
      dockerfile: Dockerfile
    command: ["python", "-m", "worker"]
    env_file: .env
    environment:
      - REDIS_URL=redis://127.0.0.1:6379/0
    volumes:
      - ./data:/data
      - /home/allie/temp:/temp
      - /home/allie/downloads:/downloads
    network_mode: host

  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    environment:
      - VITE_API_URL=http://localhost:8000
    ports:
      - "3000:3000"
```

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
