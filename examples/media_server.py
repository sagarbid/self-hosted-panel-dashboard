#!/usr/bin/env python3
"""
Media Server — streams local video/audio to the panel's WebView.

Stdlib only. HTTP Range support so seeking works.

  GET /                -> library page (or ?play=<relpath> to open the player)
  GET /api/list        -> JSON listing of the media library
  GET /stream?f=<rel>  -> the media bytes, with Range / seeking support

Environment:
  MEDIA_PORT  (default 8083)
  MEDIA_DIR   (default "<script dir>/media")
"""

import html
import json
import mimetypes
import os
import re
import socket
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE = os.path.dirname(os.path.abspath(__file__))
MEDIA_DIR = os.environ.get("MEDIA_DIR", os.path.join(BASE, "media"))
PORT = int(os.environ.get("MEDIA_PORT", "8083"))

VIDEO_EXT = {".mp4", ".m4v", ".mkv", ".webm", ".avi", ".mov", ".mpg", ".mpeg", ".ts", ".m2ts"}
AUDIO_EXT = {".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wav"}
PLAYABLE = VIDEO_EXT | AUDIO_EXT
CHUNK = 512 * 1024


def safe_join(rel):
    """Resolve rel inside MEDIA_DIR, refusing traversal."""
    rel = urllib.parse.unquote(rel).lstrip("/")
    full = os.path.realpath(os.path.join(MEDIA_DIR, rel))
    root = os.path.realpath(MEDIA_DIR)
    if full != root and not full.startswith(root + os.sep):
        return None
    return full


def scan():
    """Walk MEDIA_DIR and return a flat list of playable files."""
    out = []
    if not os.path.isdir(MEDIA_DIR):
        return out
    for dirpath, dirnames, filenames in os.walk(MEDIA_DIR):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for fn in sorted(filenames):
            if fn.startswith("."):
                continue
            ext = os.path.splitext(fn)[1].lower()
            if ext not in PLAYABLE:
                continue
            full = os.path.join(dirpath, fn)
            try:
                size = os.path.getsize(full)
            except OSError:
                continue
            rel = os.path.relpath(full, MEDIA_DIR)
            out.append({
                "rel": rel,
                "name": os.path.splitext(fn)[0],
                "folder": os.path.dirname(rel) or ".",
                "ext": ext.lstrip("."),
                "size": size,
                "size_h": human(size),
                "kind": "video" if ext in VIDEO_EXT else "audio",
            })
    out.sort(key=lambda x: (x["folder"], x["name"].lower()))
    return out


