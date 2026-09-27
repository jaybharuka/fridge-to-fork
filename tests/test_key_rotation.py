"""
Multi-key Gemini rotation (2026-09) — vision (step1_fridge_vision.py) and
text (step2_meal_planner.py) both rotate across GOOGLE_API_KEY/_2/_3 for a
given model before falling to a weaker model. Pure unit tests: the actual
Gemini call functions are mocked, zero network/quota cost.
"""

from unittest.mock import MagicMock, patch

from fridge_to_fork import step1_fridge_vision as vision
from fridge_to_fork import step2_meal_planner as text


# ---------------------------------------------------------------------------
# Key-pool construction
# ---------------------------------------------------------------------------

def test_vision_key_pool_reads_all_three_env_vars(monkeypatch):
    monkeypatch.setattr(vision, "VISION_API_KEYS", vision._dedupe([
        "a-key", "b-key", "c-key",
    ]))
    clients = vision._build_vision_clients()
    assert [label for label, _ in clients] == ["key1", "key2", "key3"]


def test_vision_key_pool_dedupes_identical_keys(monkeypatch):
    """GOOGLE_API_KEY_2 accidentally set to the same value as GOOGLE_API_KEY
    (e.g. copy-paste) must not create two clients for the same real key."""
    monkeypatch.setattr(vision, "VISION_API_KEYS", vision._dedupe([
        "same-key", "same-key", "c-key",
    ]))
    clients = vision._build_vision_clients()
    assert [label for label, _ in clients] == ["key1", "key2"]


def test_vision_key_pool_empty_when_no_keys_configured(monkeypatch):
    monkeypatch.setattr(vision, "VISION_API_KEYS", [])
    assert vision._build_vision_clients() == []


def test_text_key_pool_reads_all_three_env_vars(monkeypatch):
    monkeypatch.setattr(text, "TEXT_API_KEYS", text._dedupe(["a-key", "b-key", "c-key"]))
    clients = text._build_text_clients()
    assert [label for label, _ in clients] == ["key1", "key2", "key3"]


# ---------------------------------------------------------------------------
# Vision rotation order — model-first, key-second
# ---------------------------------------------------------------------------

def test_vision_tries_every_key_for_one_model_before_the_next_model():
    calls = []

    def fake_call(image_bytes, prompt, client, model):
        calls.append((model, client))
        raise RuntimeError("429 quota exhausted")

    clients = [("key1", "clientA"), ("key2", "clientB")]
    with patch.object(vision, "_call_gemini_vision", side_effect=fake_call):
        result = vision._call_gemini_vision_with_fallback(clients, b"img", "prompt")

    first_model = vision.VISION_MODEL_FALLBACK_CHAIN[0]
    second_model = vision.VISION_MODEL_FALLBACK_CHAIN[1]
    # both keys tried for the first model before the second model appears at all
    assert calls[0] == (first_model, "clientA")
    assert calls[1] == (first_model, "clientB")
    assert calls[2] == (second_model, "clientA")
    assert result == []  # every (model, key) failed


def test_vision_stops_on_first_success_without_trying_weaker_models():
    calls = []

    def fake_call(image_bytes, prompt, client, model):
        calls.append((model, client))
        first_model = vision.VISION_MODEL_FALLBACK_CHAIN[0]
        if model == first_model and client == "clientB":
            return [{"name": "tomato", "confidence": 90}]
        raise RuntimeError("429 quota exhausted")

    clients = [("key1", "clientA"), ("key2", "clientB")]
    with patch.object(vision, "_call_gemini_vision", side_effect=fake_call):
        result = vision._call_gemini_vision_with_fallback(clients, b"img", "prompt")

    assert result == [{"name": "tomato", "confidence": 90}]
    # succeeded on the FIRST (strongest) model's second key - never tried a weaker model
    first_model = vision.VISION_MODEL_FALLBACK_CHAIN[0]
    assert all(m == first_model for m, _ in calls)
    assert len(calls) == 2


def test_identify_ingredients_with_injected_client_bypasses_rotation_pool():
    """An explicitly-injected client (the existing DI/testing seam) must
    stay a single client, never expanded into the production key pool -
    this is also what keeps the eval harness's dedicated key isolated."""
    injected = MagicMock()
    with patch.object(vision, "_build_vision_clients", side_effect=AssertionError("should not build the pool")):
        with patch.object(vision, "_load_image", side_effect=FileNotFoundError("no such file")):
            # identify_ingredients() fails fast on a bad path either way; what
            # matters is _build_vision_clients was never called when a client
            # was injected.
            result = vision.identify_ingredients("nonexistent.jpg", client=injected)
    assert result.ingredients == []


# ---------------------------------------------------------------------------
# Text rotation order — model-first, key-second
# ---------------------------------------------------------------------------

def test_top_up_tries_every_key_for_one_model_before_the_next_model(monkeypatch):
    monkeypatch.setattr(text, "TEXT_API_KEYS", text._dedupe(["a-key", "b-key"]))

    calls = []

    def make_client(api_key):
        client = MagicMock()

        def generate_content(model, contents, config):
            calls.append((model, api_key))
            raise RuntimeError("429 quota exhausted")

        client.models.generate_content.side_effect = generate_content
        return client

    fridge = text.FridgeContents(ingredients=[text.Ingredient(name="egg")])
    meal = text.MealSuggestion(name="Omelette", description="", can_cook_now=True)

    with patch.object(text.genai, "Client", side_effect=make_client):
        result = text.generate_top_up_suggestions(fridge, meal, text.Decision.COOK)

    first_model = text.TEXT_MODEL_FALLBACK_CHAIN[0]
    second_model = text.TEXT_MODEL_FALLBACK_CHAIN[1]
    assert calls[0] == (first_model, "a-key")
    assert calls[1] == (first_model, "b-key")
    assert calls[2] == (second_model, "a-key")
    assert result == []
