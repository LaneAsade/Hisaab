import numpy as np
from eval_hisaab import add_noise, pink, tel, wilson

rng = np.random.default_rng(1)
x = np.sin(2 * np.pi * 440 * np.arange(32000) / 16000)
for snr in (20, 10, 5):  # achieved SNR must match the target
    y = add_noise(x, pink(16000, rng), snr, rng)
    got = 20 * np.log10(np.sqrt(np.mean(x ** 2)) / np.sqrt(np.mean((y - x) ** 2)))
    assert abs(got - snr) < 0.1, (snr, got)
t, sr = tel(np.sin(2 * np.pi * 7000 * np.arange(32000) / 16000), 16000)  # 7 kHz is outside the phone band
assert sr == 8000 and len(t) == 16000 and np.sqrt(np.mean(t ** 2)) < 0.05
lo, hi = wilson(8, 10)
assert 49 < lo < 50 and 94 < hi < 95
import argparse, csv, os, tempfile
import eval_hisaab as E  # human clips: files are found by stem, missing ones skipped, rows land as cond=human
d = tempfile.mkdtemp()
open(os.path.join(d, "h01.wav"), "wb").write(b"x")
open(os.path.join(d, "truth.csv"), "w", encoding="utf-8").write("file,truth,say\nh01,150,dedh sau\nh02,200,do sau\n")
E.H.stt = lambda path, model="v3", **kw: "रमेश को डेढ़ 100 जमा"
E.clips(argparse.Namespace(folder=d, truth=None, out=os.path.join(d, "o.csv"), pause=0, keyterms=False, v3_format="verbatim"))
rows = list(csv.DictReader(open(os.path.join(d, "o.csv"), encoding="utf-8-sig")))
assert len(rows) == 1 and rows[0]["a"] == "150" and rows[0]["cond"] == "human"
print("eval tests passed")
