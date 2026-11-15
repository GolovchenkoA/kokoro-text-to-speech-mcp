"""How an engine works through the pieces of a long text (the Strategy pattern).

An engine that cannot stream cuts the text into pieces and hands them to a strategy together with the
function that turns one piece into audio. The strategy decides in which order and how many at a time:

- `SequentialChunks`: one piece at a time (the default).
- `ParallelChunks`: up to N pieces at the same time. The audio is still delivered in the order of the
  text, so playback does not change; only the waiting time does.

`chunk_strategy(parallel_threads)` picks the strategy from the models file: 1 is sequential, more is
parallel.
"""

from __future__ import annotations

import itertools
from collections import deque
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Protocol, TypeVar

T = TypeVar("T")


class ChunkStrategy(Protocol):
    def generate(self, pieces: Iterable[str], work: Callable[[str], T]) -> Iterator[T]:
        """Run `work` on every piece and yield the results in the order of the pieces."""
        ...


class SequentialChunks:
    """One piece at a time: the next piece starts when the previous one is done."""

    def generate(self, pieces: Iterable[str], work: Callable[[str], T]) -> Iterator[T]:
        for piece in pieces:
            yield work(piece)


class ParallelChunks:
    """Up to `threads` pieces at the same time, results delivered in order.

    At most `threads` pieces are in progress at any moment, however long the text is. A piece is started as
    soon as the result of an earlier one is taken, so the work stays ahead of the listener by `threads`
    pieces. When the caller stops listening (the speech is stopped), pieces that have not started are
    cancelled; those already running finish and are dropped.
    """

    def __init__(self, threads: int) -> None:
        if threads < 2:
            raise ValueError("ParallelChunks needs at least 2 threads; use SequentialChunks for one")
        self._threads = threads

    @property
    def threads(self) -> int:
        return self._threads

    def generate(self, pieces: Iterable[str], work: Callable[[str], T]) -> Iterator[T]:
        remaining = iter(pieces)
        executor = ThreadPoolExecutor(max_workers=self._threads, thread_name_prefix="tts-chunk")
        try:
            in_progress = deque(executor.submit(work, piece) for piece in itertools.islice(remaining, self._threads))
            while in_progress:
                result = in_progress.popleft().result()  # re-raises a failure of that piece
                following = next(remaining, None)
                if following is not None:
                    in_progress.append(executor.submit(work, following))
                yield result
        finally:
            executor.shutdown(wait=False, cancel_futures=True)


def chunk_strategy(parallel_threads: int) -> ChunkStrategy:
    """Sequential for one thread, parallel for more."""
    return SequentialChunks() if parallel_threads <= 1 else ParallelChunks(parallel_threads)
