# p5-08 the two non-GPU skips (Verification, done criterion)

1. `tests/test_collision.py::test_outline_change_leaves_hazards_and_events_unchanged_vs_committed_v26_1_7` skips with "git history for
   v26.1.7 not available" (the check container has no `.git`). Replace the git dependency with a stored fixture: extract the v26.1.7
   files it reads from git once (`git show v26.1.7:...` on the host), store them under `tests/fixtures/v26_1_7/`, and make the test read
   the fixture. Its assertions stay.
2. `tests/test_collision_v26210.py::test_chest0004_at_zero_seconds_has_three_people` skips with "the Chest-center-0004 run is not
   present" (needs live Lab run 5fda5626e808). Replace the live-run dependency with a stored fixture of the frames it needs (build it with
   `tools/make_fixture.py` from the live Lab run of the same recording if one exists, else from the recording via a short CPU run of the
   inference; say which). Check whether its assertion still holds on the v26.2.14 baseline; if not, report before changing anything.

GPU skips (`test_depth_gpu` x4, `test_channel_order`) are run at the Phase 5 checkpoint with `HACKEYE_GPU_TESTS=1` on the GPU while the
live Lab is idle (no worker task).

## Tests
None new: the two tests must run (not skip) and pass in the check container.
