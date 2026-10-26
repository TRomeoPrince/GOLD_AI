import errno
import json
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from server.atomic_json import atomic_write_json, FileBusyError
from server import personal_store

class AtomicStatusTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.target=self.root/'logs/personal_status.json'
        atomic_write_json(self.target,{'state':'OLD','updated':1})
    def tearDown(self):self.temp.cleanup()
    def test_windows_lock_retries_then_replaces_complete_json(self):
        replace=os.replace
        calls=[]
        def locked_then_replace(src,dst):
            calls.append(str(src))
            self.assertEqual(json.loads(self.target.read_text())['state'],'OLD')
            if len(calls)<3:
                error=PermissionError(errno.EACCES,'locked')
                error.winerror=5
                raise error
            replace(src,dst)
        with patch('server.atomic_json.os.replace',side_effect=locked_then_replace),patch('server.atomic_json.time.sleep') as sleep:
            atomic_write_json(self.target,{'state':'READY','updated':2})
        self.assertEqual(len(calls),3)
        self.assertEqual(sleep.call_count,2)
        self.assertEqual(json.loads(self.target.read_text()),{'state':'READY','updated':2})
        self.assertFalse(list(self.target.parent.glob('*.tmp')))
    def test_persistent_status_lock_keeps_worker_alive_and_old_snapshot(self):
        with patch('server.personal_store.Path.cwd',return_value=self.root),patch('server.atomic_json.os.replace',side_effect=PermissionError('locked')),patch('server.atomic_json.time.sleep'),patch.dict(personal_store._status_warnings,{},clear=True),self.assertLogs(level='WARNING') as logs:
            self.assertFalse(personal_store.write_status('personal',state='READY'))
        self.assertEqual(json.loads(self.target.read_text())['state'],'OLD')
        self.assertIn('keeping last valid file',logs.output[0])
        self.assertFalse(list(self.target.parent.glob('*.tmp')))
    def test_settings_lock_reports_failure_instead_of_claiming_save(self):
        terminal=self.root/'terminal64.exe'
        terminal.touch()
        settings={'terminal_path':str(terminal),'login':1,'server':'Broker'}
        with patch.object(personal_store,'settings_path',return_value=self.target),patch('server.atomic_json.os.replace',side_effect=PermissionError('locked')),patch('server.atomic_json.time.sleep'):
            with self.assertRaises(FileBusyError):personal_store.save_settings(settings)
        self.assertEqual(json.loads(self.target.read_text())['state'],'OLD')
    def test_other_io_errors_are_not_silently_swallowed(self):
        with patch('server.atomic_json.os.replace',side_effect=OSError(errno.EIO,'disk failure')) as replace:
            with self.assertRaises(OSError):atomic_write_json(self.target,{'state':'READY'})
            replace.assert_called_once()
        self.assertEqual(json.loads(self.target.read_text())['state'],'OLD')
    def test_concurrent_writers_use_unique_complete_files(self):
        payloads=[{'state':'READY','writer':i,'data':'x'*10000} for i in range(4)]
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda value:atomic_write_json(self.target,value),payloads))
        self.assertIn(json.loads(self.target.read_text()),payloads)
        self.assertFalse(list(self.target.parent.glob('*.tmp')))
    @unittest.skipUnless(os.name=='nt','Windows sharing semantics')
    def test_real_windows_delete_sharing_lock_is_retried(self):
        import ctypes
        import threading
        import time
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.CreateFileW.argtypes=[ctypes.c_wchar_p,ctypes.c_ulong,ctypes.c_ulong,ctypes.c_void_p,ctypes.c_ulong,ctypes.c_ulong,ctypes.c_void_p]
        kernel.CreateFileW.restype=ctypes.c_void_p
        kernel.CloseHandle.argtypes=[ctypes.c_void_p]
        handle=kernel.CreateFileW(str(self.target),0x80000000,3,None,3,0x80,None)
        self.assertNotEqual(handle,ctypes.c_void_p(-1).value)
        released=threading.Event()
        lock=threading.Lock()
        def release():
            with lock:
                if not released.is_set():
                    kernel.CloseHandle(handle)
                    released.set()
        timer=threading.Timer(.08,release)
        timer.start()
        started=time.monotonic()
        try:
            atomic_write_json(self.target,{'state':'READY'})
            self.assertGreaterEqual(time.monotonic()-started,.05)
            self.assertEqual(json.loads(self.target.read_text()),{'state':'READY'})
        finally:
            timer.cancel()
            timer.join()
            release()

    def test_invalid_json_value_never_replaces_valid_snapshot(self):
        with self.assertRaises(ValueError):atomic_write_json(self.target,{'number':float('nan')})
        self.assertEqual(json.loads(self.target.read_text())['state'],'OLD')

if __name__=='__main__':unittest.main()
