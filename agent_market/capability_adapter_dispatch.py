"""Route reviewed adapters: Technical Documentation first, then the existing adapters.

capability_adapters.py is part of the research/news implementation digest, so new
adapters are added here instead of editing it.
"""
from . import capability_adapters as reviewed
from . import docs_capability_adapter as docs
from .capability_adapters import evidence_dataset  # noqa: F401


def profile(resource, contract, tool):
    value = docs.profile(resource, contract, tool)
    return value if value is not None else reviewed.profile(resource, contract, tool)


def arguments(resource, contract, tool, supplied, *, expected=None):
    if docs.profile(resource, contract, tool) is not None:
        return docs.arguments(resource, contract, tool, supplied, expected=expected)
    return reviewed.arguments(resource, contract, tool, supplied, expected=expected)


def normalize(resource, contract, tool, supplied, output, *, expected=None):
    if docs.profile(resource, contract, tool) is not None:
        return docs.normalize(resource, contract, tool, supplied, output, expected=expected)
    return reviewed.normalize(resource, contract, tool, supplied, output, expected=expected)
