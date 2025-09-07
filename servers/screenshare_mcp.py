#!/usr/bin/env python3
"""
MCP Server: Screen Capture (active monitor / region snapshots & bursts)
Tools:
  - list_displays(max_index?: int=10)
  - screenshare_start(monitor_index?: int=1, left?: int=0, top?: int=0, width?: int=0, height?: int=0, scale?: float=1.0)
  - screenshare_status()
  - screenshare_capture(save_dir?: str="~/.screen_frames", format?: "jpg"|"png"="jpg")
  - screenshare_burst(n?: int=8, period_ms?: int=150, save_dir?: str=".", format?: "jpg"|"png"="jpg", warmup?: int=0, duration_ms?: int=0)
  - screenshare_stop()

Notes:
- Drop-in replacement for the webcam-based screenshare MCP, but sources are screen grabs.
- Uses mss (fast, cross-platform) + PIL for encoding.
- No base64 in responses (optimized for @file attachment flow).
- Pure MCP over stdio (FastMCP). Logs to stderr only. No network calls.

Install deps:
  pip install mss pillow fastmcp  # or mcp.server.fastmcp
"""

import os, sys, time, logging
from pathlib import Path
from typing import Optional, Dict, Any, Tuple

# ----- Logging to stderr only -----
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger("ScreenMCP")

# ---------- FastMCP ----------
try:
    from mcp.server.fastmcp import FastMCP
except Exception:
    from fastmcp import FastMCP  # type: ignore

# ---------- Screen capture (mss + PIL) ----------
try:
    import mss  # fast, zero-copy screen grabs
    from PIL import Image
except Exception as e:
    log.error("Missing dependency: %s (pip install mss pillow)", e)
    raise

# Global capture configuration
_SRC = {
    "sct": None,          # mss.mss() handle
    "monitor_index": 1,   # mss uses 1..N for real monitors, 0 is virtual full area
    "region": None,       # dict(left, top, width, height) or None for full monitor
    "scale": 1.0,         # optional downscale (0.1..1.0)
    "props": {},
}


def _open_source(monitor_index: int, left: int, top: int, width: int, height: int, scale: float) -> Tuple[bool, str]:
    """Initialize mss and set target monitor/region; populate _SRC."""
    if _SRC["sct"] is not None:
        return True, "Screen capture already initialized"

    try:
        sct = mss.mss()
    except Exception as e:
        return False, f"Failed to initialize mss: {e}"

    monitors = sct.monitors  # index 0 is all-monitors virtual screen; 1..N are real
    if monitor_index < 0 or monitor_index >= len(monitors):
        sct.close()
        return False, f"Invalid monitor_index {monitor_index}; available 0..{len(monitors)-1}"

    mon = monitors[monitor_index]

    # Determine region: if width/height <= 0, use full monitor
    if width <= 0 or height <= 0:
        region = {
            "left": int(mon["left"]),
            "top": int(mon["top"]),
            "width": int(mon["width"]),
            "height": int(mon["height"]),
        }
    else:
        region = {
            "left": int(mon["left"] + max(0, left)),
            "top": int(mon["top"] + max(0, top)),
            "width": int(max(1, width)),
            "height": int(max(1, height)),
        }

    scale = max(0.1, min(1.0, float(scale or 1.0)))

    _SRC.update({
        "sct": sct,
        "monitor_index": monitor_index,
        "region": region,
        "scale": scale,
        "props": {
            "monitor_index": monitor_index,
            "region": region.copy(),
            "scale": scale,
        },
    })

    log.info("Screen source ready: monitor=%s region=%s scale=%.2f", monitor_index, region, scale)
    return True, "Screen source initialized"


def _close_source():
    sct = _SRC.get("sct")
    if sct is not None:
        try:
            sct.close()
        except Exception:
            pass
    _SRC.update({"sct": None, "monitor_index": 1, "region": None, "scale": 1.0, "props": {}})

def _is_wsl() -> bool:
    """Return True if running under Windows Subsystem for Linux."""
    try:
        import platform, os
        if "microsoft" in platform.release().lower() or "microsoft" in platform.version().lower():
            return True
        if os.path.exists("/proc/sys/fs/binfmt_misc/WSLInterop"):
            return True
        return False
    except Exception:
        return False

