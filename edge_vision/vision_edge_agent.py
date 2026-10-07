from __future__ import annotations

import argparse
import json
import math
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from collections import deque
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import requests

try:
    from cv2_enumerate_cameras import enumerate_cameras as enumerate_cv_cameras  # type: ignore
    CAMERA_ENUM_IMPORT_ERROR = ""
except Exception as exc:
    enumerate_cv_cameras = None
    CAMERA_ENUM_IMPORT_ERROR = repr(exc)

try:
    cv2.setLogLevel(0)
except Exception:
    pass

try:
    import mediapipe as mp  # type: ignore
    MEDIAPIPE_IMPORT_ERROR = ""
except Exception as exc:
    mp = None
    MEDIAPIPE_IMPORT_ERROR = repr(exc)

try:
    from ultralytics import YOLO as UltralyticsYOLO  # type: ignore
    ULTRALYTICS_IMPORT_ERROR = ""
except Exception as exc:  # agent can still run camera/ROI checks without YOLO
    UltralyticsYOLO = None
    ULTRALYTICS_IMPORT_ERROR = repr(exc)

APP_DIR = Path(__file__).resolve().parent
LEGACY_STATE_DIR = APP_DIR / "vision_edge_state"
if os.name == "nt" and os.getenv("LOCALAPPDATA"):
    STATE_DIR = Path(os.environ["LOCALAPPDATA"]) / "NEXis" / "VisionEdge"
else:
    STATE_DIR = LEGACY_STATE_DIR
STATE_DIR.mkdir(parents=True, exist_ok=True)
STATE_PATH = STATE_DIR / "state.json"

def migrate_legacy_state() -> None:
    if STATE_DIR == LEGACY_STATE_DIR or not LEGACY_STATE_DIR.exists():
        return
    for name in ["state.json", *(f"baseline_{k}.jpg" for k in ("adxl345", "acs712", "hall_sensor"))]:
        src = LEGACY_STATE_DIR / name
        dst = STATE_DIR / name
        if src.exists() and not dst.exists():
            try:
                dst.write_bytes(src.read_bytes())
            except Exception as exc:
                print(f"[STATE] legacy migration skipped for {name}: {exc}")

migrate_legacy_state()
SENSOR_KEYS = ("adxl345", "acs712", "hall_sensor")
ROI_LABELS = {
    "hall_led": "HALL LED",
    "rotor": "ROTOR",
    "adxl345": "ADXL345",
    "acs712": "ACS712",
    "hall_sensor": "HALL SENSOR",
}
COLORS = {
    "danger": (80, 80, 255),
    "warning": (0, 190, 255),
    "safe": (80, 220, 140),
    "unknown": (160, 160, 160),
    "unconfigured": (160, 160, 160),
    "hall_led": (80, 220, 140),
    "rotor": (255, 170, 70),
    "adxl345": (0, 190, 255),
    "acs712": (255, 210, 60),
    "hall_sensor": (220, 120, 255),
}

# Vision analysis parameters.
LED_WARMUP_FRAMES = 20
LED_HISTORY_SECONDS = 4.0
LED_GREEN_H_MIN = 35
LED_GREEN_H_MAX = 95
LED_GREEN_S_MIN = 45
LED_GREEN_V_MIN = 45
LED_GREEN_DOMINANCE_MARGIN = 10.0
LED_GREEN_MIN_PIXELS = 4
LED_HIGH_RATIO_ABS_MIN = 0.0020
LED_HIGH_RATIO_BASE_ADD = 0.0012
LED_HIGH_RATIO_NOISE_GAIN = 6.0
LED_LOW_RATIO_BASE_ADD = 0.00045
LED_LOW_RATIO_NOISE_GAIN = 2.5
LED_GREEN_RATIO_RISE_MIN = 0.0010
LED_SIGNAL_RISE_MIN = 1.80
LED_LOCAL_P95_MIN = 2.20
LED_LOCAL_ACTIVE_RATIO_MIN = 0.0010
LED_LOCAL_ACTIVE_RATIO_MAX = 0.45
LED_LOCAL_PIXEL_DELTA = 5.0
LED_EVENT_HOLD_SEC = 5.0
LED_MIN_EVENT_GAP_SEC = 0.080
LED_MIN_BLINK_EVENTS = 2

ROTOR_CONFIRM_WINDOW = 12
ROTOR_ON_MIN_COUNT = 3
ROTOR_OFF_CONFIRM_FRAMES = 28
ROTOR_HOLD_SECONDS = 1.10
ROTOR_NOISE_HISTORY = 100
ROTOR_MAX_ROI_SIDE = 220
ROTOR_PIXEL_DELTA_THRESHOLD = 5.0
ROTOR_MIN_DIFF_MEAN = 0.75
ROTOR_MIN_DIFF_P95 = 3.50
ROTOR_MIN_ACTIVE_RATIO = 0.0020
ROTOR_MIN_FLOW_MEAN = 0.038
ROTOR_MIN_FLOW_P90 = 0.105
ROTOR_ON_SCORE_ABS = 3.40
ROTOR_OFF_SCORE_ABS = 1.85
ROTOR_NOISE_ON_GAIN = 4.20
ROTOR_NOISE_OFF_GAIN = 2.10

SENSOR_MOUNT_DIFF_THRESHOLD = 55.0
SENSOR_MOUNT_WARNING_FRAMES = 24
SENSOR_MOUNT_WINDOW = 36

# Generic object / unknown-motion intrusion detection.
MOTION_BG_HISTORY = 240
MOTION_BG_VAR_THRESHOLD = 28.0
MOTION_WARMUP_FRAMES = 45
MOTION_MIN_AREA_PX = 260.0
MOTION_MIN_AREA_FRAC = 0.00030
MOTION_MAX_AREA_FRAC = 0.45
MOTION_CONFIRM_WINDOW = 5
MOTION_CONFIRM_MIN_HITS = 2
MOTION_EXCLUDE_PADDING_PX = 8
MOTION_ZONE_OVERLAP = 0.08

EDGE_PROTOCOL_VERSION = 3
LOCAL_PREVIEW_HOST = "127.0.0.1"
LOCAL_PREVIEW_PORT = 8765
LOCAL_PREVIEW_JPEG_QUALITY = 82
LOCAL_PREVIEW_MAX_FPS = 20.0
CAMERA_OPEN_LOCK = threading.RLock()


def _nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except Exception:
        return 0


def load_state() -> dict[str, Any]:
    try:
        if STATE_PATH.exists():
            data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return {
                    "baseline_revision": _nonnegative_int(data.get("baseline_revision")),
                    "reset_revision": _nonnegative_int(data.get("reset_revision")),
                    "config_revision": _nonnegative_int(data.get("config_revision")),
                }
    except Exception as exc:
        print(f"[STATE] invalid local state ignored: {exc}")
    return {"baseline_revision": 0, "reset_revision": 0, "config_revision": 0}


def save_state(state: dict[str, Any]) -> None:
    tmp = STATE_DIR / f".{STATE_PATH.name}.{os.getpid()}.{threading.get_ident()}.{time.time_ns()}.tmp"
    try:
        tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
        os.replace(tmp, STATE_PATH)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass


def baseline_path(key: str) -> Path:
    return STATE_DIR / f"baseline_{key}.jpg"


def clear_baselines() -> None:
    for key in SENSOR_KEYS:
        try:
            baseline_path(key).unlink(missing_ok=True)
        except Exception as exc:
            print(f"[BASELINE] could not delete {baseline_path(key)}: {exc}")


PHONE_CAMERA_NAME_TOKENS = (
    "phone",
    "android",
    "mobile",
    "iphone",
    "continuity camera",
    "link to windows",
    "windows virtual camera",
    "virtual camera",
    "cross device",
    "mobile device",
    "galaxy",
    "pixel",
    "oneplus",
    "xiaomi",
    "redmi",
    "poco",
    "oppo",
    "vivo",
    "huawei",
    "honor",
    "motorola",
    "realme",
    "xperia",
)
CAMERA_DEVICE_CACHE_LOCK = threading.Lock()
CAMERA_DEVICE_CACHE_TS = 0.0
CAMERA_DEVICE_CACHE: list[dict[str, Any]] = []


def _looks_like_phone_camera(name: str) -> bool:
    text = " ".join(str(name or "").casefold().split())
    if any(token in text for token in PHONE_CAMERA_NAME_TOKENS):
        return True
    # Samsung/other Android model identifiers can be exposed without a friendly phone name.
    compact = text.replace("_", "-")
    if compact.startswith("sm-") and len(compact) >= 6:
        return True
    return False


def _enumerated_windows_cameras(force: bool = False) -> list[dict[str, Any]]:
    """Enumerate Windows cameras without opening their video streams.

    DirectShow is preferred because its indices are stable for ordinary USB/integrated
    webcams. If it has no usable local camera, Media Foundation is tried as a fallback.
    Phone/mobile camera names are marked blocked before any stream is opened.
    """
    global CAMERA_DEVICE_CACHE_TS, CAMERA_DEVICE_CACHE
    if os.name != "nt" or enumerate_cv_cameras is None:
        return []
    now = time.monotonic()
    with CAMERA_DEVICE_CACHE_LOCK:
        if not force and CAMERA_DEVICE_CACHE and now - CAMERA_DEVICE_CACHE_TS < 2.0:
            return [dict(x) for x in CAMERA_DEVICE_CACHE]

    def collect(backend: int) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        try:
            for item in enumerate_cv_cameras(backend):
                idx = int(getattr(item, "index", -1))
                name = str(getattr(item, "name", "") or f"Camera {idx}")
                if idx < 0:
                    continue
                items.append({
                    "index": idx,
                    "label": f"Camera {idx}",
                    "device_name": name,
                    "backend": int(getattr(item, "backend", backend)),
                    "blocked": _looks_like_phone_camera(name),
                })
        except Exception as exc:
            print(f"[CAMERA] device enumeration failed for backend {backend}: {exc}")
        by_index = {int(x["index"]): x for x in items}
        return [by_index[k] for k in sorted(by_index)]

    devices: list[dict[str, Any]] = []
    if hasattr(cv2, "CAP_DSHOW"):
        dshow = collect(cv2.CAP_DSHOW)
        if any(not bool(x.get("blocked")) for x in dshow):
            devices = dshow
    if not any(not bool(x.get("blocked")) for x in devices) and hasattr(cv2, "CAP_MSMF"):
        msmf = collect(cv2.CAP_MSMF)
        if msmf:
            devices = msmf

    with CAMERA_DEVICE_CACHE_LOCK:
        CAMERA_DEVICE_CACHE = [dict(x) for x in devices]
        CAMERA_DEVICE_CACHE_TS = now
    return devices


def _allowed_windows_camera_map(force: bool = False) -> dict[int, dict[str, Any]]:
    return {
        int(x["index"]): dict(x)
        for x in _enumerated_windows_cameras(force=force)
        if not bool(x.get("blocked"))
    }


