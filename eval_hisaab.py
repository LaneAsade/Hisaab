"""Hisaab eval: Timbre speakers -> telephone/noise degradation -> both Prisma decodes -> gate stats.
Small run first:  py eval_hisaab.py run --limit 15      then:  py eval_hisaab.py run      then:  py eval_hisaab.py report
Needs: pip install numpy scipy soundfile. Calls go one at a time, results are saved as it goes, rerun to resume.
"""
import argparse, csv, hashlib, math, os, time
import numpy as np
import soundfile as sf
from scipy.signal import butter, resample_poly, sosfilt
import hisaab as H

SAY = [(2500, "dhai hazaar"), (150, "dedh sau"), (125, "sawa sau"), (175, "paune do sau"),
       (3500, "sadhe teen hazaar"), (5000, "paanch hazaar"), (50000, "pachas hazaar"), (500, "paanch sau"),
       (50, "pachas"), (200, "do sau"), (20000, "bees hazaar"), (2000, "do hazaar"), (250000, "dhai lakh"),
       (100000, "ek lakh"), (700, "saat sau"), (30000, "tees hazaar")]
NAMES, KINDS = ["ramesh", "suresh", "geeta"], ["udhaar", "jama"]
CONDS = ["clean", "tel", "tel+20", "tel+10", "tel+5"]  # tel = 8 kHz, 300-3400 Hz; +N = noise at N dB SNR
FIELDS = ["uid", "cond", "truth", "text", "a_text", "b_text", "a", "b", "act"]


def _rms(x):
    return float(np.sqrt(np.mean(x ** 2)) + 1e-12)


def pink(n, rng):
    f = np.fft.rfft(rng.standard_normal(n))
    f /= np.sqrt(np.maximum(np.arange(len(f)), 1))
    return np.fft.irfft(f, n)


def add_noise(x, noise, snr_db, rng):
    n = np.resize(np.roll(noise, int(rng.integers(len(noise)))), len(x))
    return x + n * (_rms(x) / _rms(n)) / 10 ** (snr_db / 20)  # SNR over the whole clip, silence included


def tel(x, sr):
    y = sosfilt(butter(4, [300, 3400], "bandpass", fs=sr, output="sos"), x)
    return resample_poly(y, 8000, sr), 8000


def degrade(x, sr, cond, noise, rng):
    if cond.startswith("tel+"):
        x = add_noise(x, noise, float(cond[4:]), rng)
    if cond != "clean":
        x, sr = tel(x, sr)
    return x * (0.9 / max(float(np.abs(x).max()), 1e-9)), sr


def load(path, rate=16000):
    x, sr = sf.read(path)
    x = x if x.ndim == 1 else x.mean(axis=1)
    return (resample_poly(x, rate, sr) if sr != rate else x), rate


