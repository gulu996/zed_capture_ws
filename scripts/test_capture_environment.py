#!/usr/bin/env python3
"""Loader regression tests; do not start ROS, sensors, or hardware acquisition."""
import contextlib
import io
import os
import pathlib
import subprocess
import sys
import unittest
from unittest import mock
import capture_environment as loader
import session

EXE = loader.WS / 'devel/lib/zed_capture/zed_capture_node'


class CaptureEnvironmentTests(unittest.TestCase):
    def test_mvs_conflict_is_detected_on_real_binary(self):
        env = dict(os.environ, LD_LIBRARY_PATH='/opt/MVS/lib/aarch64:/opt/ros/noetic/lib')
        result = loader.check_dynamic_dependencies(EXE, env)
        self.assertEqual(result['status'], 'BLOCKED')
        self.assertEqual(result['libusb_path'], '/opt/MVS/lib/aarch64/libusb-1.0.so.0')
        self.assertTrue(any('undefined symbol: libusb_wrap_sys_device' in e for e in result['errors']))

    def test_isolation_resolves_real_binary_without_mutating_parent(self):
        ambient = dict(os.environ)
        parent = dict(ambient, LD_LIBRARY_PATH='/opt/MVS/lib/aarch64:/opt/ros/noetic/lib')
        before = parent.copy()
        child = loader.capture_environment(parent)
        result = loader.check_dynamic_dependencies(EXE, child)
        self.assertEqual(result['status'], 'SOFTWARE_TESTED', result['errors'])
        self.assertEqual(result['libusb_realpath'], str(loader.SYSTEM_USB.resolve()))
        self.assertEqual(parent, before)
        self.assertEqual(dict(os.environ), ambient)
        self.assertEqual({k for k in parent if parent[k] != child[k]}, {'LD_LIBRARY_PATH'})

    def test_zero_exit_with_undefined_symbol_on_stderr_is_rejected(self):
        proc = subprocess.CompletedProcess([], 0,
            'libusb-1.0.so.0 => /usr/lib/aarch64-linux-gnu/libusb-1.0.so.0 (0x0)\n',
            'undefined symbol: another_required_function (zed_capture_node)\n')
        with mock.patch.object(loader.subprocess, 'run', return_value=proc):
            result = loader.check_dynamic_dependencies(EXE, loader.capture_environment())
        self.assertEqual(result['returncode'], 0)
        self.assertEqual(result['status'], 'BLOCKED')
        self.assertIn('another_required_function', '\n'.join(result['errors']))

    def test_missing_executable_fails_before_loader_call(self):
        with mock.patch.object(loader.subprocess, 'run') as run:
            result = loader.check_dynamic_dependencies('/nonexistent/zed_capture_node', loader.capture_environment())
        self.assertEqual(result['status'], 'BLOCKED')
        run.assert_not_called()

    def test_symbol_failure_stops_before_master_or_driver_spawn(self):
        bad = {'status':'BLOCKED','errors':['undefined symbol: libusb_wrap_sys_device']}
        # Dependency detection itself is exercised against real ELF above.
        # No Popen is permitted after returning the failed preflight result.
        with mock.patch.object(session, 'check_dynamic_dependencies', return_value=bad), \
             mock.patch.object(sys, 'argv', ['session.py','--duration','30']), \
             mock.patch.object(session.subprocess, 'Popen') as popen, \
             contextlib.redirect_stdout(io.StringIO()) as output:
            code = session.main()
        self.assertEqual(code, 2)
        self.assertIn('Capture dynamic dependencies: undefined symbol: libusb_wrap_sys_device', output.getvalue())
        popen.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
