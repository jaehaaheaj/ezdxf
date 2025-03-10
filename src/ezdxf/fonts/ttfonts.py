#  Copyright (c) 2023, Manfred Moitzi
#  License: MIT License
from __future__ import annotations
from typing import Any, no_type_check
from fontTools.pens.basePen import BasePen
from fontTools.ttLib import TTFont

import ezdxf.path
from ezdxf.math import Matrix44, UVec, BoundingBox2d
from .font_manager import FontManager
from .font_measurements import FontMeasurements

UNICODE_WHITE_SQUARE = 9633  # U+25A1
UNICODE_REPLACEMENT_CHAR = 65533  # U+FFFD

font_manager = FontManager()


class PathPen(BasePen):
    def __init__(self, glyph_set) -> None:
        super().__init__(glyph_set)
        self._path = ezdxf.path.Path2d()

    @property
    def path(self) -> ezdxf.path.Path2d:
        return self._path

    def _moveTo(self, pt: UVec) -> None:
        self._path.move_to(pt)

    def _lineTo(self, pt: UVec) -> None:
        self._path.line_to(pt)

    def _curveToOne(self, pt1: UVec, pt2: UVec, pt3: UVec) -> None:
        self._path.curve4_to(pt3, pt1, pt2)

    def _qCurveToOne(self, pt1: UVec, pt2: UVec) -> None:
        self._path.curve3_to(pt2, pt1)

    def _closePath(self) -> None:
        self._path.close_sub_path()


class NoKerning:
    def get(self, c0: str, c1: str) -> float:
        return 0.0


class KerningTable(NoKerning):
    __slots__ = ("_cmap", "_kern_table")

    def __init__(self, font: TTFont, cmap, fmt: int = 0):
        self._cmap = cmap
        self._kern_table = font["kern"].getkern(fmt)

    def get(self, c0: str, c1: str) -> float:
        try:
            return self._kern_table[(self._cmap[ord(c0)], self._cmap[ord(c1)])]
        except (KeyError, TypeError):
            return 0.0


def get_fontname(font: TTFont) -> str:
    names = font["name"].names
    for record in names:
        if record.nameID == 1:
            return record.string.decode(record.getEncoding())
    return "unknown"


class TTFontRenderer:
    def __init__(self, font: TTFont, kerning=False):
        self._glyph_path_cache: dict[str, ezdxf.path.Path2d] = dict()
        self._generic_glyph_cache: dict[str, Any] = dict()
        self._glyph_width_cache: dict[str, float] = dict()
        self.font = font
        self.cmap = self.font.getBestCmap()
        self.glyph_set = self.font.getGlyphSet()
        self.kerning = NoKerning()
        if kerning:
            try:
                self.kerning = KerningTable(self.font, self.cmap)
            except KeyError:  # kerning table does not exist
                pass
        self.undefined_generic_glyph = self.glyph_set[".notdef"]
        self.font_measurements = self._get_font_measurements()

    @property
    def font_name(self) -> str:
        return get_fontname(self.font)

    @no_type_check
    def _get_font_measurements(self) -> FontMeasurements:
        bbox = BoundingBox2d(self.get_glyph_path("x").control_vertices())
        baseline = bbox.extmin.y
        x_height = bbox.extmax.y - baseline
        bbox = BoundingBox2d(self.get_glyph_path("A").control_vertices())
        cap_height = bbox.extmax.y - baseline
        bbox = BoundingBox2d(self.get_glyph_path("p").control_vertices())
        descender_height = baseline - bbox.extmin.y
        return FontMeasurements(
            baseline=baseline,
            cap_height=cap_height,
            x_height=x_height,
            descender_height=descender_height,
        )

    def get_generic_glyph(self, char: str):
        try:
            return self._generic_glyph_cache[char]
        except KeyError:
            pass
        try:
            generic_glyph = self.glyph_set[self.cmap[ord(char)]]
        except KeyError:
            generic_glyph = self.undefined_generic_glyph
        self._generic_glyph_cache[char] = generic_glyph
        return generic_glyph

    def get_glyph_path(self, char: str) -> ezdxf.path.Path2d:
        """Returns the raw glyph path, without any scaling applied."""
        try:
            return self._glyph_path_cache[char]
        except KeyError:
            pass
        pen = PathPen(self.glyph_set)
        self.get_generic_glyph(char).draw(pen)
        glyph_path = pen.path
        self._glyph_path_cache[char] = glyph_path
        return glyph_path

    def get_glyph_width(self, char: str) -> float:
        """Returns the raw glyph width, without any scaling applied."""
        try:
            return self._glyph_width_cache[char]
        except KeyError:
            pass
        width = 0.0
        try:
            width = self.get_generic_glyph(char).width
        except KeyError:
            pass
        self._glyph_width_cache[char] = width
        return width

    def get_text_path(self, s: str, cap_height: float = 1.0) -> ezdxf.path.Path2d:
        """Returns the concatenated glyph paths of string s, scaled to cap height."""
        text_path = ezdxf.path.Path2d()
        x_offset: float = 0
        requires_kerning = isinstance(self.kerning, KerningTable)
        resize_factor = self.get_scaling_factor(cap_height)
        # set scaling factor:
        m = Matrix44.scale(resize_factor, resize_factor, 1.0)
        # set vertical offset:
        m[3, 1] = -self.font_measurements.baseline * resize_factor
        prev_char = ""
        for char in s:
            if requires_kerning:
                x_offset += self.kerning.get(prev_char, char) * resize_factor
            # set horizontal offset:
            m[3, 0] = x_offset
            glyph_path = self.get_glyph_path(char).transform(m)
            if x_offset == 0:
                text_path = glyph_path
            elif len(glyph_path):
                text_path.extend_multi_path(glyph_path)
            x_offset += self.get_glyph_width(char) * resize_factor
            prev_char = char
        return text_path

    def get_scaling_factor(self, cap_height: float) -> float:
        return 1.0 / self.font_measurements.cap_height * cap_height

    def _get_text_length_with_kerning(self, s: str, cap_height: float = 1.0) -> float:
        length = 0.0
        c0 = ""
        kern = self.kerning.get
        width = self.get_glyph_width
        for c1 in s:
            length += kern(c0, c1) + width(c1)
            c0 = c1
        return length * self.get_scaling_factor(cap_height)

    def get_text_length(self, s: str, cap_height: float = 1.0) -> float:
        if isinstance(self.kerning, KerningTable):
            return self._get_text_length_with_kerning(s, cap_height)
        width = self.get_glyph_width
        return sum(width(c) for c in s) * self.get_scaling_factor(cap_height)