def human(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024.0


CSS = """
*{margin:0;padding:0;box-sizing:border-box}
:root{
  --bg:#1e1e2e; --mantle:#181825; --crust:#11111b;
  --surface:#313244; --overlay:#45475a;
  --text:#cdd6f4; --subtext:#a6adc8; --hl:#b4befe;
  --blue:#89b4fa; --mauve:#cba6f7; --green:#a6e3a1; --peach:#fab387;
}
body{background:var(--bg);color:var(--text);
  font-family:-apple-system,'Segoe UI',system-ui,sans-serif;
  min-height:100vh;-webkit-user-select:none;user-select:none}
a{color:inherit;text-decoration:none}
.wrap{max-width:1400px;margin:0 auto;padding:26px 30px 60px}
h1{font-size:1.5rem;letter-spacing:.02em;display:flex;align-items:center;gap:12px}
h1 .dot{width:10px;height:10px;border-radius:50%;background:var(--green);
  box-shadow:0 0 14px var(--green);animation:p 2s infinite}
@keyframes p{0%,100%{opacity:1}50%{opacity:.35}}
.sub{color:var(--subtext);font-size:.85rem;margin-top:6px}
h2{font-size:.78rem;text-transform:uppercase;letter-spacing:.12em;
  color:var(--subtext);margin:30px 0 12px;padding-bottom:7px;
  border-bottom:1px solid var(--surface)}
.grid{display:grid;gap:12px;grid-template-columns:repeat(auto-fill,minmax(250px,1fr))}
.card{background:var(--mantle);border:1px solid var(--surface);border-radius:14px;
  padding:16px 18px;display:flex;gap:14px;align-items:center;
  transition:.14s;cursor:pointer}
.card:active{transform:scale(.985);background:var(--surface)}
.ico{width:42px;height:42px;flex:0 0 42px;border-radius:11px;
  display:grid;place-items:center;font-size:1.25rem;background:var(--surface)}
.card.vid .ico{background:rgba(203,166,247,.16)}
.card.aud .ico{background:rgba(137,180,250,.16)}
.meta{min-width:0;flex:1}
.nm{font-weight:600;font-size:.95rem;overflow:hidden;
  text-overflow:ellipsis;white-space:nowrap}
.fo{color:var(--subtext);font-size:.76rem;margin-top:3px;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.tag{font-size:.66rem;text-transform:uppercase;letter-spacing:.08em;
  padding:3px 8px;border-radius:6px;background:var(--surface);color:var(--subtext)}
.empty{background:var(--mantle);border:1px dashed var(--overlay);
  border-radius:16px;padding:44px 30px;text-align:center}
.empty .big{font-size:2.4rem;margin-bottom:14px}
.empty code{background:var(--crust);padding:3px 8px;border-radius:6px;
  color:var(--peach);font-size:.84rem}
.back{display:inline-flex;align-items:center;gap:8px;margin-bottom:20px;
  background:var(--surface);border-radius:10px;padding:9px 16px;font-size:.86rem}
/* player */
.player{background:#000;border-radius:14px;overflow:hidden;
  border:1px solid var(--surface)}
video,audio{width:100%;display:block;background:#000}
audio{padding:26px;background:var(--mantle)}
.ptitle{font-size:1.05rem;font-weight:600;margin:16px 0 4px}
.tip{color:var(--subtext);font-size:.8rem;margin-top:12px;line-height:1.6}
.tip code{background:var(--crust);padding:2px 7px;border-radius:5px;color:var(--peach)}
"""


def page():
    return f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="utf-8"><title>Media</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>{CSS}</style></head><body>
<div class="wrap">
  <h1><span class="dot"></span>Media Library</h1>
  <div class="sub" id="sub">loading…</div>
  <div id="body"><div class="empty"><div class="big">⏳</div>Scanning…</div></div>
</div>
<script>
function fmt(n){{const u=['B','KB','MB','GB','TB'];let i=0;
  while(n>=1024&&i<u.length-1){{n/=1024;i++}}
  return (i<2?n.toFixed(0):n.toFixed(1))+' '+u[i]}}

async function load(){{
  const r=await fetch('/api/list');const d=await r.json();
  document.getElementById('sub').textContent =
    d.files.length+' item'+(d.files.length===1?'':'s')+' · '+
    (d.total_h||'0 B')+' in '+d.dir;
  const b=document.getElementById('body');
  if(!d.files.length){{
    b.innerHTML='<div class="empty"><div class="big">🎬</div>'+
      '<div>No media yet.</div>'+
      '<div style="margin-top:14px;color:var(--subtext);font-size:.88rem">'+
      'Drop video or audio files into<br><code>'+d.dir+'</code>'+
      '<br><br>Then reload this page.</div></div>';
    return;
  }}
  const byFolder={{}};
  for(const f of d.files){{(byFolder[f.folder]=byFolder[f.folder]||[]).push(f)}}
  let h='';
  for(const fol of Object.keys(byFolder).sort()){{
    h+='<h2>'+fol+'</h2><div class="grid">';
    for(const f of byFolder[fol]){{
      const ico=f.kind==='video'?'🎬':'🎵';
      h+='<div class="card '+(f.kind==='video'?'vid':'aud')+'" '+
         'onclick="location.href=\\'/?play=\\'+encodeURIComponent(f.rel)">'+
         '<div class="ico">'+ico+'</div><div class="meta">'+
         '<div class="nm">'+f.name+'</div>'+
         '<div class="fo">'+f.folder+' · '+f.size_h+'</div></div>'+
         '<div class="tag">'+f.ext+'</div></div>';
    }}
    h+='</div>';
  }}
  b.innerHTML=h;
}}

const q=new URLSearchParams(location.search);
if(q.get('play')){{
  const f=q.get('play');
  const src='/stream?f='+encodeURIComponent(f);
  const isVid=/[.](mp4|m4v|mkv|webm|avi|mov|mpg|mpeg|ts|m2ts)$/i.test(f);
  document.querySelector('.wrap').innerHTML=
    '<a class="back" href="/">← Library</a>'+
    '<div class="ptitle">'+decodeURIComponent(f).split('/').pop()+'</div>'+
    '<div class="player">'+
    (isVid
      ? '<video src="'+src+'" controls autoplay playsinline></video>'
      : '<audio src="'+src+'" controls autoplay></audio>')+
    '</div>'+
    '<div class="tip">If this format does not play, the panel lacks a decoder for it. '+
    'H.264/AAC in <code>.mp4</code> is guaranteed to work (hardware decode).</div>';
}} else {{
  load();
  setInterval(load, 30000);
}}
</script></body></html>"""


class H(BaseHTTPRequestHandler):
    server_version = "MediaServer"

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json", extra=None):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        p = u.path
        qs = urllib.parse.parse_qs(u.query)

        if p == "/api/list":
            files = scan()
            total = sum(f["size"] for f in files)
            return self._send(200, json.dumps({
                "dir": MEDIA_DIR, "count": len(files),
                "total_h": human(total) if files else "0 B",
                "files": files}), "application/json")

        if p == "/":
            return self._send(200, page(), "text/html; charset=utf-8")

        if p == "/stream":
            return self._stream(qs.get("f", [""])[0])

        return self._send(404, json.dumps({"error": "not found"}))

    def _stream(self, rel):
        if not rel:
            return self._send(400, json.dumps({"error": "missing f"}))
        full = safe_join(rel)
        if not full or not os.path.isfile(full):
            return self._send(404, json.dumps({"error": "not found"}))

        size = os.path.getsize(full)
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        rng = self.headers.get("Range")

        if rng:
            m = re.match(r"bytes=(\d*)-(\d*)", rng)
            if m:
                s = int(m.group(1)) if m.group(1) else 0
                e = int(m.group(2)) if m.group(2) else size - 1
                e = min(e, size - 1)
                if s > e:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.end_headers()
                    return
                length = e - s + 1
                self.send_response(206)
                self.send_header("Content-Type", ctype)
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Range", f"bytes {s}-{e}/{size}")
                self.send_header("Content-Length", str(length))
                self.end_headers()
                left = length
                with open(full, "rb") as fh:
                    fh.seek(s)
                    while left > 0:
                        buf = fh.read(min(CHUNK, left))
                        if not buf:
                            break
                        try:
                            self.wfile.write(buf)
                        except (BrokenPipeError, ConnectionResetError):
                            return
                        left -= len(buf)
                return

        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(size))
        self.end_headers()
        try:
            with open(full, "rb") as fh:
                while True:
                    buf = fh.read(CHUNK)
                    if not buf:
                        break
                    self.wfile.write(buf)
        except (BrokenPipeError, ConnectionResetError):
            return


def main():
    if not os.path.isdir(MEDIA_DIR):
        os.makedirs(MEDIA_DIR, exist_ok=True)
    n = len(scan())
    print(f"Media Server on http://0.0.0.0:{PORT}  ({n} item(s))")
    print(f"  media dir: {MEDIA_DIR}")
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), H)
    srv.daemon_threads = True
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
