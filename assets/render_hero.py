"""Render the Model Finder README hero plate ("Quiet Instrument", see DESIGN.md), light and dark editions.

Usage: MF_FONTS=/path/to/fonts python3 assets/render_hero.py assets   (needs Pillow; not used at runtime)
"""
from __future__ import annotations

import os
import random
import sys
from pathlib import Path
from typing import Dict, List, Tuple

from PIL import Image, ImageDraw, ImageFont

# Instrument Serif and Geist Mono (SIL OFL). Point MF_FONTS at a folder containing the .ttf files.
FONTS = Path(os.environ.get("MF_FONTS", "fonts"))
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
W, H, S = 2400, 900, 3  # final size and supersampling factor

PALETTES: Dict[str, Dict[str, Tuple[int, int, int]]] = {
    "light": {"paper": (243, 240, 232), "ink": (28, 27, 25), "graphite": (138, 134, 125),
              "faint": (214, 209, 198), "accent": (205, 70, 42)},
    "dark": {"paper": (20, 20, 18), "ink": (236, 231, 220), "graphite": (141, 136, 126),
             "faint": (52, 51, 47), "accent": (226, 92, 60)},
}

COLS, ROWS, THRESHOLD = 16, 10, 0.9
PASSES = [2, 3, 3, 4, 6, 7, 8, 9, 10, 10, 10, 10, 10, 10, 10, 10]  # pass count per candidate, cost rising left to right
CHOSEN = next(i for i, p in enumerate(PASSES) if p / ROWS >= THRESHOLD)
FALLBACK = next(i for i, p in enumerate(PASSES) if i > CHOSEN and p == ROWS)

# geometry (final-pixel units)
M = 120
FX0, FX1 = 1080, 2240            # field x range (column centres)
FY0 = 250                        # first row centre
DY = 40                          # row step
DX = (FX1 - FX0) / (COLS - 1)
R_DOT = 8.5
AXIS_Y = FY0 + DY * (ROWS - 1) + 48
BAR_Y = AXIS_Y + 112             # baseline of the pass-rate bars
BAR_H = 56


def font(name: str, size: float) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / name), int(size * S))


def fail_rows() -> List[set]:
    rng = random.Random(1308)
    out = []
    for p in PASSES:
        out.append(set(rng.sample(range(ROWS), ROWS - p)))
    return out


class Plate:
    def __init__(self, palette: Dict[str, Tuple[int, int, int]]):
        self.c = palette
        self.img = Image.new("RGB", (W * S, H * S), palette["paper"])
        self.d = ImageDraw.Draw(self.img)
        self.boxes: List[Tuple[str, Tuple[float, float, float, float]]] = []

    # primitives in final-pixel coordinates
    def line(self, x0, y0, x1, y1, color, w=1.0):
        self.d.line([(x0 * S, y0 * S), (x1 * S, y1 * S)], fill=self.c[color], width=max(1, round(w * S)))

    def dashed(self, x0, y, x1, color, dash=6, gap=6, w=1.0):
        x = x0
        while x < x1:
            self.line(x, y, min(x + dash, x1), y, color, w)
            x += dash + gap

    def dot(self, x, y, r, color):
        self.d.ellipse([(x - r) * S, (y - r) * S, (x + r) * S, (y + r) * S], fill=self.c[color])

    def ring(self, x, y, r, color, w=1.6):
        self.d.ellipse([(x - r) * S, (y - r) * S, (x + r) * S, (y + r) * S], outline=self.c[color], width=round(w * S))

    def text(self, x, y, s, f, color, anchor="ls", tracking=0.0, tag=None):
        """Draw text (optionally letter-spaced) and record its box for the overlap audit."""
        if tracking:
            widths = [f.getlength(ch) for ch in s]
            total = sum(widths) + tracking * S * (len(s) - 1)
            start = x * S - (total if anchor[0] == "r" else total / 2 if anchor[0] == "m" else 0)
            cx = start
            for ch, w in zip(s, widths):
                self.d.text((cx, y * S), ch, font=f, fill=self.c[color], anchor="l" + anchor[1])
                cx += w + tracking * S
            l, r = start, start + total
            _, t, _, b = self.d.textbbox((start, y * S), s, font=f, anchor="l" + anchor[1])
        else:
            self.d.text((x * S, y * S), s, font=f, fill=self.c[color], anchor=anchor)
            l, t, r, b = self.d.textbbox((x * S, y * S), s, font=f, anchor=anchor)
        self.boxes.append((tag or s, (l / S, t / S, r / S, b / S)))

    def audit(self) -> None:
        for name, (l, t, r, b) in self.boxes:
            assert l >= M - 8 and r <= W - M + 1 and t >= 60 and b <= H - 60, f"out of frame: {name} {(l, t, r, b)}"
        for i, (a, ba) in enumerate(self.boxes):
            for bn, bb in self.boxes[i + 1:]:
                if ba[0] < bb[2] and bb[0] < ba[2] and ba[1] < bb[3] and bb[1] < ba[3]:
                    raise AssertionError(f"overlap: {a!r} / {bn!r}")


