"""Merge two HDF5 files by recursively unioning their group trees.

The first input file wins when a path is present in both files.  Groups that
already exist are traversed only far enough to add children that are missing;
an already existing dataset, or an already existing group child, is kept as
is.  The input files are never modified.
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import h5py


EXPECTED_ROOT_GROUPS = {"backward_scattering_data", "forward_scattering_data"}


class MergeError(RuntimeError):
    """Raised when input files cannot be safely merged."""


@dataclass
class MergeStats:
    groups_copied: int = 0
    datasets_copied: int = 0
    groups_skipped: int = 0
    datasets_skipped: int = 0


def _display(path: str) -> str:
    return path or "/"


def _copy_attributes(source: h5py.AttributeManager, target: h5py.AttributeManager) -> None:
    for name, value in source.items():
        target[name] = value


def _node_kind(node: h5py.HLObject) -> str:
    if isinstance(node, h5py.Group):
        return "group"
    if isinstance(node, h5py.Dataset):
        return "dataset"
    return type(node).__name__


def _validate_dataset_compatibility(
    first: h5py.Dataset, second: h5py.Dataset, path: str
) -> None:
    if first.dtype != second.dtype:
        raise MergeError(
            f"Dataset dtype conflict at {_display(path)}: "
            f"{first.dtype} != {second.dtype}"
        )
    if first.shape != second.shape:
        raise MergeError(
            f"Dataset shape conflict at {_display(path)}: "
            f"{first.shape} != {second.shape}"
        )


def _validate_overlapping_nodes(
    first: h5py.Group, second: h5py.Group, prefix: str = ""
) -> None:
    """Validate paths present in both files without reading dataset values."""

    for name in second:
        path = f"{prefix}/{name}"
        if name not in first:
            continue

        left = first[name]
        right = second[name]
        left_kind = _node_kind(left)
        right_kind = _node_kind(right)
        if left_kind != right_kind:
            raise MergeError(
                f"Node type conflict at {_display(path)}: "
                f"{left_kind} != {right_kind}"
            )

        if isinstance(left, h5py.Dataset) and isinstance(right, h5py.Dataset):
            _validate_dataset_compatibility(left, right, path)
        elif isinstance(left, h5py.Group) and isinstance(right, h5py.Group):
            _validate_overlapping_nodes(left, right, path)


def validate_inputs(first_path: Path, second_path: Path) -> tuple[Path, Path]:
    """Open and validate input files, returning their resolved paths."""

    first = first_path.expanduser().resolve()
    second = second_path.expanduser().resolve()
    if not first.is_file():
        raise MergeError(f"Input file does not exist: {first_path}")
    if not second.is_file():
        raise MergeError(f"Input file does not exist: {second_path}")
    if first == second:
        raise MergeError("The two input files must be different")

    try:
        with h5py.File(first, "r") as left, h5py.File(second, "r") as right:
            left_names = set(left.keys())
            right_names = set(right.keys())
            missing_left = EXPECTED_ROOT_GROUPS - left_names
            missing_right = EXPECTED_ROOT_GROUPS - right_names
            if missing_left:
                names = ", ".join(sorted(missing_left))
                raise MergeError(f"{first.name} is missing expected root group(s): {names}")
            if missing_right:
                names = ", ".join(sorted(missing_right))
                raise MergeError(f"{second.name} is missing expected root group(s): {names}")

            for name in left_names & right_names:
                left_node = left[name]
                right_node = right[name]
                if not isinstance(left_node, h5py.Group) or not isinstance(
                    right_node, h5py.Group
                ):
                    raise MergeError(
                        f"Root node must be a Group in both files: /{name}"
                    )

            _validate_overlapping_nodes(left, right)
    except OSError as exc:
        raise MergeError(f"Unable to open HDF5 input: {exc}") from exc

    return first, second


def _copy_new_node(source: h5py.HLObject, target_parent: h5py.Group, name: str) -> None:
    """Copy a complete new subtree using HDF5's native cross-file copy."""

    source.file.copy(
        source,
        target_parent,
        name=name,
        expand_soft=True,
        expand_external=True,
    )


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

