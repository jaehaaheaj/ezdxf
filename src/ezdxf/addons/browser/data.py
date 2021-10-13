#  Copyright (c) 2021, Manfred Moitzi
#  License: MIT License
from typing import Optional, Dict, List, Tuple, Iterable, Any
from pathlib import Path
from ezdxf.lldxf.loader import SectionDict
from ezdxf.addons.browser.loader import load_section_dict
from ezdxf.lldxf.types import DXFVertex, tag_type
from ezdxf.lldxf.tags import Tags

__all__ = [
    "DXFDocument",
    "IndexEntry",
    "get_row_from_line_number",
    "dxfstr",
    "EntityHistory",
    "SearchIndex",
]


class DXFDocument:
    def __init__(self, sections: SectionDict = None):
        # Important: the section dict has to store the raw string tags
        # else an association of line numbers to entities is not possible.
        # Comment tags (999) are ignored, because the load_section_dict()
        # function can not handle and store comments.
        # Therefore comments causes incorrect results for the line number
        # associations and should be stripped off before processing for precise
        # debugging of DXF files (-b for backup):
        # ezdxf strip -b <your.dxf>
        self.sections: SectionDict = dict()
        self.handle_index: Optional[HandleIndex] = None
        self.line_index: Optional[LineIndex] = None
        self.valid_handles = None
        self.filename = ""
        if sections:
            self.update(sections)

    @property
    def filepath(self):
        return Path(self.filename)

    @property
    def max_line_number(self) -> int:
        if self.line_index:
            return self.line_index.max_line_number
        else:
            return 1

    def load(self, filename: str):
        self.filename = filename
        self.update(load_section_dict(filename))

    def update(self, sections: SectionDict):
        self.sections = sections
        self.handle_index = HandleIndex(self.sections)
        self.line_index = LineIndex(self.sections)

    def absolute_filepath(self):
        return self.filepath.absolute()

    def get_section(self, name: str) -> List[Tags]:
        return self.sections.get(name)  # type: ignore

    def get_entity(self, handle: str) -> Optional[Tags]:
        if self.handle_index:
            return self.handle_index.get(handle)
        return None

    def get_line_number(self, entity: Tags, offset: int = 0) -> int:
        if self.line_index:
            return (
                self.line_index.get_start_line_for_entity(entity) + offset * 2
            )
        return 0

    def get_entity_at_line(self, number: int) -> Optional[Tags]:
        if self.line_index:
            return self.line_index.get_entity_at_line(number)
        return None

    def next_entity(self, entity: Tags) -> Optional[Tags]:
        return self.handle_index.next_entity(entity)  # type: ignore

    def previous_entity(self, entity: Tags) -> Optional[Tags]:
        return self.handle_index.previous_entity(entity)  # type: ignore

    def get_handle(self, entity) -> Optional[str]:
        return self.handle_index.get_handle(entity)  # type: ignore


class IndexEntry:
    def __init__(self, tags: Tags, handle: str = None, line: int = 0):
        self.tags: Tags = tags
        self.handle: Optional[str] = handle
        self.start_line_number: int = line
        self.prev: Optional["IndexEntry"] = None
        self.next: Optional["IndexEntry"] = None


