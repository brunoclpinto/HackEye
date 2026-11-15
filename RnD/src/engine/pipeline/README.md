# engine/pipeline -- the frame pipeline

The only engine package that may import other models (`BOUNDARIES.toml`: `engine = ["*"]`). It is being built up in
Phase 4: `run_collision` has moved here verbatim (p4-02) and is cut into stages next. It also holds the small glue helpers that
`run_collision` calls between stages. `run.py` imports the other engine models; `glue.py` only the stdlib and `engine.core`.

## API

| module | name | purpose | legacy |
|---|---|---|---|
| `glue.py` | `bottom_distance(ob, horizon, cam_h, gh, f)` | forward distance of the last image row on the centre column (the ground seen at the bottom); 0.0 on any error or non-finite value | `collision._bottom_distance` |
| `glue.py` | `hidden_fn(ob)` | `(fwd, right) -> bool` closure: the online map's cell there is hidden behind a building; None without a map | `collision._hidden_fn` |
| `glue.py` | `predict_velocities(items, wtracks, t, theta, pcfg)` | sets `pred_v` (velocity in our frame) on movers with a trusted, moving world track | `collision._predict_velocities` |
| `run.py` | `run_collision(grids, times, class_names, config, settings, motion=None, depth=None, window=None, sounds=None, worldmap_config=None, progress=None, sensors=None)` | per-frame hazards document and the speech/tone event list (the whole Lab logic, one function) | `collision.run_collision` (same object, no wrapper) |
| `glue.py` | `LAST_WORLD_TRACKS_MS` | list of the world-track step ms per frame of the last run (metrics tool only; not in the output) | `collision.LAST_WORLD_TRACKS_MS` |

`engine/pipeline/__init__.py` re-exports these four names (`__all__`). No function shares a name with a submodule.

## Inputs / outputs

- `bottom_distance`: `ob` is the online-map observer (attributes `geometry`, `geo`, `gh`, `gw`, `cam_h`) or None. With `geometry`
  it uses `groundgeom.ground_point` at the bottom row and the observer's camera height; otherwise the flat formula
  `cam_h * f / ((1 - horizon) * gh)` with the argument camera height.
- `hidden_fn`: `ob` needs `ray_hidden`, `orow`, `oc`, `cell`; cells outside the grid are not hidden.
- `predict_velocities`: only `moving` items that are not `lane_part` / `ghost`; skips untrusted, static or faster-than-`maxMoverMps`
  (default 12.0) tracks.
- `LAST_WORLD_TRACKS_MS` is one list object: `run_collision` assigns it with `[:] =` and never rebinds it.

## Config keys read

- `predict_velocities`: `maxMoverMps` from the `predictive` block, passed in as `pcfg`.

## Invariants

- `collision._bottom_distance`, `_hidden_fn`, `_predict_velocities` and `LAST_WORLD_TRACKS_MS` are the same objects as the engine
  names (`tests/engine/pipeline/test_glue.py`); `tools/worldtracks_metrics.py` reads `col.LAST_WORLD_TRACKS_MS`.
- Named rename only: `groundfuse.ground_point` became `groundgeom.ground_point` (the same function).

## run.py (p4-02)

- The body is the legacy text, AST-identical after the named renames: `groundfuse.Geometry` / `lateral_at` -> `groundgeom.*`,
  `groundfuse.resolved_mode` / `settings` -> `distfuse.*`, `groundfuse.Corrector` / `HorizonSigma` -> the engine classes,
  `sensor_lib.gps_step_length` -> `imu.gps_step_length`, `worldtracks.WorldTracks` -> `wt_mod.WorldTracks` (`tracks` is a local of the
  body), `worldmap.<x>` -> `wmap.<x>` (`from engine import worldmap as wmap`; the module is aliased so `run` binds no legacy module name).
  The two function-local `import worldmap` lines are gone. Underscore names are imported under their old aliases.
