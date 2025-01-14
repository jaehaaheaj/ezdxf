#  Copyright (c) 2021-2023, Manfred Moitzi
#  License: MIT License
from __future__ import annotations
from typing import Optional, TYPE_CHECKING, cast
import abc
import enum
import logging
import sys
import pathlib

from ezdxf.math import Matrix44
from ezdxf import options
from .font_face import FontFace
from .font_manager import FontManager
from .font_measurements import FontMeasurements

if TYPE_CHECKING:
    from ezdxf.document import Drawing
    from ezdxf.entities import DXFEntity, Textstyle
    from ezdxf.path import Path2d
    from .ttfonts import TTFontRenderer

logger = logging.getLogger("ezdxf")
FONT_MANAGER_CACHE_FILE = "font_manager_cache.json"
CACHE_DIRECTORY = ".cache"
font_manager = FontManager()

SHX_FONTS = {
    # See examples in: CADKitSamples/Shapefont.dxf
    # Shape file structure is not documented, therefore replace this fonts by
    # true type fonts.
    # `None` is for: use the default font.
    #
    # All these replacement TTF fonts have a copyright remark:
    # "(c) Copyright 1996 by Autodesk Inc., All rights reserved"
    # and therefore can not be included in ezdxf or the associated repository!
    # You got them if you install any Autodesk product, like the free available
    # DWG/DXF viewer "TrueView" : https://www.autodesk.com/viewers
    "AMGDT": "amgdt___.ttf",  # Tolerance symbols
    "AMGDT.SHX": "amgdt___.ttf",
    "COMPLEX": "complex_.ttf",
    "COMPLEX.SHX": "complex_.ttf",
    "ISOCP": "isocp.ttf",
    "ISOCP.SHX": "isocp.ttf",
    "ITALIC": "italicc_.ttf",
    "ITALIC.SHX": "italicc_.ttf",
    "GOTHICG": "gothicg_.ttf",
    "GOTHICG.SHX": "gothicg_.ttf",
    "GREEKC": "greekc.ttf",
    "GREEKC.SHX": "greekc.ttf",
    "ROMANS": "romans__.ttf",
    "ROMANS.SHX": "romans__.ttf",
    "SCRIPTS": "scripts_.ttf",
    "SCRIPTS.SHX": "scripts_.ttf",
    "SCRIPTC": "scriptc_.ttf",
    "SCRIPTC.SHX": "scriptc_.ttf",
    "SIMPLEX": "simplex_.ttf",
    "SIMPLEX.SHX": "simplex_.ttf",
    "SYMATH": "symath__.ttf",
    "SYMATH.SHX": "symath__.ttf",
    "SYMAP": "symap___.ttf",
    "SYMAP.SHX": "symap___.ttf",
    "SYMETEO": "symeteo_.ttf",
    "SYMETEO.SHX": "symeteo_.ttf",
    "TXT": "txt_____.ttf",  # Default AutoCAD font
    "TXT.SHX": "txt_____.ttf",
}
TTF_TO_SHX = {v: k for k, v in SHX_FONTS.items() if k.endswith("SHX")}
DESCENDER_FACTOR = 0.333  # from TXT SHX font - just guessing
X_HEIGHT_FACTOR = 0.666  # from TXT SHX font - just guessing


def map_shx_to_ttf(font_name: str) -> str:
    """Map SHX font names to TTF file names. e.g. "TXT" -> "txt_____.ttf" """
    # Map SHX fonts to True Type Fonts:
    font_upper = font_name.upper()
    if font_upper in SHX_FONTS:
        font_name = SHX_FONTS[font_upper]
    return font_name


def is_shx_font_name(font_name: str) -> bool:
    name = font_name.upper()
    if name.endswith(".SHX"):
        return True
    if "." not in name:
        return True
    return False


def map_ttf_to_shx(ttf: str) -> Optional[str]:
    """Map TTF file names to SHX font names. e.g. "txt_____.ttf" -> "TXT" """
    return TTF_TO_SHX.get(ttf.lower())


