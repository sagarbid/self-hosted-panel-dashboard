---
name: self-hosted-panel-dashboard
description: Build a premium self-hosted panel dashboard.
version: 1.0.0
author: Sagar Bidari
license: MIT
metadata:
  hermes:
    tags:
      - dashboard
      - glance
      - self-hosted
      - android
      - kiosk
      - launchd
      - macos
      - smart-display
    related_skills:
      - self-hosted-infra
      - macos-remote-desktop
---

# Self-Hosted Panel Dashboard

Turn a cheap Android smart panel / photo frame into a premium, self-hosted wall dashboard
with live widgets, a custom kids/family app, and a photo frame — no cloud, no subscription.

## When to use

- User wants a dashboard/calendar/photo display on a dedicated screen
- Repurposing a Chinese ODM smart panel (FotoCube, Frameo, Skylight, digital calendar, photo frame)
- "Make this look premium" on a wall-mounted display
- Building a local dashboard with live widgets (markets, weather, feeds, calendar)
- Adding a family/kids section (habits, chores, rewards) to a display

## Architecture (proven)

```
PANEL (Android + kiosk app)
   └─► http://<mac-ip>:8081
            │
        GLANCE  ← shell, theme, pages, widgets
            │
      ┌─────┴─────┐
   /kids       /photos        ← custom local service, embedded inline frames
      └─────┬─────┘
     FAMILY HUB :8082  (Python stdlib, zero deps)
```

**Why this shape:** Glance is unbeatable for feed/stat widgets but has no stateful
interactivity (its `todo` widget is read-only). So anything needing *taps that persist*
gets its own tiny local service, embedded via Glance's `iframe` widget.

## Step 1 — Pick the dashboard

**Glance** is the default recommendation. Verify the choice with current data:

```bash
curl -s https://api.github.com/repos/glanceapp/glance | python3 -c "
import json,sys; d=json.load(sys.stdin)
print(d['stargazers_count'], d['license']['spdx_id'], d['language'], d['pushed_at'])"
```

| Option | Verdict |
|---|---|
| **Glance** | ✅ Pick. Go, single <20MB binary, minimal RAM, best widget set, custom CSS/themes |
| Homarr | Only if user wants a *clickable app launcher* — burns 512MB–1GB RAM |
| Homepage | YAML, decent widgets, utilitarian look |
| Dashy | Status-check oriented |
| DAKboard / Mango | ❌ Cloud SaaS, subscription, not self-hosted |

## Step 2 — Deploy Glance as a standalone binary (NOT Docker)

⚠️ **Do not reach for Docker first.** On macOS with OrbStack, `docker pull` can hang
indefinitely behind the internal proxy (`proxy.orb.internal:8305`) — observed a 25 MB image
stall for 7+ minutes with no progress. The standalone binary is smaller, faster, and has
none of that failure mode.

```bash
cd /path/to/glance
curl -s https://api.github.com/repos/glanceapp/glance/releases/latest \
  | python3 -c "
import json,sys
for a in json.load(sys.stdin)['assets']: print(a['name'], a['browser_download_url'])"
# pick the matching platform, e.g. glance-darwin-amd64.tar.gz for Intel macOS
curl -sL -o glance.tar.gz "<url>" && tar xzf glance.tar.gz
./glance --version
```

### Glance config essentials

```yaml
server:
  port: 8081          # ⚠️ there is NO -port CLI flag — port lives HERE

pages:
  - name: Home
    columns:
      - size: small   # fixed 300px
        widgets: []
      - size: full    # remaining width
        widgets: []
```

**Column rules:** max 3 columns per page; there must be 1 or 2 `full` columns.
`small` = fixed 300px. On a 1280px panel, `small + full` gives 300 + ~980.

### Always validate before starting
```bash
./glance -config config/glance.yml config:validate   # silent + exit 0 == valid
./glance -config config/glance.yml
```

### Widget cheat-sheet (v0.8.x)
`clock` `weather` `calendar` `markets` `rss` `reddit` `hacker-news` `youtube-videos`
`docker` `server-stats` `dns-stats` `monitor` `todo` `bookmarks` `search` `releases`
`repository` `twitch` `lobsters` `iframe` `html` `custom-api` `group` `split`

## Step 3 — Custom API widget (live data with no key)

`markets` only speaks Yahoo Finance, so altcoins/small caps won't resolve. Use
`custom-api` against CoinGecko — **it works keyless**:

```yaml
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
```

⚠️ **`upper` is NOT a Glance template function.** Use CSS `text-transform:uppercase`.
⚠️ Root-level arrays work with `.JSON.Array ""`; nested paths use `.JSON.Array "a.b"`.

## Step 4 — Custom service for interactive content

Build with **Python stdlib only** (`http.server.ThreadingHTTPServer` + a JSON file). Zero
dependencies means zero install breakage and it survives forever.

Pattern that works:
- `GET  /`           → redirect
- `GET  /<page>`     → server-rendered HTML (styled to match the shell theme)
- `GET  /api/state`  → JSON state + derived values
- `POST /api/<verb>` → mutate + persist

**Make the data dir relocatable** — this is essential, because the service will almost
certainly need to run from a different disk than its data:
```python
BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.environ.get("HUB_DATA", BASE)
STATE_FILE = os.path.join(DATA, "state.json")
```

**Design for a wall panel:** oversized tap targets, high contrast, no hover-only
affordances, auto-refresh timer, and a `location.reload()` after each mutation so the
on-screen state can never drift from the file.

