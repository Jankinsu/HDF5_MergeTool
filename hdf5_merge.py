"""Merge two HDF5 files by scene-group paths."""

from __future__ import annotations

import argparse
import os
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

import h5py


PROJECT_VERSION = "0.1.0"
EXPECTED_ROOT_GROUPS = ("backward_scattering_data", "forward_scattering_data")
ProgressCallback = Callable[[str], None]


class MergeError(RuntimeError):
    """Raised when HDF5 files cannot be safely merged."""


@dataclass
class MergeStats:
    groups_copied: int = 0
    datasets_copied: int = 0
    groups_skipped: int = 0
    datasets_skipped: int = 0


class ProgressReporter:
    """Print progress messages with elapsed time."""

    def __init__(self, output: Callable[[str], None] = print) -> None:
        self.started = time.perf_counter()
        self.output = output

    @property
    def elapsed(self) -> float:
        return time.perf_counter() - self.started

    def __call__(self, message: str) -> None:
        self.output(f"{message}, elapsed {self.elapsed:.1f}s")


def _display(path: str) -> str:
    return path or "/"


def _copy_attributes(source: h5py.AttributeManager, target: h5py.AttributeManager) -> None:
    for name, value in source.items():
        target[name] = value


def _node_kind(node: h5py.HLObject) -> str:
    if isinstance(node, h5py.Group):
        return "Group"
    if isinstance(node, h5py.Dataset):
        return "Dataset"
    return type(node).__name__


def _detect_family(path: Path) -> str:
    stem = path.stem.lower()
    matches = [family for family in ("vps", "hps") if family in stem]
    if len(matches) != 1:
        raise MergeError(
            f"Cannot determine input type from filename '{path.name}'. "
            "Filename must contain exactly one of 'Vps' or 'Hps'."
        )
    return matches[0]


def _validate_dataset_compatibility(
    first: h5py.Dataset, second: h5py.Dataset, path: str
) -> None:
    if first.dtype != second.dtype:
        raise MergeError(
            f"Dataset dtype conflict at {_display(path)}: "
            f"{first.dtype} != {second.dtype}. "
            "Rename or regenerate the incompatible input files."
        )
    if first.shape != second.shape:
        raise MergeError(
            f"Dataset shape conflict at {_display(path)}: "
            f"{first.shape} != {second.shape}."
        )


def _validate_root_children(
    first: h5py.Group, second: h5py.Group, prefix: str
) -> None:
    """Validate children that can actually be merged.

    An already existing scene Group is skipped as a whole, so its descendants
    are intentionally not compared or copied from the second input.
    """

    for name in second:
        if name not in first:
            continue
        path = f"{prefix}/{name}"
        left = first[name]
        right = second[name]
        if _node_kind(left) != _node_kind(right):
            raise MergeError(
                f"Node type conflict at {_display(path)}: "
                f"{_node_kind(left)} != {_node_kind(right)}"
            )
        if isinstance(left, h5py.Dataset) and isinstance(right, h5py.Dataset):
            _validate_dataset_compatibility(left, right, path)
        # Same-name Groups are intentionally skipped as complete subtrees.


