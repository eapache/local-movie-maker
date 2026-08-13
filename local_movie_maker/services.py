from __future__ import annotations

import shlex
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass


@dataclass
class ManagedService:
    name: str
    base_url: str
    command: str | None
    startup_timeout: int
    health_path: str
    process: subprocess.Popen[bytes] | None = None

    def start(self) -> None:
        if not self.command:
            self._wait_until_ready(2)
            return
        self.process = subprocess.Popen(shlex.split(self.command))
        try:
            self._wait_until_ready(self.startup_timeout)
        except Exception:
            self.stop()
            raise

    def _wait_until_ready(self, timeout: int) -> None:
        deadline = time.monotonic() + timeout
        url = f"{self.base_url.rstrip('/')}{self.health_path}"
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            if self.process is not None and self.process.poll() is not None:
                raise RuntimeError(f"{self.name} exited with code {self.process.returncode} during startup.")
            try:
                with urllib.request.urlopen(url, timeout=2) as response:
                    if response.status < 500:
                        return
            except (OSError, urllib.error.URLError) as exc:
                last_error = exc
            time.sleep(0.5)
        hint = f" Start it first or set {self.name.upper()}_SERVER_COMMAND."
        raise RuntimeError(f"Could not reach {self.name} at {url}.{hint}") from last_error

    def stop(self) -> None:
        if self.process is None or self.process.poll() is not None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)
