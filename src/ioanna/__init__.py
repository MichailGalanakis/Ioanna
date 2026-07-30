"""Ioanna: an agentic investment system.

Three layers, in dependency order:

    governor    hard limits, deterministic, no LLM anywhere near it
    validation  tells a real edge from a lucky search
    journal     immutable pre-trade reasoning, honest post-trade accounting

None of them is a strategy. They are the frame a strategy has to survive.
"""

__version__ = "0.1.0"
