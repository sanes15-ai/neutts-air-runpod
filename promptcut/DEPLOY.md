# Hosting PromptCut on your own cloud box

Three paths, pick one. In all of them the UI ends up at
`http://YOUR_SERVER_IP:7859/?token=YOUR_TOKEN`.

**Security first:** the server edits files and runs renders. Never expose it
without `PROMPTCUT_TOKEN` set. Generate one with `openssl rand -hex 16`.

---

## Path A — Docker (recommended)

Needs Docker on the box (`curl -fsSL https://get.docker.com | sh`).

```bash
git clone -b claude/github-web-design-repos-ojfba7 \
    https://github.com/sanes15-ai/neutts-air-runpod.git
cd neutts-air-runpod/promptcut

export PROMPTCUT_TOKEN=$(openssl rand -hex 16); echo "token: $PROMPTCUT_TOKEN"
docker compose up -d --build
```

First boot seeds a demo project into `./project/` so there is something to
open immediately. Your real footage goes in `./project/media/` (upload with
`scp`/`rsync`), then register it from inside the container:

```bash
docker compose exec promptcut promptcut add media/yourclip.mp4
```

Check it: `docker compose logs -f promptcut`, then open
`http://SERVER_IP:7859/?token=...`.

## Path B — bare metal (no Docker)

```bash
git clone -b claude/github-web-design-repos-ojfba7 \
    https://github.com/sanes15-ai/neutts-air-runpod.git
cd neutts-air-runpod/promptcut
pip install -e .
./scripts/get_ffmpeg.sh                   # or apt install ffmpeg
promptcut doctor                          # must be all green

mkdir -p ~/edits/first && cd ~/edits/first
promptcut new first
export PROMPTCUT_TOKEN=$(openssl rand -hex 16); echo "token: $PROMPTCUT_TOKEN"
promptcut serve --host 0.0.0.0 --port 7859
```

Keep it alive with systemd — `/etc/systemd/system/promptcut.service`:

```ini
[Unit]
Description=PromptCut
After=network.target

[Service]
User=YOUR_USER
WorkingDirectory=/home/YOUR_USER/edits/first
Environment=PROMPTCUT_TOKEN=YOUR_TOKEN
ExecStart=/usr/bin/env promptcut serve --host 0.0.0.0 --port 7859
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

`sudo systemctl enable --now promptcut`

## Path C — RunPod / GPU pod

Same as Path B inside the pod; expose port 7859 in the pod's HTTP port
settings and open the proxy URL RunPod gives you (append `?token=...`).
Renders are CPU-bound x264 — any pod works; more vCPUs = faster finals.

---

## Testing the install

```bash
cd neutts-air-runpod/promptcut
python -m unittest discover tests -v      # 8 tests, all green expected
promptcut doctor                          # ffmpeg/ffprobe/font all present
```

## Nice-to-haves once it works

- **TLS + domain**: put nginx or Caddy in front (`caddy reverse-proxy
  --from edit.yourdomain.com --to localhost:7859`) — Caddy auto-provisions
  HTTPS.
- **Claude Code on the box**: install Claude Code on the server, open the
  project folder, and the bundled skill (`.claude/skills/promptcut/`) lets
  you edit by prompt on the same files the UI shows.
- **Firewall**: `ufw allow 7859/tcp` (or restrict to your IP:
  `ufw allow from YOUR_IP to any port 7859`).
