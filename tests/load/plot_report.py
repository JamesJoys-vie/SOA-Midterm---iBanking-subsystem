"""PNG version of the Locust report.html charts, drawn from the run's stats_stats_history.csv.

    python plot_report.py /reports/medium [/reports/stress ...]     -> <run>/report.png

Three panels like the HTML report: requests/s + failures/s, response time (median and p95, ms), user count.
"""
import csv
import os
import sys
from datetime import datetime
import matplotlib

matplotlib.use("Agg")  # no display in the container
import matplotlib.pyplot as plt  # noqa: E402


def _num(v: str) -> float | None:
    return None if v in ("", "N/A") else float(v)


def load(run_dir: str) -> dict[str, list]:
    cols = {"t": [], "users": [], "rps": [], "fails": [], "p50": [], "p95": []}
    with open(os.path.join(run_dir, "stats_stats_history.csv"), newline="") as f:
        for row in csv.DictReader(f):
            if row["Name"] != "Aggregated":
                continue
            cols["t"].append(datetime.fromtimestamp(int(row["Timestamp"])))
            cols["users"].append(int(row["User Count"]))
            cols["rps"].append(float(row["Requests/s"]))
            cols["fails"].append(float(row["Failures/s"]))
            cols["p50"].append(_num(row["50%"]))
            cols["p95"].append(_num(row["95%"]))
    return cols


def plot(run_dir: str) -> str:
    d = load(run_dir)
    t0 = d["t"][0]
    x = [(t - t0).total_seconds() for t in d["t"]]
    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(11, 9), sharex=True)
    fig.suptitle(f"Load test: {os.path.basename(os.path.normpath(run_dir))}")

    ax1.plot(x, d["rps"], color="tab:green", label="requests/s")
    ax1.plot(x, d["fails"], color="tab:red", label="failures/s")
    ax1.set_ylabel("per second")
    ax1.legend(loc="upper left")

    ax2.plot(x, d["p50"], color="tab:blue", label="median")
    ax2.plot(x, d["p95"], color="tab:orange", label="95th percentile")
    ax2.set_ylabel("response time (ms)")
    ax2.legend(loc="upper left")

    ax3.plot(x, d["users"], color="tab:purple")
    ax3.set_ylabel("users")
    ax3.set_xlabel("seconds since start")

    for ax in (ax1, ax2, ax3):
        ax.grid(alpha=0.3)
        ax.set_ylim(bottom=0)
    fig.tight_layout()
    out = os.path.join(run_dir, "report.png")
    fig.savefig(out, dpi=120)
    plt.close(fig)
    return out


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    for run in sys.argv[1:]:
        print("wrote", plot(run))
