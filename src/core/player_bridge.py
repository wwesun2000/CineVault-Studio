"""
Local External Player (VLC First-Class Support) & Playlist Bridge (`src/core/player_bridge.py`).
Implemented and verified by Argon. DO NOT MODIFY in Hydrogen tasks.
"""

from __future__ import annotations
import shutil
from pathlib import Path
from typing import List, Optional
from urllib.parse import quote
from .models import MediaItem, PlayerExecutable


COMMON_VLC_PATHS = [
    r"C:\Program Files\VideoLAN\VLC\vlc.exe",
    r"C:\Program Files (x86)\VideoLAN\VLC\vlc.exe",
    "/Applications/VLC.app/Contents/MacOS/VLC",
    "/usr/bin/vlc",
    "/snap/bin/vlc",
]

COMMON_OTHER_PLAYERS = [
    ("PotPlayer", r"C:\Program Files\DAUM\PotPlayer\PotPlayerMini64.exe", "potplayer"),
    ("MPV", "/usr/bin/mpv", "mpv"),
    ("IINA", "/Applications/IINA.app/Contents/MacOS/iina-cli", "iina"),
]


def detect_local_players(custom_vlc_path: Optional[str] = None) -> List[PlayerExecutable]:
    """
    Detects installed local media players with first-class priority for VLC Media Player.
    Always returns at least a configured VLC entry so the user can pick or override the path.
    """
    detected: List[PlayerExecutable] = []

    if custom_vlc_path:
        detected.append(
            PlayerExecutable(name="VLC Media Player (Custom)", executable_path=custom_vlc_path, player_type="vlc")
        )

    which_vlc = shutil.which("vlc")
    if which_vlc:
        detected.append(PlayerExecutable(name="VLC Media Player", executable_path=which_vlc, player_type="vlc"))

    for candidate in COMMON_VLC_PATHS:
        if Path(candidate).is_file() and all(p.executable_path != candidate for p in detected):
            detected.append(PlayerExecutable(name="VLC Media Player", executable_path=candidate, player_type="vlc"))

    # If running in a headless sandbox or machine without VLC installed yet, provide default Windows VLC path
    if not detected:
        detected.append(
            PlayerExecutable(
                name="VLC Media Player (Default Windows Path)",
                executable_path=COMMON_VLC_PATHS[0],
                player_type="vlc",
            )
        )

    for name, path_str, ptype in COMMON_OTHER_PLAYERS:
        if Path(path_str).is_file():
            detected.append(PlayerExecutable(name=name, executable_path=path_str, player_type=ptype))

    return detected


def build_vlc_launch_command(
    vlc_exe: str,
    video_path: str,
    start_time_sec: float = 0.0,
    fullscreen: bool = False,
    custom_title: Optional[str] = None,
) -> List[str]:
    """
    Builds a safe argument array to launch VLC Media Player with optional resume timestamp
    (`--start-time=<sec>`), fullscreen flag (`--fullscreen`), and custom window title.
    Handles local paths, Windows UNC paths (`\\\\server\\share\\file.mp4`), and `smb://` / `http://` URLs.
    """
    cmd = [vlc_exe]
    if start_time_sec > 0.5:
        cmd.append(f"--start-time={int(start_time_sec)}")
    if fullscreen:
        cmd.append("--fullscreen")
    if custom_title:
        cmd.append(f"--meta-title={custom_title}")
    cmd.append(video_path)
    return cmd


def build_android_intent_uri(
    video_url_or_path: str,
    player_package: str = "org.videolan.vlc",
) -> str:
    """
    Builds an Android `vlc://` or `intent://` deep link so the mobile responsive UI can
    launch VLC for Android directly on a phone or tablet.
    """
    if video_url_or_path.startswith(("http://", "https://", "smb://")):
        return f"vlc://{video_url_or_path}"
    encoded = quote(video_url_or_path, safe="/:")
    return f"vlc://file://{encoded}#Intent;package={player_package};end"


def export_m3u8_playlist(
    items: List[MediaItem],
    output_path: Optional[str | Path] = None,
) -> str:
    """
    Generates an Extended M3U8 (`#EXTM3U`) playlist compatible with VLC on Windows, macOS, Linux, and Android.
    """
    lines = ["#EXTM3U", "#PLAYLIST:CineVault Studio Curated Playlist"]
    for item in items:
        dur = int(item.duration_sec) if item.duration_sec > 0 else -1
        performer_prefix = f"{', '.join(item.performers)} - " if item.performers else ""
        studio_tag = f"[{item.studio}] " if item.studio else ""
        star_tag = f" ({item.rating:.1f}★)" if item.rating > 0 else ""
        display = f"{studio_tag}{performer_prefix}{item.title or item.file_name}{star_tag}"
        lines.append(f"#EXTINF:{dur},{display}")
        lines.append(item.file_path)

    content = "\n".join(lines) + "\n"
    if output_path is not None:
        Path(output_path).write_text(content, encoding="utf-8")
    return content
