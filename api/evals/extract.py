"""Pull quantities out of an advisor answer written in English, Hindi or Hinglish.

`quantities(text)` returns every number that carries a meaning the checks care
about (money, years, months, days, hours, clock times, kW, watts, units,
percent, panels, floors, area, metres, degrees), with its value in base units
and the size of its last stated digit (`step`), which is what decides how much
rounding to forgive later. Money also carries the currency it was written in.

Handles: Devanagari digits, Indian comma grouping (1,65,000), lakh / लाख /
crore / hazaar / हज़ार / k / L multipliers, a currency sign or code before
(₹, Rs, $, A$, US$, €, £, USD ...) or a currency word after (rupees, dollars,
euros, cents, paise), number words in front of a unit ("five years",
"paanch saal", "साढ़े चार साल", "dhai lakh"), ranges ("4-5 years",
"₹1.55 से 2.41 लाख"), "4 years 10 months", clock times ("09:40", "4:10 pm",
"10 am"), and bare large numbers with no unit at all.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass

_DEV = "ऀ-ॿ"
#: Word boundaries that also work inside Devanagari, where vowel signs are not `\w`.
_L = rf"(?<![A-Za-z0-9{_DEV}])"
_R = rf"(?![A-Za-z0-9{_DEV}])"

_DEV_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
_URL = re.compile(r"(?:https?://|www\.)\S+|\b[\w.-]+\.(?:gov\.in|com|org|net|in)\b(?:/\S*)?", re.I)


def strip_urls(text: str) -> str:
    return _URL.sub(" ", text)


def normalise(text: str) -> str:
    """Lower-noise form used for all matching: no nukta, ASCII digits, no URLs, plain spaces."""
    text = unicodedata.normalize("NFD", text).replace("़", "")
    text = unicodedata.normalize("NFC", text)
    text = text.translate(_DEV_DIGITS)
    text = re.sub(r"[   ​‌‍]", " ", text)
    return strip_urls(text)


def _alt(words: list[str]) -> str:
    return "|".join(sorted((re.escape(normalise(w)) for w in words), key=len, reverse=True))


# ---- unit vocabulary -------------------------------------------------------

_MULTIPLIERS = {
    100_000: ["lakhs", "lakh", "lacs", "lac", "लाख"],
    10_000_000: ["crores", "crore", "करोड़"],
    1_000: ["thousand", "hazaar", "hazar", "hajar", "hajaar", "हज़ार"],
}
#: Currency words written after the number, by the currencies they can mean.
_MONEY_WORDS = {
    "INR": ["rupees", "rupee", "rupaye", "rupay", "rupaiye", "rupya", "rs", "inr", "रुपये", "रुपए", "रुपया", "रुपयों", "रु"],
    "USD": ["usd", "us dollars", "us dollar"],
    "AUD": ["aud", "australian dollars", "australian dollar"],
    "DOLLAR": ["dollars", "dollar"],
    "EUR": ["eur", "euros", "euro"],
    "GBP": ["gbp", "pounds", "pound"],
}
#: Hundredths of the main unit: "16 cents a unit", "60 paise".
_FRACTION_WORDS = {"DOLLAR": ["cents", "cent"], "INR": ["paise", "paisa", "पैसे", "पैसा"]}
#: Currency signs and codes written before the number. Longest first, so "A$" is not read as "$".
_MONEY_SIGNS = {
    "₹": "INR", "rs.": "INR", "rs": "INR", "inr": "INR", "रु.": "INR", "रु": "INR", "रुपये": "INR", "रुपए": "INR",
    "us$": "USD", "usd": "USD", "a$": "AUD", "au$": "AUD", "aud": "AUD", "$": "DOLLAR",
    "€": "EUR", "eur": "EUR", "£": "GBP", "gbp": "GBP",
}
#: Which survey currencies each way of writing money is right for. A bare "$" serves any dollar.
CURRENCY_FITS = {
    "INR": {"INR"}, "USD": {"USD"}, "AUD": {"AUD"}, "EUR": {"EUR"}, "GBP": {"GBP"},
    "DOLLAR": {"USD", "AUD", "CAD", "NZD", "SGD", "HKD"},
}

_UNITS = {
    "money": [w for ws in (*_MONEY_WORDS.values(), *_FRACTION_WORDS.values()) for w in ws],
    "years": ["years", "year", "yrs", "yr", "saal", "sal", "saalon", "salon", "varsh", "baras", "साल", "सालों", "वर्ष", "वर्षों", "बरस"],
    "months": ["months", "month", "mahine", "mahina", "mahino", "महीने", "महीना", "महीनों", "माह"],
    "days": ["days", "day", "दिन", "दिनों"],
    "hours": ["hours", "hour", "hrs", "hr", "ghante", "ghanta", "ghanton", "घंटे", "घंटा", "घंटों"],
    "units": ["kwh", "units", "unit", "यूनिट", "यूनिट्स", "यूनिटों", "इकाई", "इकाइयां", "इकाइयों"],
    "kw": ["kwp", "kw", "kilowatts", "kilowatt", "किलोवाट", "केडब्ल्यू"],
    "watts": ["watts", "watt", "wp", "w", "वाट"],
    "percent": ["%", "percent", "per cent", "pratishat", "प्रतिशत", "फ़ीसदी"],
    "panels": ["panels", "panel", "पैनल", "पैनलों", "पैनल्स"],
    "floors": ["floors", "floor", "storeys", "storey", "stories", "story", "manzil", "manzila", "मंज़िल", "मंज़िला", "मंज़िलें", "तल"],
    "area": ["m²", "m2", "sq m", "sq. m", "sqm", "square metres", "square meters", "square metre", "square meter", "वर्ग मीटर", "sq ft", "sq. ft", "sqft", "square feet"],
    "metres": ["metres", "meters", "metre", "meter", "m", "मीटर", "feet", "ft"],
    "degrees": ["°", "degrees", "degree", "deg", "डिग्री"],
}
_WORD_CURRENCY = {normalise(w).lower(): code for code, ws in (*_MONEY_WORDS.items(), *_FRACTION_WORDS.items()) for w in ws}
_FRACTIONS = {normalise(w).lower() for ws in _FRACTION_WORDS.values() for w in ws}
_MULT_RE = re.compile(
    r"\s*-?\s*(?:" + "|".join(f"(?P<m{v}>{_alt(ws)})" for v, ws in _MULTIPLIERS.items()) + ")" + _R, re.I
)
#: "₹78k", "₹1.65L": only when glued to the digits.
_MULT_ATTACHED_RE = re.compile(r"(?:(?P<k>k)|(?P<l>L))" + _R)
_UNIT_RE = re.compile(
    r"\s*-?\s*(?:"
    + "|".join(f"(?P<{kind}>{_alt(ws)})" + ("" if kind == "percent" else _R) for kind, ws in _UNITS.items())
    + ")",
    re.I,
)
_CURRENCY_BEFORE = re.compile(
    r"(?:" + "|".join(("" if sign[0] in "₹$€£" else _L) + re.escape(normalise(sign)) for sign in sorted(_MONEY_SIGNS, key=len, reverse=True)) + r")\s*$",
    re.I,
)
_SIGN_CURRENCY = {normalise(sign).lower(): code for sign, code in _MONEY_SIGNS.items()}
#: "09:40", "4:10 pm", "10 am", "शाम 4:10 बजे". The hour alone counts only with am or pm after it.
_CLOCK = re.compile(r"(?<![\d:.,])(?:(\d{1,2}):(\d{2})(?!\d)(?:\s*([ap])\.?m\.?(?![A-Za-z]))?|(\d{1,2})\s*([ap])\.?m\.?(?![A-Za-z]))", re.I)
_ORDINAL_AFTER = re.compile(r"(?:st|nd|rd|th|वें|वां|वीं)" + _R, re.I)
_NUMBER = re.compile(r"(?<!\d)(?<!\d[.,])\d+(?:,\d+)*(?:\.\d+)?")
_SIGN = r"(?:₹|rs\.?|रु\.?|(?:us|au?)?\$|€|£|usd|aud|eur|gbp)?"
_RANGE_GAP = re.compile(r"\s*(?:-|–|—|to|se|से)\s*" + _SIGN + r"\s*", re.I)
_AND_GAP = re.compile(r"\s*(?:and|aur|और|or|ya|या)\s*" + _SIGN + r"\s*", re.I)
_YM_GAP = re.compile(r"\s*,?\s*(?:and|aur|और)?\s*", re.I)

# ---- number words ----------------------------------------------------------

_WORDS = {
    1: ["one", "ek", "एक"],
    2: ["two", "do", "दो"],
    3: ["three", "teen", "tin", "तीन"],
    4: ["four", "char", "chaar", "चार"],
    5: ["five", "paanch", "panch", "पांच", "पाँच"],
    6: ["six", "chhe", "chhah", "cheh", "chhe", "छह", "छः", "छे"],
    7: ["seven", "saat", "सात"],
    8: ["eight", "aath", "आठ"],
    9: ["nine", "nau", "नौ"],
    10: ["ten", "das", "दस"],
    11: ["eleven", "gyarah", "ग्यारह"],
    12: ["twelve", "barah", "baarah", "बारह"],
    15: ["fifteen", "pandrah", "पंद्रह"],
    20: ["twenty", "bees", "बीस"],
    25: ["twenty-five", "twenty five", "pachees", "pachis", "pacchis", "pachchis", "पच्चीस"],
    30: ["thirty", "tees", "तीस"],
}
_FIXED_FRACTIONS = {1.5: ["dedh", "derh", "डेढ़"], 2.5: ["dhai", "adhai", "dhaai", "ढाई", "अढ़ाई"]}
_MODIFIERS = {0.5: ["saadhe", "sadhe", "sarhe", "साढ़े"], 0.25: ["sava", "sawa", "सवा"], -0.25: ["paune", "pone", "पौने"]}

_WORD_VALUE = {normalise(w).lower(): v for v, ws in {**_WORDS, **_FIXED_FRACTIONS}.items() for w in ws}
_MOD_VALUE = {normalise(w).lower(): v for v, ws in _MODIFIERS.items() for w in ws}
#: A number word counts only when a unit or multiplier follows, so that Hinglish "do" (give) is left alone.
_FOLLOWED_BY_UNIT = (
    r"(?=[\s-]+(?:"
    + _alt([w for ws in _MULTIPLIERS.values() for w in ws] + [w for k in ("money", "years", "months", "kw", "hours", "floors") for w in _UNITS[k]])
    + ")"
    + _R
    + ")"
)
_WORD_NUMBER_RE = re.compile(
    _L + rf"(?:(?P<mod>{_alt(list(_MOD_VALUE))})\s+)?(?P<num>{_alt(list(_WORD_VALUE))}|\d+)" + _FOLLOWED_BY_UNIT, re.I
)


def _words_to_digits(text: str) -> str:
    def repl(m: re.Match) -> str:
        num, mod = m.group("num").lower(), m.group("mod")
        if num.isdigit() and not mod:
            return m.group(0)
        value = float(num) if num.isdigit() else float(_WORD_VALUE[num])
        if mod:
            value += _MOD_VALUE[mod.lower()]
        return f"{value:g}"

    return _WORD_NUMBER_RE.sub(repl, text)


# ---- extraction ------------------------------------------------------------


@dataclass
class Quantity:
    kind: str  # money | years | months | days | hours | time | units | kw | watts | percent | panels | floors | area | metres | degrees | bare
    value: float  # money, years, months, ... (multiplier applied); a clock time is minutes after midnight
    step: float  # size of the last digit the writer stated, in the same unit as value
    text: str  # the matched slice
    context: str  # a little text either side, for reports
    start: int
    end: int
    range_with: int | None = None  # index of the other end when written as "a-b" or "a to b"
    currency: str | None = None  # for money: INR, USD, AUD, EUR, GBP, or DOLLAR for a bare "$"; None when no sign or word says
    alt: float | None = None  # for a clock time with no am or pm ("4:10"): the afternoon reading

    def to_dict(self) -> dict:
        return asdict(self)


def _step(digits: str, multiplier: float) -> float:
    if "." in digits:
        return 10 ** -len(digits.split(".")[1]) * multiplier
    whole = digits.rstrip("0")
    zeros = len(digits) - len(whole) if whole else 0
    return 10**zeros * multiplier


def _clock_times(text: str) -> tuple[str, list[Quantity]]:
    """Clock times in the text, and the text with them blanked out so their digits are not read again as numbers."""
    found = []
    for m in _CLOCK.finditer(text):
        hour, minute, meridiem = (int(m.group(1)), int(m.group(2)), m.group(3)) if m.group(1) else (int(m.group(4)), 0, m.group(5))
        if hour > 23 or minute > 59:
            continue
        alt = None
        if meridiem:
            hour = hour % 12 + (12 if meridiem.lower() == "p" else 0)
        elif 1 <= hour <= 11:
            alt = (hour + 12) * 60.0 + minute
        found.append(
            Quantity("time", hour * 60.0 + minute, 1.0 if m.group(1) else 60.0, m.group(0).strip(), text[max(0, m.start() - 45) : m.end() + 25].replace("\n", " ").strip(), m.start(), m.end(), alt=alt)
        )
        text = text[: m.start()] + " " * (m.end() - m.start()) + text[m.end() :]
    return text, found


def quantities(text: str) -> list[Quantity]:
    text, times = _clock_times(_words_to_digits(normalise(text)))
    raw = []
    for m in _NUMBER.finditer(text):
        digits = m.group(0).replace(",", "")
        end = m.end()
        if _ORDINAL_AFTER.match(text, end):
            continue
        sign = _CURRENCY_BEFORE.search(text[max(0, m.start() - 8) : m.start()])
        currency = bool(sign)
        code = _SIGN_CURRENCY.get(sign.group(0).strip().lower()) if sign else None
        multiplier = 1.0
        attached = _MULT_ATTACHED_RE.match(text, end)
        spaced = _MULT_RE.match(text, end)
        if spaced:
            multiplier = float(next(k[1:] for k, v in spaced.groupdict().items() if v))
            end = spaced.end()
        elif attached and (currency or attached.group("l")):
            multiplier = 1_000.0 if attached.group("k") else 100_000.0
            end = attached.end()
        if multiplier in (100_000.0, 10_000_000.0):
            code = code or "INR"  # lakh and crore are only ever rupees
        unit = None
        um = _UNIT_RE.match(text, end)
        if um:
            unit = um.lastgroup
            end = um.end()
            if unit == "money":
                word = um.group("money").lower()
                code = code or _WORD_CURRENCY.get(word)
                if word in _FRACTIONS:
                    multiplier *= 0.01
        raw.append({"m": m, "digits": digits, "currency": currency, "code": code, "mult": multiplier, "unit": unit, "end": end})

    # "4-5 years", "₹1.55 to 2.41 lakh": the first number borrows the second's unit and multiplier.
    pairs = {}
    for i in range(len(raw) - 1):
        a, b = raw[i], raw[i + 1]
        gap = text[a["end"] : b["m"].start()]
        if _RANGE_GAP.fullmatch(gap):
            calendar = "," not in a["m"].group(0) and "." not in a["digits"] and 1990 <= float(a["digits"]) <= 2100
            if a["unit"] is None and a["mult"] == 1.0 and not calendar:
                a["unit"], a["mult"] = b["unit"], b["mult"]
                a["currency"] = a["currency"] or b["currency"]
                a["code"] = a["code"] or b["code"]
            pairs[i] = i + 1
        elif _AND_GAP.fullmatch(gap):
            pairs[i] = i + 1

    out: list[Quantity] = []
    index_of = {}
    for i, r in enumerate(raw):
        m, unit, mult = r["m"], r["unit"], r["mult"]
        number = float(r["digits"])
        value = number * mult
        if r["currency"] or unit == "money" or (mult > 1 and unit in (None, "money")):
            kind = "money"
        elif unit:
            kind = unit
        elif value >= 1000 and not ("," not in m.group(0) and "." not in r["digits"] and 1990 <= number <= 2100):
            kind = "bare"
        else:
            continue
        start = m.start() - (1 if text[max(0, m.start() - 1) : m.start()] == "₹" else 0)
        index_of[i] = len(out)
        out.append(
            Quantity(
                kind=kind,
                value=value,
                step=_step(r["digits"], mult),
                text=text[start : r["end"]].strip(),
                context=text[max(0, start - 45) : r["end"] + 25].replace("\n", " ").strip(),
                start=start,
                end=r["end"],
                currency=r["code"] if kind == "money" else None,
            )
        )
    for i, j in pairs.items():
        if i in index_of and j in index_of and out[index_of[i]].kind == out[index_of[j]].kind:
            out[index_of[i]].range_with = index_of[j]
            out[index_of[j]].range_with = index_of[i]

    # "4 years 10 months" is one figure.
    merged: list[Quantity] = []
    skip = set()
    for i, q in enumerate(out):
        if i in skip:
            continue
        nxt = out[i + 1] if i + 1 < len(out) else None
        if q.kind == "years" and nxt and nxt.kind == "months" and nxt.value < 12 and _YM_GAP.fullmatch(text[q.end : nxt.start]):
            q = Quantity("years", q.value + nxt.value / 12, 1 / 12, text[q.start : nxt.end], q.context, q.start, nxt.end)
            skip.add(i + 1)
        merged.append(q)
    if skip:  # indices moved; range links are rare next to year-month pairs, so drop them
        for q in merged:
            q.range_with = None
    return merged + times  # times go last, so the range links between the numbers stay valid


# ---- language --------------------------------------------------------------

#: Romanised Hindi words that are not also common English words.
_HINGLISH = set(
    """hai hain aap aapka aapki aapke aapko mein nahi nahin hoga hogi honge ho karein karna karne karke kar
    sakte sakta sakti liye lagbhag kareeb karib saal yeh ye kya ke ki ka ko se bachat kharcha kharch lagega
    lagegi milega milegi milenge chahiye hota hoti hote wala wali wale bhi toh lekin agar kyunki paisa paise
    rupaye mahine tak hum apne apna apni isse iska iski iske jo zyada jyada kam bahut accha achha theek haan
    ji aur ya par chhat ghar bijli wasool vasool sahi kitna kitni kitne yaani matlab jab tab phir fir sirf bas
    raha rahi rahe gaya gayi diya liya hue hui kuch koi sab har din baad pehle abhi yahan wahan jaise taki
    jisse unhe unka inka aapne humne mujhe mera meri mere tum""".split()
)
#: Names the advisor may quote in any language without that counting as Hinglish.
_NAMES = {"bijli", "ghar", "surya", "muft", "yojana", "pm", "mahavitaran"}


#: Everyday words that mark a language, for answers that are in neither English nor Hindi.
STOPWORDS = {
    "en": set("the and is are of to in for you your it that this with on will be not can have has from at as but or if about would".split()),
    "de": set("der die das und ist sind nicht ich sie ihr ihre ihren ihrem für mit auf ein eine einen von zu den dem im wird kann noch keine kein dass oder wie pro bei aus auch nach werden sich es".split()),
    "es": set("el la los las y es son no que de en para con su sus un una por se lo más del al como pero puede tiene este esta".split()),
}


def stopword_shares(text: str) -> dict:
    """Share of the words in `text` that are everyday words of each language in STOPWORDS."""
    words = re.findall(r"[^\W\d_]+", strip_urls(text).lower())
    return {lang: round(sum(1 for w in words if w in marks) / len(words), 3) if words else 0.0 for lang, marks in STOPWORDS.items()}


def language_of(text: str) -> dict:
    """Classify an answer as 'en', 'hi' (Devanagari), 'hinglish' (romanised Hindi) or 'mixed'."""
    text = strip_urls(text)
    dev = sum(1 for c in text if "ऀ" <= c <= "ॿ")
    lat = sum(1 for c in text if c.isascii() and c.isalpha())
    dev_ratio = dev / (dev + lat) if dev + lat else 0.0
    words = [w for w in re.findall(r"[A-Za-z]+", text.lower()) if w not in _NAMES]
    markers = sum(1 for w in words if w in _HINGLISH)
    marker_ratio = markers / len(words) if words else 0.0
    if dev_ratio >= 0.75:
        label = "hi"
    elif dev_ratio > 0.02:
        label = "mixed"
    elif marker_ratio >= 0.12:
        label = "hinglish"
    elif marker_ratio <= 0.03 and dev == 0:
        label = "en"
    else:
        label = "mixed"
    return {"label": label, "devanagari_share": round(dev_ratio, 3), "romanised_hindi_share": round(marker_ratio, 3)}