def _camera_index_is_blocked(index: int) -> bool:
    devices = _enumerated_windows_cameras()
    if not devices:
        return False
    for item in devices:
        if int(item.get("index", -1)) == int(index):
            return bool(item.get("blocked"))
    return False


def _camera_index_is_selectable(index: int) -> bool:
    devices = _enumerated_windows_cameras()
    if os.name == "nt" and not devices:
        return False
    if not devices:
        return not _camera_index_is_blocked(index)
    return any(
        int(item.get("index", -1)) == int(index) and not bool(item.get("blocked"))
        for item in devices
    )


def camera_candidates(value: str) -> list[int]:
    if str(value).lower() == "auto":
        devices = _enumerated_windows_cameras()
        if devices:
            return sorted(
                int(item["index"]) for item in devices if not bool(item.get("blocked"))
            )
        # Do not probe anonymous Windows camera indices. Friendly-name enumeration
        # is required so linked/mobile and virtual cameras can be filtered before opening.
        print("[CAMERA] friendly-name enumeration unavailable; camera probing is disabled")
        return []
    try:
        idx = int(value)
    except Exception:
        return camera_candidates("auto")
    if not _camera_index_is_selectable(idx):
        print(f"[CAMERA] Camera {idx} ignored because it is blocked or not a local selectable camera")
        return []
    return [idx]


def _warm_camera(cap, timeout_s: float = 1.4):
    """Give integrated/USB webcams time to produce their first valid frame."""
    deadline = time.time() + max(0.2, float(timeout_s))
    last = None
    good = 0
    while time.time() < deadline:
        ok, frame = cap.read()
        if ok and frame is not None and getattr(frame, "size", 0):
            last = frame
            good += 1
            if good >= 2:
                return last
        time.sleep(0.025)
    return last


def open_camera(value: str, width: int, height: int, fps: int):
    """Open a selected Windows camera without touching blocked phone cameras.

    On Windows, named camera enumeration is used first. When it is available we keep
    capture on DirectShow so the friendly-name index and the OpenCV index stay aligned.
    This prevents Camera 0/1/2 discovery from repeatedly waking a linked phone camera.
    """
    with CAMERA_OPEN_LOCK:
        enumerated = _enumerated_windows_cameras() if os.name == "nt" else []
        fallback_backends: list[int] = []
        if os.name == "nt" and not enumerated:
            if hasattr(cv2, "CAP_DSHOW"):
                fallback_backends.append(cv2.CAP_DSHOW)
            if hasattr(cv2, "CAP_MSMF"):
                fallback_backends.append(cv2.CAP_MSMF)
            fallback_backends.append(cv2.CAP_ANY)
        elif os.name != "nt":
            fallback_backends = [cv2.CAP_ANY]
        seen: set[tuple[int, int, str]] = set()
        for idx in camera_candidates(value):
            if _camera_index_is_blocked(idx):
                continue
            if enumerated:
                device = next((x for x in enumerated if int(x.get("index", -1)) == int(idx) and not bool(x.get("blocked"))), None)
                if device is None:
                    continue
                backends = [int(device.get("backend", cv2.CAP_DSHOW))]
            else:
                backends = list(fallback_backends)
            for backend in backends:
                for profile in ("requested", "default"):
                    marker = (idx, int(backend), profile)
                    if marker in seen:
                        continue
                    seen.add(marker)
                    cap = cv2.VideoCapture(idx, backend)
                    if not cap.isOpened():
                        cap.release()
                        continue
                    try:
                        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                    except Exception:
                        pass
                    if profile == "requested":
                        if os.name == "nt" and backend == cv2.CAP_DSHOW:
                            try:
                                cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
                            except Exception:
                                pass
                        try:
                            cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
                            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
                            cap.set(cv2.CAP_PROP_FPS, fps)
                        except Exception:
                            pass
                    frame = _warm_camera(cap, 1.4 if os.name == "nt" else 0.8)
                    if frame is not None:
                        return cap, idx, frame
                    cap.release()
        return None, None, None


def discover_cameras(width: int, height: int, fps: int, max_index: int = 5) -> list[dict[str, Any]]:
    """Return selectable cameras without opening every Windows camera.

    On Windows this uses DirectShow device enumeration, which makes Camera buttons
    available even when no camera is currently active and filters linked phone cameras
    before anything is opened. Other platforms retain the legacy probe fallback.
    """
    if os.name == "nt":
        devices = _enumerated_windows_cameras(force=True)
        if not devices:
            print("[CAMERA] no friendly-name camera enumeration result; no Windows cameras will be probed")
            return []
        result = []
        for item in devices:
            if bool(item.get("blocked")):
                print(f"[CAMERA] blocked linked/mobile camera: {item.get('device_name', 'unknown')}")
                continue
            idx = int(item["index"])
            if idx <= int(max_index):
                result.append({
                    "index": idx,
                    "label": f"Camera {idx}",
                    "device_name": str(item.get("device_name", "")),
                })
        return result

    found: list[dict[str, Any]] = []
    for idx in range(max(0, int(max_index)) + 1):
        cap, actual, first = open_camera(str(idx), width, height, fps)
        if cap is None or first is None or actual is None:
            continue
        found.append({"index": int(actual), "label": f"Camera {int(actual)}"})
        try:
            cap.release()
        except Exception:
            pass
    by_index = {int(item["index"]): item for item in found}
    return [by_index[k] for k in sorted(by_index)]


def pixel_roi(norm: dict[str, Any] | None, shape) -> tuple[int, int, int, int] | None:
    if not norm:
        return None
    h, w = shape[:2]
    try:
        x = max(0, min(w - 1, int(float(norm["x"]) * w)))
        y = max(0, min(h - 1, int(float(norm["y"]) * h)))
        rw = max(1, int(float(norm["w"]) * w))
        rh = max(1, int(float(norm["h"]) * h))
        rw = min(rw, w - x)
        rh = min(rh, h - y)
        return x, y, rw, rh
    except Exception:
        return None


def crop(frame: np.ndarray, rect: tuple[int, int, int, int] | None) -> np.ndarray | None:
    if not rect:
        return None
    x, y, w, h = rect
    if w <= 1 or h <= 1:
        return None
    out = frame[y : y + h, x : x + w]
    return out.copy() if out.size else None


def polygon_pixels(config: dict[str, Any], shape) -> np.ndarray | None:
    pts = config.get("hazard_polygon") if isinstance(config, dict) else None
    if not isinstance(pts, list) or len(pts) < 3:
        return None
    h, w = shape[:2]
    try:
        arr = np.array([[int(float(p[0]) * w), int(float(p[1]) * h)] for p in pts], dtype=np.int32)
        return arr
    except Exception:
        return None


def effective_warning_margin(config: dict[str, Any], shape) -> int:
    h, w = shape[:2]
    margin = max(0.0, min(500.0, float(config.get("warning_margin_px", 90) or 0)))
    try:
        setup_w = float(config.get("setup_frame_width", 0) or 0)
        setup_h = float(config.get("setup_frame_height", 0) or 0)
    except Exception:
        setup_w = setup_h = 0.0
    # Zone points are normalized, but the warning margin is entered in setup-frame pixels.
    # Scale it when the same-aspect camera resolution changes so the visual/physical margin
    # does not silently shrink or grow with resolution.
    if setup_w > 1 and setup_h > 1:
        scale = min(float(w) / setup_w, float(h) / setup_h)
        if math.isfinite(scale) and scale > 0:
            margin *= scale
    return max(0, min(max(h, w), int(round(margin))))


def config_frame_compatible(config: dict[str, Any], shape, camera_index: int | None = None) -> bool:
    h, w = shape[:2]
    try:
        setup_w = int(config.get("setup_frame_width", 0) or 0)
        setup_h = int(config.get("setup_frame_height", 0) or 0)
        setup_camera = int(config.get("setup_camera_index", -1))
        current_camera = int(camera_index) if camera_index is not None else -1
    except Exception:
        return False
    # Safety/setup coordinates are trusted only for the exact camera index AND exact
    # delivered frame geometry used when the operator saved them. Same-aspect resolution
    # changes are not automatically accepted because some webcam drivers alter crop/FOV.
    if min(setup_w, setup_h, int(w), int(h)) < 16 or setup_camera < 0 or current_camera < 0:
        return False
    return current_camera == setup_camera and int(w) == setup_w and int(h) == setup_h


def build_zone_masks(config: dict[str, Any], shape):
    poly = polygon_pixels(config, shape)
    if poly is None:
        return None, None, None
    h, w = shape[:2]
    danger = np.zeros((h, w), np.uint8)
    cv2.fillPoly(danger, [poly], 255)
    margin = effective_warning_margin(config, shape)
    if margin > 0:
        # A giant morphology kernel becomes extremely slow at large margins
        # (e.g. 1001x1001 for a 500 px margin). Distance transform is effectively
        # independent of the requested radius and gives the same outside-distance intent.
        outside = (danger == 0).astype(np.uint8)
        distance = cv2.distanceTransform(outside, cv2.DIST_L2, 5)
        warning = np.where((danger > 0) | (distance <= float(margin)), 255, 0).astype(np.uint8)
    else:
        warning = danger.copy()
    return poly, danger, warning


def overlap_ratio(mask: np.ndarray | None, box: tuple[int, int, int, int]) -> float:
    if mask is None:
        return 0.0
    h, w = mask.shape[:2]
    x1, y1, x2, y2 = box
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(w, x2), min(h, y2)
    if x2 <= x1 or y2 <= y1:
        return 0.0
    roi = mask[y1:y2, x1:x2]
    return float(np.count_nonzero(roi)) / float(max(1, roi.size))


def point_zone(danger: np.ndarray | None, warning: np.ndarray | None, x: int, y: int) -> str:
    if danger is None or warning is None:
        return "unconfigured"
    h, w = danger.shape[:2]
    if not (0 <= x < w and 0 <= y < h):
        return "safe"
    if danger[y, x] > 0:
        return "danger"
    if warning[y, x] > 0:
        return "warning"
    return "safe"


def strongest_zone(a: str, b: str) -> str:
    rank = {"unknown": -1, "unconfigured": -1, "safe": 0, "warning": 1, "danger": 2}
    return a if rank.get(a, -1) >= rank.get(b, -1) else b


def _expanded_box(box: list[int] | tuple[int, int, int, int], shape, pad: int = 0) -> tuple[int, int, int, int]:
    h, w = shape[:2]
    x1, y1, x2, y2 = [int(v) for v in box]
    return max(0, x1-pad), max(0, y1-pad), min(w, x2+pad), min(h, y2+pad)


