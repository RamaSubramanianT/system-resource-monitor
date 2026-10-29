# System Resource Monitor

A small, local web dashboard for live CPU, memory, disk, swap, and per-process usage. Data is read on the machine running the server and is not sent to a third party.

## Run

Requires Python 3.9+ and `psutil`:

```bash
python3 -m pip install psutil
python3 monitor.py
```

Open [http://127.0.0.1:8765](http://127.0.0.1:8765). Stop the server with `Ctrl+C`. To use another local port, set `MONITOR_PORT`, for example `MONITOR_PORT=9000 python3 monitor.py`.

## Allow access from your private network

Run the server on all network interfaces:

```bash
MONITOR_HOST=0.0.0.0 python3 monitor.py
```

Find this computer’s private IPv4 address (for example, with `hostname -I` on Linux), then open `http://YOUR_PRIVATE_IP:8765` from another device on the same trusted network. For example: `http://192.168.1.25:8765`. Allow inbound TCP port 8765 in the computer’s firewall if it blocks connections. Keep this on a trusted private network: the dashboard has no login, and anyone who can reach the port can view process information.

The default remains `127.0.0.1` for local-only access. You can also set a specific interface address with `MONITOR_HOST`, such as `MONITOR_HOST=192.168.1.25 python3 monitor.py`.

## Alerts

Set CPU and memory alert thresholds in the dashboard. The dashboard shows an alert after two consecutive readings over a threshold. Use **Enable alerts** to allow browser notifications; in-page alerts continue to work if notifications are denied. Thresholds are saved in this browser on this device.

## Notes

- CPU and memory values are system-wide. The process table shows per-process CPU and resident memory share.
- Disk usage reports the filesystem containing `/`.
- Some process names, users, or command lines may be unavailable to an unprivileged user.
- The server binds to `127.0.0.1`, so it is only available from this machine by default.


## Run as a system service (Linux with systemd)

The included `system-resource-monitor.service` unit runs the monitor after boot and restarts it if it exits. To install it system-wide, copy it to `/etc/systemd/system/`, then run `sudo systemctl daemon-reload` and `sudo systemctl enable --now system-resource-monitor`. Check it with `sudo systemctl status system-resource-monitor`; view logs with `sudo journalctl -u system-resource-monitor -f`. Stop it with `sudo systemctl disable --now system-resource-monitor`. It listens on all interfaces at port 8765, so only use it on a trusted private network.


## Process actions

- **Keep** pins a process at the top of the current process list, even when sorting by CPU or memory. Pins are stored in this browser and tied to both PID and start time, so a later process that reuses the PID is not mistaken for the pinned process.
- **Download .md** saves a report containing the selected process, its parent, direct children, resource readings, executable and working directory when available. Review the report before sharing it with an AI: command lines and paths may include secrets or personal information.
- **Terminate** asks the operating system to gracefully terminate that process after confirmation. It does not force-kill it; unsaved work may still be lost, and the OS may deny permission. The monitor protects its own process and checks the process start time to avoid acting on a reused PID.

When the monitor is exposed to your private network, other devices that can reach it can also request process termination. Use it only on a trusted network.


## Search

The process search matches text anywhere in process names, PIDs, parent PIDs, users, status, and command lines. It builds an inverted n-gram index once per incoming system snapshot; each query uses the shortest matching postings and verifies candidates, rather than scanning every process for each keystroke. Matching uses all detected processes, including those outside the top 12 display. Multiple words narrow results by requiring every word to appear. All matching rows show CPU and memory usage, with a combined usage summary above them.


## Understanding RAM usage

The **Where RAM is going** panel shows available memory, Linux file cache, kernel slab, and the summed resident set size (RSS) of visible processes. Linux uses otherwise-idle memory for caches, which can often be reclaimed when applications need it; available memory is a more useful headroom signal than the used percentage alone. These counters overlap and should not be added together. Summed process RSS can double-count shared pages and may omit processes whose details are inaccessible to the monitor user. The process table now defaults to sorting by memory.
