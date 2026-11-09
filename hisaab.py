"""Hisaab core: dual-decode amount gate + ledger.
Live: GNANI_API_KEY=... python hisaab.py entry clip.wav
Mock: python hisaab.py entry --mock "ramesh ko dhai hazaar udhaar" "ramesh ko 2500 udhaar"
"""
import argparse, json, os, re, sqlite3, sys, time, unicodedata

API = "https://api.vachana.ai"


def _norm(t):
    t = unicodedata.normalize("NFC", t.lower()).strip(".,!?।|\"'")
    return t.replace("\u093c", "").replace("\u0901", "\u0902")  # drop nukta, chandrabindu -> anusvara


def _lex(d):
    return {_norm(k): v for k, v in d.items()}


# v1 lexicon: extend with the 11-99 forms you actually see in Prisma output.
# Roman "saath" (60) is left out on purpose: it collides with "saath" (with).
_U = {1: "ek एक", 2: "do दो", 3: "teen तीन", 4: "char chaar चार", 5: "paanch panch पांच",
      6: "chhe chhah छह", 7: "saat सात", 8: "aath आठ", 9: "nau नौ", 10: "das दस",
      20: "bees बीस", 30: "tees तीस", 40: "chalis चालीस", 50: "pachas pachaas पचास",
      60: "साठ", 70: "sattar सत्तर", 80: "assi अस्सी", 90: "nabbe नब्बे"}
WORD = _lex({w: n for n, ws in _U.items() for w in ws.split()})
_HI = ("ग्यारह बारह तेरह चौदह पंद्रह सोलह सत्रह अठारह उन्नीस बीस इक्कीस बाईस तेईस चौबीस पच्चीस छब्बीस सत्ताईस अट्ठाईस उनतीस तीस "
       "इकतीस बत्तीस तैंतीस चौंतीस पैंतीस छत्तीस सैंतीस अड़तीस उनतालीस चालीस इकतालीस बयालीस तैंतालीस चौवालीस पैंतालीस छियालीस सैंतालीस अड़तालीस उनचास पचास "
       "इक्यावन बावन तिरपन चौवन पचपन छप्पन सत्तावन अट्ठावन उनसठ साठ इकसठ बासठ तिरसठ चौंसठ पैंसठ छियासठ सड़सठ अड़सठ उनहत्तर सत्तर "
       "इकहत्तर बहत्तर तिहत्तर चौहत्तर पचहत्तर छिहत्तर सतहत्तर अठहत्तर उन्यासी अस्सी इक्यासी बयासी तिरासी चौरासी पचासी छियासी सत्तासी अट्ठासी नवासी नब्बे "
       "इक्यानवे बानवे तिरानवे चौरानवे पचानवे छियानवे सत्तानवे अट्ठानवे निन्यानवे").split()
assert len(_HI) == 89  # 11..99
WORD.update(_lex({w: 11 + i for i, w in enumerate(_HI)}))
WORD.update(_lex({"पच्चास": 50, "छः": 6, "छ:": 6, "अट्ठारह": 18}))  # spellings Prisma v3.0 produced
MULT = _lex({"sau": 100, "सौ": 100, "hazaar": 1e3, "hazar": 1e3, "हज़ार": 1e3, "lakh": 1e5,
             "lac": 1e5, "लाख": 1e5, "crore": 1e7, "karod": 1e7, "करोड़": 1e7})
FRAC = _lex({"dedh": 1.5, "डेढ़": 1.5, "dhai": 2.5, "dhaai": 2.5, "ढाई": 2.5})
SAWA = _lex({w: 1 for w in "sawa sava सवा सावा".split()})  # "सवा सौ" = 125, but "सवा दो सौ" = 225
MOD = _lex({"sadhe": .5, "सादे": .5, "saade": .5, "साढ़े": .5, "paune": -.25, "पौने": -.25})
QTY = _lex({w: 1 for w in "kilo kg gram gm litre liter packet dozen piece pcs किलो ग्राम लीटर पैकेट दर्जन".split()})
JAMA = _lex({w: 1 for w in "jama jaama जमा जामा जम्मा diye diya wapas chukaya chuka paid दिए दिया वापस".split()})
UDHAR = _lex({w: 1 for w in "udhaar udhar udhari उधार उधारी उदार".split()})  # उदार = a spelling Prisma v2.5 produced
KEYTERMS = ["डेढ़", "ढाई", "सवा", "साढ़े", "पौने", "सौ", "हज़ार", "लाख", "उधार", "जमा"]  # v3.0 hints, used by eval --keyterms
_DEV = str.maketrans("०१२३४५६७८९", "0123456789")