def _grab() -> Tuple[bool, Optional[Image.Image], str]:
    from PIL import Image
    import shutil, subprocess, tempfile

    sct = _SRC.get("sct")
    region = _SRC.get("region")
    scale = float(_SRC.get("scale") or 1.0)

    if sct is None or region is None:
        return False, None, "Screen source not initialized"

    # --- Fast path: MSS (works on macOS and most X11/Wayland setups) ---
    try:
        raw = sct.grab(region)
        img = Image.frombytes("RGB", raw.size, raw.rgb)
        if 0 < scale < 1.0:
            w = max(1, int(img.width * scale))
            h = max(1, int(img.height * scale))
            img = img.resize((w, h), Image.LANCZOS)
        return True, img, "ok"
    except Exception as e_primary:
        err_primary = str(e_primary)

    # --- WSL fallback: capture Windows desktop via PowerShell ---
    if _is_wsl():
        try:
            ps_script = r"""
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$bounds = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$bmp = New-Object System.Drawing.Bitmap($bounds.Width, $bounds.Height)
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($bounds.Location, [System.Drawing.Point]::Empty, $bounds.Size)
$g.Dispose()
$tmp = [System.IO.Path]::Combine([System.IO.Path]::GetTempPath(), "wsl_scrn_{0:yyyyMMdd_HHmmss_fff}.png" -f (Get-Date))
$bmp.Save($tmp, [System.Drawing.Imaging.ImageFormat]::Png)
$bmp.Dispose()
Write-Output $tmp
"""
            out = subprocess.check_output(
                ["powershell.exe", "-NoProfile", "-Command", ps_script],
                stderr=subprocess.STDOUT,
                text=True,
                timeout=float(os.getenv("SCREENSHARE_WSL_PS_TIMEOUT", "10")),
            ).strip()
            wsl_path = subprocess.check_output(["wslpath", "-u", out], text=True).strip()
            img = Image.open(wsl_path)
            if 0 < scale < 1.0:
                w = max(1, int(img.width * scale))
                h = max(1, int(img.height * scale))
                img = img.resize((w, h), Image.LANCZOS)
            return True, img, "ok"
        except Exception as e_ps:
            err_ps = str(e_ps)
    else:
        err_ps = "n/a"

    # --- Linux compositor fallbacks: GNOME or wlroots ---
    try:
        tmp_png = os.path.join(tempfile.gettempdir(), "screenshare_fallback.png")
        if shutil.which("gnome-screenshot"):
            subprocess.run(["gnome-screenshot", "--file", tmp_png], check=True, timeout=10)
        elif shutil.which("grim"):
            # full-output Wayland screenshot on wlroots compositors (e.g., sway/hyprland)
            subprocess.run(["grim", tmp_png], check=True, timeout=10)
        else:
            raise RuntimeError("no compositor screenshot tool (gnome-screenshot/grim) found")

        img = Image.open(tmp_png)
        if 0 < scale < 1.0:
            w = max(1, int(img.width * scale))
            h = max(1, int(img.height * scale))
            img = img.resize((w, h), Image.LANCZOS)
        return True, img, "ok"
    except Exception as e_fb:
        err_fallback = str(e_fb)

    # If everything failed, report details for debugging
    return False, None, f"Failed to grab (mss={err_primary}, wsl_ps={err_ps}, fallback={locals().get('err_fallback','n/a')})"


def _encode_image_pil(img: Image.Image, fmt: str) -> Tuple[bool, bytes, str, int, int]:
    fmt = (fmt or "jpg").lower()
    ext = ".jpg" if fmt == "jpg" else ".png"
    try:
        from io import BytesIO
        bio = BytesIO()
        if fmt == "jpg":
            # ensure RGB; JPEG has no alpha
            if img.mode != "RGB":
                img = img.convert("RGB")
            img.save(bio, format="JPEG", quality=92, optimize=True)
            mime = "image/jpeg"
        else:
            img.save(bio, format="PNG", optimize=True)
            mime = "image/png"
        data = bio.getvalue()
        return True, data, mime, img.width, img.height
    except Exception as e:
        return False, b"", f"encode failed: {e}", img.width, img.height


def _timestamp_name(prefix="screen", ext=".jpg") -> str:
    ts = time.strftime("%Y%m%d_%H%M%S")
    ms = int((time.time() % 1) * 1000)
    return f"{prefix}_{ts}_{ms:03d}{ext}"


# ---------- MCP server ----------
mcp = FastMCP("Screen MCP")


@mcp.tool()
def list_displays(max_index: int = 10) -> Dict[str, Any]:
    """Enumerate available displays/monitors with geometry."""
    try:
        with mss.mss() as sct:
            mons = sct.monitors  # 0=virtual bounding box, 1..N real
            out = []
            for i, mon in enumerate(mons):
                if i > max_index:
                    break
                out.append({
                    "index": i,
                    "left": int(mon.get("left", 0)),
                    "top": int(mon.get("top", 0)),
                    "width": int(mon.get("width", 0)),
                    "height": int(mon.get("height", 0)),
                    "virtual": (i == 0),
                })
            return {"displays": out}
    except Exception as e:
        return {"displays": [], "error": str(e)}