⚠️ When writing HTML inside a Python f-string, **every literal brace in CSS/JS must be
doubled** (`{{` / `}}`). A single `{` around JS like `{setTimeout(...)}` becomes an
f-string expression and raises *"expression cannot contain assignment"*. This is the
single most common authoring bug — write the JS in a separate non-f-string constant when
it gets long.

## Step 5 — Wire custom pages into Glance

```yaml
  - name: Kids
    width: wide
    columns:
      - size: full
        widgets:
          - type: iframe
            source: http://192.168.4.53:8082/kids
            height: 1560px     # tall enough to avoid nested scrollbars
```

## Step 6 — launchd on macOS (⚠️ the big one)

**Two hard macOS restrictions, both discovered the hard way:**

| Symptom | Root cause |
|---|---|
| Agent exits `78: EX_CONFIG`, **empty logs** | launchd **cannot exec binaries from `/Volumes`** (external disks) |
| `PermissionError: [Errno 1] Operation not permitted: /Volumes/...` | **TCC blocks launchd-spawned processes from reading external volumes** |

**Therefore: every service binary, script, and data dir must live on the INTERNAL disk.**
Use external volumes only for bulk assets you copy from.

Put them in `~/Library/Application Support/<app>/`, and keep the external copy as the
editable "source" that you sync inward.

```xml
<!-- ~/Library/LaunchAgents/dev.family.glance.plist -->
<key>ProgramArguments</key>
<array>
  <string>/Users/you/Library/Application Support/family-panel/glance/glance</string>
  <string>-config</string>
  <string>/Users/you/Library/Application Support/family-panel/glance/config/glance.yml</string>
</array>
<key>RunAtLoad</key><true/>
<key>KeepAlive</key><true/>
<key>StandardOutPath</key><string>/Users/you/Library/Logs/family-panel-glance.out.log</string>
<key>StandardErrorPath</key><string>/Users/you/Library/Logs/family-panel-glance.err.log</string>
```

```bash
plutil -lint ~/Library/LaunchAgents/*.plist     # validate FIRST
launchctl load -w ~/Library/LaunchAgents/dev.family.glance.plist
launchctl list | grep dev.family                 # PID + last exit code
launchctl kickstart -k gui/$(id -u)/dev.family.glance   # restart
```

⚠️ Kill any manually-started copy **before** loading the agent, or the port stays bound by
the wrong process and the agent crash-loops on `address already in use`.

## Step 7 — Point the panel at it

If you already control a kiosk app whose URL is persisted to SharedPreferences:
```bash
adb shell "am start -n dev.kiosk.panel/.MainActivity --es url http://192.168.4.53:8081"
```

## Verification (do NOT trust the page HTML)

⚠️ **Glance hydrates client-side.** The served page is a ~9 KB shell with no widget data —
grepping it for your content returns nothing and looks like a failure. It isn't.

**Correct verification:**
```bash
# 1. widget content endpoint (server-rendered here)
curl -s "http://127.0.0.1:8081/api/pages/home/content/" -o /tmp/c.html
wc -c < /tmp/c.html                       # ~40KB when widgets render
grep -q "Bittensor" /tmp/c.html && echo OK

# 2. inline frames present?
curl -s "http://127.0.0.1:8081/api/pages/kids/content/" | grep -o '<iframe[^>]*'

# 3. PROOF the panel is actually displaying it — look for its TCP connections
lsof -i :8081 -P -n | grep "<panel-ip>"
```

⚠️ **Panel connections are short-lived.** HTTP requests idle-close after load, so a
one-shot `lsof` often shows nothing. Poll in a loop while forcing a kiosk reload:
```bash
adb shell am force-stop dev.kiosk.panel; sleep 2
adb shell am start -n dev.kiosk.panel/.MainActivity
for i in $(seq 1 20); do
  c=$(lsof -i :8081 -P -n | grep -c "<panel-ip>")
  [ "$c" -gt 0 ] && echo "t=${i}s glance=$c  CONNECTED"
  sleep 1
done
```

## Pitfalls summary

| Pitfall | Fix |
|---|---|
| `docker pull` hangs on macOS/OrbStack | use the standalone Go binary |
| `-port` flag doesn't exist | set `server.port` in the YAML |
| `upper` template function undefined | use CSS `text-transform` |
| Widget grep finds nothing | Glance is client-side; hit `/api/pages/<slug>/content/` |
| launchd exit 78, empty logs | can't exec from `/Volumes` — move to internal disk |
| TCC `Errno 1` on external volume | move data to internal disk |
| f-string "expression cannot contain assignment" | double every literal `{}` in embedded CSS/JS |
| Agent loops on `address already in use` | kill the manual process before loading the agent |
| Single `lsof` shows no panel connection | poll in a loop; connections idle-close |

## Panel-side prerequisites

The panel needs an Android kiosk app that (a) registers as HOME, (b) hides system UI,
(c) keeps the screen awake, (d) auto-starts via a BOOT_COMPLETED receiver, and (e) persists
a configurable URL. See the companion `fotocube-jailbreak` work for the device-access half
(Rockchip ADB enablement, verified partition backup, `su 0` capability limits).

⚠️ `su 0` on these builds typically holds only `CAP_SETUID` + `CAP_SETGID` — **no
`CAP_DAC_OVERRIDE`**. Read system-owned files by switching user instead (`su 1000`).
