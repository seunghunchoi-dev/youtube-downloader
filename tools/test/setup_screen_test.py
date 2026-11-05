"""설치 프로그램 첫 화면(사용권 계약서)을 캡처한 뒤 취소

사용법: python setup_screen_test.py <설치 파일 경로> <캡처 저장 폴더>
"""
import ctypes
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

from PIL import ImageGrab

setup, out = sys.argv[1], Path(sys.argv[2])
user32 = ctypes.windll.user32
user32.SetProcessDPIAware()
proc = subprocess.Popen([setup, "/CURRENTUSER", "/LANG=korean"])


def find_window(pid_title_part):
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            buf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, buf, 256)
            if pid_title_part in buf.value:
                found.append((hwnd, buf.value))
        return True

    user32.EnumWindows(cb, 0)
    return found


for _ in range(40):
    time.sleep(0.5)
    wins = find_window("YouTube Downloader")
    if wins:
        break
hwnd, title = wins[0]
print("window:", title)
time.sleep(1.5)
user32.SetForegroundWindow(hwnd)
time.sleep(0.5)
r = wintypes.RECT()
user32.GetWindowRect(hwnd, ctypes.byref(r))
ImageGrab.grab(bbox=(r.left, r.top, r.right, r.bottom), all_screens=True).save(out / "setup_license.png")
proc.kill()
print("captured")
