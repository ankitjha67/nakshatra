"""Static Jyotish reference data used by the mock engine and the rules layer.

These tables are intentionally small and classical. They drive the deterministic
*findings* so that the interpretive substance is computed, not invented by an LLM.
When you plug in your own engine, the findings layer reads from its JSON instead,
but these tables still power the rule logic (dignities, dasha themes, etc.).
"""
from __future__ import annotations

GRAHAS = ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn", "Rahu", "Ketu"]

SIGNS = ["Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
         "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces"]

# sign index (1-12) -> ruling graha
SIGN_LORD = {
    1: "Mars", 2: "Venus", 3: "Mercury", 4: "Moon", 5: "Sun", 6: "Mercury",
    7: "Venus", 8: "Mars", 9: "Jupiter", 10: "Saturn", 11: "Saturn", 12: "Jupiter",
}

# graha -> sign of exaltation (debilitation is the opposite sign, +6 mod 12)
EXALT_SIGN = {
    "Sun": 1, "Moon": 2, "Mars": 10, "Mercury": 6,
    "Jupiter": 4, "Venus": 12, "Saturn": 7,
}

# graha -> signs it owns
OWN_SIGNS = {
    "Sun": [5], "Moon": [4], "Mars": [1, 8], "Mercury": [3, 6],
    "Jupiter": [9, 12], "Venus": [2, 7], "Saturn": [10, 11],
    "Rahu": [], "Ketu": [],
}

# 27 nakshatras -> vimshottari lord (repeats Ketu..Mercury x3)
_VIM_ORDER = ["Ketu", "Venus", "Sun", "Moon", "Mars", "Rahu", "Jupiter", "Saturn", "Mercury"]
NAKSHATRAS = [
    "Ashwini", "Bharani", "Krittika", "Rohini", "Mrigashira", "Ardra",
    "Punarvasu", "Pushya", "Ashlesha", "Magha", "Purva Phalguni", "Uttara Phalguni",
    "Hasta", "Chitra", "Swati", "Vishakha", "Anuradha", "Jyeshtha",
    "Mula", "Purva Ashadha", "Uttara Ashadha", "Shravana", "Dhanishta", "Shatabhisha",
    "Purva Bhadrapada", "Uttara Bhadrapada", "Revati",
]
NAKSHATRA_LORD = {i + 1: _VIM_ORDER[i % 9] for i in range(27)}

# vimshottari dasha lengths in years
DASHA_YEARS = {
    "Ketu": 7, "Venus": 20, "Sun": 6, "Moon": 10, "Mars": 7,
    "Rahu": 18, "Jupiter": 16, "Saturn": 19, "Mercury": 17,
}

# short, plain-language significations (karakas), the vocabulary the renderer may use
KARAKA = {
    "Sun": "the self, vitality, confidence, father and authority",
    "Moon": "the mind, emotions, comfort, and the mother",
    "Mars": "energy, courage, drive, and conflict",
    "Mercury": "intellect, speech, learning, and commerce",
    "Jupiter": "wisdom, growth, fortune, teachers, and faith",
    "Venus": "love, beauty, relationships, art, and comfort",
    "Saturn": "discipline, patience, responsibility, time, and limitation",
    "Rahu": "ambition, obsession, the unconventional and the foreign",
    "Ketu": "detachment, intuition, spirituality, and the past",
}

HOUSE_MEANING = {
    1: "self, body, and the overall direction of life",
    2: "wealth, family, speech, and values",
    3: "courage, siblings, effort, and communication",
    4: "home, mother, emotional roots, and property",
    5: "creativity, children, intelligence, and romance",
    6: "work, health, service, and obstacles overcome",
    7: "partnership, marriage, and one-to-one dealings",
    8: "transformation, shared resources, and the hidden",
    9: "fortune, higher learning, dharma, and the father",
    10: "career, status, public life, and action in the world",
    11: "gains, networks, aspirations, and elder siblings",
    12: "loss, retreat, foreign lands, spirituality, and rest",
}

# category each graha most naturally speaks to (for grouping findings into sections)
GRAHA_CATEGORY = {
    "Sun": "essence", "Moon": "mind", "Mars": "career", "Mercury": "career",
    "Jupiter": "essence", "Venus": "relationships", "Saturn": "career",
    "Rahu": "essence", "Ketu": "spirit",
}


def opposite_sign(s: int) -> int:
    return ((s - 1 + 6) % 12) + 1
