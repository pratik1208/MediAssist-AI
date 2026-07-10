"""Deterministic emergency screening shared by every agent (Edge Case 11).

red_flag_check() runs BEFORE and independently of any AI call: it is plain
regex over the patient's words, so it is auditable, testable, and immune to
prompt drift (NFR-3). Never rely on the model alone for emergency detection —
the AI layer is a second net for indirect phrasings, not a replacement.

The patterns deliberately err toward false positives: sending a non-emergency
to human review costs minutes; missing a real one costs a life.
"""

import re

RED_FLAG_PATTERNS = [
    # cardiac
    r"crush(ing)?\s.*chest",
    r"chest\s+(pain|pressure|tight|heaviness|discomfort)",
    r"(pain|pressure).*(left arm|jaw).*(chest)|chest.*(radiat|spread).*(arm|jaw|neck|back)",
    # breathing
    r"can'?t\s+breathe|cannot\s+breathe|unable to breathe",
    r"struggling to breathe|gasping for (air|breath)",
    r"short(ness)? of breath (at rest|while sitting|doing nothing)",
    r"(lips|face|skin) (are |is )?(turning )?(blue|bluish)",
    r"chok(ing|ed) (on|and)",
    # stroke
    r"face\s.*(droop|numb)",
    r"slurr(ed|ing)\s+speech",
    r"one side\s.*(weak|numb|paraly)",
    r"(sudden|suddenly).*(can'?t|cannot) (see|speak|talk|move)",
    # mental health crisis
    r"(end|take|took) my (life|own life)",
    r"suicid",
    r"kill(ing)? myself",
    r"(want|going|plan(ning)?) to (die|hurt myself|harm myself)",
    r"self.?harm",
    # consciousness / neuro
    r"worst (headache|head pain) of (my|his|her|their) life",
    r"never had a (headache|head pain) this bad",
    r"unconscious|unresponsive|won'?t wake up",
    r"seizure|convuls",
    r"passed out|blacked out|fainted and",
    # bleeding
    r"(heavy|severe|uncontrolled|won'?t stop|can'?t stop)\s.*bleed",
    r"bleed(ing)?\s.*(heavily|badly|won'?t stop|everywhere)",
    r"(vomit|cough)(ing|ed)?\s.*blood",
    # poisoning / allergy
    r"overdos",
    r"(swallowed|drank|took).*(poison|bleach|chemicals|too many pills)",
    r"(throat|tongue|face)\s.*(swelling|swollen|closing)",
    r"anaphyla",
]

_COMPILED = [re.compile(p, re.I) for p in RED_FLAG_PATTERNS]


def find_red_flags(text: str) -> list[str]:
    """The patterns that matched, for audit trails and escalation summaries."""
    return [p.pattern for p in _COMPILED if p.search(text or "")]


def red_flag_check(text: str) -> bool:
    """True if the text contains any emergency red-flag phrase."""
    return any(p.search(text or "") for p in _COMPILED)
