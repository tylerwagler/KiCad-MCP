"""Freerouting backend — drives the Freerouting autorouter headless.

Freerouting is a Java application. We locate a ``freerouting*.jar`` (or a native
launcher / Docker image) and invoke it on a Specctra ``.dsn``, producing a
``.ses`` session file that the SES importer turns back into traces/vias.

Discovery order:
1. ``FREEROUTING_JAR`` env var (path to a jar, run with ``java -jar``).
2. ``FREEROUTING_CMD`` env var (a full launcher command, space-split).
3. ``freerouting`` on PATH (native launcher).
4. Common jar locations under the home dir / ``/opt`` / cwd.
5. Docker image ``ghcr.io/freerouting/freerouting`` if Docker is present.

Exit codes are unreliable, so success is judged by a parseable, non-empty SES.
"""

from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

DEFAULT_TIMEOUT = 300  # seconds
_DOCKER_IMAGE = "ghcr.io/freerouting/freerouting"

_JAR_GLOBS = [
    "~/freerouting*.jar",
    "~/.local/share/freerouting/freerouting*.jar",
    "/opt/freerouting/freerouting*.jar",
    "/usr/local/share/freerouting/freerouting*.jar",
    "./freerouting*.jar",
]


class FreeroutingNotFound(Exception):
    """Raised when no Freerouting runtime can be located."""


class FreeroutingError(Exception):
    """Raised when a Freerouting run fails."""


@dataclass
class FreeroutingRuntime:
    """A resolved way to launch Freerouting."""

    kind: str  # "jar" | "native" | "docker"
    detail: str  # jar path / launcher path / docker image

    def describe(self) -> str:
        return f"{self.kind}: {self.detail}"


def _find_jar() -> str | None:
    env_jar = os.environ.get("FREEROUTING_JAR")
    if env_jar and Path(env_jar).expanduser().is_file():
        return str(Path(env_jar).expanduser())
    for pattern in _JAR_GLOBS:
        matches = sorted(glob.glob(os.path.expanduser(pattern)), reverse=True)
        if matches:
            return matches[0]
    return None


def find_runtime() -> FreeroutingRuntime | None:
    """Locate a usable Freerouting runtime, or None."""
    # An explicit launcher command wins.
    cmd = os.environ.get("FREEROUTING_CMD")
    if cmd:
        return FreeroutingRuntime(kind="native", detail=cmd)

    jar = _find_jar()
    if jar and shutil.which("java"):
        return FreeroutingRuntime(kind="jar", detail=jar)

    native = shutil.which("freerouting")
    if native:
        return FreeroutingRuntime(kind="native", detail=native)

    if shutil.which("docker"):
        return FreeroutingRuntime(kind="docker", detail=_DOCKER_IMAGE)

    return None


def is_available() -> bool:
    """True if some Freerouting runtime is present."""
    return find_runtime() is not None


def runtime_info() -> dict[str, object]:
    """Report what Freerouting runtime (if any) was found and how to install one."""
    rt = find_runtime()
    info: dict[str, object] = {
        "available": rt is not None,
        "java": shutil.which("java"),
        "docker": shutil.which("docker"),
    }
    if rt is not None:
        info["runtime"] = rt.describe()
        if rt.kind == "jar":
            info["version"] = _jar_version(rt.detail)
    else:
        info["hint"] = (
            "No Freerouting found. Download freerouting-<ver>.jar from "
            "https://github.com/freerouting/freerouting/releases and set FREEROUTING_JAR, "
            "or install Docker to use the ghcr.io/freerouting/freerouting image."
        )
    return info


def _jar_version(jar: str) -> str:
    """Best-effort version from the jar filename (e.g. freerouting-2.2.4.jar).

    We intentionally avoid launching the jar: Freerouting ignores unknown flags
    like ``--version`` and proceeds to start up rather than exiting, so probing
    it for a version would hang.
    """
    match = re.search(r"freerouting[-_]?v?(\d+\.\d+(?:\.\d+)?)", Path(jar).name, re.IGNORECASE)
    return match.group(1) if match else "unknown"


def _build_command(
    rt: FreeroutingRuntime,
    dsn_path: str,
    ses_path: str,
    max_passes: int,
    threads: int,
) -> list[str]:
    """Build the argv for a given runtime."""
    common = [
        "-de",
        dsn_path,
        "-do",
        ses_path,
        "-mp",
        str(max_passes),
        "-mt",
        str(threads),
        "-dct",
        "0",
        "-da",  # disable anonymous analytics
        "--gui.enabled=false",
    ]
    if rt.kind == "jar":
        java = shutil.which("java") or "java"
        return [java, "-Djava.awt.headless=true", "-jar", rt.detail, *common]
    if rt.kind == "native":
        # FREEROUTING_CMD may be a multi-token launcher.
        launcher = rt.detail.split()
        return [*launcher, *common]
    # docker
    dsn_dir = str(Path(dsn_path).parent)
    return [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{dsn_dir}:/work",
        rt.detail,
        "-de",
        f"/work/{Path(dsn_path).name}",
        "-do",
        f"/work/{Path(ses_path).name}",
        "-mp",
        str(max_passes),
        "-mt",
        str(threads),
        "-dct",
        "0",
        "-da",
        "--gui.enabled=false",
    ]


def route(
    dsn_path: str,
    ses_path: str,
    *,
    max_passes: int = 10,
    threads: int = 1,
    timeout: int = DEFAULT_TIMEOUT,
) -> dict[str, object]:
    """Run Freerouting on ``dsn_path``, writing ``ses_path``.

    Returns a dict with run metadata. Raises :class:`FreeroutingNotFound` if no
    runtime exists, or :class:`FreeroutingError` if no SES was produced.
    """
    rt = find_runtime()
    if rt is None:
        raise FreeroutingNotFound(
            "Freerouting not found. Set FREEROUTING_JAR or install Docker. "
            "See check_freerouting for details."
        )

    if not Path(dsn_path).is_file():
        raise FreeroutingError(f"DSN not found: {dsn_path}")

    cmd = _build_command(rt, dsn_path, ses_path, max_passes, threads)
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise FreeroutingError(f"Freerouting timed out after {timeout}s") from exc
    except OSError as exc:
        raise FreeroutingError(f"Failed to launch Freerouting: {exc}") from exc

    ses = Path(ses_path)
    if not ses.is_file() or ses.stat().st_size == 0:
        tail = (proc.stderr or proc.stdout or "").strip()[-800:]
        raise FreeroutingError(
            f"Freerouting produced no SES output (exit {proc.returncode}).\n{tail}"
        )

    return {
        "runtime": rt.describe(),
        "exit_code": proc.returncode,
        "ses_path": ses_path,
        "ses_bytes": ses.stat().st_size,
        "max_passes": max_passes,
    }
