#!/usr/bin/env python3
"""Loader isolation for zed_capture_node only; never mutate the caller environment."""
import os
import pathlib
import re
import subprocess

WS = pathlib.Path(__file__).resolve().parents[1]
SYSTEM_USB = pathlib.Path('/usr/lib/aarch64-linux-gnu/libusb-1.0.so.0')


def capture_environment(parent=None):
    child = dict(os.environ if parent is None else parent)
    # System libusb must precede vendor SDK libraries. Do not change env.sh or
    # the environment inherited by roscore, roslaunch/Livox, or the manager.
    child['LD_LIBRARY_PATH'] = ':'.join([
        '/usr/lib/aarch64-linux-gnu',
        '/lib/aarch64-linux-gnu',
        str(WS / 'devel/lib'),
        '/home/jetson/catkin_ws/devel/lib',
        '/opt/ros/noetic/lib',
    ])
    return child


def check_dynamic_dependencies(executable, environment):
    """Relocate trusted local ELF without running main, ROS, or USB operations.

    glibc ldd -r may return 0 even when it prints undefined symbols. Both output
    streams, the exit status, and the selected libusb realpath must be checked.
    """
    command = ['/usr/bin/ldd', '-r', str(executable)]
    result = {'status': 'BLOCKED', 'command': command,
              'ld_library_path': environment.get('LD_LIBRARY_PATH'),
              'expected_libusb_realpath': str(SYSTEM_USB.resolve()),
              'libusb_path': None, 'libusb_realpath': None,
              'errors': [], 'returncode': None, 'stdout': '', 'stderr': ''}
    if not pathlib.Path(executable).is_file():
        result['errors'].append('capture executable not built')
        return result
    probe_env = dict(environment, LC_ALL='C')
    # Injection variables are not changed implicitly. Ask for a reviewed child
    # policy if they are actually present; LD_LIBRARY_PATH alone is insufficient.
    for key in ['LD_PRELOAD', 'LD_AUDIT']:
        if probe_env.get(key):
            result['errors'].append(key + ' is nonempty; capture-only loader policy requires review')
    try:
        proc = subprocess.run(command, env=probe_env, capture_output=True,
                              text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired) as exc:
        result['errors'].append('dynamic dependency check failed: ' + str(exc))
        return result
    result.update(returncode=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)
    output = proc.stdout + '\n' + proc.stderr
    if proc.returncode:
        result['errors'].append('ldd -r returned ' + str(proc.returncode))
    for line in output.splitlines():
        if re.search(r'undefined symbol|symbol lookup error|not found|relocation error|cannot open shared object', line, re.I):
            result['errors'].append(line.strip())
    match = re.search(r'^\s*libusb-1\.0\.so\.0\s+=>\s+(\S+)', output, re.M)
    if match and match.group(1).startswith('/'):
        result['libusb_path'] = match.group(1)
        result['libusb_realpath'] = os.path.realpath(match.group(1))
        if result['libusb_realpath'] != result['expected_libusb_realpath']:
            result['errors'].append('capture resolved libusb outside the approved Ubuntu system library')
    else:
        result['errors'].append('libusb-1.0.so.0 was not resolved to a file')
    if not result['errors']:
        result['status'] = 'SOFTWARE_TESTED'
    return result
