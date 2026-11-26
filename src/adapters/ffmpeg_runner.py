"""
FFmpeg Smart Cover Frame Extractor (`src/adapters/ffmpeg_runner.py`).
Assigned to Hydrogen: `[HYDROGEN-TASK-04]`.
"""

from __future__ import annotations
import re
import shutil
import struct
import subprocess
import sys
from pathlib import Path
from typing import List, Optional
from ..core.metadata_engine import compute_smart_frame_timestamp


def find_ffmpeg_binary(ffmpeg_bin: str = "ffmpeg") -> Optional[str]:
    """
    Locates `ffmpeg` in the application/executable directory first, then system PATH.
    Returns the resolved path or None if not installed.
    """
    app_dir = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent.parent
    local_exe = app_dir / ("ffmpeg.exe" if sys.platform == "win32" else "ffmpeg")
    if local_exe.is_file():
        return str(local_exe)
    return shutil.which(ffmpeg_bin)


def _parse_mvhd_chunk(buf: bytes) -> float:
    """Searches a byte buffer for an ISO BMFF `mvhd` atom and extracts duration in seconds."""
    idx = 0
    while True:
        pos = buf.find(b"mvhd", idx)
        if pos == -1 or pos + 24 > len(buf):
            break
        version = buf[pos + 4]
        try:
            if version == 0 and pos + 24 <= len(buf):
                timescale, duration = struct.unpack(">II", buf[pos + 16 : pos + 24])
                if timescale > 0 and duration > 0:
                    sec = float(duration) / float(timescale)
                    if 1.0 <= sec <= 86400.0:
                        return round(sec, 1)
            elif version == 1 and pos + 36 <= len(buf):
                timescale, duration = struct.unpack(">IQ", buf[pos + 24 : pos + 36])
                if timescale > 0 and duration > 0:
                    sec = float(duration) / float(timescale)
                    if 1.0 <= sec <= 86400.0:
                        return round(sec, 1)
        except struct.error:
            pass
        idx = pos + 4
    return 0.0


def probe_video_duration_sec(video_path: str | Path, ffmpeg_bin: str = "ffmpeg") -> float:
    """
    Fast video duration prober:
    1. First attempts zero-subprocess pure-Python ISO BMFF (`moov`/`mvhd`) parsing for MP4/M4V/MOV
       (checks top-level box chain, plus head/tail 512KB buffers).
    2. Falls back to `ffmpeg -i` stderr `Duration: HH:MM:SS.xx` parsing if FFmpeg is available.
    """
    p = Path(video_path)
    try:
        if not p.is_file():
            return 0.0
        fsize = p.stat().st_size
        if fsize < 64:
            return 0.0
    except OSError:
        return 0.0

    suffix = p.suffix.lower()
    if suffix in (".mp4", ".m4v", ".mov"):
        try:
            with p.open("rb") as f:
                # 1. Walk top-level MP4 atoms to jump straight to `moov`
                offset = 0
                steps = 0
                while offset + 8 <= fsize and steps < 32:
                    steps += 1
                    f.seek(offset)
                    hdr = f.read(16)
                    if len(hdr) < 8:
                        break
                    box_size, box_type = struct.unpack(">I4s", hdr[:8])
                    if box_size == 1:
                        if len(hdr) < 16:
                            break
                        box_size = struct.unpack(">Q", hdr[8:16])[0]
                    elif box_size == 0:
                        box_size = fsize - offset
                    if box_size < 8:
                        break
                    if box_type == b"moov":
                        read_len = min(box_size, 512 * 1024)
                        f.seek(offset)
                        moov_buf = f.read(read_len)
                        sec = _parse_mvhd_chunk(moov_buf)
                        if sec > 0:
                            return sec
                        break
                    offset += box_size

                # 2. Fallback head/tail 256KB scan
                f.seek(0)
                sec = _parse_mvhd_chunk(f.read(min(fsize, 256 * 1024)))
                if sec > 0:
                    return sec
                if fsize > 256 * 1024:
                    f.seek(max(0, fsize - 256 * 1024))
                    sec = _parse_mvhd_chunk(f.read(256 * 1024))
                    if sec > 0:
                        return sec
        except OSError:
            pass

    resolved_bin = find_ffmpeg_binary(ffmpeg_bin)
    if resolved_bin:
        popen_kwargs = {}
        if sys.platform == "win32":
            popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        try:
            proc = subprocess.run(
                [resolved_bin, "-hide_banner", "-i", str(p)],
                capture_output=True,
                timeout=6,
                check=False,
                **popen_kwargs,
            )
            stderr_txt = (proc.stderr or b"").decode("utf-8", errors="ignore")
            m = re.search(r"Duration:\s*(\d{2}):(\d{2}):(\d{2}(?:\.\d+)?)", stderr_txt)
            if m:
                hh, mm, ss = int(m.group(1)), int(m.group(2)), float(m.group(3))
                return round(hh * 3600 + mm * 60 + ss, 1)
        except (OSError, subprocess.SubprocessError):
            pass

    return 0.0


# [HYDROGEN-TASK-04]
def build_ffmpeg_extract_cmd(
    video_path: str,
    output_jpg_path: str,
    timestamp_sec: float,
    ffmpeg_bin: str = "ffmpeg",
) -> List[str]:
    """
    Constructs the exact FFmpeg CLI command to extract a single 640px-wide high-quality JPEG
    frame at `timestamp_sec` for use as a fallback cover poster when online cover art is missing.
    """
    return [
        ffmpeg_bin,
        "-y",
        "-ss",
        f"{timestamp_sec:.2f}",
        "-i",
        video_path,
        "-frames:v",
        "1",
        "-vf",
        "scale=640:-1",
        "-q:v",
        "2",
        output_jpg_path,
    ]


def extract_fallback_cover_frame(
    video_path: str,
    output_jpg_path: str,
    duration_sec: float = 0.0,
    ffmpeg_bin: str = "ffmpeg",
) -> bool:
    """
    Computes candidate timestamps via Argon's `compute_smart_frame_timestamp(duration_sec)`
    and runs FFmpeg to capture a representative video frame.
    Returns True if `output_jpg_path` was created and is non-empty.
    """
    candidates = compute_smart_frame_timestamp(duration_sec)
    out_file = Path(output_jpg_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)

    resolved_bin = find_ffmpeg_binary(ffmpeg_bin)
    if not resolved_bin:
        return False
    popen_kwargs = {}
    if sys.platform == "win32":
        popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

    for ts in candidates:
        cmd = build_ffmpeg_extract_cmd(video_path, str(out_file), ts, ffmpeg_bin=resolved_bin)
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=15, check=False, **popen_kwargs)
            if proc.returncode == 0 and out_file.is_file() and out_file.stat().st_size > 0:
                return True
        except (OSError, subprocess.SubprocessError):
            return False

    return False
