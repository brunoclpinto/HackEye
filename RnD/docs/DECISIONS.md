# HackEye RnD — decision log

One entry per version: what prompted it (usually the user's review in the Lab), the decisions made with the user, the implementation choices and deviations workers made, known limitations, and the measured result. The current rules live in [`../lab/CONTRACTS.md`](../lab/CONTRACTS.md); this file explains **why** they are what they are.

**Ground truth.** The user's Lab reviews are kept as regression fixtures in [`../tests/fixtures/`](../tests/fixtures/) (`4929_review{1,2,3}.{npz,json}`) and replayed by `tests/test_collision_regression.py`. A version bump wipes the Lab, so the fixtures are the permanent record.

**How we work** (user decisions, standing):
- **Versioning:** `v<YY>.<major>.<minor>`, with the minor dropped when 0. v26.1 is collision detection, and v26.1.x are improvements within it. `RnD/VERSION` holds the current version.
- **Fresh Lab per version:** a version change wipes Lab runs and reviews (no archive). Video proxies and per-recording settings are kept. Reviews are therefore saved as fixtures *before* bumping.
- **Roles:** the main session (Opus) plans, writes contracts, reviews and verifies. Implementation is done by Sonnet subagent workers; every plan states a worker recommendation. Workers never commit. Commits and pushes happen only when the user asks.
- **Less is more:** context first, then only potential dangers. Every addition to speech must earn its place.
- **Planning first:** features and changes are planned and approved before being built. Plans are kept in [`plans/`](plans/) (from v26.1.7 on).

---

## v26.1 — HackEye Lab + collision detection (commit `cc9143e`)
**Prompt.** Research how HackEye should behave in production, on a headless GPU box: pick footage, run the logic, watch overlays and hear audio.

**Decisions with the user:**
- **Analyse then play:** analysis can't keep up live. The pipeline does ~6 fps (later ~20 ms/frame segmentation-only) against 24 fps footage.
- **Access over Tailscale** (`tailscale serve`, tailnet-only HTTPS), with an SSH tunnel as fallback.
- **Bus detection dropped;** v26.1 is collision warnings only.
- **Collision risks:** static obstacles and moving obstacles. Trip hazards came later.
- **Audio:** a short phrase in **clock notation** (12 ahead, 9 left, 3 right, whole hours), then panned beeps that speed up as the obstacle nears.
- **Camera:** chest mount by default, overridable per recording (head, handheld).

**Implementation.**
- **Backend:** FastAPI with recordings (GoPro chapters grouped into one timeline), 960p H.264 proxies, a GPU job queue, frame-aligned 240-px class grids and mask PNGs.
- **Frontend:** vanilla JS with a canvas overlay synced through `requestVideoFrameCallback`, a WebAudio scheduler and `speechSynthesis`.
- **Collision logic:** fixed corridor trapezoid, flat-ground proximity, pinhole bearing to clock position, IoU tracking.

**Verified.** The proxy matches the original footage frame-exactly across chapter boundaries, and overlays line up on rendered frames.

**Found in testing.** 32 phrases in 60 s. A wall *alongside* the path and parked cars clipped the corridor's edge, and segmentation fragmented them into many tracks.

## v26.1.1 — path-aware, step-based, "less is more" (commit `55271ca`)
**User feedback:**
- Use a real boundary of the walking region.
- Say context once, and don't repeat it unless the path changes.
- Warn about dangers within 10 steps.
- Estimate speed and steps to features.
- Less is more.
- After the danger phrase, beeps plus **one final call at ≤ 3 steps**.
- Walking or running only.
- Estimate body parameters where possible.

**Decisions:**
- **Path change** = a turn of more than 20° held for 2 s, a surface change, or the item unseen for 30 s. The user skipped the question, so this was Claude's call.
- **Defaults:** step 0.7 m and chest camera height 1.3 m, estimated where possible.

**Implementation.**
- **Walking region:** grown from a seed surface; a horizon estimate from the region's vanishing point.
- **Distance:** ground-plane distance, with steps = distance × cadence / speed, so camera height cancels out.
- **Ego-motion:** a track from phase correlation at full fps (analysis version 2).
- **Roles:** context, feature and danger.

**Found during review and fixed before commit:**
- **Cadence:** the chest camera's dominant bob is the **stride** (~1.07 Hz); the step is its 2nd harmonic (~2.15 Hz). Cadence detection was made stride-aware.
- **False "approaching" calls:** horizon jitter near the vanishing point faked approach speeds (a parked car "approaching at 5–7 m/s"). Fixed with a common-horizon history.
- **Along-path items:** a median or curb running along the path is never a feature or danger.
- **Less context:** manholes and vegetation were dropped from speech.

**Result.** 32 → 6 phrases on the same clip.

**Known limitation.** Absolute metres read about 2× low, because the default HFOV (118°, Wide) probably doesn't match the footage. Steps are unaffected.

## v26.1.2 — speech review panel (commit `f984e9a`)
**Prompt.** The user wants to judge each phrase while watching (correct / incorrect / remove, with a note) and add missed ones, as input for planning.

**Decisions:**
- "Remove" means "should not be said": kept in the data, struck through.
- The extra info is a free-text note.

**Implementation.**
- **Storage:** reviews are stored **per recording** (they survive re-analysis). Each verdict snapshots its event plus `runId` and `collisionVersion`.
- **Matching:** a verdict is tied to its event by `(runId, version, t, text)`.
- **Export:** enriched with what the system saw at that moment, for analysis.

## v26.1.3 — add form follows the paused playhead, auto-fill (commit `2286926`)
**Prompt.** When paused, use the playhead time automatically. Pre-fill the phrase from what's detected.

**Implementation.** Auto-fill cycles through the frame's detected items, including ones the system ignored, because missed warnings are usually things it saw but discarded.

## v26.1.4 — version-scoped Lab, one analysis per video, cancel (commit `617149e`)
**Decisions:**
- Each new version starts the Lab fresh: wipe runs and reviews, **no archive**, keep proxies and settings.
- The wipe is automatic, through `RnD/VERSION` plus a marker file, checked at startup and by a 30 s watcher.
- It never wipes on doubt.
- One analysis per recording at a time (409). Progress is shown when a video is selected. Cancel is supported. A version change kills running analyses first.

## v26.1.5 — first user review (commit `6616b0a`, fixtures `4929_review1`)
**Review 1:**
- **Expected:** a grouped context summary at the start ("Obstacle at 12, Building at 2"), and "Vehicle at 11, building at 1" after a turn.
- **Wrong:** a static vehicle not on a collision course announced as danger; a parked car re-announced; a one-frame false "person, 3 steps" without a location.

**Lab bugs reported:** range should default to the full length, audio on by default, auto-fill broken, the 2nd added phrase got the 1st one's time, added speech not played back.

**Root causes found.**
- **Large runs:** a full-length run's `hazards.json` is **118 MB**, and the page downloaded it whole. Windowed endpoints, gzip and a ±90 s client window replaced it.
- **The add-form time bug:** proven in a real browser. The slow run load re-applied the stale URL time (`#t=0.2`) after the user had moved, and dragged the add form with it.

**Collision decisions:**
- confirmation over ≥ 2 frames;
- final calls include the clock;
- non-moving items are danger only with their contact point in the lane;
- context memory keyed by label family (vehicle = parked car);
- grouped context phrases;
- walls, fences and guard rails spoken as "obstacle".

**Also added.** A Playwright + Chrome E2E harness. It reproduced 9 of the 12 Lab bugs on the old code before they were fixed.

**Result.** Full run 500 → 295 phrases. All three reviewed false calls are gone.

## v26.1.6 — second review: beeps in the review, parking-style beeps (commit `40729a1`, fixtures `4929_review2`)
**Review 2:**
- **Expected:** crosswalks announced as landmarks with direction and steps; "curb at 12 in 10, beware poles"; people tracked as movers and warned sooner.
- **Wrong:** context items too far away; a parked car that wasn't parked; a "road" surface flicker.
- **Phrasing:** "person approaching at 12", with no "o'clock".

**Lab request:** beeps reviewable, renamed **Notification review**. Beeps like a car parking sensor, collisions only.

**Diagnosis.** Metres were 2–4× too small (ego 0.3–0.7 m/s at 2.1 Hz), and steps jumped (25.9 → 12.7 in 0.2 s).

**Decisions and implementation.**
- **Gait calibration:** the scale k = cadence × 0.70 m prior / measured speed, over a long window. Walking speed now reads 1.4–1.5 m/s, and step jumps of more than 30% fell from 21% to 1.4%.
- **Context:** only when near (≤ 8 steps, ≤ 3 m lateral).
- **People:** treated as moving, never "stationary" (worker decision: their motion often can't be measured). A wider zone, with `movingLaneHalfWidthM` 3.0 and `movingCollisionHalfWidthM` 1.5.
- **Crosswalks:** landmarks, announced once per crossing, with a stricter repeat override (20 s, 14 steps).
- **Poles:** "beware poles" once per cluster, re-armed after 8 s without poles or a turn.
- **Features:** repeat suppression.
- **Surface:** a change needs 8 s persistence plus a crossed curb or crosswalk.
- **Phrasing:** "X at 12 in 6", with same-label grouping.
- **Beeps:** constant 880 Hz, the interval shrinking with steps, continuous at ≤ 1.5 steps. Collision tracks only. `beeps` episode events, **one track per episode**, so ⊘ in the review can silence exactly that episode.

**Result.** Speech 295 → 276. 40 beep episodes, all on collision tracks.

**Known weaknesses.** Calls arrive 1.5–3 s late (2-frame confirmation and fragmented detections). More person calls. The first ~17 s are uncalibrated.

## v26.1.7 — third review: object permanence (commit `5ff8e98`, fixtures `4929_review3`, plan [`plans/v26.1.7.md`](plans/v26.1.7.md))
**Review 3:** 33 judgements, **27 ✓, 0 ✗, 0 missing, 6 ⊘**.
- **Five of the ⊘ were repeats** of the same real object: a re-detection after fragmentation or a turn, the same crosswalk from a new angle, the same person.
- **The sixth** was a "road" flicker at 199 s while still on the sidewalk.
- **Note:** "always add position and distance to any announced object".

**Decisions with the user:**
- Final calls only for objects **never named** (otherwise beeps carry proximity).
- Surface: **stricter logic now**; the model-level fix comes later.
- Objects stay known **until passed**.

**Implementation:**
- **World memory by dead reckoning:** cadence × step length along the motion heading. Each announced object is remembered by label family and ground position, matched within 2.5 m + 10% of its distance, and forgotten when behind or beyond 30 m.
- **Phrases:** position and distance on every object phrase ("poles at 11 and 1 in 8").
- **Surface:** a change only when an edge **at least 0.15 of the frame wide** passes under the user, with 70% of a 10 s window plus 8 s persistence. The first surface is adopted silently.

**Worker deviations (accepted):**
- **The memory doesn't change pacing:** it filters at emit time, and the speech state machine runs unchanged. Otherwise suppressed phrases shifted later confirmed ones by more than 1.5 s.
- **Per-label context memory kept** as a second gate. Without it, new unreviewed announcements appeared.
- **Static objects keep their first announced position.** Refreshing let a long curb or wall drag its memory entry along forever.
- **People** match only on a hand-off within 1 s. A person first named without "approaching" is news once when later measured approaching.
- **Surface rules are stricter than planned.** The width test and 8 s persistence are kept on top of the 70% window. The literal spec gave 28 surface events instead of 7.
- **Approach phrases** also get "in N".

**Result.** On the full run all **27 ✓ kept, 6 ⊘ gone**. Speech 276 → 236. Beeps unchanged (40 episodes, 93 tones). The full-run regression runs behind `HACKEYE_FULL_RUN=1`.

**Known limitations:**
- **Dead-reckoning drift:** speed is assumed from cadence × 0.70 m, so it is wrong for running or a non-default stride, and heading drifts. Dense rows of poles or people merge into one memory entry.
- **Surface calls:** silent more often, and real changes come about 8 s late.

**Open / candidates:**
- A model-level fix for sidewalk-vs-road confusion: fine-tune in HackEye-Models on the user's footage.
- ~~HFOV / lens mode of the footage~~: the user confirmed it is **Wide** (2026-10-17), so the 118° default is correct. The low absolute metres come from elsewhere; the gait scale corrects them.
- Earlier detection (lower confirmation latency) without bringing back one-frame false alarms.

## Spec consolidation (docs only, after v26.1.7)
`lab/CONTRACTS.md` was rewritten as one current-rules spec, verified against the code. History moved here. Where the old, layered text and the code disagreed, the **code won**. Notable points:
- **Surface:** a change needs a 70% majority over 10 s, **and** 8 s of uninterrupted persistence, **and** pass-under evidence (`passUnderMinWidth` 0.15, within a 10 s lookback). `debounceSeconds` now only gates how long context waits for the first surface. The first surface is adopted silently.
- **People:** never stationary. A person beside the path (≤ 3.0 m) is a danger without collision: speech, but no beeps and no final call. Beeps need ≤ 1.5 m or an approach.
- **Final call:** muted by *any* matching world-memory entry. The muted slot still consumes pacing.
- **World memory:** only active with a motion track.
  - Static entries keep their position.
  - Movers match only within a 1 s takeover; owner adoption takes 3 s.
  - Entries seen within the last 1 s are never forgotten.
  - "poles" notices store unnamed entries.
  - "Named but not approaching" doesn't silence an approach phrase.
- **Step length:** never estimated from footage. It is the 0.70 m prior or the per-recording value, and `ego.stepLengthRangeM` is unused. The gait calibration corrects the *distance scale*, not the step length.
- **Roles:** `featureMinLaneCover` is 0.2.
- **Thresholds in force but missing from the old spec:**
  - `contextMinAreaFraction` 0.003, `minObstacleAreaM2` 0.08;
  - a 1.5 s warm-up and a 0.5 s minimum track age;
  - a 5 s danger-label cooldown and a 1.0 s priority gap;
  - the thin-notice re-arm and the feature label gap (with the crosswalk override);
  - the people-motion wait.
- **Spoken context labels:** obstacle, building, vehicle, parked car. All barrier-type classes are "obstacle", so wall, fence and vegetation are never spoken.
- **Horizon:** rows clamped to the image border are excluded from the fit. The first 1.5 s uses the mean of the raw estimates, and a failed estimate is held for 3 s.

**Small open items found:**
- The HUD doesn't show the gait scale (`ego.scale` / `scaleSource` are in hazards.json).
- `static/js/autofill.js` still has stale fallback templates with "o'clock". Harmless, since the real templates are fetched from the config.

## v26.1.8 — contours, classes & safety-levels panel, self-contained E2E (plan [`plans/v26.1.8.md`](plans/v26.1.8.md))
**Requests:**
- Draw items as **contours that follow the mask edges** instead of bounding boxes.
- A **checkbox list of model classes**, each with a dropdown of its safety level.
- A **list of safety levels** with editable colour and opacity.
- **Two Save buttons**: one for class levels, one for level colours.

**Decisions with the user:**
- The panel is **Lab view only**. It changes how the mask is painted and never touches the shared safety mapping or collision behaviour.
- A class checkbox = **show/hide in the mask overlay**.
- The Save buttons store the view **on the Lab server** (`debug/lab/display/`), shared by laptop and phone. It survives version wipes, like recording settings.

**Implementation:**
- **Outlines:** each item with a role carries an `outline`. It is traced on the item's own component (pixel corners, so its extent equals the bbox), with Douglas–Peucker simplification to ≤ 32 points; concavities are kept. Role `none` items get none, to keep hazards.json small: +10% on the role-heavy fixtures.
- **Outlines vs. events:** speech, beeps and roles are byte-identical to v26.1.7 (tested).
- **Overlay:** a Shapes select (Outlines / Boxes, default Outlines).
- **Mask colouring moved into the browser:**
  - The server sends each frame's class-id grid (`classes.png`) and the matching mapping's classes and levels (`segmentation.find_mapping`, pure, no GPU).
  - The page paints through a lookup table that repaints instantly on any edit.
  - The pre-rendered `mask.png` stays as a fallback.
- **Panel controls:** unsaved edits are kept as a local draft with an "unsaved changes" marker and Discard. The Save buttons are enabled only when needed. Reset to defaults is confirmed first.

**Test hygiene fix:** 12 older E2E tests were hard-wired to the user's full-length run `7b9d5ac14e14`, which the v26.1.7 bump wiped. They now create and delete their own run, so version wipes can't break them.

## v26.1.9 — the models now see true RGB (plan [`plans/v26.1.9.md`](plans/v26.1.9.md))
**Finding:**
- **The bug:** found while checking the iPhone export. The pipeline converts each frame BGR→RGB for the letterbox, then hands that numpy array to Ultralytics' `predict()`, which assumes numpy input is OpenCV BGR and flips it again. The segmentation model and the bus detector therefore saw **red and blue swapped**, in every Lab run and every review so far (v26.1 – v26.1.8).
- **Confirmed** against Ultralytics' own file loader on 6 frames of 4929: 14–34% of pixels took a different class, and the fixed path matched the file loader exactly (0 px).

**Fix:**
- `models.to_ultralytics(rgb)` hands the array over as contiguous BGR. It is used by `SegmentationModel.predict_class_grid` and `BusDetector.detect`.
- Callers keep passing RGB.
- New `tests/test_channel_order.py`: a unit test, plus an opt-in GPU parity test against the file loader (`HACKEYE_GPU_TESTS=1`).

**Before / after:**

The class shares (6 frames of 4929) are the main effect:

| Class | Before | After |
|---|---|---|
| flat road | 19.5% | 12.9% |
| flat sidewalk | 1.9% | 13.3% |
| curb | 0.5% | 1.7% |

Most of the "promenade is road" and sidewalk-vs-road confusion was this bug, not the model.

Full 52-minute run of 4929:

| Output | Before | After |
|---|---|---|
| speech | 236 (context 66, feature 74, danger 91, surface 5) | 268 (63 / 100 / 103 / 2) |
| beeps episodes | 40 | 51 |
| beep tones | 93 | 113 |

Against review 3:
- All 6 removals are still gone.
- 9 of the 27 confirmed calls match as before. Most of the others are still said, just 1–4 s earlier or later or with a different clock or step count. Three "person approaching" calls (76, 107, 201 s) and two beep episodes are gone.

**Decisions with the user:**
- **The full-run regression test is removed.** It takes too long; the user will ask when a full-run check is needed. Its baseline was the swapped segmentation anyway.
- The review 1–3 fixtures stay: they freeze grids, so they keep testing the collision logic. They no longer represent current model output.
- **The next review (on the fixed model) is the new behavioural baseline.** The thresholds tuned in v26.1.5 – v26.1.7 were tuned on swapped colours and may need revisiting from that review.

**Inference-resolution selector (same version):**
- **Request:** pick the inference resolution per run, for a speed/accuracy race between 544p and 720p at 32 px steps.
- **Options:** the Lab's Resolution select offers `544p`–`736p`. N is the padded short side of the model input. The aspect stays native, both input dimensions are multiples of 32, and nothing is upscaled (`profiles.short_side_spec`; table in CONTRACTS).
- **Display:** options show their size (e.g. `576p · 1024×576`), and the run badge and runs list show the input size.
- **Grid:** the collision grid stays 240 wide, so the race compares segmentation only.
- **Legacy profiles:** still accepted by the API, not offered.
- **Measured:** 736p runs at ~29 ms/frame on the 5060 Ti.
- **Caveat:** the `20261012-544` release was fine-tuned at 544, so higher resolutions run it off its training scale. The 1280-trained `20261011` release is the fairer contender above 544p.
- **Implementation:** done by a Sonnet worker and reviewed. Deviations: Lab tests went in a new `tests/test_lab_resolution.py`, and a size that can't reach N exactly is also refused (otherwise a 540-high source at 576p would silently give 544).

**Also noted:**
- The app's `yolo26s-semINT8512x896.mlpackage` is FP16, not INT8 (its metadata says `int8: False`).
- The iPhone feeds CoreML true RGB, so after this fix the Lab and the app see the same input.
