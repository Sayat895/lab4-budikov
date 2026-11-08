import os
import sys
from pathlib import Path


def certificate_directory():
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        return Path.home() / ".local" / "share" / "Lab4Budikov" / "tls"

    executable = Path(sys.executable)
    if "WindowsApps" in executable.parts and executable.parent.name.startswith(
        "PythonSoftwareFoundation.Python."
    ):
        return (
            Path(local_app_data)
            / "Packages"
            / executable.parent.name
            / "LocalCache"
            / "Local"
            / "Lab4Budikov"
            / "tls"
        )
    return Path(local_app_data) / "Lab4Budikov" / "tls"
