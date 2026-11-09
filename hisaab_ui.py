"""Hisaab browser UI.  Run:  py hisaab_ui.py   then open http://localhost:8000  (Chrome or Edge)
Mic -> Prisma v3.0 (words + hints) and v2.5 -> amount gate -> spoken read-back (Timbre) -> ledger.
Typed input works without the API.  Needs the same packages as the eval (requests, soundfile)."""
import argparse, base64, io, json, os, time, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hisaab as H

PENDING = {}


def audio_for(text):
    """Timbre read-back as a data URL; None when there is no API key or the call fails."""
    if not os.getenv("GNANI_API_KEY"):
        return None
    try:
        os.makedirs("tmp", exist_ok=True)
        H.tts(text, "tmp/q.wav", rate=16000)
        return "data:audio/wav;base64," + base64.b64encode(open("tmp/q.wav", "rb").read()).decode()
    except Exception:
        return None


def ledger(c):
    rows = c.execute("select name, kind, amt, ts from e order by ts desc limit 9").fetchall()
    return {"balances": [{"name": n, "amount": H.inr(abs(v)), "owes": v > 0} for n, v in H.balances(c).items() if v],
            "recent": [{"name": n, "kind": k, "amt": H.inr(a), "when": time.strftime("%d %b, %H:%M", time.localtime(t))}
                       for n, k, a, t in rows]}


def verdict(a, b):
    f = H.inr
    if a and b and a == b:
        return f"Both read {f(a)}. They match."
    if a and b:
        return f"They disagree: {f(a)} and {f(b)}."
    if a or b:
        return f"Only {'Prisma 3.0' if a else 'Prisma 2.5'} found an amount ({f(a or b)})."
    return "Neither model found an amount."


def decide(c, a_text, b_text):
    a, b = (H._one(H.amounts(t)) for t in (a_text, b_text))
    act, opts = H.gate(a, b)
    known = [r[0] for r in c.execute("select distinct name from e")]
    name = next((n for n in (H.parse_entry(t, known)[0] for t in (a_text, b_text)) if n != "?"), "?")
    kinds = {H.parse_entry(t, known)[1] for t in (a_text, b_text)} - {None}
    kind = kinds.pop() if len(kinds) == 1 else None  # missing or conflicting direction -> ask
    seen = {"heard": [a_text, b_text], "read": [H.inr(x) if x else "no amount" for x in (a, b)], "verdict": verdict(a, b)}
    if act == "commit" and name != "?" and kind:
        H.add(c, name, kind, opts[0], a_text, b_text, act)
        return {"saved": f"{name}, {kind} of {H.inr(opts[0])}", **seen}
    q = None if act == "commit" else (f"{name}, {kind}: " if name != "?" and kind else "") + H.prompt(act, opts)
    pid = uuid.uuid4().hex[:8]
    PENDING[pid] = dict(a_text=a_text, b_text=b_text, act=act, opts=opts)
    return {"id": pid, "act": act, "options": opts, "fmt": [H.inr(o) for o in opts], "name": "" if name == "?" else name,
            "kind": kind, "question": q, "audio": audio_for(q) if q else None, **seen}


