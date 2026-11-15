"""The chunk strategies (sequential and parallel) and how the Qwen3 engine uses them."""

from __future__ import annotations

import json
import threading
import time
from dataclasses import replace

import numpy as np
import pytest

from tests.fakes import CHUNK_FRAMES, models_data, wait_until
from tests.conftest import call_tool_on
from tts_mcp.catalog import CatalogError, parse_catalog
from tts_mcp.engines.chunking import ParallelChunks, SequentialChunks, chunk_strategy
from tts_mcp.engines.qwen3 import Qwen3Engine


class Work:
    """A piece of work that records how many ran at the same time and in which order they started."""

    def __init__(self, delay_for=lambda piece: 0.0, fail_on=None) -> None:
        self.delay_for = delay_for
        self.fail_on = fail_on
        self.lock = threading.Lock()
        self.active = 0
        self.max_active = 0
        self.started: list[str] = []

    def __call__(self, piece: str) -> str:
        with self.lock:
            self.started.append(piece)
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            time.sleep(self.delay_for(piece))
            if piece == self.fail_on:
                raise RuntimeError(f"failed on {piece}")
            return piece.upper()
        finally:
            with self.lock:
                self.active -= 1


PIECES = [f"p{i}" for i in range(8)]


# -- choosing the strategy -----------------------------------------------------------------------
@pytest.mark.parametrize("threads", [1, 0, -3])
def test_one_thread_or_fewer_means_sequential(threads):
    assert isinstance(chunk_strategy(threads), SequentialChunks)


def test_more_than_one_thread_means_parallel():
    strategy = chunk_strategy(3)
    assert isinstance(strategy, ParallelChunks) and strategy.threads == 3


def test_a_parallel_strategy_needs_at_least_two_threads():
    with pytest.raises(ValueError):
        ParallelChunks(1)


# -- sequential ----------------------------------------------------------------------------------
def test_sequential_works_on_one_piece_at_a_time_in_order():
    work = Work(delay_for=lambda piece: 0.01)
    assert list(SequentialChunks().generate(PIECES, work)) == [p.upper() for p in PIECES]
    assert work.max_active == 1
    assert work.started == PIECES


def test_sequential_is_lazy_the_next_piece_starts_only_when_asked_for():
    work = Work()
    results = SequentialChunks().generate(PIECES, work)
    assert work.started == []
    assert next(results) == "P0"
    assert work.started == ["p0"]


# -- parallel ------------------------------------------------------------------------------------
def test_parallel_delivers_the_results_in_the_order_of_the_text_even_if_later_pieces_finish_first():
    work = Work(delay_for=lambda piece: 0.2 - 0.02 * int(piece[1:]))  # p0 is the slowest, p7 the fastest
    assert list(ParallelChunks(4).generate(PIECES, work)) == [p.upper() for p in PIECES]


def test_parallel_runs_several_pieces_at_once_but_never_more_than_the_thread_count():
    work = Work(delay_for=lambda piece: 0.05)
    list(ParallelChunks(3).generate([f"p{i}" for i in range(12)], work))
    assert work.max_active == 3  # it did run in parallel, and stopped at the limit


def test_parallel_is_faster_than_sequential_when_the_work_waits():
    pieces = [f"p{i}" for i in range(6)]
    started = time.monotonic()
    list(SequentialChunks().generate(pieces, Work(delay_for=lambda piece: 0.1)))
    sequential = time.monotonic() - started
    started = time.monotonic()
    list(ParallelChunks(3).generate(pieces, Work(delay_for=lambda piece: 0.1)))
    parallel = time.monotonic() - started
    assert parallel < sequential * 0.7


def test_parallel_with_fewer_pieces_than_threads_works():
    assert list(ParallelChunks(5).generate(["a", "b"], Work())) == ["A", "B"]
    assert list(ParallelChunks(5).generate([], Work())) == []


def test_a_failing_piece_raises_when_its_turn_comes():
    work = Work(fail_on="p2")
    results = ParallelChunks(3).generate(PIECES, work)
    assert next(results) == "P0" and next(results) == "P1"
    with pytest.raises(RuntimeError, match="failed on p2"):
        next(results)


def test_stopping_early_cancels_the_pieces_that_have_not_started():
    work = Work(delay_for=lambda piece: 0.05)
    results = ParallelChunks(2).generate([f"p{i}" for i in range(20)], work)
    assert next(results) == "P0"
    results.close()  # the speech was stopped
    time.sleep(0.3)  # long enough for the rest to run if it had not been cancelled
    assert len(work.started) <= 4  # the first two, the replacement for the one taken, and at most one more


