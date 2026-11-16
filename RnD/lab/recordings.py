"""Media discovery, GoPro chapter grouping and the browser-proxy builder.

Discovery, chapter grouping, per-recording settings and the sensors path moved to `lab.store.recordings` (v26.3.0 p5-02, audit 7.8);
the proxy builder (an ffmpeg thread, its status dict and the proxy file paths) moved to `lab.jobs.proxy` (p5-03). Every moved name stays
reachable here as a forward to its home (`recordings.LAB_DIR`, `recordings.get_recording`, `recordings.proxy_status`, ...).

GoPro splits a long take into ~4 GB chapters (GOPR4927, GP014927, GP024927).
The Lab treats them as one continuous timeline: the proxy is a concat of all chapters so proxy time equals recording time.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lab._forward import install  # noqa: E402

# v26.3.0 p5-03: the proxy builder moved to lab.jobs.proxy (audit 7.8)
install(__name__, {
    **dict.fromkeys(
        ("MEDIA_DIR", "LAB_DIR", "VIDEO_EXTENSIONS", "_GOPR", "_GP", "sensors_path", "sensors_for", "_VideoInfo", "_info_cache",
         "_probe", "_group_key", "scan_recordings", "_NAME", "name_hints", "_input_sizes", "list_recordings", "get_recording",
         "recording_frame_at", "_settings_path", "_body_locations", "_distance_defaults", "get_settings", "save_settings"),
        "lab.store.recordings"),
    "_atomic_write_json": "lab.store.util",
    **dict.fromkeys(
        ("PROXY_WIDTH", "_log", "proxies_dir", "proxy_path", "_proxy_lock", "_building", "proxy_status", "_set_proxy", "start_proxy",
         "_build_proxy"),
        "lab.jobs.proxy"),
})
