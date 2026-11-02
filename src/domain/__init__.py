"""Assessment and planning rules, independent of providers and storage."""

from __future__ import annotations
from collections.abc import Mapping
from types import MappingProxyType


def freeze(value):
    """Detach and recursively protect JSON-shaped source metadata."""
    if isinstance(value, Mapping):
        return MappingProxyType({key: freeze(item) for key, item in value.items()})
    if isinstance(value, (tuple, list)):
        return tuple(freeze(item) for item in value)
    return value


def thaw(value):
    """Return a detached JSON-boundary value."""
    if isinstance(value, Mapping):
        return {key: thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw(item) for item in value]
    return value


class DomainError(ValueError):
    """A proposed domain state violates an assessment invariant."""
