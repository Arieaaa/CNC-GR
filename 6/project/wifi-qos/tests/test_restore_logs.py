import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location('restore_logs', Path(__file__).resolve().parents[1]/'scripts/restore_logs.py')
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class RestoreLogsTests(unittest.TestCase):
    def fixture(self, root, path='run01/config.txt', content='中文\r\nsecond\n', digest=None):
        source=root/'merged'
        source.mkdir()
        (source/'run01.jsonl').write_text(json.dumps({'path':path,'content':content,
            'sha256':digest or hashlib.sha256(content.encode()).hexdigest()},ensure_ascii=False)+'\n')
        return source

    def test_restores_original_utf8_bytes_and_line_endings(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            source=self.fixture(root)
            self.assertEqual(module.restore(source,root/'logs'),1)
            self.assertEqual((root/'logs/run01/config.txt').read_bytes(),'中文\r\nsecond\n'.encode())

    def test_tampered_content_fails_before_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            source=self.fixture(root,digest='0'*64)
            with self.assertRaises(ValueError):module.restore(source,root/'logs')
            self.assertFalse((root/'logs').exists())

    def test_parent_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            source=self.fixture(root,path='../outside.txt')
            with self.assertRaises(ValueError):module.restore(source,root/'logs')
            self.assertFalse((root/'outside.txt').exists())

    def test_existing_directory_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            source=self.fixture(root)
            (root/'logs').mkdir()
            (root/'logs/keep.txt').write_text('keep')
            with self.assertRaises(FileExistsError):module.restore(source,root/'logs')
            self.assertEqual((root/'logs/keep.txt').read_text(),'keep')

    def test_duplicate_paths_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            source=self.fixture(root)
            f=source/'run01.jsonl'
            f.write_text(f.read_text()*2)
            with self.assertRaises(ValueError):module.restore(source,root/'logs')


if __name__ == '__main__':unittest.main()
