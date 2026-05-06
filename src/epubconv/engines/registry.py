"""Engine registry with plugin discovery via Python entry points.

Built-in engines are wired directly for fast startup. Third parties can
register additional engines under the ``epubconv.engines`` entry-point
group:

    [project.entry-points."epubconv.engines"]
    fanhuaji = "myplugin.fanhuaji:make_engine"

The registered object must be a callable matching the EngineFactory protocol:
``(source: str, target: str, **kwargs) -> Engine``.
"""
from __future__ import annotations

import importlib.metadata as md
from typing import Callable, Iterable

from .base import Engine
from .opencc_engine import OpenCCEngine

EntryPointGroup = "epubconv.engines"

EngineFactory = Callable[..., Engine]


def _opencc_factory(source: str, target: str, **kwargs) -> Engine:
    return OpenCCEngine(source, target, config=kwargs.get("opencc_config"))


_BUILTIN: dict[str, EngineFactory] = {
    "opencc": _opencc_factory,
}


def _discover() -> Iterable[md.EntryPoint]:
    try:
        return md.entry_points(group=EntryPointGroup)
    except TypeError:
        # Older importlib.metadata.entry_points() returned a dict.
        return md.entry_points().get(EntryPointGroup, [])


def list_engines() -> list[str]:
    """Return all known engine names (builtin + entry-point plugins), sorted."""
    names = set(_BUILTIN)
    for ep in _discover():
        names.add(ep.name)
    return sorted(names)


def get_engine(name: str, source: str, target: str, **kwargs) -> Engine:
    if name in _BUILTIN:
        return _BUILTIN[name](source, target, **kwargs)
    for ep in _discover():
        if ep.name == name:
            factory = ep.load()
            if not callable(factory):
                raise TypeError(f"engine plugin {name!r} is not callable: {factory!r}")
            return factory(source=source, target=target, **kwargs)
    raise ValueError(f"unknown engine: {name!r}; known: {list_engines()}")
