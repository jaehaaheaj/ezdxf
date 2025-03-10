#  Copyright (c) 2023, Manfred Moitzi
#  License: MIT License
from __future__ import annotations
from typing import Iterable, NamedTuple, Optional, Sequence
import os
import platform
import json

from pathlib import Path
from fontTools.ttLib import TTFont
from .font_face import FontFace

WINDOWS = "Windows"
LINUX = "Linux"
MACOS = "Darwin"


WIN_SYSTEM_ROOT = os.environ.get("SystemRoot", "C:/Windows")
WIN_FONT_DIRS = [
    # AutoCAD and BricsCAD do not support fonts installed in the user directory:
    "~/AppData/Local/Microsoft/Windows/Fonts",
    f"{WIN_SYSTEM_ROOT}/Fonts",
]
LINUX_FONT_DIRS = [
    "/usr/share/fonts",
    "/usr/local/share/fonts",
    "~/.fonts",
    "~/.local/share/fonts",
    "~/.local/share/texmf/fonts",
]
MACOS_FONT_DIRS = ["/Library/Fonts/"]
FONT_DIRECTORIES = {
    WINDOWS: WIN_FONT_DIRS,
    LINUX: LINUX_FONT_DIRS,
    MACOS: MACOS_FONT_DIRS,
}

DEFAULT_FONTS = [
    "Arial.ttf",
    "DejaVuSansCondensed.ttf",  # widths of glyphs is similar to Arial
    "DejaVuSans.ttf",
    "LiberationSans-Regular.ttf",
    "OpenSans-Regular.ttf",
]
CURRENT_CACHE_VERSION = 1


class CacheEntry(NamedTuple):
    file_path: Path  # full file path e.g. "C:\Windows\Fonts\DejaVuSans.ttf"
    font_face: FontFace


GENERIC_FONT_FAMILY = {
    "serif": "DejaVu Serif",
    "sans-serif": "DejaVu Sans",
    "monospace": "DejaVu Sans Mono",
}


class FontCache:
    def __init__(self) -> None:
        # cache key is the lowercase ttf font name without parent directories
        # e.g. "arial.ttf" for "C:\Windows\Fonts\Arial.ttf"
        self._cache: dict[str, CacheEntry] = dict()

    def __contains__(self, font_name: str) -> bool:
        return self.key(font_name) in self._cache

    def __getitem__(self, item: str) -> CacheEntry:
        return self._cache[self.key(item)]

    def __len__(self):
        return len(self._cache)

    def clear(self) -> None:
        self._cache.clear()

    @staticmethod
    def key(font_name: str) -> str:
        return str(font_name).lower()

    def add_entry(self, font_path: Path, font_face: FontFace) -> None:
        self._cache[self.key(font_path.name)] = CacheEntry(font_path, font_face)

    def get(self, font_name: str, fallback: str) -> CacheEntry:
        try:
            return self._cache[self.key(font_name)]
        except KeyError:
            return self._cache[self.key(fallback)]

    def find_best_match(self, font_face: FontFace) -> Optional[FontFace]:
        entry = self._cache.get(self.key(font_face.filename), None)
        if entry:
            return entry.font_face
        return self.find_best_match_ex(
            family=font_face.family,
            style=font_face.style,
            weight=font_face.weight,
            width=font_face.width,
            italic=font_face.is_italic,
        )

    def find_best_match_ex(
        self,
        family: str = "sans-serif",
        style: str = "Regular",
        weight: int = 400,
        width: int = 5,
        italic: Optional[bool] = False,
    ) -> Optional[FontFace]:
        # italic == None ... ignore italic flag
        family = GENERIC_FONT_FAMILY.get(family, family)
        entries = filter_family(family, self._cache.values())
        if len(entries) == 0:
            return None
        elif len(entries) == 1:
            return entries[0].font_face
        entries_ = filter_style(style, entries)
        if len(entries_) == 1:
            return entries_[0].font_face
        elif len(entries_):
            entries = entries_
        # best match by weight, italic, width
        # Note: the width property is used to prioritize shapefile types:
        # 1st .shx; 2nd: .shp; 3rd: .lff
        result = sorted(
            entries,
            key=lambda e: (
                abs(e.font_face.weight - weight),
                e.font_face.is_italic is not italic,
                abs(e.font_face.width - width),
            ),
        )
        return result[0].font_face

    def loads(self, s: str) -> None:
        cache: dict[str, CacheEntry] = dict()
        try:
            content = json.loads(s)
        except json.JSONDecodeError:
            raise IOError("invalid JSON file format")
        try:
            version = content["version"]
            content = content["font-faces"]
        except KeyError:
            raise IOError("invalid cache file format")
        if version == CURRENT_CACHE_VERSION:
            for entry in content:
                try:
                    file_path, family, style, weight, width = entry
                except ValueError:
                    raise IOError("invalid cache file format")
                path = Path(file_path)  # full path, e.g. "C:\Windows\Fonts\Arial.ttf"
                font_face = FontFace(
                    filename=path.name,  # file name without parent dirs, e.g. "Arial.ttf"
                    family=family,  # Arial
                    style=style,  # Regular
                    weight=weight,  # 400 (Normal)
                    width=width,  # 5 (Normal)
                )
                cache[self.key(path.name)] = CacheEntry(path, font_face)
        else:
            raise IOError("invalid cache file version")
        self._cache = cache

    def dumps(self) -> str:
        faces = [
            (
                str(entry.file_path),
                entry.font_face.family,
                entry.font_face.style,
                entry.font_face.weight,
                entry.font_face.width,
            )
            for entry in self._cache.values()
        ]
        data = {"version": CURRENT_CACHE_VERSION, "font-faces": faces}
        return json.dumps(data, indent=2)