class HandleIndex:
    def __init__(self, sections: SectionDict):
        # dict() entries have to be ordered since Python 3.6!
        # Therefore _index.values() returns the DXF entities in file order!
        self._index: Dict[str, IndexEntry] = dict()
        self._max_line_number: int = 0
        self._build(sections)

    def _build(self, sections: SectionDict) -> None:
        start_line_number = 1
        dummy_handle = 1
        entity_index = dict()
        prev_entity: Optional[IndexEntry] = None
        for section in sections.values():
            for tags in section:
                try:
                    handle = tags.get_handle()
                except ValueError:
                    handle = f"*{dummy_handle:X}"
                    dummy_handle += 1
                handle = handle.upper()
                new_entity = IndexEntry(
                    tags, handle=handle, line=start_line_number  # type: ignore
                )
                if prev_entity is not None:
                    new_entity.prev = prev_entity
                    prev_entity.next = new_entity
                entity_index[handle] = new_entity
                prev_entity = new_entity

                # calculate next start line number:
                # add 2 lines for each tag: group code, value
                start_line_number += len(tags) * 2  # type: ignore
            start_line_number += 2  # for missing ENDSEC tag

        self._max_line_number = start_line_number - 3  # last ENDSEC!
        self._index = entity_index

    def __contains__(self, handle: str) -> bool:
        return handle.upper() in self._index

    @property
    def max_line_number(self) -> int:
        return self._max_line_number

    def get(self, handle: str) -> Optional[Tags]:
        entity = self._index.get(handle.upper())
        if entity is not None:
            return entity.tags
        else:
            return None

    def get_handle(self, entity: Tags) -> Optional[str]:
        if not len(entity):
            return None

        try:
            return entity.get_handle()
        except ValueError:
            pass

        first_tag = entity[0]
        # get dummy handle
        for handle, e in self._index.items():
            # comparing Tags() by the "is" operator is not safe!
            tags = e.tags
            # compare first DXF tag
            if len(tags) and tags[0] is first_tag:
                return handle
        return None

    def next_entity(self, entity: Tags) -> Tags:
        handle = self.get_handle(entity)
        if handle is not None:
            dxf_entity = self._index.get(handle)
            next_entity = dxf_entity.next  # type: ignore
            # next of last entity is None!
            if next_entity is not None:
                return next_entity.tags
        return entity

    def previous_entity(self, entity: Tags) -> Tags:
        handle = self.get_handle(entity)
        if handle is not None:
            dxf_entity = self._index.get(handle)
            prev_entity = dxf_entity.prev  # type: ignore
            # prev of first entity is None!
            if prev_entity is not None:
                return prev_entity.tags
        return entity

    def get_start_line_for_entity(self, entity: Tags) -> int:
        handle = self.get_handle(entity)
        if handle is not None:
            entry = self._index.get(handle)
            if entry:
                return entry.start_line_number
        return 0

    def get_entity_at_line(self, number: int) -> Optional[Tags]:
        tags = None
        for entry in self._index.values():
            if entry.start_line_number > number:
                return tags  # tags of previous entry!
            tags = entry.tags
        return tags


class LineIndex:
    def __init__(self, sections: SectionDict):
        # id, (start_line_number, entity tags)
        self._entity_index: Dict[
            int, Tuple[int, Tags]
        ] = LineIndex.build_entity_index(sections)

        # entity index of sorted (start_line_number, entity) tuples
        index = LineIndex.build_line_index(sections)
        self._line_index: List[Tuple[int, Tags]] = index
        self._max_line_number = 1
        if index:
            last_start_number, e = self._line_index[-1]
            self._max_line_number = last_start_number + len(e) * 2 - 1

    @property
    def max_line_number(self) -> int:
        return self._max_line_number

    @staticmethod
    def build_entity_index(sections: SectionDict) -> Dict:
        index: Dict[int, Tuple[int, Tags]] = dict()
        line_number = 1
        for section in sections.values():
            # the section dict contain raw string tags
            for entity in section:
                index[id(entity)] = line_number, entity  # type: ignore
                line_number += (
                    len(entity) * 2  # type: ignore # group code, value
                )
            line_number += 2  # for missing ENDSEC tag
        return index

    @staticmethod
    def build_line_index(sections: SectionDict) -> List:
        index: List[Tuple[int, Tags]] = list()
        start_line_number = 1
        for name, section in sections.items():
            # the section dict contain raw string tags
            for entity in section:
                index.append((start_line_number, entity))  # type: ignore
                # add 2 lines for each tag: group code, value
                start_line_number += len(entity) * 2  # type: ignore
            start_line_number += 2  # for missing ENDSEC tag
        index.sort()  # sort index by line number
        return index

    def get_start_line_for_entity(self, entity: Tags) -> int:
        entry = self._entity_index.get(id(entity))
        if entry:
            return entry[0]
        return 0

    def get_entity_at_line(self, number: int) -> Optional[Tags]:
        index = self._line_index
        if len(index) == 0:
            return None

        _, entity = index[0]  # first entity
        for start, e in index:
            if start > number:
                return entity
            entity = e
        return entity


def get_row_from_line_number(
    entity: Tags, start_line_number: int, select_line_number: int
) -> int:
    count = select_line_number - start_line_number
    lines = 0
    row = 0
    for tag in entity:
        if lines >= count:
            return row
        if isinstance(tag, DXFVertex):
            lines += len(tag.value) * 2
        else:
            lines += 2
        row += 1
    return row


def dxfstr(tags: Tags) -> str:
    return "".join(tag.dxfstr() for tag in tags)


class EntityHistory:
    def __init__(self):
        self._history: List[Tags] = list()
        self._index: int = 0
        self._time_travel: List[Tags] = list()

    def __len__(self):
        return len(self._history)

    @property
    def index(self):
        return self._index

    def clear(self):
        self._history.clear()
        self._time_travel.clear()
        self._index = 0

    def append(self, entity: Tags):
        if self._time_travel:
            self._history.extend(self._time_travel)
            self._time_travel.clear()
        count = len(self._history)
        if count:
            # only append if different to last entity
            if self._history[-1] is entity:
                return
        self._index = count
        self._history.append(entity)

    def back(self) -> Optional[Tags]:
        entity = None
        if self._history:
            index = self._index - 1
            if index >= 0:
                entity = self._time_wrap(index)
            else:
                entity = self._history[0]
        return entity

    def forward(self) -> Tags:
        entity = None
        history = self._history
        if history:
            index = self._index + 1
            if index < len(history):
                entity = self._time_wrap(index)
            else:
                entity = history[-1]
        return entity  # type: ignore

    def _time_wrap(self, index) -> Tags:
        self._index = index
        entity = self._history[index]
        self._time_travel.append(entity)
        return entity

    def content(self) -> List[Tags]:
        return list(self._history)