def _merge_group(
    source: h5py.Group, target: h5py.Group, stats: MergeStats
) -> None:
    for name in source:
        source_node = source[name]
        if name not in target:
            _copy_new_node(source_node, target, name)
            copied_groups, copied_datasets = _count_subtree(source_node)
            stats.groups_copied += copied_groups
            stats.datasets_copied += copied_datasets
            continue

        target_node = target[name]
        if isinstance(source_node, h5py.Group):
            # The group itself is duplicated, so preserve the first source's
            # attributes and recurse only to find children absent from it.
            if not isinstance(target_node, h5py.Group):
                raise MergeError(f"Node type conflict during merge at {source_node.name}")
            stats.groups_skipped += 1
            _merge_group(source_node, target_node, stats)
        else:
            # Validation already checked type, dtype and shape.  The first
            # source owns both the data and attributes for duplicate datasets.
            stats.datasets_skipped += 1


def _default_output_name(first: Path, second: Path) -> str:
    names = f"{first.stem} {second.stem}".lower()
    if "vps" in names and "hps" not in names:
        return "merged_Vps.h5"
    if "hps" in names and "vps" not in names:
        return "merged_Hps.h5"
    return "merged.h5"


def merge_files(
    first_path: Path,
    second_path: Path,
    output_path: Path,
    *,
    force: bool = False,
) -> MergeStats:
    """Validate and merge two files into *output_path* atomically."""

    first, second = validate_inputs(first_path, second_path)
    output = output_path.expanduser().resolve()
    if output in {first, second}:
        raise MergeError("Output file must be different from both input files")
    if output.exists() and not force:
        raise MergeError(f"Output already exists; use --force to replace it: {output}")
    if not output.parent.exists():
        raise MergeError(f"Output directory does not exist: {output.parent}")

    temporary = output.with_name(f".{output.name}.{uuid.uuid4().hex}.tmp")
    stats = MergeStats()
    try:
        with h5py.File(first, "r") as left, h5py.File(second, "r") as right:
            with h5py.File(temporary, "w") as result:
                _copy_attributes(left.attrs, result.attrs)
                _merge_group(left, result, stats)
                _merge_group(right, result, stats)
                result.flush()
        validate_output(temporary, first, second)
        if output.exists() and not force:
            raise MergeError(f"Output appeared during merge: {output}")
        os.replace(temporary, output)
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


def validate_output(output_path: Path, first_path: Path, second_path: Path) -> None:
    """Verify that the output is readable and contains the expected union."""

    with h5py.File(output_path, "r") as output, h5py.File(first_path, "r") as first, h5py.File(
        second_path, "r"
    ) as second:
        for source in (first, second):
            for path, source_node in _iter_nodes(source):
                if path not in output:
                    raise MergeError(f"Output is missing node: {path}")
                output_node = output[path]
                if _node_kind(source_node) != _node_kind(output_node):
                    raise MergeError(f"Output node type mismatch at {path}")
                if isinstance(source_node, h5py.Dataset):
                    if isinstance(output_node, h5py.Dataset) and (
                        output_node.dtype != source_node.dtype
                        or output_node.shape != source_node.shape
                    ):
                        raise MergeError(f"Output dataset metadata mismatch at {path}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("first", type=Path, help="first input HDF5 file")
    parser.add_argument("second", type=Path, help="second input HDF5 file")
    parser.add_argument(
        "-o", "--output", type=Path, help="output HDF5 file (default is inferred from inputs)"
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="validate inputs without creating an output file",
    )
    parser.add_argument(
        "--force", action="store_true", help="replace an existing output file"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        first, second = validate_inputs(args.first, args.second)
        if args.validate_only:
            print(f"Validation passed: {first.name}, {second.name}")
            return 0

        output = args.output or Path(_default_output_name(first, second))
        stats = merge_files(first, second, output, force=args.force)
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
