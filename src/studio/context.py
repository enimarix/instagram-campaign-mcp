"""
What the asset detail page shows next to the player (GOAL.md §3.2, §5.6): the idea
(hook, hypothesis, citations), the rights source, and the version chain.
"""

from __future__ import annotations

from typing import Any, Dict

from ..store import CampaignStore
from .publish import ai_generated


def asset_context(store: CampaignStore, asset_id: int) -> Dict[str, Any]:
    """-> {idea, source|None, parent|None, children: [...] oldest first, ai_label: published
    with Instagram's AI label}. KeyError: no asset."""
    asset = store.get_asset(asset_id)
    idea = store.get_idea(asset["idea_id"])
    parent_id = asset["parent_asset_id"]
    # ponytail: store has no "children of" read and store.py is a hot file; _select is
    # its own query helper. Move to a store method when a second caller needs it.
    children = store._select("SELECT * FROM assets", {"parent_asset_id": asset_id}, "id", 100)
    return {
        "idea": idea,
        "source": store.get_source(idea["source_id"]) if idea["source_id"] else None,
        "parent": store.get_asset(parent_id) if parent_id else None,
        "children": children,
        "ai_label": ai_generated(asset, idea),
    }