def confirm(c, d):
    p = PENDING.get(d.get("id"))
    name, kind, amt = (d.get("name") or "").strip(), d.get("kind"), d.get("amount")
    if d.get("discard"):
        PENDING.pop(d.get("id"), None)
        return {"discarded": True}
    if not p or p["act"] == "reask" or amt not in p["opts"] or not name or kind not in ("udhaar", "jama"):
        return {"error": "incomplete entry: pick an amount, a name and udhaar or jama"}
    name = H.match(name, [r[0] for r in c.execute("select distinct name from e")])
    H.add(c, name, kind, amt, p["a_text"], p["b_text"], p["act"])
    del PENDING[d["id"]]
    return {"saved": f"{name}, {kind} of {H.inr(amt)}"}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, body, ctype, code=200):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8", code)

    def do_GET(self):
        if self.path == "/api/ledger":
            c = H.db()
            self._json(ledger(c))
            c.close()
        else:
            self._send(PAGE.encode("utf-8"), "text/html; charset=utf-8")

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        c = H.db()
        try:
            if self.path == "/api/entry":  # WAV from the browser; sent on as FLAC, which avoids the WAV block seen earlier
                import soundfile as sf
                data, sr = sf.read(io.BytesIO(body))
                os.makedirs("tmp", exist_ok=True)
                sf.write("tmp/entry.flac", data, sr, format="FLAC")
                out = decide(c, H.stt("tmp/entry.flac", "v3", fmt="verbatim", keyterms=H.KEYTERMS),
                             H.stt("tmp/entry.flac", "v25"))
            elif self.path == "/api/text":
                d = json.loads(body)
                if not (d.get("a") or "").strip():
                    raise ValueError("type the v3.0 text first")
                out = decide(c, d["a"], (d.get("b") or "").strip() or d["a"])
            else:
                out = confirm(c, json.loads(body))
            out["ledger"] = ledger(c)
            self._json(out)
        except (Exception, SystemExit) as e:
            self._json({"error": str(e)}, 502)
        finally:
            c.close()


PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Hisaab</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Kalam:wght@400;700&family=Mukta:wght@400;600;700&display=swap" rel="stylesheet">
<style>
:root{--cloth:#5A1B1F;--deep:#3F1015;--brass:#D2A24A;--paper:#F2F5EE;--rule:#B9C8DA;--ink:#17223B;--red:#B3261E;--mut:#4F5B73;
--hand:"Kalam","Nirmala UI","Noto Sans Devanagari",cursive;--ui:"Mukta","Nirmala UI","Noto Sans Devanagari",system-ui,sans-serif}
*{box-sizing:border-box}
body{margin:0;font:17px/1.5 var(--ui);color:var(--ink);background:var(--paper)}
.shell{min-height:100vh;display:grid;grid-template-columns:minmax(300px,390px) 1fr}
.cover{background:var(--cloth);color:#F8EFE2;padding:32px 28px;box-shadow:inset -8px 0 0 var(--brass)}
.mark{font:700 64px/1 var(--hand);color:var(--brass);margin:0}
.cover p{margin:.4rem 0}.sub{color:#E8D6C0}
.mic{--lvl:0;position:relative;width:136px;height:136px;margin:34px 0 14px;border-radius:50%;border:3px solid var(--brass);background:var(--deep);color:#fff;font:700 19px var(--ui);cursor:pointer}
.mic::after{content:"";position:absolute;inset:-13px;border-radius:50%;border:2px solid var(--brass);opacity:calc(.2 + var(--lvl) * .8);transform:scale(calc(1 + var(--lvl) * .2));pointer-events:none}
.mic.on{background:var(--red);border-color:#fff}
button:focus-visible,input:focus-visible,summary:focus-visible{outline:3px solid var(--brass);outline-offset:3px}
.say{font:400 22px/1.35 var(--hand);color:#fff;margin-top:6px}
details{margin-top:28px;color:#E8D6C0}summary{cursor:pointer}
details input{width:100%;margin-top:8px;padding:10px 12px;border:1px solid #8a4a4f;border-radius:6px;background:var(--deep);color:#fff;font:inherit}
.go{margin-top:8px;padding:10px 14px;border-radius:6px;border:1px solid var(--brass);background:transparent;color:var(--brass);font:600 16px var(--ui);cursor:pointer}
.page{padding:32px clamp(18px,4vw,56px) 48px;max-width:860px}
h2{font:700 20px/1.3 var(--ui);margin:0 0 10px}
#heard,#ask{margin-bottom:26px}
.hr{display:grid;grid-template-columns:96px 1fr auto;gap:12px;align-items:baseline;padding:8px 0;border-bottom:1px solid var(--rule)}
.who{color:var(--mut);font-weight:600}.tx{font:400 21px/1.35 var(--hand)}.rd{font:700 21px var(--hand);white-space:nowrap}
.verdict{margin:10px 0 0;font-weight:600}.red{color:var(--red)}.pre{white-space:pre-wrap}
.q{font:700 24px/1.3 var(--hand);color:var(--red);margin:0 0 12px}
.who2{display:flex;gap:14px;flex-wrap:wrap;align-items:flex-end;margin-bottom:14px}
.who2 label{display:grid;gap:4px;font-weight:600}
.who2 input{padding:10px 12px;border:1px solid var(--ink);border-radius:6px;background:#fff;font:400 20px var(--hand);color:var(--ink);min-width:220px}
.seg{display:flex}.seg button{padding:8px 16px;border:1px solid var(--ink);background:#fff;color:var(--ink);font:600 16px var(--ui);cursor:pointer;text-align:left}
.seg button+button{border-left:0}.seg small{display:block;font-weight:400;color:var(--mut);font-size:13px}
.seg button[aria-pressed=true]{background:var(--ink);color:#fff}.seg button[aria-pressed=true] small{color:#cbd5e6}
.opts{display:flex;gap:12px;flex-wrap:wrap;align-items:center}
.stamp{min-height:52px;padding:10px 22px;border:3px double var(--red);background:transparent;color:var(--red);font:700 24px var(--hand);cursor:pointer}
.stamp:hover{background:var(--red);color:#fff}
.ghost{min-height:44px;padding:8px 14px;border:0;background:transparent;color:var(--mut);font:600 16px var(--ui);text-decoration:underline;cursor:pointer}
.ledger{border-left:3px double var(--red);padding-left:16px}
.row{display:grid;grid-template-columns:1fr 130px 130px;height:38px;border-bottom:1px solid var(--rule);font:400 22px/38px var(--hand)}
.row.head{font:600 15px/38px var(--ui);color:var(--mut)}
.nm small{font:400 13px var(--ui);color:var(--mut);margin-left:10px}
.amt{text-align:right;padding-right:8px;border-left:1px solid var(--rule)}
.new{animation:ink .8s ease-out}@keyframes ink{from{clip-path:inset(0 100% 0 0)}to{clip-path:inset(0)}}
.empty{margin:14px 0;color:var(--mut)}
.bal{margin-top:22px}.bl{display:flex;justify-content:space-between;max-width:360px;font:400 22px/36px var(--hand)}.bl.red{color:var(--red)}
@media(max-width:860px){.shell{grid-template-columns:1fr}.cover{box-shadow:inset 0 -8px 0 var(--brass)}.row{grid-template-columns:1fr 96px 96px}}
@media(prefers-reduced-motion:reduce){.new{animation:none}.mic::after{transform:none}}
</style></head><body><div class="shell">
<aside class="cover"><h1 class="mark">हिसाब</h1>
<p class="sub">Hisaab. Say the entry. Two models listen and check every rupee.</p>
<button class="mic" id="mic" aria-describedby="st">Speak</button>
<p id="st" aria-live="polite">Tap Speak, then say the entry.</p>
<p class="say">“ramesh ko dhai hazaar udhaar likho”</p>
<details><summary>No mic? Type what the models heard</summary>
<input id="ta" aria-label="Prisma 3.0 text" placeholder="Prisma 3.0: रमेश को ढाई हज़ार उधार">
<input id="tb" aria-label="Prisma 2.5 text" placeholder="Prisma 2.5 (optional)">
<button class="go" id="go">Use this text</button></details></aside>
<main class="page"><section id="heard" hidden></section><section id="ask" hidden></section>
<section class="ledger" aria-label="Ledger"><div class="row head"><span>Name</span><span class="amt">Udhaar (given)</span><span class="amt">Jama (paid)</span></div>
<div id="rows"></div><div class="bal" id="bal"></div></section></main></div>
<script>
const $ = id => document.getElementById(id);
const esc = s => String(s).replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
const post = (u, o) => fetch(u, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(o)}).then(r => r.json());
let rec = null, cur = null, fresh = false;
function ledger(l) {
  $("rows").innerHTML = l.recent.map((x, i) => `<div class="row${fresh && i === 0 ? " new" : ""}"><span class="nm">${esc(x.name)}<small>${esc(x.when)}</small></span><span class="amt">${x.kind === "udhaar" ? esc(x.amt) : ""}</span><span class="amt">${x.kind === "jama" ? esc(x.amt) : ""}</span></div>`).join("")
    || `<p class="empty">Nothing written yet. Tap Speak and say an entry, like “ramesh ko dhai hazaar udhaar likho”.</p>`;
  $("bal").innerHTML = l.balances.map(b => `<div class="bl${b.owes ? " red" : ""}"><span>${esc(b.name)}</span><span>${b.owes ? "baaki " : "advance "}${esc(b.amount)}</span></div>`).join("");
  fresh = false;
}
function setKind(k) { cur.kind = k; document.querySelectorAll("[data-k]").forEach(b => b.setAttribute("aria-pressed", b.dataset.k === k)); }
function show(o) {
  if (o.ledger) { fresh = !!o.saved; ledger(o.ledger); }
  const h = $("heard"), a = $("ask");
  h.hidden = false; a.hidden = true;
  if (o.error) { h.innerHTML = `<h2>That did not work</h2><p class="red pre">${esc(o.error)}</p>`; return; }
  if (o.discarded) { h.innerHTML = `<h2>Discarded</h2><p>Nothing was written.</p>`; return; }
  const rd = o.read || [], rows = o.heard ? [["Prisma 3.0", 0], ["Prisma 2.5", 1]].map(([w, i]) => `<div class="hr"><span class="who">${w}</span><span class="tx">${esc(o.heard[i])}</span><span class="rd">${esc(rd[i])}</span></div>`).join("") : "";
  h.innerHTML = `<h2>${o.heard ? "What the two models heard" : "Saved"}</h2>${rows}` +
    (o.verdict ? `<p class="verdict${o.act && o.act !== "commit" ? " red" : ""}">${esc(o.verdict)}</p>` : "") +
    (o.saved ? `<p class="verdict">Written in the ledger: ${esc(o.saved)}</p>` : "");
  if (o.saved) return;
  cur = o; a.hidden = false;
  if (o.act === "reask") { a.innerHTML = `<p class="q">${esc(o.question)}</p>`; return; }
  const amt = o.act === "choose" ? o.options.map((v, i) => `<button class="stamp" data-a="${v}">${esc(o.fmt[i])}</button>`).join("")
    : `<button class="stamp" data-a="${o.options[0]}">${o.act === "confirm" ? "Yes, " : "Save "}${esc(o.fmt[0])}</button>`;
  a.innerHTML = `${o.question ? `<p class="q">${esc(o.question)}</p>` : ""}
    <div class="who2"><label>Customer<input id="nm" value="${esc(o.name)}" autocomplete="off"></label>
    <div class="seg" role="group" aria-label="Entry type"><button data-k="udhaar">Udhaar<small>gave on credit</small></button><button data-k="jama">Jama<small>customer paid</small></button></div></div>
    <div class="opts">${amt}<button class="ghost" id="no">Discard</button></div>`;
  setKind(o.kind);
  if (o.audio) new Audio(o.audio).play().catch(() => {});
}
$("ask").onclick = async e => {
  const b = e.target.closest("button");
  if (!b) return;
  if (b.dataset.k) setKind(b.dataset.k);
  else if (b.id === "no") show(await post("/api/confirm", {id: cur.id, discard: true}));
  else if (b.dataset.a) {
    const name = $("nm").value.trim();
    if (!name || !cur.kind) { $("st").textContent = "Add the customer's name and choose udhaar or jama first."; $("nm").focus(); return; }
    show(await post("/api/confirm", {id: cur.id, amount: Number(b.dataset.a), name, kind: cur.kind}));
  }
};
$("go").onclick = async () => show(await post("/api/text", {a: $("ta").value, b: $("tb").value}));
function down(buf, from, to) {
  if (from === to) return buf;
  const r = from / to, n = Math.floor(buf.length / r), out = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    const s = Math.floor(i * r), e = Math.min(buf.length, Math.floor((i + 1) * r));
    let t = 0; for (let j = s; j < e; j++) t += buf[j];
    out[i] = t / Math.max(1, e - s);
  }
  return out;
}
function wav(f, sr) {
  const buf = new ArrayBuffer(44 + f.length * 2), v = new DataView(buf);
  const w = (o, s) => [...s].forEach((c, i) => v.setUint8(o + i, c.charCodeAt(0)));
  w(0, "RIFF"); v.setUint32(4, 36 + f.length * 2, true); w(8, "WAVEfmt "); v.setUint32(16, 16, true);
  v.setUint16(20, 1, true); v.setUint16(22, 1, true); v.setUint32(24, sr, true); v.setUint32(28, sr * 2, true);
  v.setUint16(32, 2, true); v.setUint16(34, 16, true); w(36, "data"); v.setUint32(40, f.length * 2, true);
  for (let i = 0; i < f.length; i++) v.setInt16(44 + i * 2, Math.max(-1, Math.min(1, f[i])) * 0x7fff, true);
  return new Blob([buf], {type: "audio/wav"});
}
async function stopRec() {
  const {ctx, stream, proc, chunks} = rec;
  rec = null;
  proc.disconnect(); stream.getTracks().forEach(t => t.stop());
  const all = new Float32Array(chunks.reduce((s, c) => s + c.length, 0));
  let o = 0; for (const c of chunks) { all.set(c, o); o += c.length; }
  const sr = ctx.sampleRate; ctx.close();
  $("mic").textContent = "Speak"; $("mic").classList.remove("on"); $("mic").style.setProperty("--lvl", 0);
  $("st").textContent = "Checking with both models…";
  show(await fetch("/api/entry", {method: "POST", body: wav(down(all, sr, 16000), 16000)}).then(r => r.json()));
  $("st").textContent = "Tap Speak for the next entry.";
}
$("mic").onclick = async () => {
  if (rec) return stopRec();
  try {
    const stream = await navigator.mediaDevices.getUserMedia({audio: {channelCount: 1}});
    const ctx = new AudioContext(), src = ctx.createMediaStreamSource(stream), proc = ctx.createScriptProcessor(4096, 1, 1), an = ctx.createAnalyser(), chunks = [];
    an.fftSize = 512; src.connect(an);
    proc.onaudioprocess = e => chunks.push(new Float32Array(e.inputBuffer.getChannelData(0)));
    src.connect(proc); proc.connect(ctx.destination);
    rec = {ctx, stream, proc, chunks};
    const buf = new Uint8Array(an.fftSize);
    const tick = () => {
      if (!rec) return;
      an.getByteTimeDomainData(buf);
      let s = 0; for (const v of buf) { const d = (v - 128) / 128; s += d * d; }
      $("mic").style.setProperty("--lvl", Math.min(1, Math.sqrt(s / buf.length) * 4));
      requestAnimationFrame(tick);
    };
    tick();
    $("mic").textContent = "Stop"; $("mic").classList.add("on"); $("st").textContent = "Listening. Tap Stop when you finish.";
  } catch (e) { $("st").textContent = "The mic is not available: " + e.message; }
};
fetch("/api/ledger").then(r => r.json()).then(ledger);
</script></body></html>"""

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=8000)
    a = ap.parse_args()
    print(f"Hisaab UI on http://localhost:{a.port}  (API key {'set' if os.getenv('GNANI_API_KEY') else 'NOT set: typed input only'})")
    ThreadingHTTPServer(("127.0.0.1", a.port), Handler).serve_forever()
