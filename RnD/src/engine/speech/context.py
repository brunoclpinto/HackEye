"""Context memory of a speech policy: what was said, registered objects, adopted surfaces."""
# ruff: noqa: E501

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from engine.core.types import Item, ObjectMemory, Track

__all__ = ["ContextMixin"]


class ContextMixin:
    """The context-memory methods of ``SpeechPolicy`` (composed with ``TextMixin`` and ``WallsMixin``)."""

    memory: dict[str, float]
    pending_since: dict[str, float]
    thin_armed: bool
    first_summary: bool
    summary: bool
    summary_since: float | None
    forget_s: float
    world: ObjectMemory | None
    surface_pending: tuple[str, str] | None
    context_speak: set[str]

    def clear_context(self, t: float | None = None) -> None:
        """Forget what was said (a turn): the next context phrase is a fresh summary of the new view."""
        self.memory.clear()
        self.pending_since.clear()
        self.thin_armed = True  # a turn: a new view, "beware poles" may be said again
        self.first_summary = False
        self.summary, self.summary_since = True, t

    @staticmethod
    def _key(it: Item) -> str:
        """Memory key: the item's label family ("vehicle" and "parked car" are one thing), not its side."""
        return it.family or it.label

    def _known(self, key: str) -> bool:
        return key in self.memory

    @property
    def _mem(self) -> bool:
        """World memory is in charge (motion data available)."""
        return self.world is not None and self.world.active

    def _seen_before(self, it: Item, named: bool = True, approach: bool = False, danger: bool = False) -> bool:
        """The item is a remembered object (only with world memory). ``named``: it must have been announced by
        name, not merely covered by a "poles" notice that was never spoken for it. ``approach``: an object that was
        named but not as "approaching" is news again once it approaches (a person who was standing, or walking away).
        ``danger`` (v26.1.16, review 8, 10.9 s: collision and danger supersede notify-once): the question is for a danger / final
        phrase, which only an earlier danger / final phrase for the same object mutes; having been named as context or feature does not."""
        if danger:
            return self._mem and it.mem_id is not None and it.mem_danger and (it.mem_approach or not approach)
        return self._mem and it.mem_id is not None and (it.mem_named or not named) and (it.mem_approach or not approach)

    def _register(
        self,
        t: float,
        it: Item,
        tracks: dict[int, Track],
        named: bool = True,
        approach: bool = False,
        danger: bool = False,
    ) -> None:
        """Remember an announced object so that neither its fragments nor a later view of it are announced again."""
        if not self._mem:
            return
        if it.mem_id is None:
            it.mem_id = self.world.add(it, t, named)  # type: ignore[union-attr]  # _mem guarantees the world is set
            tracks[it.track_id].mem_id = it.mem_id
        e = self.world.entries[it.mem_id]  # type: ignore[union-attr]  # _mem guarantees the world is set
        e["named"] = e["named"] or named
        e["approach"] = e["approach"] or approach
        e["danger"] = e["danger"] or danger
        it.mem_named, it.mem_approach, it.mem_danger = e["named"], e["approach"], e["danger"]

    def observe_context(self, t: float, keys: set[str]) -> None:
        """Refresh memory for labels seen now; forget labels unseen for forgetAfterSeconds."""
        for k in keys:
            if k in self.memory:
                self.memory[k] = t
        for k in [k for k, seen in self.memory.items() if t - seen > self.forget_s]:
            del self.memory[k]

    def surface_adopted(self, old: str | None, new: str, surfaces: dict[str, Any], announce: bool = True) -> None:
        """A debounced surface change. Only road/rail matter: those are where the user must be told
        (starting on one, or moving into or out of one). Sidewalk <-> bike lane relabels stay silent, and
        so does any change the tracker could not back with crossing evidence (``announce`` False)."""
        if not announce:
            return
        announce_groups = set(surfaces.get("announceGroups", []))
        if new in announce_groups or (old is not None and old in announce_groups):
            self.surface_pending = (new, surfaces["groups"][new]["label"])

    def memory_if_spoken(self, t: float, it: Item) -> None:
        """A danger/final call that names a context label counts as having referenced it."""
        if it.label in self.context_speak:
            self.memory[self._key(it)] = t
