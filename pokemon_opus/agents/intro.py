"""
Intro Agent — handles the Pokemon Blue intro sequence efficiently.

Uses RAM state for what it can detect reliably (dialog, party count),
and falls back to screenshot vision for screens RAM can't distinguish
(title screen vs naming screen vs overworld).

Naming screen navigation:
- D-pad (press_up/down/left/right) moves the cursor on the letter grid
- press_a selects a letter
- press_b deletes a letter
- press_start confirms the name

The letter grid layout (uppercase):
  Row 0: A B C D E F G H I
  Row 1: J K L M N O P Q R
  Row 2: S T U V W X Y Z
  Row 3: x ( ) : ; [ ] Pk Mn
  Row 4: - ? ! ♂ ♀ / . , ED

9 columns, 5 rows. "lower case" option at bottom toggles case.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)

INTRO_SYSTEM_PROMPT = """You are an AI playing Pokemon Blue. You are in the INTRO SEQUENCE (before gameplay starts).

You can SEE the game screen in the attached image. Your job is to identify what screen this is and respond with the correct actions.

## Screen Types

### 1. TITLE or COPYRIGHT screen
A mostly black or white screen with text like "Nintendo", "Game Freak", "Pokemon", or a Pokemon image.
Action: Press A or Start to advance.

### 2. MAIN MENU screen
Shows options like "NEW GAME" and possibly "CONTINUE".
Action: Press A to select NEW GAME.

### 3. DIALOG / OAK SPEECH
Professor Oak is talking. There is text at the bottom of the screen with a dialog box.
Action: Press A to advance the text.

### 4. NAMING SCREEN
This is the most important screen to identify correctly.
You will see:
- "YOUR NAME?" or "RIVAL's NAME?" at the top
- The name being typed (with an underscore cursor) near the top
- A grid of letters (A-Z in rows of 9)
- A small arrow (▶) pointing at one letter in the grid — this is your CURSOR
- "lower case" or "UPPER CASE" text at the bottom

When you see a naming screen:
- Look at what name has been typed so far (shown at the top)
- Look at where the cursor arrow (▶) currently is in the grid
- Decide what letter you want to type next
- Navigate the cursor to that letter using press_up/press_down/press_left/press_right
- Press A to select the letter
- When the name is complete, press Start to confirm

The letter grid positions (row, col starting from 0):
  Row 0: A(0,0) B(0,1) C(0,2) D(0,3) E(0,4) F(0,5) G(0,6) H(0,7) I(0,8)
  Row 1: J(1,0) K(1,1) L(1,2) M(1,3) N(1,4) O(1,5) P(1,6) Q(1,7) R(1,8)
  Row 2: S(2,0) T(2,1) U(2,2) V(2,3) W(2,4) X(2,5) Y(2,6) Z(2,7)
  Row 3: (symbols row)
  Row 4: (symbols row, ED at bottom-right)

### 5. YES/NO PROMPT
A small box with "YES" and "NO" options.
Action: Press A to select the highlighted option (usually YES).

### 6. OVERWORLD (gameplay)
You can see the game world — a room, town, or route. The player character is visible on the map. There is NO dialog box, NO letter grid, NO menu.
Action: Report this as OVERWORLD. Do NOT press A — that talks to nearby objects.

### 7. POKEMON SELECTION (starter choice)
Professor Oak's lab with 3 Poke Balls on a table, or a screen asking you to choose.
Action: Report this as STARTER_CHOICE.

## Response Format
Respond with a JSON object:
```json
{
    "screen_type": "TITLE|MENU|DIALOG|NAMING|YES_NO|OVERWORLD|STARTER_CHOICE|UNKNOWN",
    "reasoning": "What I see on screen (1-2 sentences)",
    "current_name": "letters typed so far (only for NAMING screen)",
    "cursor_position": "the letter the cursor is on (only for NAMING screen)",
    "desired_name": "the full name I want to type (only for NAMING screen)",
    "actions": ["press_a"]
}
```

