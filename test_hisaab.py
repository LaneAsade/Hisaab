from hisaab import *

A = amounts
assert A("ramesh ko dhai hazaar udhaar") == [2500]
assert A("dedh sau") == [150] and A("sawa sau") == [125] and A("paune do sau") == [175]
assert A("sadhe teen hazaar") == [3500] and A("do lakh pachas hazaar") == [250000]
assert A("do hazaar paanch sau") == [2500] and A("₹2,50,000 diye") == [250000]
assert A("ढाई हज़ार") == [2500] and A("पाँच हज़ार") == [5000] and A("पचास हजार") == [50000]
assert A("डेढ़ सौ") == [150] and A("५०० जमा") == [500]
assert A("ek kilo cheeni aur 200 udhaar") == [200] and A("do kilo atta") == []
assert inr(250000) == "₹2,50,000" and inr(5000) == "₹5,000" and inr(50) == "₹50"
assert inr(1234567) == "₹12,34,567"

assert gate(5000, 50000) == ("choose", [5000, 50000]) and gate(None, 500) == ("confirm", [500])
assert gate(500, 500) == ("commit", [500]) and gate(5000, 5000) == ("confirm", [5000])
assert gate(None, None) == ("reask", [])

c, said = db(":memory:"), []
r = run(c, "ramesh ko dhai hazaar udhaar", "ramesh ko 2500 udhaar", said.append, lambda _: "y")
assert r == ("confirm", "ramesh", "udhaar", 2500)
assert run(c, "ramesh ko 500 jama", "ramesh ko 500 jama", said.append, lambda _: "")[3] == 500
assert run(c, "suresh ko paanch hazaar udhaar", "suresh ko pachas hazaar udhaar",
           said.append, lambda _: "2")[3] == 50000
assert balances(c) == {"ramesh": 2000, "suresh": 50000}
assert A("डेढ़ 100 जमा") == [150] and A("ढाई 1000") == [2500] and A("देत 100 जमा।") == [100]
assert parse_entry("ramesh ko 500 jama", ["रमेश"]) == ("रमेश", "jama")
assert parse_entry("देत 100 जमा") == ("?", "jama")
ask = iter(["2", "ramesh"]).__next__  # real clip-2 transcripts: v3.0 misheard "dedh" as "det"
assert run(c, "देत 100 जमा।", "डेढ़ 100 जमा", said.append, lambda _: ask()) == ("choose", "ramesh", "jama", 150)
assert balances(c)["ramesh"] == 1850
# real transcripts from the eval: v2.5 wrote "सावा 100", v3.0 wrote "जामा"
assert A("गीता को सावा 100 जमा लिखो") == [125] and A("गीता को 125 जामा लिखो।") == [125]
assert parse_entry("गीता को 125 जामा लिखो।")[1] == "jama" and parse_entry("सुरेश को 200 उदार")[1] == "udhaar"
assert parse_entry("गीता को 125 लिखो")[1] is None
c2 = db(":memory:")
assert run(c2, "गीता को 125 जामा लिखो।", "गीता को सावा 100 जमा लिखो", said.append, lambda _: "") == ("commit", "गीता", "jama", 125)
assert run(c2, "गीता को 125 लिखो", "गीता को 125 लिखो", said.append, lambda _: "j")[2:] == ("jama", 125)
assert A("सुरेश को देव सौढ़ान लिखो।") == [] and A("सुरेश को देव सौधार लिखो") == []
# real eval transcripts: "पौने 200", "साढ़े 3,000", and fraction-of-a-rupee traps
assert A("रमेश को पौने 200 जमा लिखो") == [175] and A("सुरेश को साढ़े 3,000 उधार लिखो।") == [3500]
assert A("सुरेश को 1.25 उधार लिखो।") == [] and A("सुरेश को सावा सा उधार लिखो।") == []
assert A("रमेश को 1,750 जमा लिखो।") == [1750] and A("रमेश को डोसा उधार लिखो।") == []
assert gate(5, 5) == ("confirm", [5]) and gate(50, 50) == ("commit", [50])
# verbatim (number-word) output, 11-99, and "sawa" before a number
assert A("रमेश को पच्चीस जमा") == [25] and A("एक सौ पचास") == [150] and A("पंद्रह सौ") == [1500]
assert A("दो सौ पचहत्तर") == [275] and A("तीन हज़ार पाँच सौ") == [3500] and A("निन्यानवे") == [99]
assert A("सवा दो सौ") == [225] and A("सवा सौ") == [125] and A("सावा 200") == [225] and A("सावा 100") == [125]
assert A("रमेश को सादे तीन हज़ार जमा लिखो।") == [3500] and A("सुरेश को पच्चास जमा लिखो।") == [50]
assert A("रमेश को पाँच सौ उधार दे।") == [500] and A("गीता को दो सौ जमा लिखो।") == [200]
# real human clips: spelling variants, a clock-time reading, and a mishear both decodes shared
assert A("गीता को छः सौ जमा लिखो।") == [600] and A("गीता को अट्ठारह सौ उधार लिखो।") == [1800]
assert A("सुरेश 04:30 100 जमा लिखों") == [450] and A("सुरेश 03:45 100 जमा") == [375] and A("सुरेश 4:15 1,000 जमा") == [4250]
assert A("सुरेश को साठ हज़ार पाँच सौ जमा लिखो।") == [60500]  # सात heard as साठ: only the large-amount read-back can catch it
import hisaab, os, tempfile  # a Cloudflare 403 on a WAV upload retries once as FLAC
calls = []


class _R:
    def json(self):
        return {"transcript": "ok"}


def _fake_post(url, **kw):
    calls.append(kw["files"]["audio_file"][0])
    if len(calls) == 1:
        raise hisaab.ApiError(403, "from x\nCloudflare block (code ?)")
    return _R()


hisaab._post, hisaab._flac = _fake_post, lambda p: b"flac"
f = os.path.join(tempfile.mkdtemp(), "x.wav")
open(f, "wb").write(b"RIFF")
assert hisaab.stt(f) == "ok" and calls == ["x.wav", "x.flac"]
import json  # keyterms go to v3.0 as a JSON array form field
seen = {}
hisaab._post = lambda url, **kw: seen.update(kw) or _R()
hisaab.stt(f, "v3", keyterms=["डेढ़"])
assert json.loads(seen["data"]["keyterms"]) == ["डेढ़"]
hisaab.stt(f, "v25", keyterms=["डेढ़"])
assert "keyterms" not in seen["data"]
hisaab.stt(f, "v3", fmt="verbatim")
assert seen["data"]["format"] == "verbatim"
hisaab.stt(f, "v25", fmt="verbatim")
assert seen["data"]["format"] == "transcribe"
print("all tests passed;", len(said), "spoken prompts")
