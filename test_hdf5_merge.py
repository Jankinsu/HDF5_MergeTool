import tempfile
import unittest
from pathlib import Path

import h5py
import numpy as np

from hdf5_merge import MergeError, merge_files, validate_inputs


def make_input(path: Path, group_name: str, value: float, duplicate: bool = False) -> None:
    with h5py.File(path, "w") as handle:
        handle.attrs["source"] = path.stem
        backward = handle.create_group("backward_scattering_data")
        forward = handle.create_group("forward_scattering_data")
        scene = backward.create_group(group_name)
        scene.attrs["owner"] = path.stem
        scene.create_dataset("bsc_alpha", data=np.array([value, value + 1]))
        fscene = forward.create_group(group_name)
        segments = fscene.create_group("segments")
        contour = segments.create_group("scNo0")
        contour.create_dataset("contourNo0", data=np.array([[value, 0, 1.0]]))
        if duplicate:
            scene.create_dataset("duplicate", data=np.array([value]))


class MergeTests(unittest.TestCase):
    def test_union_and_first_source_wins(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "182Vps.h5"
            second = root / "352Vps.h5"
            output = root / "merged_Vps.h5"
            make_input(first, "theta_10.0_phi_182.0", 1.0)
            make_input(second, "theta_10.0_phi_352.0", 2.0)
            merge_files(first, second, output)
            with h5py.File(output, "r") as handle:
                self.assertEqual(handle.attrs["source"], "182Vps")
                self.assertIn("theta_10.0_phi_182.0", handle["backward_scattering_data"])
                self.assertIn("theta_10.0_phi_352.0", handle["backward_scattering_data"])

    def test_duplicate_group_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first.h5"
            second = root / "second.h5"
            output = root / "merged.h5"
            make_input(first, "same", 1.0, duplicate=True)
            make_input(second, "same", 9.0, duplicate=False)
            merge_files(first, second, output)
            with h5py.File(output, "r") as handle:
                scene = handle["backward_scattering_data/same"]
                self.assertEqual(scene.attrs["owner"], "first")
                self.assertIn("duplicate", scene)
                np.testing.assert_array_equal(scene["bsc_alpha"][:], [1.0, 2.0])

    def test_conflicting_node_type_fails_before_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first.h5"
            second = root / "second.h5"
            output = root / "merged.h5"
            make_input(first, "same", 1.0)
            make_input(second, "same", 2.0)
            with h5py.File(second, "a") as handle:
                del handle["backward_scattering_data/same"]
                handle["backward_scattering_data"].create_dataset("same", data=[1])
            with self.assertRaises(MergeError):
                validate_inputs(first, second)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
