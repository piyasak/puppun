

import sys

# Python 3.14 asks WMI for the Windows version and CPU (platform.win32_ver/uname/machine), and a stuck WMI
# service hangs every caller, yt-dlp's YoutubeDL() included (QA PC, 2026-10-23: imports and downloads froze).
# Without its private _wmi module, platform reads the same answers from sys.getwindowsversion and the registry.
if sys.platform == "win32":
    import platform as _platform

    if getattr(_platform, "_wmi", None) is not None:
        _platform._wmi = None
