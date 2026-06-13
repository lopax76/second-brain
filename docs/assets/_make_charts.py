"""Generate the README charts (PNG) from the measured experiment data. Run once.

Data sources: the three cold-chat runs (NIENTE / ADESSO / DOPO) and the `secondbrain assess`
measurement on a real multi-repo project (~1,684 indexed files). Token = bytes/4 heuristic.
"""

from __future__ import annotations

import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

OUT = os.path.dirname(os.path.abspath(__file__))

# Palette (close to Second Brain node colors)
INK = "#0f172a"
DIM = "#64748b"
GRID = "#e2e8f0"
MANUAL = "#94a3b8"
SB = "#2563eb"
GOOD = "#16a34a"
BAD = "#dc2626"

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "font.size": 11,
    "axes.edgecolor": DIM,
    "axes.labelcolor": INK,
    "text.color": INK,
    "xtick.color": INK,
    "ytick.color": DIM,
    "figure.dpi": 130,
})


def _bar_labels(ax, bars, fmt):
    for b in bars:
        h = b.get_height()
        ax.annotate(fmt(h), (b.get_x() + b.get_width() / 2, h),
                    ha="center", va="bottom", fontsize=10, fontweight="bold", color=INK,
                    xytext=(0, 3), textcoords="offset points")


def chart_tokens():
    fig, ax = plt.subplots(figsize=(7.2, 4.0))
    labels = ["Read every\nfile", "Read the\ndocs", "Manual cold\nexploration", "Second Brain\ndigest"]
    vals = [26_752_514, 4_092_482, 100_000, 250]
    colors = [MANUAL, MANUAL, MANUAL, SB]
    bars = ax.bar(labels, vals, color=colors, width=0.62)
    ax.set_yscale("log")
    ax.set_ylim(100, 1e8)
    ax.set_ylabel("Tokens to orient an assistant (log scale)")
    ax.set_title("Cost to orient on a ~1,684-file project, every session", fontweight="bold")
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{int(v):,}"))
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    _bar_labels(ax, bars, lambda h: f"~{int(h):,}")
    ax.annotate("~400x less than the docs\n~100,000x less than reading everything",
                (3, 250), xytext=(2.1, 9000), fontsize=9.5, color=SB, fontweight="bold",
                ha="center", arrowprops=dict(arrowstyle="->", color=SB, lw=1.4))
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "chart-tokens.png"))
    plt.close(fig)


def chart_time():
    fig, ax = plt.subplots(figsize=(7.2, 3.6))
    labels = ["NIENTE\n(manual)", "ADESSO\n(manual)", "DOPO\n(Second Brain)", "SB index\nbuild (once)"]
    vals = [8.5, 9.0, 3.5, 0.02]
    colors = [MANUAL, MANUAL, SB, "#93c5fd"]
    bars = ax.bar(labels, vals, color=colors, width=0.6)
    ax.set_ylabel("Minutes")
    ax.set_title("Time to answer the same 4 questions", fontweight="bold")
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    _bar_labels(ax, bars, lambda h: f"{h:g} min" if h >= 0.1 else "~1.3 s")
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "chart-time.png"))
    plt.close(fig)


def chart_accuracy():
    fig, ax = plt.subplots(figsize=(7.2, 3.8))
    labels = ["NIENTE\n(manual)", "ADESSO\n(manual)", "DOPO\n(Second Brain)"]
    vals = [112, 131, 117]
    colors = [BAD, BAD, GOOD]
    bars = ax.bar(labels, vals, color=colors, width=0.55)
    ax.axhline(117, color=INK, linestyle="--", linewidth=1.3,
               label="ground truth = 117 (exact, reproducible)")
    ax.legend(loc="upper right", frameon=False, fontsize=9.5)
    ax.set_ylabel("Decisions counted")
    ax.set_ylim(0, 155)
    ax.set_title("Accuracy: same project, same day, different answers", fontweight="bold")
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    _bar_labels(ax, bars, lambda h: f"{int(h)}")
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "chart-accuracy.png"))
    plt.close(fig)


def chart_memory():
    fig, ax = plt.subplots(figsize=(7.2, 3.8))
    sessions = list(range(1, 13))
    # Illustrative: fidelity of the mental/written project map as work spans many chats.
    without = [100, 92, 83, 78, 70, 63, 58, 52, 47, 43, 39, 36]
    withsb = [100, 100, 99, 100, 99, 100, 99, 100, 99, 100, 99, 100]
    ax.plot(sessions, without, marker="o", color=BAD, lw=2, label="Without Second Brain")
    ax.plot(sessions, withsb, marker="o", color=SB, lw=2, label="With Second Brain")
    ax.fill_between(sessions, without, withsb, color=SB, alpha=0.06)
    ax.set_xlabel("Sessions / chats over time")
    ax.set_ylabel("Project-map fidelity (%)")
    ax.set_ylim(0, 108)
    ax.set_title("Memory continuity across chats  (illustrative)", fontweight="bold")
    ax.grid(color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.legend(frameon=False, loc="lower left")
    ax.annotate("orphans & stale files pile up,\nlinks get lost between chats",
                (8, 52), xytext=(6.2, 24), fontsize=9, color=BAD,
                arrowprops=dict(arrowstyle="->", color=BAD, lw=1.2))
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "chart-memory.png"))
    plt.close(fig)


if __name__ == "__main__":
    chart_tokens()
    chart_time()
    chart_accuracy()
    chart_memory()
    print("charts written to", OUT)
