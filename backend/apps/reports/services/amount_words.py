# Amount written out in words for the "Arrêté à la somme de" line of the
# priced documents (proforma, purchase order) - spec 2026-10-11
# documents-commerciaux D6: fr / en / ar, whole units up to the billions,
# no extra dependency. Cents are ignored (XOF amounts are whole).

from decimal import ROUND_HALF_UP, Decimal

_CURRENCY = {"fr": "FCFA", "en": "FCFA", "ar": "فرنك"}
_SCALES = [(10**9, "billion"), (10**6, "million"), (10**3, "thousand")]

# --- French ------------------------------------------------------------------

_FR_UNITS = [
    "zéro", "un", "deux", "trois", "quatre", "cinq", "six", "sept", "huit", "neuf", "dix",
    "onze", "douze", "treize", "quatorze", "quinze", "seize", "dix-sept", "dix-huit", "dix-neuf",
]
_FR_TENS = {2: "vingt", 3: "trente", 4: "quarante", 5: "cinquante", 6: "soixante"}


def _fr_below_100(n: int, plural_ok: bool) -> str:
    if n < 20:
        return _FR_UNITS[n]
    tens, unit = divmod(n, 10)
    if tens in (7, 9):  # soixante-dix..., quatre-vingt-dix...
        base = "soixante" if tens == 7 else "quatre-vingt"
        if tens == 7 and unit == 1:
            return "soixante et onze"
        return f"{base}-{_FR_UNITS[10 + unit]}"
    if tens == 8:
        if unit == 0:
            return "quatre-vingts" if plural_ok else "quatre-vingt"
        return f"quatre-vingt-{_FR_UNITS[unit]}"
    word = _FR_TENS[tens]
    if unit == 0:
        return word
    if unit == 1:
        return f"{word} et un"
    return f"{word}-{_FR_UNITS[unit]}"


def _fr_below_1000(n: int, plural_ok: bool) -> str:
    hundreds, rest = divmod(n, 100)
    parts = []
    if hundreds:
        if hundreds == 1:
            parts.append("cent")
        else:
            parts.append(f"{_FR_UNITS[hundreds]} cent" + ("s" if rest == 0 and plural_ok else ""))
    if rest:
        parts.append(_fr_below_100(rest, plural_ok))
    return " ".join(parts)


def _fr(n: int) -> str:
    if n == 0:
        return _FR_UNITS[0]
    words = {"billion": ("milliard", "milliards"), "million": ("million", "millions")}
    parts = []
    for scale, name in _SCALES:
        group, n = divmod(n, scale)
        if not group:
            continue
        if name == "thousand":
            # "mille" is invariable and never preceded by "un"; a group before
            # it keeps "cent"/"quatre-vingt" singular.
            parts.append("mille" if group == 1 else f"{_fr_below_1000(group, False)} mille")
        else:
            singular, plural = words[name]
            parts.append(f"{_fr_below_1000(group, True)} {singular if group == 1 else plural}")
    if n:
        parts.append(_fr_below_1000(n, True))
    return " ".join(parts)


# --- English -----------------------------------------------------------------

_EN_UNITS = [
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
    "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen",
]
_EN_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]


def _en_below_1000(n: int) -> str:
    hundreds, rest = divmod(n, 100)
    parts = [f"{_EN_UNITS[hundreds]} hundred"] if hundreds else []
    if rest:
        if rest < 20:
            parts.append(_EN_UNITS[rest])
        else:
            tens, unit = divmod(rest, 10)
            parts.append(_EN_TENS[tens] + (f"-{_EN_UNITS[unit]}" if unit else ""))
    return " ".join(parts)


def _en(n: int) -> str:
    if n == 0:
        return _EN_UNITS[0]
    parts = []
    for scale, name in _SCALES:
        group, n = divmod(n, scale)
        if group:
            parts.append(f"{_en_below_1000(group)} {name}")
    if n:
        parts.append(_en_below_1000(n))
    return " ".join(parts)


# --- Arabic ------------------------------------------------------------------

_AR_UNITS = [
    "صفر", "واحد", "اثنان", "ثلاثة", "أربعة", "خمسة", "ستة", "سبعة", "ثمانية", "تسعة", "عشرة",
    "أحد عشر", "اثنا عشر", "ثلاثة عشر", "أربعة عشر", "خمسة عشر", "ستة عشر", "سبعة عشر",
    "ثمانية عشر", "تسعة عشر",
]
_AR_TENS = ["", "", "عشرون", "ثلاثون", "أربعون", "خمسون", "ستون", "سبعون", "ثمانون", "تسعون"]
_AR_HUNDREDS = ["", "مائة", "مائتان", "ثلاثمائة", "أربعمائة", "خمسمائة", "ستمائة", "سبعمائة",
                "ثمانمائة", "تسعمائة"]
# singular, dual, plural (3-10), accusative singular (11-99)
_AR_SCALES = {
    "billion": ("مليار", "ملياران", "مليارات", "مليارا"),
    "million": ("مليون", "مليونان", "ملايين", "مليونا"),
    "thousand": ("ألف", "ألفان", "آلاف", "ألفا"),
}


def _ar_below_1000(n: int) -> str:
    hundreds, rest = divmod(n, 100)
    parts = [_AR_HUNDREDS[hundreds]] if hundreds else []
    if rest:
        if rest < 20:
            parts.append(_AR_UNITS[rest])
        else:
            tens, unit = divmod(rest, 10)
            parts.append(f"{_AR_UNITS[unit]} و{_AR_TENS[tens]}" if unit else _AR_TENS[tens])
    return " و".join(parts)


def _ar(n: int) -> str:
    if n == 0:
        return _AR_UNITS[0]
    parts = []
    for scale, name in _SCALES:
        group, n = divmod(n, scale)
        if not group:
            continue
        singular, dual, plural, accusative = _AR_SCALES[name]
        last_two = group % 100
        if group == 1:
            parts.append(singular)
        elif group == 2:
            parts.append(dual)
        elif 3 <= last_two <= 10:
            parts.append(f"{_ar_below_1000(group)} {plural}")
        elif last_two >= 11:
            parts.append(f"{_ar_below_1000(group)} {accusative}")
        else:
            parts.append(f"{_ar_below_1000(group)} {singular}")
    if n:
        parts.append(_ar_below_1000(n))
    return " و".join(parts)


_SPELLERS = {"fr": _fr, "en": _en, "ar": _ar}


def amount_in_words(amount, lang: str = "fr", currency: str = "FCFA") -> str:
    lang = lang if lang in _SPELLERS else "fr"
    # Rounded like the printed total (_format_money: half-up to the unit).
    words = _SPELLERS[lang](int(Decimal(amount).quantize(Decimal("1"), rounding=ROUND_HALF_UP)))
    if lang != "ar":
        words = words[0].upper() + words[1:]
    label = _CURRENCY[lang] if currency in ("XOF", "FCFA", "") else currency
    return f"{words} {label}"
