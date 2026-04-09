"""Test LLM client with Sonnet — basic chat, JSON parsing, vision."""

import pytest


@pytest.mark.asyncio
async def test_basic_chat(llm_client):
    """LLM responds to a simple text prompt."""
    result = await llm_client.chat(
        role="agent",
        messages=[{"role": "user", "content": "Say 'test passed' and nothing else."}],
    )
    assert "content" in result
    assert len(result["content"]) > 0
    assert "usage" in result
    assert result["usage"]["input_tokens"] > 0
    assert result["usage"]["output_tokens"] > 0


@pytest.mark.asyncio
async def test_chat_json(llm_client):
    """LLM can return structured JSON."""
    result = await llm_client.chat_json(
        role="agent",
        messages=[{
            "role": "user",
            "content": 'Respond with exactly this JSON: {"status": "ok", "number": 42}',
        }],
        system="You must respond with valid JSON only. No other text.",
    )
    assert "parsed" in result
    assert result["parsed"]["status"] == "ok"
    assert result["parsed"]["number"] == 42


@pytest.mark.asyncio
async def test_vision_with_screenshot(llm_client, game_client):
    """LLM can analyze a game screenshot (multimodal)."""
    b64 = await game_client.screenshot_base64()

    result = await llm_client.chat(
        role="agent",
        messages=[{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                {"type": "text", "text": "What do you see in this Game Boy screenshot? Be brief."},
            ],
        }],
    )
    assert len(result["content"]) > 10, "Vision response should describe the screenshot"


@pytest.mark.asyncio
async def test_intro_agent_screen_detection(llm_client, game_client):
    """Intro agent's LLM call correctly identifies the screen type."""
    from pokemon_opus.agents.intro import INTRO_SYSTEM_PROMPT

    b64 = await game_client.screenshot_base64()
    result = await llm_client.chat_json(
        role="agent",
        messages=[{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                {"type": "text", "text": "Turn: 1\nParty count: 0\nHas pokedex: False"},
            ],
        }],
        system=INTRO_SYSTEM_PROMPT,
    )
    parsed = result["parsed"]
    assert "screen_type" in parsed, "Intro agent must return screen_type"
    assert parsed["screen_type"] in (
        "TITLE", "MENU", "DIALOG", "NAMING", "YES_NO",
        "OVERWORLD", "STARTER_CHOICE", "UNKNOWN",
    ), f"Unknown screen_type: {parsed['screen_type']}"
    assert "actions" in parsed, "Intro agent must return actions"
    assert isinstance(parsed["actions"], list)
