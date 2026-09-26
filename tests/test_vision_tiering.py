"""
Phase B tests — _assign_tier() rule table (step1_fridge_vision.py), pure
unit tests, zero Gemini calls, zero quota. See the plan's §3 rule table:
needs_confirmation always wins; a packaged item with candidate matches is
treated the same way even if the flag wasn't set; otherwise confidence
alone decides CONFIRMED/PROBABLE/UNCERTAIN.
"""

from fridge_to_fork.step1_fridge_vision import TIER_CONFIRMED, TIER_PROBABLE, TIER_UNCERTAIN, _assign_tier


def test_high_confidence_no_flags_is_confirmed():
    assert _assign_tier({"confidence": 90, "state": "fresh"}) == TIER_CONFIRMED


def test_confidence_exactly_at_confirmed_floor_is_confirmed():
    assert _assign_tier({"confidence": 80}) == TIER_CONFIRMED


def test_mid_confidence_is_probable():
    assert _assign_tier({"confidence": 70}) == TIER_PROBABLE


def test_confidence_exactly_at_probable_floor_is_probable():
    assert _assign_tier({"confidence": 60}) == TIER_PROBABLE


def test_low_confidence_is_uncertain():
    assert _assign_tier({"confidence": 55}) == TIER_UNCERTAIN


def test_needs_confirmation_flag_always_wins_even_at_high_confidence():
    """The core anti-fabrication guarantee: a model that says "I'm not sure
    what this specific product is" must never be overridden into CONFIRMED
    just because it also reported a high confidence number."""
    assert _assign_tier({"confidence": 99, "needs_confirmation": True}) == TIER_UNCERTAIN


def test_packaged_item_with_possible_matches_is_uncertain_even_without_the_flag():
    """Backstop for a response that fills in possible_matches (a genuine
    'I'm guessing between a few things' signal) but forgets to also set
    needs_confirmation — don't trust the flag alone either."""
    item = {"confidence": 92, "state": "packaged", "possible_matches": ["moong dal", "toor dal"]}
    assert _assign_tier(item) == TIER_UNCERTAIN


def test_packaged_item_without_possible_matches_is_not_forced_uncertain():
    """A packaged item the model IS confident about (empty possible_matches,
    no flag) should still be able to reach CONFIRMED — packaging alone
    isn't automatic uncertainty, only genuine ambiguity is."""
    item = {"confidence": 90, "state": "packaged", "possible_matches": []}
    assert _assign_tier(item) == TIER_CONFIRMED


def test_missing_confidence_defaults_to_uncertain():
    assert _assign_tier({}) == TIER_UNCERTAIN


def test_needs_confirmation_false_does_not_force_uncertain():
    assert _assign_tier({"confidence": 85, "needs_confirmation": False}) == TIER_CONFIRMED
