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

## v26.1.10 — review auto-scroll, quarter clocks, metric depth (plan [`plans/v26.1.10.md`](plans/v26.1.10.md))
**Requests:**
- The speech review panel should follow the playhead.
- Clock positions in quarters ("person at 12:15 in 10"), because positioning matters for navigation.
- Would an ML model give better distance and collision results than the rules, using the mask boundaries? Something like V-JEPA, open-source and local.
- Mid-planning: make `Yolo26m-sem-HackEye20261011.pt` and 736p the Lab defaults.

**Review 4 (wiped by this bump, not saved as a fixture):** one ⊘ at 150.65 s, "crosswalk at 12 in 12": "Already referenced before. need to improve object tracking". The user said it is in line with this work and will review the next version in depth.

**ML recommendation (agreed):**
- **No end-to-end learned collision model yet.** There is no labelled data (the reviews are its start), and the rules stay explainable and reviewable.
- **Depth model:** fuse a learned *metric depth* model with the mask boundaries. Distance was the weakest link: ground contact, horizon jitter, camera height.
- **V-JEPA 2 / 2.1** (Meta, open, 1.2B): not viable on an iPhone 12. It is a later Lab-only candidate, as the feature extractor of a hazard model trained on review labels.
- **Depth Anything 3 Metric Large** (ByteDance, **Apache-2.0**, 0.35B) is used in the Lab. DA3-Small and DA3-Base (also Apache-2.0, with CoreML ports) are the production path. The Large any-view and Giant models are CC-BY-NC, so they are avoided.

**Implementation** (three Sonnet workers on disjoint files, reviewed):
- **Auto-scroll:** at ≥ 1200 px the list isn't the scroll container (`#reviewPanel` is), so the old `list.scrollTop` did nothing. Rows are now revealed in the nearest ancestor that actually scrolls, never the window.
- **Quarter clocks:** `clock_quarter` (7.5° steps) and `clock_text` ("12", "12:15", "11:45", "1:30"). `clockText` is added to hazards and to speech and beeps events, and the integer `clock` is kept.
- **Lens projection** (`projection` setting, auto = fisheye at HFOV ≥ 100°): it matters at quarter precision (pinhole and equidistant differ by ~10° at x = 0.75 for 118°). It applies only to bearings and the depth focal; lane, lateral and ground math are unchanged.
- **Depth pass** (`depth: "da3-metric-large"` run option):
  - DA3 runs on the un-letterboxed RGB frame at process_res 504, with metric = focal·net/300 (README).
  - Output goes to `depth.npz` at 120×68.
  - DA3 is installed from a pinned commit with `--no-deps` plus its import-time deps. Its metadata asks for numpy < 2, but it works on numpy 2.2.
- **Distance source** (`distanceSource`: ground / depth / fused): re-scored with "Re-run collision", without new inference. Tracking still matches on ground distances, and the gait calibration stays ground-based.
- **Lab UI:** a Depth select, a Depth overlay (turbo, near = red), Lens and Distance settings, and labels showing `ground X m · depth Y m`.
- **Fused mode dropped** (user decision after the A/B): "its either one or the other". `distanceSource` is `ground | depth`; a stored or requested `fused` is refused (422) or resolves to ground in the library.
- **Defaults:** model `Yolo26m-sem-HackEye20261011.pt` (`HACKEYE_LAB_DEFAULT_MODEL`), resolution 736p. Depth with Metric Large was briefly the default distance source; it was revised in the follow-up below (Small/Base, opt-in, ground default). The API defaults for a missing `depth`/`profile` stay `none`/`default`.

**Results** (4929 full, 20261011 @ 736p + depth, 72 ms/frame of which depth 45.5):

| Source | Speech | Beeps | Step jumps > 30 % | Closing |Δ| median / p90 |
|---|---|---|---|---|
| ground | 234 | 63 | 0.4 % | 0.22 / 0.83 m/s |
| **depth** | **159** | **24** | 0.9 % | **0.11 / 0.46** |
| fused | 209 | 39 | 6.3 % | 0.17 / 0.89 |

- 61 % of phrases land on a quarter.
- Depth reads a median **1.44×** farther than the gait-calibrated ground distance (p10 0.97, p90 2.54), so fewer items fall within 10 steps.
- **Scale check (no ground truth):** the closing speed of static poles divided by the walking speed should be a bit under 1 (lateral offset). It is 0.87 with depth (IQR 0.42–1.21) and 0.75 with ground (0.39–1.34), so depth's scale looks right and the ground distances still read short.