def validate_inputs(
    first_path: Path,
    second_path: Path,
    *,
    progress: ProgressCallback | None = None,
) -> tuple[Path, Path]:
    """Open and validate the two input files."""

    if progress:
        progress("[progress] validating input files and compatibility...")

    first = first_path.expanduser().resolve()
    second = second_path.expanduser().resolve()
    if not first.is_file():
        raise MergeError(f"Input file does not exist: {first_path}")
    if not second.is_file():
        raise MergeError(f"Input file does not exist: {second_path}")
    if first == second:
        raise MergeError("The two input files must be different.")

    first_family = _detect_family(first)
    second_family = _detect_family(second)
    if first_family != second_family:
        raise MergeError(
            f"Input type mismatch: {first.name} is {first_family.upper()}, "
            f"but {second.name} is {second_family.upper()}. "
            "Merge two Vps files or two Hps files."
        )

    try:
        with h5py.File(first, "r") as left, h5py.File(second, "r") as right:
            left_names = set(left.keys())
            right_names = set(right.keys())
            missing_left = set(EXPECTED_ROOT_GROUPS) - left_names
            missing_right = set(EXPECTED_ROOT_GROUPS) - right_names
            if missing_left:
                raise MergeError(
                    f"{first.name} is missing root Group(s): "
                    f"{', '.join(sorted(missing_left))}."
                )
            if missing_right:
                raise MergeError(
                    f"{second.name} is missing root Group(s): "
                    f"{', '.join(sorted(missing_right))}."
                )

            for root_name in EXPECTED_ROOT_GROUPS:
                left_root = left[root_name]
                right_root = right[root_name]
                if not isinstance(left_root, h5py.Group) or not isinstance(
                    right_root, h5py.Group
                ):
                    raise MergeError(
                        f"Root path '/{root_name}' must be a Group in both inputs."
                    )
                _validate_root_children(
                    left_root, right_root, f"/{root_name}"
                )
    except OSError as exc:
        raise MergeError(f"Unable to open HDF5 input: {exc}") from exc

    if progress:
        progress(f"[progress] input validation complete: {first.name} + {second.name}")
    return first, second


def _count_subtree(node: h5py.HLObject) -> tuple[int, int]:
    if isinstance(node, h5py.Dataset):
        return 0, 1
    groups = 1
    datasets = 0
    if isinstance(node, h5py.Group):
        for child in node.values():
            child_groups, child_datasets = _count_subtree(child)
            groups += child_groups
            datasets += child_datasets
    return groups, datasets


def _copy_new_node(source: h5py.HLObject, target_parent: h5py.Group, name: str) -> None:
    source.file.copy(
        source,
        target_parent,
        name=name,
        expand_soft=True,
        expand_external=True,
    )


