# AgentX Platform

## Testing

Run tests inside the API container so the test environment matches the runtime environment:

```bash
docker compose exec api pytest
```

Or use:

```bash
make test
```

Do not run `pytest` directly on the host Python environment.
