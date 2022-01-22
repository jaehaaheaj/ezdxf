#  Copyright (c) 2022, Manfred Moitzi
#  License: MIT License
from typing import (
    List,
    Iterable,
    Optional,
    Callable,
)
import abc
import copy
from dataclasses import dataclass
import random
import time

__all__ = [
    "DNA",
    "Selection",
    "BitDNA",
    "FloatDNA",
    "RouletteSelection",
    "GeneticOptimizer",
]


class DNA(abc.ABC):
    fitness: Optional[float] = None
    _data: List

    @classmethod
    @abc.abstractmethod
    def random(cls, length: int) -> "DNA":
        ...

    @classmethod
    def n_random(cls, n: int, length: int) -> List["DNA"]:
        return [cls.random(length) for _ in range(n)]

    @abc.abstractmethod
    def reset(self, values: Iterable):
        ...

    @property
    @abc.abstractmethod
    def is_valid(self) -> bool:
        ...

    def copy(self):
        return copy.deepcopy(self)

    def _taint(self):
        self.fitness = None

    def __eq__(self, other):
        assert isinstance(other, self.__class__)
        return self._data == other._data

    def __len__(self):
        return len(self._data)

    def __getitem__(self, item):
        return self._data.__getitem__(item)

    def __setitem__(self, key, value):
        self._data.__setitem__(key, value)
        self._taint()

    def __iter__(self):
        return iter(self._data)

    @abc.abstractmethod
    def flip_mutate_at(self, index: int) -> None:
        ...


class Mutate(abc.ABC):
    @abc.abstractmethod
    def mutate(self, dna: DNA, rate: float):
        ...


class FlipMutate(Mutate):
    def mutate(self, dna: DNA, rate: float):
        for index in range(len(dna)):
            if random.random() < rate:
                dna.flip_mutate_at(index)


class SwapNeighbors(Mutate):
    def mutate(self, dna: DNA, rate: float):
        for index in range(len(dna)):
            if random.random() < rate:
                i2 = index - 1
                tmp = dna[i2]
                dna[i2] = dna[index]
                dna[index] = tmp


class RandomSwap(Mutate):
    def mutate(self, dna: DNA, rate: float):
        length = len(dna)
        for index in range(len(dna)):
            if random.random() < rate:
                i1 = random.randrange(0, length)
                i2 = random.randrange(0, length)
                tmp = dna[i2]
                dna[i2] = dna[i1]
                dna[i1] = tmp


class Mate(abc.ABC):
    @abc.abstractmethod
    def recombine(self, dna1: DNA, dna2: DNA):
        pass


class Mate1pCX(Mate):
    def recombine(self, dna1: DNA, dna2: DNA):
        length = len(dna1)
        index = random.randrange(0, length)
        recombine_dna_2pcx(dna1, dna2, index, length)


class Mate2pCX(Mate):
    def recombine(self, dna1: DNA, dna2: DNA):
        length = len(dna1)
        i1 = random.randrange(0, length)
        i2 = random.randrange(0, length)
        if i1 > i2:
            i1, i2 = i2, i1
        recombine_dna_2pcx(dna1, dna2, i1, i2)


class MateUniformCX(Mate):
    def recombine(self, dna1: DNA, dna2: DNA):
        for index in range(len(dna1)):
            if random.random() > 0.5:
                tmp = dna1[index]
                dna1[index] = dna2[index]
                dna2[index] = tmp


class MateOrderedCX(Mate):
    """Recombination class for ordered DNA like IntegerDNA(). """
    def recombine(self, dna1: DNA, dna2: DNA):
        length = len(dna1)
        i1 = random.randrange(0, length)
        i2 = random.randrange(0, length)
        if i1 > i2:
            i1, i2 = i2, i1
        recombine_dna_ocx1(dna1, dna2, i1, i2)


def recombine_dna_2pcx(dna1: DNA, dna2: DNA, i1: int, i2: int) -> None:
    """Two point crossover."""
    part1 = dna1[i1:i2]
    part2 = dna2[i1:i2]
    dna1[i1:i2] = part2
    dna2[i1:i2] = part1


def recombine_dna_ocx1(dna1: DNA, dna2: DNA, i1: int, i2: int) -> None:
    """Ordered crossover."""
    copy1 = dna1.copy()
    replace_dna_ocx1(dna1, dna2, i1, i2)
    replace_dna_ocx1(dna2, copy1, i1, i2)


