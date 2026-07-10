"""Text normalization for lexical matching.

Source records abbreviate ("CONC RM 50MPA W/ 25% SLAG") while the catalog
spells things out ("Ready-mix concrete, 50 MPa, 25% slag"). Normalization
turns both sides into comparable lowercase tokens:

1. Phrase rules rewrite multi-word/imperial spellings on the raw text.
2. The text is split into word and number tokens.
3. Record tokens go through the abbreviation map, then two fallbacks for
   spellings the map does not know: a plural strip, and a unique-prefix
   expansion against the catalog vocabulary (construction shorthand is
   almost always a chopped-off word).

The abbreviation map was built by diffing the record vocabulary against
the catalog vocabulary over the fixture set; words deliberately absent
(ALLOW, DWG, MOB, ...) mark non-material records and must stay
untranslated so those records score low and land in the red tier.
"""

import re

# Applied to lowercased raw text before tokenizing. Keys are regexes.
# Number-unit gluing ("50 MPa" -> token "50mpa") keeps each number tied
# to what it measures; without it "50 MPa, 25% slag" and "25 MPa,
# 50% slag" collapse into the same bag of tokens.
PHRASE_RULES: list[tuple[str, str]] = [
    (r"\bw/", " "),               # "W/ 25% SLAG": the catalog never says
                                  # "with", so translating it would add a
                                  # dead token to every record carrying it
    (r"\b5/8\s*in\b", " 15.9 mm "),   # imperial gypsum sizes -> catalog metric
    (r"\b1/2\s*in\b", " 12.7 mm "),
    (r"\bgr\s*400\b", " grade 400w "),  # rebar shorthand for Grade 400W
    # The lookbehind keeps the glue off dimension parts: in "38x89 mm"
    # the 89 belongs to the dimension token, not to "mm".
    (r"(?<![\dx.])(\d+(?:\.\d+)?)\s*mpa\b", r" \1mpa "),
    (r"(?<![\dx.])(\d+(?:\.\d+)?)\s*mm\b", r" \1mm "),
    (r"(?<![\dx.])(\d+(?:\.\d+)?)\s*%", r" \1pct "),
]

# Record shorthand -> catalog wording. Multi-word expansions are allowed.
ABBREVIATIONS: dict[str, str] = {
    "asph": "asphalt",
    "bd": "board",
    "blk": "black",
    "bm": "wide flange beam",
    "chan": "channel",
    "cmu": "concrete masonry unit",
    "conc": "concrete",
    "cu": "copper",
    "dfir": "douglas fir",
    "fa": "fly ash",
    "fg": "fibreglass",
    "gr": "grade",
    "gran": "granular",
    "gyp": "gypsum",
    "insul": "insulation",
    "int": "interior",
    "lbr": "lumber",
    "ltx": "latex",
    "lw": "lightweight",
    "mw": "mineral wool",   # in records MW is mineral wool, not wire mesh MW9.1
    "pnt": "paint",
    "porc": "porcelain",
    "pt": "pressure treated",
    "pvg": "paving",
    "plywd": "plywood",
    "rebar": "reinforcing steel bar",
    "rm": "ready mix",
    "sch": "schedule",
    "stl": "steel",
}

# Number-led mixed tokens ("50mpa", "400w") stay whole so glued
# number-unit pairs survive; letter-led ones ("t90") still split.
_TOKEN_RE = re.compile(r"\d+(?:\.\d+)?[a-z]+|[a-z]+|\d+(?:\.\d+)?")

# Dimension strings ("6x6x3/8", "915x2135", "3/8") stay whole: splitting
# them loses which number is which, so HSS 4x2 would look identical to
# HSS 2x2 after duplicates collapse. Kept atomic they are also rare
# tokens, which forces exact-size agreement.
_DIMENSION_RE = re.compile(r"\d+(?:\.\d+)?(?:x\d+(?:\.\d+)?|/\d+)+")


def tokenize(text: str) -> list[str]:
    """Lowercase, apply phrase rules, split into word/number tokens while
    keeping dimension strings atomic."""
    text = text.lower()
    for pattern, replacement in PHRASE_RULES:
        text = re.sub(pattern, replacement, text)
    dimensions = _DIMENSION_RE.findall(text)
    remainder = _DIMENSION_RE.sub(" ", text)
    return dimensions + _TOKEN_RE.findall(remainder)


def expand_token(token: str, vocab: set[str]) -> list[str]:
    """Translate one record token into catalog wording.

    Order: abbreviation map, known vocabulary word, plural strip, then the
    unique-prefix fallback (new abbreviations are usually the start of a
    real word; expand only when exactly one vocabulary word fits, so
    ambiguous chops like "con" stay untouched).
    """
    if token in ABBREVIATIONS:
        return tokenize(ABBREVIATIONS[token])
    if token in vocab or not token.isalpha():
        return [token]
    if token.endswith("s") and token[:-1] in vocab:
        return [token[:-1]]
    if len(token) >= 3:
        completions = [w for w in vocab if w.startswith(token)]
        if len(completions) == 1:
            return completions
    return [token]


def normalize_record_text(text: str, vocab: set[str]) -> set[str]:
    """Full record-side pipeline: tokenize, then expand every token."""
    tokens: list[str] = []
    for token in tokenize(text):
        tokens.extend(expand_token(token, vocab))
    return set(tokens)
