"""AgentValCon fallback agents: the last links of a necklace slot chain.

A necklace slot runs its primary pearl, then external alternatives, then at most
two AgentValCon fallbacks from this package (OPERATIONS_CHARTER 0절 "대체 원칙").
Every agent is a read-only lookup against a keyless public source. Results carry
the source, its license and required notice, the retrieval time and whether the
answer came from a live call, a cache or a local snapshot.

Nothing here registers catalog rows, routes or listings. The necklace runner
calls ``run(agent_id, arguments)``; the ops gate decides when a fallback goes live.
"""
from .agents import FallbackAgents, FallbackUnavailable, run, slot_output  # noqa: F401
from .catalog import SPECS, tool_spec  # noqa: F401

__all__ = ["FallbackAgents", "FallbackUnavailable", "run", "slot_output", "SPECS", "tool_spec"]