def _tokens(text):
    text = re.sub(r"(?<=\d),(?=\d)", "", text.translate(_DEV).replace("₹", " "))
    # ASR may read "साढ़े चार" as a clock time: 04:30 = 4.5, 04:15 = sawa 4, 03:45 = paune 4
    text = re.sub(r"\b0?(\d{1,2}):(15|30|45)\b", lambda m: str(int(m[1]) + int(m[2]) / 60), text)
    return [_norm(t) for t in text.split()]


def _is_num(t):
    return bool(re.fullmatch(r"\d+(\.\d+)?", t)) or any(t in d for d in (WORD, MULT, FRAC, MOD, SAWA))


POW = {100, 1000, 100000, 10000000}


def _parse(run):
    total = cur = mod = 0.0
    prev = False  # last token was a plain number; ASR may write "sau" as a bare 100 after it
    for i, t in enumerate(run):
        nxt = run[i + 1] if i + 1 < len(run) else ""
        if t in SAWA:
            if nxt in WORD or (nxt[:1].isdigit() and int(float(nxt)) not in POW):
                mod, prev = .25, False  # "सवा दो सौ": a quarter more than two hundred
            else:
                cur, prev = cur + 1.25, True  # "सवा सौ": 1.25 hundreds
        elif t in MOD:
            mod, prev = MOD[t], False
        elif t in FRAC:
            cur, prev = cur + FRAC[t], True
        elif t in MULT or (prev and t.isdigit() and int(t) in POW):
            m = MULT.get(t) or int(t)
            if m == 100:
                cur = (cur or 1) * 100
            else:
                total += (cur or 1) * m
                cur = 0
            prev = False
        else:
            x = float(t) if t[0].isdigit() else WORD[t]
            # ASR writes "साढ़े 3,000" / "पौने 200": the fraction applies to the round number's own unit
            x += mod * 10 ** (len(t) - 1) if mod and re.fullmatch(r"[1-9]0{2,}", t) else mod
            cur += x
            mod, prev = 0.0, True
    v = total + cur
    if abs(v - round(v)) > 1e-6:  # a fraction of a rupee means sawa/dhai lost its multiplier: no amount
        return None
    v = round(v)
    return v if v > 0 else None


def amounts(text):
    """All rupee amounts in a transcript; number runs followed by kilo/litre/... are skipped."""
    toks, out, i = _tokens(text), [], 0
    while i < len(toks):
        if not _is_num(toks[i]):
            i += 1
            continue
        j = i
        while j < len(toks) and _is_num(toks[j]):
            j += 1
        if not (j < len(toks) and toks[j] in QTY):
            v = _parse(toks[i:j])
            if v:
                out.append(v)
        i = j
    return out


def _one(xs):
    return xs[0] if len(xs) == 1 else None  # several candidates = ambiguous


def inr(n):
    s = str(int(n))
    head = re.sub(r"(\d)(?=(\d\d)+$)", r"\1,", s[:-3])
    return "₹" + (head + "," + s[-3:] if head else s)


def gate(a, b, big=1000, small=10):
    """a, b = amount from each decode (int or None) -> (action, options)."""
    opts = sorted({x for x in (a, b) if x})
    if not opts:
        return "reask", []
    if len(opts) == 2:
        return "choose", opts  # decodes disagree
    if a != b:
        return "confirm", opts  # only one decode heard an amount
    return ("confirm" if opts[0] >= big or opts[0] < small else "commit"), opts