def render(edition: str) -> Image.Image:
    p = Plate(PALETTES[edition])
    serif = font("InstrumentSerif-Regular.ttf", 176)
    serif_it = font("InstrumentSerif-Italic.ttf", 48)
    mono = font("GeistMono-Regular.ttf", 22)
    mono_s = font("GeistMono-Regular.ttf", 18)
    fails = fail_rows()

    # ---- left: title block -------------------------------------------------------------
    p.text(M, 132, "PLATE 01", mono, "graphite", tracking=3)
    p.text(M + 178, 132, "A FIELD INSTRUMENT FOR CHOOSING MODELS", mono, "graphite", tracking=3)
    p.text(M - 6, 352, "Model", serif, "ink")
    p.text(M - 6, 512, "Finder", serif, "ink")
    p.line(M, 590, M + 56, 590, "accent", 2.0)
    p.text(M, 662, "the cheapest model that passes your own tests", serif_it, "graphite")
    p.text(M, BAR_Y + 30, "AUDIT  ·  EVALUATE  ·  ROUTE  ·  SIZE", mono, "ink", tracking=3)

    # ---- right: the observation field ----------------------------------------------------
    for j in range(COLS):  # faint column guides
        x = FX0 + j * DX
        p.line(x, FY0 - 34, x, FY0 + DY * (ROWS - 1) + 22, "faint", 1.0)
    for i in range(ROWS):  # row labels
        p.text(FX0 - 36, FY0 + i * DY, f"e{i + 1:02d}", mono_s, "graphite", anchor="rm")
    for j in range(COLS):
        x = FX0 + j * DX
        for i in range(ROWS):
            y = FY0 + i * DY
            if i in fails[j]:
                p.ring(x, y, R_DOT - 0.8, "graphite" if j != CHOSEN else "accent", 1.6)
            else:
                p.dot(x, y, R_DOT, "accent" if j == CHOSEN else "ink")

    # chosen column: hairline from the axis to its plate label
    xc = FX0 + CHOSEN * DX
    p.line(xc, FY0 - 62, xc, FY0 - 34, "accent", 1.2)
    p.text(xc, FY0 - 76, "fig. 1  cheapest that passes", mono_s, "accent", anchor="ms", tracking=1)
    # cascade bracket to the fallback
    xf = FX0 + FALLBACK * DX
    yb = FY0 + DY * (ROWS - 1) + 34
    p.line(xc, yb - 6, xc, yb, "accent", 1.2)
    p.line(xf, yb - 6, xf, yb, "accent", 1.2)
    p.line(xc, yb, xf, yb, "accent", 1.2)

    # axis with major and minor ticks
    p.line(FX0 - DX / 2, AXIS_Y, FX1 + DX / 2, AXIS_Y, "ink", 1.2)
    for j in range(COLS):
        x = FX0 + j * DX
        p.line(x, AXIS_Y, x, AXIS_Y + 10, "ink", 1.2)
        if j < COLS - 1:
            for k in (1, 2, 3):
                xm = x + DX * k / 4
                p.line(xm, AXIS_Y, xm, AXIS_Y + 5, "graphite", 1.0)
    p.text(FX0 - DX / 2, AXIS_Y + 38, "CHEAPER", mono_s, "graphite", tracking=2)
    p.text(FX1 + DX / 2, AXIS_Y + 38, "COST PER PASSING ANSWER  →", mono_s, "graphite", anchor="rs", tracking=2)

    # pass-rate bars with the threshold
    for j, passes in enumerate(PASSES):
        x = FX0 + j * DX
        h = BAR_H * passes / ROWS
        color = "accent" if j == CHOSEN else "ink" if passes / ROWS >= THRESHOLD else "graphite"
        p.line(x, BAR_Y, x, BAR_Y - h, color, 4.0)
    yt = BAR_Y - BAR_H * THRESHOLD
    p.dashed(FX0 - DX / 2, yt, FX1 + DX / 2, "graphite", dash=5, gap=5, w=1.0)
    p.line(FX0 - DX / 2, BAR_Y, FX1 + DX / 2, BAR_Y, "faint", 1.0)
    p.text(FX1 + DX / 2, BAR_Y + 30, f"PASS RATE  ·  THRESHOLD {THRESHOLD:.1f}  ·  n = {COLS * ROWS}", mono_s,
           "graphite", anchor="rs", tracking=2)

    p.audit()
    return p.img.resize((W, H), Image.LANCZOS)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for ed in ("light", "dark"):
        render(ed).save(OUT / f"readme-hero-{ed}.png", optimize=True)
        print("wrote", OUT / f"readme-hero-{ed}.png")
