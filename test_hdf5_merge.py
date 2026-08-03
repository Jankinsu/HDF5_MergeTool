from contextlib import redirect_stdout
from io import StringIO
import tempfile
import unittest
from pathlib import Path

import h5py
import numpy as np

from hdf5_merge import MergeError, ProgressReporter, main, merge_files, validate_inputs


def make_input(path: Path, group_name: str, value: float, duplicate: bool = False) -> None:
    with h5py.File(path, "w") as handle:
        handle.attrs["source"] = path.stem
        backward = handle.create_group("backward_scattering_data")
        forward = handle.create_group("forward_scattering_data")
        scene = backward.create_group(group_name)
        scene.attrs["owner"] = path.stem
        scene.create_dataset("bsc_alpha", data=np.array([value, value + 1]))
        if duplicate:
            scene.create_dataset("only_in_second", data=np.array([value]))
        fscene = forward.create_group(group_name)
        segments = fscene.create_group("segments")
        contour = segments.create_group("scNo0")
        contour.create_dataset("contourNo0", data=np.array([[value, 0, 1.0]]))


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

    def test_duplicate_scene_group_is_skipped_as_a_whole(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "182Vps.h5"
            second = root / "352Vps.h5"
            output = root / "merged_Vps.h5"
            make_input(first, "theta_10.0_phi_182.0", 1.0)
            make_input(second, "theta_10.0_phi_182.0", 9.0, duplicate=True)
            merge_files(first, second, output)
            with h5py.File(output, "r") as handle:
                scene = handle["backward_scattering_data/theta_10.0_phi_182.0"]
                self.assertEqual(scene.attrs["owner"], "182Vps")
                self.assertNotIn("only_in_second", scene)
                np.testing.assert_array_equal(scene["bsc_alpha"][:], [1.0, 2.0])

    def test_mixed_vps_and_hps_inputs_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "182Vps.h5"
            second = root / "352Hps.h5"
            make_input(first, "scene", 1.0)
            make_input(second, "scene", 2.0)
            with self.assertRaisesRegex(MergeError, "Input type mismatch"):
                validate_inputs(first, second)

    def test_unknown_input_family_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first.h5"
            second = root / "352Vps.h5"
            make_input(first, "scene", 1.0)
            make_input(second, "scene2", 2.0)
            with self.assertRaisesRegex(MergeError, "Cannot determine input type"):
                validate_inputs(first, second)

    def test_progress_callback_reports_stages_and_elapsed_time(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "182Vps.h5"
            second = root / "352Vps.h5"
            output = root / "merged_Vps.h5"
            make_input(first, "scene1", 1.0)
            make_input(second, "scene2", 2.0)
            messages: list[str] = []
            merge_files(first, second, output, progress=ProgressReporter(messages.append))
            self.assertTrue(any("input validation complete" in message for message in messages))
            self.assertTrue(any("temporary write complete" in message for message in messages))
            self.assertTrue(all("elapsed" in message for message in messages))

    def test_existing_output_requires_force(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "182Vps.h5"
            second = root / "352Vps.h5"
            output = root / "merged_Vps.h5"
            make_input(first, "scene1", 1.0)
            make_input(second, "scene2", 2.0)
            output.write_bytes(b"existing")
            with self.assertRaisesRegex(MergeError, "already exists"):
                merge_files(first, second, output)
            merge_files(first, second, output, force=True)
            with h5py.File(output, "r") as handle:
                self.assertIn("backward_scattering_data", handle)

    def test_validate_only_does_not_create_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "182Vps.h5"
            second = root / "352Vps.h5"
            output = root / "not_created.h5"
            make_input(first, "scene1", 1.0)
            make_input(second, "scene2", 2.0)
            with redirect_stdout(StringIO()):
                result = main([str(first), str(second), "--validate-only", "--output", str(output)])
            self.assertEqual(result, 0)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
