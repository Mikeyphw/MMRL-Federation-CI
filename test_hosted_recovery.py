#!/usr/bin/env python3
"""Local behavior checks; no GitHub or Android execution."""
import json
import pathlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import hosted
import native_event_capture

class Recovery(unittest.TestCase):
    def test_subprocess_failure_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            ev=pathlib.Path(tmp)
            def failing(coord,ev):
                hosted.stage('install-pinned-native-devtool')
                raise subprocess.CalledProcessError(2,['private-command','private-secret'])
            with patch.object(hosted,'main',failing):
                self.assertEqual(hosted.entry(ev,ev),2)
            r=json.loads((ev/'terminal-receipt.json').read_text())
            self.assertEqual((r['status'],r['stage'],r['exit_code']),('failed','install-pinned-native-devtool',2))
            self.assertNotIn('private-secret',json.dumps(r))
            self.assertFalse(r['release_qualified'])
    def test_generic_failure_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            ev=pathlib.Path(tmp)
            with patch.object(hosted,'main',side_effect=RuntimeError('private-data')):
                self.assertEqual(hosted.entry(ev,ev),1)
            r=json.loads((ev/'terminal-receipt.json').read_text())
            self.assertEqual(r['exception_type'],'RuntimeError')
            self.assertNotIn('private-data',json.dumps(r))
    def test_completed_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            ev=pathlib.Path(tmp)
            with patch.object(hosted,'main',return_value=None):
                self.assertEqual(hosted.entry(ev,ev),0)
            self.assertEqual(json.loads((ev/'terminal-receipt.json').read_text())['status'],'completed')
    def test_event_projection(self):
        r=native_event_capture.capture(SimpleNamespace(run_id='example',node_id='node',exit_code=0,argv=['secret'],metadata={'token':'secret'}))
        self.assertEqual(r['node_id'],'node'); self.assertEqual(r['exit_code'],0)
        self.assertNotIn('secret',json.dumps(r))
    def test_launcher_no_version(self):
        src=pathlib.Path(hosted.__file__).read_text()
        self.assertNotIn("cmd(executable,'--version')",src)
        self.assertIn("cmd(executable, '--help')",src)
        self.assertIn("parse_args(['-r','.', 'federation','plan','validate-both'])",src)
    def test_source_and_drift_guards_retained(self):
        src=pathlib.Path(hosted.__file__).read_text()
        for guard in ('PORTABLE_','HOST_LOCAL_LOCK_NOT_MATCHED','HOST_DAG_REFUSED','EXECUTED_LOCK_CHANGED',"'--drift-policy','fail'",'POSTRUN_HEAD_CHANGED'):
            self.assertIn(guard,src)
        self.assertNotIn('allow-if-equivalent',src)
    def test_workflow_preserves_early_receipt(self):
        data=(pathlib.Path(hosted.__file__).parent/'.github/workflows/n05g-federation.yml').read_text()
        self.assertIn('job-start.json',data); self.assertIn('if: always()',data); self.assertIn('if-no-files-found: error',data)
        self.assertLess(data.index('job-start.json'),data.index('Run source-bound native federation'))
if __name__=='__main__': unittest.main(verbosity=2)