def skin_ratio_in_box(frame: np.ndarray, box: list[int] | tuple[int, int, int, int]) -> tuple[float, int]:
    """Return a conservative skin-like pixel ratio for a motion box.

    This is only a fallback when MediaPipe is unavailable or misses a moving hand.
    It never replaces YOLO person detection and it does not create alerts/events.
    """
    x1, y1, x2, y2 = _expanded_box(box, frame.shape, 0)
    if x2 <= x1 or y2 <= y1:
        return 0.0, 0
    roi = frame[y1:y2, x1:x2]
    if roi is None or roi.size == 0:
        return 0.0, 0
    try:
        ycrcb = cv2.cvtColor(roi, cv2.COLOR_BGR2YCrCb)
        y, cr, cb = cv2.split(ycrcb)
        # Wide, illumination-tolerant skin range; motion gating keeps this from being
        # used as a generic static color detector.
        mask = ((cr >= 130) & (cr <= 180) & (cb >= 70) & (cb <= 140) & (y >= 35))
        pixels = int(np.count_nonzero(mask))
        ratio = float(pixels) / float(max(1, mask.size))
        return ratio, pixels
    except Exception:
        return 0.0, 0


def skin_motion_hand_fallback(frame: np.ndarray, motion_items: list[dict[str, Any]]):
    """Promote only skin-like moving intrusions to hand detections.

    Returns (hands, remaining_motion). This keeps non-skin tools/objects in the
    Object / Motion channel instead of mislabeling every moving blob as a hand.
    """
    hands: list[dict[str, Any]] = []
    remaining: list[dict[str, Any]] = []
    for item in motion_items:
        box = item.get("xyxy") if isinstance(item, dict) else None
        if not isinstance(box, (list, tuple)) or len(box) != 4:
            remaining.append(item); continue
        ratio, pixels = skin_ratio_in_box(frame, box)
        area = max(1, (int(box[2])-int(box[0])) * (int(box[3])-int(box[1])))
        # Conservative fallback: enough absolute skin pixels and enough of the moving box.
        if pixels >= max(120, int(area * 0.035)) and ratio >= 0.055:
            confidence = min(0.98, max(0.35, 0.30 + ratio * 2.6))
            hands.append({
                "xyxy": [int(v) for v in box],
                "zone": str(item.get("zone", "safe")),
                "label": "HAND",
                "confidence": round(float(confidence), 3),
                "skin_ratio": round(float(ratio), 4),
                "detection_mode": "skin_motion_fallback",
            })
        else:
            remaining.append(item)
    return hands, remaining


class LocalPreviewServer:
    """Serve the current webcam frame only on loopback.

    The browser reads this directly from the same Windows PC, so raw video does not
    make an AWS round trip. Only compact detection/status JSON is sent to NEXis.
    """

    def __init__(self, host: str = LOCAL_PREVIEW_HOST, port: int = LOCAL_PREVIEW_PORT):
        self.host = host
        self.port = int(port)
        self.lock = threading.Lock()
        self.jpg: bytes | None = None
        self.frame_ts = 0.0
        self.frame_seq = 0
        parent = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def _cors(self):
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Private-Network", "true")
                self.send_header("Cross-Origin-Resource-Policy", "cross-origin")
                self.send_header("Timing-Allow-Origin", "*")
                self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
                self.send_header("Pragma", "no-cache")

            def do_OPTIONS(self):
                self.send_response(204)
                self._cors()
                self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "*")
                self.send_header("Content-Length", "0")
                self.end_headers()

            def do_GET(self):
                path = self.path.split("?", 1)[0]
                if path == "/health":
                    with parent.lock:
                        body = json.dumps({"ok": True, "frame": bool(parent.jpg), "frame_seq": parent.frame_seq, "frame_age_s": max(0.0, time.time()-parent.frame_ts) if parent.frame_ts else None}).encode("utf-8")
                    self.send_response(200)
                    self._cors()
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                if path == "/frame.jpg":
                    with parent.lock:
                        raw = parent.jpg
                        ts = parent.frame_ts
                    if not raw or not ts or time.time() - ts > 3.0:
                        body = b"No fresh local frame"
                        self.send_response(404)
                        self._cors()
                        self.send_header("Content-Type", "text/plain; charset=utf-8")
                        self.send_header("Content-Length", str(len(body)))
                        self.end_headers()
                        self.wfile.write(body)
                        return
                    self.send_response(200)
                    self._cors()
                    self.send_header("Content-Type", "image/jpeg")
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    try:
                        self.wfile.write(raw)
                    except (BrokenPipeError, ConnectionResetError):
                        pass
                    return
                body = b"NEXis local camera preview"
                self.send_response(200)
                self._cors()
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, fmt, *args):
                return

        self.httpd = ThreadingHTTPServer((self.host, self.port), Handler)
        self.httpd.daemon_threads = True
        self.thread = threading.Thread(target=self.httpd.serve_forever, name="nexis-local-preview", daemon=True)
        self.thread.start()

    def update(self, frame: np.ndarray, seq: int) -> bool:
        ok, enc = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), LOCAL_PREVIEW_JPEG_QUALITY])
        if not ok:
            return False
        with self.lock:
            self.jpg = enc.tobytes()
            self.frame_ts = time.time()
            self.frame_seq = int(seq)
        return True

    def clear(self) -> None:
        with self.lock:
            self.jpg = None
            self.frame_ts = 0.0

    def close(self) -> None:
        try:
            self.httpd.shutdown()
            self.httpd.server_close()
        except Exception:
            pass
        self.thread.join(timeout=1.0)


class ServerLink:
    def __init__(self, server: str, token: str):
        self.server = str(server).strip().rstrip("/")
        if not self.server.startswith(("http://", "https://")):
            self.server = "http://" + self.server
        self.headers = {"X-Vision-Token": str(token).strip()}
        self.session = requests.Session()

    def get_config(self) -> dict[str, Any] | None:
        try:
            r = self.session.get(self.server + "/api/vision/edge/config", headers=self.headers, timeout=2.5)
            if r.status_code == 401:
                raise RuntimeError("edge token rejected by server")
            r.raise_for_status()
            data = r.json()
            return data if isinstance(data, dict) else None
        except Exception as exc:
            print(f"[SERVER] config fetch failed: {exc}")
            return None

    def send_status(self, payload: dict[str, Any]) -> bool:
        try:
            r = self.session.post(self.server + "/api/vision/edge/status", headers=self.headers, json=payload, timeout=2.5)
            r.raise_for_status()
            return True
        except Exception as exc:
            print(f"[SERVER] status upload failed: {exc}")
            return False

    def send_frame(self, jpg: bytes) -> bool:
        try:
            r = self.session.post(
                self.server + "/api/vision/edge/frame",
                headers=self.headers,
                files={"frame": ("vision.jpg", jpg, "image/jpeg")},
                timeout=4.0,
            )
            r.raise_for_status()
            return True
        except Exception as exc:
            print(f"[SERVER] frame upload failed: {exc}")
            return False


class NetworkBridge:
    """Keep HTTP latency/failures away from the camera analysis loop.

    Only the newest status/frame is retained, so a slow network cannot create an
    ever-growing upload backlog. Configuration is refreshed in the same worker.
    """

    def __init__(self, link: ServerLink, config_interval: float = 1.5):
        self.link = link
        self.config_interval = max(0.5, float(config_interval))
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.latest_status: dict[str, Any] | None = None
        self.latest_frame: bytes | None = None
        self.latest_config: dict[str, Any] | None = None
        self.config_generation = 0
        self.thread = threading.Thread(target=self._run, name="nexis-vision-network", daemon=True)
        self.thread.start()

    def publish_status(self, payload: dict[str, Any]) -> None:
        with self.lock:
            self.latest_status = dict(payload)

    def publish_frame(self, jpg: bytes) -> None:
        with self.lock:
            self.latest_frame = bytes(jpg)

    def config_snapshot(self) -> tuple[int, dict[str, Any] | None]:
        with self.lock:
            cfg = dict(self.latest_config) if isinstance(self.latest_config, dict) else None
            return self.config_generation, cfg

    def _run(self) -> None:
        next_config = 0.0
        while not self.stop_event.is_set():
            # Prioritize outgoing health/status over a potentially slow config GET so
            # a transient config-fetch delay does not make an otherwise healthy Edge
            # agent look offline. Latest-only queues still prevent upload backlog.
            with self.lock:
                status = self.latest_status
                frame = self.latest_frame
                self.latest_status = None
                self.latest_frame = None
            if status is not None:
                self.link.send_status(status)
            if frame is not None:
                self.link.send_frame(frame)
            now = time.monotonic()
            if now >= next_config:
                cfg = self.link.get_config()
                next_config = time.monotonic() + self.config_interval
                if cfg is not None:
                    with self.lock:
                        self.latest_config = dict(cfg)
                        self.config_generation += 1
            self.stop_event.wait(0.04)

    def close(self) -> None:
        self.stop_event.set()
        self.thread.join(timeout=1.0)




