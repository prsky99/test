"""Dispatch only reviewed fixed adapters; never discover, approve or invoke.

The unchanged paper implementation is retained byte-for-byte in its own module
so existing signed paper workflows keep their original implementation digest.
The first-party profile has a separate source digest and explicit approval.
"""
from . import paper_capability_adapter as paper
from . import owned_capability_adapter as owned
from .paper_capability_adapter import PROFILE, ENDPOINT, TOOL, CONTRACT, MANIFEST, IMPLEMENTATION, evidence_dataset  # noqa: F401


def profile(resource, contract, tool):
    value=owned.profile(resource,contract,tool)
    if value is not None:return value
    value=paper.profile(resource,contract,tool)
    return {**value,'implementation_hash':IMPLEMENTATION} if value else None


def arguments(resource, contract, tool, supplied, *, expected=None):
    if owned.profile(resource,contract,tool) is not None:
        return owned.arguments(resource,contract,tool,supplied,expected=expected)
    return paper.arguments(resource,contract,tool,supplied,expected=expected)


def normalize(resource, contract, tool, supplied, output, *, expected=None):
    if owned.profile(resource,contract,tool) is not None:
        return owned.normalize(resource,contract,tool,supplied,output,expected=expected)
    return paper.normalize(resource,contract,tool,supplied,output,expected=expected)
