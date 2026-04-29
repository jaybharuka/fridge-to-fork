"""
Tests for step1_fridge_vision — all Claude API calls are mocked.
"""

import base64
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from fridge_to_fork.models import FridgeContents, Ingredient
from fridge_to_fork.step1_fridge_vision import (
    _is_url,
    _load_image_as_base64,
    identify_ingredients,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_API_RESPONSE = {
    "ingredients": [
        {"name": "eggs", "quantity": "6", "confidence": 0.95},
        {"name": "butter", "quantity": "half block", "confidence": 0.90},
        {"name": "cheddar cheese", "quantity": "1 pack", "confidence": 0.85},
        {"name": "milk", "quantity": "1 litre", "confidence": 0.80},
        {"name": "leftover pasta", "quantity": "some", "confidence": 0.60},
    ],
    "raw_description": "A well-stocked fridge with dairy items and some leftovers.",
}


def _mock_client(response_json: dict) -> MagicMock:
    """Build a mock anthropic.Anthropic client that returns a given JSON payload."""
    content_block = MagicMock()
    content_block.text = json.dumps(response_json)

    message = MagicMock()
    message.content = [content_block]

    client = MagicMock()
    client.messages.create.return_value = message
    return client


# ---------------------------------------------------------------------------
# Unit tests: _is_url
# ---------------------------------------------------------------------------

def test_is_url_with_http():
    assert _is_url("http://example.com/fridge.jpg") is True


def test_is_url_with_https():
    assert _is_url("https://example.com/fridge.jpg") is True


def test_is_url_with_path():
    assert _is_url("/home/user/fridge.jpg") is False


def test_is_url_with_bytes():
    assert _is_url(b"\xff\xd8\xff") is False


# ---------------------------------------------------------------------------
# Unit tests: _load_image_as_base64
# ---------------------------------------------------------------------------

def test_load_image_bytes():
    raw = b"\xff\xd8\xff\xe0"  # JPEG magic bytes
    b64, media_type = _load_image_as_base64(raw)
    assert base64.standard_b64decode(b64) == raw
    assert media_type == "image/jpeg"


def test_load_image_file(tmp_path: Path):
    img_path = tmp_path / "test.png"
    img_path.write_bytes(b"\x89PNG\r\n")
    b64, media_type = _load_image_as_base64(img_path)
    assert base64.standard_b64decode(b64) == b"\x89PNG\r\n"
    assert media_type == "image/png"


def test_load_image_missing_file():
    with pytest.raises(FileNotFoundError):
        _load_image_as_base64("/nonexistent/fridge.jpg")


def test_load_image_bad_type():
    with pytest.raises(TypeError):
        _load_image_as_base64(12345)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Unit tests: identify_ingredients (mocked API)
# ---------------------------------------------------------------------------

def test_identify_ingredients_from_bytes():
    client = _mock_client(SAMPLE_API_RESPONSE)
    raw_img = b"\xff\xd8\xff"  # fake JPEG bytes

    result = identify_ingredients(raw_img, client=client)

    assert isinstance(result, FridgeContents)
    assert len(result.ingredients) == 5
    assert result.raw_description == SAMPLE_API_RESPONSE["raw_description"]

    eggs = next(i for i in result.ingredients if i.name == "eggs")
    assert eggs.quantity == "6"
    assert eggs.confidence == pytest.approx(0.95)


def test_identify_ingredients_from_url():
    client = _mock_client(SAMPLE_API_RESPONSE)

    result = identify_ingredients("https://example.com/fridge.jpg", client=client)

    # Verify it called client.messages.create with a URL source block
    call_kwargs = client.messages.create.call_args.kwargs
    image_block = call_kwargs["messages"][0]["content"][0]
    assert image_block["source"]["type"] == "url"
    assert len(result.ingredients) == 5


def test_identify_ingredients_from_file(tmp_path: Path):
    client = _mock_client(SAMPLE_API_RESPONSE)
    img_path = tmp_path / "fridge.jpg"
    img_path.write_bytes(b"\xff\xd8\xff")

    result = identify_ingredients(img_path, client=client)

    call_kwargs = client.messages.create.call_args.kwargs
    image_block = call_kwargs["messages"][0]["content"][0]
    assert image_block["source"]["type"] == "base64"
    assert len(result.ingredients) == 5


def test_identify_ingredients_strips_markdown_fence():
    """Model sometimes wraps JSON in ```json ... ``` — must be handled."""
    wrapped = "```json\n" + json.dumps(SAMPLE_API_RESPONSE) + "\n```"
    content_block = MagicMock()
    content_block.text = wrapped
    message = MagicMock()
    message.content = [content_block]
    client = MagicMock()
    client.messages.create.return_value = message

    result = identify_ingredients(b"\xff\xd8\xff", client=client)
    assert len(result.ingredients) == 5


def test_identify_ingredients_empty_fridge():
    client = _mock_client({"ingredients": [], "raw_description": "Empty fridge."})
    result = identify_ingredients(b"\xff\xd8\xff", client=client)
    assert result.ingredients == []
    assert result.raw_description == "Empty fridge."


def test_identify_ingredients_confidence_sorting():
    """Ingredients with lower confidence should still be returned."""
    client = _mock_client(SAMPLE_API_RESPONSE)
    result = identify_ingredients(b"\xff\xd8\xff", client=client)
    confidences = [i.confidence for i in result.ingredients]
    assert all(0.0 <= c <= 1.0 for c in confidences)


def test_identify_ingredients_uses_correct_model():
    client = _mock_client(SAMPLE_API_RESPONSE)
    identify_ingredients(b"\xff\xd8\xff", model="claude-haiku-4-5-20251001", client=client)
    call_kwargs = client.messages.create.call_args.kwargs
    assert call_kwargs["model"] == "claude-haiku-4-5-20251001"
