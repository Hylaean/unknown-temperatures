#!/usr/bin/env python3
"""Unknown Temperatures: every day since 1940, drawn as a stack of pulses.

One line per year, oldest at the top, each line hiding the ones behind it, in the
manner of the stacked pulsar plot on the sleeve of Joy Division's "Unknown Pleasures".

  resample()  daily temperatures -> one coarse profile per year: how many of its
              days fell in each temperature bin. Nothing is smoothed, so the bell
              curves of a density plot become jagged pulses.
  render()    the profiles -> white lines on black, as PNG and SVG.

    python unknown_temperatures.py              # fetch, resample, render
    python unknown_temperatures.py --bin 0.08   # coarser pulses
    python unknown_temperatures.py --refresh    # download the latest days first

Data: ERA5 daily global-mean 2 m air temperature, Copernicus Climate Change
Service / ECMWF.
"""

import argparse
import csv
import urllib.request
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.font_manager import FontProperties, fontManager
from matplotlib.patches import PathPatch
from matplotlib.path import Path as MplPath
from matplotlib.textpath import TextPath, text_to_path
from matplotlib.transforms import Affine2D

HERE = Path(__file__).resolve().parent
SOURCE = (
    "https://sites.ecmwf.int/data/climatepulse/data/series/"
    "era5_daily_series_2t_global.csv"
)
DAILY = HERE / "data" / "era5_daily_series_2t_global.csv"
OUT = HERE / "unknown_temperatures"

# The source gives anomalies against 1991-2020, which C3S puts 0.88 degC above
# the 1850-1900 average.
PREINDUSTRIAL = 0.88

TITLE = "UNKNOWN TEMPERATURES"
# The title is set in the first of these that is installed.
FONT = ["Inter", "Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"]
INK, PAPER = "#ffffff", "#000000"

# Layout, in pixels of the 1080 x 1350 canvas (--scale multiplies all of it).
WIDTH, HEIGHT = 1080, 1350
LINE_GAP = 10  # from one year's baseline to the next
LINE_LENGTH = 670
LINE_WIDTH = 1.3
PEAK = 10  # height of the tallest pulse, in line gaps
MARGIN = 0.5  # degC of flat line beyond the coldest and the warmest day
TITLE_SIZE = 26
TITLE_DROP = 70  # from the last line down to the title's baseline
POINTS = 72 / 100  # per canvas pixel


def load_daily(path=DAILY, refresh=False):
    """Every day's year and temperature above 1850-1900 (degC), and the last date."""
    if refresh or not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        part = path.with_suffix(".part")
        urllib.request.urlretrieve(SOURCE, part)
        part.replace(path)
    with open(path, newline="") as f:
        rows = list(csv.DictReader(line for line in f if not line.startswith("#")))
    years = np.array([int(r["date"][:4]) for r in rows])
    anomaly = np.array([float(r["ano_91-20"]) for r in rows]) + PREINDUSTRIAL
    return years, anomaly, rows[-1]["date"]


def resample(years, anomaly, bin_width):
    """Count each year's days in temperature bins `bin_width` degC wide.

    The bins are the same for every year. Returns the years, the bin centres (degC)
    and counts[year, bin].
    """
    # Rounding first puts a day that sits exactly on a bin edge in the bin above,
    # whatever the floating-point error.
    k = np.floor(np.round(anomaly / bin_width, 6)).astype(int)
    labels, row = np.unique(years, return_inverse=True)
    counts = np.zeros((len(labels), k.max() - k.min() + 1), dtype=int)
    np.add.at(counts, (row, k - k.min()), 1)
    centres = (np.arange(k.min(), k.max() + 1) + 0.5) * bin_width
    return labels, centres, counts


def save_profiles(path, labels, centres, counts):
    """Write the resampled data: days per year (rows) and bin centre (columns)."""
    with open(path, "w", newline="") as f:
        out = csv.writer(f)
        out.writerow(["year", *(f"{c:+.3f}" for c in centres)])
        out.writerows([year, *row] for year, row in zip(labels, counts))


