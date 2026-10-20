"""Command-line entry point for one bounded hidden-flow solve."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from tempfile import SpooledTemporaryFile
from typing import Any, BinaryIO

from .solver import (
    MAXIMUM_BATCH_INPUT_BYTES,
    MAXIMUM_BATCH_REQUESTS,
    MAXIMUM_BATCH_RESULT_BYTES,
    MAXIMUM_INPUT_BYTES,
    MAXIMUM_RESULT_BYTES,
    HiddenFlowInputError,
    iter_canonical_json_bytes,
    load_request_bytes,
    solve_request,
)


def _add_aggregate_bytes(
    current: int,
    byte_length: int,
    maximum_bytes: int,
    resource: str,
) -> int:
    next_total = current + byte_length
    if byte_length < 0 or next_total > maximum_bytes:
        raise HiddenFlowInputError(
            f"{resource} exceeds the {maximum_bytes} aggregate byte limit"
        )
    return next_total


def _read_input(path: str) -> bytes:
    if path == "-":
        return sys.stdin.buffer.read(MAXIMUM_INPUT_BYTES + 1)

    input_path = Path(path)
    size = input_path.stat().st_size
    if not input_path.is_file():
        raise HiddenFlowInputError("input is not a regular file")
    if size > MAXIMUM_INPUT_BYTES:
        raise HiddenFlowInputError("input exceeds the 16 MiB byte limit")
    with input_path.open("rb") as stream:
        raw = stream.read(MAXIMUM_INPUT_BYTES + 1)
    if len(raw) != size:
        raise HiddenFlowInputError("input size changed while reading")
    return raw


def _write_bounded_output(
    stream: BinaryIO,
    value: Any,
    maximum_bytes: int,
) -> int:
    written = 0
    for chunk in iter_canonical_json_bytes(value):
        next_written = written + len(chunk)
        if next_written > maximum_bytes:
            raise HiddenFlowInputError(
                f"output exceeds the {maximum_bytes} byte limit"
            )
        if stream.write(chunk) != len(chunk):
            raise OSError("could not write the complete solver output")
        written = next_written
    return written


def _write_output(
    path: str,
    value: Any,
    maximum_bytes: int = MAXIMUM_RESULT_BYTES,
) -> int:
    if path == "-":
        with SpooledTemporaryFile(max_size=1024 * 1024, mode="w+b") as staged:
            written = _write_bounded_output(staged, value, maximum_bytes)
            staged.seek(0)
            while True:
                chunk = staged.read(64 * 1024)
                if not chunk:
                    break
                sys.stdout.buffer.write(chunk)
        sys.stdout.buffer.flush()
        return written
    output_path = Path(path)
    created = False
    complete = False
    try:
        with output_path.open("xb") as stream:
            created = True
            written = _write_bounded_output(stream, value, maximum_bytes)
        complete = True
    finally:
        if created and not complete:
            try:
                output_path.unlink()
            except FileNotFoundError:
                pass
    return written


def _solve_one(input_path: str, output_path: str) -> None:
    raw = _read_input(input_path)
    request = load_request_bytes(raw)
    result = solve_request(request, raw)
    _write_output(output_path, result)


def _run_batch(directory: str, count: int) -> None:
    if count < 1 or count > MAXIMUM_BATCH_REQUESTS:
        raise HiddenFlowInputError(
            f"batch count must be between 1 and {MAXIMUM_BATCH_REQUESTS}"
        )
    root = Path(directory)
    if not root.is_dir():
        raise HiddenFlowInputError("batch directory is not a directory")
    request_paths = [
        root / f"request-{index:03d}.json" for index in range(count)
    ]
    result_paths = [
        root / f"result-{index:03d}.json" for index in range(count)
    ]
    aggregate_input_bytes = 0
    for path in request_paths:
        if not path.is_file():
            raise HiddenFlowInputError(
                f"batch request {path.name!r} is not a regular file"
            )
        size = path.stat().st_size
        if size > MAXIMUM_INPUT_BYTES:
            raise HiddenFlowInputError(
                f"batch request {path.name!r} exceeds the 16 MiB byte limit"
            )
        aggregate_input_bytes = _add_aggregate_bytes(
            aggregate_input_bytes,
            size,
            MAXIMUM_BATCH_INPUT_BYTES,
            "batch input",
        )

    complete = False
    created_results: list[Path] = []
    actual_input_bytes = 0
    aggregate_result_bytes = 0
    try:
        for index, (input_path, output_path) in enumerate(
            zip(request_paths, result_paths)
        ):
            raw = _read_input(str(input_path))
            actual_input_bytes = _add_aggregate_bytes(
                actual_input_bytes,
                len(raw),
                MAXIMUM_BATCH_INPUT_BYTES,
                "batch input",
            )
            request = load_request_bytes(raw)
            result = solve_request(request, raw)
            remaining = MAXIMUM_BATCH_RESULT_BYTES - aggregate_result_bytes
            if remaining <= 0:
                raise HiddenFlowInputError(
                    "batch output exceeds the "
                    f"{MAXIMUM_BATCH_RESULT_BYTES} aggregate byte limit"
                )
            output_limit = min(MAXIMUM_RESULT_BYTES, remaining)
            try:
                written = _write_output(
                    str(output_path),
                    result,
                    maximum_bytes=output_limit,
                )
            except HiddenFlowInputError as error:
                if output_limit < MAXIMUM_RESULT_BYTES:
                    raise HiddenFlowInputError(
                        "batch output exceeds the "
                        f"{MAXIMUM_BATCH_RESULT_BYTES} aggregate byte limit "
                        f"at result {index}"
                    ) from error
                raise
            created_results.append(output_path)
            aggregate_result_bytes = _add_aggregate_bytes(
                aggregate_result_bytes,
                written,
                MAXIMUM_BATCH_RESULT_BYTES,
                "batch output",
            )
        complete = True
    finally:
        if not complete:
            for path in created_results:
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Solve one FlowBlind hidden-flow support request."
    )
    parser.add_argument("--input", help="Input JSON path, or - for stdin.")
    parser.add_argument(
        "--output", help="Output JSON path, or - for stdout."
    )
    parser.add_argument(
        "--batch-directory",
        help="Internal directory containing request-NNN.json batch inputs.",
    )
    parser.add_argument(
        "--batch-count",
        type=int,
        help="Internal count of request-NNN.json batch inputs.",
    )
    arguments = parser.parse_args(argv)
    batch_mode = (
        arguments.batch_directory is not None or arguments.batch_count is not None
    )
    if batch_mode:
        if (
            arguments.batch_directory is None
            or arguments.batch_count is None
            or arguments.input is not None
            or arguments.output is not None
        ):
            parser.error(
                "batch mode requires --batch-directory and --batch-count only"
            )
    elif arguments.input is None or arguments.output is None:
        parser.error("single mode requires --input and --output")

    try:
        if batch_mode:
            _run_batch(arguments.batch_directory, arguments.batch_count)
        else:
            _solve_one(arguments.input, arguments.output)
    except (HiddenFlowInputError, OSError) as error:
        print(f"hidden-flow-solver: {error}", file=sys.stderr)
        return 2
    return 0
