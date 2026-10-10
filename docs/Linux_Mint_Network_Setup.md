# FootballAnalysisEngine on another Wi-Fi (Linux Mint)

Run the interactive helper from the project root after the notebook and, if it
is used as a client, the Samsung Note 9 have joined the same Wi-Fi:

```bash
git switch football-engine
git pull --ff-only
./scripts/network_setup.sh
```

The helper discovers the notebook's active default-route interface, IPv4/CIDR
and gateway. It deliberately rejects Docker, bridge, veth and Tailscale as the
default LAN connection. It asks for the phone's IPv4 only to perform optional
reachability checks; this repository does not establish that the phone hosts a
service.

## What the repository actually runs

1. `scripts/init_database.py` creates/updates the local SQLite database.
2. The optional SearXNG Docker Compose stack provides the local search service.
   Its repository default is `127.0.0.1:8080`.
3. FastAPI is launched as `uvicorn app.main:app`; the local proxy default in
   the repository is port `8000`.
4. `scripts/run_worker.py` launches the pull-based local worker.
5. Ollama is optional. Its application default is `127.0.0.1:11434`; the
   helper never downloads a model automatically.

The helper creates an ignored `services/searxng/local-config/settings.yml` on
first SearXNG start and replaces the template secret with a random local one.
It does not place secrets in Git.

## Phone access and safety

Keep the API loopback-only unless the phone must call it. When asked to expose
it, the helper requires `WORKER_API_TOKEN` or `API_SECRET_TOKEN` already be
exported in that terminal, then binds FastAPI to the LAN. For example, choose a
new value locally and do not commit it:

```bash
export WORKER_API_TOKEN='replace-with-a-long-random-secret'
./scripts/network_setup.sh
```

The only unauthenticated endpoints are health checks. Protected API calls must
send `X-Worker-Token` (or a Bearer token). The script never changes firewall
rules, uses no `sudo`, and does not open a phone-side port.

## Useful commands

```bash
curl -fsS http://127.0.0.1:8000/health
tail -f logs/api.log
tail -f logs/worker.log
pkill -f 'uvicorn app.main:app'
pkill -f 'scripts/run_worker.py'
```

If SearXNG does not become ready, use:

```bash
cd services/searxng
docker compose logs --tail=100 core
```

If the phone cannot reach the notebook after LAN exposure, first confirm both
devices are on the same Wi-Fi and that client isolation is disabled on the
router. Then test `http://NOTEBOOK_IP:8000/health`. Only after that evidence,
review any local firewall rule manually.
