"""Keep the default WSL distro alive while ocode containers are running."""

import os
import subprocess


_KEEPALIVE_SCRIPT = r'''command -v docker >/dev/null 2>&1 || exit 1
command -v flock >/dev/null 2>&1 || exit 1
flock -n "/tmp/ocode-wsl-keepalive-${UID}.lock" bash -c '
idle=0
while :; do
  if containers=$(docker ps --filter label=io.ocode.mode -q 2>/dev/null); then
    if [ -n "$containers" ]; then
      idle=0
    else
      idle=$((idle + 1))
      [ "$idle" -ge 4 ] && exit 0
    fi
  else
    idle=0
  fi
  sleep 15
done
'
'''


def ensure_wsl_keepalive() -> None:
    """Start a detached WSL session; its lock makes duplicate starts harmless."""
    command = ["wsl", "--exec", "bash", "-lc", _KEEPALIVE_SCRIPT]
    try:
        probe = subprocess.run(
            [
                "wsl", "--exec", "bash", "-lc",
                "command -v flock >/dev/null && docker version --format '{{.Server.Version}}'",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError("No se pudo comprobar Docker dentro de WSL.") from exc
    if probe.returncode != 0:
        raise RuntimeError("Docker no está disponible dentro de WSL.")

    kwargs = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = (
            getattr(subprocess, "CREATE_NO_WINDOW", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        )
    try:
        subprocess.Popen(command, **kwargs)
    except OSError as exc:
        raise RuntimeError("No se pudo iniciar la sesión persistente de WSL.") from exc
