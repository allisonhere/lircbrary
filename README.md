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
