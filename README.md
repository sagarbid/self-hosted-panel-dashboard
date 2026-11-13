# Self-Hosted Panel Dashboard

Turn a **cheap Android smart panel** — a digital calendar, photo frame, or Chinese ODM
device — into a genuinely **premium, self-hosted wall dashboard**. No cloud. No
subscription. No vendor app.

Built and verified end-to-end on a **FotoCube HY-XKSZ-15.6** (Rockchip RK3326, Android 8.1).

```
┌──────────────────────────────────────────────────────────┐
│  ANDROID PANEL                                           │
│  custom kiosk app  →  http://<host>:8081                 │
└───────────────────────────┬──────────────────────────────┘
                            │
              ┌─────────────▼──────────────┐
              │  GLANCE  :8081             │  shell + theme + widgets
              │  Home / Kids / Photos      │
              └──────┬──────────────┬──────┘
                     │ iframe       │ iframe
        ┌────────────▼───┐   ┌──────▼─────────┐
        │  /kids  :8082  │   │ /photos :8082  │
        └────────────────┘   └────────────────┘
            FAMILY HUB — Python stdlib, zero deps
```

## What you get

| Page | Contents |
|---|---|
| **Home** | Clock · Weather · Calendar · **live portfolio** (CoinGecko, keyless) · security & AI news feeds |
| **Kids** | Habit tracker · routine checklists · star-based reward economy |
| **Photos** | Full-bleed slideshow, Ken Burns zoom, crossfade, clock overlay |

Theme: **Catppuccin Mocha** at `contrast-multiplier 1.2` — tuned for legibility at
across-the-room distance.

## Why Glance

| | Glance | Homarr | Homepage | Dashy | DAKboard |
|---|---|---|---|---|---|
| Runtime | **Go, <20 MB binary** | Node, 512 MB–1 GB RAM | Node | Node | Cloud SaaS |
| Self-hosted | ✅ | ✅ | ✅ | ✅ | ❌ |
| Markets widget | ✅ | ❌ | ⚠️ | ⚠️ | ⚠️ |
| Custom API | ✅ full Go templates | ❌ | ❌ | ⚠️ | ❌ |
| iFrame | ✅ | ❌ | ❌ | ✅ | ❌ |
| Custom CSS | ✅ | ⚠️ | ⚠️ | ✅ | ❌ |

> Glance wins for a **feed-and-stats wall page**. Homarr only wins if you want a
> *clickable app launcher* — which a wall display doesn't.

## Quick start

```bash
# 1. Grab the standalone binary (NOT Docker — see PITFALLS)
curl -s https://api.github.com/repos/glanceapp/glance/releases/latest \
  | python3 -c "import json,sys; [print(a['name'], a['browser_download_url']) for a in json.load(sys.stdin)['assets']]"
curl -sL -o glance.tar.gz <url> && tar xzf glance.tar.gz

# 2. Configure — note: port lives in the YAML, there is NO -port flag
cat > config/glance.yml <<'YAML'
server:
  port: 8081
pages:
  - name: Home
    columns:
      - size: small
        widgets:
          - type: clock
            hour-format: 24h
          - type: weather
            location: Melbourne, Australia
            units: metric
      - size: full
        widgets:
          - type: custom-api
            title: Portfolio
            cache: 5m
            url: https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&ids=bittensor,venice-token,meteora,moonbeam&price_change_percentage=24h
            template: |
              <ul class="list list-gap-10">
              {{ range .JSON.Array "" }}
                <li class="flex justify-between">
                  <span class="color-highlight" style="text-transform:uppercase">{{ .String "symbol" }}</span>
                  <span>{{ .Float "current_price" | printf "$%.4f" }}</span>
                </li>
              {{ end }}
              </ul>
YAML

# 3. ALWAYS validate
./glance -config config/glance.yml config:validate   # silent + exit 0 == valid

# 4. Run
./glance -config config/glance.yml
```

Then point your panel's kiosk app at `http://<host-ip>:8081`.

## ⚠️ Read this before you start — the five traps

Full detail in [`SKILL.md`](SKILL.md). The short version:

1. **`docker pull` can hang forever** on macOS behind OrbStack's internal proxy
   (`proxy.orb.internal:8305`). A 25 MB image stalled 7+ minutes. **Use the standalone Go
   binary** — smaller, faster, no proxy.
2. **`launchd` cannot exec from `/Volumes`** — agents exit `78: EX_CONFIG` with *empty logs*.
   And **TCC blocks launchd-spawned processes from reading external volumes**
   (`PermissionError: [Errno 1]`). **Every service binary, script and data dir must live on
   the internal disk.**
3. **`-port` is not a CLI flag** — the port goes in `server.port` in the YAML.
4. **`upper` is not a Glance template function** — use CSS `text-transform`.
5. **Glance hydrates client-side** — the served HTML is a ~9 KB shell with no widget data.
   Grepping it looks like a failure and isn't. Verify with
   `/api/pages/<slug>/content/` instead.

## Verifying it actually works

```bash
# widget content (server-rendered here)
curl -s "http://127.0.0.1:8081/api/pages/home/content/" | wc -c    # ~40KB when rendering

# inline frames present
curl -s "http://127.0.0.1:8081/api/pages/kids/content/" | grep -o '<iframe[^>]*'

# PROOF the panel is displaying it — poll, because connections idle-close
for i in $(seq 1 20); do
  lsof -i :8081 -P -n | grep -q "<panel-ip>" && echo "t=${i}s CONNECTED"
  sleep 1
done
```

## Repo layout

```
SKILL.md                       full playbook (architecture, steps, pitfalls, verification)
examples/glance.yml            working config — 3 pages incl. CoinGecko portfolio
examples/family_hub.py         the stdlib-only kids/photo service (habits, routine, rewards)
```

## Requirements

- **Glance** — https://github.com/glanceapp/glance (MIT)
- An Android panel you control, with a kiosk app that registers as HOME and persists a URL
- Python 3 (stdlib only) for the custom service
- macOS + `launchd` if you want boot persistence

## Licence

MIT
