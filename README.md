# Hisaab: a voice ledger for kirana shops that double-checks every rupee

Built for the Great Indian AI Internship Challenge 2026 with Gnani AI's Prisma (speech to text) and Timbre (text to speech). One-page pitch: [PITCH.pdf](PITCH.pdf).

A shopkeeper says an entry in Hindi or Hinglish ("ramesh ko dhai hazaar udhaar likho"). Hisaab sends the same audio to Prisma v3.0 (number words plus hint words) and Prisma v2.5 (digits), reads an amount from each and compares them. A small amount both models agree on is saved. Any disagreement, a missing amount, an amount under Rs 10 or an amount of Rs 1,000 or more is read back by Timbre and needs a tap to confirm.

## Run it

```
pip install -r requirements.txt
$env:GNANI_API_KEY="your-key"          # PowerShell; never commit the key
py hisaab_ui.py                        # browser UI at http://localhost:8000
py hisaab.py entry clip.flac           # command line, one recorded entry
py test_hisaab.py; py test_eval.py     # offline tests, no API needed
```

The "Type instead" box in the UI runs the whole flow without a mic or an API key.

## Evaluate it

```
py eval_hisaab.py run --noise noise.wav --v3-format verbatim --keyterms --out eval_vk.csv   # 160 synthetic clips
py eval_hisaab.py clips human --v3-format verbatim --out eval_human_v.csv                    # your own recordings of human/truth.csv
py eval_hisaab.py report --out eval_human_v.csv --show
```

Reports re-parse the saved transcripts, so parser fixes need no new API calls.

## What we found

| Test | Result |
|---|---|
| 160 synthetic clips (16 amounts, 2 repeats, clean, phone band, 3 noise levels) | Prisma v3.0 with digits 83% right; number words plus hint words 99%; no wrong amount saved without a question |
| 30 real-voice lines | Prisma v3.0 90% (93% with hints), Prisma v2.5 93%; no wrong amount saved without a question |

Prisma v3.0 turned some spoken numbers into digits with a tenfold error (Rs 175 as Rs 1,750). Asking for number words fixed most of them, and the second model flagged the rest.

## Files

| File | What it is |
|---|---|
| `hisaab.py` | Amount parser (Hindi and Hinglish), two-model gate, ledger, Prisma and Timbre calls, command line |
| `hisaab_ui.py` | Browser UI: mic, both transcripts, spoken read-back, ledger |
| `eval_hisaab.py` | Synthetic-speaker stress test, human-clip scorer, report |
| `human/truth.csv` | The 30 lines to record for the real-voice test |
| `test_hisaab.py`, `test_eval.py` | Offline tests |

## Limits

Small samples (30 real-voice lines, one synthetic voice). The hint words and some spelling fixes were chosen after seeing these clips, so the scores are best-case. One mishear shared by both models (7,500 read as 60,500) was caught only because amounts of Rs 1,000 and above always ask. Confirmation is by tap, not voice. Hindi and Hinglish amounts only. Evon was not used: its open weights need more memory than a 16 GB laptop has.