class CameraCaptureWorker:
    """Continuously capture/encode local preview independently from AI inference."""

    def __init__(self, camera: str, width: int, height: int, fps: int, preview: LocalPreviewServer):
        self.width, self.height, self.fps_target = int(width), int(height), int(fps)
        self.preview = preview
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.requested: str = str(camera)
        self.request_generation = 1
        self.handled_generation = 0
        self.frame: np.ndarray | None = None
        self.frame_seq = 0
        self.camera_index: int | None = None
        self.camera_ok = False
        self.switch_error = ""
        self.capture_fps = 0.0
        self.thread = threading.Thread(target=self._run, name="nexis-camera-capture", daemon=True)
        self.thread.start()

    def request_camera(self, index: int) -> None:
        with self.lock:
            self.requested = str(int(index))
            self.request_generation += 1
            self.switch_error = ""

    def request_camera_off(self) -> None:
        with self.lock:
            self.requested = "off"
            self.request_generation += 1
            self.switch_error = ""

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "camera_ok": bool(self.camera_ok),
                "camera_index": self.camera_index,
                "frame": None if self.frame is None else self.frame.copy(),
                "frame_seq": int(self.frame_seq),
                "fps": float(self.capture_fps),
                "camera_switch_error": str(self.switch_error),
            }

    def _run(self) -> None:
        cap = None
        failures = 0
        next_retry = 0.0
        fps_count = 0
        fps_ts = time.time()
        last_preview = 0.0
        try:
            while not self.stop_event.is_set():
                with self.lock:
                    req = self.requested
                    gen = self.request_generation
                if gen != self.handled_generation:
                    self.handled_generation = gen
                    if str(req).strip().lower() == "off":
                        old = cap
                        cap = None
                        if old is not None:
                            try: old.release()
                            except Exception: pass
                        self.preview.clear()
                        failures = 0
                        with self.lock:
                            self.camera_index = None
                            self.camera_ok = False
                            self.frame = None
                            self.switch_error = ""
                        self.stop_event.wait(0.02)
                        continue
                    # Clicking the camera that is already active is a no-op.
                    # tried to open the same Windows device a second time while the old
                    # handle still owned it, which could make Camera 0 appear broken.
                    try:
                        requested_idx = int(req) if str(req).lower() != "auto" else None
                    except Exception:
                        requested_idx = None
                    with self.lock:
                        current_idx = self.camera_index
                        current_ok = self.camera_ok
                    if cap is not None and current_ok and requested_idx is not None and current_idx == requested_idx:
                        with self.lock:
                            self.switch_error = ""
                        continue

                    previous_idx = current_idx if cap is not None and current_ok else None
                    old = cap
                    cap = None
                    if old is not None:
                        try: old.release()
                        except Exception: pass
                    self.preview.clear()
                    # Let Windows release the previous camera handle before reopening/switching.
                    time.sleep(0.12)
                    new_cap, new_idx, first = open_camera(req, self.width, self.height, self.fps_target)
                    if new_cap is not None and first is not None and new_idx is not None:
                        cap = new_cap
                        failures = 0
                        fps_count = 0
                        fps_ts = time.time()
                        with self.lock:
                            self.camera_index = int(new_idx)
                            self.camera_ok = True
                            self.switch_error = ""
                            self.frame = first.copy()
                            self.frame_seq += 1
                        self.preview.update(first, self.frame_seq)
                    else:
                        # If a switch fails, restore the previous camera instead of leaving
                        # the whole Vision page dark.
                        restored = False
                        if previous_idx is not None:
                            prev_cap, prev_idx, prev_first = open_camera(str(previous_idx), self.width, self.height, self.fps_target)
                            if prev_cap is not None and prev_first is not None and prev_idx is not None:
                                cap = prev_cap
                                restored = True
                                with self.lock:
                                    self.camera_index = int(prev_idx)
                                    self.camera_ok = True
                                    self.frame = prev_first.copy()
                                    self.frame_seq += 1
                                    self.switch_error = f"Camera {req} connection failed · previous camera restored"
                                self.preview.update(prev_first, self.frame_seq)
                        if not restored:
                            with self.lock:
                                self.camera_ok = False
                                self.camera_index = None
                                self.frame = None
                                self.switch_error = f"Unable to open Camera {req}" if req != "auto" else "Unable to open any available camera"
                        next_retry = time.time() + 1.0
                if cap is None:
                    if str(req).strip().lower() == "off":
                        self.stop_event.wait(0.05)
                        continue
                    if time.time() >= next_retry:
                        with self.lock:
                            self.request_generation += 1
                        next_retry = time.time() + 1.0
                    self.stop_event.wait(0.03)
                    continue
                ok, frame = cap.read()
                now = time.time()
                if not ok or frame is None:
                    failures += 1
                    if failures >= 30:
                        try: cap.release()
                        except Exception: pass
                        cap = None
                        self.preview.clear()
                        with self.lock:
                            self.camera_ok = False
                            self.frame = None
                            self.camera_index = None
                            self.switch_error = "Camera stream lost · reconnecting"
                            self.request_generation += 1
                        failures = 0
                    self.stop_event.wait(0.01)
                    continue
                failures = 0
                fps_count += 1
                if now - fps_ts >= 1.0:
                    with self.lock:
                        self.capture_fps = fps_count / max(0.001, now - fps_ts)
                    fps_count = 0
                    fps_ts = now
                with self.lock:
                    self.frame = frame.copy()
                    self.frame_seq += 1
                    seq = self.frame_seq
                    self.camera_ok = True
                if now - last_preview >= (1.0 / LOCAL_PREVIEW_MAX_FPS):
                    last_preview = now
                    self.preview.update(frame, seq)
        finally:
            if cap is not None:
                try: cap.release()
                except Exception: pass
            self.preview.clear()

    def close(self) -> None:
        self.stop_event.set()
        self.thread.join(timeout=2.0)


