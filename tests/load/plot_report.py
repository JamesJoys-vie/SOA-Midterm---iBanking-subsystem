"""Draw a Locust run's charts as <run>/report.png from its stats_stats_history.csv.

    python plot_report.py /reports/medium [/reports/stress ...]
"""
import csv
import os
import sys
from datetime import datetime
import matplotlib

matplotlib.use("Agg")  # no display in the container
import matplotlib.pyplot as plt  # noqa: E402


def _num(v: str) -> float | None:
    """CSV cell -> number; None for the empty / "N/A" cells Locust writes before the first response."""
    return None if v in ("", "N/A") else float(v)


def load(run_dir: str) -> dict[str, list]:
    """The whole-run ("Aggregated") rows of the history CSV, one list per column (one row per second)."""
    # t = sample time, users = active users, rps / fails = requests / failures per second, p50 / p95 = ms
    cols = {"t": [], "users": [], "rps": [], "fails": [], "p50": [], "p95": []}
    with open(os.path.join(run_dir, "stats_stats_history.csv"), newline="") as f:
        for row in csv.DictReader(f):
            if row["Name"] != "Aggregated":  # skip the per-endpoint rows
                continue
            cols["t"].append(datetime.fromtimestamp(int(row["Timestamp"])))
            cols["users"].append(int(row["User Count"]))
            cols["rps"].append(float(row["Requests/s"]))
            cols["fails"].append(float(row["Failures/s"]))
            cols["p50"].append(_num(row["50%"]))
            cols["p95"].append(_num(row["95%"]))
    return cols


def plot(run_dir: str) -> str:
    """Write report.png (throughput, response time, users over time) into run_dir; returns its path."""
    d = load(run_dir)
    t0 = d["t"][0]  # run start
    x = [(t - t0).total_seconds() for t in d["t"]]  # x axis: seconds since start
    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(11, 9), sharex=True)
    fig.suptitle(f"Load test: {os.path.basename(os.path.normpath(run_dir))}")  # title = run folder name

    # panel 1: throughput and failures
    ax1.plot(x, d["rps"], color="tab:green", label="requests/s")
    ax1.plot(x, d["fails"], color="tab:red", label="failures/s")
    ax1.set_ylabel("per second")
    ax1.legend(loc="upper left")

    # panel 2: response time
    ax2.plot(x, d["p50"], color="tab:blue", label="median")
    ax2.plot(x, d["p95"], color="tab:orange", label="95th percentile")
    ax2.set_ylabel("response time (ms)")
    ax2.legend(loc="upper left")

    # panel 3: active virtual users (ramp-up, steady load, stop)
    ax3.plot(x, d["users"], color="tab:purple")
    ax3.set_ylabel("users")
    ax3.set_xlabel("seconds since start")

    for ax in (ax1, ax2, ax3):
        ax.grid(alpha=0.3)
        ax.set_ylim(bottom=0)
    fig.tight_layout()
    out = os.path.join(run_dir, "report.png")
    fig.savefig(out, dpi=120)
    plt.close(fig)  # free the figure when plotting several runs
    return out


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    for run in sys.argv[1:]:
        print("wrote", plot(run))
