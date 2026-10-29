#!/usr/bin/env python3
"""Local system resource monitor. Requires psutil (pip install psutil)."""
from __future__ import annotations

import json
import os
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import psutil

ROOT = Path(__file__).resolve().parent
HOST = os.environ.get("MONITOR_HOST", "127.0.0.1")
PORT = int(os.environ.get("MONITOR_PORT", "8765"))

# Prime per-process CPU counters before serving the first snapshot.
for _p in psutil.process_iter():
    try:
        _p.cpu_percent(None)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass


def snapshot() -> dict:
    vm = psutil.virtual_memory()
    swap = psutil.swap_memory()
    meminfo = {}
    if os.path.exists("/proc/meminfo"):
        try:
            with open("/proc/meminfo", encoding="ascii") as source:
                for line in source:
                    key, raw = line.split(":", 1)
                    parts = raw.split()
                    if parts:
                        meminfo[key] = int(parts[0]) * (1024 if len(parts) > 1 and parts[1] == "kB" else 1)
        except (OSError, ValueError):
            meminfo = {}
    try:
        disk = psutil.disk_usage(os.path.abspath(os.sep))
        disk_data = {"total": disk.total, "used": disk.used, "percent": disk.percent}
    except OSError:
        disk_data = {"total": 0, "used": 0, "percent": 0}

    processes = []
    for proc in psutil.process_iter(["pid", "name", "username", "status", "memory_info", "cmdline"]):
        try:
            info = proc.info
            mem = info.get("memory_info")
            processes.append({
                "pid": info.get("pid"),
                "create_time": proc.create_time(),
                "ppid": proc.ppid(),
                "killable": proc.pid not in (1, os.getpid()),
                "name": info.get("name") or "(unknown)",
                "user": info.get("username") or "",
                "status": info.get("status") or "",
                "cpu": round(proc.cpu_percent(None), 1),
                "memory": round((mem.rss / vm.total) * 100, 2) if mem and vm.total else 0,
                "memory_bytes": mem.rss if mem else 0,
                "command": " ".join(info.get("cmdline") or [])[:240],
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    processes.sort(key=lambda p: (p["cpu"], p["memory"]), reverse=True)
    process_rss = sum(p["memory_bytes"] for p in processes)
    return {
        "host": socket.gethostname(),
        "platform": f"{psutil.LINUX and 'Linux' or os.name}",
        "cpu": {"percent": psutil.cpu_percent(None), "cores": psutil.cpu_count() or 1},
        "memory": {
            "total": vm.total, "used": vm.used, "available": vm.available, "percent": vm.percent,
            "free": vm.free,
            "cached": meminfo.get("Cached", getattr(vm, "cached", 0)),
            "buffers": meminfo.get("Buffers", getattr(vm, "buffers", 0)),
            "shared": meminfo.get("Shmem", getattr(vm, "shared", 0)),
            "slab": meminfo.get("Slab", getattr(vm, "slab", 0)),
            "slab_reclaimable": meminfo.get("SReclaimable", 0),
            "slab_unreclaimable": meminfo.get("SUnreclaim", 0),
            "anonymous": meminfo.get("AnonPages", 0),
            "process_rss": process_rss,
        },
        "swap": {"total": swap.total, "used": swap.used, "percent": swap.percent},
        "disk": disk_data,
        "processes": processes,
    }


def process_details(pid: int) -> dict:
    """Return a process and its immediate parent and children for a report."""
    target = psutil.Process(pid)

    def describe(proc: psutil.Process) -> dict:
        try:
            with proc.oneshot():
                mem = proc.memory_info()
                try:
                    cmd = proc.cmdline()
                except psutil.AccessDenied:
                    cmd = []
                try:
                    exe = proc.exe()
                except psutil.AccessDenied:
                    exe = ""
                try:
                    cwd = proc.cwd()
                except psutil.AccessDenied:
                    cwd = ""
                try:
                    username = proc.username()
                except psutil.AccessDenied:
                    username = ""
                return {
                    "pid": proc.pid,
                    "ppid": proc.ppid(),
                    "name": proc.name(),
                    "username": username,
                    "status": proc.status(),
                    "create_time": proc.create_time(),
                    "cpu_percent": proc.cpu_percent(None),
                    "memory_bytes": mem.rss,
                    "memory_percent": proc.memory_percent(),
                    "executable": exe,
                    "working_directory": cwd,
                    "command_line": cmd,
                }
        except psutil.AccessDenied:
            return {"pid": proc.pid, "unavailable": "Metadata access was denied."}
        except (psutil.NoSuchProcess, psutil.ZombieProcess):
            return {"pid": proc.pid, "unavailable": "Process exited while collecting metadata."}

    try:
        parent = target.parent()
        parent_data = describe(parent) if parent else None
    except (psutil.NoSuchProcess, psutil.ZombieProcess):
        parent_data = None
    try:
        children = [describe(child) for child in target.children(recursive=False)]
    except (psutil.NoSuchProcess, psutil.ZombieProcess):
        children = []
    return {"process": describe(target), "parent": parent_data, "children": children}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/stats":
            payload = json.dumps(snapshot()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if path.startswith("/api/process/"):
            try:
                pid = int(path.rsplit("/", 1)[1])
                payload = json.dumps(process_details(pid)).encode()
            except (ValueError, psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                self.send_error(404, "Process is no longer available or metadata access was denied")
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if path in ("/", "/index.html"):
            payload = (ROOT / "index.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        self.send_error(404)

    def do_POST(self):
        if urlparse(self.path).path != "/api/terminate":
            self.send_error(404)
            return
        if self.headers.get_content_type() != "application/json":
            self.send_error(415, "Expected application/json")
            return
        try:
            length = min(int(self.headers.get("Content-Length", "0")), 4096)
            body = json.loads(self.rfile.read(length))
            pid = int(body["pid"])
            expected_created = float(body["create_time"])
        except (ValueError, TypeError, KeyError, json.JSONDecodeError):
            self.send_error(400, "Invalid process identity")
            return
        try:
            proc = psutil.Process(pid)
            if pid in (0, 1, os.getpid()) or abs(proc.create_time() - expected_created) > 0.01:
                self.send_error(409, "Process identity changed or is protected")
                return
            proc.terminate()
            payload = json.dumps({"ok": True, "message": f"Terminate requested for PID {pid}."}).encode()
        except psutil.NoSuchProcess:
            self.send_error(404, "Process has already exited")
            return
        except psutil.AccessDenied:
            self.send_error(403, "Permission denied; this monitor cannot terminate that process")
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt, *args):
        print(f"[{self.log_date_time_string()}] {fmt % args}")


def main():
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"System Resource Monitor listening on {HOST}:{PORT}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping monitor…")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
