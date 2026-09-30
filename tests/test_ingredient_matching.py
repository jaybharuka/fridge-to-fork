import pytest
from fridge_to_fork.ingredient_matching import (
    same_ingredient, recipe_item_in_fridge, dedupe_detections,
)

SAME = [
    ("bell pepper", "red bell pepper"), ("capsicum", "bell pepper"),
    ("curd", "yogurt"), ("coriander leaves", "coriander"), ("dhania", "coriander"),
    ("coriander powder", "coriander powder"), ("tomatoes", "cherry tomato"),
    ("green chillies", "green chilli"), ("mint leaves", "mint"),
    ("potatoes", "potato"), ("curry leaves", "curry leaf"), ("garlic cloves", "garlic"),
    ("fenugreek leaves", "methi"), ("button mushrooms", "mushroom"), ("lauki", "bottle gourd"),
]
DIFFERENT = [
    ("green chilli", "green peas"), ("tomato", "tomato ketchup"), ("spring onion", "onion"),
    ("fresh cream", "fresh coriander"), ("milk", "coconut milk"), ("cream", "ice cream"),
    ("cheese", "cream cheese"), ("fresh coriander", "coriander powder"),
    ("tomato", "tomato puree"), ("red chilli", "green chilli"), ("butter", "peanut butter"),
    ("water", "coconut water"), ("flour", "gram flour"), ("curry leaves", "curry"),
    ("fenugreek leaves", "fenugreek seeds"), ("sweet corn", "sweet potato"),
    ("bottle gourd", "bottle"),
]

@pytest.mark.parametrize("a,b", SAME)
def test_same(a, b):
    assert same_ingredient(a, b) and same_ingredient(b, a)

@pytest.mark.parametrize("a,b", DIFFERENT)
def test_different(a, b):
    assert not same_ingredient(a, b) and not same_ingredient(b, a)

def test_paste_needs_every_part():
    assert recipe_item_in_fridge("ginger-garlic paste", ["ginger", "garlic"])
    assert not recipe_item_in_fridge("ginger-garlic paste", ["ginger"])

def test_dedupe_keeps_distinct_items():
    items = [
        {"name": "green chilli", "confidence": 90},
        {"name": "green peas", "confidence": 70},
        {"name": "red bell pepper", "confidence": 60},
        {"name": "bell pepper", "confidence": 85},
    ]
    names = [i["name"] for i in dedupe_detections(items)]
    assert names == ["green chilli", "bell pepper", "green peas"]


from fridge_to_fork.ingredient_matching import is_blocked_detection, passes_confidence

@pytest.mark.parametrize("name", ["sauce", "bottle", "steel container", "water",
                                  "turmeric", "coriander powder", "black pepper", "bay leaf"])
def test_blocked(name):
    assert is_blocked_detection(name)

@pytest.mark.parametrize("name", ["soy sauce", "chilli sauce", "bottle gourd", "fenugreek leaves",
                                  "lemon juice", "mango pickle", "bread", "leftover dal",
                                  "bell pepper", "green chilli", "coconut water", "curry leaves",
                                  "rice", "dal", "basmati rice"])
def test_not_blocked(name):
    assert not is_blocked_detection(name)

def test_meat_needs_high_confidence():
    assert not passes_confidence("chicken breast", 80)
    assert passes_confidence("chicken", 95)
    assert passes_confidence("paneer", 65)


# ---------------------------------------------------------------------------
# Gap fix (a): "fresh turmeric" (the root, a real visible fridge item) must
# not be blocked the way dried/powdered turmeric spice correctly is.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["fresh turmeric", "turmeric root", "raw fresh turmeric"])
def test_fresh_turmeric_not_blocked(name):
    assert not is_blocked_detection(name)

@pytest.mark.parametrize("name", ["turmeric", "dried turmeric"])
def test_dried_or_bare_turmeric_still_blocked(name):
    assert is_blocked_detection(name)
    # Not asserting "turmeric powder" here: separate, pre-existing gap
    # (unrelated to this fix) — its head noun is "powder", not "turmeric",
    # so is_blocked_detection() never matched it via PANTRY_ONLY's
    # "turmeric" entry in the first place.


# ---------------------------------------------------------------------------
# Gap fix (b): bare "rice"/"dal" are never outright blocked (a real, common
# fridge item — the old blacklist's mistake), but — deliberately, like
# meat/fish — need high confidence, since a bag/container of pale dry
# goods is easy to misidentify at a glance.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["rice", "dal", "basmati rice", "leftover dal", "lentils"])
def test_bare_rice_and_dal_not_outright_blocked(name):
    assert not is_blocked_detection(name)

@pytest.mark.parametrize("name", ["rice", "dal", "leftover dal", "lentils"])
def test_bare_rice_and_dal_need_high_confidence(name):
    assert not passes_confidence(name, 80)
    assert passes_confidence(name, 95)

def test_paneer_unaffected_by_dry_goods_bar():
    """Sanity check: the new high-confidence bar is scoped to rice/dal/
    lentil only, not every ordinary ingredient."""
    assert passes_confidence("paneer", 65)