- One sanctioned added statement, first after the docstring: `if worldmap_config is None: worldmap_config = wm_config.default_config_loader()`.
  The facade `worldmap.py` installs the hook, so a patched `worldmap.load_config` is still seen; the two `... else wmap.load_config()`
  fallbacks stay (dead when called with None).
- `# noqa` only on three lines (B023, PLR1714, SIM114); no expression was rewritten. File-level `# ruff: noqa: E501` and `# mypy: ignore-errors` (the body is untyped legacy code; p4-06 removes it).
- `collision.run_collision is engine.pipeline.run.run_collision`; tests that monkeypatch `collision.run_collision` still work because
  the Lab calls it through the module.


## state.py / locals -> state (p4-03)

`state.py` has two dataclasses, `RunState` and `FrameState` (every field typed `Any`, default None, or a fresh `list` / `dict`
where the first assignment is an empty literal; fields in order of first assignment). `run_collision` builds `s = RunState()` first
(then `s.<param> = <param>` for every parameter, in signature order) and `f = FrameState()` first in every frame iteration. Every local of the
body became `s.<name>` or `f.<name>` by a mechanical rename (no statement moved, no expression changed). Left bare: the frame-loop
variable `i`, the targets of inner `for` loops and comprehensions and lambda parameters, and the reads of them inside the scope that
binds them. `tid`, `tr` and `k` are also plain locals (`tid = matches.get(ii)`, `tr = tracks[...]`, `k = scale.value`): those are
`f.tid` / `f.tr` / `f.k`. Classification rule: a name is `f` only if it is assigned inside the frame loop only, every read is
preceded by an assignment on all paths of the same frame (checked by a definite-assignment scan), and it is not read after the loop;
everything else is `s`. Line numbers refer to the pre-conversion `run.py` (p4-02).

