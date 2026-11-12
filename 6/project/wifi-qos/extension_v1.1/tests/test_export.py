from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
try:
    import export_logs
except ImportError:
    export_logs=None
from restore_logs import restore


class LosslessExport(unittest.TestCase):
    def test_completed_run_restores_byte_exact_and_running_is_excluded(self):
        self.assertIsNotNone(export_logs,'lossless exporter missing')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);runs=root/'formal/runs';runs.mkdir(parents=True)
            done=runs/'test_run';done.mkdir();(done/'status.txt').write_text('PASS\n')
            (done/'config.json').write_text('{"kind":"formal"}\n')
            (done/'unicode.txt').write_bytes('中文\r\nlast line without newline'.encode())
            running=runs/'unfinished';running.mkdir();(running/'status.txt').write_text('RUNNING\n')
            index=export_logs.export(root,root/'merged')
            self.assertEqual(len(index['runs']),1)
            self.assertEqual(restore(root/'merged',root/'restored'),3)
            self.assertEqual((root/'restored/test_run/unicode.txt').read_bytes(),(done/'unicode.txt').read_bytes())

    def test_cross_batch_name_collision_is_rejected_before_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for batch in ['one','two']:
                run=root/batch/'runs/same';run.mkdir(parents=True);(run/'status.txt').write_text('PASS\n')
            with self.assertRaises(ValueError):export_logs.export(root,root/'merged')
            self.assertFalse((root/'merged/index.json').exists())

    def test_duplicate_index_names_are_rejected(self):
        import json
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);run=root/'formal/runs/one';run.mkdir(parents=True);(run/'status.txt').write_text('PASS\n')
            index=export_logs.export(root,root/'merged');index['runs'].append(index['runs'][0])
            (root/'merged/index.json').write_text(json.dumps(index))
            with self.assertRaises(ValueError):restore(root/'merged',root/'restored')


if __name__=='__main__':unittest.main()
