import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pipeline import feeds

# Pan-regional shared-feed attribution must match a country as a whole word,
# not a bare substring (METHODOLOGY_REVIEW F2 / PATCH_PLAN P4).
NAMES = ["Oman", "Sudan", "Turkey", "Saudi Arabia", "Iran", "Palestine"]
ALIASES = {"UAE": "United Arab Emirates", "Gaza": "Palestine",
           "Tehran": "Iran", "Türkiye": "Turkey"}


def test_substring_false_positive_not_attributed():
    # "woman" and "Romania" both contain "oman" as a substring but are not Oman
    assert "Oman" not in feeds._match_countries("Saudi woman wins science prize", NAMES, ALIASES)
    assert "Oman" not in feeds._match_countries("Romania and Turkey sign defence pact", NAMES, ALIASES)


def test_south_sudan_not_attributed_to_sudan():
    assert "Sudan" not in feeds._match_countries("South Sudan ceasefire holds", NAMES, ALIASES)


def test_real_mentions_still_attributed():
    assert "Oman" in feeds._match_countries("Oman mediates regional talks", NAMES, ALIASES)
    assert "Sudan" in feeds._match_countries("Sudan army advances on the capital", NAMES, ALIASES)
    assert "Turkey" in feeds._match_countries("Romania and Turkey sign defence pact", NAMES, ALIASES)


def test_aliases_resolve_to_country():
    assert "Palestine" in feeds._match_countries("Gaza strikes reported overnight", NAMES, ALIASES)
    assert "Iran" in feeds._match_countries("Tehran responds to new sanctions", NAMES, ALIASES)