## Naming Guidelines
- For YOUR NAME: Choose a cool, short name (max 7 characters). Examples: RED, ASH, BLUE, ACE, OPUS
- For RIVAL NAME: Choose a rival name. Examples: GARY, BLUE, RIVAL
- Names are UPPERCASE only in Pokemon Blue
- Max 7 characters
- Count your cursor movements carefully! The grid has 9 columns per row.

## Rules
- GO FAST. Speed matters more than perfection.
- For DIALOG/TITLE: spam press_a aggressively. Use sequences like: press_a, press_a, press_a, press_a.
- For NAMING: navigate to letters and type them. You can type MULTIPLE letters per turn — navigate to a letter, press A, navigate to the next letter, press A, etc. Don't waste time going one letter at a time.
- If you accidentally typed wrong letters (e.g., you mashed A and landed on the naming screen), just press B repeatedly to delete them, then start typing the correct name. It's not a big deal.
- If you see a screen you don't recognize, press A to try to advance it.
"""


# Grid layout for computing navigation
LETTER_GRID = {
    'A': (0, 0), 'B': (0, 1), 'C': (0, 2), 'D': (0, 3), 'E': (0, 4),
    'F': (0, 5), 'G': (0, 6), 'H': (0, 7), 'I': (0, 8),
    'J': (1, 0), 'K': (1, 1), 'L': (1, 2), 'M': (1, 3), 'N': (1, 4),
    'O': (1, 5), 'P': (1, 6), 'Q': (1, 7), 'R': (1, 8),
    'S': (2, 0), 'T': (2, 1), 'U': (2, 2), 'V': (2, 3), 'W': (2, 4),
    'X': (2, 5), 'Y': (2, 6), 'Z': (2, 7),
}


def compute_nav(from_letter: str, to_letter: str) -> List[str]:
    """Compute d-pad presses to navigate from one letter to another on the grid."""
    if from_letter not in LETTER_GRID or to_letter not in LETTER_GRID:
        return []

    fr, fc = LETTER_GRID[from_letter]
    tr, tc = LETTER_GRID[to_letter]

    actions = []
    # Vertical movement
    if tr > fr:
        actions.extend(["press_down"] * (tr - fr))
    elif tr < fr:
        actions.extend(["press_up"] * (fr - tr))
    # Horizontal movement
    if tc > fc:
        actions.extend(["press_right"] * (tc - fc))
    elif tc < fc:
        actions.extend(["press_left"] * (fc - tc))

    return actions


class IntroAgent:
    """Handles the intro sequence: title, naming, Oak's speech."""

    def __init__(self, config, llm_client, game_client=None):
        self.config = config
        self.llm = llm_client
        self.game = game_client
        self._last_screen_type = ""

    def is_intro_phase(self, gs) -> bool:
        """Check if we're still in the intro phase based on RAM state."""
        # Intro is over once we have a Pokemon in the party
        return len(gs.party) == 0 and not gs.has_pokedex

    async def decide(
        self, gs, raw_state: Dict[str, Any], game_client=None
    ) -> Tuple[List[str], str]:
        """Decide intro actions.

        Uses RAM state where reliable, vision where RAM can't help.
        Returns: (actions, reasoning)
        """
        client = game_client or self.game

        # Every turn uses vision — the LLM decides what to do each time
        screenshot_b64 = None
        if client:
            try:
                screenshot_b64 = await client.screenshot_base64()
            except Exception as e:
                logger.warning(f"Intro screenshot failed: {e}")

        if not screenshot_b64:
            # No screenshot available — safe fallback: press A
            return ["press_a"], "No screenshot, pressing A to advance."

        # Ask LLM to identify the screen and decide actions
        context = self._build_context(gs, raw_state)
        messages = self._build_messages(context, screenshot_b64)

        try:
            result = await self.llm.chat_json(
                role="agent",
                messages=messages,
                system=INTRO_SYSTEM_PROMPT,
            )
            parsed = result["parsed"]

            usage = result.get("usage", {})
            gs.total_tokens += usage.get("input_tokens", 0) + usage.get("output_tokens", 0)

            screen_type = parsed.get("screen_type", "UNKNOWN").upper()
            reasoning = parsed.get("reasoning", "")
            actions = parsed.get("actions", ["press_a"])

            self._last_screen_type = screen_type

            # Overworld/starter — not an intro screen, signal the orchestrator
            if screen_type in ("OVERWORLD", "STARTER_CHOICE"):
                return None, f"[INTRO] Detected {screen_type} — deferring to explore agent."

            # For naming screens, compute navigation for ALL remaining letters
            if screen_type == "NAMING":
                cursor_pos = parsed.get("cursor_position", "").upper().strip()
                desired_name = parsed.get("desired_name", "").upper().strip()
                current_name = parsed.get("current_name", "").upper().strip()

                if desired_name and current_name is not None and cursor_pos:
                    name_so_far = current_name.replace("_", "").replace(" ", "")

                    # If garbage letters from A-mashing, delete them first
                    if name_so_far and not desired_name.startswith(name_so_far):
                        deletes = ["press_b"] * len(name_so_far)
                        actions = deletes
                        reasoning = (
                            f"Clearing accidental letters '{name_so_far}' "
                            f"before typing '{desired_name}'."
                        )
                    elif len(name_so_far) < len(desired_name):
                        # Type all remaining letters in one go
                        remaining = desired_name[len(name_so_far):]
                        actions = []
                        current = cursor_pos
                        typed = []
                        for letter in remaining:
                            if letter in LETTER_GRID and current in LETTER_GRID:
                                nav = compute_nav(current, letter)
                                actions.extend(nav)
                                actions.append("press_a")
                                current = letter
                                typed.append(letter)
                            else:
                                break  # Unknown letter, let LLM handle it
                        if typed:
                            # After all letters, confirm with Start
                            if len(name_so_far) + len(typed) >= len(desired_name):
                                actions.append("press_start")
                            reasoning = (
                                f"Naming: typing '{''.join(typed)}' to complete "
                                f"'{desired_name}' (had '{name_so_far}')."
                            )
                    elif len(name_so_far) >= len(desired_name):
                        actions = ["press_start"]
                        reasoning = f"Name '{desired_name}' complete — confirming."

            # Validate actions
            actions = self._validate_actions(actions)
            return actions, f"[INTRO {screen_type}] {reasoning}"

        except Exception as e:
            logger.error(f"Intro agent error: {e}")
            return ["press_a"], f"Intro error: {e}. Pressing A."

    def _build_context(self, gs, raw_state: Dict[str, Any]) -> str:
        """Build context string with what RAM can tell us."""
        parts = []
        parts.append(f"Turn: {gs.turn_count}")

        player = raw_state.get("player", {})
        player_name = player.get("name", "")
        rival_name = player.get("rival_name", "")

        parts.append(f"Player name in RAM: '{player_name}' (may be stale/default during intro)")
        parts.append(f"Rival name in RAM: '{rival_name}' (may be stale/default during intro)")
        parts.append(f"Party count: {len(raw_state.get('party', []))}")
        parts.append(f"Has pokedex: {raw_state.get('flags', {}).get('has_pokedex', False)}")

        map_info = raw_state.get("map", {})
        parts.append(f"Map: {map_info.get('map_name', '?')} (id={map_info.get('map_id', '?')})")

        if gs.action_history:
            parts.append("\nRecent actions:")
            for entry in gs.action_history[-3:]:
                parts.append(f"  T{entry.turn}: {entry.actions} → {entry.reasoning[:80]}")

        return "\n".join(parts)

    def _build_messages(
        self, context: str, screenshot_b64: str
    ) -> List[Dict[str, Any]]:
        """Build multimodal message with screenshot."""
        return [{
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/png;base64,{screenshot_b64}",
                    },
                },
                {
                    "type": "text",
                    "text": context,
                },
            ],
        }]

    def _validate_actions(self, actions: List[Any]) -> List[str]:
        """Validate and sanitize action list."""
        valid_prefixes = ("walk_", "press_", "hold_", "wait_")
        validated = []
        for a in actions:
            if not isinstance(a, str):
                continue
            a = a.strip().lower()
            if any(a.startswith(p) for p in valid_prefixes):
                validated.append(a)
        return validated or ["press_a"]
