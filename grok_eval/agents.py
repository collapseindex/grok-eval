"""Agent definitions for the Grok 4.20 evaluation.

Mirrors Grok's native multi-agent architecture:
    Captain  -- coordinator
    Harper   -- research / facts
    Benjamin -- logic / math
    Lucas    -- creative / balance
"""

from __future__ import annotations

AGENTS = {
    "grok-captain": {
        "name": "Captain",
        "role": "coordinator",
        "system": (
            "You are Captain, the coordinator of a multi-agent team. "
            "Decompose tasks, delegate to specialists, resolve conflicts, "
            "and synthesize final answers. Be concise (2-3 sentences)."
        ),
        "action_cycle": [
            ("api_call", False),
            ("api_call", False),
            ("api_call", False),
            ("message", False),
            ("api_call", True),
        ],
    },
    "grok-harper": {
        "name": "Harper",
        "role": "research",
        "system": (
            "You are Harper, a research and facts specialist. "
            "Gather data, cross-reference sources, ground claims in evidence. "
            "Always cite reasoning. Be concise (2-3 sentences)."
        ),
        "action_cycle": [
            ("web_browse", False),
            ("search", False),
            ("api_call", False),
            ("file_write", False),
            ("web_browse", True),
        ],
    },
    "grok-benjamin": {
        "name": "Benjamin",
        "role": "logic",
        "system": (
            "You are Benjamin, a logic and math specialist. "
            "Perform rigorous step-by-step reasoning, verify code, "
            "and prove mathematical claims. Be precise (2-3 sentences)."
        ),
        "action_cycle": [
            ("terminal_exec", False),
            ("file_read", False),
            ("terminal_exec", False),
            ("file_write", False),
            ("terminal_exec", True),
        ],
    },
    "grok-lucas": {
        "name": "Lucas",
        "role": "creative",
        "system": (
            "You are Lucas, a creative and balance specialist. "
            "Provide divergent thinking, detect blind spots, "
            "optimize for human relevance. Be creative but concise."
        ),
        "action_cycle": [
            ("web_browse", False),
            ("message", False),
            ("api_call", True),
            ("message", False),
            ("spawn_agent", True),
        ],
    },
}

AGENT_IDS = list(AGENTS.keys())

AGENT_COLORS_HEX = {
    "grok-captain": "#00BFFF",
    "grok-harper": "#00FF7F",
    "grok-benjamin": "#FFD700",
    "grok-lucas": "#FF69B4",
}