def build_system_font_cache(**kwargs) -> None:
    """Builds or rebuilds the font manager cache. The font manager cache has a fixed
    location in the cache directory of the users home directory "~/.cache/ezdxf" or the
    directory specified by the environment variable "XDG_CACHE_HOME".
    """
    build_font_manager_cache(_get_font_manger_path())


def find_font_face(font_name: str) -> FontFace:
    """Get the font face definition by the font file name e.g. "Arial.ttf",
    returns the default font if `font_name` was not found.

    """
    return font_manager.get_font_face(font_name)


def get_font_face(font_name: str, map_shx=True) -> FontFace:
    """Get the font face definition by the font file name e.g. "Arial.ttf".

    This function translates a DXF font definition by the TTF font file name into a
    :class:`FontFace` object. Fonts which are not available on the current system gets
    a default font face.

    Args:
        font_name: raw font file name as stored in the
            :class:`~ezdxf.entities.Textstyle` entity
        map_shx: maps SHX font names to TTF replacement fonts,
            e.g. "TXT" -> "txt_____.ttf"

    """
    if not isinstance(font_name, str):
        raise TypeError("font_name has invalid type")
    if map_shx:
        font_name = map_shx_to_ttf(font_name)
    return find_font_face(font_name)


def get_font_measurements(font_name: str, map_shx=True) -> FontMeasurements:
    """Get cached font measurements by TTF file name e.g. "Arial.ttf".

    Args:
        font_name: raw font file name as stored in the
            :class:`~ezdxf.entities.Textstyle` entity
        map_shx: maps SHX font names to TTF replacement fonts,
            e.g. "TXT" -> "txt_____.ttf"

    """
    if map_shx:
        font_name = map_shx_to_ttf(font_name)
    elif is_shx_font_name(font_name):
        return FontMeasurements(
            baseline=0,
            cap_height=1,
            x_height=X_HEIGHT_FACTOR,
            descender_height=DESCENDER_FACTOR,
        )
    font = TrueTypeFont(font_name, cap_height=1)
    return font.measurements


def find_best_match(
    *,
    family: str = "sans-serif",
    style: str = "Regular",
    weight: int = 400,
    width: int = 5,
    italic: Optional[bool] = False,
) -> Optional[FontFace]:
    """Returns the :class:`FontFace` that matches the given properties best.

    Args:
        family: font family name e.g. "sans-serif", "Liberation Sans"
        style: font style e.g. "Regular", "Italic", "Bold"
        weight: weight in the range from 1-1000 (usWeightClass)
        width: width in the range from 1-9 (usWidthClass)
        italic: ``True``, ``False`` or ``None`` to ignore this flag

    """
    return font_manager.find_best_match(family, style, weight, width, italic)


def find_font_file_name(font_face: FontFace) -> str:
    """Returns the true type font file name without parent directories e.g. "Arial.ttf"."""
    return font_manager.find_font_name(font_face)


def load():
    """Load all cache files."""
    _load_font_manager()


def _get_font_manger_path():
    cache_path = options.xdg_path("XDG_CACHE_HOME", CACHE_DIRECTORY)
    return cache_path / FONT_MANAGER_CACHE_FILE


def _load_font_manager() -> None:
    if "pytest" in sys.modules:
        return  # do nothing: system under test (sut)

    fm_path = _get_font_manger_path()
    if fm_path.exists():
        try:
            font_manager.loads(fm_path.read_text())
            return
        except IOError as e:
            logger.info(f"Error loading cache file: {str(e)}")
    build_font_manager_cache(fm_path)


def build_sut_font_manager_cache(repo_font_path: pathlib.Path) -> None:
    """Load font manger cache for system under test (sut).

    Load the fonts included in the repository folder "./fonts" to guarantee the tests
    have the same fonts available on all systems.
    """
    if font_manager.has_font("DejaVuSans.ttf"):
        return
    font_manager.clear()
    cache_file = repo_font_path / "font_manager_cache.json"
    if cache_file.exists():
        try:
            font_manager.loads(cache_file.read_text())
            return
        except IOError as e:
            print(f"Error loading cache file: {str(e)}")
    font_manager.build([str(repo_font_path)])
    s = font_manager.dumps()
    try:
        cache_file.write_text(s)
    except IOError as e:
        print(f"Error writing cache file: {str(e)}")


