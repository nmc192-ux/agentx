# AgentX Workers

Run workers in Docker so they share the same dependency set and environment as the API.

Start one worker:

```bash
docker compose up -d worker
```

Start the full stack with workers:

```bash
docker compose up -d --build
```

Scale workers horizontally:

```bash
docker compose up -d --scale worker=3
```

Inspect worker logs:

```bash
docker compose logs worker
```

Do not run `python3 workers/worker.py` from the host machine for normal development.