class VisionAnalyzer:
    def __init__(self, model: Any | None, hand_detector: Any | None = None):
        self.model = model
        self.hand_detector = hand_detector
        self.last_boxes: list[dict[str, Any]] = []
        self.last_person_zone = "unknown" if model is None else "safe"
        self.last_person_error = "YOLO unavailable" if model is None else ""
        self.person_detector_ok = model is not None
        self.person_has_run = False
        self.hand_detector_ok = hand_detector is not None
        self.last_hands: list[dict[str, Any]] = []
        self.last_hand_zone = "unknown" if hand_detector is None else "safe"
        self.last_hand_error = "MediaPipe unavailable" if hand_detector is None else ""
        self.hand_has_run = False
        self.frame_index = 0

        self.motion_detector_ok = True
        self.motion_detector_error = ""
        self.motion_frame_count = 0
        self.motion_hit_history: deque[bool] = deque(maxlen=MOTION_CONFIRM_WINDOW)
        self.last_motion_intrusions: list[dict[str, Any]] = []
        self.last_motion_zone = "safe"
        self.bg_subtractor = cv2.createBackgroundSubtractorMOG2(
            history=MOTION_BG_HISTORY,
            varThreshold=MOTION_BG_VAR_THRESHOLD,
            detectShadows=False,
        )

        self.led_frame_count = 0
        self.led_times: deque[float] = deque(maxlen=180)
        self.led_values: deque[float] = deque(maxlen=180)
        self.led_green_ratio_values: deque[float] = deque(maxlen=180)
        self.led_event_times: deque[float] = deque(maxlen=120)
        self.last_led_event_time = 0.0
        self.last_led_signal: float | None = None
        self.last_led_green_ratio: float | None = None
        self.prev_led_gray: np.ndarray | None = None
        self.led_high_state = False

        self.prev_rotor_gray: np.ndarray | None = None
        self.rotor_flags: deque[bool] = deque(maxlen=ROTOR_CONFIRM_WINDOW)
        self.rotor_state = False
        self.rotor_off_counter = 0
        self.last_rotor_motion_ts = 0.0
        self.rotor_noise_scores: deque[float] = deque(maxlen=ROTOR_NOISE_HISTORY)
        self.rotor_last_on_threshold = ROTOR_ON_SCORE_ABS
        self.rotor_last_off_threshold = ROTOR_OFF_SCORE_ABS

        self.mount_flags: dict[str, deque[bool]] = {k: deque(maxlen=SENSOR_MOUNT_WINDOW) for k in SENSOR_KEYS}
        # Baseline images are cached in memory. Reading/decoding up to three JPEGs on
        # every camera frame caused needless disk I/O and reduced Edge FPS.
        self.mount_baselines: dict[str, np.ndarray | None] = {k: None for k in SENSOR_KEYS}
        self.mount_baseline_revision = 0

    def reset_runtime(self):
        self.last_boxes = []
        self.last_person_zone = "unknown" if self.model is None else "safe"
        self.last_person_error = "YOLO unavailable" if self.model is None else ""
        self.person_detector_ok = self.model is not None
        self.person_has_run = False
        self.hand_detector_ok = self.hand_detector is not None
        self.last_hands = []
        self.last_hand_zone = "unknown" if self.hand_detector is None else "safe"
        self.last_hand_error = "MediaPipe unavailable" if self.hand_detector is None else ""
        self.hand_has_run = False
        self.motion_detector_ok = True
        self.motion_detector_error = ""
        self.motion_frame_count = 0
        self.motion_hit_history.clear()
        self.last_motion_intrusions = []
        self.last_motion_zone = "safe"
        self.bg_subtractor = cv2.createBackgroundSubtractorMOG2(
            history=MOTION_BG_HISTORY,
            varThreshold=MOTION_BG_VAR_THRESHOLD,
            detectShadows=False,
        )
        self.led_frame_count = 0
        self.led_times.clear()
        self.led_values.clear()
        self.led_green_ratio_values.clear()
        self.led_event_times.clear()
        self.last_led_event_time = 0.0
        self.last_led_signal = None
        self.last_led_green_ratio = None
        self.prev_led_gray = None
        self.led_high_state = False
        self.prev_rotor_gray = None
        self.rotor_flags.clear()
        self.rotor_state = False
        self.rotor_off_counter = 0
        self.last_rotor_motion_ts = 0.0
        self.rotor_noise_scores.clear()
        self.reset_mount_votes()

    def reset_mount_votes(self):
        for q in self.mount_flags.values():
            q.clear()

    def clear_mount_baseline_cache(self):
        self.mount_baselines = {k: None for k in SENSOR_KEYS}
        self.mount_baseline_revision = 0
        self.reset_mount_votes()

    def load_mount_baselines(self, revision: int, force: bool = False) -> None:
        revision = int(revision or 0)
        if not force and revision > 0 and self.mount_baseline_revision == revision:
            return
        loaded: dict[str, np.ndarray | None] = {}
        for key in SENSOR_KEYS:
            bp = baseline_path(key)
            loaded[key] = cv2.imread(str(bp), cv2.IMREAD_COLOR) if bp.exists() else None
        self.mount_baselines = loaded
        self.mount_baseline_revision = revision if revision > 0 else 0
        self.reset_mount_votes()

    def mount_baselines_complete(self, config: dict[str, Any]) -> bool:
        rois = config.get("rois", {}) if isinstance(config, dict) else {}
        expected = [key for key in SENSOR_KEYS if rois.get(key)]
        return bool(expected) and all(self.mount_baselines.get(key) is not None for key in expected)

    def analyze_people(self, frame: np.ndarray, danger: np.ndarray | None, warning: np.ndarray | None, every_n: int, conf: float, zone_ready: bool):
        self.frame_index += 1
        if self.model is None:
            self.person_detector_ok = False
            return [], "unknown", False, self.last_person_error or "YOLO person detector unavailable"

        run_now = (not self.person_has_run) or self.frame_index % max(1, every_n) == 0
        if run_now:
            boxes: list[dict[str, Any]] = []
            try:
                res = self.model.predict(frame, verbose=False, conf=max(0.05, min(0.95, float(conf))), classes=[0], imgsz=640)
                if res:
                    for b in res[0].boxes:
                        xy = b.xyxy[0].detach().cpu().numpy().astype(int).tolist()
                        x1, y1, x2, y2 = xy
                        score = float(b.conf[0].detach().cpu().item())
                        if zone_ready:
                            foot = ((x1 + x2) // 2, max(0, min(frame.shape[0] - 1, y2 - 2)))
                            z = point_zone(danger, warning, foot[0], foot[1])
                            dr = overlap_ratio(danger, (x1, y1, x2, y2))
                            wr = overlap_ratio(warning, (x1, y1, x2, y2))
                            if dr >= 0.08:
                                z = "danger"
                            elif z != "danger" and wr >= 0.08:
                                z = "warning"
                        else:
                            z = "unconfigured"
                        boxes.append({"xyxy": [x1, y1, x2, y2], "confidence": score, "zone": z})
                self.last_boxes = boxes
                zone = "safe" if zone_ready else "unconfigured"
                for b in boxes:
                    zone = strongest_zone(zone, str(b.get("zone", zone)))
                self.last_person_zone = zone
                self.last_person_error = ""
                self.person_detector_ok = True
                self.person_has_run = True
            except Exception as exc:
                self.last_person_error = str(exc)[:240]
                self.person_detector_ok = False
                self.person_has_run = True
                self.last_boxes = []
                self.last_person_zone = "unknown"
                return [], "unknown", False, self.last_person_error

        if not self.person_detector_ok:
            return self.last_boxes, "unknown", False, self.last_person_error or "YOLO person detector unavailable"
        return self.last_boxes, self.last_person_zone, True, ""

    def analyze_hands(self, frame: np.ndarray, danger: np.ndarray | None, warning: np.ndarray | None, every_n: int, zone_ready: bool):
        if self.hand_detector is None:
            self.hand_detector_ok = False
            return [], "unknown", False, self.last_hand_error or "MediaPipe hand detector unavailable"
        run_now = (not self.hand_has_run) or self.frame_index % max(1, int(every_n)) == 0
        if run_now:
            hands: list[dict[str, Any]] = []
            try:
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                result = self.hand_detector.process(rgb)
                landmarks_sets = list(result.multi_hand_landmarks or [])
                handed = list(result.multi_handedness or [])
                h, w = frame.shape[:2]
                for i, lmset in enumerate(landmarks_sets):
                    pts=[]
                    zone = "unconfigured" if not zone_ready else "safe"
                    for lm in lmset.landmark:
                        x=max(0,min(w-1,int(lm.x*w))); y=max(0,min(h-1,int(lm.y*h))); pts.append((x,y))
                        if zone_ready:
                            zone=strongest_zone(zone, point_zone(danger, warning, x, y))
                    if not pts:
                        continue
                    xs=[q[0] for q in pts]; ys=[q[1] for q in pts]
                    pad=max(4,int(0.02*max(w,h)))
                    x1=max(0,min(xs)-pad); y1=max(0,min(ys)-pad); x2=min(w-1,max(xs)+pad); y2=min(h-1,max(ys)+pad)
                    label="HAND"; score=1.0
                    if i < len(handed) and getattr(handed[i], "classification", None):
                        c=handed[i].classification[0]; label=str(getattr(c,"label","HAND") or "HAND").upper(); score=float(getattr(c,"score",1.0) or 1.0)
                    hands.append({"xyxy":[x1,y1,x2,y2],"zone":zone,"label":label,"confidence":score})
                overall = "safe" if zone_ready else "unconfigured"
                for item in hands:
                    overall=strongest_zone(overall,str(item.get("zone",overall)))
                self.last_hands=hands; self.last_hand_zone=overall; self.last_hand_error=""; self.hand_detector_ok=True; self.hand_has_run=True
            except Exception as exc:
                self.last_hand_error=str(exc)[:240]; self.hand_detector_ok=False; self.hand_has_run=True; self.last_hands=[]; self.last_hand_zone="unknown"
                return [], "unknown", False, self.last_hand_error
        if not self.hand_detector_ok:
            return self.last_hands, "unknown", False, self.last_hand_error or "MediaPipe hand detector unavailable"
        return self.last_hands, self.last_hand_zone, True, ""

    def analyze_motion_intrusions(
        self,
        frame: np.ndarray,
        danger: np.ndarray | None,
        warning: np.ndarray | None,
        rois: dict[str, Any],
        ignore_boxes: list[dict[str, Any]],
        zone_ready: bool,
    ):
        """Detect non-person/non-hand moving intrusions near the configured hazard zone.

        Known Vision ROIs and already-detected person/hand boxes are masked out to
        reduce duplicate detections.
        """
        try:
            fg = self.bg_subtractor.apply(frame, learningRate=0.006)
            self.motion_frame_count += 1
            if fg is None or fg.size == 0:
                raise RuntimeError("background subtractor returned no mask")

            _, fg = cv2.threshold(fg, 200, 255, cv2.THRESH_BINARY)
            fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
            fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
            fg = cv2.dilate(fg, np.ones((5, 5), np.uint8), iterations=1)

            # Known machine/sensor ROIs already have dedicated detectors. Mask them from the
            # generic motion channel so rotor motion or a blinking LED does not become an
            # "object intrusion" by itself.
            for key in ROI_LABELS:
                rect = pixel_roi(rois.get(key) if isinstance(rois, dict) else None, frame.shape)
                if not rect:
                    continue
                x, y, rw, rh = rect
                pad = MOTION_EXCLUDE_PADDING_PX * (3 if key == "rotor" else 1)
                x1, y1 = max(0, x-pad), max(0, y-pad)
                x2, y2 = min(frame.shape[1], x+rw+pad), min(frame.shape[0], y+rh+pad)
                fg[y1:y2, x1:x2] = 0

            # Person/hand detections already have dedicated boxes. Remove those regions from
            # the generic motion mask so the dashboard does not draw duplicate boxes.
            for item in ignore_boxes:
                box = item.get("xyxy") if isinstance(item, dict) else None
                if not isinstance(box, (list, tuple)) or len(box) != 4:
                    continue
                x1, y1, x2, y2 = _expanded_box(box, frame.shape, 10)
                if x2 > x1 and y2 > y1:
                    fg[y1:y2, x1:x2] = 0

            if not zone_ready or warning is None or danger is None:
                self.last_motion_intrusions = []
                self.last_motion_zone = "unconfigured"
                self.motion_detector_ok = True
                self.motion_detector_error = ""
                return [], "unconfigured", True, "", max(0, MOTION_WARMUP_FRAMES-self.motion_frame_count)

            # Only movement in the warning/danger envelope is relevant to intrusion safety.
            fg = cv2.bitwise_and(fg, warning)
            warmup_remaining = max(0, MOTION_WARMUP_FRAMES - self.motion_frame_count)
            if warmup_remaining > 0:
                self.motion_hit_history.append(False)
                self.last_motion_intrusions = []
                self.last_motion_zone = "safe"
                self.motion_detector_ok = True
                self.motion_detector_error = ""
                return [], "safe", True, "", warmup_remaining

            contours, _ = cv2.findContours(fg, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            frame_area = float(max(1, frame.shape[0] * frame.shape[1]))
            min_area = max(MOTION_MIN_AREA_PX, frame_area * MOTION_MIN_AREA_FRAC)
            max_area = frame_area * MOTION_MAX_AREA_FRAC
            items: list[dict[str, Any]] = []
            for cnt in contours:
                area = float(cv2.contourArea(cnt))
                if area < min_area or area > max_area:
                    continue
                x, y, rw, rh = cv2.boundingRect(cnt)
                if rw < 4 or rh < 4:
                    continue
                box = (x, y, x+rw, y+rh)
                dr = overlap_ratio(danger, box)
                wr = overlap_ratio(warning, box)
                z = point_zone(danger, warning, x + rw//2, min(frame.shape[0]-1, y+rh-1))
                if dr >= MOTION_ZONE_OVERLAP:
                    z = "danger"
                elif z != "danger" and wr >= MOTION_ZONE_OVERLAP:
                    z = "warning"
                if z not in ("warning", "danger"):
                    continue
                roi = fg[y:y+rh, x:x+rw]
                motion_ratio = float(np.count_nonzero(roi)) / float(max(1, roi.size))
                items.append({
                    "xyxy": [int(x), int(y), int(x+rw), int(y+rh)],
                    "zone": z,
                    "area_px": round(area, 1),
                    "motion_ratio": round(motion_ratio, 4),
                    "danger_overlap": round(dr, 4),
                    "warning_overlap": round(wr, 4),
                    "kind": "object_motion",
                })

            items.sort(key=lambda x: float(x.get("area_px", 0.0)), reverse=True)
            items = items[:8]
            hit = bool(items)
            self.motion_hit_history.append(hit)
            confirmed = hit and sum(1 for x in self.motion_hit_history if x) >= MOTION_CONFIRM_MIN_HITS
            if not confirmed:
                items = []

            zone = "safe"
            for item in items:
                zone = strongest_zone(zone, str(item.get("zone", "safe")))

            self.last_motion_intrusions = [dict(x) for x in items]
            self.last_motion_zone = zone
            self.motion_detector_ok = True
            self.motion_detector_error = ""
            return items, zone, True, "", 0
        except Exception as exc:
            self.motion_detector_ok = False
            self.motion_detector_error = str(exc)[:240]
            self.last_motion_intrusions = []
            self.last_motion_zone = "unknown"
            return [], "unknown", False, self.motion_detector_error, 0

    def analyze_led(self, frame: np.ndarray, rect, ts: float):
        roi_bgr = crop(frame, rect)
        if roi_bgr is None or roi_bgr.size <= 0:
            return {"configured": False, "blink_detected": False, "signal": 0.0, "blink_rate_hz": 0.0, "evidence": 0.0, "brightness_delta": 0.0}

        # Hall-module LEDs are not guaranteed to be green. Use a color-agnostic
        # brightness/contrast channel as the primary blink signal, with green-excess
        # retained as extra evidence when the board LED happens to be green.
        hsv = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2HSV)
        v_img = cv2.GaussianBlur(hsv[:, :, 2], (3, 3), 0)
        vp99 = float(np.percentile(v_img, 99)); vp95 = float(np.percentile(v_img, 95)); vp50 = float(np.percentile(v_img, 50))
        signal = max(0.0, 0.70 * (vp99 - vp50) + 0.30 * (vp95 - vp50))
        bright_cut = min(250.0, max(90.0, vp50 + 28.0))
        bright_ratio = float(np.mean(v_img >= bright_cut))

        try:
            roi_f = roi_bgr.astype(np.float32)
            b, g, r = cv2.split(roi_f)
            green_excess_f = g - 0.55 * r - 0.45 * b
            green_excess = np.clip(green_excess_f, 0, 255).astype(np.uint8)
            ghsv = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2HSV)
            mask_hsv = cv2.inRange(ghsv, np.array([LED_GREEN_H_MIN, LED_GREEN_S_MIN, LED_GREEN_V_MIN], dtype=np.uint8), np.array([LED_GREEN_H_MAX, 255, 255], dtype=np.uint8))
            dominance = ((g >= r + LED_GREEN_DOMINANCE_MARGIN) & (g >= b + LED_GREEN_DOMINANCE_MARGIN) & (green_excess_f >= LED_GREEN_DOMINANCE_MARGIN))
            green_mask = cv2.bitwise_and(mask_hsv, dominance.astype(np.uint8) * 255)
            if green_mask.size >= 25:
                green_mask = cv2.medianBlur(green_mask, 3)
            green_pixels = int(cv2.countNonZero(green_mask))
            total_pixels = max(int(green_mask.shape[0] * green_mask.shape[1]), 1)
            green_ratio = float(green_pixels / total_pixels)
        except Exception:
            green_pixels = 0; green_ratio = 0.0

        self.led_frame_count += 1
        ratio_hist = np.asarray(self.led_green_ratio_values, dtype=float)
        sig_hist = np.asarray(self.led_values, dtype=float)
        if len(ratio_hist) >= 8:
            base_ratio = float(np.percentile(ratio_hist, 30))
            ratio_noise = float(np.median(np.abs(ratio_hist - np.median(ratio_hist))) * 1.4826)
        elif len(ratio_hist) > 0:
            base_ratio = float(np.median(ratio_hist)); ratio_noise = 0.0005
        else:
            base_ratio = float(green_ratio); ratio_noise = 0.0005
        if len(sig_hist) >= 8:
            base_signal = float(np.percentile(sig_hist, 30))
            sig_noise = float(np.median(np.abs(sig_hist - np.median(sig_hist))) * 1.4826)
        elif len(sig_hist) > 0:
            base_signal = float(np.median(sig_hist)); sig_noise = 1.0
        else:
            base_signal = float(signal); sig_noise = 1.0

        high_th = max(LED_HIGH_RATIO_ABS_MIN, base_ratio + max(LED_HIGH_RATIO_BASE_ADD, LED_HIGH_RATIO_NOISE_GAIN * max(ratio_noise, 0.00025)))
        low_th = base_ratio + max(LED_LOW_RATIO_BASE_ADD, LED_LOW_RATIO_NOISE_GAIN * max(ratio_noise, 0.00025))
        sig_rise_th = max(LED_SIGNAL_RISE_MIN, 3.0 * max(sig_noise, 0.7))
        sig_high_th = base_signal + max(4.0, 4.0 * max(sig_noise, 0.7))
        sig_low_th = base_signal + max(1.2, 1.7 * max(sig_noise, 0.7))
        ratio_delta = float(green_ratio - self.last_led_green_ratio) if self.last_led_green_ratio is not None else 0.0
        signal_delta = float(signal - self.last_led_signal) if self.last_led_signal is not None else 0.0

        local_p95 = 0.0; local_ratio = 0.0
        if self.prev_led_gray is not None and self.prev_led_gray.shape == v_img.shape:
            cur = v_img.astype(np.float32); prev = self.prev_led_gray.astype(np.float32)
            shift = float(np.median(cur) - np.median(prev))
            cur_comp = np.clip(cur - shift, 0, 255).astype(np.uint8)
            diff_img = cv2.absdiff(cur_comp, self.prev_led_gray)
            local_p95 = float(np.percentile(diff_img, 95)); local_ratio = float(np.mean(diff_img >= LED_LOCAL_PIXEL_DELTA))
            self.prev_led_gray = cur_comp.copy()
        else:
            self.prev_led_gray = v_img.copy()

        color_high = bool(green_pixels >= LED_GREEN_MIN_PIXELS and green_ratio >= high_th)
        brightness_high = bool(signal >= sig_high_th and bright_ratio >= 0.001)
        high_now = color_high or brightness_high
        warmup = self.led_frame_count <= LED_WARMUP_FRAMES
        if warmup:
            self.led_high_state = high_now
            self._append_led(ts, signal, green_ratio)
            return {"configured": True, "blink_detected": False, "signal": signal, "brightness_signal": signal, "brightness_delta": 0.0, "bright_ratio": bright_ratio, "blink_rate_hz": 0.0, "evidence": 0.0, "green_ratio": green_ratio, "blink_events": 0}

        if self.led_high_state and green_ratio <= low_th and signal <= sig_low_th:
            self.led_high_state = False
        ratio_rise = ratio_delta >= LED_GREEN_RATIO_RISE_MIN
        signal_rise = signal_delta >= sig_rise_th and signal >= base_signal + sig_rise_th
        local_change = local_p95 >= LED_LOCAL_P95_MIN and LED_LOCAL_ACTIVE_RATIO_MIN <= local_ratio <= LED_LOCAL_ACTIVE_RATIO_MAX
        transition_event = bool((not self.led_high_state) and high_now and (ratio_rise or signal_rise or local_change))
        if transition_event and (ts - self.last_led_event_time) >= LED_MIN_EVENT_GAP_SEC:
            self.led_event_times.append(float(ts)); self.last_led_event_time = float(ts); self.led_high_state = True

        self._append_led(ts, signal, green_ratio)
        recent_events = [t for t in self.led_event_times if ts - t <= LED_EVENT_HOLD_SEC]
        while self.led_event_times and ts - self.led_event_times[0] > max(LED_EVENT_HOLD_SEC, LED_HISTORY_SECONDS) * 2:
            self.led_event_times.popleft()
        rate = 0.0
        if len(recent_events) >= 2:
            span = max(recent_events[-1] - recent_events[0], 1e-6); rate = float((len(recent_events) - 1) / span)
        evidence = max(green_ratio / max(high_th, 1e-9), signal / max(sig_high_th, 1e-9), max(0.0, signal_delta) / max(sig_rise_th, 1e-9), local_p95 / max(LED_LOCAL_P95_MIN, 1e-9), local_ratio / max(LED_LOCAL_ACTIVE_RATIO_MIN, 1e-9))
        return {
            "configured": True, "blink_detected": bool(len(recent_events) >= LED_MIN_BLINK_EVENTS),
            "signal": float(signal), "brightness_signal": float(signal), "brightness_delta": float(signal_delta), "bright_ratio": float(bright_ratio),
            "blink_rate_hz": rate, "evidence": float(evidence), "green_ratio": float(green_ratio), "blink_events": int(len(recent_events)),
            "detection_mode": "brightness+color"
        }

    def _append_led(self, ts: float, signal: float, green_ratio: float):
        self.led_times.append(float(ts))
        self.led_values.append(float(signal))
        self.led_green_ratio_values.append(float(green_ratio))
        self.last_led_signal = float(signal)
        self.last_led_green_ratio = float(green_ratio)
        while self.led_times and ts - self.led_times[0] > LED_HISTORY_SECONDS:
            self.led_times.popleft()
            self.led_values.popleft()
            self.led_green_ratio_values.popleft()

    def analyze_rotor(self, frame: np.ndarray, rect, now: float):
        roi = crop(frame, rect)
        if roi is None:
            self.prev_rotor_gray = None
            self.rotor_flags.clear()
            self.rotor_state = False
            return {"configured": False, "motion_detected": False, "motion_score": 0.0, "active_ratio": 0.0}
        gray = cv2.GaussianBlur(cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY), (5, 5), 0)
        h, w = gray.shape[:2]
        if max(h, w) > ROTOR_MAX_ROI_SIDE:
            scale = ROTOR_MAX_ROI_SIDE / float(max(h, w))
            gray = cv2.resize(gray, (max(16, int(w * scale)), max(16, int(h * scale))), interpolation=cv2.INTER_AREA)
        if self.prev_rotor_gray is None or self.prev_rotor_gray.shape != gray.shape:
            self.prev_rotor_gray = gray.copy()
            return {"configured": True, "motion_detected": self.rotor_state, "motion_score": 0.0, "active_ratio": 0.0}

        cur = gray.astype(np.float32)
        prev = self.prev_rotor_gray.astype(np.float32)
        global_shift = float(np.median(cur) - np.median(prev))
        cur_comp = np.clip(cur - global_shift, 0, 255).astype(np.uint8)
        diff = cv2.absdiff(cur_comp, self.prev_rotor_gray)
        diff_mean = float(np.mean(diff))
        diff_p95 = float(np.percentile(diff, 95))
        active_ratio = float(np.mean(diff >= ROTOR_PIXEL_DELTA_THRESHOLD))

        flow_mean = 0.0
        flow_p90 = 0.0
        try:
            flow = cv2.calcOpticalFlowFarneback(self.prev_rotor_gray, cur_comp, None, 0.5, 2, 15, 2, 5, 1.1, 0)
            mag, _ = cv2.cartToPolar(flow[..., 0], flow[..., 1])
            flow_mean = float(np.mean(mag))
            flow_p90 = float(np.percentile(mag, 90))
        except Exception:
            pass

        score = float(max(diff_mean * 2.5, diff_p95, active_ratio * 520.0, flow_mean * 16.0, flow_p90 * 5.5))
        if (not self.rotor_state) and score < max(ROTOR_ON_SCORE_ABS, self.rotor_last_on_threshold):
            self.rotor_noise_scores.append(score)
        if len(self.rotor_noise_scores) >= 12:
            arr = np.asarray(self.rotor_noise_scores, dtype=float)
            med = float(np.median(arr))
            mad = float(np.median(np.abs(arr - med)) * 1.4826)
            on_th = max(ROTOR_ON_SCORE_ABS, med + ROTOR_NOISE_ON_GAIN * max(mad, 0.12))
            off_th = max(ROTOR_OFF_SCORE_ABS, med + ROTOR_NOISE_OFF_GAIN * max(mad, 0.12))
        else:
            on_th, off_th = ROTOR_ON_SCORE_ABS, ROTOR_OFF_SCORE_ABS
        self.rotor_last_on_threshold = float(on_th)
        self.rotor_last_off_threshold = float(off_th)

        diff_cue = diff_mean >= ROTOR_MIN_DIFF_MEAN and diff_p95 >= ROTOR_MIN_DIFF_P95 and active_ratio >= ROTOR_MIN_ACTIVE_RATIO
        flow_cue = flow_mean >= ROTOR_MIN_FLOW_MEAN and flow_p90 >= ROTOR_MIN_FLOW_P90
        moving = bool(score >= on_th and (diff_cue or flow_cue))
        self.rotor_flags.append(moving)
        if moving:
            self.last_rotor_motion_ts = now
            self.rotor_off_counter = 0
        else:
            self.rotor_off_counter += 1
        if not self.rotor_state and sum(self.rotor_flags) >= ROTOR_ON_MIN_COUNT:
            self.rotor_state = True
            self.last_rotor_motion_ts = now
        if self.rotor_state:
            if (now - self.last_rotor_motion_ts) > ROTOR_HOLD_SECONDS and score < off_th and self.rotor_off_counter >= ROTOR_OFF_CONFIRM_FRAMES:
                self.rotor_state = False
                self.rotor_flags.clear()
        self.prev_rotor_gray = cur_comp.copy()
        return {
            "configured": True,
            "motion_detected": bool(self.rotor_state),
            "motion_score": score,
            "active_ratio": active_ratio,
            "diff_mean": diff_mean,
            "flow_mean": flow_mean,
        }

    def analyze_sensor_mount(self, frame: np.ndarray, rect, key: str, baseline_ready: bool):
        roi = crop(frame, rect)
        if rect is None:
            self.mount_flags[key].clear()
            return {"status": "not_configured", "diff": 0.0, "votes": 0}
        if roi is None:
            self.mount_flags[key].append(True)
            return {"status": "missing", "diff": 999.0, "votes": int(sum(self.mount_flags[key]))}
        if not baseline_ready:
            self.mount_flags[key].clear()
            return {"status": "uncalibrated", "diff": 0.0, "votes": 0}
        ref = self.mount_baselines.get(key)
        if ref is None:
            self.mount_flags[key].clear()
            return {"status": "uncalibrated", "diff": 0.0, "votes": 0}
        if ref.shape[:2] != roi.shape[:2]:
            ref = cv2.resize(ref, (roi.shape[1], roi.shape[0]), interpolation=cv2.INTER_AREA)
        # Keep the sensor-mount metric conservative:
        # direct grayscale mean absolute difference + multi-frame voting.
        g1 = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        g2 = cv2.cvtColor(ref, cv2.COLOR_BGR2GRAY)
        diff = float(np.mean(cv2.absdiff(g1, g2)))
        changed_now = diff >= SENSOR_MOUNT_DIFF_THRESHOLD
        q = self.mount_flags[key]
        q.append(changed_now)
        votes = int(sum(q))
        if votes >= SENSOR_MOUNT_WARNING_FRAMES:
            status = "changed"
        elif changed_now or votes > 0:
            status = "checking"
        else:
            status = "ok"
        return {"status": status, "diff": diff, "votes": votes, "window": len(q), "threshold": SENSOR_MOUNT_DIFF_THRESHOLD}


