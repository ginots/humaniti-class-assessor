"""Read-only environment checks; no third-party packages or private content."""
import ctypes
import json
import os
import platform
import shutil
import struct
import subprocess
import sys
import sysconfig


def main():
    result = {
        'python_version': platform.python_version(),
        'python_bits': struct.calcsize('P') * 8,
        'python_free_threaded': bool(sysconfig.get_config_var('Py_GIL_DISABLED')),
        'platform': platform.system(),
        'logical_cpu_count': os.cpu_count(),
        'disk': {drive: dict(zip(('total_bytes', 'used_bytes', 'free_bytes'), shutil.disk_usage(drive)))
                 for drive in ('C:\\', 'E:\\')},
        'ffmpeg_on_path': shutil.which('ffmpeg'),
        'ffprobe_on_path': shutil.which('ffprobe'),
        'nvcc_on_path': shutil.which('nvcc'),
        'cache_environment': {name: os.environ.get(name) for name in (
            'TEMP', 'TMP', 'TMPDIR', 'PIP_CACHE_DIR', 'UV_CACHE_DIR', 'HF_HOME',
            'HF_HUB_CACHE', 'TORCH_HOME', 'XDG_CACHE_HOME', 'NUMBA_CACHE_DIR')},
    }
    if os.name == 'nt':
        class MemoryStatus(ctypes.Structure):
            _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong)] + [
                (name, ctypes.c_ulonglong) for name in (
                    'total_physical', 'available_physical', 'total_pagefile',
                    'available_pagefile', 'total_virtual', 'available_virtual', 'extended_virtual')]
        memory = MemoryStatus()
        memory.length = ctypes.sizeof(memory)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)):
            result['ram_total_bytes'] = memory.total_physical
            result['ram_available_bytes'] = memory.available_physical
    nvidia = shutil.which('nvidia-smi')
    if nvidia:
        try:
            result['gpu_name_memory_driver'] = subprocess.run(
                [nvidia, '--query-gpu=name,memory.total,driver_version', '--format=csv,noheader'],
                capture_output=True, text=True, check=True, timeout=20).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            result['gpu_check'] = 'failed'
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