class SearchIndex:
    NOT_FOUND = None, -1

    def __init__(self, entities: Iterable[Tags]):
        self.entities: List[Tags] = list(entities)
        self._current_entity_index: int = 0
        self._current_tag_index: int = 0
        self._search_term: Optional[str] = None
        self._search_term_lower: Optional[str] = None
        self._backward = False
        self._end_of_index = not bool(self.entities)
        self.case_insensitive = True
        self.whole_words = False
        self.numbers = False
        self.regex = False  # False = normal mode

    @property
    def is_end_of_index(self) -> bool:
        return self._end_of_index

    @property
    def search_term(self) -> Optional[str]:
        return self._search_term

    def set_current_entity(self, entity: Tags, tag_index: int = 0):
        self._current_tag_index = tag_index
        try:
            self._current_entity_index = self.entities.index(entity)
        except ValueError:
            self.reset_cursor()

    def update_entities(self, entities: List[Tags]):
        current_entity, index = self.current_entity()
        self.entities = entities
        if current_entity:
            self.set_current_entity(current_entity, index)

    def current_entity(self) -> Tuple[Optional[Tags], int]:
        if self.entities and not self._end_of_index:
            return (
                self.entities[self._current_entity_index],
                self._current_tag_index,
            )
        return self.NOT_FOUND

    def reset_cursor(self, backward: bool = False):
        self._current_entity_index = 0
        self._current_tag_index = 0
        count = len(self.entities)
        if count:
            self._end_of_index = False
            if backward:
                self._current_entity_index = count - 1
                entity = self.entities[-1]
                self._current_tag_index = len(entity) - 1
        else:
            self._end_of_index = True

    def cursor(self) -> Tuple[int, int]:
        return self._current_entity_index, self._current_tag_index

    def move_cursor_forward(self) -> None:
        if self.entities:
            entity: Tags = self.entities[self._current_entity_index]
            tag_index = self._current_tag_index + 1
            if tag_index >= len(entity):
                entity_index = self._current_entity_index + 1
                if entity_index < len(self.entities):
                    self._current_entity_index = entity_index
                    self._current_tag_index = 0
                else:
                    self._end_of_index = True
            else:
                self._current_tag_index = tag_index

    def move_cursor_backward(self) -> None:
        if self.entities:
            tag_index = self._current_tag_index - 1
            if tag_index < 0:
                entity_index = self._current_entity_index - 1
                if entity_index >= 0:
                    self._current_entity_index = entity_index
                    self._current_tag_index = (
                        len(self.entities[entity_index]) - 1
                    )
                else:
                    self._end_of_index = True
            else:
                self._current_tag_index = tag_index

    def reset_search_term(self, term: str) -> None:
        self._search_term = str(term)
        self._search_term_lower = self._search_term.lower()

    def find(
        self, term: str, backward: bool = False, reset_index: bool = True
    ) -> Tuple[Optional[Tags], int]:
        self.reset_search_term(term)
        if reset_index:
            self.reset_cursor(backward)
        if len(self.entities) and not self._end_of_index:
            if backward:
                return self.find_backwards()
            else:
                return self.find_forward()
        else:
            return self.NOT_FOUND

    def find_forward(self) -> Tuple[Optional[Tags], int]:
        return self._find(self.move_cursor_forward)

    def find_backwards(self) -> Tuple[Optional[Tags], int]:
        return self._find(self.move_cursor_backward)

    def _find(self, move_cursor) -> Tuple[Optional[Tags], int]:
        if self.entities and self._search_term and not self._end_of_index:
            while not self._end_of_index:
                entity, tag_index = self.current_entity()
                move_cursor()
                if self._match(*entity[tag_index]):  # type: ignore
                    return entity, tag_index
        return self.NOT_FOUND

    def _match(self, code: int, value: Any) -> bool:
        if tag_type(code) is not str:
            if not self.numbers:
                return False
            value = str(value)

        if self.case_insensitive:
            search_term = self._search_term_lower
            value = value.lower()
        else:
            search_term = self._search_term

        if self.whole_words:
            return any(search_term == word for word in value.split())
        else:
            return search_term in value