def build_font_manager_cache(path: pathlib.Path) -> None:
    font_manager.build()
    s = font_manager.dumps()
    if not path.parent.exists():
        path.parent.mkdir(parents=True)
    try:
        path.write_text(s)
    except IOError as e:
        logger.info(f"Error writing cache file: {str(e)}")


class FontRenderType(enum.Enum):
    # render glyphs as filled paths: TTF, OTF
    OUTLINE = enum.auto()

    # render glyphs as line strokes: SHX, SHP
    STROKE = enum.auto


class AbstractFont:
    """The `ezdxf` font abstraction for text measurement and text path rendering."""

    font_render_type = FontRenderType.STROKE

    def __init__(self, measurements: FontMeasurements):
        self.measurements = measurements

    @abc.abstractmethod
    def text_width(self, text: str) -> float:
        pass

    @abc.abstractmethod
    def text_width_ex(
        self, text: str, cap_height: float, width_factor: float = 1.0
    ) -> float:
        pass

    @abc.abstractmethod
    def space_width(self) -> float:
        pass

    @abc.abstractmethod
    def text_path(self, text: str) -> Path2d:
        ...

    @abc.abstractmethod
    def text_path_ex(
        self, text: str, cap_height: float, width_factor: float = 1.0
    ) -> Path2d:
        ...


class TrueTypeFont(AbstractFont):
    """Represents a True type Font. Font measurement and glyph rendering is done by the
    `fontTools`package. The given cap height and width factor are the default values for
    measurements and glyph rendering. The extended methods can override these default
    values.

    """

    font_render_type = FontRenderType.OUTLINE
    _ttf_render_engines: dict[str, TTFontRenderer] = dict()

    def __init__(self, ttf: str, cap_height: float, width_factor: float = 1.0):
        self.engine = self._create_engine(ttf)
        self.cap_height = float(cap_height)
        self.width_factor = float(width_factor)
        measurements = self.engine.font_measurements
        scale_factor = self.engine.get_scaling_factor(self.cap_height)
        super().__init__(measurements.scale(scale_factor))
        self._space_width = (
            self.engine.get_text_length(" ", self.cap_height) * self.width_factor
        )
        self._matrix = Matrix44.scale(self.width_factor, 1.0, 1.0)

    def _create_engine(self, ttf: str) -> TTFontRenderer:
        from .ttfonts import TTFontRenderer

        key = pathlib.Path(ttf).name.lower()
        try:
            return self._ttf_render_engines[key]
        except KeyError:
            pass
        engine = TTFontRenderer(font_manager.get_ttf_font(ttf))
        self._ttf_render_engines[key] = engine
        return engine

    def text_width(self, text: str) -> float:
        """Returns the text width in drawing units for the given `text` string.
        Text rendering and width calculation is based on fontTools.
        """
        return self.text_width_ex(text, self.cap_height, self.width_factor)

    def text_width_ex(
        self, text: str, cap_height: float, width_factor: float = 1.0
    ) -> float:
        """Returns the text width in drawing units, bypasses the stored `cap_height` and
        `width_factor`.
        """
        if not text.strip():
            return 0
        return self.engine.get_text_length(text, cap_height) * width_factor

    def text_path(self, text: str) -> Path2d:
        """Returns the 2D text path for the given text."""
        p = self.engine.get_text_path(text, self.cap_height)
        return p if self.width_factor == 1.0 else p.transform(self._matrix)

    def text_path_ex(
        self, text: str, cap_height: float, width_factor: float = 1.0
    ) -> Path2d:
        """Returns the 2D text path for the given text, bypasses the stored `cap_height`
        and `width_factor`."""
        p = self.engine.get_text_path(text, cap_height)
        if width_factor == 1.0:
            return p
        return p.transform(Matrix44.scale(width_factor, 1.0, 1.0))

    def space_width(self) -> float:
        """Returns the width of a "space" char."""
        return self._space_width


