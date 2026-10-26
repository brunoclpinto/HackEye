# common/

Cross-implementation shared state for HackEye — currently **data, not code**.

## Status

- **`config/`** — tunable parameters and the safety mapping. The safety
  mapping started as a straight port of
  `Apple/Models/Domain/{BusDetector,BusTracker,SafetySegmentation}.swift`'s
  19-class Cityscapes table, but `RnD/` has since moved to a model trained on
  124-class Mapillary Vistas v2.0, so `config/safety_mapping.json` now
  reflects that instead (see its own `_source` field).
  `config/safety_mapping_hackeye48.json` is the same table collapsed to the
  48-class HackEye merge (`HackEye-Models/.../merges/HackEye26.1-48.yaml`) used by
  `Yolo26m-sem-HackEye26.1-48-1280.pt`; `RnD/` picks whichever mapping's class
  names match the loaded checkpoint. Consumed today by
  `RnD/` (Python). **Not yet consumed by the Swift app** — the Swift
  `Config` structs and `CityscapesMapping.classes` still hold their own
  hardcoded Cityscapes copies, now diverged from this file. Wiring the app
  to load these JSON files at runtime, and deciding whether/how to migrate
  it to Vistas too, is the remaining half of this step; it wasn't done as
  part of this change because it touches `Apple/` and can't be
  build-verified from this machine. Until that's done, a value changed in
  one place does not automatically apply to the other — treat `config/` as
  the source of truth to copy from, not yet a single source of truth
  enforced by the code.
- **`fixtures/`** — empty. Meant to hold raw model-output tensors dumped from
  the Apple CLI plus their expected post-processing results, for the
  cross-implementation parity check described in `RnD/README.md`. Needs a Mac
  to populate.
- **`core/`** — empty, deliberately. A shared *algorithm* implementation
  (tracking, segmentation post-processing, geometry) is a real prospect if
  the Python R&D rig and the Swift app end up maintaining the same logic
  long-term, but building it now would be guessing at an architecture before
  the pipeline has been run against real footage. See the plan doc for the
  reasoning and the proposed Rust/UniFFI approach if this stage is reached.

## Why data first, not code

Extracting a shared *algorithm* core (Stage 2 in the plan) means picking a
language and FFI story serving two consumers that don't exist yet in a
committed sense — R&D here is Python, production is Swift, and there's no
second shipped platform. Extracting the *parameters* costs almost nothing and
pays off immediately: it's the difference between tuning a threshold once vs.
tuning it twice and hoping the two match.
