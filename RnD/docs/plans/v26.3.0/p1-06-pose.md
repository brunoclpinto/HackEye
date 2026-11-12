# p1-06 engine.core.pose.DeadReckoner (new; no legacy change yet)

Goal: the dead-reckoning arithmetic of `collision._WorldMemory.advance` becomes a core class. This prepares the memory/worldmap cycle break (plan decision 4). The legacy code is NOT switched over here: `_WorldMemory` starts composing it in p2 memory, and `worldmap.PoseTracker` in Phase 3.

## API: `engine.core.pose`
```
class DeadReckoner:
    __init__(self, hold_s: float = 5.0)   # speed hold, same meaning as _WorldMemory.hold_s (cfg speedHoldSeconds)
    attributes: x: float = 0.0, y: float = 0.0, theta: float | None = None, speed: float | None = None,
                speed_t: float = -math.inf, hold_s: float
    advance(self, t: float, dt: float, speed: float | None, heading_deg: float | None,
            pose: tuple[float, float, float] | None = None) -> None
```
- `advance` is a **verbatim copy** of the pose part of `_WorldMemory.advance` (collision.py, `def advance`): the `heading_deg is None` early return, the speed latch, the pose override, and the integration with `mid`. Same statement order and the same float expressions.
- It must NOT include the `fx, fy` computation or the entries pruning; those stay in memory.
- Also add `class PoseLike(Protocol)` with the read-only attributes `x, y, theta, speed, speed_t, hold_s` (used later by `_Coast`).

## Tests (Sonnet): `tests/engine/core/test_pose.py`
- **Equivalence by construction:** for 3 seeded random sequences (numpy `default_rng(1..3)`, 300 steps each), feed the same `(t, dt, speed or None, heading or None, pose or None)` sequence to a legacy `collision._WorldMemory({}, True)` and to a `DeadReckoner(hold_s=5.0)`. After every step assert `x`, `y`, `theta`, `speed` and `speed_t` are **exactly equal** (`==`, not approx).
  - About 10 % of steps have `speed=None`, about 5 % `heading=None`, and about 5 % a `pose` tuple.
  - Include gaps longer than `hold_s` so the speed hold expires.
- Defaults right after `__init__`.
- `hold_s` respected: a custom `hold_s=1.0` against `_WorldMemory({"speedHoldSeconds": 1.0})`.

## Implementation (Sonnet)
- A new file only; `collision.py` is unchanged. The engine README "verbatim" rule applies to the copied statements.

## Done
- `check.sh --files src/engine/core/pose.py src/engine/core/__init__.py --tests tests/engine/core/test_pose.py` is green.