def capture_sensor_baselines(frame: np.ndarray, config: dict[str, Any]) -> tuple[int, int]:
    rois = config.get("rois", {}) if isinstance(config, dict) else {}
    count = 0
    expected = 0
    for key in SENSOR_KEYS:
        if not rois.get(key):
            try:
                baseline_path(key).unlink(missing_ok=True)
            except Exception:
                pass
            continue
        expected += 1
        rect = pixel_roi(rois.get(key), frame.shape)
        roi = crop(frame, rect)
        if roi is None:
            continue
        if cv2.imwrite(str(baseline_path(key)), roi):
            count += 1
    return count, expected


def draw_overlay(frame: np.ndarray, config: dict[str, Any], poly, danger, warning, people, person_zone, led, rotor, sensors, detector_ok: bool):
    out = frame.copy()
    if warning is not None:
        contours, _ = cv2.findContours(warning, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(out, contours, -1, COLORS["warning"], 2)
    if poly is not None:
        overlay = out.copy()
        cv2.fillPoly(overlay, [poly], COLORS["danger"])
        out = cv2.addWeighted(overlay, 0.12, out, 0.88, 0)
        cv2.polylines(out, [poly], True, COLORS["danger"], 3, cv2.LINE_AA)
        cv2.putText(out, "HAZARD ZONE", tuple(poly[0]), cv2.FONT_HERSHEY_SIMPLEX, 0.65, COLORS["danger"], 2, cv2.LINE_AA)
    rois = config.get("rois", {}) if isinstance(config, dict) else {}
    for key, norm in rois.items():
        rect = pixel_roi(norm, frame.shape)
        if not rect:
            continue
        x, y, w, h = rect
        color = COLORS.get(key, (220, 220, 220))
        cv2.rectangle(out, (x, y), (x + w, y + h), color, 2)
        label = ROI_LABELS.get(key, key.upper())
        if key in sensors:
            label += f" {sensors[key].get('status','').upper()}"
        elif key == "hall_led":
            label += " BLINK" if led.get("blink_detected") else " NO-BLINK"
        elif key == "rotor":
            label += " MOVING" if rotor.get("motion_detected") else " STILL"
        cv2.putText(out, label, (x, max(18, y - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.50, color, 2, cv2.LINE_AA)
    for item in people:
        x1, y1, x2, y2 = item["xyxy"]
        z = item.get("zone", "safe")
        color = COLORS.get(z, COLORS["safe"])
        cv2.rectangle(out, (x1, y1), (x2, y2), color, 3)
        cv2.putText(out, f"PERSON {str(z).upper()} {item.get('confidence',0):.2f}", (x1, max(22, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.58, color, 2, cv2.LINE_AA)
    zone_color = COLORS.get(person_zone, COLORS["unknown"])
    cv2.rectangle(out, (10, 10), (500, 74), (10, 15, 20), -1)
    detector_text = "OK" if detector_ok else "UNAVAILABLE"
    cv2.putText(out, f"NEXis Vision | PERSON: {person_zone.upper()} ({len(people)})", (22, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.65, zone_color, 2, cv2.LINE_AA)
    cv2.putText(out, f"YOLO: {detector_text} | LED: {'BLINK' if led.get('blink_detected') else 'NO'} | ROTOR: {'MOVING' if rotor.get('motion_detected') else 'STILL'}", (22, 62), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (210, 220, 230), 1, cv2.LINE_AA)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="NEXis Windows webcam vision edge agent")
    ap.add_argument("--server", required=True, help="NEXis server URL")
    ap.add_argument("--token", required=True, help="Vision Edge token")
    ap.add_argument("--camera", default="auto", help="camera index or auto")
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=720)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--model", default=str(APP_DIR / "yolo11n.pt"))
    ap.add_argument("--confidence", type=float, default=0.40)
    ap.add_argument("--yolo-every", type=int, default=6)
    ap.add_argument("--hand-every", type=int, default=2)
    ap.add_argument("--preview-port", type=int, default=LOCAL_PREVIEW_PORT)
    ap.add_argument("--show", action="store_true")
    args = ap.parse_args()
    args.server = str(args.server).strip(); args.token = str(args.token).strip()
    if not args.server or not args.token:
        print("[ERROR] Both --server and --token must be non-empty."); return 2
    if args.width < 16 or args.height < 16 or args.fps < 1:
        print("[ERROR] --width/--height must be >=16 and --fps must be >=1."); return 2
    if not (0.05 <= float(args.confidence) <= 0.95) or int(args.yolo_every) < 1 or int(args.hand_every) < 1:
        print("[ERROR] Invalid detector parameters."); return 2

    link = ServerLink(args.server, args.token)
    if link.server.lower().startswith("http://"):
        print("[SECURITY] Edge status and low-rate preview JPEG use plain HTTP. AI inference still runs locally on this PC.")
    bridge = NetworkBridge(link)
    try:
        preview = LocalPreviewServer(port=int(args.preview_port))
    except Exception as exc:
        bridge.close(); print(f"[ERROR] Local preview server failed: {exc}"); return 3
    initial_cameras = discover_cameras(args.width,args.height,args.fps,9)
    bridge.publish_status({"source_time":time.strftime("%Y-%m-%dT%H:%M:%S"),"vision_protocol":EDGE_PROTOCOL_VERSION,"camera_ok":False,"camera_index":None,"available_cameras":initial_cameras,"fps":0.0,"frame_seq":0,"local_preview":True,"local_preview_port":int(args.preview_port),"local_preview_ready":False,"person_detector_ok":False,"person_zone":"unknown","person_count":0,"people":[],"hand_detector_ok":False,"hand_detection_mode":"unavailable","hand_zone":"unknown","hand_count":0,"hands":[],"motion_detector_ok":True,"motion_detector_error":"","motion_warmup_remaining":MOTION_WARMUP_FRAMES,"object_intrusion_count":0,"object_intrusion_zone":"unknown","unknown_motion_zone":"unknown","motion_intrusions":[],"safety_zone":"unknown"})

    model = None
    if UltralyticsYOLO is not None:
        try:
            model = UltralyticsYOLO(args.model); print("[YOLO] ready (COCO person class only)")
        except Exception as exc: print(f"[YOLO] unavailable: {exc}")
    else: print(f"[YOLO] unavailable: {ULTRALYTICS_IMPORT_ERROR}")
    hand_detector = None
    if mp is not None:
        try:
            solutions = getattr(mp, "solutions", None)
            hands_api = getattr(solutions, "hands", None) if solutions is not None else None
            if hands_api is None:
                raise RuntimeError("installed MediaPipe build has no legacy solutions.hands API")
            hand_detector = hands_api.Hands(static_image_mode=False,max_num_hands=2,model_complexity=0,min_detection_confidence=0.45,min_tracking_confidence=0.45)
            print("[MEDIAPIPE] hand detector ready")
        except Exception as exc:
            print(f"[MEDIAPIPE] unavailable: {exc}; skin-motion fallback remains active")
    else:
        print(f"[MEDIAPIPE] unavailable: {MEDIAPIPE_IMPORT_ERROR}; skin-motion fallback remains active")

    analyzer = VisionAnalyzer(model, hand_detector)
    capture = CameraCaptureWorker(args.camera,args.width,args.height,args.fps,preview)
    state = load_state(); config: dict[str,Any]={}; configured=False
    last_config_generation=-1; last_status_send=0.0; last_frame_send=0.0; last_analyzed_seq=-1; last_camera_index=None; last_baseline_attempt=0.0
    zone_cache_key=None; poly=danger=warning=None
    desired_camera_index=None; camera_selection_revision=0; handled_camera_selection_revision=0
    camera_refresh_revision=0; handled_camera_refresh_revision=0
    available_cameras: list[dict[str,Any]]=[dict(x) for x in initial_cameras]; camera_list_lock=threading.Lock()

    def remember_camera(index:int):
        if _camera_index_is_blocked(index):
            return
        with camera_list_lock:
            if all(int(x.get("index",-1))!=int(index) for x in available_cameras):
                available_cameras.append({"index":int(index),"label":f"Camera {int(index)}"}); available_cameras.sort(key=lambda x:int(x.get("index",999)))
    def camera_list_snapshot():
        with camera_list_lock: return [dict(x) for x in available_cameras]
    def refresh_camera_list():
        # Camera enumeration happens only at startup and on an explicit dashboard request.
        # Friendly-name enumeration blocks linked/mobile cameras before any video stream opens.
        found=discover_cameras(args.width,args.height,args.fps,9)
        snap=capture.snapshot(); active=snap.get("camera_index")
        if active is not None and not _camera_index_is_blocked(int(active)) and all(int(x.get("index",-1))!=int(active) for x in found):
            found.append({"index":int(active),"label":f"Camera {int(active)}"})
            found.sort(key=lambda x:int(x.get("index",999)))
        with camera_list_lock:
            available_cameras[:]=[dict(x) for x in found]
        print(f"[CAMERA] camera list refreshed: {[x.get('label') for x in found]}")

    def apply_remote(remote:dict[str,Any]|None):
        nonlocal configured,config,zone_cache_key,desired_camera_index,camera_selection_revision,camera_refresh_revision
        if remote is None:return
        sel=remote.get("camera_selection",{}) if isinstance(remote,dict) else {}
        if isinstance(sel,dict):
            try:rev=int(sel.get("revision",0) or 0)
            except Exception:rev=0
            try:idx=None if sel.get("requested_index") is None else int(sel.get("requested_index"))
            except Exception:idx=None
            if idx is not None and not 0<=idx<=15: idx=None
            if idx is not None and not _camera_index_is_selectable(idx):
                print(f"[CAMERA] ignored blocked/unlisted Camera {idx}")
                idx=None
            if rev>=camera_selection_revision: camera_selection_revision=rev; desired_camera_index=idx
            try:refresh_rev=int(sel.get("refresh_revision",0) or 0)
            except Exception:refresh_rev=0
            if refresh_rev>=camera_refresh_revision: camera_refresh_revision=refresh_rev
        prev_conf=configured; prev_rev=int(config.get("revision",0) or 0) if configured else 0
        reset_rev=int(remote.get("reset_revision",0) or 0)
        if reset_rev>int(state.get("reset_revision",0) or 0):
            clear_baselines(); state["reset_revision"]=reset_rev; state["baseline_revision"]=0; state["config_revision"]=0; save_state(state); analyzer.clear_mount_baseline_cache(); analyzer.reset_runtime()
        configured=bool(remote.get("configured")); config=remote if configured else {}
        cfg_rev=int(config.get("revision",0) or 0) if configured else 0
        if configured and cfg_rev!=int(state.get("config_revision",0) or 0):
            clear_baselines(); state["config_revision"]=cfg_rev; state["baseline_revision"]=0; save_state(state); analyzer.clear_mount_baseline_cache(); analyzer.reset_runtime()
        if configured!=prev_conf or cfg_rev!=prev_rev: zone_cache_key=None

    try:
        while True:
            now=time.time(); gen,remote=bridge.config_snapshot()
            if gen!=last_config_generation: last_config_generation=gen; apply_remote(remote)
            if camera_selection_revision>handled_camera_selection_revision:
                handled_camera_selection_revision=camera_selection_revision
                if desired_camera_index is None and camera_selection_revision>0: capture.request_camera_off()
                elif desired_camera_index is not None: capture.request_camera(desired_camera_index)
            if camera_refresh_revision>handled_camera_refresh_revision:
                handled_camera_refresh_revision=camera_refresh_revision
                refresh_camera_list()

            camera_user_off=bool(camera_selection_revision>0 and desired_camera_index is None)
            snap=capture.snapshot(); cam_ok=bool(snap["camera_ok"]); cam_index=snap["camera_index"]; frame=snap["frame"]; frame_seq=int(snap["frame_seq"]); fps_value=float(snap["fps"])
            if cam_index is not None: remember_camera(int(cam_index))
            if cam_index!=last_camera_index:
                last_camera_index=cam_index; analyzer.reset_runtime(); zone_cache_key=None; last_analyzed_seq=-1

            baseline_revision=int(config.get("baseline_revision",0) or 0) if configured else 0
            state_match=bool(baseline_revision>0 and int(state.get("baseline_revision",0) or 0)==baseline_revision)
            if state_match: analyzer.load_mount_baselines(baseline_revision)
            baseline_ready=bool(state_match and analyzer.mount_baselines_complete(config))

            if not cam_ok or frame is None:
                if now-last_status_send>=0.5:
                    last_status_send=now
                    bridge.publish_status({"source_time":time.strftime("%Y-%m-%dT%H:%M:%S",time.localtime(now)),"vision_protocol":EDGE_PROTOCOL_VERSION,"camera_ok":False,"camera_user_off":camera_user_off,"camera_index":cam_index,"available_cameras":camera_list_snapshot(),"camera_selection_revision":camera_selection_revision,"camera_refresh_revision":camera_refresh_revision,"camera_requested_index":desired_camera_index,"camera_switch_error":snap.get("camera_switch_error","") ,"fps":fps_value,"frame_seq":frame_seq,"configured":bool(configured),"config_revision":int(config.get("revision",0) or 0) if configured else 0,"frame_config_compatible":None,"baseline_revision":int(state.get("baseline_revision",0) or 0),"baseline_requested_revision":baseline_revision,"baseline_ready":baseline_ready,"person_detector_ok":False,"person_detector_error":"Camera unavailable","person_count":0,"person_zone":"unknown","people":[],"hand_detector_ok":False,"hand_detector_error":"Camera unavailable","hand_detection_mode":"unavailable","hand_count":0,"hand_zone":"unknown","hands":[],"motion_detector_ok":True,"motion_detector_error":"","motion_warmup_remaining":MOTION_WARMUP_FRAMES,"object_intrusion_count":0,"object_intrusion_zone":"unknown","unknown_motion_zone":"unknown","motion_intrusions":[],"safety_zone":"unknown","local_preview":True,"local_preview_port":int(args.preview_port),"local_preview_ready":False,"hall_led":{"configured":False,"blink_detected":False,"blink_rate_hz":0.0,"evidence":0.0},"rotor":{"configured":False,"motion_detected":False,"motion_score":0.0,"active_ratio":0.0},"sensors":{k:{"status":"camera_offline","diff":0.0,"votes":0} for k in SENSOR_KEYS}})
                time.sleep(0.02); continue

            frame_compatible=config_frame_compatible(config,frame.shape,cam_index) if configured else True
            rois=config.get("rois",{}) if configured else {}
            pending=bool(configured and config.get("baseline_required",True) and baseline_revision>0)
            local_baseline_ready=bool(state_match and analyzer.mount_baselines_complete(config))
            if configured and frame_compatible and pending and not local_baseline_ready and now-last_baseline_attempt>=0.5:
                last_baseline_attempt=now; count,expected=capture_sensor_baselines(frame,config)
                if count==expected and expected>0:
                    state["baseline_revision"]=baseline_revision; save_state(state); analyzer.load_mount_baselines(baseline_revision,force=True); state_match=True; local_baseline_ready=analyzer.mount_baselines_complete(config)
            baseline_ready=bool(frame_compatible and state_match and local_baseline_ready)

            if configured:
                poly_sig=tuple(tuple(round(float(v),7) for v in pt) for pt in config.get("hazard_polygon",[]) if isinstance(pt,(list,tuple)) and len(pt)==2)
                key=(int(config.get("revision",0) or 0),int(config.get("warning_margin_px",90) or 0),int(config.get("setup_frame_width",0) or 0),int(config.get("setup_frame_height",0) or 0),poly_sig,int(frame.shape[0]),int(frame.shape[1]))
                if key!=zone_cache_key: poly,danger,warning=build_zone_masks(config,frame.shape); zone_cache_key=key
            else: poly=danger=warning=None; zone_cache_key=None

            # Analyze only when a new captured frame arrives. Capture/preview continues in its own thread.
            if frame_seq==last_analyzed_seq:
                time.sleep(0.005); continue
            last_analyzed_seq=frame_seq
            ready=bool(configured and frame_compatible)
            people,person_zone,det_ok,det_err=analyzer.analyze_people(frame,danger,warning,max(1,int(args.yolo_every)),args.confidence,ready and poly is not None)
            hands,hand_zone,hand_ok,hand_err=analyzer.analyze_hands(frame,danger,warning,max(1,int(args.hand_every)),ready and poly is not None)
            hand_mode="mediapipe" if hand_ok else "unavailable"
            motion_items,motion_zone,motion_ok,motion_err,motion_warmup=analyzer.analyze_motion_intrusions(frame,danger,warning,rois,[*people,*hands],ready and poly is not None)
            # If MediaPipe is unavailable or misses a moving hand, reuse the already-confirmed
            # motion box only when that moving region is skin-like. This keeps the launcher
            # functional on Python builds where MediaPipe wheels/APIs are unavailable.
            if ready and motion_items and (not hand_ok or not hands):
                fallback_hands,remaining_motion=skin_motion_hand_fallback(frame,motion_items)
                if fallback_hands:
                    if not hands:
                        hands=fallback_hands
                        hand_zone="safe"
                        for item in hands: hand_zone=strongest_zone(hand_zone,str(item.get("zone","safe")))
                    else:
                        hands=[*hands,*fallback_hands]
                        for item in fallback_hands: hand_zone=strongest_zone(hand_zone,str(item.get("zone","safe")))
                    hand_ok=True; hand_err=""; hand_mode="skin_motion_fallback" if hand_detector is None else "mediapipe+skin_motion_fallback"
                    motion_items=remaining_motion
                    motion_zone="safe"
                    for item in motion_items: motion_zone=strongest_zone(motion_zone,str(item.get("zone","safe")))
            led=analyzer.analyze_led(frame,pixel_roi(rois.get("hall_led"),frame.shape),now) if ready else {"configured":False,"blink_detected":False,"signal":0.0,"brightness_delta":0.0,"blink_rate_hz":0.0,"evidence":0.0}
            rotor=analyzer.analyze_rotor(frame,pixel_roi(rois.get("rotor"),frame.shape),now) if ready else {"configured":False,"motion_detected":False,"motion_score":0.0,"active_ratio":0.0}
            sensors={k:analyzer.analyze_sensor_mount(frame,pixel_roi(rois.get(k),frame.shape),k,baseline_ready) for k in SENSOR_KEYS} if ready else ({k:{"status":"frame_mismatch","diff":0.0,"votes":0} for k in SENSOR_KEYS} if configured else {k:{"status":"not_configured","diff":0.0,"votes":0} for k in SENSOR_KEYS})
            safety_zone=strongest_zone(strongest_zone(person_zone,hand_zone),motion_zone) if ready else "unconfigured"
            payload={"source_time":time.strftime("%Y-%m-%dT%H:%M:%S",time.localtime(now)),"vision_protocol":EDGE_PROTOCOL_VERSION,"camera_ok":True,"camera_user_off":False,"camera_index":cam_index,"available_cameras":camera_list_snapshot(),"camera_selection_revision":camera_selection_revision,"camera_refresh_revision":camera_refresh_revision,"camera_requested_index":desired_camera_index,"camera_switch_error":snap.get("camera_switch_error","") ,"fps":fps_value,"frame_seq":frame_seq,"frame_width":int(frame.shape[1]),"frame_height":int(frame.shape[0]),"configured":bool(configured),"config_revision":int(config.get("revision",0) or 0) if configured else 0,"frame_config_compatible":bool(frame_compatible),"baseline_revision":int(state.get("baseline_revision",0) or 0),"baseline_requested_revision":baseline_revision,"baseline_ready":baseline_ready,"person_detector_ok":bool(det_ok),"person_detector_error":det_err,"person_count":len(people),"person_zone":person_zone,"people":people,"hand_detector_ok":bool(hand_ok),"hand_detector_error":hand_err,"hand_detection_mode":hand_mode,"hand_count":len(hands),"hand_zone":hand_zone,"hands":hands,"motion_detector_ok":bool(motion_ok),"motion_detector_error":motion_err,"motion_warmup_remaining":int(motion_warmup),"object_intrusion_count":len(motion_items),"object_intrusion_zone":motion_zone,"unknown_motion_zone":motion_zone,"motion_intrusions":motion_items,"safety_zone":safety_zone,"local_preview":True,"local_preview_port":int(args.preview_port),"local_preview_ready":True,"hall_led":led,"rotor":rotor,"sensors":sensors}
            if now-last_status_send>=0.25: last_status_send=now; bridge.publish_status(payload)
            # Web preview only: upload a JPEG at low rate in the separate network worker.
            # All AI/LED/rotor/sensor decisions above use the local raw frame directly,
            # so a slow or choppy cloud preview cannot slow inference or change results.
            if now-last_frame_send>=0.60:
                last_frame_send=now
                ok_jpg,enc=cv2.imencode(".jpg",frame,[int(cv2.IMWRITE_JPEG_QUALITY),72])
                if ok_jpg: bridge.publish_frame(enc.tobytes())
            if args.show:
                annotated=draw_overlay(frame,config,poly,danger,warning,people,person_zone,led,rotor,sensors,det_ok); cv2.imshow("NEXis Vision Edge",annotated); key=cv2.waitKey(1)&0xFF
                if key in (27,ord('q'),ord('Q')): break
    except KeyboardInterrupt: pass
    finally:
        capture.close()
        bridge.close(); preview.close()
        try:
            if hand_detector is not None: hand_detector.close()
        except Exception: pass
        if args.show: cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    sys.exit(main())