def filter_family(family: str, entries: Iterable[CacheEntry]) -> list[CacheEntry]:
    key = str(family).lower()
    return [e for e in entries if e.font_face.family.lower().startswith(key)]


def filter_style(style: str, entries: Iterable[CacheEntry]) -> list[CacheEntry]:
    key = str(style).lower()
    return [e for e in entries if key in e.font_face.style.lower()]


# TrueType and OpenType fonts:
# Note: CAD applications like AutoCAD/BricsCAD do not support OpenType fonts!
SUPPORTED_TTF_TYPES = {".ttf", ".ttc", ".otf"}
# Basic stroke-fonts included in CAD applications:
SUPPORTED_SHAPE_FILES = {".shx", ".shp", ".lff"}
NO_FONT_FACE = FontFace()


class FontNotFoundError(Exception):
    pass


class FontManager:
    def __init__(self) -> None:
        self.platform = platform.system()
        self._font_cache: FontCache = FontCache()
        self._loaded_ttf_fonts: dict[str, TTFont] = dict()
        self._fallback_font_name = ""

    def has_font(self, font_name: str) -> bool:
        return font_name in self._font_cache

    def clear(self) -> None:
        self._font_cache = FontCache()
        self._loaded_ttf_fonts.clear()
        self._fallback_font_name = ""

    def fallback_font_name(self) -> str:
        fallback_name = self._fallback_font_name
        if fallback_name:
            return fallback_name
        fallback_name = DEFAULT_FONTS[0]
        for name in DEFAULT_FONTS:
            try:
                cache_entry = self._font_cache.get(name, fallback_name)
                fallback_name = cache_entry.file_path.name
                break
            except KeyError:
                pass
        self._fallback_font_name = fallback_name
        return fallback_name

    def get_ttf_font(self, font_name: str, font_number: int = 0) -> TTFont:
        try:
            return self._loaded_ttf_fonts[font_name]
        except KeyError:
            pass
        fallback_name = self.fallback_font_name()
        try:
            font = TTFont(
                self._font_cache.get(font_name, fallback_name).file_path,
                fontNumber=font_number,
            )
        except IOError as e:
            raise FontNotFoundError(str(e))
        self._loaded_ttf_fonts[font_name] = font
        return font

    def ttf_font_from_font_face(self, font_face: FontFace) -> TTFont:
        return self.get_ttf_font(Path(font_face.filename).name)

    def get_font_face(self, font_name: str) -> FontFace:
        cache_entry = self._font_cache.get(font_name, self.fallback_font_name())
        return cache_entry.font_face

    def find_best_match(
        self,
        family: str = "sans-serif",
        style: str = "Regular",
        weight=400,
        width=5,
        italic: Optional[bool] = False,
    ) -> Optional[FontFace]:
        return self._font_cache.find_best_match_ex(family, style, weight, width, italic)

    def find_font_name(self, font_face: FontFace) -> str:
        """Returns the font file name of the font without parent directories
        e.g. "LiberationSans-Regular.ttf".
        """
        font_face = self._font_cache.find_best_match(font_face)  # type: ignore
        if font_face is None:
            font_face = self.get_font_face(self.fallback_font_name())
            return font_face.filename
        else:
            return font_face.filename

    def build(self, folders: Optional[Sequence[str]] = None) -> None:
        """Adds all supported font types located in the given `folders` to the font
        manager. If no directories are specified, the known font folders for Windows,
        Linux and macOS are searched by default. Searches recursively all
        subdirectories.

        The folders stored in the config SUPPORT_DIRS option are scanned recursively for
        .shx, .shp and .lff fonts, the basic stroke fonts included in CAD applications.

        """
        from ezdxf._options import options

        if folders:
            dirs = list(folders)
        else:
            dirs = FONT_DIRECTORIES.get(self.platform, LINUX_FONT_DIRS)
        self.scan_all(dirs + list(options.support_dirs))

    def scan_all(self, folders: Iterable[str]) -> None:
        for folder in folders:
            folder = folder.strip("'\"")  # strip quotes
            self.scan_folder(Path(folder).expanduser())

    def scan_folder(self, folder: Path):
        if not folder.exists():
            return
        for file in folder.iterdir():
            if file.is_dir():
                self.scan_folder(file)
                continue
            ext = file.suffix.lower()
            if ext in SUPPORTED_TTF_TYPES:
                font_face = get_ttf_font_face(file)
                self._font_cache.add_entry(file, font_face)
            elif ext in SUPPORTED_SHAPE_FILES:
                font_face = get_shape_file_font_face(file)
                self._font_cache.add_entry(file, font_face)

    def dumps(self) -> str:
        return self._font_cache.dumps()

    def loads(self, s: str) -> None:
        self._font_cache.loads(s)