def replace_dna_ocx1(dna1: DNA, dna2: DNA, i1: int, i2: int) -> None:
    """Replace part in dna1 by dna2 and preserve order of remaining values in
    dna1.
    """
    old = dna1.copy()
    new = dna2[i1:i2]
    dna1[i1:i2] = new
    index = 0
    new_set = set(new)
    for value in old:
        if value in new_set:
            continue
        if index == i1:
            index = i2
        dna1[index] = value
        index += 1


class FloatDNA(DNA):
    """Arbitrary float numbers in the range [0, 1]."""

    __slots__ = ("_data", "fitness")

    def __init__(self, values: Iterable[float]):
        self._data: List[float] = list(values)
        self._check_valid_data()
        self.fitness: Optional[float] = None

    @classmethod
    def random(cls, length: int) -> "FloatDNA":
        return cls(random.random() for _ in range(length))

    @property
    def is_valid(self) -> bool:
        return all(0.0 <= v <= 1.0 for v in self._data)

    def _check_valid_data(self):
        if not self.is_valid:
            raise ValueError("data value out of range")

    def __str__(self):
        if self.fitness is None:
            fitness = ", fitness=None"
        else:
            fitness = f", fitness={self.fitness:.4f}"
        return f"{str([round(v, 4) for v in self._data])}{fitness}"

    def reset(self, values: Iterable[float]):
        self._data = list(values)
        self._check_valid_data()
        self._taint()

    def flip_mutate_at(self, index: int) -> None:
        self._data[index] = 1.0 - self._data[index]  # flip pick location


class BitDNA(DNA):
    __slots__ = ("_data", "fitness")

    def __init__(self, values: Iterable):
        self._data: List[bool] = list(bool(v) for v in values)
        self.fitness: Optional[float] = None

    @property
    def is_valid(self) -> bool:
        return True  # everything can be evaluated to True/False

    @classmethod
    def random(cls, length: int) -> "BitDNA":
        return cls(bool(random.randint(0, 1)) for _ in range(length))

    def __str__(self):
        if self.fitness is None:
            fitness = ", fitness=None"
        else:
            fitness = f", fitness={self.fitness:.4f}"
        return f"{str([int(v) for v in self._data])}{fitness}"

    def reset(self, values: Iterable) -> None:
        self._data = list(bool(v) for v in values)
        self._taint()

    def flip_mutate_at(self, index: int) -> None:
        self._data[index] = not self._data[index]


class IntegerDNA(DNA):
    """Unique integer values in the range from 0 to length-1.
    E.g. IntegerDNA(10) = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]

    Requires MateOrderedCX() as recombination class to preserve order and
    validity after DNA recombination.

    """

    __slots__ = ("_data", "fitness")

    def __init__(self, length: int):
        self._data: List[int] = list(range(length))
        self.fitness: Optional[float] = None

    @classmethod
    def random(cls, length: int) -> "IntegerDNA":
        dna = cls(length)
        random.shuffle(dna._data)
        return dna

    @property
    def is_valid(self) -> bool:
        return len(set(self._data)) == len(self._data)

    def __str__(self):
        if self.fitness is None:
            fitness = ", fitness=None"
        else:
            fitness = f", fitness={self.fitness:.4f}"
        return f"{str([int(v) for v in self._data])}{fitness}"

    def reset(self, values: Iterable) -> None:
        self._data = list(int(v) for v in values)
        self._taint()

    def flip_mutate_at(self, index: int) -> None:
        raise TypeError("flip mutation not supported")


class Selection(abc.ABC):
    @abc.abstractmethod
    def pick(self, count: int) -> Iterable[DNA]:
        ...

    @abc.abstractmethod
    def reset(self, strands: Iterable[DNA]):
        ...


class Evaluator(abc.ABC):
    @abc.abstractmethod
    def evaluate(self, dna: DNA) -> float:
        ...


@dataclass
class LogEntry:
    fitness: float
    avg_fitness: float


