"""
Menu/Dialog Agent — handles dialog text advancement and menu navigation.
Mostly mechanical — minimal LLM usage.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class MenuAgent:
    """Mechanical handler for dialogs and menus. No LLM needed."""

    def __init__(self, config):
        self.config = config

    def handle_dialog(self, raw_state: Dict[str, Any]) -> List[str]:
        """Advance dialog text. Press A repeatedly until dialog clears."""
        # Fast text: hold B to speed up, then press A to advance
        return ["hold_b_120", "press_a", "press_a"]

    def handle_menu(self, raw_state: Dict[str, Any]) -> List[str]:
        """Handle start menu. Usually we want to close it and continue."""
        return ["press_b"]  # Close menu

    def heal_at_pokecenter(self) -> List[str]:
        """Button sequence to heal at a Pokemon Center.

        Assumes player is standing in front of the nurse.
        """
        return [
            "press_a",           # Talk to nurse
            "wait_60",           # Wait for greeting
            "press_a",           # "Would you like me to heal?"
            "wait_60",           # Wait for "Yes/No"
            "press_a",           # Select "Yes"
            "wait_60",           # Healing animation
            "wait_60",           # "Your Pokemon are fighting fit!"
            "press_a",           # Dismiss
            "wait_60",           # Final text
            "press_a",           # Close dialog
        ]

    def buy_item_sequence(self, slot: int = 0, quantity: int = 1) -> List[str]:
        """Button sequence to buy items at a Poke Mart.

        Args:
            slot: Item position in shop menu (0 = first item)
            quantity: How many to buy
        """
        actions = [
            "press_a",  # Talk to clerk
            "wait_60",
            "press_a",  # "May I help you?" -> "BUY"
            "wait_60",
        ]
        # Navigate to item slot
        for _ in range(slot):
            actions.append("press_down")
        actions.append("press_a")  # Select item

        # Set quantity (default is 1)
        for _ in range(quantity - 1):
            actions.append("press_up")
        actions.append("press_a")  # Confirm quantity

        actions.extend([
            "press_a",  # Confirm purchase
            "wait_60",
            "press_b",  # Exit shop
            "press_b",  # Exit dialog
        ])
        return actions

    def use_pc_heal(self) -> List[str]:
        """Button sequence to use the PC in a Pokemon Center to heal."""
        # In Gen 1, you can heal by depositing and withdrawing,
        # but the nurse is easier. This is a fallback.
        return self.heal_at_pokecenter()

    def open_bag_and_use_item(self, item_slot: int = 0) -> List[str]:
        """Open bag from start menu and use an item."""
        actions = [
            "press_start",   # Open menu
            "press_down",    # Navigate to ITEM
            "press_a",       # Open bag
        ]
        for _ in range(item_slot):
            actions.append("press_down")
        actions.extend([
            "press_a",       # Select item
            "press_a",       # USE
        ])
        return actions
