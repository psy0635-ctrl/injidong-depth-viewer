"""Input path boundaries; temporary files are synthetic test data only."""
import tempfile
import unittest
from pathlib import Path
import paths


class PortablePathTests(unittest.TestCase):
    def test_resolver_is_available(self):
        self.assertTrue(callable(paths.resolve_recorded))

    def test_relative_mapping_is_confined(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            self.assertEqual(paths._relative(root, 'data/frame.json'), root/'data/frame.json')
            for value in ('../escape', '/absolute', 'X:/absolute', 'folder\\file', ''):
                with self.subTest(value=value), self.assertRaises(ValueError):
                    paths._relative(root, value)

    def test_unknown_path_has_no_fallback_even_if_file_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/'metadata.json'
            p.write_text('{}', encoding='utf-8')
            with self.assertRaises(ValueError):
                paths.resolve_recorded(p)

    def test_missing_required_file_explains_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(FileNotFoundError, '누락.*외부 입력'):
                paths.required(Path(tmp)/'missing.npz')

    def test_runtime_code_stays_inside_public_app(self):
        for p in (paths.CODE, paths.BASELINE, paths.COLOR):
            self.assertTrue(p.is_relative_to(paths.REPOSITORY))
