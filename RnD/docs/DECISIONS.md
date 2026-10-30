# HackEye RnD — decision log

One entry per version: what prompted it (usually the user's review in the Lab), the decisions made with the user, the implementation choices and deviations workers made, known limitations, and the measured result. The current rules live in [`../lab/CONTRACTS.md`](../lab/CONTRACTS.md); this file explains **why** they are what they are.

**Ground truth.** The user's Lab reviews are kept as regression fixtures in [`../tests/fixtures/`](../tests/fixtures/) (`4929_review1`–`6`, `chest0002_crosswalk`, `chest0004_review7`, `chest0004_review8`; `.npz` + `.json` each) and replayed by `tests/test_collision_regression.py` and the per-version tests. A version bump wipes the Lab, so the fixtures are the permanent record.

**How we work** (user decisions, standing):
- **Versioning:** `v<YY>.<major>.<minor>`, with the minor dropped when 0. v26.1 is collision detection, and v26.1.x are improvements within it. `RnD/VERSION` holds the current version.
- **Fresh Lab per version:** a version change wipes Lab runs and reviews (no archive). Video proxies and per-recording settings are kept. Reviews are therefore saved as fixtures *before* bumping.
- **Roles:** the main session (Opus) plans, writes contracts, reviews and verifies. Implementation is done by Sonnet subagent workers; every plan states a worker recommendation. When the user asks for a version ("bump version, commit, push, mail"), the delivery is: tests (unit + E2E) → DECISIONS + CONTRACTS → bump → Lab restart (never while an analysis runs) → commit on the milestone branch → push → a summary mail to the user.
- **Don't block on results** (user rule, 2026-10-25): when a measurement misses expectations (a ✓ lost, a ✗ back, a target missed), ship the best measured variant anyway and list every miss in the entry's **Known / possible issues** section; offer alternatives in the mail. Only destructive or irreversible steps wait for the user.
- **Questions by mail:** when the user is away, blocking questions go by email; the done-mail states how a terse answer was interpreted.
- **Branches:** one branch per milestone (`v26.2`); after it is squash-merged into `main`, the branch is deleted locally and remotely.
- **Less is more:** context first, then only potential dangers. Every addition to speech must earn its place.
- **Planning first:** features and changes are planned and approved before being built. Plans are kept in [`plans/`](plans/) (from v26.1.7 on).

**Where we are:** the milestone status, the open issues and the next steps are kept in [`plans/v26.2.md`](plans/v26.2.md) (section *Status and next steps*); each version's own known issues are at the end of its entry below.

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

### v26.1.10 follow-up 5 — fisheye level investigation: pinhole rays for depth
**Investigation** (4929 0–300 s, flat walking-region ground, no ground truth). The geometric z (camera 1.28 m, pitch, lens model) was compared with both models' z, by distance and by column.
- **The models read the fisheye as pinhole.** With the equidistant fisheye rays, DA2's ratio (geometric / model) fell from 0.22 at 1–2 m to 0.13 at 8–12 m, and Large showed the same. A search over the lens family `r = (f/k)·tan(kθ)` and pitch made both models agree with the geometry across 1–12 m (std of the log ratio 0.6–0.8%) at **k ≈ 0.95–1.0 (pinhole)** and pitch ≈ −4° (slightly up). DA2 and DA3 are trained on pinhole images and read any frame as pinhole.
- **The near-ground scale barely changes** (0.98×), so the fisheye is *not* the cause of the 1.40 gait-check gap.
- **The Metric Large reference was inflated.** Its metric conversion used the equidistant focal, which under the pinhole reading inflates it ×1.62. Corrected, the DA2 plane level is ≈ 1.02× Large: the camera-height calibration and Large agree.
- **The walking-speed estimate is the outlier:** cadence × step reads 1.4–1.8× fast, and the stride-vs-step harmonic choice is the suspect.

**Decisions (user):**
- **Fix 1:** pinhole rays for depth-model back-projection, implemented as `distance.depthRayModel` (`"lens"` | `"pinhole"`).
  - **Measured on 4929 0–300 s:** pinhole rays made the full plane fit *worse*:

    | Rays | Pitch | Level vs Large (corrected) | Gait check | Speech / beeps |
    |---|---|---|---|---|
    | lens | 2.9° | 0.63 (1.02) | 1.40 | 34 / 4 |
    | pinhole | 3.4° | 0.47 (0.76) | 1.87 | 43 / 10 |

    Drift was 3% / 9% either way, and pinhole made depth usable from 0.3 s instead of 3.7 s.
  - **Why the offline test misled:** it fixed the camera height and only scored near-to-far flatness. The real fit also solves height and pitch, and does not reproduce the −4° solution.
  - **Default:** `"lens"`, so behaviour is unchanged. `"pinhole"` stays available for normal-lens cameras: in production iOS delivers distortion-corrected frames and per-frame intrinsics, so there pinhole is the true model.
- **Fix 2 is parked:** correcting the Metric Large reference conversion.
- **Fix 3 won't happen:** cadence verification. The gait estimate stays a check only (`depthGaitCheck`), known to read high on this footage; it never changes distances.

### v26.1.10 follow-up 6 — CPU device for Lab analyses (same version, no wipe)
**Prompt:** the user will train a yolo26x teacher at 1280 in HackEye-Models (2026-10-18). The X-1280 timing probe peaked at 14.8 GB of the 16 GB GPU at batch 1, about 7 h per epoch. The user wants to keep working in the Lab while it trains, and asked for analyses to run on CPU on request. They also reported that the Cancel button and the progress bar had disappeared.

**Decisions:**
- **New option:** `POST /api/runs` takes `device: "gpu" | "cpu"`. GPU is the default; any other value gives 422.
- **CPU only when asked:** CPU runs only on request, never as a fallback. A GPU run without CUDA still fails through `gpu_guard`.
- **Not part of the run id:** `device` is an execution option and isn't hashed into the run id, so an identical finished run is reused whatever device is asked for. The run doc records it as a top-level field; a missing field means gpu.
- **Model cache:** keyed by path + device (segmentation) and variant + device (depth). CPU uses `HACKEYE_LAB_CPU_THREADS` threads (default cpu_count − 2), which leaves cores for training's data loaders.
- **UI:** a Device select, remembered in localStorage, and a "· CPU" tag on the run badge and the past-runs list.

**Verified:**
- **Unit tests:** 335 passed, 6 skipped. The new `tests/test_lab_device.py` adds 7 tests.
- **CPU run:** 4929 31–61 s at 6 fps and 736p, with DA2, finished in 150 s wall. Segmentation took 812 ms/frame and depth 527 ms/frame, about 5× real time.
- **No CUDA-only code:** none in `models.py` or `depth.py`. One caveat: DA3's autocast queries `torch.cuda.is_bf16_supported()`, so it's untested in a container with no CUDA at all.

**Cancel/progress report:** not reproduced. The new E2E test `tests/e2e/test_run_controls.py` runs a CPU analysis and checks:
- the Cancel button and progress bar show, and progress advances;
- both survive a reload mid-run;
- Cancel ends the run and hides both.

It passes. Short GPU ranges finish in 3–6 s, so the controls show only briefly; a stale browser cache of `app.js` (served without Cache-Control) is the other suspect. The JS and CSS logic was not changed.

## v26.1.11 — review 4: motion words, collision course, stationary user (plan [`plans/v26.1.11.md`](plans/v26.1.11.md), fixtures `4929_review4`)
**Review 4** (first on the fixed model: run `ffc2e6f0bd66`, 4929 full length, 736p, DA2 plane depth, collision v26.1.10): 63 judgements, **52 ✓, 2 ✗, 9 ⊘**, 12 notes on ✓ entries. The user wants: person/rider state (static, approaching, moving away); no distance for fast things; nothing for movers that are not on a collision course; no vehicle context; one curb per crossing; nothing static announced while they stand still; "tarmac" fixed. The fixtures (`tests/fixtures/4929_review4.{json,npz}`, 25 MB) were saved **before** the version bump: seven windows (20–50, 66–105, 150–205, 236–270, 284–345, 352–410, 436–470 s) with grids, 24 Hz motion, the DA2 depth maps and the 63 annotations; the residual flow (§ below) was computed from the video afterwards because the run predates it.

**Decisions** (the plan's nine, as built; deviations marked **Δ**):
1. **Motion words** for people and riders (`SpeechPolicy._kind`): `person standing at 12 in 7` (cyclist: `stopped`), `person approaching at 12` (any measured mover on a collision course, vehicles too), `person moving away at 12`; unmeasured motion keeps `person at 12 in 7`. Approaching and moving away have **no distance**.
2. **Only a collision course is a danger for a measured mover** (`_on_collision_course`): `T = distance / closing`, lateral at the meeting `lateral + lat_vel × T` within 1.5 m, meeting within 8 s. Beeps follow (collision tracks only). **Δ** the velocity model is weaker than the plan assumed, measured on 4929: a STANDING pole/building has a lateral-position slope of 0.5 m/s median and 1.4–2.4 m/s at p90 (also after the turn correction), a standing person 0.3 / 1.0. So the sideways velocity is used only above a 2 m/s deadband (a vehicle crossing the crosswalk reads 5–8 m/s; a person walking across at 1–1.5 does not register and keeps the lane rule on the current lateral, as before), `moving` is decided on the speed *along* the line of sight (+ a sideways speed above the deadband), and a mover must also be within the old reach of the lane now (3.0 m people, 1.6 m vehicles). A person walking away inside the lane is a danger without beeps ("moving away").
   **Δ (depth closing scale)** depth closing rates read low against the gait (`depthGaitCheck` 1.2–1.6): a standing person's closing was 0.85 m/s against our 1.4, so the plan's `closing − ego speed` made standing people "move away" and approaching ones "stand". `along = (closing − v/c)·c` with the gait level `c` of the plane-anchored depth (clamped [0.8, 2.5]; 1 before it is measured), smoothed with a 1 s EMA (a far person's closing swings 1.0 ↔ 4.0 m/s).
3. **Vehicles are never context** (`contextSpeak` = obstacle, building). **Δ extra:** a vehicle of unknown motion is no static danger while ego speed is known (a moving car re-detected in fragments has no closing speed for ~0.75 s and was one at 39.0 s); a parked car measured standing in the lane is still a static danger.
4. **Curbs once per crossing:** `featureLabelOverrides.curb` = 20 s / **24** steps (the far-side curb of a ~15-step crossing is the same crossing), crosswalk 20 s / **20** steps (was 14: the review 3 ✗ at 59.85 s came back with the new timing). **Δ** the plan's second clause (no curb when a crosswalk was announced < 20 s ago) contradicts its own expected result for 39.0 s ("curb + poles", the near-side curb is wanted before the crossing), so only the once-per-crossing override is implemented: 37.3 crosswalk, 39.5 curb, nothing at 40.5 / 46.2.
5. **Surface change needs a curb/crosswalk that crossed the lane:** `feature_frames ≥ confirmFrames` before a track counts as evidence. **Δ the plan's diagnosis was wrong for 159.8 s:** the evidence there was a *crosswalk* (not a curb along the path) at the left edge of the lane, 7 s before and 5 s after the road run began (v26.1.10 and 11 both log it). Lane cover, bbox and seed-box coverage of the ten evidence tracks of 0–300 s did not separate it, so the rule is now causal: evidence counts only within [−3 s, +2 s] of the start of the new surface's stretch (`evidenceLookbackSeconds` 10 → 3, new `evidenceLeadSeconds` 2; flickers of ≤ 1.5 s bridged). Removes "road" at 159.8 and with it "sidewalk" at 244.0 (the genuine crosswalk at 236.0 sat exactly at that run's start).
6. **Stationary user** (investigation; `egoflow.py`, `estimate_stationary`, `ego.stationary`): see the numbers below. While stationary: ego speed 0, cadence ignored, world memory stands still, every item except a measured mover on a collision course gets role `none` (no context, feature, thin notice, danger, final, beeps).
7. **Ego speed when the cadence drops:** the last cadence-based speed is held `cadenceWindowSeconds`, then unknown (people get no motion word); the witness speed stays only as the cold-start guess before any gait scale exists. With depth distances cadence × step length is used from the first cadence (they are metres from the start).
8. **Cadence refine:** a parabola that moves more than one bin or leaves the search band is rejected (the −16.3 Hz came from the band edge with a bigger neighbour outside it).
9. **TTS:** `audio.js` utterances get `lang = "en-US"` and an English voice from `speechSynthesis.getVoices()` (cached, refreshed on `voiceschanged`). The user verifies by ear.

**Stationary detector — what was measured** (4929; ground truth by looking at the frames: the user walks until ~296 s, stops and turns in the outdoor gym ~296–305 s, stands still from ~308 s to ≥ 346 s):
- **(b) static-witness closing speeds: rejected.** Depth closing of pole-like items is 0.0–1.2 m/s while walking at 1.4–1.6 (median ~0.5), so it cannot be told from standing.
- **(c) cadence quality: rejected before building.** Standing 286–345 s reads 1.3–2.2 Hz with a 1.1 m/s speed and a bob RMS (0.0019–0.0030 of the frame height at 290–304 s) in the walking range (0.0029 at 36 s).
- **(a) image motion: works.** Radial divergence of the Farneback flow was right in the mean (standing ≈ 0) but fell to 0 on sky-facing and featureless frames while walking (40–44 s, 222–224 s). What separates is the **residual flow**: after subtracting the median flow (pan, tilt, bob) the median flow magnitude over the textured pixels, frame vs. 6 frames earlier, 160×90 (≈ 1.5 ms per frame; stored as `motion.npz` `resid`). **Causal 1 s median of it: standing (308–350 s) 0.07–0.58 px; walking (0–296 s and 360–470 s) ≥ 1.34 px at every moment** (p1 1.82, median 2.8). Thresholds enter < 0.8 px for 1.5 s, leave ≥ 1.0 px for 1 s: a 2.3× gap on both sides. Result on 0–500 s: stationary 307.3 → 351.4 s only, plus one 1.4 s pause at 300.8 s; **never while walking**. The state starts at 307.3 s, about when the picture goes still (the 1 s median is < 0.8 px from ~306 s; the user stops and turns first). A turn in place (301–304 s) reads as walking (the picture rotates), so "obstacle at 12:15 in 7" at 302.8 s is still said.
- No texture (frames of plain sky or wall) never enters the state and counts as walking evidence when leaving: a wrong "stationary" would silence warnings, a wrong "walking" only talks too much.
- `ANALYSIS_VERSION` 2 → 3 (`resid`). Runs without it (and fixtures 1–3) are never stationary.

**Result** (4929 0–450 s, the last reviewed time; v26.1.10 logic re-scored on the same new run's data, which reproduces the old run's counts exactly (34 / 4 for 0–300 s)):

| | v26.1.10 | v26.1.11 |
|---|---|---|
| speech 0–450 s | 52 (15 context, 16 feature, 18 danger, 1 final, 2 surface) | **38** (10 context, 14 feature, 13 danger, 1 final) |
| beep episodes / tones 0–450 s | 7 / 15 | **5 / 9** |
| speech 0–300 s | 34 | **25** |
| beep episodes 0–300 s | 4 | **3** |
| speech 284–345 s | 7 | 4 (6 on the separate 284–345 s clip run, cold start) |

Of the 11 ✗/⊘ entries up to 450 s, 9 were still produced by v26.1.10 and 2 are by v26.1.11 (see below); of the 44 checked ✓ entries v26.1.11 reproduces 32 (a ±2.5 s label match; 44 before): lost by decision are the two vehicle phrases (5.7, 215.0 s), people who are not on a collision course (86.8, 98.8, 263.7, 294.2 s: "no need to notify if the person is in a non-collision direction"), 178.7 s (the person is static), and context/curb phrases that moved by more than 2.5 s because the slot before them changed (42.3, 51.8, 189.0, 356.6, 362.8 s).

**What each ✗/⊘ of review 4 now produces:** 39.0 vehicle + beeps → gone (a curb at 39.5 s: "curb at 12 in 5", the near-side curb); 40.5 curb → merged into that one curb; 46.2 curb → nothing; 159.8 "road" → nothing; 178.7 "approaching" → `person standing at 12:15 in 13` at 173.8 s; 244.0 "sidewalk" → nothing; 302.8 obstacle → **still said** (the user is not yet "stationary", see above); 321.7 person, 334.2 obstacle → nothing (stationary); 380.7, 399.1 vehicle → nothing (vehicles are not context). The ✓ notes: the person at 28.0 s is now `person standing at 11:45 in 8` (30.0 s), the one at 200.3 s `person approaching at 12:15` (200.8 s), the one at 98.8 s is silent (not on a collision course); cyclists at 190.5 and 445.3 s: `cyclist approaching at 11:45` / `12`, no distance.

**Known limitations:**
- **Depth closing is the weak link:** the along-speed of a far person (10 m+) is ±0.7 m/s noisy, so "standing" vs "approaching" is a judgement of the smoothed speed, not a certainty; in the 192–218 s cold window (no gait level yet) 201.3 s "approaching" is not recognised, the warm run says it at 200.8 s.
- **Vehicles** that the model re-detects as fragments are silent until their motion is measured (~0.75 s).
- A person walking across the path at 1–1.5 m/s is not told from standing by their sideways speed (noise); the lane rule decides.
- `common/config/collision.json` is shared with the app: `contextSpeak` and the new keys change what the iOS port reads when it adopts v26.1.11 (Apple/ untouched).

**Tests:** 373 passed, 6 skipped (335 before); browser E2E (`tests/e2e/run.sh`, after the `audio.js` change): 31 passed; `tests/test_collision_v26111.py` (27 synthetic tests, one or more per rule), a review-4 block in `test_collision_regression.py` (11 tests), review 1–3 expectations updated where the decisions change them: vehicles are never context (review 1 "vehicle and building after the turn", review 2 start phrases, review 3 5.34 s tick), one curb per crossing (review 2 38.8 s curb; review 3 49.67 s tick), moving-away/approaching phrases carry no distance (review 3 phrase regex, the matcher ignores motion words), the 201.33 s cold-window tick (above), and one trailing frame of a beeping track may be role `none`.

### v26.1.11 follow-up: Chrome mobile audio (same version, no wipe)
The user reported no audio (beeps or speech) on Chrome for Android. Diagnosis, all of it confirmed in the code:
- **Unlock on the wrong event.** `armOnFirstGesture` fired once on the first of `pointerdown`/`keydown`/`touchend` and removed its listeners. A touch `pointerdown` is not a user activation in Chrome Android, so `resume()` left the context suspended, the silent speech prime was rejected (`not-allowed`) and nothing retried; `enabled` only checked that a context existed, so tones were scheduled into a suspended context. Now: listeners on `pointerup`/`touchend`/`click`/`keydown` stay for the page's life and retry until the context is `running` and the prime was accepted; later gestures and `visibilitychange` resume a suspended/`interrupted` context; no tone is scheduled unless `ctx.state === "running"`.
- **Speech cancelled by buffering.** `waiting`/`playing` called `reset()` -> `speechSynthesis.cancel()`, killing phrases on every stall, and Chrome Android drops a `speak()` that follows a `cancel()`. Now those two only reset the tone schedule; speech is cancelled on real discontinuities, and only when something is speaking or pending.
- Stuck-paused synthesis: `resume()` before `speak()` when `speechSynthesis.paused`.
- Voice (v26.1.11 decision 9): on Android a `localService` English voice is preferred; a voice whose utterance errors is dropped and the phrase retried once with lang `en-US` only.
- Utterance errors are logged (`console.warn` and `__labAudioLog` `{type: "speech-error", error}`) so the next report says what the phone does.
- Not verifiable without a real phone: the actual audible output, Android voice behaviour, background/foreground resume. Tests use an emulated touch context.
- **Second report: beeps but no speech (real Android Chrome).** The WebAudio unlock works, `speechSynthesis` produces nothing. Likely cause: the silent `" "` prime at volume 0 never fires end/error on the Android TTS engine, so `speaking`/`pending` stay true and every later phrase queues behind it. Fixes: (1) **prime skipped on Android** (chosen over speaking a real word at volume 0 and cancelling it: that would still be an utterance the engine may never finish, plus a cancel() glued to later speak() calls, which Chrome Android drops; Chrome needs only sticky activation, which any tap gives; desktop unchanged); (2) watchdog: no `onstart` in 1.5 s while the synthesis is busy -> cancel, drop the voice, speak once more; a busy queue holding nothing of ours is cancelled before a new phrase; (3) live utterances kept in a Set (Chrome GCs them and loses their events); (4) a voice that never starts counts as failed (reuses `voiceFailed`).
- **Remote diagnostics** since the cause cannot be proven without the phone: `POST /api/client-log` -> `debug/lab/client-log.jsonl` (5 MB, one rotated generation, outside the wipe set) carrying voices, every speak/utterance event, cancels and the AudioContext state; plus a "Test speech" button in the Audio panel that reports the outcome in a toast. Read the file after the user taps the button on the phone.
- **Third report: Chrome macOS (154) lost speech.** Client log: (1) watchdog false positive: a phrase spoken while the previous one is still speaking is only queued, never started within 1.5 s, so the watchdog cancelled the phrase being heard (`utt-error interrupted`) and set `voiceFailed`, silencing the voice for every later phrase. Now the timer only runs while none of our utterances has started-and-not-ended (armed when the one ahead ends/errors), the pre-phrase clear and the watchdog never cancel a started utterance, and the voice is dropped only if the retry without it starts while the voiced attempt never did. (2) Voice choice picked "Albert" (first en-US alphabetically, a macOS novelty voice): novelty/Eloquence voices are excluded by name prefix, then ranked default English voice > known natural voices > en-US > any en (Android keeps localService first; iOS still picks Samantha); the chosen voice is logged in the `voices` client-log entry.
- **Fourth report: system voice + stale cache.** The user asked to go back to the pre-v26.1.11 system voice: when the platform default voice is English, utterances set neither `lang` nor `voice` (`mode: "system"`); only a non-English default (iPhone: Joana pt-PT first) keeps `en-US` + the ranked English voice (CONTRACTS §12.2). The user also ran a stale `audio.js` (heuristic browser caching): `/static/*` and `/` now send `Cache-Control: no-cache`.

## v26.1.12 — review 5: motion-state accuracy, 10-step reach, beeps at 5 steps (plan [`plans/v26.1.12.md`](plans/v26.1.12.md), fixtures `4929_review5`)
**Review 5** (run `2ced2e0f2909`, 4929 0–120 s, default 960w, no depth maps, collision v26.1.11, done on the Mac with the system voice): reviewed up to 105 s, 17 judgements, **12 ✓, 3 ✗, 2 ⊘**, notes on 6. The user wants: speech that matches the text ("curb", not "tarmac"); a person who walks left not called "standing"; a person walking away not called "standing"; movers announced within 10 steps only; beeps only at 5 steps or less (speech before that); "approaching" announced when a person turns towards us; and a beep for a person near us whose motion is unknown. The fixtures (`tests/fixtures/4929_review5.{json,npz}`, 0.9 MB: one window 0–110 s with grids, 24 Hz motion incl. `resid`, the 17 annotations with their notes, and the 25 v26.1.11 events of the window) were saved from the run and `GET /api/reviews/export` **before** the version bump; the window run of the fixture reproduces the run's events exactly (19 speech + beeps).

**Decisions** (the plan's six, as built; deviations marked **Δ**):
1. **Reach:** `movingDangerSteps` 15 → 10.
2. **Beeps:** `tones.maxSteps` 10 → 5, `bySteps` `[[5,0.5],[3,0.25],[2,0.12]]` (still collision tracks only).
3. **Re-announcement:** `_Track.approach_done`; a track announced before is announced again once when its kind becomes `approach` ("person approaching at 12:15"). The label gap (5 s) and the world memory (`mem_approach`) still apply.
4. **Motion states** (`_motion_state`): standing = |own speed along the line of sight| < 0.3 m/s held 1 s and no sideways motion; approaching / moving away ≥ 0.4 m/s (kept down to 0.3); anything else is unknown and gets the plain phrase. `stationaryMps` is no longer used. See the lateral-rate investigation below: **no `crossing` state** (the rate does not separate), the rate is a veto for "standing" only.
5. **Unknown motion near the user:** diagnosis and the rules below.
6. **"Curb" → "kerb"** in `audio.js` (`PRONUNCIATIONS`, `pronounce()`), text of events and reviews unchanged, `spoken` in the client-log `speak` entry. The user verifies by ear.

**Lateral rate — what was measured** (4929 0–110 s, ground truth by the user's note: person 743 walks left at 40–42 s). The v26.1.11 lateral-offset slope is noise-dominated (poles p90 1.4–2.4 m/s). New: `_cross_velocity`: bearing of the bbox centre plus the camera heading (so our turn cancels), linear fit over ~1 s, speed across the view = `R · rate − v · sin(bearing)` (a static point drifts outwards at `v sin θ / R`; `R = hypot(distance, lateral)`, values at the window's middle). Results (`crossMps`, |value|):
- static **poles**: 357 samples median 0.29, p90 1.26 m/s; by range: < 6 m median 0.20 / p90 1.25 (16 % of frames above 0.6), 6–12 m 0.28 / 0.62 (12 %), > 12 m 0.54 / 1.87 (42 %). All static classes within 12 m: 40 % of frames above 0.6, p90 1.5. On review 4 (depth distances): poles median 0.41, p90 1.5.
- **track 743** at 40.7–42.3 s (moving left): 0.31 → 0.46 → 0.57 → 0.61–0.80 m/s (sign: left).
- A longer window (1.5 / 2 s) does not help (poles p90 1.0–1.3); bbox centre vs. contact point: 10 % better for the centre. The old formula without the parallax term and with `R = distance` was worse (poles p90 0.9–1.25 within 12 m, 35–90° bearings worst).
- **Verdict: does not separate** (a walking-left person 0.6–0.8 against poles at p90 0.6–1.25), so no "moving left/right" phrase and no `crossing` state. The rate is used as the veto for "standing" (≥ 0.6 m/s means "maybe moving sideways"): costs a "standing" in ~12–16 % of the frames of a really standing person, which then gets the plain phrase.
- 743 on the new logic: smoothed own speed −0.6 m/s from 41.0 s (closing 0.5–0.96 against our 1.32) → "moving away" at 3 m to the side: outside the lane, silent. Before that (40.2–40.8 s) the speed is 0 ± 0.2 with cross −0.4 … −0.5 → unknown (a single 5-step beep at 40.8, see below). The "standing" at 41.8 is gone.

**Unknown motion at 90.8 s — why, and what changed.** Track 2147 steps into view close by (first frame 90.34 s, 6.3 steps); at 90.84 s it was 0.5 s old, a closing speed needed ≥ 0.75 s (and 3 points) of history, and from 91.3 s its bbox touches the bottom edge, which clears the history (a clipped contact row is only a lower bound), so it never had one while it was announced. Now: **people get a closing speed after 0.45 s / 3 points** (`tracking.peopleMotionMinSeconds`; poles and the gait witnesses keep 0.75 s); at 90.84 s it reads +1.4 m/s towards us. And where motion is still unknown, a person within 5 steps (`roles.unknownMotionBeepSteps`) and inside `movingLaneHalfWidthM` (3 m) is `collision` (beeps only; not while the user stands). **Δ extra:** with the motion known the person was *not* a danger (lateral 2.15 m > the 1.5 m collision half-width), i.e. the phrase the user had ticked disappeared; so a person measured approaching, within 5 steps, closing ≥ 0.2 m/s and inside the 3 m zone is on a collision course regardless of the predicted lateral position ("passing at arm's length, coming towards us" beeps). Result: "person approaching at 12:45" + beeps from 90.84 s at 5 → 3 steps.

**Result on 4929 0–110 s** (Lab run `fe79e205dd48`; v26.1.11 = run `2ced2e0f2909`, identical to the logic re-run on the fixture):

| | v26.1.11 | v26.1.12 |
|---|---|---|
| speech | 15 | **13** |
| beep episodes | 4 | **5** |

Phrases before: 0.7 obstacle at 11:15 in 5; 3.2 building at 12:45 in 4; 15.5 pole at 12:15 in 11; 18.4 obstacle at 12:45 in 4; 28.8 pole at 12 in 8; 30.3 person moving away at 11:45; 38.0 crosswalk at 12 in 4; 39.3 curb at 12 in 3; 41.8 person standing at 1 in 4; 49.8 obstacle at 11 in 3; 52.3 crosswalk at 10:15 in 4; 54.7 and 63.5 person moving away at 12; 90.8 person at 12:45 in 5; 105.1 person standing at 12:15 in 14. Beeps before: 28.8 pole 8 steps; 39.5 obstacle 5 steps; 43.2 person 6→5; 76.5 person 9 steps.
Phrases after: the same up to 39.3 (incl. 30.3); 41.8 gone; 43.2 **person moving away at 12**; 52.3 crosswalk; 56.0 **obstacle at 1:45 in 3** (49.8's obstacle, see below); 76.5 **person approaching at 12:15**; 90.8 **person approaching at 12:45**; 54.7, 63.5, 105.1 gone. Beeps after: 39.5 obstacle 5 steps (kept); 40.8 person at 1, 5 steps (unknown motion, one beep); 46.7–52.9 person at 12:45, 4→2 steps (approaching, then unknown at 2 steps, 6 s); 90.8 person at 1:30, 5→3 steps; 92.0 person at 1:15, 3 steps.

**What each review-5 entry with a note or ✗/⊘ now produces:**
- 39.3 "speech should match text" → text unchanged `curb at 12 in 3`; the Lab speaks "kerb".
- 41.8 ✗ "standing at 1 in 4" → nothing (track 743: unknown, then "moving away" at 3 m to the side = silent).
- 54.7, 63.5 ⊘ "moving away at 12" (12.4 / 12.2 steps) → nothing (beyond 10 steps).
- 76.5 ✗ beeps at 9 steps → **speech** `person approaching at 12:15` at the same instant (track 1504, re-announced after "moving away" at 63.5), no beeps.
- 90.8 ✓ "should also beep" → `person approaching at 12:45` and beeps from the same instant (5 → 3 steps).
- 105.1 ✗ "standing at 12:15 in 14" → nothing (14 steps; and the track reads −0.6 m/s = moving away, never standing).
- ✓ entries: 10 of 12 are still produced; moved: **28.8 beeps pole 8 steps** (beeps start at 5), **43.2 beeps person 6→5** (the person walks away at −0.55 … −0.58 m/s: now "person moving away at 12", no beeps), **49.8 obstacle at 11 in 3** (spoken at 56.0 as "obstacle at 1:45 in 3": the person 889 at 46.5–49 s is now an approaching-at-arm's-length danger, remembered from the "moving away" of 43.2 s and so silent, and a danger holds the context phrase back until it goes stale after 3 s).

**Δ / open items:**
- **Δ (tests):** review 1–4 expectations changed where a decision moves them: version strings; review 2 (35.3 beeps 7 steps leave, the 49.5 phrase is "person approaching at 1", beeps may flicker between two tones); review 3 (the 48.5 obstacle beeps are taken over by a person 2 steps away who beeps from 47.8 s as an unknown-motion person; 106.98 and 196.32 are movers beyond 10 steps; 118.66 has "person approaching at 12:45" in the cold window, which has not named the person before); review 4 (`R4_BEYOND_REACH`: 28.0, 74.5, 190.5, 200.3, 371.5, 462.2, 467.2 are movers named at 11–15 steps; 48.7 beeps at 5.5 steps). Pinned by `test_review4_the_entries_that_left_are_beyond_the_new_reach`.
- **More beeps near people:** unknown motion within 5 steps beeps, and so does an approaching person at arm's length: on 0–110 s 5 beep episodes against 4, in review 2/3 windows several people 2–3 steps beside the path now beep (they beeped only when in the lane before). The user should judge whether that is the wanted behaviour; the knob is `unknownMotionBeepSteps` and `movingLaneHalfWidthM`.
- **43.2 s:** a person measured walking away at 0.55 m/s while we gain on them (closing 0.7–1.0) no longer beeps ("moving away" carries no beeps, v26.1.11); the user had ticked those beeps. If they want it back: beep a receding person we are catching up on within 5 steps.
- **Context behind a muted danger** (49.8 s) is a v26.1.7 mechanism, left alone.
- **Lateral rate** could separate with the depth model (distance noise is the main error source); re-try when review footage has depth.
- The pronunciation is Lab-only (`audio.js`); the iOS app speaks the text.

**Tests:** 398 passed, 6 skipped (373 before); `tests/test_collision_v26112.py` (24 tests: one or more per rule and the review-5 block), browser E2E (`tests/e2e/run.sh`, `audio.js` changed): 40 passed (39 before + `test_pronunciation_map_changes_the_spoken_text_only`).

## v26.1.13 — review 6: phrase window for people, early warning for fast movers, strict beeps (plan [`plans/v26.1.13.md`](plans/v26.1.13.md), fixtures `4929_review6`)
**Review 6** (run `36d9d120d801`, 4929 0–900 s, 736p, DA2 depth, model `…-1280`, collision v26.1.12, reviewed up to 449 s): **36 ✓, 0 ✗, 10 ⊘, 2 added**, notes on 9. The user wants: people announced once at 5–10 steps, with the distance, even when they will not collide ("good to know someone is there"); **under 5 steps only beeps**; riders and vehicles on or near a collision course announced as early as possible, without a distance; beeps only when really on a collision course; no context phrase for things beside the path that are not in the way; and a person who walks towards us must not be called "standing". The fixtures (`tests/fixtures/4929_review6.{json,npz}`) were saved from the run and `GET /api/reviews/export` **before** the version bump; `debug/lab/reviews/4929.json`, `run.json`, `events.json` and the export are also backed up outside the repo.

**Fixture format (Δ to the plan).** One window **0–452 s** (2713 frames, 27 MB), not the four windows of the plan: cold windows do not reproduce the run (a window starting at 100 s or even 60 s moves the 180.7 s person from "approaching at 1:15" to "standing", the depth scale and ego state need the whole history; only a start at 0 reproduces the run exactly). To stay under 30 MB the depth maps (`w0_depth`, 68×120 float16) have their two lowest mantissa bits cleared (≤ 0.3 % error); the run's 0–452 s events are reproduced unchanged. Annotations (48, with the 2 `added`), settings and the 98 v26.1.12 system events are in the `.json`.

**Decisions** (the plan's five, as built; deviations marked **Δ**):
1. **People (person, animal):** spoken **once at 4.5–10 steps** (`peopleSpeakMinSteps` 4.5 so that "in 5" is allowed, `movingDangerSteps` 10) inside `peopleSpeakLateralM` = **2.75 m**, whatever their motion state, always with the distance: `person approaching at 12:15 in 9`, `person moving away at 12:30 in 8`, `person standing at … in N`, `person at … in N` (templates `approach` / `receding` got ` in {steps}`). **Under 5 steps** no speech and no final: such a person is a *silent danger* (`_Item.speak = false`) only when on a collision course, and only beeps. Zone: 2.4 m (the + at 111.6) must be in, the static person at 2.9–3.4 m (178–181 s) out; the lateral is noisy (±0.3 m), 2.5 m cut the 111.6 s person at 2.55 m, 3.0 m let the 2.9 m one in (+3 phrases on 0–452 s, +1 ✓), so 2.75.
2. **Fast movers (rider, vehicle: `classes.fast`):** a measured mover that is not receding is a danger (spoken, **no step limit**) when it closes (`courseMinClosingMps`), would reach us within `fastWarnSeconds` = **6 s** (distance / closing), is within `fastWarnMaxM` = 30 m, its predicted lateral at the meeting is within `movingLaneHalfWidthM` (3.0 m) **and** its present lateral is within the old reach (riders 3.0 m, vehicles `laneHalfWidthM + 1.0`; without that a car crossing 7 m away at 4 m/s sideways was announced). New template `approachFast` (`cyclist approaching at 11`, no distance, also as a final); `collision` (beeps) only on the real collision course of item 3. **Investigation, 445.3 s (track 13381):** it is the right-hand one of **two cyclists riding side by side** (frame 445.32: the pair at x 0.45 and 0.35). The same rider was tracked as 13358 from 442.98 s (17.8 m) with a measured approach (closing 4.4 m/s) from 443.49 s (15.4 m, 21 steps), lost at 443.99 s (10.9 m) and re-detected as 13381 at 444.49 s (9.2 m, 12 steps, no history); 13381 itself was first confirmed approaching at 445.15 s (6.1 m, 8 steps) and spoken at 445.32 s (6.5 steps): v26.1.12 only knew the new track. v26.1.13 speaks 13358 at **443.65 s** (13.6 m, 18 steps), 1.7 s / 7 m earlier. The left cyclist (13351 → 13390 → …, lateral −1.9 … −2.2 m, 11:45–11:30) was never a danger in v26.1.12 (1.5 m gate), and is the "position is wrong" half of it. **Clock:** `_bottom_point` takes the column of the lowest row nearest the image centre; for a bicycle + rider (bbox 0.42–0.48) that is the wheel's inner edge (x 0.477, "12") against the body at 0.45 ("11:45"). **Δ extra:** a rider's column is the **middle of its lowest row** (`detect_items`); 13381 at 445.32 s now reads 11:45 (−0.57 m). **191.5 s (track 4798):** first seen 189.65 s at 14.3 m (19 steps), closing known from 190.15 s (10.1 m, 8 m/s), danger from 190.32 s: spoken **1.2 s earlier** ("cyclist approaching at 11:45", 9.5 m), lateral −1.9 m: no beeps. The remaining gap is the detection: the rider is first seen ≤ 14 m out, with a closing speed after 0.45 s (`peopleMotionMinSeconds`); a second cyclist of a group is held back by the 5 s label gap (`LABEL_COOLDOWN_S`) unless both are danger in the same frame ("cyclist approaching at 11:45 and 12", review 4's window).
3. **Beeps only on a real collision course:** `beepLateralM` = **0.9 m** (lane half 0.6 + body): `|lateral|` for a person who stands or whose motion is unknown, the predicted `|lateral + lat_vel·T|` at the meeting for a measured mover (`_on_collision_course`, `T ≤ courseMaxSeconds`), and `stepsTo ≤ tones.maxSteps` (5, unchanged). Removed: v26.1.12's "unknown motion within 5 steps / 3 m" and "approaching within 5 steps / 3 m"; `movingCollisionHalfWidthM` (1.5) and `unknownMotionBeepSteps` are gone. **No lateral threshold separates the beep verdicts** (see open items): ✓ beeps at 2.4 / 2.4 / 2.0 / 1.9 / 2.6 m and ⊘ beeps at 3.0 / 2.1 / 1.2–1.4 / 1.9 m. **Review 5's 90.8 case** (lateral 2.1 m, 5 steps) is now spoken at 5 steps ("person approaching at 12:45 in 5") and no longer beeps.
4. **Context beside the path:** `contextMaxLateralM` 3.0 → **2.5 m**, plus `contextNearSteps` 3 / `contextNearLateralM` 3.0 (Δ, the plan's "combined rule"). The laterals of the context entries of reviews 4–6: ✓ at 1.2, 1.6, 1.9, 1.9, 2.2, 2.3, 2.4, 2.9 (59.2 s, 2.6 steps) and 2.9 (448.99 s, 3.8 steps); ⊘ at 2.9 (132.3 s, 7.8 steps) and 2.86 (179.5 s, 3.7 steps). Lateral alone cannot separate them; 179.5 s (3.7 steps) and 448.99 s (3.8 steps) cannot be separated by lateral and steps either. The rule keeps 59.2 s, removes both ⊘ entries and **loses 448.99 s** (a ✓).
5. **Ego speed for the motion states:** `_robust_speed`: the median of the last `egoMedianSeconds` = 3 s of the cadence-based speed (also for `_cross_velocity`). **374.0 s (track 11195):** the "spike" is not momentary: the cadence estimate flips between 1.45–1.5 Hz (1.1 m/s) and 2.3–2.8 Hz (1.7–2.07 m/s, a harmonic) in runs of 2–6 s (360–378 s: 1.1 / 2.0 / 1.1 / 2.0 / 1.1 / 1.8–2.07 / 1.1 / 2.4 / 1.3 m/s), 368.5–374.0 s all in the high mode; the median of 3 s therefore sits at ~1.95 m/s until about 375.5 s. State of 11195 with the change: closing 1.4–1.7 m/s, **never "standing"** (v26.1.12: standing at 374.0 s), unknown (plain phrase "person at 12:30 in 6" at 375.17 s) until the median has left the high mode, **approaching from 375.67 s**; in the review 4 window run (cold, no ego history) "person approaching at 12:15 in 10" at 374.0 s. The cause is the cadence harmonic (open item), not the speed noise.

**Result on 4929 0–450 s** (Lab run `70e334e9a444`, GPU; v26.1.12 = run `36d9d120d801` on the CPU, depth values differ slightly, `0–450 s` events of the run compared):

| | v26.1.12 | v26.1.13 |
|---|---|---|
| speech | 35 | **33** |
| beep episodes / tones | 11 / 52 | **1 / 2** |

Speech before → after: the review-6 ⊘ phrases (78.2, 90.5 "person approaching at 1"; 132.3, 179.5 obstacles; 180.7 "person approaching at 1:15"; 203.8 "person approaching at 12:45") are gone or replaced; the people phrases now carry the distance and come at 5–10 steps: 30.5 **person moving away at 11:45 in 7**; 76.5 **person approaching at 12:15 in 9** (the added entry); 90.7 **person approaching at 12:45 in 5**; 108.5 **person moving away at 12:15 in 10**; 202.7 **person approaching at 12:30 in 9** (203.8: 1.2 s earlier, with the distance); 291.0 **person moving away at 11:45 in 10** (292.7's "standing"); 356.7 **person at 11:30 in 5**; 375.2 **person at 12:30 in 6** (374.0's person, no longer "standing"); riders: 190.3 **cyclist approaching at 11:45** (191.5), 443.65 **cyclist approaching at 12** (445.3); new context: 150.3 **obstacle at 1:45 in 3** and 188.98 **obstacle at 1:45 in 2** (the people dangers beside the path that held the context back are gone), 357.8 **pole at 1:30 in 2**. Gone for a decision: 352.7 / 366.5 phrases under 5 steps, 374.0 standing, 448.99 obstacle at 2.9 m, 48.5 "person at 12:45 in 5" (lateral 2.6–2.8 m flickering around the zone limit). Beeps before: 48.8, 78.2, 90.5, 91.1, 92.1, 180.7, 191.5, 203.8, 366.5, 376.0, 445.65; after: **445.65 beeps · cyclist at 11:45 · 4 steps** only (the cyclist, lateral −0.6 m).

**What each review-6 entry now produces** (fixture window run, `tests/test_collision_v26113.py`):
- ⊘ (10): all gone. 78.2 and 90.5 "person approaching at 1" → nothing at 78 s; the person of 90.5 s is announced at 9 steps in the fixture run (88.8 s, "person approaching at 12:30 in 9"), at 5 steps in the Lab run (90.7 s, track 2026 appears at 7 steps and is inside the window for 0.5 s); 132.3 / 179.5 obstacles → nothing; 180.7 person (phrase + beeps) → nothing; 191.5 beeps → none (the phrase is 190.3 s); 203.8 phrase → **202.66 s "person approaching at 12:30 in 8"**, no beeps; 203.8 and 376.0 beeps → none.
- Added: 76.6 "person approaching at 12:15 in 9" → produced at 76.49 s. 111.6 "person moving away at 12:30 in 8" (track 2481, lateral 2.4–2.7 m, motion unknown, reaching 3.0 m after two frames) → **not produced**: "person moving away at 12:15 in 9" is spoken at 108.5 s (another person at the same place, track 2137) and the 5 s label gap holds the second one back; the first confirmation of 2481 needs two frames inside the zone.
- Noted ✓: 191.5 cyclist → 1.2 s earlier, no distance (190.3 s); 374.0 → see item 5; 445.3 → 1.7 s earlier (443.65 s), clock fixed (item 2).
- **✓ entries (36):** **22 still produced** (same text pattern ±1.5 s); the 14 that are not are listed in the first open item below.

**Δ / open items:**
- **The ✓ person beeps are lost (6 of the 7 ✓ beeps).** The user ticked beeps at lateral 2.4 (48.8, 78.2, 90.5 s), 2.0 (91.1), 1.9 (92.1) and 2.6 m (366.5 s) and marked beeps at 3.0 (180.7), 2.1 (376.0), 1.2–1.4 (203.8, unknown motion, short tracks) and 1.9 m (cyclist 191.5, passing). Nothing separates them by lateral (376.0 s at 2.1 m diverging, lateral velocity +0.2, against 78.2 s at 2.4 m converging at 0.3 m/s, and 48.8 s at 2.4 m converging at 0.7 m/s). A candidate if the user wants some of them back: a person measured approaching within 5 steps whose lateral is ≤ 2.6 m **and decreasing**; not built (it is a rule nobody has reviewed). Of the 36 ✓: the 6 beeps, 366.5 phrase (3 steps), 352.7 (1.4 steps), the 2 cyclists (replaced by earlier phrases), 292.7 (replaced by 291.0), 48.5, 357.0 (thin notice, crowd), 448.99 are not produced.
- **Cadence harmonic.** The cadence flips between ~1.5 and ~2.5–2.8 Hz (item 5); fixing it (the step rate at 2.7 Hz is not walking) would help every motion state; a median cannot.
- **More context phrases** (150.3, 188.98 s): fewer dangers hold the context back, nothing was judged on them.
- **Track hand-off of fast movers** (13358 → 13381): a new track has no motion for 0.45 s; matching a fast mover by its extrapolated position would announce even earlier.
- **GPU vs CPU:** the Lab run on the GPU differs slightly from the CPU-derived fixture run in 2 phrases (88.8 s / 405.3 s "person approaching …" are in the fixture run only).
- The v26.1.12 test expectations changed where a decision moves them: `test_collision.py` (people zone, group / re-announcement phrases now with the distance), `test_collision_v26111.py` (collision course at 0.9 m, receding person beside the path is spoken, phrase strings), `test_collision_v26112.py` (unknown-motion / arm's-length beeps replaced by the v26.1.13 behaviour, 76.5 and 90.8 s of review 5: speech with the distance, no beeps), regression: review 2 (start summary leads with the nearest obstacle "10:45", the person at 46–49 s is tracked but not spoken: 4.7 steps when it reaches the zone, context lateral invariant), review 3 (118.66 s memory-less person, 47.5 "person at 1 in 4" under 5 steps), review 4 (`R4_BEYOND_REACH` without 190.5 / 371.5 / 462.2, `R4_KEPT` without 48.5 / 366.5 / 445.3, the cyclist and 374 s tests, people with distance / riders without).

**Beep rule (b), evaluated and not adopted (coordinator request after the first review).** Candidate: a person/animal measured `approaching` (3 s median ego speed), within 5 steps, |lateral| ≤ `beepApproachLateralM`, and converging on the path axis (heading-corrected linear fit of the lateral position over the last 1 s, ≥ `beepConvergeMps`), in addition to the 0.9 m rule; riders and vehicles unchanged. Built, run on the review 6 fixture window over a grid, then removed (no config keys, no code left). The convergence rate is noisy frame to frame (the same track swings −0.6 … +1.1 m/s) and close people are clipped at the image bottom, which clears their history (convergence unknown below ~3 steps). Per entry (lateral m / convergence m/s / state at the beep, approaching = measured toward us):
| entry | verdict | lateral | convergence | state |
|---|---|---|---|---|
| 48.8 person 12:30 | ✓ | 1.0–1.4 | 1.1 → −0.04 | standing / unknown (not approaching) |
| 78.2 person 1:30 | ✓ | 2.4 → 1.7 | 0.7 (5.5 steps) → −0.2 (≤ 4 steps) | approaching |
| 90.5 person 1:15 (1890) | ✓ | 2.4–2.5 | 0.4, 1.1, 1.5 | approaching |
| 91.1 person 1:30 (2026) | ✓ | 2.0–2.3 | 0.3, 0.06, unknown | approaching |
| 92.1 person 1:15 | ✓ | 1.9–2.1 | unknown (clipped) | approaching |
| 366.5 person 1:45 | ✓ | 2.5–2.9 | 1.4 → −0.1 | moving away |
| 445.65 cyclist | ✓ | 0.6–0.8 | 0.04, 0.8 | (a) keeps it |
| 180.7 person 1:30 | ⊘ | 3.0–3.6 | −0.5 … unknown | approaching |
| 191.5 cyclist | ⊘ | 1.9 | 0.8 | rider: only (a) |
| 203.8 person (4984) | ⊘ | 1.6–1.9 | 0.27, 0.37, 0.66, 0.95, 0.76 | approaching |
| 376.0 person (11195) | ⊘ | 2.0–2.4 | 0.09, **1.06**, 0.97 | approaching |
Review 4 / 5 ✓ person beeps are at 6–8 steps or 1–2 steps (nothing within 5 steps to test). Grid on the review 6 window (beep episodes in 0–452 s; rule (a) alone = 1): lateral 2.0: 2 episodes for convergence 0.15–0.5 (brings back ⊘ 203.8), 1 for ≥ 0.8; lateral 2.6: **4 episodes** for 0.15–0.5 (✓ 90.5 and 92.1 back, but also ⊘ 203.8 and ⊘ 376.0), 3 for 0.8 (90.8 ✓, ⊘ 376.0), **1** for ≥ 1.1 (only the cyclist). The ⊘ 203.8 person converges at 0.3–0.95 m/s at 1.8 m, the ✓ 90.5 person at 0.4–1.5 m/s at 2.4 m, the ⊘ 376.0 person reaches 1.06: every setting that returns a ✓ beep returns a ⊘ one, and a lower lateral limit does not help because the ⊘ is the *closer* one. **Decision: keep the 0.9 m rule** (1 beep episode on 0–450 s, the ticked cyclist). The ✓ person beeps stay lost; if the user wants them back at the price of the 203.8 / 376.0 beeps, the knob is `beepLateralM`-style widening (not built).

**Tests:** **438 passed, 6 skipped** (398 passed, 6 skipped before); `tests/test_collision_v26113.py` (26 test functions, 39 cases: one or more per rule and one per review-6 entry on `4929_review6`), browser E2E (`tests/e2e/run.sh`): **40 passed** (no JS changed).

### v26.1.13 follow-up — a soft proximity sound for approaching people (plan [`plans/v26.1.13-followup-proximity.md`](plans/v26.1.13-followup-proximity.md))
The user answered the beep question above with option (c): **two sounds**, the parking beeps keep meaning "collision course", a softer, different one means "a person is close by and coming towards you". Done on the current version: **no bump** (`RnD/VERSION` and `collision.json` stay `v26.1.13`, no Lab wipe); the run `70e334e9a444` (never reviewed) was re-scored in place and stays reviewable. The plan was written as `v26.1.14` and renamed.

1. **Rule** (`_assign_role`, `_Item.proximity`; no role, so speech, context and the beeps are untouched): a person or animal (not riders / vehicles) that is measured **approaching** (`approaching`, i.e. not unknown, standing, receding or sideways), in the walking zone, within `proximitySteps` **5** and |lateral| ≤ `proximityLateralM` **2.6** m, and **not** on a collision course; confirmed for `confirmFrames` frames (track counter `prox_run`), cleared while we stand still and during warm-up. Spoken and soft at once (4.5–5 steps) is allowed: a phrase and a sound are different channels.
2. **Sound** (`tones.proximity`): **440 Hz** sine (collision: 880), **gain 0.25** (collision peak 0.5, so 50 %), attack 40 ms (collision 5 ms), a **double chirp** (2 × 0.12 s, 0.1 s apart) every **1.2 s**, a fixed rhythm that does not encode distance. Pan from the item as for the beeps.
3. **Switching:** a separate soft stream (nearest such person, 0.5 s hold for a lost track) runs next to the collision stream; while the collision stream is active (held tracks included) soft tones are dropped, so the two never play at once; a track turning into a collision course simply stops being `proximity`. Episodes per kind and track: `type: "beeps"`, `kind: "proximity"`, text `soft · person at 1:30 · 4→2 steps`. Every `tone` / `beeps` event carries `kind` (`collision` | `proximity`); `_tone_events` keeps its old call shape (the proximity stream is an optional fourth argument).
4. **Lab:** `audio.js` plays the sound from the event (`frequencyHz`, `gain` default 0.5, `chirp`); the speech code is untouched. The review panel labels a proximity episode `🔉 soft` (row `data-kind="proximity"`), verdicts work as for beeps (⊘ silences its tones in the preview); the Beeps checkbox covers both kinds; the audio log entry has `kind` and `gain`.

**Result on 4929 0–450 s** (Lab run `70e334e9a444`, re-scored in place; speech unchanged, 33): **1 collision episode** (445.7 s, cyclist at 11:45, 2 tones, as in v26.1.13) and **5 proximity episodes** (5 soft tones): 78.2 s (track 1742, "person at 1"), 90.7 s (1:15), 92.0 s (1:15), 204.0 s (12:45), 376.0 s (1).

**Review-6 beep entries now** (fixture run; `tests/test_collision_proximity.py`):
| entry | verdict | produces |
|---|---|---|
| 48.8 person 12:30 | ✓ | nothing (standing / unknown motion, not measured approaching) |
| 78.2 person 1:30 | ✓ | soft at 78.2 s, clock 1 (a different clock) |
| 90.5 person 1:15 | ✓ | soft at 90.7 s, 1:15 |
| 91.1 person 1:30 | ✓ | soft at 90.7 s (1:15) and 92.0 s |
| 92.1 person 1:15 | ✓ | soft at 92.0 s, 1:15 |
| 366.5 person 1:45 | ✓ | nothing (moving away, short track) |
| 445.65 cyclist | ✓ | collision beeps (unchanged) |
| 180.7 person 1:30 | ⊘ | nothing (3.0–3.6 m, outside the zone) |
| 191.5 cyclist | ⊘ | nothing (riders never get it) |
| 203.8 person | ⊘ | soft at 203.8 s (12:45, track 4984): the accepted trade-off of choosing (c) |
| 376.0 person | ⊘ | soft at 376.0 s (clock 1, track 11195): same |

**Δ / open items:** the two ⊘ person sounds (203.8, 376.0) are the price of (c) and will show up in the next review as soft episodes to judge; the soft sound is not played when we stand still (only collisions are); the sound parameters (440 Hz, 0.25, 1.2 s) are a first guess to be judged by ear; the 78.2 / 91.1 s ticks are matched by time and person only (clock differs by a quarter or two); soft episodes last one or two chirps (0.3–1.5 s) because the person is inside the 5 steps for a second or two.

**Tests:** **455 passed, 6 skipped** (438 before); new `tests/test_collision_proximity.py`, `tests/test_collision.py` (event keys) and the run helpers of `test_collision_regression.py` / the lost-ticks list of `test_collision_v26113.py` adapted; browser E2E (`tests/e2e/run.sh`): **41 passed** (the new `test_two_distinct_sounds_are_scheduled_and_the_review_panel_shows_the_kind` included).

### v26.1.13 follow-up — re-analysing a range that was already analysed (same version, no wipe)
The user pressed Analyse and saw no progress: run ids come from the request, the POST matched a finished run, and the UI silently loaded it. `POST /api/runs` now marks a reused finished run `"reused": true` (response only) and accepts `"force": true` to re-run it from scratch under the same id (reviews untouched); the UI says "already analysed ... Loaded it" with a Re-analyse button, and the Analyse button is re-enabled on every path.

### v26.1.13 follow-up — stuck speech engine notice (same version, no wipe)
On the user's Mac, Chrome's speech engine stayed stuck for the whole browser session (every utterance `speaking` but no `onstart`, reload useless, only Cmd+Q fixed it). The Lab now counts consecutive utterances that never started (watchdog firings) and, at 2, logs `speech-stuck` and shows a dismissable notice in the Audio panel with a per-platform "quit and reopen the browser" hint; any `onstart` clears it. Speech logic unchanged (CONTRACTS §12.2).

## v26.1.14 — crosswalk enter / exit tones; E2E on the renamed footage (plan [`plans/v26.1.14.md`](plans/v26.1.14.md), fixture `chest0002_crosswalk`)
The user asked for a warning when stepping into and out of a crosswalk ("a deeper, longer tone when stepping into it, a double deeper tone when stepping out") and for the E2E tests to be updated: the footage was renamed (`Chest-center-0001…0008`, `Head-center-0001…0011`; 4928 / 4929 are gone, 4929 is `Chest-center-0002`, same frames), so the suite failed with 422 "Unknown recording". No review existed, so no review fixtures were saved; before the bump the Chest runs were mined instead (below). **Note:** the Lab watches `RnD/VERSION` and wipes runs the moment it changes (it wiped the four runs while the unit tests were still running), so the fixture had to be, and was, saved first.

**Decisions** (the plan's three, as built):
1. **Crosswalk state** (`_CrosswalkTracker`, `config.crosswalk`): the share of crosswalk-class cells in `surfaces.seedBox` (bottom centre, under the feet). **In:** share ≥ **0.3** for **0.5 s** without a break, never while the user stands still. **Out:** share ≤ **0.15** for **0.7 s** without a break. The optional `under_last` support was **not** used (the box under the feet already excludes a crosswalk merely seen ahead, and the surface-evidence logic stays untouched).
2. **Sounds** (`tones.crosswalk`, kinds `crosswalk-enter` / `crosswalk-exit`, a `tone` event plus a `beeps` episode each, role `feature`): **330 Hz** (collision 880, proximity 440), gain **0.5** (the collision peak). In: **one tone of 0.6 s**. Out: **two tones of 0.2 s, 0.12 s apart** ("double deeper tone" read as the deep tone twice). Overlap with a collision / proximity tone: never dropped, shifted later by at most **0.3 s**. The speech phrase "crosswalk at 12 in N" is unchanged.
3. **Lab:** `audio.js` already plays a tone from the event fields (`frequencyHz`, `durationSeconds`, `gain`, `chirp`), so only its doc comment changed; the speech code is untouched. The review panel shows `🔊 tone` rows with `⇥ crosswalk in · one deep tone` / `⇤ crosswalk out · two deep tones` (row `data-kind` = the event kind) with ✓ ✗ ⊘; the Beeps checkbox covers them.
4. **E2E:** one source of truth in `tests/e2e/conftest.py`: `HACKEYE_E2E_RECORDING` (default `Chest-center-0002`, ≥ 125 s: the session run analyses its 0–120 s, which hold two crossings) and `HACKEYE_E2E_SHORT_RECORDING` (default `Chest-center-0005`, 88 s); a missing recording stops the session with a clear message, missing proxies are built first, `run.sh` passes the variables on. Durations come from the API (`clock()` mirrors the Lab's time format), so the range and add-form assertions that hard-coded 3.3 s / 51:33 follow the recording. **Δ to the plan:** the long one is not a short Chest recording: the windowing and review tests need > 90 s of analysed range, and `Chest-center-0002` has a ready proxy and is the 4929 footage the tests were written for. The short recording is longer than the old 3 s clip, so the resolution test analyses only 0–6 s (a full 88 s run at 576p timed out next to the training job). New E2E tests: crosswalk sounds scheduled (one 330 Hz oscillator, then two 0.32 s apart, deeper than 440 Hz, panel rows and kinds, Beeps checkbox), ⊘ silences, the run's own tones alternate in / out and one plays during playback. A new page hook `window.__osc` records oscillator starts.

**Thresholds from the data** (crosswalk share of the seed box per analysed frame; runs `341fd5511f4d` = Chest-center-0002 0–1062 s and `9a270e9a4328` = Chest-center-0001 0–532 s, 6 fps, before the wipe):
- Share segments (any share > 0.02, gaps < 1 s merged): **22** in Chest-0002 (the first nine are the review-6 footage 0–452 s) and **11** in Chest-0001. Of these **30 are real crossings** and **3 are flickers** (0.3 s or two frames: 354.2 s, 86.3 s, 321.3 s).
- Most crossings are short: **2.0–3.5 s** of share (narrow crosswalks over side streets and slip lanes, 3–5 m at walking pace); only 40.7–49.3 s (Chest-0002) and 61.0–69.7 s (Chest-0001) are 8–9 s. The plan expected 4–20 s; the data says 2–9 s, so `enterSeconds` / `exitSeconds` stay short.
- Parameter scan (enter share × hold, exit share × hold) over both runs, pairs found / expected 21 + 9: **enter 0.3, 0.5 s → 21 + 9 pairs, 0 false triggers**, durations 2.0–9.0 s. Enter 0.4 with a 0.67 s hold loses 3 crossings (19 + 8); **enter 0.5 / 0.5 s loses 9 of 30** (7 + 2: crossings whose share peaks at only 0.48–0.57 never hold 0.5), so 0.5 is too strict; enter 0.3 with a 0.33 s hold finds the same 21 + 9 but the flickers (< 0.33 s) are then only just rejected, so 0.5 s was kept. The exit level hardly matters (0.05 / 0.15, 0.5 / 0.7 s give the same pairs within 0.2 s); 0.15 / 0.7 s was chosen so a gap between stripes (≤ 0.5 s at 0 share) does not end a crossing.
- The real pipeline (stationary state included) gives the same pairs: **`4929_review6` 0–452 s: 8 pairs** (41.3–50.3, 62.0–64.8, 142.7–145.5, 155.3–157.8, 219.7–222.2, 234.7–236.7, 392.2–394.9, 404.7–407.3; the 354.2 s flicker none), the saved **`chest0002_crosswalk`** windows **11 pairs** (2.5–9.0 s), the verification run **6 pairs**.

**Fixture `tests/fixtures/chest0002_crosswalk.{json,npz}`** (6.9 MB, from run `341fd5511f4d`): six windows 36–66, 136–160, 350–358 (the flicker), 384–410, 580–590, 1034–1056 s with grids, times, 24 Hz motion and DA2 depth (float16, two mantissa bits cleared), run cold by `_run_windows`; the crosswalk rule needs only the grids and the stationary flag.

**Verification** (Lab run `1b12ee4e9cf8`, `Chest-center-0001` **150–450 s**, 736p, DA2, 6 fps, model `…-1280`, GPU, no review to anchor on): **6 enter / exit pairs**, 176.0 → 178.8, 189.6 → 192.3, 261.2 → 263.7, 277.7 → 279.3, 358.0 → 360.7, 371.5 → 374.2 s: exactly the six crosswalk-share segments of that window (175.3, 189.0, 260.3, 276.0, 357.3, 370.7 s; the enter tone comes 0.65–1.65 s after the first crosswalk pixels under the feet, the exit tone 0.8–1.0 s after the last); the spoken "crosswalk at … in N" phrase comes 7.7–9.0 s before each enter (168.3, 181.5, 252.7, 268.7, 350.0, 363.3 s) and is unchanged. No tone overlaps a collision tone in this window (0 collision, 4 proximity tones).

**Δ / open items:** crossing durations are 2–3 s for most crossings, so the "in" and "out" tones come within ~2.5 s of each other; the user may want to judge by ear whether the 0.6 s "in" tone is too long there. The tone is emitted 0.5 s (in) / 0.7 s (out) after the first / last crosswalk pixels under the feet; it cannot be earlier without a prediction. A crosswalk drawn across a wide road with a median or faded stripes can split into two crossings (the share must stay ≤ 0.15 for 0.7 s). The Head recordings were not mined (the head mount's seed box sees farther ahead). Sound parameters (330 Hz, 0.6 s, 2 × 0.2 s) are a first choice to be judged by ear.

**Tests:** unit **472 passed, 6 skipped** (455 before; new `tests/test_collision_crosswalk.py`, 17 tests, and the `tones()` helper of `test_collision.py` ignores crosswalk kinds); browser E2E (`tests/e2e/run.sh`): **48 passed** (4 new crosswalk tests, the recording-length-dependent assertions adapted; the first run on the renamed footage had 2 failures that were fixed: an overly broad "no tone" assertion in a new test and the 88 s resolution run).

**v26.1.14 follow-up — ETA on the analyse progress bar** (user: "ETA on the analyse progress bar"). Client only (`lab/static/js/eta.js`, used by `watchRun`; no server change, no bump, no Lab wipe): a 60 s sliding-window rate (average since `createdAt` when the page is opened mid-run), EMA-smoothed and re-based at most every 5 s so the text does not jitter, `estimating…` early, `stalled?` after 60 s without progress; the Runs list tag and the Analyse tooltip show it too. Tests: `tests/e2e/test_eta.py` (formatter, tracker states, a real run).

## v26.1.15 — review 7: speech on time (player queue), people warm-up, no start silence (plan [`plans/v26.1.15.md`](plans/v26.1.15.md), fixture `chest0004_review7`)
**Review 7** (run `180acf11eedb`, Chest-center-0004, 0–454 s, 736p, DA2, CPU, collision v26.1.14, reviewed up to 7.8 s): 4 ✓, 1 ⊘, 1 added. At 2.0 s the user added "Person static at 12 in 9" ("Danger overlaps other notifications … it waits for previous speech to finish talking. This is a no-go: if speech is to start out of time, don't.") and removed the 3.2 s "person approaching at 12:15 in 8" ("same person/persons at 2.0"). Then, via the coordinator: notifications must be able to start at t = 0 of the analysed range, not after a first-second warm-up. **Version:** the user chose the **bump** (v26.1.15), so the Lab wiped the runs and the review; the fixture was saved first and runs `180acf11eedb`, `341fd5511f4d`, `1b12ee4e9cf8` were mined offline before `RnD/VERSION` was written (no in-place re-scores).

**Diagnosis.** Tracks 28 / 44 (two persons) are first detected at **0.17 / 0.33 s** at 13 steps, become dangers (≤ 10 steps) at **1.84 s** and were held by `_motion_pending` (1.5 s) and said at 3.2 s; the ego speed was 0.59 m/s at 2.0 s and 1.28 at 3.2 s (the 3 s median still ramping), so a standing person read "approaching". In the browser every phrase went to `speechSynthesis`, which queues it behind whatever is still talking: the phrases before it took ~3 s to say.

**Decisions** (the plan's four, plus the three added during the work; deviations marked **Δ**):
1. **Player queue** (`audio.js`, `AudioEngine`): one utterance at a time is handed to `speechSynthesis`. Priority `final 5 > danger 4 > feature / thin 3 > surface 2 > context 1`; a phrase of higher priority than the one speaking cancels it and speaks at once (`cancelNow("preempt")`, after 60 ms on Android only), equal or lower waits (best first, then oldest). A waiting phrase that cannot start within `SPEECH_LATE_S` = **1.0 s of media time** of its event time is dropped. Logged: audio log `speech-preempted` {text, by, started} and `speech-dropped-late` {text, lateS}, the same two in the client log. "Hear review edits" phrases use the same speech list and so the same queue. **Hard-won behaviour kept:** the system voice rule, the pronunciation map, the prime, `unstick()` before each handed phrase (not after our own preempt cancel), the watchdog (1.5 s, one retry, voice drop) and the stuck notice (2 consecutive) are unchanged; a preempted utterance is *retired* before the cancel (its events end nothing, the watchdog is settled, `noteNoStart` is never called), and an utterance cut off before its `onstart` goes back to the queue. The "Test speech" button still speaks directly in the click. **Δ** (not in the plan, needed for safety of the queue): (a) every phrase of one tick window is queued (before, only one of them was kept); (b) an utterance the engine silently lost (`speechSynthesis` idle for 500 ms after `speak()`, no end event: `utt-lost`) or one that never ends (4 s + 150 ms per character: `utt-hung`, cancelled) is let go, otherwise one missing `onend` (WebKit has done this) would block every later phrase; (c) the E2E `HOOKS` stub now reports `onstart` / `onend` (it never did), because the queue waits for the end of each phrase.
2. **No motion wait while the ego speed is not settled** (`_Item.ego_settled`, `SpeechPolicy._motion_pending`). *Settled* = the history of the robust ego speed is unbroken for the full `egoMedianSeconds` (3 s); a measured standing user is settled at once; a gap in the ego speed restarts it. A person gets the plain phrase immediately.
3. **Motion words need a settled ego speed** (`SpeechPolicy._kind`): standing / stopped, moving away, approaching (person) only when settled; otherwise the plain phrase. **Δ:** a rider / vehicle `approach` keeps its word without it (it closes at several m/s; review 4 / 6 asked for it as early as possible, and after every stop-and-go the 3 s would delay the warning; the first version without this exception broke 3 cyclist tests). Mid-run, a cadence dropout restarts the history: three phrases changed for that reason in the mined runs (below).
4. **Review 7 as built:** one person phrase at **2.002 s**, "person at 12:15 in 10" (plain), nothing for them at 3.2 s, no "approaching" in 0–8 s.
5. **No start silence** (added). Every gate on the first seconds of a run, what it guards, how long it delays (config in `common/config/collision.json`, constants in `collision.py`):

| gate | guards | delay | now |
|---|---|---|---|
| `warm` (`WARMUP_S` 1.5 s): danger / feature roles forced to `none`, proximity off | "no distances on a guessed horizon" | 1.5 s | **removed** (horizon = mean of the raw estimates so far, else the mount / body preset) |
| `MIN_TRACK_AGE_S` 0.5 s (`settled`) | single-frame flicker | 0.5 s | **not in the first `WARMUP_S`**; later unchanged |
| `confirmFrames` 2 | flicker | 0.33 s (0.17 s to the 2nd frame at 6 fps) | **kept** (the minimum) |
| depth anchor `initialAnchorMinFrames` 3 plane fits | depth scale | 0.33–0.5 s | kept (the ground-geometry distance with the body / mount camera height is used until then, as before); not changed to 1: `test_collision_body` / `_depth_initial` define 3 and a one-fit median is noisy |
| cadence (step rate) 2.4 s, then the 3 s median | ego speed, motion states | 2.4 s + 3 s | kept; until settled only plain phrases (decision 3), no motion wait (decision 2) |
| start summary `summaryHoldSeconds` 0.5 s | one grouped phrase for the first view | 0.5 s, context only | kept (the user ticked that grouped phrase; context is not a danger) |
| `globalMinGapSeconds` 2.5 s | context / surface chatter | up to 2.5 s | kept |
| `priorityMinGapSeconds` 1.0 s | danger / feature chatter | up to 1.0 s | **a phrase with a danger in it is no longer delayed by an earlier feature / context phrase** (only by an earlier danger / final); review 7: the person was held 0.17 s behind "pole at 11:30 in 8" (1.17 s) and then lost to a role flicker until 2.67 s |
| `dangerSteps` / `movingDangerSteps` 10, `peopleSpeakMinSteps` 4.5 | reach | geometry | kept: the two persons are 13 steps away until 1.8 s, so they cannot be said "within ~0.35 s of the first detection"; they are said at the first confirmed frame inside 10 steps |

**Review 7, 0–8 s, before → after** (events at run start reproduce exactly from the fixture and from a fresh Lab run of 0–10 s, verified below): before (v26.1.14): 0.67 "building at 1:15 in 2, obstacle at 12:45 in 2", 0.83 "pole at 11:45 in 9", 3.17 "person approaching at 12:15 in 8", 6.01 beeps person at 12 · 5 steps, 7.84 "vegetation at 12 in 9". After: **0.17 "obstacle at 12:30 in 2" (role final) + beeps (2 steps)**, **1.17 "pole at 11:30 in 8"**, **2.00 "person at 12:15 in 10"**, 6.01 beeps person at 12 · 5 steps (kept), **6.17 "building at 1:30 in 2"**, 7.84 "vegetation at 12 in 9" (kept). The two ✓ context entries of the opening changed: the obstacle 2–3 steps ahead in the lane is a danger (final, beeps) as soon as it is confirmed, and the building, which the 2.5 s global gap pushed behind it, comes at 6.17 s (it was in the first summary before). Judge by ear.

**Mined before the wipe** (new code on the stored grids / motion / depth vs the stored v26.1.14 events; the full-length runs):
- `180acf11eedb` (Chest-0004, 0–454 s): speech **79 → 82**, beeps episodes 41 → 42. Besides the opening above: "building at 1:15 in 2, obstacle at 1 in 2" 54.50 → "building at 1:30 in 2, obstacle at 1 in 2" 54.67; "person moving away at 12 in 10" 98.16 → 97.16; new "vehicle approaching at 11:45" 52.17 and "vehicle approaching at 12:15" 234.0 (not investigated; most likely phrases the old feature gap held back).
- `341fd5511f4d` (Chest-0002, 0–1062 s): speech **74 → 75**, beeps 55 → 55, first 10 s unchanged (0.67 "obstacle at 11:15 in 5", 3.17 "building at 12:45 in 4"). Mid-run: "cyclist approaching at 11:45" 490.16 / 906.49 → "cyclist approaching at 12" 488.99 / 905.16 (earlier, a different clock quarter); "person approaching at 12:45 in 7" 785.66 and "person moving away at 11:45 in 5" 915.83 became plain "person at …" (the ego speed was not settled there: a cadence dropout); new "person approaching at 12:45 in 5" at 960.34.
- `1b12ee4e9cf8` (Chest-0001, 0–532 s): speech **23 → 23**, beeps 15 → 15, identical.

**Regression fixtures** (cold windows, so each window start now speaks at once; `4929_review6`, the full 0–452 s run from its start, is **identical** to v26.1.14: 56 / 56 events): review 1 w1 (14 s) "building at 1 in 2", "pole at 12:15 in 9", "obstacle at 12:30 in 6" → "pole at 12 in 8", "obstacle at 12:45 in 5"; w2 "pole at 12 in 9" 0.65 → 0.32 s plus "obstacle at 12 in 9"; review 2 w1 "pole at 12 in 15", "building at 1:45 in 2" → "person at 11:45 in 8, pole at 12 in 13" at 0.32 s, building 0.34 s earlier; w2 "obstacle at 2 in 2" 2.5 s earlier plus "person approaching at 12:15 in 10"; w4 "person at 12:30 in 5" 1.5 s earlier, "obstacle at 12:30 in 4" → "obstacle at 2 in 3"; review 3 w1 "poles at 11:30 and 12 in 5" + "crosswalk at 12 in 13" → one group at 0.33 s "obstacle at 12 in 6, crosswalk at 12 in 5, pole at 11:30 in 5"; w3 starts with "pole at 12 in 8, poles at 11:30 and 11:45 in 8" (0.32 s) and says "person at 12 in 9" instead of "person approaching at 12 in 8" (unsettled start); review 4 w0 (20 s): "pole at 12 in 5, pole at 11:45 in 7" at 0.35 s, "building at 1:15 in 3" 23.15, "obstacle at 1:15 in 2" 25.65, and "person standing at 11:45 in 10" at 28.99 (the user's ✓ 28.0 s "person at 11:45 in 11" is outside the 10 steps and stays out; the person walks into reach one second later); w5 the person beeps at 352.35 instead of 354.31 (cold window; the person is in view at the window start); review 5 w0 (0–110 s) three additions that the feature gap had held back: 39.5 "obstacle at 12 in 5" (the user's ✓ beeps at 39.5), 53.0 "person moving away at 11:45 in 9" (within the user's 10 steps; the ⊘ at 54.7 / 63.5 "too far away, warn at 10 steps max" are about the 12+ step ones and stay silent), 54.0 "pole at 12 in 13"; `chest0002_crosswalk` windows speak 0.3–0.6 s after their start. **Tests adapted (5):** review-4 `R4_KEPT` 354.3 s (tolerance 2.5 s, cold window), `R4_WALKS_INTO_REACH` 28.0 s, review-2 pole regex (a phrase may also carry a person), the crosswalk phrase assertion (the crosswalk may be a later entry of a group), review-5 far movers (said ones must be within 10 steps); version asserts v26.1.14 → v26.1.15; the `_item` / `_rated` helpers set `ego_settled`.

**Fixture `tests/fixtures/chest0004_review7.{json,npz}`** (1.2 MB, from run `180acf11eedb`, saved first): window 0–20 s from the run start (cold start = the run, reproduces its events exactly), grids, 24 Hz motion incl. `resid`, DA2 depth (float16, two mantissa bits cleared), settings, the v26.1.14 system events and the 6 annotations (the added one with the user's note).

**Verification in the Lab** (Lab run `9d8092942c38`, Chest-center-0004 **0–10 s**, 736p, DA2, 6 fps, `…-1280`, **CPU** — a `train_semantic.py` job held 10.4 of 16 GB of the GPU): `v26.1.15`, events exactly the "after" list above (0.17 final + beeps, 1.17, 2.00, 6.01 beeps, 6.17, 7.84).

**Tests:** unit **483 passed, 6 skipped** (472 before; new `tests/test_collision_v26115.py`, 11 tests); browser E2E (`tests/e2e/run.sh`): **56 passed** (51 before; the first run had one failure, in a new test that did not wait for the first phrase to be heard). Five new `test_player_queue_*` tests (a danger preempts a speaking context phrase at once, an equal one waits and nothing is cancelled twice; priority order; a stale queued phrase is dropped with `speech-dropped-late`; three preemptions, also of utterances that never started, trigger no watchdog, no `speech-stuck`, no notice and no unstick cancel; a lost end event does not block the queue).

**Δ / open items:** (1) the persons are 13 steps away for the first 1.8 s: nothing can say them earlier without widening the 10-step reach; (2) the start now has an obstacle "final" with beeps at 0.17 s on a very close object and the building later: by ear; (3) a cadence dropout mid-run restarts the 3 s settle, during which a person gets the plain phrase (mined: 2 phrases in 1062 s); riders / vehicles are exempt; (4) the global 2.5 s gap still lets a context phrase pass a danger only by queueing (the player now cuts it off when a danger comes); (5) `initialAnchorMinFrames` stays 3; (6) the lost / hung guards are timing heuristics (500 ms idle, 4 s + 150 ms/char) tuned on reasoning, not on a device: check the client log for `utt-lost` / `utt-hung` on the iPhone and the Mac.

## v26.1.15 follow-up — camera orientation (landscape / portrait) with camera-side windows (plan [`plans/v26.1.15-followup-orientation.md`](plans/v26.1.15-followup-orientation.md))
A Lab feature on the current version (no bump, no wipe). The user wanted to check detection and behaviour for portrait as well as landscape footage: an **Orientation** select above Resolution, working with the existing Camera side (left / center / right): the full image when it matches the recording name, otherwise a window cut from it, black padding rather than stretching. User answers: the **largest window** that fits, scaled evenly to the resolution; **real directions** (the lens geometry of the original frame is kept).

**Decisions** (deviations from the plan marked **Δ**):
1. **Window rule** (`profiles.camera_window`): landscape = the full frame (the largest 16:9 window of a 16:9 source is the frame, so landscape left / right equal it and the side only moves the lane; *a choice the user may revisit — the alternative is a shifted full-size window with black padding*). Portrait = the largest 9:16 window, full height: 4K 1215×2160, 2.7K 855×1520; left x0 = 0, center centred, right ends at W. Scaled evenly with `short_side_spec` on the window: at 736p 4K and 2.7K give landscape 1280×736 and portrait 736×1280 (content 720×1280). No upscaling; the only padding is the stride alignment, which the existing letterbox crop removes, so no extra black padding exists with the largest-window rule.
2. **Δ Full-frame storage instead of window coordinates.** The plan stored window-normalised grids and mapped back in `collision.py`. Built instead: the stored grids / masks / depth maps / hazards always span the **full frame** at the same cell size; the window is a column range (portrait: 76 of 240 columns) and the other cells hold class **255 (`NO_DATA`)** (depth NaN). Collision then sees exactly the source lens: bearings, clock, pan, focal, principal point, seed box, horizon prior, lane and ground distances are those of the source with no mapping code, and nothing outside the window can be a surface, item or depth anchor. The only collision change is that the horizon fit treats the window edges as crops (`estimate_horizon(..., bounds)`) and `hazards.json` records `window`. The Lab overlay needs only a dim + frame for the area outside the window (mask, lane, outlines and boxes are already in full-frame coordinates and so fall inside it).
3. **Run identity.** `orientation` and `side` enter the request (and the run id) **only for portrait**; landscape requests and ids are unchanged, so the matched path is untouched. `run.json` gains `orientation`, `side`, `window` (source pixels) and `gridWindow` for every new run. A portrait run's collision pass (re-runs too) uses the run's own side (lane offset), not the recording's current one.
4. **Settings and names.** `orientation` is a per-recording setting next to `cameraSide`. A recording name `<Location>-<side>-<nnnn>` provides defaults for location and side when nothing is saved (Chest-center → chest, center; the body calibration has that location). Δ: this also changes the defaults of unsaved Chest / Head recordings from the legacy mount to the body mode.
5. **Lab view.** Orientation select above Resolution; its resolution labels use the window (`736p · 736×1280`); changing Orientation or side loads the done run of the same range / fps / resolution / model / depth with that window, else the next Analyse makes a new one. The runs list and run badge show `portrait · left`. The area outside the window is dimmed (55%) and framed.
6. Production note: the production resolution 960×540 has a portrait twin, 540×960. Apple/ is untouched.

**Consequence worth knowing (real directions).** The walking lane and the seed box stay straight ahead. A left or right window does not contain them: portrait-left of Chest-center-0004 (0–60 s) has no walking region in any frame, hence no surface, no horizon fit (the preset horizon is used) and few phrases (3 speech, 0 beeps against 11 / 6 for landscape); portrait-center, which contains the seed box, keeps the region (360 / 360 frames).

**Verification** (Chest-center-0004, 0–60 s, 736p, 6 fps, DA2, GPU, `…-1280`, recording settings unchanged: legacy chest mount):
| run | window | tracked objects per class | speech | beeps |
|---|---|---|---|---|
| `4ae66a9dd538` landscape-center (matched) | full 2704×1520 | person 68, pole 246, vehicle 168, building 313, curb 84, crosswalk 7, … | 11 | 6 |
| `d1aa57f5e571` portrait-center | x0 924, 855×1520, cols 82–157 | person 65, pole 117, vehicle 60, building 91, curb 39, crosswalk 0, … | 14 | 9 |
| `8a934dba272c` portrait-left | x0 0, 855×1520, cols 0–75 | person 19, pole 70, vehicle 89, building 138, curb 104, rider 14, crosswalk 12 | 3 | 0 |
Overlay: in both portrait runs every item bbox lies inside the window (center x 0.342–0.658, left x 0.000–0.317); the danger lane (x 0.36–0.64) is straight ahead, so in portrait-left it falls in the dimmed area outside the window.

**Matched path identity.** `collision_pass` on a copy of run `9d8092942c38` (landscape, matched) gives `hazards.json` `9893fbe0ceb5da44…` and `events.json` `9873646292cf5977…`, the same bytes as the stored files; the fixture `chest0004_review7` (collision output hash `dbf69f1a…`) is the golden value of a unit test; a landscape request and run id are unchanged (tests).

**Open items:** (1) items cut by the window edge are not flagged as clipped; (2) left / right portrait windows without the seed box give no surface information (see above), a different seed rule is the user's call; (3) depth runs on the window crop, so DA2 sees a narrower view than the lens has.

## v26.1.16 — sound tuner, directional collision beeps, speech speed; review 8 fixes (plan [`plans/v26.1.16.md`](plans/v26.1.16.md), fixture `chest0004_review8`)
The user asked for a tone tuner in the middle section (pitch low ↔ high, repeat interval, duration), beep types **crosswalk in**, **crosswalk out**, **collision left 9:00–11:45**, **collision center 11:45–12:15**, **collision right 12:15–3:00**, and a **speech speed bar**. Review 8 (run `180acf11eedb`, Chest-center-0004, 0–454 s, collision v26.1.15, reviewed 1–150 s: 41 ✓, 1 ✗, 2 ⊘, 2 added) was made on v26.1.15 and is not part of the request; Opus decided to fix its notes in the same version (flagged in the done-mail). The review file, the export and the data are saved as `tests/fixtures/chest0004_review8.{json,npz}` (9.7 MB, window 0–155 s from the start of the run, grids + 24 Hz motion incl. `resid` + DA2 depth + settings + the 87 v26.1.15 system events + the 46 annotations) **before** the `RnD/VERSION` bump wiped the Lab; the fixture reproduces the stored v26.1.15 speech exactly (32 / 32 phrases).

### A. Sounds
1. **Kinds.** `collision` is split by the item's clock quarter at each tone: **center** 11:45–12:15 (quarters −1…+1), **left** 9:00–11:30 (≤ −2), **right** 12:30–3:00 (≥ +2). The user's list gives the boundaries 11:45 and 12:15 twice; they belong to the center. An episode whose item changes sector switches kind per tone and is split there. **Δ** the crosswalk kinds were `crosswalk-enter` / `-exit` (the plan called them `-in` / `-out` as "existing"): renamed to `crosswalk-in` / `crosswalk-out`; the player and review panel still understand the old names (old runs). `proximity` stays and is tunable like the rest (the user decided to keep it).
2. **Defaults** (all different): center 880 Hz / 80 ms, left 660 Hz, right 1100 Hz, crosswalk-in 330 Hz 600 ms, crosswalk-out 330 Hz 2 × 200 ms with a 120 ms gap, proximity 440 Hz soft double chirp (120 ms, period 1.2 s). In `collision.json` `tones.sounds`; the old `frequencyHz` / `durationSeconds` / `proximity.{frequencyHz,intervalSeconds,durationSeconds}` / crosswalk keys are gone (one place for the numbers).
3. **Profile and API.** One Lab-wide profile in `debug/lab/display/sounds.json` (overrides only, survives version wipes, `lab/sounds.py`, the pattern of `lab/display.py`); `GET` / `PUT` / `DELETE /api/sounds`. Per kind `pitchHz` (150–2000), `durationMs` (20–1500), `intervalS` (0.05–5); global `speechRate` (0.5–2). `intervalS` is the repeat interval at 5 steps for collision kinds (the whole `bySteps` table is scaled by `intervalS / 0.5`, the continuous chunk is not), the gap of crosswalk-out, the period of proximity, unused for crosswalk-in. The collision pass reads the profile.
4. **Tuner (middle section, `#secSounds` in `#main`).** A row per kind (log pitch slider with Hz, duration, interval, ▶ test) and a Speech speed bar with ▶ test. **Live:** pitch, duration, speech speed (the player overrides the event's values by kind; a continuous chunk keeps its length; the speed multiplies the playback rate, clamped 0.5–2). **Re-score:** interval changes show "Apply timing to this run" (re-runs the collision pass). Saved with a 400 ms debounce. All speech guards are untouched (system voice rule, watchdog, stuck notice, priority queue, lateness drop, client-log diagnostics).
5. **Review panel:** "beeps · left · person at 11:30 · 4→2 steps", "⇥ crosswalk in", bell title "Collision beeps (left)".

### B. Review 8
| t (s) | entry | now |
|---|---|---|
| 10.9 | added "Building at 12" | **not produced** (see 6: nothing on this footage is a lane danger at 10.9 s); the memory rule is in (a context-named building would no longer be muted) |
| 27.3 / 28.5 | added "Person at 11:45 in 8" / ⊘ "person at 12:15 in 6" | **27.33 "person at 11:45 in 8"** (the added phrase, word for word); nothing at 28.5 |
| 52.2 | ✗ "vehicle approaching at 11:45" | **silent** (a vehicle needs 2.0 m/s of its own speed, see 8) |
| 107.0 | ⊘ "vegetation at 12 in 2" | **silent** (its beeps stay: 107.0–107.2 center) |

6. **Danger beats notify-once** (world memory entries get `danger`): context, feature and thin phrases are muted by any entry as before; a danger or final is muted only by an earlier danger / final for the object. Consequences on the footage: "pole at 11:45 in 2" (108.7 s, 143.2 s) are now spoken after the feature call; the 35.3 s obstacle of review 2 and the 40.8 s pole of review 3 are called a danger after their context / feature phrase (the tests of v26.1.7 that muted them are changed; this is the opposite of the review-3 "no repeat" complaints, decided by the plan).
   - **The lane and the 11:45–12:15 band (the user asked to verify).** The walking lane is ±0.6 m. Its half-angle is **16.7° at 2 m, 8.5° at 4 m, 4.6° at 7.4 m** (10 steps at 0.7 m), so at 10 steps the lane lies **inside** the center band (±7.5° between the labels 11:45 and 12:15; ±11.25° to the edge of quarter ±1); it equals ±7.5° at **4.56 m (6.5 steps)** (±11.25° at 3.0 m) and is **wider** than the band closer than that. The band is wider than the lane only beyond 4.56 m: at 10 steps (7.0 m) it reaches 0.92 m sideways against 0.6 m. **Decision: the lane test stays.** Counting everything touching the walking region inside 11:45–12:15 within 10 steps as a collision course was run on the 155 s: danger phrases **18 → 32**, collision beep episodes **11 → 16** (new: poles, signs, vegetation, a building at 2 steps), none of them the 10.9 s building; a second experiment (a static thing whose pixels cover lane cells higher up counts as in the lane, 15–100 cells) gave **11 → 23–29** beep episodes (every wall along the sidewalk) and the 10.8 s "building at 12 in 3" only together with them. Both reverted.
   - **The 10.9 s building.** The track the user saw is a wall on the right (2.4–3.3 m sideways, 2.6 steps, role context, along the path) whose contact point jumps to the center for three frames (10.7–11.2 s); the only building in the 12:15–12 band is a second one (11.3 s, 9.6 steps, lateral 0.8 m, one frame), which fails the 2-frame confirmation. Nothing on this footage is a lane danger at 10.9 s, with or without the memory rule. **Not fixed**; open item.
7. **27.3 s person.** Cause: the head turned 9° in one frame (heading 16.3° → 7.2°), the person 5.7 m away moved a full box width in the image, lost its track and was re-born as tracks 978 and 982 (age 0, no motion, confirmation restarting, `settled` after 0.5 s, then the 1.5 s people motion wait): said at 28.5 s. Fix: for **people** the match also tries the previous box moved by the scene's pan (`−Δheading / hfov`) when the pan is ≥ 0.06 of the image per frame (`tracking.panMatchMinShift`; 0.04 and compensating every mover reshuffled the speech of reviews 3–7: track ids, phrases, 4 of 41 ticks). Result: the person is **one track** and said at **27.33 s**. The same hard pan makes the ego speed unsettled for `roles.panSettleSeconds` (1 s; the cadence read 2.09 against 1.2 m/s around 27 s, so the first run of the fix said "person standing at 11:45 in 8"): the phrase is the plain **"person at 11:45 in 8"**, the user's added entry.
8. **52.2 s static vehicle.** The plan's rule is built (`ego_settled` or `own_fast`: `closing − 2.0 ≥ 0.4` for a rider / vehicle), but at 52.2 s the ego speed *is* settled, so it does not touch this case. The vehicle's own speed along the line of sight reads 1.0–3.0 m/s for parked cars in a row (`closing` 1.7–4.1 against a walking speed of 1.27: the depth closing of a big, fragmenting component). **Δ** a vehicle needs `vehicleApproachingMps` **2.0** to be `approach` (leave level 1.4); cyclists keep the person levels (their early warnings of reviews 4 and 6 stay). On the full 454 s run this removes 7 "vehicle approaching" phrases at 160–384 s that were never reviewed (and adds one at 288 s): a car that really approaches closes at 4+ m/s (49.2 s: 6.6–7.3).
9. **107.0 s "vegetation at 12 in 2".** It is a *final* (not a context phrase) for something that was only ever a context item. Rule 9: no context phrase for 2.5 s (`contextAfterDangerSeconds`; the plan said ≈ 3 s: at 3.0 s the ticked 6.17 s "building at 1:30 in 2" was 3 ms inside the window) after a danger / final phrase or a collision-beep **stream** (≥ 2 frames; a single pass-by beep does not count: the same 6.17 s phrase follows the first beep of a passing person at 6.0 s and is ticked); and **Δ** rule 9b: a final for a never-named non-thin static thing that has been a context item, inside that window, is consumed silently (the beeps carry it). Result: 107.0 s is silent; its beeps stay.

**Tests:** unit **557 passed, 6 skipped** (483 before; new `tests/test_collision_v26116.py`, `tests/test_lab_sounds.py`; reviews 1–7 and the crosswalk fixture stay green, with these changes to what they pin: the version, the `collision` / `crosswalk-enter` kinds and `beeps ·` texts, the pitch of the center sector, hard-coded track ids that shift when the 27.3 s person keeps its track (4984 → …, 4798, 11195, 1504, 2147: now looked up), rule 6 (review 2's 35.3 s obstacle and review 3's 40.8 s pole are called a danger after their context / feature phrase; the v26.1.7 "named once" tests say so), the lost-tick list of review 6 (357.0 s pole is produced again), the review 7 golden hash re-pinned (`83568a1d…`)); `/api/sounds`: defaults, overrides only, clamping, 422s, unused interval, survives the version wipe. Browser E2E (`tests/e2e/run.sh`): **64 passed** (7 new: tuner in `#main` with a row per kind, persistence through the API and a reload, ▶ test frequency / crosswalk-out gap / crosswalk-in single tone, live pitch & duration of injected events, speech speed × playback rate, review panel sectors and pitches, "Apply timing" re-scoring the session run; `open_lab(profile=...)`, `window.__labAudio`).

**Verification in the Lab** (run `116731b3e5c2`, Chest-center-0004 **0–155 s**, 736p, DA2, 6 fps, `…-1280`, **CPU** — the GPU is held by a training job, as for `180acf11eedb`; 932 ms/frame, `v26.1.16`; the collision pass was re-run after the Lab restart with the final code): its speech and beeps equal the fixture run's (52 / 52 events up to 154.5 s). Speech **32 → 32** phrases (v26.1.15 → v26.1.16): 27.33 "person at 11:45 in 8" replaces 28.50 "person at 12:15 in 6"; 52.17 "vehicle approaching at 11:45" and 107.01 "vegetation at 12 in 2" are gone; 54.67 → 54.50 "building at 1:15 in 2, obstacle at 1 in 2" (another clock quarter of the same two objects); new 108.66 and 143.16 "pole at 11:45 in 2" (finals for a pole named as a feature before: rule 6). Collision beep episodes **11 → 13** (the 79.0–79.3 s episode is split where the obstacle crosses from 12:15 to 12:30): center 11, right 2 (the obstacle at 12:30, 0.2 s and 79.2 s), left 0; proximity 5, crosswalk in 1 / out 1. **Ticks:** 40 of the 41 ✓ are still produced (all 17 beeps ✓ and 23 of the 24 phrases); the lost one is 54.67 "building at 1:30 in 2, obstacle at 1 in 2", said at the same moment at 1:15. Full 454 s run, mined from the stored grids / motion / depth before the wipe (code before the `panSettleSeconds` rule; not reviewed past 150 s): speech 82 → 78, beep episodes 42 → 47 (center 25, right 3, left 2, proximity 9, crosswalk 4 / 4); 7 "vehicle approaching" phrases at 160–384 s are gone and one is new at 288 s; 6 pole phrases shift (268, 289, 293, 384 s new; 289, 385 s gone).

**Δ / open items:** (1) the 10.9 s building is **not** produced; the evidence is in 6 — needs the user's look at the overlay (which building, which frame) or a different rule; (2) the vehicle level of 2.0 m/s drops 7 unreviewed "vehicle approaching" phrases on the full run; (3) two rules (6, 9b) pull in opposite directions in the user's eyes: finals for named things come back (rule 6), finals for never-named context things inside a danger run go silent (9b); (4) the crosswalk kinds were renamed; (5) Apple/ is untouched.


## v26.1.16 follow-up — lane part of a building (review 8, 10.9 s "Building at 12"; plan [`plans/v26.1.16-followup-building-lane.md`](plans/v26.1.16-followup-building-lane.md); no version bump, no Lab wipe)
**User feedback.** The 10.9 s "Building at 12" of review 8 was not produced by v26.1.16 (item 6 above: open item 1). The user approved the planner's rule: treat the part of a wall / building that stands in the lane as a full lane danger (spoken, collision beeps ≤ 5 steps, final only if never named).

**Cause.** A static item is measured at its lowest pixel. The wall on the right and the scaffolded section that juts out in front of the user are ONE `building` component (track 239); its lowest pixel is the side wall's base (lateral 2.4–3.3 m, 2.6 steps, along the path, context), so the base of the jutting section — in the lane — was never measured.

**Rule** (`_lane_part_item`, `roles.laneBase*`, CONTRACTS §6 / §7.4 / §7.15). For static items of `laneBaseClasses` whose main item is not a lane hit (or is `along_path`), an extra `_Item` (`lane_part`, hazards JSON `lanePart: true`) measured at the **ground base**: component pixels with walking region directly below (`geo.floor_below`) that lie in `geo.lane_region`. **Variant used: `floor_below`** (the plan's primary variant). The fallback ("lowest cell per column, walking region within N rows below") was NOT needed for the target: with `floor_below` the 10.9 s face has 4–15 base cells in 2–7 columns per frame; I also tried a "walking region within 2–3 rows below" tolerance and it did not bring back the frames after 15.2 s (the base inside the lane simply shrinks there), so it was dropped. Further decisions:
1. **Own track and id range.** `_match` never matches a lane part with the side wall's track (`it.lane_part == tr.lane_part`); lane-part ids start at `1_000_000`, so the ids of ordinary tracks do not shift (the first attempt shifted them and broke the review-5 tests that look up track 743).
2. **Depth under the base.** With `distanceSource: depth` the first version read the depth under the component's lowest rows = the side wall (1.9 m, "2.7 steps"). The item now carries `depth_cells` (its base cells).
3. **Flat base.** The plan's "≥ 2 columns" alone made every wall along a sidewalk a lane part (review 8 with the barrier classes and no flatness test: lane-part dangers and beeps on the walls along the sidewalk at 1.3–3.7 s, 24–27 s, 43–98 s, 11–23 beep episodes more: the old failure). A wall seen edge-on has a *diagonal* base (1–2 cells per row over many rows, contact at the lane edge |lateral| ≈ 0.55–0.6, cover 0.03–0.07); a face across the lane has a flat one. Flat = the widest row has ≥ `laneBaseMinRowColumns` (4) cells and holds ≥ `laneBaseMinConcentration` (0.42) of all base cells (the first try, "widest ≥ 0.5 × rows", let a 7-cell fringe row of a diagonal wall through at 26.3 s). A non-flat base may only *continue* a flat one for `laneBaseHoldSeconds` (3 s): without the hold the lane part vanished at 15.2 s and the final 5→4 step beeps (15.8–16.2 s) were lost.
4. **Measured closing.** A lane part is a danger only with a known ego speed and raw closing ≥ `laneBaseMinClosingMps` (0.3): a wall that bends across the camera axis keeps or gains its distance (4929 / Chest-center-0002 51–52 s: the sea wall along the right of the sidewalk, 4 frames of "danger" at 2.9 m). And its track must be ≥ `laneBaseMinAgeSeconds` (1 s) old. A lane part that is not a danger is role `none` (context stays the side wall's job). It is not a speed witness.
5. **Classes: `building` only** (deviation from the plan's initial list). With `barrier wall` / `barrier fence` / `barrier` / `barrier guard-rail` included the fixtures changed in 4929 reviews 2, 4, 5 and Chest-center-0002: new "obstacle at 12 in 6" at 40.3 s (review 2, ~ the wall behind the crosswalk the user ticked at 35.3 s: plausible), beeps at 49.2 s (review 4), and above all review 5, 39.2 s: the lane part of the barrier wall the user ticked as "obstacle at 12 in 5" (39.5 s) reached danger 0.3 s earlier ("obstacle at 11:45 in 5", beeps from 39.16 s), the priority gap of 1.0 s then pushed the ticked "curb at 12 in 3" (39.33 s) out to a later curb at 42.2 s — a lost ✓ — and 51.0–51.3 s still had a 3-frame "obstacle at 12:15 in 3" with beeps beside the sea wall (wall 2 m ahead, 0.3–0.5 m right of the lane centre, closing 0.4–0.8 m/s). Not justified without the user's look, so walls and fences are off by default (the config key lists them).

**Verification.**
- **Run `116731b3e5c2`** (Chest-center-0004, 0–155 s, 736p, DA2, 6 fps, `v26.1.16`; Lab restarted, collision pass re-run: `POST /api/runs/116731b3e5c2/collision`, 9.8 s). Events 88 → 93 (36 tones both; +3 tones). Changed events — **new**: 11.83 speech "building at 12 in 10" (lane-part danger from 11.66 s at 9.9 steps, lateral 0.2–0.5 m, track 1000002; the 2-frame confirmation puts the phrase at 11.83 s; the building's base reads 12–13 steps until 11.5 s on the depth distances, so the 10-step danger line is first crossed at 11.66 s, not at 10 s as in the planner's ground-geometry prototype), and **15.83 beeps · center · building at 12 · 5→4 steps** with tones at 15.83 / 16.25 / 16.67 s (the lane part is a danger through 16.2 s at 4.3–4.6 steps). **Lost:** none. Speech 32 → 33, collision beep episodes 13 → 14, every other event identical. The lane part is a danger on 11.66–15.17 s (10 → 6 steps) with a gap 15.17–15.67 s (base not flat; held by `laneBaseHoldSeconds`) and 15.67–16.17 s (4.3–4.6 steps). No collision beeps between 11.8 and 15.7 s: they start at ≤ 5 steps, and the depth distance of the building stays at 6+ steps until 15.5 s (expected "14.5–16.2 s" in the plan: the beeps are 15.83–16.7 s).
- **Fixtures** (every window of `tests/fixtures/*`, event lists before / after, tones excluded). Only `chest0004_review7` (same footage, 0–20 s) and `chest0004_review8` change, by exactly the two events above; every 4929 review, the Chest-center-0002 crosswalk windows and all other windows are **identical** (user ✓ entries all kept). Wall-along-sidewalk false positives: found with the barrier classes and the first (loose) versions (item 3, 4, 5); with `building` only, 0 new events outside the target.
- **Tests.** Unit **566 passed, 6 skipped** (557 + 9; new `tests/test_collision_v26116_lanepart.py`: config + hazard field, plain side wall → no lane part, L-shaped building → side-wall context + lane-part danger + beeps (synthetic, with a pole as speed witness), the base-cell extra item and its absence for a plain wall / a face that is a lane hit by itself / config off, review 8: "building at 12" at 9.9–12.0 s, center beeps 10–17 s, lane-part track ids ≥ 1000000, at most 3 lane-part danger tracks). The golden hash of `chest0004_review7` in `test_orientation.py` is re-pinned (the 10.9 s building: `83568a1d…` → `85e11f9c…`). No Lab UI / JS change, no browser E2E.

**Δ / open items.** (1) The phrase comes at 11.83 s, not 10–11 s: on the depth distances the building is farther than 10 steps until 11.6 s. (2) Beeps are 15.83–16.7 s (5→4 steps), not 14.5–16.2 s. (3) Walls / fences are not covered (item 5); a lane part of a wall that is also a main lane danger arrives 0.3 s earlier and can displace a feature phrase by the 1.0 s priority gap — decide with the user's look at the review-5 39 s and 51 s overlay (the `lanePart` field is in the hazards for the overlay). (4) The 0.3 m/s closing and 1 s age gates make a lane part silent for its first second and while the ego speed is unknown (start of a run). (5) Apple/ untouched.


## v26.2.0 — world map spike + Lab layout (plan [`plans/v26.2.0.md`](plans/v26.2.0.md); roadmap step 1 of v26.2; Lab only, collision rules untouched, version bumped so the Lab wiped its runs)

**Layout and overflow (user request, same version).** The world view sits next to the video (video left, map right, same height; speech/review panel stays in the right column; the left options and the other panels start below the video+map row). The map is always visible (no longer a collapsed panel). The Sounds table overflowed the phone (scrollWidth 650 at 390 px); it now scrolls inside its own wrapper. Details: plan v26.2.0 "Layout", CONTRACTS §9. The version bump wiped run 116731b3e5c2 (no reviews existed); it was re-created afterwards from its saved request.

**Follow-up: clock markers (user request, same version).** To judge positions on the world map, the canvas now draws clock spokes from the user marker (hours 9..3 faint to the canvas edge, quarter hours at 7.5 degrees fainter to 10 steps, same clock rules as `clock_quarter` / `clock_text`), faint rings at every step to 10 steps (5-step rings and their "N st" labels kept), tick marks where the quarter spokes cross each ring, hour labels once at the outer end of the hour spokes (the "N st" labels are offset and hidden near the top edge so they never collide), and a hover/tap readout ("12:30 · 7.5 st · 5.3 m") next to the status line. Static Lab files only; no version bump, no collision rules touched.

**Question.** Is a local, ego-centric bird's-eye map fused over time from what a run already stores cheap enough, consistent enough, and is our pose (cadence x step length along the optical-flow heading) good enough for it, or is visual odometry needed first?

**What was built** (`src/worldmap.py`, `common/config/worldmap.json`, `POST/GET /api/runs/{id}/worldmap`, `worldmap/{i}.png`, `worldmap/pose.json`; CONTRACTS §8.1; `tools/worldmap_metrics.py`, `tools/worldmap_render.py`; `tests/test_worldmap.py`). Inputs only `grids.npz`, `depth.npz` and the horizon / ego block / calibration stored in `hazards.json` (so the map uses exactly the calibration the hazards used; `collision.resolve_settings` is not re-run). Reused from `collision.py` without change: `focal_px`, the `ground_distance_m` / `lateral_m` formulas (inverted), `_WorldMemory.advance` for the pose, `load_config`.
- **Surfaces** by inverse ground-plane sampling (each map cell looks up the pixel that sees it: no holes, vectorised); camera height x 1.0 when the distance source is depth (the plane anchor already makes depth and ground agree), the gait scale otherwise.
- **Objects** only at their base (lowest pixel of each vertical run), at depth x `depthScale` (what `distanceM` uses) or the row's ground distance without depth; upper pixels are not projected. Movers are never mapped.
- **Fusion:** 64 m world window of 0.10 m cells, range-weighted votes with a 6 s half-life (lazy decay: no per-frame cost), floor 0.25, object votes x 2 (a wall base is one thin line among many surface cells; at x 1 a 0.3 m wall across the path was out-voted by the sidewalk around it in the synthetic test).
- **Snapshot** 200 x 200 heading-up, user at (col 100, row 180); `classes` + `conf` + `pose` + `ms` in `worldmap.npz`.

**Metrics, run `116731b3e5c2`** (Chest-center-0004, 0-155 s, 930 frames, DA2 depth, fisheye 118 deg, depth distances; `hazards.json` / `events.json` sha256 identical before and after the pass):

| Metric | Value |
|---|---|
| Cost per frame (observation + fusion + snapshot, single-threaded numpy, Ryzen, CPU) | mean **4.9 ms**, p95 5.7 ms, max 13.8 ms (whole run 4.7 s) |
| Wall along the right, 10-16 s, one frame (robust line fit, RMS perpendicular) | 0.16 m (all points 0.30 m mean, p90 0.38) |
| same, the base points of the last 1 s / 2 s / 3 s / 6 s pooled in the world frame by the pose | 0.23 / 0.26 / 0.32 / 0.39 m |
| same, the fused map at 16 s (all points / worst 10 % dropped) | 0.53 / 0.39 m |
| Wall base source: depth vs ground ray of the contact row (per-frame RMS) | 0.30 m vs 0.49 m: depth is better; the lens-model lateral (`lateralModel: lens`) is slightly worse than the collision pass's rectilinear lateral (0.34 vs 0.30), so the default stays `collision` |
| Poles / lights / signs seen >= 3 s (40 tracks): std of world position over the life | median 0.80 m, p90 2.5 m |
| ...of which inside 1 s windows (= measurement noise) | median 0.34 m |
| ...spread by track life 3-5 s / 5-8 s / > 8 s | 0.64 / 0.63 / 1.56 m (the > 8 s ones are first seen farther: 12 m vs 8 m) |
| Drift proxy: same pole first vs last fifth of its life | median 1.0 m, p90 3.1 m (first seen at 7.9 m median) |
| All static tracks (168) | spread median 2.2 m, first-vs-last 2.8 m (walls / vegetation: a track is a whole component, its contact point slides) |
| Fused vs current-frame class on surface cells | 24 % disagree (rows are 0.3-2.5 m deep at 6-18 m; class flips at the far edge) |
| Pose | path 171 m (155 s, 20 s standing), max step 0.41 m / 2.5 m/s (the known noisy cadence speed), end (86.6, 98.3) m |
| 10.9 s extrusion: building cells in the +-0.6 m corridor ahead (0-8 m) | 11 s 67 cells, nearest 5.3 m; 12 s 123 / 4.7 m; 13 s 241 / 4.5 m; 14 s 256 / 3.4 m; 15 s 246 / 2.7 m; 16 s 211 / 1.9 m: **yes**, the section that juts into the path is a solid cluster in the corridor from 11 s on, approaching at walking pace |

**Verdict (decision gate).** Cost is not an issue (about 5 ms/frame vs 932 ms/frame for the analysis). Pose is **good enough for step 2 as a short-memory map (about 6-10 s, about 10 m)**: a wall pooled over 6 s of walking (7-8 m) blurs by about 0.2-0.25 m beyond a single frame, and the pole spread does not grow with life (0.64 m for 3-5 s tracks, 0.63 m for 5-8 s), i.e. the error is dominated by the depth range error at 8+ m (0.34 m noise inside 1 s, 1 m first-vs-last at 8 m), not by the pose. Visual odometry is not needed first. What this spike does **not** show: drift over minutes (no loop or surveyed reference on this footage), so the map must keep decaying (half-life 6 s) and must not become a persistent global map without a loop check; and the 24 % far-edge class disagreement means step 2 should read the map near the user (within about 10 m) and use `conf`.

**Deviations / open items.** (1) Settings are read from the run's `hazards.json` instead of re-running `collision.resolve_settings` (same numbers, one source of truth; a run needs its collision pass first). (2) `objectVoteGain` 2.0 is an addition to the plan's fusion (reason above). (3) The wall metric fits the building/barrier-wall base points in the ego region 0-8 m ahead, 1-8 m right: it includes the scaffolded section and door recesses, so 0.16 m per frame is an upper bound on pure measurement noise. (4) No Chest-0002 run: analyses occupy the Lab worker on CPU while the GPU trains; one needs the user's OK. (5) The PNG default is RGBA with binary alpha (a canvas premultiplies, so class ids under partial alpha would be corrupted); confidence is `?alpha=conf` (display only) or `worldmap.npz`. (6) The browser panel is W2.

**W2 - Lab "World map" panel** (`lab/static/js/worldmap.js`, `#secWorldmap` above the Sounds panel; CONTRACTS §9). The snapshot of the playhead frame, coloured with the mask's class LUT (follows the Classes panel), user marker, +-0.6 m corridor to 10 steps, rings every 5 steps (frame `stepLengthM`), current hazards as dots (movers = diamonds, danger = ring); "Build map" when the run has none. Fetch on seek, at most 6/s while playing, 24-entry cache, nothing while collapsed. Found by `pose.json` times, so it needs no frame-index mapping. Tested by `tests/e2e/test_worldmap.py` (full E2E 65 passed). Note: the pre-existing Sounds table overflows a 390 px phone viewport (page scrollWidth 650); the map panel itself fits.

**Tests:** unit **573 passed, 6 skipped** (566 + 7 new in `tests/test_worldmap.py`: straight wall + corridor face, a pole stays in one place, a mover is not mapped, stationary pose does not drift, pose = `_WorldMemory`, vote decay / floor, endpoints). Collision goldens untouched.

## v26.2.1 — the collision rules read the world map (plan [`plans/v26.2.1.md`](plans/v26.2.1.md); roadmap step 2 of v26.2; collision version bumped, Lab wiped, run `116731b3e5c2` re-created)

**What the plan said and what was built.** The plan made the online world map (v26.2.0 spike) decide every static danger ("are there obstacle cells inside my corridor within 10 steps"). It was built and measured on the 9 fixtures (4929 reviews 1-6, chest0002_crosswalk, chest0004 reviews 7-8), `staticSource` image (= v26.2.0, reproduced byte for byte on events) against map. **The pass rule failed and tuning could not fix it**, so the options went to the user, who chose "1+3": option 1 now, option 3 as the separate version v26.2.2.

**Measured options (evidence for v26.2.2)** — fixtures, ✓ = tick of a user review lost / ✗⊘ brought back / events gained / lost against v26.2.0:
- pure map (the plan): margin 0 / 1 cell **11** ✓ lost, 1 ⊘ back, +120 / −28 events; margin −0.15 / 3 cells 14, 0, +79 / −28; margin −0.30 / 3 cells 17, 0, +59 / −34; margin −0.40 / 3 cells 13, 0, +49 / −30 (also drops real obstacles at 0.2-0.4 m lateral).
- union (the image rule kept, the map adds dangers for every static class): core ±0.30 / 6 cells **5** ✓ lost, 0 back, +37 / −9; core ±0.30 / 3 cells 9, 0, +52 / −14. The ✓ losses are cascades: every added event shifts the speech gaps (97.00 pole, 97.16 person, 108.49 person, 107.01 vegetation beep ...).
- why: the map's lateral blur (about 0.16 m per frame, depth noise) equals the corridor margin and a wall beside the sidewalk sits 0.5-0.9 m from the body line, so cells of the wall's own family leak into the corridor. Walls-along-sidewalk among the new dangers (rendered): 96.5 s building at 12 in 9, 103.5 s vegetation at 12 (planter), the building beside the user at 0.17 s, 26.3 s an electricity cabinet in a wall. **Walls-along-sidewalk count of the chosen rule: 0** (no new danger on any fixture except the building section below).

**The rule as built (option 1).**
1. **Online map in the collision pass** (`collision._StaticMap` over `worldmap.WorldMap`, causal, fed with the frame's rounded ego values so that `worldmap.build` over hazards.json equals what the pass saw; `worldmap.PoseTracker` shared; `Observer.object_bases` split out).
2. **Static dangers keep v26.2.0's image rule** (`lane_hit` and not `along_path`), for every class, vehicles included.
3. **Building section on the map replaces the v26.1.16 lane part** (not emitted any more under `map`): for a `laneBaseClasses` item (building) whose contact point is not a lane hit, ≥ 10 map cells of the item's family (footprint = its own ground-base points + 0.3 m, fused confidence ≥ 0.7) in the corridor core (|lateral| ≤ 0.6 − 0.3 m), on the map ≥ 0.5 s (gaps ≤ 0.7 s bridged), the nearest corridor cell closing at ≥ 0.6 m/s over ≥ 0.5 s. The item itself then is the lane danger with the nearest cell as measurement (distance = ahead, lateral = right, bearing = atan2(right, ahead), clock, steps); the image values stay as `imageDistanceM` / `imageLateralM`.
4. **Ghost:** a confirmed static danger (`role_run ≥ confirmFrames`, settled) that is clipped or within 2 m is kept alive from the map after the image loses it (world position dead-reckoned, fused object cells of its family, confidence ≥ 0.3, whole corridor, ≤ 2 s) until passed (`ahead ≤ 0`): danger, beeps and final call continue (`ghost: true`, no outline). Synthetic test: a pole whose base leaves the frame beeps to 0.1 steps; the image rule stops at its last frame. **Fires 0 times on the fixtures and on run 116731b3e5c2** (the real poles are lost earlier or stay in the image), so it changes no event there.
5. Hazards JSON: static items `source` ("map" | "image"), `mapCells`, `imageDistanceM` / `imageLateralM`, `ghost`; per frame `corridor: {nearestM, nearestSteps, className}`. `staticSource: "image"` = v26.2.0 (A/B, the tests that pin it). Config keys: `staticSource`, `mapMinConf`, `mapFootprintRadiusM`, `mapCorridorMarginM`, `mapMinCells`, `mapMinAgeSeconds`, `mapGapSeconds`, `mapMinClosingMps`, `mapClosingSpanSeconds`, `mapGhostMinConf`, `mapGhostSeconds`, `mapGhostNearM` (`mapUnion` was tried and dropped).

**Pass rule on the 9 fixtures (image → map): no ✓ lost, no ✗/⊘ brought back.** The only event changes (in chest0004_review7 and review8, the same footage): speech **11.83 "building at 12 in 10" → 13.50 "building at 12 in 8"** (the map's 10-cell core test is reached later than the lane part's flat base: 1.7 s later, 8 steps), and the collision beep episode **15.83 → 15.33 "center · building at 12 · 5→4 steps"** (tones 15.83 / 16.25 / 16.67 s → 15.33 / 16.00 s). The user ✓ on that building is kept (same speech, same beeps). Every other fixture event is identical (4929 reviews 1-6 and chest0002: 0 changes).

**Run `116731b3e5c2`** (Chest-center-0004 0-155 s, CPU, v26.2.1, Lab restarted after the bump; the run id is the same because the request is): events 93 → 92 (speech 33 → 33, collision beep episodes 14 → 14, tones 39 → 38): exactly the building changes above, nothing else. 13 hazard frames are judged on the map (the building, 13.3-16.2 s at 8.3 → 3.9 steps, plus 26.3-26.8 s at 4.3 / 3.4 steps where the speech policy says nothing, the building is already named); 0 ghost frames.

**Cost.** Collision pass ms/frame: fixtures 7.6 → 13.4 (map update included, about 5.8 ms: observe + fuse + snapshot + per-item lookup), run 116731b3e5c2 offline 10.4 → 15.7. Offline `worldmap.build`: 5.5 ms/frame (unchanged).

**Tests.** Unit **581 passed, 6 skipped** (573 → 581: the new `tests/test_collision_v2621.py`, 8 tests: config, plain wall beside the sidewalk = no danger, pole leaving the bottom of the frame keeps beeping, a pole beside the lane is never a ghost danger, a mover is unaffected, `image` source = v26.2.0 (lane part back, no new keys), review 7 (11.83 under `image`, 13.50 + beeps on the map), online map = offline build); browser E2E **68 passed**. Changed pins, and why: version asserts v26.2.0 → v26.2.1 (version string); `tests/test_collision_v26116_lanepart.py` now runs on `staticSource: image` (it pins the v26.1.16 lane part, which the map replaces by default); `test_beep_episodes...`: `minSteps ≥ 1` → `≥ 0` (a ghost beeps down to 0.1 steps, intended); `test_output_documents_are_serializable_and_complete`: new keys `corridor` (frame), `source` / `mapCells` (static hazards); `test_collision_depth.strip`: ignores `corridor` (the map places objects with the depth when there is one, a reporting key); golden hash `GOLDEN_CHEST0004_REVIEW7` re-pinned (version string, the new keys, the building 11.83 → 13.50 and its beeps).

**Deviations from the plan.** (1) The map judges only the building section and the ghost, not every static item (user decision); (2) the context measurement stays image-based, parked vehicles stay on the image rule (movers are not in the map); (3) the 10.9 s building is spoken later (13.50 s, "in 8"), see above; (4) the ghost never fired on real footage, it is covered by a synthetic test only.

**Open items.** (1) v26.2.2 (option 3): a face-versus-edge test so that the map can judge every static item and walls beside the sidewalk stay silent (tables above are the baseline; ideas: cells persisting over metres of travel at a consistent lateral, protrusion past the neighbouring wall line, a pose-error-aware corridor). (2) Map conf near objects is fragile in synthetic scenes with piecewise-constant depth (1.5 m per image row at 12 m): the L-shaped-wall case is therefore tested on the real review 7 fixture, not synthetically. (3) The Lab UI does not show `corridor` / `source` yet. (4) Ghost needs a real-footage case before its thresholds (2 m, 2 s, conf 0.3) can be called tuned.

## v26.2.2 — the map judges the walls (face or edge), items inside solid areas are snapped to their wall, vanished movers coast (plan [`plans/v26.2.2.md`](plans/v26.2.2.md); user decision "2+3" 2026-10-24, snap correction 2026-10-25; collision + worldmap version bumped, Lab wiped, run `116731b3e5c2` re-created)

**Why.** v26.2.1 showed that the map cannot judge walls by "cells in my corridor" (a wall beside the pavement blurs ~0.16 m per frame into the ±0.6 m corridor). v26.2.2 gives the map a **shape test** (face vs edge) and lets it judge all wall-like classes. The user then added two observations: notifications for things "inside solid areas" are impossible, and movers that disappear should continue on their trajectory.

**Ground truth before tuning.** Phase A emitted every corridor candidate of the pure-map rule (margin 0, 1 cell, fused confidence ≥ 0.7) on the 9 fixtures and run `116731b3e5c2`: 491 episodes → **184 deduped candidates** (fixtures 4929 101, Chest-0004 65, Chest-0002 18; the run's 61 are shared with the fixtures), each rendered (`debug/v26.2.2/cand_NNN.png`, index.json / index.md). Opus labelled the 144 wall-like ones: 49 face, 62 edge, 33 unsure; poles, signs and sidewalk-obstacles stay on the image rule.

**The test** (`src/faceedge.py`, `_StaticMap.faceedge`): per side a RANSAC wall line (|angle| ≤ 25°, ≥ 15 cells over ≥ 2 m, cells 0-8 m ahead); a corridor cell is an **edge** within 0.25 m (+0.02 m per metre of range) of its side's line (a cell on a side without a line is judged against the other side's line: this fix removed the wall-beside-the-path false faces, FPs 10 → 6) and a **face** when not an edge and it protrudes past the line toward the axis by ≥ 0.3 m, or its local cluster runs across the path (≥ 45°), or there is no wall line at all. ≥ 3 face cells (`minFaceCells`) and the user not standing still → lane danger, measured at the nearest face cell. No ghost rule changes.

**Labelled set, per episode (a face in any frame at ≤ 10 steps), unsure excluded:**

| step | TP / FP / FN | precision / recall |
|---|---|---|
| phase A code (per cell side only) | 28 / 10 / 9 | 0.74 / 0.76 |
| + cross-side edge fix (**shipped**) | 27 / 6 / 10 | 0.82 / 0.73 |
| + persistence ≥ 2 frames (dead-reckoned world position) | 19 / 5 / 18 | 0.79 / 0.51 |
| + persistence ≥ 3 frames | 14 / 3 / 23 | 0.82 / 0.38 |
| `minFaceCells` 1 | 30 / 13 / 7 | 0.70 / 0.81 |
| + depth gate on the base ratio (band 0.6-1.6) | 14 / 8 / 23 | 0.64 / 0.38 |

The target (0.9 / 0.8) was **not reached**; the user accepted residual false and missed wall dangers. Protrusion 0.45 / 0.6 / 0.8, edge band 0.35 / 0.4 and cross angle 60° changed nothing. Persistence did not help (many true faces last 1-2 frames; the depth-error FPs persist too). Rep-frame scoring (the coordinator's first numbers) was 0.64 / 0.71 all ranges, 0.68 / 0.68 at ≤ 10 steps.

**Depth errors (option 3, how it was measured).**
- Candidate cause list: 4 FPs are depth errors (46, 70, 118, 168), 2 are narrow sidewalks / V-shaped walls (138, 184). Tried and **left out** (no gain on the labelled set): a depth-consistency gate (depth distance / ground-ray distance of the base row: true near walls read 1.4-3.5, the depth-error FPs 1.0-2.3, no band separates them); free-space carving (cells free on all four sides at 0.5 m / 1 m, the walked trail ±0.3 m: the depth-error FPs are not deep inside free space; the true faces have as much free space around them); requiring ground under an object base (recall 0.73 → 0.59).
- **DA2 range compression** (run `116731b3e5c2`, scaled depth ÷ ground-ray distance of surface pixels; the 1.45 near-field offset is the fisheye error of the ground-ray formula): ground distance 0-3 m **1.45**, 3-5 **1.48**, 5-8 **1.48**, 8-12 **1.27**, 12-16 **1.03**, 16-20 **0.84**, 20-30 **0.64**, 30-60 **0.39**. Relative to the near field, depth shrinks by about 30 % at 12-16 m, 45 % at 16-20 m, 56 % at 20-30 m and 73 % beyond 30 m; **sky reads 12 m** (p10 8, p90 14). So a building 30 m away lands at 6-12 m on the map, which is where the "distant wall mapped at 4-9 m" false faces come from. Two of the FPs are different: #118 (chest0002 136.18 s) has no depth scale and a bad horizon (ground fallback), #168 is a building base occluded by a car (the visible base is the roof line). No map-side fix; a distance cap or a range correction of the depth would be the next step.

**Inside solid areas → snap (user decision 2026-10-25).** The user's first wording was "notifications of collisions inside solid areas" are impossible; the first build suppressed them (3 notifications removed on the fixtures, none a ✓; 52 notifying items were inside solid). The user then decided they must not be discarded: "adjust their position to the solid area collision border, its a depth issue therefore correction". **Built:** `insideSolid.mode "snap"` (`"suppress"` / `"off"` for A/B): solid = fused wall-like cells (confidence ≥ 0.7); an item (static of another class, mover, coasting mover; wall-like items never count against their own face) whose own bearing ray meets ≥ `minRayCells` (3) consecutive solid cells more than `solidDepthM` (0.8 m; the 0.5 m / 2 cells start value moved a ✓ pole call and lost 287.66 pole in review 6, 1.0 m / 4 cells was no better than 0.8 / 3) before the item is **moved along its ray to the first solid cell** (distance, lateral, bearing, clock, steps recomputed; every later rule sees the corrected values). Hazards JSON `insideSolid`, `solidCorrected`, `rawDistanceM`; the Lab panel draws a dashed line from the raw to the snapped position. **Measured** (fixtures + run, snap vs off): **795 snapped item episodes (2003 item-frames)**, mostly far poles / signs / persons with no notification; **changed events: 107.51 "person at 12:15 in 5" removed → 108.49 "person at 11:45 in 5" added** (chest0004 review 8 and the run; 108.49 is the user's ✓ that v26.2.1 had and the first full-suite design had shifted), nothing else changes. 295.50 "obstacle at 12 in 7" (4929 r4), which the suppress mode removed, is kept as before. Synthetic test: an item behind a wall face is snapped to the wall's near border on its bearing.

**Movers that vanish coast (`_Coast`).** A person / rider / animal / vehicle measured for ≥ 3 frames over ≥ 0.5 s is followed on its least-squares world velocity (dead-reckoned pose) for ≤ 2 s (vehicles 3 s) when it vanishes; it stays a collision item (course, beeps, proximity) but is never spoken; it stops on a rematch, passed, > 30 m, time up, or inside solid. **Real cases (fixtures, 8028 frames):** 927 episodes (706 vehicles, 213 persons, 8 riders), **173 start within 10 steps**; ended by rematch 722 (mostly 1-3 frame segmentation dropouts), expired 91, passed 50, out of range 48, window end 16; 20 episodes held a danger frame and 8 a collision beep. Event changes it causes (against the same run without coasting): 6 added beeps (person 3 steps 42.50 r3; 190.98, 243.66, 243.99 r4; 190.98, 282.49 r6), 2 soft beeps lost (47.01 r5, 93.19 moved), 1 vehicle phrase "approaching at 12" at 93.84 (r5) said earlier because the track stayed alive; no ✓ touched.

**Ghost beeps (real-case check).** One real ghost in all fixtures and the run: chest0002_crosswalk 350.68-351.18 s, a barrier fence leaving the bottom of the frame (4 frames, down to 1.9 steps, 1 beep event in the span). Too thin to tune the thresholds; unchanged.

**Pass rule on the 9 fixtures (v26.2.1 → v26.2.2), 80 ✓ that v26.2.1 produced:** 74 identical (≤ 0.6 s), 5 moved by 0.8-1.7 s (an earlier call on a wall judged on the map: 97.00 pole → 97.66, 97.16 person → 98.16, 139.84 building 8 → 138.34 in 9, 141.01 obstacle 6 → 140.01 in 7, 39.50 beeps → 41.17), **1 lost (150.50), 1 ✗ back (28.50)**. The user decided not to block on this: shipped, listed below. Events: 4929 review 1 unchanged, r2 one clock moved, r3 +2, r4 +10 / −1, r5 +4 / −3, r6 +9 / −1, chest0002 +6 / −1, chest0004 r7 +2, r8 +21 / −6 (Σ +54 / −12 against v26.2.1). **Every new wall event with its label** (candidate ids of `debug/v26.2.2/index.json`; unique events, repeats across overlapping fixtures dropped): 26 face (e.g. 5, 11, 13, 27, 111, 135, 156, 175, 179), **6 edge** (70 distant fence 304.85 r6, 137 building 26.33, 138 building 35.67, 153 building 96.50, and the same events in the run), **11 unsure** (71 fence 305 r4/r6, 91 351.52, 119 350 chest0002 ...), and 11 events that are not a wall (movers / a sidewalk-obstacle / beep repeats).

**Run `116731b3e5c2`** (Chest-center-0004 0-155 s, CPU, v26.2.2, Lab restarted after the bump, same request and id as before; worldmap built in 4.6 s, 4.9 ms/frame): events 92 → **127** (speech 33 → 37, collision beep episodes 14 → 31, tones 39 → 59); 64 coasting episodes, 366 coasting item-frames, 611 snapped item-frames, 591 hazard frames with a face / edge result. Building speech: 6.17 "in 2", **13.50 "building at 12 in 8"**, 26.33 "at 12:15 in 4" (#137 edge false call), 35.00 (#138), 54.50, 89.84, 96.50 "at 12:15 in 6" (#153 edge false call), 138.51 "at 12 in 10", 144.33 "at 12:30 in 3".

**Tests (final).** Unit **587 passed, 6 skipped** (581 → 587: the 6 tests of `test_collision_v2622.py`); browser E2E (`tests/e2e/run.sh`, run only after the analysis had finished) **68 passed**.

**Cost.** Collision pass ms/frame on the fixtures (8028 frames, same machine): v26.2.1 13.9 → v26.2.2 **14.8** (face / edge test, solid rays, coasting included); with the Phase A diagnostics only 17-18.

**Tests.** Unit suite green after re-pinning: version asserts → v26.2.2; the review fixtures that pin v26.1.x numbers (`test_collision_regression.CONFIG`, used by all `_run_windows` tests) now run on the v26.2.0 rules (`staticSource: image`, `coast.enabled: false`) because the default config moves a few events in time (known issues); `test_collision` output-key sets (+ `faceEdgeLines`, `faceEdge`, `insideSolid`, `solidCorrected`, `rawDistanceM`, `coasting`, top-level `coast`); `test_collision_depth.strip` ignores the map diagnostics; `test_collision_v2621` config keys (the building-section gates are gone) and review 7 (13.50 "building at 11:45 in 8", face from 12.33 s); golden hash `GOLDEN_CHEST0004_REVIEW7` re-pinned. New `tests/test_collision_v2622.py` (config, an item behind a wall is snapped to its face, nothing snapped in front / within the margin / for wall-like items, suppress mode, face vs edge cells, a vanished mover coasts and is not spoken).

### Known / possible issues (shipped on purpose; the user decided not to block on the pass rule)
1. **150.50 ✓ moved to 144.33.** "building at 12:45 in 3" (chest0004 review 8) is no longer said at 150.50; the same building is now called earlier as a face danger at 144.33 "in 3" (+ beeps, candidate 179, labelled face) and the speech memory suppresses the context repeat.
2. **28.50 ✗ back, caused by the #137 edge false call at 26.33.** The user's "should not be said" "person at 12:15 in 6" returns because the new false "building at 12:15 in 4" at 26.33 (a facade recess read as a face, protrusion 0.69 m) shifts the speech gap: the person ✓ at 27.33 becomes 27.99 and a person call lands at 28.50 again. The same mechanism moves 97.00 / 97.16 / 108.49-type calls by 0.6-1.0 s (the 96.50 building at 12:15 in 6, #153, is another edge false face).
3. **The 10.9 s Chest-0004 building is still spoken at 13.50 s ("in 8"),** not 10.9-11.9 s: the first face frame on the map is 12.33 s at 10 steps in the collision pass (10.99 s in the phase A episode run) and the speech policy needs a confirmed, settled danger; v26.2.0 said it at 11.83. Beeps at 15.33 "5→4 steps".
4. **6 new edge events and 11 unsure events** (see the labels above): residual false wall dangers (facade recesses 137 / 138 / 153, a distant fence 70) and ambiguous ones; precision 0.82 / recall 0.73 on the labelled set, the low sea wall across the path (5, 7, 9, 10, 12, 24, 25) is missed by the map (1-2 cells, no wall line).
5. **DA2 depth compresses distances beyond ~12 m** (ratio table above): distant buildings / fences map at 6-12 m and can become faces (46, 70, 118, 168); sky reads 12 m. Not corrected; the snap only fixes objects behind a wall face the map already knows.
6. **Snap side effects:** 795 item episodes were moved (mostly silent far items). Poles / signs standing in front of a facade can be moved to a nearer wall corner on their ray (the 0.5 m / 2 cells setting moved the 287.66 pole ✓ and made a pole call at 96.33 "in 3"; 0.8 m / 3 cells does not on the fixtures, but a pole next to a nearer facade corner is the case to watch). A snapped item's `imageDistanceM` is not kept (`rawDistanceM` is).
7. **Coasting side effects:** a vanished vehicle / person is predicted on a velocity of a few frames (dropouts mostly bridge 1-3 frames; 91 episodes ran the full 2-3 s); a person who stops behind an occluder is still predicted to walk on. The track staying alive can make a returning vehicle be announced one frame earlier (93.84 "vehicle approaching at 12"). Coasting is also active while the user stands still only for a mover on a collision course.
8. The review fixtures of v26.1.x are pinned on the v26.2.0 rules in the unit tests (see Tests); the default rules differ from them by the events above.

## v26.2.3 — ground + depth distance, a horizon on/off switch, user height 1.78 m (plan [`plans/v26.2.3.md`](plans/v26.2.3.md); user requests 2026-10-25; collision + worldmap version bumped, Lab wiped, run `116731b3e5c2` re-created)

**What was built.**
- `distance.objectDistance` = `depth | ground-contact | ground+depth` (`src/groundfuse.py`; CONTRACTS §7.3b), **one setting for the collision pass (item and mover distances) and the world map (object bases)**: the pass stores the setting and, per frame, the correction curve (`depthCorrection`) in hazards.json, and the offline map build reads them from there, so the map uses exactly what the pass used. Per item `distanceSource` (`depth | ground | fused`), `rawDepthM`, `groundM`.
- `ground+depth`: per frame a range-correction curve rho(depth) fitted on the walking-region cells (depth ÷ ground ray, binned by depth, log-EMA 1 s, held 2 s, non-increasing, the DA2 squash table as the prior beyond the farthest bin); `corrected = depth / rho`; a base in contact (not clipped, a surface class below it) inside the band (>= 4 rows below the horizon) is fused with the ground ray by inverse variance (ground sigma from the horizon jitter of the stored track + 0.5 row of quantisation, depth sigma 12 % / rho); sanity gate: a base in contact is never nearer than 0.7 x its ground ray. Closing speeds keep using the raw depth history.
- **Ground ray = the lens geometry, not the pinhole formula (deviation from the plan, on purpose).** The plan's `H f / ((y - horizon) gh)` is 1.45 times off in the near field under the 118 deg fisheye, and wrong towards the image sides (the first build moved a building at the image edge from 1.6 m to 4.4 m; its first measurement lost 18 ticks, most of it from that). `groundfuse.ground_z` intersects the pixel's ray (equidistant fisheye / pinhole) with the floor for the pitch the horizon implies and returns the z-depth, the quantity DA2 holds; `ref` (q) is then the residual factor (~1; 0.8 for the legacy-mount settings of Chest-center-0004). The plan's "correction = depth / r(depth)" with r = 1.45 near would have moved the whole near field by 31 %; the curve is therefore normalised by `ref` so that the near field is unchanged.
- `useHorizon` (per run, Lab **Horizon On / Off** next to Object distance, below Lens / Distance; both saved with the recording's settings and passed by the collision pass; **Re-run collision also rebuilds an existing `worldmap.npz`**). Default **true**.
- **What `useHorizon=false` removes:** the ground ray in every object / mover distance (distance = depthScale x DA2 only: no correction, no fusion, no gate; hazards identical to `objectDistance: depth` for the items that are not map-judged); in the world map the object bases (depth only; no depth = no bases) and the **surface projection (surfaces are back-projected through the depth map with the lens ray model, forward = z cos(pitch) - y sin(pitch) with the plane-fit pitch, each pixel splatted over its footprint)**. **What it keeps (needs the horizon):** the horizon estimate itself and the pixel danger lane (the image rule's corridor), the below-horizon / 30 m pre-filter of item detection, ground-based track matching and the ground closing of items without depth, items and bases without a depth value (items fall back to their ground distance; map bases are dropped), and the **depth scale calibration** (the plane fit uses the horizon only for its row cut and the fixed anchor horizon; the gait level does not). `distanceSource: ground` runs are untouched.
- **User height 1.78 m** (`body.defaultUserHeightM`, user correction 2026-10-25: "my height is not 1.7m its 1.78"; recordings.py / the Lab UI placeholder / tests read the config value; the recording settings of Chest-center-0004 now carry 1.78 m + chest location, so the body calibration applies: camera 1.282 m, step 0.739 m instead of the legacy mount 1.30 m / 0.70 m).

**Measurement.** Fixtures (9, 8028 frames) and run `116731b3e5c2` (Chest-center-0004 0-155 s), all in body mode (chest location; user height as stated) at **1.78 m** unless said; ✓ = the user's ticks, against `depth` at 1.78 m (= v26.2.2 rules) unless said. Machine shared with the training container; ms = collision pass only.

*Height alone (v26.2.2 rules, 1.70 m → 1.78 m):* 67 ticks produced by both: 65 identical (≤ 0.6 s), **1 moved** (49.67 "curb at 12 in 3" → 48.17 "in 2", 4929 r3), **1 lost** (114.33 "pole at 1 in 2", chest0004 r8; steps 2 → 1.x at the closest range), 0 ✗ back. Events 5/24/23/61/27/67/52/11/72 → 6/25/22/61/26/65/49/11/70 per fixture (Σ gained 31 / lost 38; mostly "in N" step numbers). Wall set: precision/recall 0.73/0.73 (27/10/10) at 1.70 → **0.82/0.73 (27/6/10)** at 1.78; run: 72 → 68 events, buildings spoken 10.33 / 12.16 / 26.33 / 35.00 / 54.50 / 89.84 / 96.33 / 138.17 / 144.33 at 1.70, 10.83 / 12.33 / 26.33 / 35.00 / 54.50 / 89.84 / 139.84 at 1.78. The 1.78 m numbers are the reference below (the wall set is better at 1.78 m).

*Variants (horizon on except D):*

| variant | ✓ same / moved / lost | ✗ back | events gained / lost | wall set TP/FP/FN, prec/rec | 46 / 70 / 118 / 168 fire (FP) | new wall events: face / edge / unsure | collision ms/frame |
|---|---|---|---|---|---|---|---|
| depth (v26.2.2 rules, reference) | 68 produced: 68 / 0 / 0 | 0 | – | 27/6/10, **0.82/0.73** | 46, 70, 118 / – (168 not) | – | **14.4** |
| ground-contact | 50 / 6 / **12** | 1 | 84 / 65 | 29/9/8, 0.76/0.78 | 46, 70, 118 | 16 / 4 / 2 | 15.8 |
| ground+depth (corr + fusion + gate) | 49 / 7 / **12** | 1 | 79 / 64 | 26/13/11, 0.67/0.70 | 46, 70, 118 | 10 / 6 / 2 | 16.1 |
| E: correction only | 61 / 6 / 1 | 2 | 40 / 31 | 25/5/12, 0.83/0.68 | 70, 118 (**46 fixed**) | 9 / 2 / 3 | 15.8 |
| F: correction + gate | 61 / 6 / 1 | 2 | 40 / 31 | 23/5/14, 0.82/0.62 | 70, 118 (**46 fixed**) | 9 / 2 / 3 | 15.9 |
| depth, horizon off (D) | 67 / 0 / 1 | 0 | 20 / 35 | 8/4/29, 0.67/**0.22** | 168 only (the map misses most walls) | 14 / 4 / 0 | 15.3 |

("new wall events" = labelled candidates behind the events a variant adds against depth; the unlabelled and the non-wall events (movers, beeps) are not counted: ground+depth adds 57 non-wall events, E 25.) Lost ticks of ground+depth: 15.68 "obstacle at 12:15 in 7", 23.65 "pole at 12:15 in 14", 37.33 "crosswalk at 11:45 in 9", 48.67 beeps "obstacle at 12 · 5 steps", 59.18, 132.84 / 145.81 / 210.84 / 380.67 / 394.19 "crosswalk at 12 in 14-15" (the landmark threshold at 15 steps), 188.98, 287.66 "pole at 12:30 in 8", 367.99 "curb at 12 in 8", 383.34, 0.83 "pole at 11:45 in 9", 1.17, 2.00; ✗ back: 90.51 "person approaching at 1". Ground+depth moves distances by a few percent, and the calls sit on step thresholds tuned on raw depth (landmarkSteps 15, 8-10 steps), so every tick near a threshold moves. Correction only (E / F) lost 1 tick (102.84 "obstacle at 12:15" beep 5→2 steps; plus 15.68, 23.65, 132.84, 210.84, 380.67, 383.34 moved by 1-2 steps) and brought 2 ✗ back (90.51, 132.34 "obstacle at 12:30 in 8").

*Depth ÷ ground ray table (run, surface pixels per ground-ray bin, ÷ `ref`, raw → after the correction):* 0-3 m 1.06 → 1.03; 3-5 0.99 → 1.01; 5-8 0.99 → 1.04; 8-12 0.98 → 1.08; 12-16 **0.87 → 1.09**; 16-20 **0.77 → 1.03**; 20-30 **0.66 → 1.00**; 30-60 **0.44 → 0.73**. The correction does what it is for (the squash is gone to 30 m; beyond that it is only half undone because DA2 hardly changes there). At 1.78 m with the legacy settings of the old table (pinhole formula, 1.45): 1.00 / 0.93 / 0.92 / 0.90 / 0.80 / 0.69 / 0.59 / 0.40.

*The 10.9 s Chest-0004 building:* depth 12.33 "building at 12 in 9" (the building-section call), ground-contact 12.50, **ground+depth 10.83 "building at 12 in 10"** (the target), correction only 12.33, horizon off 13.83. Run events (1.78 m): depth 68, ground-contact 73, ground+depth 75, E/F 74, horizon off 71; sources used (item-frames): ground+depth depth 10073 / ground 213 / fused 12279.

**Chosen defaults.** `objectDistance: "depth"`, `useHorizon: true`. The plan said: keep ground+depth as the default only if the user's ticks are no worse; they are clearly worse (12 lost + 7 moved + 1 ✗ back against 0 / 0 / 0), and the wall set got worse too (0.82/0.73 → 0.67/0.70), so the default is the v26.2.2 behaviour and the option is shipped (Lab settings, per run). Correction only would be the candidate to look at next (it fixes candidate 46 and the squash table; 1 tick lost, 6 moved by 1-2 steps, 2 ✗ back, wall set 0.83/0.68). Horizon off is much worse for the walls (recall 0.22): the map through the depth map has holes and the squash puts distant walls in the wrong cells, and it is shipped as a switch only.

**Tests.** Unit **606 passed, 6 skipped** (587 → 606: `tests/test_collision_v2623.py`, 19 tests: lens ground ray, curve fit / smoothing / hold / prior, fusion weights, no-contact / band, sanity gate, modes, `depth` byte-identical to v26.2.2 (stripped hash), horizon off keeps the depth distances, the map reads the curve and settings, map object bases per mode, map surfaces through depth, Lab settings round trip and pass-through). Re-pinned: version asserts → v26.2.3; `tests/test_collision.CONFIG` and the regression CONFIG pin `distance.objectDistance` = `depth` with a comment; `test_collision` settings keys (+ `objectDistance`, `useHorizon`); golden hash of `chest0004_review7` (only the version string and the two settings keys changed: `test_collision_v2623` proves the stripped hash is the v26.2.2 one); `test_collision_body` reads the default height from the config (user height 1.78 m, user correction 2026-10-25). Browser E2E (`tests/e2e/run.sh`, run with no analysis running): **68 passed**.

**Run `116731b3e5c2`** (CPU, v26.2.3, 1.78 m body calibration with the chest location, `objectDistance: depth`, Lab restarted after the bump, same request and id; worldmap built in 4.9 s, 5.2 ms/frame): 68 events (the `depth` row above), buildings spoken 10.83 / 12.33 / 26.33 / 35.00 / 54.50 / 89.84 / 139.84.

### Known / possible issues (shipped on purpose; user rule 2026-10-25: don't block)
1. **ground+depth and ground-contact are worse than depth on the user's ticks** (12 lost, 7 moved, 1 ✗ back; wall set 0.67-0.76 precision), so they are not the default. Candidates 46, 70 and 118 still fire as faces with both (the far trees / fence / building are mostly not "in contact" with a surface the walking region sees, or sit above the band); 168 is not a false face at 1.78 m even with depth. The correction alone fixes 46 only.
2. **The 10.9 s building is spoken at 10.83 s only with ground+depth**; with the default depth it is 12.33 s ("in 9"), as in v26.2.2 (known issue 3 there).
3. **The ground ray assumes a flat floor under a known camera height and a horizon that implies the pitch**; `ref` absorbs a constant error (0.8 on the legacy settings of Chest-center-0004, which is why that recording now has the body calibration), not a slope or a curb edge. The first build with the pinhole formula was biased 1.45 near and wrong at the image sides.
4. **The correction curve is binned by depth and fitted on the walking region only**: past the farthest road pixel it continues with the measured prior (DA2 saturates at 16-18 m, so one metre of depth there is 3-10 m of distance; corrected depths are capped at 45 m), and the DA2 reading of sky is 12 m. Between 30 and 60 m the table is only half corrected (0.73).
5. **Closing speeds (movers) still use the raw depth history**, so with the correction on a far mover's distance and its closing speed are in different units beyond 12 m.
6. **Horizon off:** the map through the depth map has holes at range (splat footprints are capped at 0.6 m), uses the plane-fit pitch only when the run has one, and the image rule's lane / pre-filter / tracking stay on the horizon (listed above); walls get far fewer faces (recall 0.22). It is a switch for A/B, not a recommendation.
7. **Height:** 1.78 m moved 2 ticks (49.67 curb, 114.33 pole) by one step threshold; the other fixtures were already measured at 1.78 m (4929 r4-6, chest0002) or on the legacy mount (r1-3, chest0004 r7/r8 in the unit tests), so only the run and those fixtures change with the config default.
8. Timing: the collision pass costs 14.4 → 15.8-16.1 ms/frame with the correction (+10 %); the map rebuild after a re-run adds 5 s.

## v26.2.4 — review tools: a click readout on the world map, a forward-only map and an Auto-fill that works (plan [`plans/v26.2.4.md`](plans/v26.2.4.md); user request 2026-10-25; collision + worldmap version bumped, Lab cleaned; no run re-created: the user reviews this version with fresh runs)

**Why.** The user will test the v26.2.3 depth options extensively next, so the review tools come first: "for improved review i'll need coordinates, type of region and type of item when i click anywhere on the map … unmapped areas should only return unmapped … speech auto-fill does not work, its rules are simple".

**What was built.**
- **Forward-only map:** the 200 × 200 snapshot of 0.1 m cells keeps its size, but the user now stands on the bottom edge (col 100 / row 200): 20 m ahead, ±10 m to the sides, nothing behind (was row 180 with 2 m behind). The 64 m fusion grid is unchanged. No collision rule reads snapshot rows behind the user (`corr_full` needs `ahead > 0`, the ghost's "passed" test uses the dead-reckoned world position, solid rays start ahead). The Lab's clock spokes, rings and ticks are re-centred on the new origin.
- **Separate layers:** `worldmap.npz` also stores `surface` and `object` (N × 200 × 200, 255 = none). They are the winning surface class and the winning object class of each cell, so an object no longer hides the surface under it. The combined `classes` layer that the collision rules read is unchanged. Maps built before v26.2.4 have no layers.
- **Click readout:** a click on the world map selects a cell (the marker stays across frames until the next click). A box below the map, not overlaid, shows the clock and steps, metres ahead and to the side, the grid cell, the region (surface) class with its safety level, and the object class plus nearby hazards items. A never-observed cell shows only `unmapped`. The data comes from the new endpoint `GET /api/runs/{id}/worldmap/cell?i=&col=&row=` (CONTRACTS §8.1). It replaces the hover readout.
- **Auto-fill:** (1) the form time becomes the playhead (the paused frame), always; (2) it picks the highest-priority object of that analysed frame: role final > danger > feature > context > none, then the higher safety level, then the fewest steps; (3) it fills the phrase, role and type, and never saves. Repeated clicks at the same time cycle to the next candidate. An empty frame says "nothing detected at this time" and still sets the time. With no run loaded it loads the newest finished run that covers the time.
- **Why Auto-fill didn't work (cause read from the code change; the build session's reproduction notes were not recorded):** it read the form's typed time instead of the playhead, and it stopped with "Load a run to auto-fill." whenever no run was loaded in the review panel. Safety level was also not part of the ranking.

**Collision output.** The same events on every fixture. The regression golden of `chest0004_review7` was re-pinned (`3d5d983c…`, was `e356b6ec…`): 2 of 120 frames differ in item values at the 20 m snapshot edge, now that the forward edge is 20 m instead of 18 m.

**Tests.** Unit **607 passed, 6 skipped** (new `test_forward_only_snapshot_and_separate_layers`; version asserts → v26.2.4; tests that pinned originRow 180 moved to 200). New browser E2E: `test_click_readout_mapped_and_unmapped_cell`, `test_autofill_populates_time_phrase_role_and_type_without_saving`. Browser E2E (`tests/e2e/run.sh`, after the Lab restart): **70 passed**.

**Lab.** The marker was already v26.2.4 (the version wipe ran on 2026-10-25), so the remaining test run `116731b3e5c2` was deleted by hand before the restart: the Lab starts clean for the user's fresh runs. Its default model is now `Yolo26m-sem-HackEye26.1-48-1280.pt` (commit 5477682, the HackEye-Models rename).

### Known / possible issues (shipped on purpose; user rule 2026-10-25: don't block)
1. **Old maps:** a `worldmap.npz` built before v26.2.4 has no separate layers; its readout shows only the combined class. The Lab was cleaned, so this only matters for maps copied in from elsewhere.
2. **Nothing behind the user is shown any more.** Rules that need it read the fusion grid, but a reviewer can no longer see what the map remembers behind.
3. **The DECISIONS entry was written at commit time from the plan and the code change.** The build session left no notes on worker deviations or measurements beyond the tests.

## v26.2.4 follow-up — Open issues panel and a Notes box in the Lab (plan [`plans/v26.2.4-followup-notes.md`](plans/v26.2.4-followup-notes.md); user requests 2026-10-27; no version bump, no Lab wipe)

**Why.** The user asked for "a freeform text box where i'll write reviewes, remarks and fix requests". While that was being built, they added: "above freeform review add open issues group with subgroups as presented before in here where i can click the issues and close and comment on them to be used here, similar to reviews."

**What was built.** Both panels sit at the top of the review panel. Open issues comes first and Notes below it.
- **Open issues (N open):** the same list and groups as `plans/v26.2.md`:
  - Open issues O1–O6
  - Needs your decision 5–9
  - Untested or technical debt 10–14
  - Long-term, on hold 15–17
  - Closed (items 1–4)
  
  Each row has Close / Reopen. A click expands its details and a comment box that autosaves like the review notes. The catalogue is `lab/issues.json` in the repo, kept by Claude together with the plan. The user's close, reopen and comment state is `LAB_DIR/issues-state.json`, which survives version wipes. CONTRACTS §9.5.
- **Notes:** one Lab-wide freeform document, `LAB_DIR/notes.json`, which also survives wipes. Each save keeps the previous text in `notes.prev.json`. It autosaves and retries when offline. **⏱ Insert time** adds `[<recording> @ m:ss.s · run <id>]` at the cursor. A save from a stale tab or device gets a 409 and a Load theirs / Keep mine choice, so nothing is overwritten silently. CONTRACTS §9.4.
- **Export:** `GET /api/reviews/export` now carries `notes` and `issues` (only the issues the user touched). Claude already reads that export at the start of every Lab task, so notes and issue actions are picked up exactly like reviews. Claude never edits the user's notes. A closed issue is moved to "Closed" in the plan and in the catalogue, with the user's comment as the reason.
- **No version bump:** this is Lab tooling with no change to analysis output, following the precedent of the v26.1.14 ETA and the v26.1.15 orientation follow-ups. The user's run `5fda5626e808` (0–454 s, 42 min on CPU) was kept.

**Worker notes.**
- A Sonnet worker built both panels. Opus wrote the plan, the issue catalogue and the docs.
- Opus added `DELETE /api/issues/{id}/state`. It resets one issue to the catalogue state, so the E2E cleanup leaves no "touched" marks in the export.
- Opus fixed two E2E test mistakes: a Playwright `arg=` keyword, and opening the collapsed Closed group before clicking Reopen.

**Tests.**
- Unit: **619 passed, 6 skipped**. New: `test_lab_notes.py` (6) and `test_lab_issues.py` (6).
- Browser E2E after the Lab restart: **75 passed**, with the new `test_notes.py` (3) and `test_issues.py` (2). The E2E tests back up the user's notes and issue state and restore them.
- Screenshots were checked at 1500 px and 390 px, with no horizontal scroll.

### Known / possible issues
1. With every group open, the issue list is long and pushes the notification list down the review panel. The section and each subgroup collapse, and the choice is remembered per browser.
2. The E2E notes restore writes the notes back, so `notes.json` gets a new `updatedAt` even when the text is unchanged. An open Lab tab may then show the conflict notice once if it had unsaved edits during a test run.
3. The issue badges use the id as written, so `O1` can look like `01` in the badge font.

## v26.2.5 — walls on the world map as solid faces, stale walls cleared (plan [`plans/v26.2.5.md`](plans/v26.2.5.md); user note in the Lab Notes box 2026-10-29; collision + worldmap version bumped, Lab wiped: run `5fda5626e808` removed)

**Why.** The user's note on run `5fda5626e808` (Chest-center-0004, ground+depth): "at time 0, building is detect on the right with representation of boundary on video image but only a few pixels on the world map … world map at around 1:45 and 2:00 should items when its definitly a wall like the bounding lines show, correct this issues." No speech reviews were exported, so there were no fixtures to save.

**Diagnosis (Opus).** (1) Frames 0–1 had no `depthScale` (the plane anchor needs 3 fits), so at 0 s the facade gave only horizon-placed contact bases: 72 cells. (2) Each object base was one edge pixel read alone; edge depth mixes the wall with what is below or behind it, and most bases sat on a sign, pole, tree, car or sky rather than the ground, so walls landed as dashes from 3 to 20 m. (3) The combined map's argmax let surface votes hide the thin wall line (115 s: 8,570 object cells → 1,492 shown). (4) Fusion only ever added object votes, so jittered faces accumulated into a cloud over the 6 s half-life.

**What was built (Sonnet worker, Opus review).**
- **Frame 0–1 depth scale:** the collision pass reports the frame's own plane-fit scale as `depthScale` on frames 0–1 (the anchor `a_now` itself is unchanged, so ego speed and items are not affected); the world map falls back to the nearest known scale of the run when a frame has none.
- **Wall faces (`faceClasses`):** per image column, the distance is the median depth of the bottom `faceDepthRows` 6 rows of the run (all object bases use this median now); ground+depth fusion only for bases standing on a surface; bases on sky dropped; running median over ±`faceSmoothCols` 3 columns with an outlier drop (`faceOutlierFrac` 0.25); adjacent columns within `faceJoinFrac` 0.2 (gap ≤ `faceJoinCols` 2) are joined by a rasterised line `faceThicknessM` 0.3 m thick.
- **Objects win their cells:** an object class wins a combined cell when the object votes are ≥ `objectWinShare` 0.35 of the total. Its `conf` is from the object weight (otherwise it would sit under `mapMinConf`).
- **Negative evidence:** cells the current frame sees as ground multiply object votes by `objectClearFactor` 0.3, and so do the cells along each face column's ray up to the face minus `objectClearMarginM` 0.3 (`objectClearRays`). Cells within the margin of the frame's own objects, and cells nearer than the last image row's ground + `objectClearBottomM` 0.5 (objects whose base just left the image, e.g. a pole being passed), are not cleared.

**Before → after on run `5fda5626e808`** (map built in memory; scatter = building + wall cells > 0.5 m from up to 3 RANSAC lines):

| t (s) | combined building | combined wall | fused object cells | fused scatter |
|---|---|---|---|---|
| 0 | 72 → 420 | 0 → 12 | 72 → 432 | 0 → 19 |
| 1 | 957 → 1313 | 6 → 9 | 1073 → 1328 | 461 → 314 |
| 3 | 1941 → 2048 | 15 → 19 | 2415 → 2119 | 1235 → 754 |
| 105 | 2248 → 2138 | 512 → 194 | 4468 → 2304 | 3045 → 1101 |
| 115 | 1492 → 1296 | 15 → 41 | 8647 → 1860 | 6141 → 898 |
| 120 | 3376 → 4247 | 463 → 538 | 9056 → 5798 | 6258 → 3187 |

At 0 s the right facade is a continuous line; at 105 s the walls are thin lines at 15–16 m instead of a cloud. World map 6.8–7.3 → 10.8 ms/frame mean (p95 7.5–9.1 → 12.5).

**Collision output.** `chest0004_review7` window 0: 13.50 "building at 11:45 in 8" → "building at 12 in 8" (same time and steps); beep 15.33 "5→4 steps at 12:15" → 15.67 "5→4 steps at 12". The first map face of the 10.9 s building is at ~11.5 s (was 12.33). Goldens re-pinned (`GOLDEN_V2622` `7cac303f…`, `GOLDEN_CHEST0004_REVIEW7` `d301fe13…`; both also carry `depthScale` on frames 0–1). The 4929 reviews and every other pinned test are unchanged. Worker deviations: frames 0–1 (not only 0) lacked a scale; the object-win `conf` rule above; a synthetic pole fixture got vertical object depth (`_vertical_objects`) because the bottom-rows median misreads a depth map that gives every row the ground distance; the ray clearing and the bottom band were needed (with ground clearing only, scatter stayed 3408 / 6216 at 105 / 120 s).

**Tests.** Unit **629 passed, 6 skipped** (8 new: noisy facade → one line, outlier column dropped, base on sky dropped, thin wall wins against surface, depth-scale fallback, frame-0 scale seeding, stale wall cleared by seen ground, current wall protected by the margin, face ray clears free space). Browser E2E **75 passed**.

### Known / possible issues (shipped on purpose; user rule: don't block)
1. **Stale votes where nothing is seen:** cells the current frame neither sees as ground nor covers with a face ray keep old wall votes until they decay (120 s: a wedge behind the hand holding the cane).
2. **Fewer wall cells at 105 s:** barrier-wall cells in the combined map are 194 (512 before). Most of the old ones were the stale cloud, but some real wall may be cleared too; not checked cell by cell.
3. **Far false faces are more visible:** faces are now lines, so the DA2 far-range squash (O1) draws clearer false walls at 6–12 m.
4. **Map cost +50%:** 10.8 ms/frame mean (was ~7).
5. **Horizon off:** the `objectClearBottomM` band uses the horizon formula, an approximation when the run has the horizon switched off.

## v26.2.6 — world map built with the run, wall lines always on, cleaner readout, selectable items (plan [`plans/v26.2.6.md`](plans/v26.2.6.md); user note in the Lab Notes box 2026-10-30; Lab version bumped and wiped: run `5fda5626e808` removed; collision + worldmap output unchanged)

**Why.** The user's note on run `5fda5626e808` (Chest-center-0004, v26.2.5): build the map when collision detection finishes and drop the Build button; wall lines always on; the "Beyond 20 m (low trust, …)" line in the click readout showed for almost any cell, even right in front of the user, and said more than was asked; the object at 12:30 / 1.5 m ahead / 0.5 m right should be selectable, but a click read the sidewalk under it; no white circle for buildings (cells and wall lines are enough). No speech reviews were exported, so there were no fixtures to save.

**Diagnosis (Opus).** The job ran only the collision pass; the map came from `POST /worldmap` (the button). The "Beyond 20 m" line listed every hazard of the frame past 20 m / ±10 m, whatever the cell. At 0 s the obstacle is a danger item at 1.58 m / 0.58 m right, drawn as a dot, but the map's object layer is empty there (cells 105,183–185 = none, 104,185 = sidewalk), so the readout led with "Region: flat sidewalk · Object: none".

**What was built (Sonnet worker, Opus review).**
- `_run_job` runs `worldmap_pass` after `collision_pass`, before the run is done (a failure is logged; the run still finishes). `POST /collision` always rebuilds the map. `POST /worldmap` stays as an API; `#wmBuild` is gone.
- `#wmRules` and its localStorage key are gone: the wall lines, face and edge cells are always drawn.
- The readout's "Beyond 20 m" line is removed.
- A click within an item marker's drawn radius (at least 8 CSS px, danger ring included; nearest wins) selects the item and snaps the selection to its cell. `Object:` names the item (class · role · track · distance source), plus `map: <class>` when the cell has one; it follows the item by track id while it stays on the cell. Without a hit: the map's object class, else the nearest marker covering the cell, else "none".
- Items of class building, structure bridge and structure tunnel get no marker (dot, ring, snap line, cross). Their cells still read them on a click.

**Tests.** Unit **632 passed, 6 skipped** (3 new in `tests/test_worldmap_job.py`: re-run builds a missing map, re-run survives a failing map pass, the job helper builds / swallows failures). Browser E2E **76 passed** (map present without a click, no Build / wall-lines controls, no "Beyond 20 m", a click on an item marker names it).

### Known / possible issues (shipped on purpose; user rule: don't block)
1. **Small objects missing from the object layer (O9):** the 0 s sidewalk-obstacle has no object cells on the map. Its marker is now clickable, but the map cells and the rules that read the map still miss it.
2. **Longer jobs:** a run finishes after its map is built (~11 ms/frame, about 30 s for a 454 s run at 6 fps).
3. **Buildings with role danger** show no marker any more; the danger is visible only through the wall cells and lines (and speech).
