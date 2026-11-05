"""컴파일된 exe: 클립보드 → [붙여넣기] → [추가] → [전체 다운로드] 를 실제 클릭으로 시험

사용법: python click_download_test.py <exe 경로> <캡처 저장 폴더> <다운로드 저장 폴더>
주의: 실제 마우스를 움직이므로 시험 중에는 다른 창을 모두 닫고 PC를 만지지 않는다.
"""
import ctypes
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

from PIL import ImageGrab

exe, out, dl_dir = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
user32 = ctypes.windll.user32
user32.SetProcessDPIAware()
URL = "https://www.youtube.com/watch?v=jNQXAC9IVRw"

subprocess.run(["powershell", "-NoProfile", "-Command", f"Set-Clipboard '{URL}'"], check=True)


def find(title_part):
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            buf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, buf, 256)
            if title_part in buf.value:
                found.append(hwnd)
        return True

    user32.EnumWindows(cb, 0)
    return found[0] if found else None


def origin(hwnd):
    pt = wintypes.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    r = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(r))
    return pt.x, pt.y, r.right, r.bottom


def click(hwnd, cx, cy):
    x, y, _, _ = origin(hwnd)
    user32.SetForegroundWindow(hwnd)
    user32.SetCursorPos(x + cx, y + cy)
    time.sleep(0.2)
    user32.mouse_event(2, 0, 0, 0, 0)
    time.sleep(0.05)
    user32.mouse_event(4, 0, 0, 0, 0)
    time.sleep(0.5)


def shot(hwnd, name):
    x, y, w, h = origin(hwnd)
    ImageGrab.grab(bbox=(x, y, x + w, y + h), all_screens=True).save(out / name)


before = {p.name for p in dl_dir.glob("*.mp4")}
proc = subprocess.Popen([exe])
hwnd = None
for _ in range(60):
    time.sleep(0.5)
    hwnd = find("YouTube Downloader 1.0.0")
    if hwnd:
        break
time.sleep(4)
_, _, w, _ = origin(hwnd)
click(hwnd, w - 214, 140)   # 붙여넣기
time.sleep(1)
click(hwnd, w - 104, 140)   # 추가
time.sleep(12)
shot(hwnd, "b2_added.png")
click(hwnd, w - 309, 486)   # 전체 다운로드
new = []
for _ in range(60):
    time.sleep(2)
    new = [p for p in dl_dir.glob("*.mp4") if p.name not in before]
    if new:
        break
time.sleep(3)
shot(hwnd, "b3_done.png")
print("new:", [(p.name, p.stat().st_size) for p in new], flush=True)
proc.kill()
