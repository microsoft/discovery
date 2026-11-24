"""Minimal stdio JSON-RPC driver for the bundled CLIO (Science.Autopilot --mcp).

    python scripts/clio_driver.py tools
Live runs require an explicit --cwd, project root, marked results and new --out.

Runs are hosted in-process by this driver's child server, so this process must stay alive for
the run's duration. All JSON-RPC traffic is appended to <log_dir>/rpc.jsonl.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from queue import Empty, Queue

if __package__:
    from .result_paths import ResultPaths
else:
    from result_paths import ResultPaths


def _executable(value: str | Path) -> str:
    """Validate an operator-selected path or command; never silently ignore it."""
    text = os.path.expandvars(str(value)).strip()
    if not text:
        raise ValueError("CLIO executable override must not be empty")
    path = Path(text).expanduser()
    if not path.is_file():
        found = shutil.which(str(path))
        if found is None:
            raise FileNotFoundError(f"CLIO executable not found: {text}")
        path = Path(found)
    if not path.is_file() or not os.access(path, os.X_OK):
        raise PermissionError(f"CLIO executable is not an executable file: {text}")
    return str(path.resolve())


def _version_key(name: str) -> tuple:
    """Sort installed versions numerically, with a release after its prereleases."""
    match = re.search(r"(\d+(?:\.\d+)+)(?:-([A-Za-z0-9.-]+))?", name)
    if match is None:
        return (0, 0, 0, 0), 0, ()
    numbers = tuple(int(part) for part in match[1].split("."))
    version = numbers + (0,) * max(0, 4 - len(numbers))
    suffix = tuple((1, int(part)) if part.isdigit() else (0, part.lower())
                   for part in re.findall(r"\d+|[A-Za-z]+", match[2] or ""))
    return version, int(match[2] is None), suffix


def exe(clio_executable: str | Path | None = None) -> str:
    """Resolve explicit option, environment, PATH, then Discovery Preview installs."""
    if clio_executable is not None:
        return _executable(clio_executable)
    if "DISCOVERY_CLIO_EXE" in os.environ:
        return _executable(os.environ["DISCOVERY_CLIO_EXE"])
    for command in ("Science.Autopilot", "Science.Autopilot.exe"):
        found = shutil.which(command)
        if found:
            return _executable(found)
    local = os.environ.get("LOCALAPPDATA")
    if local:
        root = Path(local) / "Programs" / "Discovery App - Preview"
        tail = ("extensions/discovery-app.discovery-app-*/dist/clio-plugin/plugins/"
                "clio/bin/windows-x64/Science.Autopilot.exe")
        hits = [path for pattern in (f"*/{tail}", tail) for path in root.glob(pattern)
                if path.is_file() and os.access(path, os.X_OK)]
        if hits:
            def version(path: Path) -> tuple:
                parts = path.relative_to(root).parts
                extension = next(p for p in parts if p.startswith("discovery-app.discovery-app-"))
                return _version_key(parts[0]), _version_key(extension), str(path)

            return str(max(hits, key=version).resolve())
    raise FileNotFoundError(
        "CLIO executable not found. Install Discovery/CLIO, put Science.Autopilot on PATH, "
        "or set --clio-executable / DISCOVERY_CLIO_EXE to an installed executable."
    )


class Client:
    def __init__(self, cwd: Path, log: Path, *, clio_executable: str | Path | None = None,
                 env: dict[str, str] | None = None):
        executable = exe(clio_executable)
        self.log = log.open("x", encoding="utf-8")
        self.p = subprocess.Popen(
            [executable, "--mcp"], cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, encoding="utf-8", bufsize=1, env=env,
        )
        self.q: Queue = Queue()
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()
        self.n = 0

    def _read(self):
        for line in self.p.stdout:
            line = line.strip()
            if line:
                self.log.write(json.dumps({"t": time.time(), "in": line}) + "\n")
                self.log.flush()
                try:
                    self.q.put(json.loads(line))
                except json.JSONDecodeError:
                    pass

    def send(self, method: str, params: dict | None = None, notify: bool = False):
        msg = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        if not notify:
            self.n += 1
            msg["id"] = self.n
        self.log.write(json.dumps({"t": time.time(), "out": msg}) + "\n")
        self.log.flush()
        self.p.stdin.write(json.dumps(msg) + "\n")
        self.p.stdin.flush()
        return msg.get("id")

    def call(self, method: str, params: dict | None = None, timeout: float = 600):
        rid = self.send(method, params)
        end = time.time() + timeout
        while time.time() < end:
            try:
                m = self.q.get(timeout=1)
            except Empty as exc:
                if self.p.poll() is not None:
                    raise RuntimeError("CLIO server exited") from exc
                continue
            if m.get("id") == rid:
                if "error" in m:
                    raise RuntimeError(json.dumps(m["error"]))
                return m["result"]
        raise TimeoutError(method)

    def init(self):
        self.call("initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                                 "clientInfo": {"name": "physics-heldout", "version": "1"}})
        self.send("notifications/initialized", notify=True)

    def tool(self, name: str, args: dict, timeout: float = 600) -> str:
        r = self.call("tools/call", {"name": name, "arguments": args}, timeout)
        return "\n".join(c.get("text", "") for c in r.get("content", []))

    def close(self):
        try:
            self.p.kill()
            self.p.wait(timeout=10)
        except OSError:
            pass
        self.reader.join(timeout=5)
        self.log.close()


def run(prompt: str, out: Path, *, cwd: Path, timeout: float = 7200,
    clio_executable: str | Path | None = None, env: dict[str, str] | None = None) -> dict:
    """Own the native server until completion; retain full receipts in an isolated cwd."""
    out.mkdir(parents=True, exist_ok=False)
    # Keep the original two-argument client interface for embedders and test doubles.
    options = {}
    if clio_executable is not None:
        options["clio_executable"] = clio_executable
    if env is not None:
        options["env"] = env
    c = Client(cwd, out / "rpc.jsonl", **options)
    t0 = time.monotonic()
    try:
        c.init()
        tools = {t["name"]: t for t in c.call("tools/list")["tools"]}
        with (out / "tools.json").open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(sorted(tools), indent=1))
        start = c.tool("start", {"task": prompt}, 300)
        with (out / "start.txt").open("x", encoding="utf-8") as stream:
            stream.write(start)
        m = re.search(r"^\s*run_id:\s*([0-9a-f]{6,})", start, re.M)
        if not m:
            raise RuntimeError("no run_id in start response")
        run_id = m.group(1)
        seq, deadline, state = 0, time.monotonic() + timeout, "running"
        while time.monotonic() < deadline:
            try:
                w = c.tool(
                    "wait", {"run_id": run_id, "since_seq": seq, "timeout_seconds": 120}, 300,
                )
            except TimeoutError:
                continue
            with (out / "wait.log").open("a", encoding="utf-8") as fh:
                fh.write(w + "\n---\n")
            s = re.search(r"seq=(\d+)", w)
            seq = int(s.group(1)) if s else seq
            b = re.search(rf"run {run_id} \[(\w+)\]", w)
            if b and b.group(1) in ("done", "failed", "stopped"):
                state = b.group(1)
                break
            if "No run found" in w:
                state = "lost"
                break
        else:
            state = "timeout"
            c.tool("stop", {"run_id": run_id}, 60)
        result = {"run_id": run_id, "state": state, "seq": seq,
                  "wall_s": round(time.monotonic() - t0, 3), "server_pid": c.p.pid}
        with (out / "result.json").open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(result, indent=1))
        return result
    finally:
        c.close()


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("action", choices=("tools", "run"))
    ap.add_argument("prompt", type=Path, nargs="?")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--project-root", type=Path)
    ap.add_argument("--results-dir", type=Path)
    ap.add_argument("--runs-root", type=Path, help="Optional per-prompt store under results/runs")
    ap.add_argument("--cwd", type=Path)
    ap.add_argument("--timeout", type=float, default=7200)
    ap.add_argument("--clio-executable",
                    help="Installed CLIO executable; overrides DISCOVERY_CLIO_EXE")
    args = ap.parse_args(argv)
    if args.action == "tools":
        with tempfile.TemporaryDirectory(prefix="clio-tools-") as temporary:
            log = Path(temporary) / "rpc.jsonl"
            cwd = args.cwd if args.cwd is not None else Path.cwd()
            c = (Client(cwd, log) if args.clio_executable is None else
                 Client(cwd, log, clio_executable=args.clio_executable))
            try:
                c.init()
                print(json.dumps(c.call("tools/list"), indent=1)[:8000])
            finally:
                c.close()
        return 0
    if any(value is None for value in (
        args.prompt, args.out, args.cwd, args.project_root, args.results_dir,
    )):
        ap.error("run requires a prompt, --out, --cwd, --project-root and --results-dir")
    try:
        paths = ResultPaths(args.project_root, args.results_dir)
        output = paths.output(args.out)
        cwd = paths.guard.project_root(args.cwd)
        if not cwd.is_relative_to(paths.project):
            raise ValueError("--cwd must be the explicit project or one of its non-source directories")
        env = paths.child_env(args.runs_root)
        prompt = paths.input(args.prompt)
    except (OSError, ValueError, RuntimeError) as exc:
        ap.error(str(exc))
    result = run(
        prompt.read_text(encoding="utf-8"), output, cwd=cwd, timeout=args.timeout,
        clio_executable=args.clio_executable, env=env,
    )
    print(json.dumps(result))
    return 0 if result["state"] == "done" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
