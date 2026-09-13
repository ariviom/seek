import shutil
import subprocess
from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class WebBundleHook(BuildHookInterface):  # type: ignore[misc]
    """Builds the web UI into the package's static directory for regular wheels.

    Editable installs skip this: during development run `pnpm build` in web/ yourself.
    """

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        if self.target_name != "wheel" or version == "editable":
            return
        web = Path(self.root) / "web"
        pnpm = shutil.which("pnpm")
        if pnpm is None:
            raise RuntimeError("pnpm is required to build the mentor web UI: install Node 22 and run `corepack enable`")
        subprocess.run([pnpm, "install", "--frozen-lockfile"], cwd=web, check=True)
        subprocess.run([pnpm, "run", "build"], cwd=web, check=True)