def prompt(action, opts):
    if action == "choose":
        return f"{inr(opts[0])} ya {inr(opts[1])}? Kitna likhna hai?"
    if action == "confirm":
        return f"{inr(opts[0])}, sahi hai? Haan ya nahi bolo."
    return "Amount samajh nahi aaya. Dobara bolo."


_DV = dict(zip("कखगघचछजझटठडढणतथदधनपफबभमयरलवशषसह",
               "k kh g gh ch ch j jh t th d dh n t th d dh n p f b bh m y r l v sh sh s h".split()))
PARTS = _lex({w: 1 for w in "ko ne se ka ki ke को ने से का की के".split()})


def _skel(name):
    """Script-free name key: 'रमेश' and 'Ramesh' both -> 'rmsh'."""
    s = "".join(_DV.get(ch, ch) for ch in unicodedata.normalize("NFC", name.lower()))
    s = re.sub(r"[aeiou]|[^a-z]", "", s.replace("w", "v"))
    return re.sub(r"(.)\1+", r"\1", s)


def match(name, known):
    k = _skel(name)
    return next((n for n in known if _skel(n) == k), name) if k else name


def parse_entry(text, known=()):
    """v1 heuristic: kind from keywords, name = word before ko/ne/se/ka, matched to known customers."""
    toks = _tokens(text)
    j, u = bool(JAMA.keys() & set(toks)), bool(UDHAR.keys() & set(toks))
    kind = "jama" if j and not u else "udhaar" if u and not j else None  # unknown or conflicting -> ask
    name = next((toks[i - 1] for i in range(1, len(toks))
                 if toks[i] in PARTS and not _is_num(toks[i - 1])), "?")
    return match(name, known), kind


def db(path="hisaab.db"):
    c = sqlite3.connect(path)
    c.execute("create table if not exists e(ts real, name text, kind text, amt int, a text, b text, act text)")
    return c


def add(c, name, kind, amt, a, b, act):
    c.execute("insert into e values (?,?,?,?,?,?,?)", (time.time(), name, kind, amt, a, b, act))
    c.commit()


def balances(c):
    q = "select name, sum(case kind when 'udhaar' then amt else -amt end) from e group by name"
    return dict(c.execute(q))


def _hdr():
    k = os.getenv("GNANI_API_KEY") or sys.exit("set GNANI_API_KEY first")
    return {"X-API-Key-ID": k}


def _why(r):
    """Readable error text; Cloudflare block pages are HTML, so strip tags and surface the code + Ray ID."""
    t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", r.text)).strip()
    if "cloudflare" in r.text.lower():
        m = re.search(r"[Ee]rror (?:code )?:?\s*(\d{4})", t)
        return (f"Cloudflare block (code {m.group(1) if m else '?'}), cf-ray {r.headers.get('cf-ray', '?')}. "
                f"Page text: {t[:600]}")
    return t[:400]


class ApiError(Exception):
    def __init__(self, status, msg):
        super().__init__(f"HTTP {status} {msg}")
        self.status, self.msg = status, msg


def _post(url, **kw):
    """POST with the API key; retry 429/5xx (per the docs), otherwise raise ApiError with the server's message."""
    import requests
    for i in range(3):
        r = requests.post(url, headers=_hdr(), timeout=60, **kw)
        if r.status_code not in (429, 500, 503, 504):
            break
        time.sleep(0.5 * 2 ** i)
    if not r.ok:
        raise ApiError(r.status_code, f"from {url}\n{_why(r)}")
    return r


def _flac(path):
    import io
    import soundfile as sf  # pip install soundfile
    d, sr = sf.read(path)
    b = io.BytesIO()
    sf.write(b, d, sr, format="FLAC")
    return b.getvalue()


