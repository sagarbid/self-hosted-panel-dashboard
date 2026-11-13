# Family Panel — 15.6" FotoCube Dashboard

**Live on the panel** at `http://192.168.4.53:8081`

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  FotoCube HY_S915 panel (Android 8.1, RK3326)           │
│  kiosk app: dev.kiosk.panel/.MainActivity               │
│  boots straight into →  http://192.168.4.53:8081        │
└───────────────────────────┬─────────────────────────────┘
                            │
              ┌─────────────▼──────────────┐
              │  GLANCE  :8081             │  ← the shell + theme
              │  3 pages: Home/Kids/Photos │
              └──────┬──────────────┬──────┘
                     │ iframe       │ iframe
        ┌────────────▼───┐   ┌──────▼─────────┐
        │ /kids  :8082   │   │ /photos :8082  │
        └────────────────┘   └────────────────┘
              FAMILY HUB  (Python, stdlib only)
```

Both services run under **launchd** — start at login, self-heal on crash.

---

## Services

| Service | Port | launchd label |
|---|---|---|
| Glance (dashboard shell) | 8081 | `dev.family.glance` |
| Family Hub (kids + photos) | 8082 | `dev.family.hub` |

### Control
```bash
# status
launchctl list | grep dev.family

# restart
launchctl kickstart -k gui/$(id -u)/dev.family.glance
launchctl kickstart -k gui/$(id -u)/dev.family.hub

# stop / start
launchctl unload ~/Library/LaunchAgents/dev.family.glance.plist
launchctl load -w ~/Library/LaunchAgents/dev.family.glance.plist
```

### Logs
```bash
tail -f ~/Library/Logs/family-panel-glance.err.log
tail -f ~/Library/Logs/family-panel-hub.err.log
```

---

## ⚠️ CRITICAL: why everything lives on the INTERNAL disk

**launchd cannot execute binaries from `/Volumes/…`, and processes it spawns are blocked by
macOS TCC from reading external volumes.**

Two failures this caused, both fixed by moving to the internal disk:

| Symptom | Cause |
|---|---|
| Both agents exited `78: EX_CONFIG`, empty logs | launchd refuses to exec from `/Volumes` |
| `PermissionError: [Errno 1] Operation not permitted: '/Volumes/Seagate/…/photos'` | TCC blocks launchd-spawned processes from removable volumes |

**Therefore:**

| Path | Purpose |
|---|---|
| `~/Library/Application Support/family-panel/glance/glance` | Glance binary |
| `~/Library/Application Support/family-panel/glance/config/glance.yml` | **edit the config HERE** |
| `~/Library/Application Support/family-panel/hub/family_hub.py` | Family Hub script |
| `~/Library/Application Support/family-panel/hub/data/state.json` | Habit/task/reward state |
| `~/Library/Application Support/family-panel/hub/data/photos/` | **drop photos HERE** |

Seagate copies are kept as the editable source in `/Volumes/Seagate/Projects/glance/` and
`/Volumes/Seagate/Projects/family-hub/`, but **changes must be copied into
`~/Library/Application Support/family-panel/` and the service restarted to take effect.**

---

## Pages

### Home — the premium dashboard
- **Clock** (24h, Melbourne + UTC) · **Weather** (Melbourne) · **Calendar**
- **Portfolio** — live CoinGecko data for TAO / VVV / MET / GLMR, colour-coded 24h change
  *(CoinGecko needs no API key. SN93 is not listed there.)*
- **Cyber Security** — The Hacker News · BleepingComputer · Krebs on Security
- **AI & Tech** — OpenAI · Google AI · MIT Tech Review

Theme: **Catppuccin Mocha**, `contrast-multiplier: 1.2` (wall-panel legibility).

### Kids — for Ellysse
- **Habits** — 8 tappable tiles, starred. Tap → green + stars. Tap again → undo.
- **Routine** — Morning / After School / Evening checklists
- **Rewards** — spendable star balance, locked/unlocked tiers, progress bar

### Photos — digital photo frame
Full-bleed slideshow, Ken Burns zoom, 1.6 s crossfade, clock overlay, 9 s per photo.

**Add photos to:** `~/Library/Application Support/family-panel/hub/data/photos/`
(JPG · PNG · WEBP · GIF — they start cycling immediately, no restart needed)

---

## Changing the panel's URL

The kiosk persists the URL to SharedPreferences. To repoint it:
```bash
adb -s 0aaf794b4e12996 shell "am start -n dev.kiosk.panel/.MainActivity --es url http://NEW:PORT"
# revert to the built-in default page:
adb -s 0aaf794b4e12996 shell "am start -n dev.kiosk.panel/.MainActivity --bool reset true"
```

## Family Hub API (for automation)

```bash
# read state
curl http://192.168.4.53:8082/api/state

# toggle a habit for today
curl -X POST -H 'Content-Type: application/json' \
  -d '{"habit_id":"read"}' http://192.168.4.53:8082/api/habit/toggle

# toggle a routine task
curl -X POST -H 'Content-Type: application/json' \
  -d '{"block":"morning","task_id":"m2"}' http://192.168.4.53:8082/api/task/toggle

# award/deduct stars (parent override)
curl -X POST -H 'Content-Type: application/json' \
  -d '{"delta":5}' http://192.168.4.53:8082/api/stars/add

# clear today
curl -X POST -H 'Content-Type: application/json' \
  -d '{}' http://192.168.4.53:8082/api/reset-today
```

---

## Editing content

**Habits / routines / rewards** — edit the `DEFAULT_STATE` block in `family_hub.py`, then delete
`state.json` to regenerate (⚠️ wipes star balance), or edit `state.json` directly:
```bash
cd "$HOME/Library/Application Support/family-panel/hub/data"
python3 - <<'PY'
import json; p="state.json"; s=json.load(open(p))
s["kid"]["name"] = "Ellysse"
json.dump(s, open(p,"w"), indent=2)
PY
```

**Dashboard widgets** — edit `glance.yml` in the internal path, validate, restart:
```bash
cd "$HOME/Library/Application Support/family-panel/glance"
./glance -config config/glance.yml config:validate     # must print nothing
launchctl kickstart -k gui/$(id -u)/dev.family.glance
```

---

## Gotchas hit along the way

| Issue | Fix |
|---|---|
| `upper` is not a Glance template function | use CSS `text-transform:uppercase` |
| Port is NOT a CLI flag | set `server.port` in `glance.yml` |
| Glance hydrates client-side | the shell HTML has no widget data — check `/api/pages/<slug>/content/` to verify |
| Docker pull hung via OrbStack's proxy | use the standalone Go binary instead (6 MB, no Docker) |
| `launchctl` exit 78 / empty logs | can't exec from `/Volumes` — run from internal disk |
| TCC blocks external volumes | keep data on the internal disk |