def normalize_style(style: str) -> str:
    if style in {"Book"}:
        style = "Regular"
    return style


def get_ttf_font_face(font_path: Path) -> FontFace:
    try:
        ttf = TTFont(font_path, fontNumber=0)
    except IOError:
        return FontFace(filename=font_path.name)

    names = ttf["name"].names
    family = ""
    style = ""
    for record in names:
        if record.nameID == 1:
            family = record.string.decode(record.getEncoding())
        elif record.nameID == 2:
            style = record.string.decode(record.getEncoding())
        if family and style:
            break
    os2_table = ttf["OS/2"]
    weight = os2_table.usWeightClass
    width = os2_table.usWidthClass
    return FontFace(
        filename=font_path.name,
        family=family,
        style=normalize_style(style),
        width=width,
        weight=weight,
    )


def get_shape_file_font_face(font_path: Path) -> FontFace:
    ext = font_path.suffix.lower()
    # Note: the width property is not defined in shapefiles and is used to
    # prioritize the shapefile types for find_best_match():
    # 1st .shx; 2nd: .shp; 3rd: .lff

    width = 5
    if ext == ".shp":
        width = 6
    if ext == ".lff":
        width = 7

    return FontFace(
        filename=font_path.name,  # "txt.shx", "simplex.shx", ...
        family=font_path.stem.lower(),  # "txt", "simplex", ...
        style=font_path.suffix.lower(),  # ".shx", ".shp" or ".lff"
        width=width,
        weight=400,
    )
