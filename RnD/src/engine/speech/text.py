"""Phrase text: steps, clocks, templates and the phrase entry of a speech policy."""
# ruff: noqa: E501

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable

    from engine.core.types import Item

__all__ = ["TextMixin"]


class TextMixin:
    """The text building methods of ``SpeechPolicy`` (composed with ``ContextMixin`` and ``WallsMixin``)."""

    cfg: dict[str, Any]
    STATE_WORDS: dict[str, str]

    @staticmethod
    def _n(steps: float) -> int:
        return max(1, int(round(steps)))  # noqa: RUF046

    @staticmethod
    def _join_clocks(items: Iterable[Item]) -> str:
        """Distinct clock texts of ``items``, left to right (by quarter index): "1", "12:15 and 1:30"."""
        cs = [txt for _, txt in sorted({(i.clock_q, i.clock_text) for i in items})]
        return cs[0] if len(cs) == 1 else ", ".join(cs[:-1]) + " and " + cs[-1]

    def _steps_txt(self, it: Item) -> str | None:
        """Steps as spoken ("1 step", "8"); None when the distance is unknown."""
        if it.steps is None or not math.isfinite(it.steps):
            return None
        n = self._n(it.steps)
        return "1 step" if n == 1 else str(n)

    def _fmt(self, template: str, **kw: Any) -> str:
        """Format a template; without steps the " in {steps}" part is left out (only for an unknown distance)."""
        tpl = self.cfg["templates"][template]
        if kw.get("steps") is None:
            tpl = tpl.replace(" in {steps}", "")
        return tpl.format(**kw)  # type: ignore[no-any-return]  # cfg is the untyped config block

    def _text(self, template: str, it: Item | None = None, label: str = "") -> str:
        if it is None:
            return self.cfg["templates"][template].format(label=label)  # type: ignore[no-any-return]  # cfg is the untyped config block
        if template == "approach" and it.fast and not it.own_ok:
            return self._fmt("approachFast", label=it.label, clock=it.clock_text, steps=None)
        if (
            template == "approach" and it.from_side and "approachSide" in self.cfg["templates"]
        ):  # v26.2.14: "vehicle approaching from right at 12:30 in 5"
            return self._fmt(
                "approachSide", label=it.label, clock=it.clock_text, steps=self._steps_txt(it), side=it.from_side
            )
        return self._fmt(template, label=it.label, clock=it.clock_text, steps=self._steps_txt(it))

    @staticmethod
    def _plural(label: str) -> str:
        return label if label.endswith("s") else label + "s"

    @staticmethod
    def _kind(it: Item, base: str) -> str:
        """Phrase template of a danger/final item (v26.1.11, review 4: "need to know if static, approaching or moving away").

        A mover measured approaching is "approaching" (v26.1.13: a person with the distance, a rider / vehicle without it: at
        their speed the number means nothing), a person walking away is "moving away", a person (rider: "stopped") measured
        standing is "standing". Anything whose motion is not measured keeps ``base`` ("{label} at {clock} in {steps}")."""
        approach = (
            it.moving is True and not it.receding and (it.approaching or (it.fast and it.role in ("danger", "final")))
        )
        if it.own_ok:  # v26.2.14: "approaching" only when its own motion says so (a parked vehicle is not approaching)
            approach = it.moving is True and it.approaching and not it.receding
        if approach and (it.ego_settled or it.own_fast):
            return "approach"  # v26.1.16: a rider / vehicle on an unsettled ego speed only if it closes faster than we could walk
        if not it.ego_settled:  # v26.1.15 (review 7): a ramping ego speed gives wrong states; the plain phrase, now
            return base
        if it.people and it.moving is True and it.receding:
            return "receding"
        if it.people and it.moving is False:
            return "stopped" if it.class_name == "rider" else "standing"
        return base

    def _entry(self, template: str, group: list[Item]) -> str:
        """One phrase entry for same-label items: "pole at 12 in 6", merged "person at 1 and 2 in 4", "poles at 11 and 1 in 8".
        The steps are those of the nearest item; a rider / vehicle "approaching" has none (``approachFast``)."""
        near = min(group, key=lambda i: i.steps if i.steps is not None and math.isfinite(i.steps) else math.inf)
        clocks = {i.clock_q for i in group}
        steps = self._steps_txt(near)
        if template in self.STATE_WORDS:
            if template == "approach" and near.fast and not near.own_ok:
                return self._fmt("approachFast", label=near.label, clock=self._join_clocks(group), steps=None)
            if (
                template == "approach"
                and len(group) == 1
                and near.from_side
                and "approachSide" in self.cfg["templates"]
            ):
                return self._fmt(
                    "approachSide", label=near.label, clock=self._join_clocks(group), steps=steps, side=near.from_side
                )
            if len(clocks) == 1 or template in ("approach", "receding"):
                return self._fmt(template, label=near.label, clock=self._join_clocks(group), steps=steps)
            return self._fmt(
                "multi",
                label=f"{near.label} {self.STATE_WORDS[template]}",
                clocks=self._join_clocks(group),
                steps=steps,
            )
        if template == "thin":
            label = self._plural(near.label) if len(group) > 1 else near.label
            return self._fmt("thinNotice", label=label, clocks=self._join_clocks(group), steps=steps)
        if len(clocks) == 1:
            return self._text(template, near)
        return self._fmt("multi", label=near.label, clocks=self._join_clocks(group), steps=steps)

    @staticmethod
    def _words(text: str) -> int:
        return len(text.replace(",", " ").split())