class GeneticOptimizer:
    def __init__(
        self,
        evaluator: Evaluator,
        max_generations: int,
        max_fitness: float = 1.0,
    ):
        if max_generations < 1:
            raise ValueError("max_generations < 1")
        # data:
        self.name = "GeneticOptimizer"
        self.log: List[LogEntry] = []
        self._dna_strands: List[DNA] = []

        # core components:
        self.evaluator: Evaluator = evaluator
        self.selection: Selection = RouletteSelection()
        self.mate: Mate = Mate2pCX()
        self.mutation = FlipMutate()

        # options:
        self.max_generations = int(max_generations)
        self.max_fitness: float = float(max_fitness)
        self.max_runtime: float = 1e99
        self.max_stagnation = 100
        self.crossover_rate = 0.70
        self.mutation_rate = 0.001
        self.elitism: int = 2

        # state of last (current) generation:
        self.generation: int = 0
        self.runtime: float = 0.0
        self.best_dna = BitDNA([])
        self.best_fitness: float = 0.0
        self.stagnation: int = 0  # generations without improvement

    @property
    def is_executed(self) -> bool:
        return bool(self.generation)

    @property
    def dna_count(self) -> int:
        return len(self._dna_strands)

    def add_dna(self, dna: Iterable[DNA]):
        if not self.is_executed:
            self._dna_strands.extend(dna)
        else:
            raise TypeError("already executed")

    def execute(
        self,
        feedback: Callable[["GeneticOptimizer"], bool] = None,
        interval: float = 1.0,
    ) -> None:
        if self.is_executed:
            raise TypeError("can only run once")
        if not self._dna_strands:
            print("no DNA defined!")
        t0 = time.perf_counter()
        start_time = t0
        for self.generation in range(1, self.max_generations + 1):
            self.measure_fitness()
            t1 = time.perf_counter()
            self.runtime = t1 - start_time
            if (
                self.best_fitness >= self.max_fitness
                or self.runtime >= self.max_runtime
                or self.stagnation >= self.max_stagnation
            ):
                break
            if feedback and t1 - t0 > interval:
                if feedback(self):  # stop if feedback() returns True
                    break
                t0 = t1
            self.next_generation()

    def measure_fitness(self) -> None:
        self.stagnation += 1
        fitness_sum: float = 0.0
        for dna in self._dna_strands:
            if dna.fitness is not None:
                fitness_sum += dna.fitness
                continue
            fitness = self.evaluator.evaluate(dna)
            dna.fitness = fitness
            fitness_sum += fitness
            if fitness > self.best_fitness:
                self.best_fitness = fitness
                self.best_dna = dna.copy()
                self.stagnation = 0

        try:
            avg_fitness = fitness_sum / len(self._dna_strands)
        except ZeroDivisionError:
            avg_fitness = 0.0
        self.log.append(LogEntry(self.best_fitness, avg_fitness))

    def next_generation(self) -> None:
        selector = self.selection
        selector.reset(self._dna_strands)
        dna_strands: List[DNA] = []
        count = len(self._dna_strands)

        if self.elitism > 0:
            dna_strands.extend([self.best_dna] * self.elitism)

        while len(dna_strands) < count:
            dna1, dna2 = selector.pick(2)
            dna1 = dna1.copy()
            dna2 = dna2.copy()
            self.recombine(dna1, dna2)
            self.mutate(dna1, dna2)
            dna_strands.append(dna1)
            dna_strands.append(dna2)
        self._dna_strands = dna_strands

    def recombine(self, dna1: DNA, dna2: DNA):
        if random.random() < self.crossover_rate:
            self.mate.recombine(dna1, dna2)

    def mutate(self, dna1: DNA, dna2: DNA):
        mutation_rate = self.mutation_rate * self.stagnation
        self.mutation.mutate(dna1, mutation_rate)
        self.mutation.mutate(dna2, mutation_rate)


class RouletteSelection(Selection):
    def __init__(self):
        self._strands: List[DNA] = []
        self._weights: List[float] = []

    def reset(self, strands: Iterable[DNA]):
        # dna.fitness is not None here!
        self._strands = list(strands)
        sum_fitness = sum(dna.fitness for dna in self._strands)
        if sum_fitness == 0.0:
            sum_fitness = 1.0
        self._weights = [dna.fitness / sum_fitness for dna in self._strands]  # type: ignore

    def pick(self, count: int) -> Iterable[DNA]:
        return random.choices(self._strands, self._weights, k=count)