def run(a):
    rng = np.random.default_rng(7)
    noise = load(a.noise)[0] if a.noise else pink(160000, rng)
    voices = [v.split(":") for v in a.voices.split(",")]
    done = set()
    if os.path.exists(a.out):
        done = {(r["uid"], r["cond"]) for r in csv.DictReader(open(a.out, encoding="utf-8-sig"))}
    new = not os.path.exists(a.out) or os.path.getsize(a.out) == 0
    os.makedirs("cache", exist_ok=True)
    os.makedirs("clips", exist_ok=True)
    items = [(amt, w, rep) for rep in range(a.reps) for amt, w in SAY]
    rows = 0
    with open(a.out, "a", newline="", encoding="utf-8-sig") as f:
        wr = csv.DictWriter(f, FIELDS)
        if new:
            wr.writeheader()
        try:
            for k, (amt, words, rep) in enumerate(items):
                voice, lang = voices[k % len(voices)]
                name, kind = NAMES[(k + rep) % 3], KINDS[(k // 2 + rep) % 2]
                text, uid = f"{name} ko {words} {kind} likho", f"{amt}-{rep}-{voice}"
                todo = [c for c in CONDS if (uid, c) not in done]
                if not todo:
                    continue
                wav = os.path.join("cache", hashlib.md5(f"{voice}|{lang}|{text}".encode()).hexdigest() + ".wav")
                if not os.path.exists(wav):
                    H.tts(text, wav, voice, lang, rate=16000)
                    time.sleep(a.pause)
                x, sr = load(wav)
                for c in todo:
                    y, ysr = degrade(x, sr, c, noise, rng)
                    p = os.path.join("clips", f"{uid}_{c}.flac")
                    sf.write(p, y, ysr, format="FLAC")
                    ta = H.stt(p, "v3", keyterms=H.KEYTERMS if a.keyterms else None, fmt=a.v3_format)
                    time.sleep(a.pause)
                    tb = H.stt(p, "v25")
                    time.sleep(a.pause)
                    pa, pb = (H._one(H.amounts(t)) for t in (ta, tb))
                    wr.writerow(dict(uid=uid, cond=c, truth=amt, text=text, a_text=ta, b_text=tb,
                                     a=pa, b=pb, act=H.gate(pa, pb)[0]))
                    f.flush()
                    rows += 1
                    if rows >= a.limit:
                        print(f"stopped after --limit {a.limit} rows")
                        return
        except H.ApiError as e:
            print("Stopped, progress is saved; rerun to resume:", e)
            return
    print(f"done, {rows} new rows")


def _find(folder, stem):
    for ext in (".wav", ".m4a", ".flac", ".mp3", ".ogg", ".aac"):
        path = os.path.join(folder, stem + ext)
        if os.path.exists(path):
            return path


def clips(a):
    """Score human recordings: a folder of clips plus truth.csv (file,truth). Clips go to the API as they are."""
    truth = list(csv.DictReader(open(a.truth or os.path.join(a.folder, "truth.csv"), encoding="utf-8-sig")))
    done = set()
    if os.path.exists(a.out):
        done = {r["uid"] for r in csv.DictReader(open(a.out, encoding="utf-8-sig"))}
    new = not os.path.exists(a.out) or os.path.getsize(a.out) == 0
    with open(a.out, "a", newline="", encoding="utf-8-sig") as f:
        wr = csv.DictWriter(f, FIELDS)
        if new:
            wr.writeheader()
        try:
            for r in truth:
                path = _find(a.folder, r["file"])
                if r["file"] in done or not path:
                    if not path:
                        print("missing:", r["file"])
                    continue
                ta = H.stt(path, "v3", keyterms=H.KEYTERMS if a.keyterms else None, fmt=a.v3_format)
                time.sleep(a.pause)
                tb = H.stt(path, "v25")
                time.sleep(a.pause)
                pa, pb = (H._one(H.amounts(t)) for t in (ta, tb))
                wr.writerow(dict(uid=r["file"], cond="human", truth=r["truth"], text=r.get("say", ""),
                                 a_text=ta, b_text=tb, a=pa, b=pb, act=H.gate(pa, pb)[0]))
                f.flush()
        except H.ApiError as e:
            print("Stopped, progress is saved; rerun to resume:", e)


def wilson(k, n, z=1.96):
    p, d = k / n, 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return 100 * (c - h), 100 * (c + h)


def fmt(k, n, ci=True):
    if not n:
        return "-"
    if not ci:
        return f"{100 * k / n:.0f}%"
    lo, hi = wilson(k, n)
    return f"{100 * k / n:.0f}% ({lo:.0f}-{hi:.0f})"


def report(a):
    rows = list(csv.DictReader(open(a.out, encoding="utf-8-sig")))
    for x in rows:  # re-parse the saved transcripts, so parser fixes need no new API calls
        pa, pb = (H._one(H.amounts(x[k])) for k in ("a_text", "b_text"))
        x["a"], x["b"], x["act"] = pa or "", pb or "", H.gate(pa, pb)[0]
    val = lambda x, k: int(x[k]) if x[k] else None
    t = lambda x: int(x["truth"])
    print("| condition | n | v3.0 right | v2.5 right | prompted | silent wrong | v3.0 errors caught |")
    print("|---|---|---|---|---|---|---|")
    for c in [c for c in CONDS + ["human"] if any(x["cond"] == c for x in rows)] + ["all"]:
        r = [x for x in rows if c == "all" or x["cond"] == c]
        f = lambda k, n: fmt(k, n, c != "all")  # pooled row shares utterances across rows, so no interval
        wrong3 = [x for x in r if val(x, "a") != t(x)]
        prompted = sum(x["act"] != "commit" for x in r)
        silent = sum(x["act"] == "commit" and val(x, "a") != t(x) for x in r)
        caught = sum(x["act"] != "commit" for x in wrong3)
        print(f"| {c} | {len(r)} | {f(len(r) - len(wrong3), len(r))} | "
              f"{f(sum(val(x, 'b') == t(x) for x in r), len(r))} | {f(prompted, len(r))} | "
              f"{f(silent, len(r))} | {f(caught, len(wrong3))} |")
    print("\n| amount band | n | v3.0 right | v2.5 right | prompted | prompts that caught a v3.0 error | silent wrong |")
    print("|---|---|---|---|---|---|---|")
    for lab, ok in (("under Rs 1,000", lambda x: t(x) < 1000), ("Rs 1,000 and over", lambda x: t(x) >= 1000)):
        r = [x for x in rows if ok(x)]
        f = lambda k: fmt(k, len(r), False)
        print(f"| {lab} | {len(r)} | {f(sum(val(x, 'a') == t(x) for x in r))} | {f(sum(val(x, 'b') == t(x) for x in r))} | "
              f"{f(sum(x['act'] != 'commit' for x in r))} | "
              f"{sum(x['act'] != 'commit' and val(x, 'a') != t(x) for x in r)} of {sum(x['act'] != 'commit' for x in r)} | "
              f"{f(sum(x['act'] == 'commit' and val(x, 'a') != t(x) for x in r))} |")
    if a.show:
        print("\nRows where either decode was wrong:")
        for x in rows:
            if val(x, "a") != t(x) or val(x, "b") != t(x):
                print(f"{x['uid']} {x['cond']}: truth={x['truth']} v3.0={x['a_text']!r}->{x['a'] or '-'} "
                      f"v2.5={x['b_text']!r}->{x['b'] or '-'} [{x['act']}]")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    s = p.add_subparsers(dest="cmd", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--pause", type=float, default=0.7)
    common.add_argument("--v3-format", default="transcribe", choices=["transcribe", "verbatim", "codemix"],
                        help="output style requested from v3.0 (verbatim/codemix write numbers as words)")
    common.add_argument("--keyterms", action="store_true", help="send hint words with the v3.0 call (use with --out)")
    common.add_argument("--out", default="eval_rows.csv")
    r = s.add_parser("run", parents=[common])
    r.add_argument("--reps", type=int, default=2)
    r.add_argument("--limit", type=int, default=10 ** 9, help="stop after this many rows (try 15 first)")
    r.add_argument("--voices", default="Poorvi:hi-en", help="Voice:lang pairs, comma separated")
    r.add_argument("--noise", help="wav of real ambient noise (shop/street); default is synthetic pink noise")
    c = s.add_parser("clips", parents=[common], help="score human recordings listed in truth.csv (file,truth)")
    c.add_argument("folder")
    c.add_argument("--truth", help="default: <folder>/truth.csv")
    s.add_parser("report", parents=[common]).add_argument("--show", action="store_true", help="list rows where a decode was wrong")
    a = p.parse_args()
    {"run": run, "clips": clips, "report": report}[a.cmd](a)


if __name__ == "__main__":
    main()