# -- the Qwen3 engine ----------------------------------------------------------------------------
def qwen_spec(**options):
    spec = parse_catalog(models_data()).models["qwen3"]
    return replace(spec, options={**spec.options, **options})


SENTENCES = " ".join(f"Sentence number {n} " + "x" * n + "." for n in range(10, 70, 8))


def test_by_default_the_engine_works_on_one_piece_at_a_time(fakes):
    fakes.qwen.delay_for = lambda text: 0.02
    engine = Qwen3Engine(qwen_spec(max_chars=60), None)
    chunks = list(engine.synthesize(SENTENCES, "Ryan", "English", 1.0))
    assert len(chunks) == len(fakes.qwen.calls) > 3
    assert fakes.qwen.max_active == 1


def test_parallel_threads_make_the_engine_work_on_several_pieces_at_once(fakes):
    fakes.qwen.delay_for = lambda text: 0.05
    engine = Qwen3Engine(qwen_spec(max_chars=60, parallel_threads=3), None)
    chunks = list(engine.synthesize(SENTENCES, "Ryan", "English", 1.0))
    assert len(chunks) == len(fakes.qwen.calls) > 3
    assert 1 < fakes.qwen.max_active <= 3


def test_parallel_and_sequential_give_the_same_audio_in_the_same_order(fakes):
    sequential = list(Qwen3Engine(qwen_spec(max_chars=60), None).synthesize(SENTENCES, "Ryan", "English", 1.0))
    fakes.qwen.delay_for = lambda text: 0.2 / max(len(text), 1) * 10  # shorter pieces finish later
    parallel = list(
        Qwen3Engine(qwen_spec(max_chars=60, parallel_threads=4), None).synthesize(SENTENCES, "Ryan", "English", 1.0)
    )
    assert len(parallel) == len(sequential)
    assert all(np.array_equal(a, b) for a, b in zip(sequential, parallel))
    assert len({float(chunk[0]) for chunk in parallel}) > 1  # the pieces really are different, so the order is checked


def test_the_pieces_are_never_longer_than_max_chars_in_parallel_mode(fakes):
    list(Qwen3Engine(qwen_spec(max_chars=60, parallel_threads=3), None).synthesize(SENTENCES, "Ryan", "English", 1.0))
    assert all(len(call["text"]) <= 60 for call in fakes.qwen.calls)


@pytest.mark.parametrize("value", [0, -1, "2", True, 1.5, None])
def test_invalid_options_are_rejected_with_a_message_that_names_them(fakes, value):
    for option in ("parallel_threads", "max_chars"):
        with pytest.raises(CatalogError, match=f"option '{option}' must be a whole number of at least 1"):
            Qwen3Engine(qwen_spec(**{option: value}), None)


def test_the_models_file_option_reaches_the_engine_through_the_whole_server(make_app, fakes, tmp_path):
    data = models_data("qwen3")
    data["models"]["qwen3"]["options"].update(max_chars=60, parallel_threads=3)
    path = tmp_path / "parallel.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    fakes.qwen.delay_for = lambda text: 0.05
    app = make_app(models_file=path)

    assert not call_tool_on(app, "start_speech", text=SENTENCES).is_error
    assert wait_until(lambda: call_tool_on(app, "speech_status").text == "finished", timeout=20)
    assert 1 < fakes.qwen.max_active <= 3
    assert fakes.sd.streams[-1].frames == len(fakes.qwen.calls) * CHUNK_FRAMES  # every piece was played, once


def test_stopping_a_parallel_speech_stops_the_work(make_app, fakes, tmp_path):
    data = models_data("qwen3")
    data["models"]["qwen3"]["options"].update(max_chars=60, parallel_threads=2)
    path = tmp_path / "parallel.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    fakes.qwen.delay_for = lambda text: 0.1
    app = make_app(models_file=path)
    long_text = " ".join(f"Sentence number {n} is here." for n in range(60))

    call_tool_on(app, "start_speech", text=long_text)
    assert wait_until(lambda: fakes.qwen.calls)
    assert call_tool_on(app, "stop_speech").text == "Speech stopped."
    time.sleep(0.8)
    assert len(fakes.qwen.calls) < 20  # nowhere near all the pieces of the text were generated
