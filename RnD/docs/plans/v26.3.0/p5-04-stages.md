# p5-04 lab.stages

## Moves
- `models.py`: `_ModelCache` (`_torch_device` stays a method looked up on the class; tests patch it).
- `frames.py`: `MOTION_W`, `MOTION_H`, `_FrameReader`.
- `inference.py`: `_run_job(run_id, ctx)` (the `JobContext` replaces `_check_cancel` / `_finish`; otherwise verbatim).
- `collision.py`: `_build_worldmap`, `collision_pass`.
- `worldmap.py`: `worldmap_pass`.
Calls of `collision.*` / `worldmap.*` and the lazy flat imports (`models`, `depth`, `segmentation`, `egoflow`, `letterbox`, `profiles`,
`gpu_guard`, `torch`, `cv2`, `lab.sounds`) stay as today (p5-00 decision 2). `YOLO_CONFIG_DIR` is still set before the first model
load. `lab.stages` may import `lab.store` (and `engine.pipeline` / `engine.infer`, unused for now).

## Tests (Sonnet): `tests/lab/test_stages.py`
- Identity through `analysis`; `monkeypatch.setattr(collision, "run_collision", spy)` is seen by `collision_pass` (as
  `test_collision_runs.py` does); `monkeypatch.setattr(worldmap, "build", spy)` is seen by `worldmap_pass`.
- `_FrameReader` on a short synthetic video (cv2 writer in `tmp_path`): pin frame count and first-frame checksum from the legacy class.
- The existing lab tests pass unchanged.
