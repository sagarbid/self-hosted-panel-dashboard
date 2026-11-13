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

## 📺 Streaming on a panel with no Google Play Services

Most cheap panels ship **without GMS** — which kills the Netflix/Spotify/YouTube apps
outright, and Widevine is **L3 at best** on uncertified SoCs like the RK3326. So
**Netflix / Disney+ / Prime Video are simply not possible** on this hardware. Don't waste
time on them.

What *does* work, verified on-device:

| Service | Route | Status |
|---|---|---|
| **YouTube** | SmartTube (ad-free, big-screen) | ✅ works, no GMS |
| **YouTube** | NewPipe | ✅ works, no GMS |
| **PeerTube / SoundCloud** | NewPipe | ✅ |
| **Twitch / YouTube web** | WebView browser | ✅ |
| **Your own media** | local file server + WebView `<video>` | ✅ hardware-decoded |
| **Local files** | RockVideoPlayer (re-enable it — vendors ship it) | ✅ HW-accelerated |
| Jellyfin server | needs Docker (no native mac build) | ⚠️ optional |
| Netflix / Disney+ / Prime | needs Widevine **L1** + certification | ❌ impossible |

### Why the device audit decides everything

Before promising any streaming, check:

```bash
# 1. DRM — is there a Widevine engine at all?
adb shell getprop | grep -i widevine
adb shell ls /vendor/lib/libwvdrmengine.so

# 2. GMS present? (if absent, only GMS-free clients will install)
adb shell pm list packages | grep -iE 'gms|vending|com.google.android.gms'

# 3. Hardware codecs — what can the VPU actually decode?
adb shell cat /vendor/etc/media_codecs.xml | grep -oE 'name="OMX[^"]*"'

# 4. ABI — pick APKs that match, or they'll install then refuse to run
adb shell getprop ro.product.cpu.abilist
```

Both NewPipe and SmartTube publish **`armeabi-v7a`** builds — always match the ABI. F-Droid
serves **x86_64** for VLC, so its main-repo APK will install and then fail.

### Launching apps from the dashboard

An Android WebView honours the `intent://` scheme, so a bookmark can launch a native app:

```yaml
- type: bookmarks
  groups:
    - name: Streaming Apps
      links:
        - title: SmartTube
          url: intent://browse#Intent;package=org.smarttube.stable;end
```

### ⚠️ The return problem (and its fix)

Once an external app covers the screen, a kiosk panel with **no physical Home button** is
stuck. Verified fix — the HOME keyevent returns to the kiosk:

```bash
adb shell input keyevent 3     # HOME -> kiosk resumes
```

Confirm the device maps HOME/BACK/MENU at all:
```bash
adb shell cat /system/usr/keylayout/*.kl | grep -E 'HOME|BACK|MENU'
```
For a hands-free panel, add a floating overlay button to the kiosk app, or keep playback
*inside* the WebView so no app switch ever happens.

### Playing local media with no server at all

You don't need Jellyfin. Serve files over HTTP with **Range support** and let the WebView's
`<video>` tag handle it — the panel's VPU does the decoding:

```
GET /stream?f=<relpath>   -> 206 Partial Content, Content-Range
```

Range support is what makes **seeking** work; without it the scrubber is dead. Match the
container to the VPU: **H.264/AAC in `.mp4` is guaranteed**; `.mkv`/`HEVC` depend on
`OMX.rk.video_decoder.*` entries in `/vendor/etc/media_codecs.xml`.

---

## ⚠️ Read this before you start — the traps

Full detail in [`SKILL.md`](SKILL.md). The short version:

1. **`docker pull` can hang forever** on macOS behind OrbStack's internal proxy
   (`proxy.orb.internal:8305`). A 25 MB image stalled 7+ minutes. **Use the standalone Go
   binary** — smaller, faster, no proxy.
2. **`launchd` cannot exec from `/Volumes`** — agents exit `78: EX_CONFIG` with *empty logs*.
   And **TCC blocks launchd-spawned processes from reading external volumes**
   (`PermissionError: [Errno 1]`). **Every service binary, script and data dir must live on
   the internal disk.** (This is why local media must sit on the internal disk, not a big
   external drive — unless you grant Full Disk Access.)
3. **`-port` is not a CLI flag** — the port goes in `server.port` in the YAML.
4. **`upper` is not a Glance template function** — use CSS `text-transform`.
5. **Glance hydrates client-side** — the served HTML is a ~9 KB shell with no widget data.
   Grepping it looks like a failure and isn't. Verify with
   `/api/pages/<slug>/content/` instead.
6. **Widget type is `docker-containers`, not `docker`** — the docs' heading text isn't the
   type string. The error is `unknown widget type: docker`.
7. **Theme and bookmark colours are `H S L`, not RGB** — `color: 203 166 247` fails with
   *"HSL saturation must be between 0 and 100"*.
8. **`iframe` height must be an integer** — `height: 1400`, never `height: 1400px`.
9. **`launchctl list` showing `exit -15` does NOT mean the service is down** — that's the
   stale code from your own `kickstart -k`. Confirm with an HTTP request, not the exit code.

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
