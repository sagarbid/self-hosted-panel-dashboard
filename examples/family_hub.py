#!/usr/bin/env python3
"""
Family Hub — kids dashboard + digital photo frame
Serves the FotoCube panel's Kids and Photos pages.

Stdlib only. No dependencies.

  GET  /                  -> redirect to /kids
  GET  /kids              -> habit tracker + routine + rewards UI
  GET  /photos            -> digital photo frame slideshow
  GET  /api/state         -> full JSON state + derived stats
  POST /api/habit/toggle  {habit_id, date?}
  POST /api/task/toggle   {block, task_id}
  POST /api/reward/redeem {reward_id}
  POST /api/reset-today   {}
  GET  /api/photos        -> list of image filenames
  GET  /media/<name>      -> serve a photo
"""
import json, os, re, html, mimetypes, threading, datetime, posixpath, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE = os.path.dirname(os.path.abspath(__file__))
# Data dir can be relocated (e.g. when the script runs from the internal disk
# but its state + photos live on an external volume).
DATA = os.environ.get("HUB_DATA", BASE)
STATE_FILE = os.path.join(DATA, "state.json")
PHOTO_DIR = os.path.join(DATA, "photos")
PORT = int(os.environ.get("HUB_PORT", "8082"))
LOCK = threading.Lock()

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}

DEFAULT_STATE = {
    "kid": {"name": "Champion", "emoji": "🦸"},
    "habits": [
        {"id": "brush_am", "name": "Brush teeth (AM)", "emoji": "🪥", "stars": 1},
        {"id": "brush_pm", "name": "Brush teeth (PM)", "emoji": "🦷", "stars": 1},
        {"id": "bed",      "name": "Make my bed",     "emoji": "🛏️", "stars": 1},
        {"id": "read",     "name": "Read 20 minutes", "emoji": "📚", "stars": 2},
        {"id": "tidy",     "name": "Tidy my room",    "emoji": "🧸", "stars": 1},
        {"id": "outside",  "name": "Play outside",    "emoji": "🌳", "stars": 1},
        {"id": "water",    "name": "Drink water",     "emoji": "💧", "stars": 1},
        {"id": "kind",     "name": "Do something kind", "emoji": "💛", "stars": 2},
    ],
    "routines": {
        "morning":   {"label": "Morning",   "emoji": "🌅", "tasks": [
            {"id": "m1", "name": "Wake up on time"},
            {"id": "m2", "name": "Brush teeth"},
            {"id": "m3", "name": "Get dressed"},
            {"id": "m4", "name": "Eat breakfast"},
            {"id": "m5", "name": "Pack school bag"},
        ]},
        "afternoon": {"label": "After School", "emoji": "🎒", "tasks": [
            {"id": "a1", "name": "Unpack bag"},
            {"id": "a2", "name": "Have a snack"},
            {"id": "a3", "name": "Homework"},
            {"id": "a4", "name": "Play time"},
        ]},
        "evening":   {"label": "Evening",   "emoji": "🌙", "tasks": [
            {"id": "e1", "name": "Tidy up toys"},
            {"id": "e2", "name": "Bath / shower"},
            {"id": "e3", "name": "Brush teeth"},
            {"id": "e4", "name": "Story time"},
            {"id": "e5", "name": "Lights out on time"},
        ]},
    },
    "rewards": [
        {"id": "r1", "name": "30 min extra screen time", "emoji": "📺", "cost": 10},
        {"id": "r2", "name": "Pick dinner",              "emoji": "🍕", "cost": 15},
        {"id": "r3", "name": "Ice cream trip",           "emoji": "🍦", "cost": 25},
        {"id": "r4", "name": "Movie night pick",         "emoji": "🎬", "cost": 30},
        {"id": "r5", "name": "Trip to the park",         "emoji": "🎡", "cost": 40},
        {"id": "r6", "name": "New book or toy",          "emoji": "🎁", "cost": 60},
    ],
    "stars": 0,
    "star_history": [],
    "log": {},
}


# ---------------------------------------------------------------- state io
def load_state():
    if not os.path.exists(STATE_FILE):
        save_state(DEFAULT_STATE)
        return json.loads(json.dumps(DEFAULT_STATE))
    try:
        with open(STATE_FILE) as f:
            s = json.load(f)
    except Exception:
        return json.loads(json.dumps(DEFAULT_STATE))
    # forward-compatible: fill missing top-level keys
    for k, v in DEFAULT_STATE.items():
        s.setdefault(k, json.loads(json.dumps(v)))
    return s


