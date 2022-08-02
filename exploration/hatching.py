#  Copyright (c) 2022, Manfred Moitzi
#  License: MIT License
from typing import List
from pathlib import Path
import time

import ezdxf
from ezdxf.math import Vec2
from ezdxf.render import forms, hatching

CWD = Path("~/Desktop/Outbox").expanduser()
if not CWD.exists():
    CWD = Path(".")


def polygon_hatching(filename: str):
    doc = ezdxf.new()
    setup(doc)
    msp = doc.modelspace()
    polygon = Vec2.list(
        forms.gear(16, top_width=1, bottom_width=3, height=2, outside_radius=10)
    )
    hole = list(forms.circle(16, radius=4))
    hole1 = Vec2.list(forms.translate(hole, (-2, -2)))
    hole2 = Vec2.list(forms.translate(hole, (2, 2)))
    baseline = hatching.HatchBaseLine(
        Vec2(), direction=Vec2(1, 1), offset=Vec2(-1, 1)
    )
    render_hatch(msp, baseline, polygon, [hole1, hole2])
    doc.saveas(CWD / filename)


def draw(d: str) -> List[Vec2]:
    point = Vec2()
    points = [point]
    for cmd in d.split(","):
        cmd = cmd.strip()
        if cmd[0] == "h":
            point += Vec2(float(cmd[1:]), 0)
        elif cmd[0] == "v":
            point += Vec2(0, float(cmd[1:]))
        elif cmd[0] == "q":
            direction = cmd[1]
            l = float(cmd[2:])
            if direction == "1":
                point += Vec2(l, l)
            elif direction == "2":
                point += Vec2(-l, l)
            elif direction == "3":
                point += Vec2(-l, -l)
            else:
                point += Vec2(l, -l)
        points.append(point)
    return points


SIZE = 0.1


def setup(doc):
    doc.layers.add("POLYGON", color=ezdxf.colors.BLUE)
    doc.layers.add("MARKERS", color=ezdxf.colors.GREEN)
    doc.layers.add("POINTS", color=ezdxf.colors.RED)
    doc.layers.add("HATCH", color=ezdxf.colors.YELLOW)
    marker = doc.blocks.new("MARKER")
    marker.add_line((-SIZE, -SIZE), (SIZE, SIZE))
    marker.add_line((-SIZE, SIZE), (SIZE, -SIZE))


def render_hatch(msp, baseline, polygon, holes=None, offset=Vec2()):
    polygons = [Vec2.list(forms.translate(polygon, offset))]
    if holes:
        for hole in holes:
            polygons.append(Vec2.list(forms.translate(hole, offset)))
    for polygon in polygons:
        msp.add_lwpolyline(
            polygon,
            close=True,
            dxfattribs={"layer": "POLYGON"},
        )
        for p in polygon:
            msp.add_circle(
                p,
                radius=SIZE,
                dxfattribs={"layer": "POINTS"},
            )
    for line in hatching.hatch_polygons(baseline, polygons):
        msp.add_line(
            line.start,
            line.end,
            dxfattribs={"layer": "HATCH"},
        )
        msp.add_blockref("MARKER", line.start, dxfattribs={"layer": "MARKERS"})
        msp.add_blockref("MARKER", line.end, dxfattribs={"layer": "MARKERS"})


def collinear_hatching(filename: str):
    doc = ezdxf.new()
    msp = doc.modelspace()
    setup(doc)
    polygons = [
        forms.turtle("10 l 10 l 10"),
        forms.turtle("2 l 2 r 2 r 2 l 6 " "l 10 l 2 l 2 r 2 r 2 l 6"),
        forms.turtle(
            "2 l 2 r 2 l 2 r 2 r 4 l 4 l 10 l 2 l 2 r 2 l 2 r 2 r 4 l 4"
        ),
        forms.turtle(
            "2 r 2 l 2 r 2 l 2 l 4 r 4 l 10 l 2 r 2 l 2 r 2 l 2 l 4 r 4"
        ),
        forms.turtle(
            "2 l 2 r 2 r 2 l 2 l 4 r 2 r 4 l 2 l 10 l 2 r 2 l 2 l 2 r 2 r 4 l 2 l 4 r 2"
        ),
        forms.turtle("3 @2,2 @2,-2 3 l 10 l @-2,-2 @-2,2 2 @-2,-2 @-2,2"),
        forms.turtle(
            "3 @1,1 @1,1 @1,-1 @1,-1 3 l 10 l @-1,-1 @-1,-1 @-1,1 @-1,1 2 "
            "@-1,-1 @-1,-1 @-1,1 @-1,1"
        ),
    ]
    for index, polygon in enumerate(polygons):
        baseline = hatching.HatchBaseLine(
            Vec2(), direction=Vec2(1, 0), offset=Vec2(0, 1)
        )
        render_hatch(msp, baseline, polygon, offset=Vec2(12 * index, 0))
    doc.saveas(CWD / filename)


def explode_hatch_pattern(filename: str):
    doc = ezdxf.readfile(CWD / filename)
    msp = doc.modelspace()
    attribs = {"layer": "EXPLODE", "color": ezdxf.colors.RED}
    t0 = time.perf_counter()
    for hatch in msp.query("HATCH"):
        for start, end in hatching.explode_hatch_pattern(hatch, 1):  # type: ignore
            msp.add_line(start, end, attribs)
    t1 = time.perf_counter()
    print(f"Exploding hatch pattern took: {t1-t0:.3}s")
    doc.saveas(CWD / filename.replace(".dxf", ".explode.dxf"))


if __name__ == "__main__":
    # polygon_hatching("polygon_hatching.dxf")
    collinear_hatching("collinear_hatching.dxf")
    # explode_hatch_pattern("hatch_pattern_iso.dxf")
