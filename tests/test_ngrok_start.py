import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from server.ngrok_start import start_ngrok

class NgrokTests(unittest.TestCase):
    def test_existing_agent_is_reused(self):
        response=io.BytesIO(json.dumps({'tunnels':[{'public_url':'https://example.test','config':{'addr':'http://localhost:8765'}}]}).encode())
        with patch('urllib.request.urlopen',return_value=response), patch('subprocess.Popen') as spawn:
            self.assertIn('already running',start_ngrok(Path('.'),8765))
            spawn.assert_not_called()

    def test_task_is_preferred(self):
        with patch('urllib.request.urlopen',side_effect=OSError), patch('shutil.which',return_value='powershell.exe'), patch('subprocess.run',return_value=Mock(returncode=0)), patch('subprocess.Popen') as spawn:
            self.assertIn('startup requested',start_ngrok(Path('.'),8765))
            spawn.assert_not_called()

    def test_independent_fallback_uses_no_shell(self):
        with tempfile.TemporaryDirectory() as folder:
            exe=Path(folder)/'ngrok.exe'
            exe.touch()
            with patch('urllib.request.urlopen',side_effect=OSError), patch('shutil.which',return_value=None), patch.dict('os.environ',{'GOLD_AI_NGROK_EXE':str(exe),'GOLD_AI_NGROK_CONFIG':''}), patch('subprocess.Popen',return_value=Mock(pid=123)) as spawn:
                self.assertIn('independently',start_ngrok(Path(folder),8765))
                self.assertEqual(spawn.call_args.args[0][-1],'8765')
                self.assertTrue(spawn.call_args.kwargs['close_fds'])
                self.assertNotIn('shell',spawn.call_args.kwargs)

    def test_task_error_does_not_launch_duplicate_agent(self):
        with patch('urllib.request.urlopen',side_effect=OSError), patch('shutil.which',return_value='powershell.exe'), patch('subprocess.run',return_value=Mock(returncode=1)), patch('subprocess.Popen') as spawn:
            with self.assertRaisesRegex(RuntimeError,'permissions'):
                start_ngrok(Path('.'),8765)
            spawn.assert_not_called()