@mcp.tool()
def screenshare_start(
    monitor_index: int = 1,
    left: int = 0,
    top: int = 0,
    width: int = 0,
    height: int = 0,
    scale: float = 1.0,
) -> Dict[str, Any]:
    """
    Initialize the screen source.
    - monitor_index: 0 = virtual (all monitors), 1..N = specific monitor from list_displays
    - left/top/width/height: optional crop region relative to the chosen monitor; if width/height <= 0, uses full monitor
    - scale: 0.1..1.0 downscale to reduce file size
    """
    ok, msg = _open_source(monitor_index, left, top, width, height, scale)
    return {"ok": ok, "message": msg, "props": _SRC["props"], "monitor_index": _SRC["monitor_index"]}


@mcp.tool()
def screenshare_status() -> Dict[str, Any]:
    """Report whether screen source is initialized and its properties."""
    sct = _SRC.get("sct")
    return {
        "open": bool(sct is not None),
        "monitor_index": _SRC.get("monitor_index"),
        "props": _SRC.get("props", {}),
    }


@mcp.tool()
def screenshare_capture(
    save_dir: str = "~/.screen_frames",
    format: str = "jpg",
) -> Dict[str, Any]:
    """
    Capture one screenshot. Saves to save_dir and returns the saved path and metadata.
    (No base64 returned.)
    """
    ok, img, msg = _grab()
    if not ok or img is None:
        return {"ok": False, "error": msg}

    ok2, data, mime, w, h = _encode_image_pil(img, format)
    if not ok2:
        return {"ok": False, "error": mime}

    out_dir = Path(os.path.expanduser(save_dir))
    out_dir.mkdir(parents=True, exist_ok=True)
    ext = ".jpg" if mime == "image/jpeg" else ".png"
    fname = _timestamp_name("screen", ext)
    fpath = out_dir / fname
    try:
        with open(fpath, "wb") as f:
            f.write(data)
    except Exception as e:
        return {"ok": False, "error": f"Failed to write file: {e}"}

    return {
        "ok": True,
        "path": str(fpath),
        "mime": mime,
        "width": int(w),
        "height": int(h),
    }


@mcp.tool()
def screenshare_burst(
    n: int = 8,
    period_ms: int = 150,
    save_dir: str = ".",
    format: str = "jpg",
    warmup: int = 0,
    duration_ms: int = 0,
) -> Dict[str, Any]:
    """
    Capture N screenshots spaced by period_ms and return their file paths (chronological).
    If duration_ms > 0, n is computed as round(duration_ms / period_ms).
    (No base64 returned.)
    """
    if _SRC.get("sct") is None:
        return {"ok": False, "error": "Screen source not initialized"}

    # compute n from duration if provided
    if duration_ms and duration_ms > 0:
        n = max(1, int(round(float(duration_ms) / float(period_ms))))

    out_dir = Path(os.path.expanduser(save_dir))
    out_dir.mkdir(parents=True, exist_ok=True)

    period_s = max(0.0, float(period_ms) / 1000.0)
    t0 = time.perf_counter()

    paths: list[str] = []
    mime_last = "image/jpeg" if (format or "jpg").lower() == "jpg" else "image/png"
    w_last = h_last = 0

    # optional warmup no-op (kept for API parity)
    for _ in range(max(0, int(warmup))):
        _grab()

    for i in range(max(1, int(n))):
        target = t0 + i * period_s
        now = time.perf_counter()
        if target > now:
            time.sleep(target - now)

        ok, img, msg = _grab()
        if not ok or img is None:
            return {"ok": False, "error": f"Failed to capture: {msg}", "paths": paths}

        ok2, data, mime, w, h = _encode_image_pil(img, format)
        if not ok2:
            return {"ok": False, "error": "encode failed", "paths": paths}
        mime_last, w_last, h_last = mime, w, h

        ts = time.strftime("%Y%m%d_%H%M%S")
        ms = int((time.time() % 1) * 1000)
        ext = ".jpg" if mime == "image/jpeg" else ".png"
        fname = f"scr_{ts}_{ms:03d}_{i:02d}{ext}"
        fpath = out_dir / fname
        with open(fpath, "wb") as f:
            f.write(data)
        paths.append(str(fpath))

        if i == 0 or (i + 1) % 5 == 0 or (i + 1) == n:
            log.info("Burst capture %d/%d saved %s", i + 1, n, fpath.name)

    return {
        "ok": True,
        "paths": paths,
        "mime": mime_last,
        "width": int(w_last),
        "height": int(h_last),
        "n": len(paths),
        "period_ms": period_ms,
        "duration_ms": duration_ms,
        "save_dir": str(out_dir),
    }


@mcp.tool()
def screenshare_stop() -> Dict[str, Any]:
    """Release the screen source."""
    _close_source()
    return {"ok": True}


if __name__ == "__main__":
    mcp.run()