| name | s/f | first assignment line | reason |
|---|---|---|---|
| `config` | s | signature | parameter |
| `depth` | s | signature | parameter |
| `window` | s | signature | parameter |
| `sounds` | s | signature | parameter |
| `progress` | s | signature | parameter |
| `sensors` | s | signature | parameter |
| `class_names` | s | signature | parameter |
| `settings` | s | signature | parameter |
| `motion` | s | signature | parameter |
| `worldmap_config` | s | signature | parameter |
| `grids` | s | signature | parameter |
| `times` | s | signature | parameter |
| `gw` | s | 268 | setup |
| `gh` | s | 268 | setup |
| `n` | s | 268 | setup |
| `ids` | s | 269 | setup |
| `f` | s | 270 | setup: the focal length in px (clashes with the FrameState variable, so it is s.f) |
| `roles` | s | 271 | setup |
| `trk` | s | 271 | setup |
| `geo_cfg` | s | 271 | setup |
| `lane_half` | s | 272 | setup |
| `labels` | s | 273 | setup |
| `parked_labels` | s | 274 | setup |
| `default_step` | s | 275 | setup |
| `lat_off` | s | 276 | setup |
| `ego_cfg` | s | 277 | setup |
| `step_len` | s | 279 | setup |
| `step_len0` | s | 284 | setup |
| `sl_cfg` | s | 285 | setup |
| `step_source` | s | 286 | setup |
| `step_windows_s` | s | 287 | setup |
| `step_info` | s | 288 | setup |
| `gps_cfg` | s | 289 | setup |
| `gps_scale` | s | 290 | setup |
| `dist_cfg` | s | 301 | setup |
| `_ah` | s | 303 | setup |
| `anchor_horizon` | s | 304 | setup |
| `depth_rows_frac` | s | 307 | setup |
| `source` | s | 308 | setup |
| `projection` | s | 309 | setup |
| `depth_rays` | s | 313 | setup |
| `depth_t` | s | 314 | setup |
| `depth_maps` | s | 314 | setup |
| `anchor_mode` | s | 315 | setup |
| `relative` | s | 320 | setup |
| `plane` | s | 321 | setup |
| `dscale` | s | 322 | setup |
| `gait_check` | s | 323 | setup |
| `anchor` | s | 324 | setup |
| `level_mode` | s | 337 | setup |
| `level_prior` | s | 340 | setup |
| `recalibrate` | s | 349 | setup |
| `anchor_rows` | s | 350 | setup |
| `gd_cfg` | s | 352 | setup |
| `item_lens_mode` | s | 356 | setup |
| `lens_all` | s | 357 | setup |
| `item_lens` | s | 358 | setup |
| `obj_mode` | s | 363 | setup |
| `gd_on` | s | 366 | setup |
| `surf_lut` | s | 367 | setup |
| `corrector` | s | 367 | setup |
| `hsig` | s | 367 | setup |
| `gd_geo` | s | 369 | setup |
| `win_bounds` | s | 380 | setup |
| `mser` | s | 383 | setup |
| `flow_hcum` | s | 384 | setup |
| `sser` | s | 385 | setup |
| `heading_source` | s | 390 | setup |
| `cadence_source` | s | 391 | setup |
| `stationary_source` | s | 392 | setup |
| `mt_s` | s | 394 | setup |
| `h_src` | s | 395 | setup |
| `c_src` | s | 395 | setup |
| `st_src` | s | 395 | setup |
| `flow_stat` | s | 396 | setup |
| `cad_s` | s | 397 | setup |
| `stat_s` | s | 400 | setup |
| `use_gps` | s | 413 | setup |
| `hcum_s` | s | 418 | setup |
| `gst` | s | 425 | setup |
| `ego` | s | 431 | setup |
| `surface` | s | 432 | setup |
| `crosswalk` | s | 433 | setup |
| `cw_name` | s | 434 | setup |
| `cw_class` | s | 435 | setup |
| `cw_marks` | s | 436 | setup |
| `scale` | s | 437 | setup |
| `policy` | s | 438 | setup |
| `world` | s | 439 | setup |
| `coast` | s | 441 | setup |
| `wtracks` | s | 442 | setup |
| `_op` | s | 445 | setup |
| `one_pose` | s | 448 | setup |
| `smap` | s | 449 | setup |
| `map_ms` | s | 466 | setup |
| `jump_cfg` | s | 467 | setup |
| `stable_s` | s | 468 | setup |
| `follow_cfg` | s | 469 | setup |
| `follow` | s | 470 | setup |
| `wfollow` | s | 472 | setup |
| `pass_cfg` | s | 473 | setup |
| `full_all` | s | 474 | setup |
| `mover` | s | 475 | setup |
| `blk_cfg` | s | 477 | setup |
| `blk_last_t` | s | 478 | setup |
| `blk_pos` | s | 478 | setup |
| `blk_run` | s | 478 | setup |
| `blk_kind` | s | 478 | setup |
| `blk_open` | s | 479 | setup |
| `blk_seen_t` | s | 479 | setup |
| `meas_hist` | s | 483 | setup |
| `meas_win` | s | 484 | setup |
| `reset_classes` | s | 485 | setup |
| `tree_cfg_run` | s | 486 | setup |
| `src_cfg` | s | 487 | setup |
| `map_mode` | s | 488 | setup |
| `src_counts` | s | 489 | setup |
| `under_rows` | s | 491 | setup |
| `under_gone_s` | s | 492 | setup |
| `under_min_w` | s | 493 | setup |
| `tracks` | s | 494 | setup |
| `next_id` | s | 495 | setup |
| `next_lane_part_id` | s | 496 | setup |
| `prev_group` | s | 499 | setup |
| `prev_left` | s | 500 | setup |
| `prev_right` | s | 500 | setup |
| `horizon` | s | 501 | setup |
| `h_state` | s | 502 | setup |
| `hz_cfg` | s | 503 | setup |
| `hz_source` | s | 504 | setup |
| `hz_off` | s | 505 | setup |
| `raws` | s | 512 | setup |
| `last_estimate_t` | s | 513 | setup |
| `first_t` | s | 514 | setup |
| `frames_out` | s | 515 | setup |
| `frame_collision` | s | 516 | setup |
| `frame_proximity` | s | 517 | setup |
| `events` | s | 518 | setup |
| `prev_t` | s | 519 | setup |
| `beep_run` | s | 520 | setup |
| `people_classes` | s | 521 | setup |
| `last_hard_pan_t` | s | 522 | setup |
| `prev_heading` | s | 523 | setup |
| `held_speed` | s | 526 | setup |
| `held_t` | s | 527 | setup |
| `ego_hist` | s | 528 | setup |
| `ego_hist_t0` | s | 531 | setup |
| `t` | f | 536 | assigned in the frame loop, always before its reads |
| `dt` | f | 537 | assigned in the frame loop, always before its reads |
| `grid` | f | 539 | assigned in the frame loop, always before its reads |
| `region` | f | 542 | assigned in the frame loop, always before its reads |
| `group` | f | 543 | assigned in the frame loop, always before its reads |
| `adopted` | f | 544 | assigned in the frame loop, always before its reads |
| `raw` | f | 552 | assigned in the frame loop, always before its reads |
| `warm` | f | 557 | assigned in the frame loop, always before its reads |
| `target` | f | 567 | assigned in the frame loop, always before its reads |
| `step` | f | 568 | assigned in the frame loop, always before its reads |
| `flow_heading` | f | 572 | assigned in the frame loop, always before its reads |
| `heading` | f | 572 | assigned in the frame loop, always before its reads |
| `cadence` | f | 572 | assigned in the frame loop, always before its reads |
| `stationary` | f | 573 | assigned in the frame loop, always before its reads |
| `ego_sens` | f | 574 | assigned in the frame loop, always before its reads |
| `stat` | f | 576 | assigned in the frame loop, always before its reads |
| `hcum` | f | 576 | assigned in the frame loop, always before its reads |
| `mt` | f | 576 | assigned in the frame loop, always before its reads |
| `cad` | f | 576 | assigned in the frame loop, always before its reads |
| `j` | f | 577 | assigned in the frame loop, always before its reads |
| `roll_now` | f | 586 | assigned in the frame loop, always before its reads |
| `pitch_now` | f | 586 | assigned in the frame loop, always before its reads |
| `walk_cadence` | f | 599 | assigned in the frame loop, always before its reads |
| `_roll` | f | 601 | assigned in the frame loop, always before its reads |
| `g_now` | f | 606 | assigned in the frame loop, always before its reads |
| `cw_change` | f | 613 | assigned in the frame loop, always before its reads |
| `k` | f | 618 | assigned in the frame loop, always before its reads |
| `geo` | f | 619 | assigned in the frame loop, always before its reads |
| `dmap` | f | 633 | assigned in the frame loop, always before its reads |
| `items` | f | 639 | assigned in the frame loop, always before its reads |
| `a_hz` | f | 644 | assigned in the frame loop, always before its reads |
| `a_cells` | f | 650 | assigned in the frame loop, always before its reads |
| `a_raw` | f | 650 | assigned in the frame loop, always before its reads |
| `pan_shift` | f | 660 | assigned in the frame loop, always before its reads |
| `matches` | f | 666 | assigned in the frame loop, always before its reads |
| `tid` | f | 668 | assigned in the frame loop, always before its reads |
| `tr` | f | 685 | assigned in the frame loop, always before its reads |
| `min_span` | f | 694 | assigned in the frame loop, always before its reads |
| `raw_closing` | f | 697 | assigned in the frame loop, always before its reads |
| `a_c` | f | 707 | assigned in the frame loop, always before its reads |
| `d_s` | f | 709 | assigned in the frame loop, always before its reads |
| `a_t` | f | 714 | assigned in the frame loop, always before its reads |
| `wit` | f | 726 | assigned in the frame loop, always before its reads |
| `r` | f | 729 | assigned in the frame loop, always before its reads |
| `prior_c` | f | 732 | assigned in the frame loop, always before its reads |
| `depth_scale_source` | s | 736 | read in a later frame before reassignment (loop-carried) |
| `c_source` | s | 736 | read in a later frame before reassignment (loop-carried) |
| `level` | f | 736 | assigned in the frame loop, always before its reads |
| `a_now` | f | 751 | assigned in the frame loop, always before its reads |
| `ds` | f | 752 | assigned in the frame loop, always before its reads |
| `dc_rep` | f | 755 | assigned in the frame loop, always before its reads |
| `sig_rows` | f | 757 | assigned in the frame loop, always before its reads |
| `sc_total` | f | 758 | assigned in the frame loop, always before its reads |
| `walls` | f | 760 | assigned in the frame loop, always before its reads |
| `d_use` | f | 772 | assigned in the frame loop, always before its reads |
| `y_l` | f | 783 | assigned in the frame loop, always before its reads |
| `raw_c` | f | 790 | assigned in the frame loop, always before its reads |
| `d_before` | f | 806 | assigned in the frame loop, always before its reads |
| `d_before_t` | f | 806 | assigned in the frame loop, always before its reads |
| `depth_distances` | f | 839 | assigned in the frame loop, always before its reads |
| `ego_speed` | f | 843 | assigned in the frame loop, always before its reads |
| `ego_win` | f | 858 | assigned in the frame loop, always before its reads |
| `ego_motion` | f | 862 | assigned in the frame loop, always before its reads |
| `ego_settled` | f | 863 | assigned in the frame loop, always before its reads |
| `turned` | f | 873 | assigned in the frame loop, always before its reads |
| `depth_scale_out` | f | 877 | assigned in the frame loop, always before its reads |
| `corridor_out` | f | 888 | assigned in the frame loop, always before its reads |
| `frame_in` | f | 892 | assigned in the frame loop, always before its reads |
| `seen_now` | f | 921 | assigned in the frame loop, always before its reads |
| `g` | f | 925 | assigned in the frame loop, always before its reads |
| `real` | f | 937 | assigned in the frame loop, always before its reads |
| `span` | f | 953 | assigned in the frame loop, always before its reads |
| `valid` | f | 955 | assigned in the frame loop, always before its reads |
| `c_rate` | f | 1006 | assigned in the frame loop, always before its reads |
| `along` | f | 1008 | assigned in the frame loop, always before its reads |
| `tau` | f | 1011 | assigned in the frame loop, always before its reads |
| `base` | f | 1037 | assigned in the frame loop, always before its reads |
| `weak_lost` | f | 1047 | assigned in the frame loop, always before its reads |
| `df_t` | f | 1100 | assigned in the frame loop, always before its reads |
| `df` | f | 1100 | assigned in the frame loop, always before its reads |
| `seen_tracks` | f | 1119 | assigned in the frame loop, always before its reads |
| `wt_out` | f | 1164 | assigned in the frame loop, always before its reads |
| `_t_wt` | f | 1166 | assigned in the frame loop, always before its reads |
| `path_change` | f | 1194 | assigned in the frame loop, always before its reads |
| `surface_known` | f | 1214 | assigned in the frame loop, always before its reads |
| `w_now` | f | 1225 | assigned in the frame loop, always before its reads |
| `speech` | f | 1235 | assigned in the frame loop, always before its reads |
| `blk` | f | 1252 | assigned in the frame loop, always before its reads |
| `th_` | f | 1269 | assigned in the frame loop, always before its reads |
| `bx` | f | 1270 | assigned in the frame loop, always before its reads |
| `by` | f | 1271 | assigned in the frame loop, always before its reads |
| `txt` | f | 1275 | assigned in the frame loop, always before its reads |
| `beeping` | f | 1306 | assigned in the frame loop, always before its reads |
| `near_soft` | f | 1335 | assigned in the frame loop, always before its reads |
| `speed_known` | f | 1340 | assigned in the frame loop, always before its reads |
| `episodes` | s | 1380 | setup |
| `tone_events` | s | 1380 | setup |
| `version` | s | 1386 | setup |
| `hazards_doc` | s | 1387 | setup |
