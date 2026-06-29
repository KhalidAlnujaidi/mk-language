---
name: deploy-dashboard
description: Deploy any kinox dashboard (or long-running local service) as a systemd unit so it stays live 24/7 — survives reboot, auto-restarts on crash. Use whenever a dashboard should be always-on instead of a detached nohup process, or to standardize how observability surfaces ship on the host.
metadata:
  origin: kinox
---

# Deploy a Dashboard as a systemd Service

The kinox default for every dashboard: never leave it as a `nohup ... &` process
that dies on reboot. Run it under **systemd** so it is boot-persistent and
self-healing. This is the standard deployment for all dashboards.

## When to Use
- A dashboard / web UI (Streamlit, stdlib `http.server`, FastAPI, …) should be live 24/7.
- You started something with `nohup ... &` and want it to survive reboots and crashes.
- Standardizing how any observability surface is deployed on the host.

## Principles
- Bind to `0.0.0.0` and run headless — reachable over LAN / Tailscale.
- One service per dashboard, named `kx-<thing>` (e.g. `kx-ui`, `kx-council`).
- `Restart=on-failure` + `WantedBy=multi-user.target` (auto-restart, starts at boot).
- Run as the owning user (not root), `WorkingDirectory` at the repo root.
- Dashboards are read-only observers of host state — keep them that way.

## How It Works
Use the helper `tools/deploy-dashboard.sh` (it generates the unit; installs it
when run as root, otherwise prints the `sudo` commands):

```bash
tools/deploy-dashboard.sh \
  --name kx-ui \
  --desc "kinox observability dashboard" \
  --workdir /home/enigma/kinox \
  --port 8501 \
  --exec '/home/enigma/kinox/.venv/bin/python -m streamlit run /home/enigma/kinox/products/dashboard/streamlit_app.py --server.headless true --server.address 0.0.0.0 --server.port 8501'
```

Then (if you weren't root):
```bash
sudo cp tools/kx-ui.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now kx-ui.service
```

Always **free the port first** (stop any `nohup` instance: `kill $(cat tools/<name>.pid)`)
or the start fails to bind.

### Verify
```bash
systemctl status <name> --no-pager      # expect: active (running)
journalctl -u <name> -n 30 --no-pager   # logs if it failed to start
```

### Example — the council/language dashboard on :8800
```bash
tools/deploy-dashboard.sh --name kx-council \
  --desc "kinox council/language experiment dashboard" \
  --workdir /home/enigma/kinox --port 8800 \
  --exec '/home/enigma/kinox/.venv/bin/python projects/language/dashboard.py'
```

## Notes
- To remove a dashboard service: `sudo systemctl disable --now <name> && sudo rm /etc/systemd/system/<name>.service && sudo systemctl daemon-reload`.
- For something that should run as a one-shot (stop after a single result), use `Type=simple` with the process exiting 0 and no restart — see `tools/kx-writer-daemon.sh` for that pattern.