class MonospaceFont(AbstractFont):
    """Represents a monospaced font where each letter has the same cap- and descender
    height and the same width. The given cap height and width factor are the default
    values for measurements and rendering. The extended methods can override these
    default values.

    This font exists only for generic text measurement in tests and does not render any
    glyphs!

    """

    font_render_type = FontRenderType.STROKE

    def __init__(
        self,
        cap_height: float,
        width_factor: float = 1.0,
        baseline: float = 0,
        descender_factor: float = DESCENDER_FACTOR,
        x_height_factor: float = X_HEIGHT_FACTOR,
    ):
        super().__init__(
            FontMeasurements(
                baseline=baseline,
                cap_height=cap_height,
                x_height=cap_height * x_height_factor,
                descender_height=cap_height * descender_factor,
            )
        )
        self._width_factor: float = abs(width_factor)
        self._space_width = self.measurements.cap_height * self._width_factor

    def text_width(self, text: str) -> float:
        """Returns the text width in drawing units for the given `text`."""
        return self.text_width_ex(
            text, self.measurements.cap_height, self._width_factor
        )

    def text_width_ex(
        self, text: str, cap_height: float, width_factor: float = 1.0
    ) -> float:
        """Returns the text width in drawing units, bypasses the stored `cap_height` and
        `width_factor`.
        """
        return len(text) * cap_height * width_factor

    def text_path(self, text: str) -> Path2d:
        """Returns the rectangle text width x cap height as :class:`~ezdxf.path.Path2d` instance."""
        return self.text_path_ex(text, self.measurements.cap_height, self._width_factor)

    def text_path_ex(
        self, text: str, cap_height: float, width_factor: float = 1.0
    ) -> Path2d:
        """Returns the rectangle text width x cap height as  :class:`~ezdxf.path.Path2d`
        instance, bypasses the stored `cap_height` and `width_factor`.
        """
        from ezdxf.path import Path2d

        text_width = self.text_width_ex(text, cap_height, width_factor)
        p = Path2d((0, 0))
        p.line_to((text_width, 0))
        p.line_to((text_width, cap_height))
        p.line_to((0, cap_height))
        p.close()
        return p

    def space_width(self) -> float:
        """Returns the width of a "space" char."""
        return self._space_width


def make_font(
    font_name: str, cap_height: float, width_factor: float = 1.0
) -> AbstractFont:
    """Factory function to create a font abstraction.

    Returns a :class:`TrueTypeFont` instance, SHX font support will be added in the
    future. The current implementation maps SHX fonts to equivalent TTF fonts.

    The special name "*monospace" returns the test font :class:`MonospaceFont`.

    Args:
        font_name: font file name as stored in the :class:`~ezdxf.entities.Textstyle`
            entity e.g. "OpenSans-Regular.ttf"
        cap_height: desired cap height in drawing units.
        width_factor: horizontal text stretch factor

    """
    if font_name == "*monospace":
        return MonospaceFont(cap_height, width_factor)
    return TrueTypeFont(font_name, cap_height, width_factor)


def get_entity_font_face(entity: DXFEntity, doc: Optional[Drawing] = None) -> FontFace:
    """Returns the :class:`FontFace` defined by the associated text style.
    Returns the default font face if the `entity` does not have or support
    the DXF attribute "style". Supports the extended font information stored in
    :class:`~ezdxf.entities.Textstyle` table entries.

    Pass a DXF document as argument `doc` to resolve text styles for virtual
    entities which are not assigned to a DXF document. The argument `doc`
    always overrides the DXF document to which the `entity` is assigned to.

    """
    if entity.doc and doc is None:
        doc = entity.doc
    if doc is None:
        return FontFace()

    style_name = ""
    # This works also for entities which do not support "style",
    # where style_name = entity.dxf.get("style") would fail.
    if entity.dxf.is_supported("style"):
        style_name = entity.dxf.style

    font_face = FontFace()
    if style_name:
        style = cast("Textstyle", doc.styles.get(style_name))
        family, italic, bold = style.get_extended_font_data()
        if family:
            text_style = "Italic" if italic else "Regular"
            text_weight = 700 if bold else 400
            font_face = FontFace(family=family, style=text_style, weight=text_weight)
        else:
            ttf = style.dxf.font
            if ttf:
                font_face = get_font_face(ttf)
    return font_face


_load_font_manager()