def stt(path, model="v3", keyterms=None, fmt="transcribe"):
    """One Prisma decode. If a WAV upload is blocked by Cloudflare (403), retry once as FLAC."""
    data = {"format": fmt if model == "v3" else "transcribe", "language_code": "hi-IN,en-IN" if model == "v3" else "hi-IN"}
    if model == "v3":
        data["model"] = "prisma-v3.0"
        if keyterms:
            data["keyterms"] = json.dumps(keyterms, ensure_ascii=False)  # v3.0 only, up to 200 items
    audio, name = open(path, "rb").read(), os.path.basename(path)
    for attempt in (0, 1):
        try:
            r = _post(f"{API}/stt/v3", data=data, files={"audio_file": (name, audio)})
            break
        except ApiError as e:
            if attempt or e.status != 403 or "Cloudflare" not in e.msg or name.lower().endswith(".flac"):
                raise
            print(f"[{name} blocked; retrying once as FLAC]", file=sys.stderr)
            audio, name = _flac(path), os.path.splitext(name)[0] + ".flac"
    j = r.json()
    return j.get("transcript") or j.get("text") or ""  # check the field name on your first call


def tts(text, out="readback.wav", voice="Poorvi", lang="hi-en", rate=48000):
    body = {"text": text, "voice": voice, "model": "timbre-v2.5", "language": lang, "speed": 1.0,
            "audio_config": {"sample_rate": rate, "num_channels": 1, "sample_width": 2,
                             "encoding": "linear_pcm", "container": "wav"}}
    open(out, "wb").write(_post(f"{API}/api/v1/tts/inference", json=body).content)
    return out


def run(c, a_text, b_text, speak, ask):
    """a_text = Prisma v3.0 transcript, b_text = Prisma v2.5 transcript."""
    a, b = (_one(amounts(t)) for t in (a_text, b_text))
    act, opts = gate(a, b)
    known = [r[0] for r in c.execute("select distinct name from e")]
    name = next((n for n in (parse_entry(t, known)[0] for t in (a_text, b_text)) if n != "?"), "?")
    kinds = {parse_entry(t, known)[1] for t in (a_text, b_text)} - {None}
    kind = kinds.pop() if len(kinds) == 1 else None  # missing or conflicting direction -> ask
    who = f"{name}, {kind}: " if name != "?" and kind else ""
    amt = opts[0] if act == "commit" else None
    if act in ("confirm", "choose"):
        speak(who + prompt(act, opts))
        r = ask("> ").strip().lower()  # typed stand-in for a spoken reply; wire a 3rd Prisma call later
        if act == "choose" and r in ("1", "2"):
            amt = opts[int(r) - 1]
        elif act == "confirm" and r in ("y", "yes", "haan", "han", "हाँ", "हां"):
            amt = opts[0]
    elif act == "reask":
        speak(prompt(act, opts))
    if amt and name == "?":
        speak("Kiska hisaab hai? Naam bolo.")
        name = match(ask("naam> ").strip(), known) or "?"
    if amt and kind is None:
        speak("Udhaar ya jama?")
        kind = {"u": "udhaar", "उ": "udhaar", "j": "jama", "ज": "jama"}.get(ask("udhaar/jama> ").strip().lower()[:1])
    if not (amt and name != "?" and kind):
        return act, name, kind, None
    add(c, name, kind, amt, a_text, b_text, act)
    return act, name, kind, amt


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    s = p.add_subparsers(dest="cmd", required=True)
    e = s.add_parser("entry")
    e.add_argument("wav", nargs="?")
    e.add_argument("--mock", nargs=2, metavar=("V3_TEXT", "V25_TEXT"))
    s.add_parser("balances")
    args = p.parse_args()
    c = db()
    if args.cmd == "balances":
        for n, v in balances(c).items():
            print(f"{n}: {inr(v)}")
        return
    if args.mock:
        a_text, b_text = args.mock
        speak = lambda t: print("SAY:", t)
    else:
        a_text, b_text = stt(args.wav, "v3", fmt="verbatim", keyterms=KEYTERMS), stt(args.wav, "v25")
        speak = lambda t: (print("SAY:", t), tts(t))
    print("v3.0 :", a_text, "\nv2.5 :", b_text)
    print(run(c, a_text, b_text, speak, input))


if __name__ == "__main__":
    try:
        main()
    except ApiError as e:
        sys.exit(str(e))