**Known limitations:**
- **fused** switched source frame to frame, so step counts jumped (6.3 %).
- **Lens model:** DA3 assumes a pinhole camera, but the footage is fisheye (equidistant focal used).
- **Portrait recordings:** their depth maps are stretched to 120×68.
- **Validation:** fewer calls is not yet validated: the next review is the baseline.
- **Fixture matching:** the regression fixtures match clocks with a ±2-quarter tolerance (fisheye bearings shift).

### v26.1.10 follow-up — mobile-sized depth: DA3 Small / Base (same version, no wipe)
**Request:** run DA3 Small and Base, the mobile-viable sizes; there is "no gain in testing large if it won't be a good match for mobile". Decisions: remove Metric Large from the Lab (weights kept in `~/models`), make Small the default depth model, and use a gait-calibrated scale.

**Finding: relative depth.** Small and Base are DA3 "any-view" models (Apache-2.0) and output **relative z-depth**. Against Metric Large on the same 4929 frames:
- **Within a frame:** they match up to one scale with ~4% error, so the shape is good.
- **Across frames:** that scale drifts (median 7%, p90 ~20% per 1.7 s, range ~7.5–12 for Small).

**Iterations** (scaled `depthM` against Large; frame-level error around the run's median level):

| Scaling | Level vs Large | Drift median / p90 | Frames within ±25% |
|---|---|---|---|
| Run-level gait scale only (Small) | 0.55 | — (items: p10 0.13, p90 2.4) | 15% |
| Per-frame ground anchor (estimated horizon) + gait level, Small | 0.77 | 12% / 33% | 38% |
| … Base | 0.67 | 12% / 34% | 19% |
| **Anchor on the fixed mount horizon** (user's idea), 0.4 s smoothing, Small | 0.74 | **9% / 26%** | 28% |
| … Base | 0.68 | 11% / 29% | 17% |

- **User's suggestion, adopted:** hold the horizon at its mid/mount row for the anchor. A fixed point is easy to stabilise in 2–3 frames, and it only loses consistency while turning, which is accepted. It cut the drift, so `distance.anchorHorizon: "fixed"` is the default.
- **The remaining gap is the absolute level:** ~0.74× Large, about the same level as the plain ground geometry (≈0.69× Large). Either the gait level undershoots or Large overshoots; the pole check put Large's closing at 0.87× walking speed. Only a **ground-truth measurement** (a clip walking up to a tape-measured landmark) can settle it.
- **Timing (5060 Ti):** depth takes Small 23 ms/frame and Base 32 ms/frame in the full runs (Large took 45.5). Base is no better than Small here.

**Decision (user):** ship Small and Base as **opt-in** experiments. The distance default goes **back to ground**, and depth runs still default to Small, so the overlay and the A/B are one click away.

**Next:** a small **metric** model for mobile. Depth Anything V2 Metric Outdoor Small (24.8M parameters) needs its license verified. UniDepth v2 is CC-BY-NC, so it is ruled out.

**Lab state:** the Small run `95d1beea0684`, the Base run `33b0702b8c81` and the Large reference `5b1d10dd5b3d` are kept for comparison.

### v26.1.10 follow-up 2 — metric mobile depth models, licence documentation (same version, no wipe)
**User input:**
- The apps are open-source, free and **non-commercial**, so CC BY-NC models are acceptable. This reverses the earlier "UniDepth is CC-BY-NC, ruled out".
- Ground truth isn't viable: production cameras can't be known. So models that estimate the camera themselves are preferred.

**Added as Lab depth options** (a Sonnet worker built them and the lead reviewed):
- `da2-metric-outdoor-small`: Depth Anything V2 Metric Outdoor Small, 24.8M params, Apache-2.0, fine-tuned on Virtual KITTI 2 (CC BY-NC-SA 3.0). Loaded with transformers.
- `unidepth-v2-s`: UniDepth v2 ViT-S, CC BY-NC 4.0. It runs **without intrinsics** and estimates the camera itself. On 4929 it estimated fx ≈ 1282 px, i.e. a pinhole view of ~74° HFOV, while the GoPro Wide covers ~118°.
- **Install:** both from pinned commits with `--no-deps`. The new deps are `transformers`, `timm` and `wandb`; wandb is imported by UniDepth only and is disabled with `WANDB_MODE=disabled`.

**4929 full runs** (20261011 @ 736p, depth mode re-scored; reference = the DA3 Metric Large run `5b1d10dd5b3d`):

| Model | ms/frame | Level vs Large | Drift median / p90 | Frames within ±25% | Speech / beeps | Step jumps | Closing \|Δ\| median / p90 |
|---|---|---|---|---|---|---|---|
| DA3 Small, anchored | 23 | 0.74 | 9% / 26% | 28% | 231 / 47 | 1.9% | 0.13 / 0.52 |
| DA3 Base, anchored | 32 | 0.68 | 11% / 29% | 17% | 270 / 62 | 2.7% | 0.13 / 0.58 |
| **DA2 Metric Outdoor S** | 56 | **2.23** | **4% / 10%** | 0% | 65 / 5 | **0.0%** | 0.25 / 0.86 |
| UniDepth v2 S | 39 | 1.33 | 19% / 37% | 42% | 126 / 13 | 7.8% | 0.32 / 1.44 |

**Reading the results:**
- **DA2 Metric Outdoor S** is by far the most temporally stable: per-frame scale drift 4%, no step jumps. Its absolute level, though, is ~2.2× Large. That is a near-constant bias, most likely because it was trained on pinhole driving footage and is now shown fisheye pedestrian frames.
- **UniDepth** lands closest in level, but it is noisy frame to frame.
- **Desktop timings** include post-processing at the full frame size. DA2's 56 ms is mostly its upsampling to 1920×1080, which the phone would not need.

**Candidate next step:**
- Treat a metric model as *metric up to a constant* and apply only the gait-calibrated level `c`, without the per-frame anchor, to DA2's very stable maps.
- That pairs the best stability with a self-calibrated level, needing no camera knowledge.

**Licence documentation:**
- `THIRD_PARTY_LICENSES.md` was added to HackEye and to HackEye-Models.
  - **Section 1, "requires legal handling":**
    - Ultralytics AGPL-3.0, which covers the YOLO26 bases, the fine-tunes and the exports;
    - Mapillary Vistas CC BY-NC-SA 4.0, ADE20K and Cityscapes terms;
    - UniDepth CC BY-NC 4.0, and Virtual KITTI 2 behind DA2 Metric;
    - the Meta Wearables Developer Terms;
    - the GPL-3.0 tools in the RnD image only (evo, plyfile, ffmpeg);
    - the Apple SDK terms.
  - It ends with a shipping checklist.
  - **Section 2, "Thanks":** the permissive projects, with their licences read from package metadata.
- **READMEs:** the HackEye, RnD and HackEye-Models READMEs gained licence sections. The RnD "Depth model" section lists each option's licence and download.

**User's idea: a quick "delta" calibration for DA2, within 6 frames** (`tools/depth_delta_calibration.py`):
- **Method:** over N frames, c₀ = median(flat-ground z / DA2 z) on the walking region. The flat-ground z uses the fixed mount horizon and the preset camera height, the only absolute reference available within 6 frames; gait needs ~2.4 s for a cadence. Then depth = c₀ × DA2 is held.
- **Test:** a fresh calibration every minute of 4929 (50 calibrations), each held for the following minute.
- **c₀ is very consistent:** 0.174 (p10 0.162, p90 0.191, spread 4%). **3 frames are as good as 6.**
- **Held for a minute, the error around the level is a median 6% (p90 14%)**, the most stable result so far. Anchored DA3 Small, re-anchored every frame, gave 9% / 26%.
- **The absolute level is whatever the reference says:** 0.39× Large with the uncalibrated camera height and lens. It moves to roughly ground level once multiplied by the gait scale k (≈ 1.8 on 4929), and that refinement can take over later.
- **Result:** DA2 plus a 3–6-frame flat-ground calibration (then gait refinement) is the best mobile candidate so far, a candidate for the next version's collision logic.

### v26.1.10 follow-up 3 — DA2 with initial-frame calibration is the default depth mode
**Request:** make DA2 with the frame calibration the default depth mode. Also: verification runs use a **5-minute window** (4929 0–300 s), because full runs take too long for the gain.

**Implementation** (a Sonnet worker, reviewed):
- **Anchor modes:** each depth variant declares one: DA3 → `per-frame`, DA2 → `initial`, UniDepth → `none`.
- **`initial`:** collects the flat-ground / DA2 ratio on the walking region (fixed mount horizon), uses its running median from the 3rd valid frame, and freezes it at the 6th. The gait level `c` refines it as before.
- **Defaults:** depth model `da2-metric-outdoor-small` in the UI, and `distanceSource: depth`.

**4929 0–300 s** (re-scored from the existing runs; no new inference):

| Distance | Speech | Beeps | Step jumps | Closing \|Δ\| median / p90 | Level vs Large (after 60 s) | Drift median / p90 (after 60 s) |
|---|---|---|---|---|---|---|
| ground | 33 | 14 | 0.2% | 0.19 / 0.67 | — | — |
| **DA2 + initial calibration** | **24** | **3** | 0.4% | 0.11 / 0.43 | **0.83** | 10% / 30% |
| DA3 Small, per-frame anchor | 35 | 11 | 2.1% | 0.11 / 0.42 | 0.65 | 5% / 16% |
| Metric Large (reference) | 26 | 3 | 0.4% | 0.10 / 0.38 | 1.00 | — |

- **Usable from 0.3 s:** DA2 is usable almost at once (frozen anchor 0.208).
- **Closest to the reference:** of the mobile options, DA2 is the closest to the Metric Large reference in level and in what it actually announces (24 / 3 against 26 / 3), with the same step stability.
- **Drift:** over the first minute it is higher (p90 52%) while `c` settles from the ground scale to its gait estimate. DA3 Small drifts less in this window but reads further off and jumps more.

### v26.1.10 follow-up 4 — the DA2 first-minute drift: body-based plane calibration
**The problem:** the DA2 first-minute drift came from the gait level `c`, not the anchor. `c` borrowed the uncalibrated ground scale (1.0 → 0.8), got its first estimate at ~35 s, then kept climbing (1.2 → 2.4 by 145 s), so the level went 0.44 → 1.09× Large.

**Step 1, freeze the level:** `c` is frozen at its first estimate (`levelModeByAnchor.initial = freeze`), with `depthLevelPrior` default `"ground"`. That stopped the wander, holding 0.51–0.68× after 40 s, but the first 40 s stayed uncalibrated and the frozen level was only as good as that first estimate.

**Step 2, no camera priors.** The user's requirement: production cameras, mounting heights and angles are unknown. Production will instead ask once for the user's **height** and the camera **location** (waist / chest / eye / head) and **side** (left / center / right).
- **New body settings** (editable in the Lab): camera height = ratio × height (chest 0.72), step length = 0.415 × height, a lane offset from the side, and a per-location horizon default.
- **DA2 anchor `plane`:** a per-frame ground-plane fit in back-projected DA2 depth gives the camera height in depth units and the pitch. Scale = body-derived camera height / fitted height, frozen after 6 valid frames. The gait estimator is only a cross-check (`depthGaitCheck`).
- **Head mounts:** the user will record head-mounted footage when a GoPro head mount or Meta / Samsung glasses arrive. The lane heading is isolated (`_walking_axis_offset_m`) for a later IMU body heading.
- **The user's footage:** 1.78 m, GoPro chest, center → camera 1.28 m, step 0.74 m. Set on 4929.

**4929 0–300 s:**

| Distance | Speech | Beeps | Step jumps | Closing \|Δ\| median / p90 | Level vs Large | Drift median / p90 (whole window) | Usable from |
|---|---|---|---|---|---|---|---|
| ground (body settings) | 34 | 10 | 0.4% | 0.24 / 0.80 | — | — | — |
| **DA2 + plane** | 34 | **4** | 0.6% | **0.11 / 0.47** | 0.63 | **3% / 9%** | 3.7 s |
| DA2 + initial + frozen gait | 34 | 4 | 0.7% | 0.12 / 0.47 | 0.65 | 4% / 27% | 0.3 s |
| Metric Large (reference) | 26 | 3 | 0.6% | 0.10 / 0.42 | 1.00 | — | 0 s |

- **The first-minute drift is gone:** 3% / 9% over the whole window, including the first minute.
- **Estimated pitch:** 2.9° down.
- **Absolute level is still unresolved:** the plane level is 0.63× Large, while the walking cross-check is **1.40** (walking says distances read ~40% short).
  - If the walking check is right, the true level is ≈ 0.88× Large, and the body-derived camera height or the fisheye back-projection near the bottom edge is off.
  - If the camera height is right, the step length (0.74 m) is too long.
  - The two absolute references disagree. The bottom-edge fisheye geometry is the first suspect, and a non-fisheye camera (iPhone, glasses) should settle it.
