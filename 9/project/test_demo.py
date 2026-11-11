import pathlib,sys,unittest,importlib.util,tempfile,json
sys.path.insert(0,str(pathlib.Path('9/project').resolve()))
import demo
class Checks(unittest.TestCase):
 def test_missing_manifest_file(self):
  with tempfile.TemporaryDirectory() as d:
   old=demo.ROOT;demo.ROOT=pathlib.Path(d)/'project';demo.ROOT.mkdir();(demo.ROOT/'manifest.json').write_text(json.dumps({'absent':'abc'}))
   try:self.assertTrue(demo.verify())
   finally:demo.ROOT=old
 def test_offline_browser(self):
  self.assertEqual(demo.browse(),0);self.assertIn('smoke_20261111', (demo.ROOT/'index.html').read_text(encoding='utf8'))
 def test_actual_pass(self):
  p=next((demo.ROOT/'evidence').glob('smoke_*'));self.assertEqual((p/'status.txt').read_text().strip(),'PASS');self.assertEqual(json.loads((p/'config.json').read_text())['operator'],'wifi09')
unittest.main()