def save_state(s):
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(s, f, indent=2)
    os.replace(tmp, STATE_FILE)


def today():
    return datetime.date.today().isoformat()


def day_entry(s, d=None):
    d = d or today()
    return s["log"].setdefault(d, {"habits": [], "tasks": []})


def habit_stars(s):
    by_id = {h["id"]: h.get("stars", 1) for h in s["habits"]}
    return sum(by_id.get(h, 1) for h in day_entry(s)["habits"])


def derived(s):
    d = day_entry(s)
    total_h = len(s["habits"])
    all_tasks = [t["id"] for b in s["routines"].values() for t in b["tasks"]]
    return {
        "date": d,
        "habits_done": len(d["habits"]),
        "habits_total": total_h,
        "tasks_done": len(d["tasks"]),
        "tasks_total": len(all_tasks),
        "stars_today": habit_stars(s),
        "stars_total": s["stars"],
        "spendable": s["stars"],
    }


# ---------------------------------------------------------------- html shell
def page(title, body, extra_css=""):
    return f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,user-scalable=no">
<title>{html.escape(title)}</title>
<style>
  :root {{
    --base:#1e1e2e; --mantle:#181825; --crust:#11111b;
    --surface0:#313244; --surface1:#45475a; --surface2:#585b70;
    --text:#cdd6f4; --subtext:#a6adc8; --overlay:#7f849c;
    --blue:#89b4fa; --lavender:#b4befe; --sapphire:#74c7ec; --sky:#89dceb;
    --teal:#94e2d5; --green:#a6e3a1; --yellow:#f9e2af; --peach:#fab387;
    --maroon:#eba0ac; --red:#f38ba8; --mauve:#cba6f7; --pink:#f5c2e7;
  }}
  *{{box-sizing:border-box;-webkit-tap-highlight-color:transparent}}
  html,body{{margin:0;padding:0;height:100%}}
  body{{
    background:var(--crust); color:var(--text);
    font-family:-apple-system,'SF Pro Display','Segoe UI',system-ui,sans-serif;
    overflow-x:hidden;
  }}
  .wrap{{padding:22px 26px 34px;max-width:1280px;margin:0 auto}}
  h1{{font-size:34px;margin:0 0 4px;letter-spacing:-.5px}}
  .sub{{color:var(--subtext);font-size:14px;margin-bottom:20px}}
  .grid{{display:grid;gap:16px}}
  .card{{
    background:var(--mantle);border:1px solid var(--surface0);
    border-radius:18px;padding:18px 20px;
    box-shadow:0 6px 22px rgba(0,0,0,.30);
  }}
  .card h2{{
    font-size:15px;text-transform:uppercase;letter-spacing:1.4px;
    color:var(--overlay);margin:0 0 14px;font-weight:600;
  }}
  /* ---- stars banner ---- */
  .stars{{
    display:flex;align-items:center;justify-content:space-between;
    background:linear-gradient(135deg,#2a2440,#1e1e2e);
    border:1px solid var(--surface1);border-radius:20px;
    padding:18px 24px;margin-bottom:18px;
  }}
  .stars .n{{font-size:52px;font-weight:800;color:var(--yellow);line-height:1}}
  .stars .lbl{{color:var(--subtext);font-size:13px;letter-spacing:1px;text-transform:uppercase}}
  .bar{{height:12px;border-radius:99px;background:var(--surface0);overflow:hidden;margin-top:8px}}
  .bar>i{{display:block;height:100%;background:linear-gradient(90deg,var(--yellow),var(--peach));transition:width .4s}}
  /* ---- habits ---- */
  .habits{{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:12px}}
  .hbtn{{
    display:flex;flex-direction:column;align-items:center;gap:8px;
    padding:16px 10px;border-radius:16px;cursor:pointer;
    background:var(--surface0);border:2px solid transparent;
    transition:transform .12s,background .2s,border-color .2s;
    user-select:none;text-align:center;
  }}
  .hbtn:active{{transform:scale(.95)}}
  .hbtn .e{{font-size:30px;line-height:1}}
  .hbtn .n{{font-size:12.5px;color:var(--subtext);line-height:1.25}}
  .hbtn.on{{background:linear-gradient(160deg,#2d4a34,#1e3226);border-color:var(--green)}}
  .hbtn.on .n{{color:var(--green);font-weight:600}}
  /* ---- routine ---- */
  .rblocks{{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:14px}}
  .rblock .hd{{display:flex;align-items:center;gap:8px;margin-bottom:10px;font-weight:700;font-size:15px}}
  .task{{
    display:flex;align-items:center;gap:11px;padding:11px 13px;margin-bottom:7px;
    border-radius:12px;background:var(--surface0);cursor:pointer;user-select:none;
    transition:background .2s;
  }}
  .task:active{{transform:scale(.98)}}
  .task .box{{
    width:22px;height:22px;border-radius:7px;border:2px solid var(--surface2);
    display:flex;align-items:center;justify-content:center;flex:0 0 auto;
    font-size:14px;color:var(--crust);font-weight:900;
  }}
  .task.on{{background:#22313f}}
  .task.on .box{{background:var(--green);border-color:var(--green)}}
  .task.on .tn{{color:var(--subtext);text-decoration:line-through}}
  .tn{{font-size:14px}}
  /* ---- rewards ---- */
  .rews{{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:12px}}
  .rew{{
    background:var(--surface0);border-radius:14px;padding:14px 15px;
    display:flex;flex-direction:column;gap:8px;border:1px solid transparent;
  }}
  .rew.can{{border-color:var(--mauve);background:#2b2440}}
  .rew .top{{display:flex;align-items:center;gap:9px}}
  .rew .e{{font-size:24px}}
  .rew .rn{{font-size:13.5px;line-height:1.3;flex:1}}
  .rew .cost{{font-size:12px;color:var(--yellow);font-weight:700;white-space:nowrap}}
  .rew button{{
    margin-top:2px;padding:9px;border:0;border-radius:10px;font-size:13px;font-weight:700;
    background:var(--surface1);color:var(--overlay);cursor:pointer;
  }}
  .rew.can button{{background:var(--mauve);color:var(--crust);cursor:pointer}}
  .rew.can button:active{{transform:scale(.97)}}
  /* ---- photos ---- */
  .frame{{position:fixed;inset:0;background:#000;overflow:hidden}}
  .slide{{
    position:absolute;inset:0;background-size:cover;background-position:center;
    opacity:0;transition:opacity 1.6s ease-in-out;
  }}
  .slide.show{{opacity:1;animation:kb 22s ease-out forwards}}
  @keyframes kb{{from{{transform:scale(1)}}to{{transform:scale(1.10)}}}}
  .overlay{{
    position:fixed;left:0;right:0;bottom:0;padding:26px 34px;
    background:linear-gradient(to top,rgba(0,0,0,.72),transparent);
    color:#fff;display:flex;align-items:flex-end;justify-content:space-between;
  }}
  .overlay .clk{{font-size:58px;font-weight:200;letter-spacing:-2px;line-height:1}}
  .overlay .dte{{font-size:16px;opacity:.85;margin-top:8px}}
  .empty{{padding:80px 30px;text-align:center;color:var(--overlay);font-size:16px;line-height:1.7}}
  .toast{{
    position:fixed;left:50%;bottom:44px;transform:translateX(-50%);
    background:var(--surface0);border:1px solid var(--surface2);color:var(--text);
    padding:14px 26px;border-radius:99px;font-size:15px;font-weight:600;
    box-shadow:0 10px 34px rgba(0,0,0,.5);opacity:0;pointer-events:none;
    transition:opacity .3s,transform .3s;z-index:99;
  }}
  .toast.show{{opacity:1;transform:translateX(-50%) translateY(-8px)}}
  {extra_css}
</style></head>
<body>{body}
<div class="toast" id="toast"></div>
<script>
const $=s=>document.querySelector(s);
function toast(m){{const t=$('#toast');t.textContent=m;t.classList.add('show');
  clearTimeout(t._x);t._x=setTimeout(()=>t.classList.remove('show'),1700);}}
async function api(path,body){{
  const r=await fetch(path,{{method:'POST',headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify(body||{{}})}});
  return r.json();
}}
function rel(){{setTimeout(()=>location.reload(),260);}}
</script>
</body></html>"""


# ---------------------------------------------------------------- kids page
def kids_page():
    s = load_state()
    d = derived(s)
    done_h = set(day_entry(s)["habits"])
    done_t = set(day_entry(s)["tasks"])
    kid = s["kid"]

    # stars banner
    next_rew = next((r for r in sorted(s["rewards"], key=lambda x: x["cost"])
                     if r["cost"] > s["stars"]), None)
    if next_rew:
        need = next_rew["cost"] - s["stars"]
        pct = int(100 * s["stars"] / next_rew["cost"]) if next_rew["cost"] else 0
        progress_txt = f"{need} more star{'s' if need != 1 else ''} to unlock {next_rew['emoji']} {next_rew['name']}"
    else:
        pct = 100
        progress_txt = "All rewards unlocked — legend!"
    pct = min(100, pct)

    banner = f"""
    <div class="stars">
      <div>
        <div class="lbl">Stars to spend</div>
        <div class="n">{s['stars']}</div>
      </div>
      <div style="flex:1;max-width:520px;margin-left:30px">
        <div class="lbl">{html.escape(progress_txt)}</div>
        <div class="bar"><i style="width:{pct}%"></i></div>
      </div>
      <div style="text-align:right">
        <div class="lbl">Today</div>
        <div class="n" style="font-size:34px;color:var(--green)">{d['stars_today']}</div>
      </div>
    </div>"""

    habits = "".join(
        f"""<div class="hbtn {'on' if h['id'] in done_h else ''}"
                 onclick="api('/api/habit/toggle',{{habit_id:'{h['id']}'}}).then(rel)">
              <span class="e">{h['emoji']}</span><span class="n">{html.escape(h['name'])}</span>
            </div>""" for h in s["habits"])

    rblocks = "".join(f"""
      <div class="rblock">
        <div class="hd"><span>{b['emoji']}</span><span>{html.escape(b['label'])}</span></div>
        {''.join(f'''<div class="task {'on' if t['id'] in done_t else ''}"
              onclick="api('/api/task/toggle',{{block:'{bk}',task_id:'{t['id']}'}}).then(rel)">
              <span class="box">{'✓' if t['id'] in done_t else ''}</span>
              <span class="tn">{html.escape(t['name'])}</span></div>'''
            for t in b["tasks"])}
      </div>""" for bk, b in s["routines"].items())

    def rew_html(r):
        can = s["stars"] >= r["cost"]
        oc = ("onclick=\"api('/api/reward/redeem',{reward_id:'" + r["id"]
              + "'}).then(rel)\"") if can else "disabled"
        label = "Redeem" if can else "Locked"
        return (
            f'<div class="rew {"can" if can else ""}">'
            f'<div class="top">'
            f'<span class="e">{r["emoji"]}</span>'
            f'<span class="rn">{html.escape(r["name"])}</span>'
            f'<span class="cost">★ {r["cost"]}</span>'
            f'</div>'
            f'<button {oc}>{label}</button>'
            f'</div>'
        )

    rews = "".join(rew_html(r) for r in s["rewards"])

    body = f"""
<div class="wrap">
  <h1>{kid['emoji']} Hi {html.escape(kid['name'])}!</h1>
  <div class="sub">{datetime.date.today().strftime('%A, %d %B %Y')} &nbsp;·&nbsp;
    Habits {d['habits_done']}/{d['habits_total']} &nbsp;·&nbsp; Tasks {d['tasks_done']}/{d['tasks_total']}</div>

  {banner}

  <div class="grid" style="grid-template-columns:1fr">
    <div class="card"><h2>My Habits — tap when done</h2><div class="habits">{habits}</div></div>
    <div class="card"><h2>My Routine</h2><div class="rblocks">{rblocks}</div></div>
    <div class="card"><h2>Rewards</h2><div class="rews">{rews}</div></div>
  </div>
</div>
<script>
let _i;
document.addEventListener('visibilitychange',()=>{{
  if(!document.hidden) location.reload();
}});
setInterval(()=>location.reload(), 300000); // refresh every 5 min
</script>"""
    return page(f"{kid['name']}'s Dashboard", body)


# ---------------------------------------------------------------- photos page
def photos_page():
    files = list_photos()
    if not files:
        body = """<div class="empty">
          <div style="font-size:64px">🖼️</div><br>
          <b>No photos yet</b><br><br>
          Drop images into:<br>
          <code style="color:var(--blue)">/Volumes/Seagate/Projects/family-hub/photos/</code><br><br>
          JPG · PNG · WEBP · GIF — they'll start cycling automatically.
        </div>"""
        return page("Photos", body)

    slides = "".join(
        f'<div class="slide" style="background-image:url(\'/media/{urllib.parse.quote(f)}\')"></div>'
        for f in files)
    body = f"""
<div class="frame">{slides}</div>
<div class="overlay">
  <div><div class="clk" id="clk">--:--</div><div class="dte" id="dte"></div></div>
  <div style="text-align:right;opacity:.7;font-size:13px">{len(files)} photo{'s' if len(files)!=1 else ''}</div>
</div>
<script>
const S=[...document.querySelectorAll('.slide')];let i=0;
const DUR=9000;
function show(n){{
  S.forEach((s,k)=>s.classList.toggle('show',k===n));
  const cur=S[n];
  cur.style.animation='none'; void cur.offsetWidth; cur.style.animation='';
}}
if(S.length){{show(0);setInterval(()=>{{i=(i+1)%S.length;show(i);}},DUR);}}
function tick(){{
  const d=new Date();
  document.getElementById('clk').textContent=
    String(d.getHours()).padStart(2,'0')+':'+String(d.getMinutes()).padStart(2,'0');
  document.getElementById('dte').textContent=
    d.toLocaleDateString(undefined,{{weekday:'long',day:'numeric',month:'long'}});
}}
tick();setInterval(tick,10000);
</script>"""
    return page("Photos", body)


def list_photos():
    if not os.path.isdir(PHOTO_DIR):
        return []
    out = []
    for n in sorted(os.listdir(PHOTO_DIR)):
        if os.path.splitext(n)[1].lower() in IMAGE_EXT:
            out.append(n)
    return out


# ---------------------------------------------------------------- handler
class H(BaseHTTPRequestHandler):
    server_version = "FamilyHub/1.0"

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="text/html; charset=utf-8", extra=None):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(body)
        except Exception:
            pass

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj), "application/json")

    def do_GET(self):
        p = urllib.parse.urlparse(self.path).path

        if p in ("/", "/kids"):
            return self._send(200, kids_page())

        if p == "/photos":
            return self._send(200, photos_page())

        if p == "/api/state":
            s = load_state()
            return self._json({"state": s, "derived": derived(s),
                               "photos": list_photos()})

        if p == "/api/photos":
            return self._json({"photos": list_photos()})

        if p == "/health":
            return self._json({"ok": True})

        if p.startswith("/media/"):
            name = urllib.parse.unquote(posixpath.basename(p))
            if name not in list_photos():
                return self._send(404, "not found", "text/plain")
            fp = os.path.join(PHOTO_DIR, name)
            ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
            try:
                with open(fp, "rb") as f:
                    return self._send(200, f.read(), ctype,
                                      {"Cache-Control": "public, max-age=3600"})
            except Exception:
                return self._send(500, "read error", "text/plain")

        return self._send(404, "not found", "text/plain")

    def do_POST(self):
        p = urllib.parse.urlparse(self.path).path
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        try:
            data = json.loads(raw or b"{}")
        except Exception:
            data = {}

        with LOCK:
            s = load_state()
            e = day_entry(s)

            if p == "/api/habit/toggle":
                hid = data.get("habit_id")
                if not any(h["id"] == hid for h in s["habits"]):
                    return self._json({"ok": False, "error": "unknown habit"}, 400)
                if hid in e["habits"]:
                    e["habits"].remove(hid)
                else:
                    e["habits"].append(hid)
                save_state(s)

            elif p == "/api/task/toggle":
                tid = data.get("task_id")
                blk = data.get("block")
                if blk not in s["routines"] or not any(
                        t["id"] == tid for t in s["routines"][blk]["tasks"]):
                    return self._json({"ok": False, "error": "unknown task"}, 400)
                if tid in e["tasks"]:
                    e["tasks"].remove(tid)
                else:
                    e["tasks"].append(tid)
                save_state(s)

            elif p == "/api/reward/redeem":
                rid = data.get("reward_id")
                r = next((x for x in s["rewards"] if x["id"] == rid), None)
                if not r:
                    return self._json({"ok": False, "error": "unknown reward"}, 400)
                if s["stars"] < r["cost"]:
                    return self._json({"ok": False, "error": "not enough stars"}, 400)
                s["stars"] -= r["cost"]
                save_state(s)

            elif p == "/api/stars/add":
                # optional: award/deduct stars manually (parent use)
                delta = int(data.get("delta") or 0)
                s["stars"] = max(0, s["stars"] + delta)
                save_state(s)

            elif p == "/api/reset-today":
                s["log"][today()] = {"habits": [], "tasks": []}
                save_state(s)

            elif p == "/api/award-day":
                # convert today's habit stars into the spendable balance
                s["stars"] += habit_stars(s)
                save_state(s)

            else:
                return self._json({"ok": False, "error": "unknown endpoint"}, 404)

            return self._json({"ok": True, "derived": derived(s)})


def main():
    os.makedirs(PHOTO_DIR, exist_ok=True)
    load_state()
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), H)
    print(f"Family Hub on http://0.0.0.0:{PORT}  (photos: {PHOTO_DIR})", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