def _merge_root_group(
    source: h5py.Group,
    target: h5py.Group,
    stats: MergeStats,
    *,
    source_label: str,
    progress: ProgressCallback | None = None,
) -> None:
    """Merge scene children; a duplicate scene Group is skipped entirely."""

    names = list(source)
    total = len(names)
    progress_step = max(1, total // 20)
    for index, name in enumerate(names, start=1):
        source_node = source[name]
        if name not in target:
            _copy_new_node(source_node, target, name)
            copied_groups, copied_datasets = _count_subtree(source_node)
            stats.groups_copied += copied_groups
            stats.datasets_copied += copied_datasets
        elif isinstance(source_node, h5py.Group):
            stats.groups_skipped += 1
        else:
            stats.datasets_skipped += 1

        if progress and (index == 1 or index == total or index % progress_step == 0):
            percent = index * 100 // total if total else 100
            progress(
                f"[progress] copying {source_label}: {source.name} "
                f"{percent}% ({index}/{total})"
            )


def _default_output_name(first: Path, second: Path) -> str:
    family = _detect_family(first)
    if family == "vps":
        return "merged_Vps.h5"
    return "merged_Hps.h5"


def merge_files(
    first_path: Path,
    second_path: Path,
    output_path: Path,
    *,
    force: bool = False,
    progress: ProgressCallback | None = None,
) -> MergeStats:
    """Validate and merge two files into output_path atomically."""

    first, second = validate_inputs(first_path, second_path, progress=progress)
    output = output_path.expanduser().resolve()
    if output in {first, second}:
        raise MergeError("Output file must be different from both input files.")
    if output.exists() and not force:
        raise MergeError(
            f"Output already exists: {output}. Choose another path or use --force."
        )
    if not output.parent.exists():
        raise MergeError(f"Output directory does not exist: {output.parent}")

    temporary = output.with_name(f".{output.name}.{uuid.uuid4().hex}.tmp")
    stats = MergeStats()
    try:
        with h5py.File(first, "r") as left, h5py.File(second, "r") as right:
            with h5py.File(temporary, "w") as result:
                _copy_attributes(left.attrs, result.attrs)
                if progress:
                    progress(f"[progress] writing temporary output: {temporary.name}")
                for source, source_path in ((left, first), (right, second)):
                    if progress:
                        progress(f"[progress] copying source: {source_path.name}")
                    for root_name in EXPECTED_ROOT_GROUPS:
                        source_root = source[root_name]
                        if root_name not in result:
                            target_root = result.create_group(root_name)
                            _copy_attributes(source_root.attrs, target_root.attrs)
                        else:
                            target_root = result[root_name]
                        _merge_root_group(
                            source_root,
                            target_root,
                            stats,
                            source_label=source_path.name,
                            progress=progress,
                        )
                result.flush()
        if progress:
            progress("[progress] temporary write complete; validating output...")
        validate_output(temporary, first, second)
        os.replace(temporary, output)
        if progress:
            progress(f"[progress] output validation complete: {output.name}")
    except Exception:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return stats


def _iter_nodes(group: h5py.Group) -> Iterable[tuple[str, h5py.HLObject]]:
    for name in group:
        node = group[name]
        yield node.name, node
        if isinstance(node, h5py.Group):
            yield from _iter_nodes(node)


def _validate_output_subtree(
    output: h5py.File, source_node: h5py.HLObject
) -> None:
    path = source_node.name
    if path not in output:
        raise MergeError(f"Output is missing node: {path}")
    output_node = output[path]
    if _node_kind(source_node) != _node_kind(output_node):
        raise MergeError(f"Output node type mismatch at {path}")
    if isinstance(source_node, h5py.Dataset):
        if output_node.dtype != source_node.dtype or output_node.shape != source_node.shape:
            raise MergeError(f"Output dataset metadata mismatch at {path}")
    elif isinstance(source_node, h5py.Group):
        for child in source_node.values():
            _validate_output_subtree(output, child)


def validate_output(output_path: Path, first_path: Path, second_path: Path) -> None:
    """Verify output, allowing complete duplicate scene Groups to be skipped."""

    with h5py.File(output_path, "r") as output, h5py.File(
        first_path, "r"
    ) as first, h5py.File(second_path, "r") as second:
        for path, source_node in _iter_nodes(first):
            _validate_output_subtree(output, source_node)

        for root_name in EXPECTED_ROOT_GROUPS:
            first_root = first[root_name]
            second_root = second[root_name]
            for name, source_node in second_root.items():
                if name in first_root and isinstance(source_node, h5py.Group):
                    continue
                _validate_output_subtree(output, source_node)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("first", type=Path, help="first input HDF5 file")
    parser.add_argument("second", type=Path, help="second input HDF5 file")
    parser.add_argument(
        "-o", "--output", type=Path, help="output HDF5 file (default is inferred)"
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="validate inputs without creating an output file",
    )
    parser.add_argument(
        "--force", action="store_true", help="replace an existing output file"
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {PROJECT_VERSION}"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    reporter = ProgressReporter()
    try:
        if args.validate_only:
            first, second = validate_inputs(
                args.first, args.second, progress=reporter
            )
            print(f"Validation passed: {first.name}, {second.name}")
            print(f"Completed in {reporter.elapsed:.1f}s")
            return 0

        output = args.output or Path(_default_output_name(args.first, args.second))
        stats = merge_files(
            args.first,
            args.second,
            output,
            force=args.force,
            progress=reporter,
        )
        print(f"[progress] completed in {reporter.elapsed:.1f}s")
        print(f"Merged successfully: {output.resolve()}")
        print(
            "Groups copied/skipped: "
            f"{stats.groups_copied}/{stats.groups_skipped}; "
            "datasets copied/skipped: "
            f"{stats.datasets_copied}/{stats.datasets_skipped}"
        )
        return 0
    except (MergeError, OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