def title_outline(text, size, width):
    """Outlines of `text`, letter-spaced so that its ink spans x = 0 to `width`."""
    installed = {font.name for font in fontManager.ttflist}
    family = next(name for name in FONT if name in installed)
    prop = FontProperties(family=family, weight="light", size=size)
    measure = text_to_path.get_text_width_height_descent
    advance = [measure(ch, prop, ismath=False)[0] for ch in text]
    glyph = {ch: TextPath((0, 0), ch, prop=prop) for ch in set(text) - {" "}}
    start, end = glyph[text[0]].get_extents().x0, glyph[text[-1]].get_extents().x1
    gap = (width - sum(advance[:-1]) - end + start) / (len(text) - 1)
    pen = np.cumsum([0, *advance[:-1]]) + gap * np.arange(len(text)) - start
    shifted = [
        glyph[ch].transformed(Affine2D().translate(x, 0))
        for ch, x in zip(text, pen)
        if ch in glyph
    ]
    return MplPath.make_compound_path(*shifted)


def render(centres, counts, out, scale=1):
    """Draw one line per row of `counts`: first row at the top, last row in front."""
    n = len(counts)
    step = centres[1] - centres[0]
    # Heights are shares of each year's days, so an unfinished year compares.
    share = counts / counts.sum(axis=1, keepdims=True)
    pulse = np.pad(share / share.max() * PEAK * LINE_GAP, ((0, 0), (2, 2)))

    # Each line reaches zero one bin outside the data, then runs flat for MARGIN.
    lo, hi = centres[0] - step - MARGIN, centres[-1] + step + MARGIN
    x = np.r_[lo, centres[0] - step, centres, centres[-1] + step, hi]
    left = (WIDTH - LINE_LENGTH) / 2
    x = left + (x - lo) / (hi - lo) * LINE_LENGTH

    # Centre the drawing between its highest peak and the title. Baselines sit on
    # half pixels, which keeps the flat lines crisp.
    rise = (np.arange(n)[::-1] * LINE_GAP + pulse.max(axis=1)).max()
    bottom = round((HEIGHT - rise - TITLE_DROP) / 2 + TITLE_DROP) + 0.5

    fig = plt.figure(
        figsize=(WIDTH / 100, HEIGHT / 100), dpi=100 * scale, facecolor=PAPER
    )
    ax = fig.add_axes((0, 0, 1, 1))  # one unit is one canvas pixel
    ax.set(xlim=(0, WIDTH), ylim=(0, HEIGHT))
    ax.axis("off")
    stroke = {
        "color": INK,
        "linewidth": LINE_WIDTH * POINTS,
        "solid_joinstyle": "round",
        "solid_capstyle": "butt",
    }
    for i, y in enumerate(pulse):
        base = bottom + (n - 1 - i) * LINE_GAP
        ax.fill_between(x, base, base + y, color=PAPER, linewidth=0, zorder=i)
        ax.plot(x, base + y, zorder=i + 0.5, **stroke)

    title = title_outline(TITLE, TITLE_SIZE, LINE_LENGTH)
    title.vertices += (left, bottom - TITLE_DROP)
    ax.add_patch(PathPatch(title, facecolor=INK, linewidth=0))

    for suffix in (".png", ".svg"):
        fig.savefig(f"{out}{suffix}")
    plt.close(fig)


def main():
    p = argparse.ArgumentParser(
        description=__doc__.split("\n")[0],
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--bin", type=float, default=0.05, help="bin width in degC")
    p.add_argument("--scale", type=int, default=1, help="pixel multiplier")
    p.add_argument("--refresh", action="store_true", help="download the series again")
    p.add_argument("--out", default=OUT, help="output path without extension")
    args = p.parse_args()

    years, anomaly, last_day = load_daily(refresh=args.refresh)
    labels, centres, counts = resample(years, anomaly, args.bin)
    save_profiles(f"{args.out}.csv", labels, centres, counts)
    render(centres, counts, args.out, args.scale)
    n_years, n_bins = counts.shape
    print(f"{len(anomaly)} days to {last_day}: {n_years} years x {n_bins} bins")
    print(f"wrote {args.out}.png, .svg and .csv")


if __name__ == "__main__":
    main()
