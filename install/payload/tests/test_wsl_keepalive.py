import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from ocode import docker
from ocode import wsl_keepalive


class WslKeepaliveTests(unittest.TestCase):
    def test_probe_then_detached_session(self):
        with patch.object(wsl_keepalive.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)), \
             patch.object(wsl_keepalive.subprocess, "Popen") as popen:
            wsl_keepalive.ensure_wsl_keepalive()

        popen.assert_called_once()
        command = popen.call_args.args[0]
        self.assertEqual(command[:4], ["wsl", "--exec", "bash", "-lc"])
        self.assertIn("flock -n", command[-1])
        self.assertIn("docker ps --filter label=io.ocode.mode -q", command[-1])
        self.assertIn('[ "$idle" -ge 4 ] && exit 0', command[-1])

    def test_failed_probe_does_not_start_session(self):
        with patch.object(wsl_keepalive.subprocess, "run", return_value=subprocess.CompletedProcess([], 1)), \
             patch.object(wsl_keepalive.subprocess, "Popen") as popen:
            with self.assertRaisesRegex(RuntimeError, "Docker no está disponible"):
                wsl_keepalive.ensure_wsl_keepalive()
        popen.assert_not_called()

    def test_wsl_launch_preview_starts_keepalive_before_command(self):
        preview = docker.CommandPreview(["wsl", "docker", "run", "-d"], wsl_keepalive=True)
        with patch.object(docker, "_ensure_wsl_keepalive") as ensure, \
             patch.object(docker.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "id")) as run:
            docker.launch_detached(preview)

        ensure.assert_called_once_with()
        run.assert_called_once()

    def test_non_wsl_launch_does_not_start_keepalive(self):
        preview = docker.CommandPreview(["docker", "run", "-d"])
        with patch.object(docker, "_ensure_wsl_keepalive") as ensure, \
             patch.object(docker.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "id")):
            docker.launch_detached(preview)
        ensure.assert_not_called()
