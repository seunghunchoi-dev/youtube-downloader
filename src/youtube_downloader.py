"""유튜브 다중 다운로더 - 원본 스트림 그대로(재인코딩 없음) MP4로 저장

Copyright (c) 2026 최승훈. All rights reserved.
본 프로그램의 무단 복제·배포·수정 및 역설계를 금지합니다.
"""
import copy
import io
import itertools
import json
import os
import queue
import re
import shutil
import subprocess
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tkinter import TclError, filedialog, messagebox
from urllib.parse import parse_qs, urlparse

import customtkinter as ctk
import yt_dlp
from customtkinter.windows.widgets.appearance_mode import CTkAppearanceModeBaseClass
from customtkinter.windows.widgets.core_widget_classes import CTkBaseClass, DropdownMenu
from PIL import Image, ImageDraw


def _set_appearance_mode_without_flush(self, mode_string):
    # CustomTkinter는 테마를 바꿀 때 위젯마다 화면 전체 갱신(update_idletasks)을 호출해서
    # 카드가 많으면 몇 초씩 멈춘다. 다시 그리기만 하고 화면 갱신은 Tk에 맡긴다.
    CTkAppearanceModeBaseClass._set_appearance_mode(self, mode_string)
    self._draw()


CTkBaseClass._set_appearance_mode = _set_appearance_mode_without_flush

APP_NAME = "YouTube Downloader"
APP_VERSION = "1.0.0"
AUTHOR = "최승훈"
COPYRIGHT = "Copyright © 2026 최승훈. All rights reserved."
NOTICE = "본 프로그램의 무단 복제·배포·수정 및 역설계를 금지합니다."

APP_DIR = Path(__file__).resolve().parent  # 개발 중: src 폴더 / 설치본: 설치 폴더
# 함께 배포하는 ffmpeg·node·아이콘 위치 (설치본은 설치 폴더, 개발 중에는 프로젝트 폴더)
RESOURCE_DIRS = [APP_DIR, APP_DIR.parent]
DEFAULT_OUT = Path.home() / "Downloads" / APP_NAME
# 설정은 사용자 폴더에 저장 (설치 폴더는 쓰기 권한이 없을 수 있다)
SETTINGS_FILE = Path(os.environ.get("APPDATA", Path.home())) / APP_NAME / "settings.json"
RAW_MAX_AGE = 3 * 3600  # 유튜브 스트림 주소는 몇 시간 뒤 만료되므로 그 전에 다시 가져온다

VIDEO_MODES = {
    # 최고 비트레이트 영상 스트림을 그대로 받아 MP4 컨테이너로만 합침(스트림 복사, 화질 손실 없음)
    # 오디오는 채널 수(5.1 우선) → Opus 우선 → 비트레이트 순
    "원본 최고화질": {"filter": "", "format_sort": ["res", "fps", "hdr:12", "vbr", "channels", "acodec", "abr"]},
    # H.264 + AAC만 선택 → 어떤 플레이어에서도 재생 (최대 1080p 정도)
    "호환성 우선": {"filter": "[vcodec^=avc1]", "format_sort": ["res", "fps", "vbr", "abr"]},
}

RESOLUTIONS = {
    "최고 화질": None,
    "8K (4320p)": 4320,
    "4K (2160p)": 2160,
    "QHD (1440p)": 1440,
    "FHD (1080p)": 1080,
    "HD (720p)": 720,
    "480p": 480,
    "360p": 360,
}
RES_NAMES = {4320: "8K", 2160: "4K", 1440: "QHD", 1080: "FHD", 720: "HD"}

AUDIO_MODES = {
    # 가장 높은 음질 스트림 그대로 (대부분 Opus 가변 비트레이트, 5.1 AAC가 있으면 그것)
    "최고 음질": "",
    # AAC 스트림만 선택 → 거의 고정 비트레이트(약 128kbps), 편집 프로그램 호환
    "고정 비트레이트 (AAC)": "[acodec^=mp4a]",
}

# 카드 안의 좁은 공간용 짧은 이름 → 전체 이름
CARD_VIDEO = {"원본 화질": "원본 최고화질", "호환 H.264": "호환성 우선"}
CARD_AUDIO = {"최고 음질": "최고 음질", "AAC 고정": "고정 비트레이트 (AAC)"}

LIST_CHOICES = ["이 영상만", "재생목록 전체"]

# ---------------- 디자인 토큰 (라이트, 다크) ----------------
BG = ("#F4F5F7", "#0E1014")
SURFACE = ("#FFFFFF", "#171A21")
SURFACE_2 = ("#F3F6FE", "#151B29")  # 재생목록 묶음 배경 (옅은 블루)
BORDER = ("#E4E6EB", "#252933")
INPUT = ("#F7F8FA", "#1E222B")
TEXT = ("#111318", "#F2F3F5")
MUTED = ("#6B7280", "#9AA0AB")
TRACK = ("#E9EBEF", "#2A2E38")
# 눈이 편한 소프트 블루 강조색
ACCENT = "#4C7DF0"
ACCENT_HOVER = "#3F6CD9"
GHOST_HOVER = ("#ECEEF2", "#232731")
TEAL = ("#0F766E", "#14B8A6")
GREEN = ("#16A34A", "#22C55E")
WARN = ("#EA580C", "#F97316")  # 실패·주소 오류 (빨강 대신 부드러운 주황)
GRAY = ("#9CA3AF", "#6B7280")

STATES = {
    # state: (칩 텍스트, 칩/진행바 색)
    "fetching": ("불러오는 중", ("#64748B", "#94A3B8")),
    "ready": ("준비됨", TEAL),
    "queued": ("대기", GRAY),
    "downloading": ("다운로드 중", (ACCENT, ACCENT)),
    "merging": ("MP4 합치는 중", ("#7C3AED", "#A78BFA")),
    "done": ("완료", GREEN),
    "failed": ("실패", WARN),
    "cancelled": ("취소됨", GRAY),
}
ACTIVE = {"queued", "downloading", "merging"}
EDITABLE = {"ready", "failed", "cancelled"}

# 주소 종류: (칩 텍스트, 칩 색, 안내 문구)
URL_KINDS = {
    "empty": (None, None, "유튜브 영상 또는 재생목록 주소를 붙여넣고 Enter · 여러 줄을 붙여넣으면 모두 추가됩니다"),
    "video": ("▶  영상", TEAL, "영상 1개가 목록에 추가됩니다"),
    "playlist": ("☰  재생목록", (ACCENT, ACCENT), "재생목록 안의 모든 영상이 하나의 묶음으로 추가됩니다"),
    "mixed": ("☰  재생목록 포함", (ACCENT, ACCENT), "재생목록 안의 영상 주소입니다. 무엇을 추가할까요?"),
    "channel": ("☰  채널", (ACCENT, ACCENT), "채널의 모든 영상이 하나의 묶음으로 추가됩니다 (영상이 많을 수 있어요)"),
    "other": ("기타 사이트", GRAY, "유튜브 외 주소입니다. 지원되는 사이트라면 받을 수 있습니다"),
    "invalid": ("주소 확인", WARN, "http:// 또는 https:// 로 시작하는 주소를 입력하세요"),
}

SPINNER = "◐◓◑◒"  # 불러오는 중 표시용 (글자만 바꾸므로 가볍다)
AUTO_COLLAPSE = 12  # 이보다 영상이 많은 재생목록은 불러오는 동안 접어 둔다

THUMB_W, THUMB_H = 176, 99
FONT_FAMILY = "Malgun Gothic"


def find_resource(*parts):
    for base in RESOURCE_DIRS:
        path = base.joinpath(*parts)
        if path.exists():
            return path
    return None


def find_ffmpeg():
    # 함께 배포한 ffmpeg 우선, 없으면 PC에 설치된 것
    bundled = find_resource("bin", "ffmpeg.exe")
    if bundled:
        return str(bundled.parent)
    path = shutil.which("ffmpeg")
    if path:
        return str(Path(path).parent)
    winget = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
    if winget.exists():
        for exe in winget.glob("*FFmpeg*/**/bin/ffmpeg.exe"):
            return str(exe.parent)
    return None


def find_js_runtime():
    # 유튜브 서명 해독용 JavaScript 실행기. 함께 배포한 node 우선
    bundled = find_resource("bin", "node.exe")
    if bundled:
        return {"node": {"path": str(bundled)}}
    for name in ("deno", "node", "bun"):
        if shutil.which(name):
            return {name: {}}
    return None


def load_settings():
    try:
        return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def normalize_url(url):
    url = url.strip()
    if url and not re.match(r"https?://", url) and re.match(r"(www\.|m\.)?(youtube\.com|youtu\.be)/", url):
        url = "https://" + url
    return url


def classify_url(url):
    url = normalize_url(url)
    if not url:
        return "empty"
    if not re.match(r"https?://\S+$", url):
        return "invalid"
    p = urlparse(url)
    host = p.netloc.lower()
    if not (host.endswith("youtube.com") or host.endswith("youtu.be")):
        return "other"
    q = parse_qs(p.query)
    has_video = "v" in q or host.endswith("youtu.be") or p.path.startswith(("/shorts/", "/live/"))
    if "list" in q and has_video:
        return "mixed"
    if "list" in q or p.path.startswith("/playlist"):
        return "playlist"
    if p.path.startswith(("/@", "/channel/", "/c/", "/user/")):
        return "channel"
    return "video"


def safe_folder_name(name):
    name = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", name).strip(" .")
    return name[:80] or "재생목록"


def build_mode(video_mode, height, audio_mode):
    """선택한 옵션으로 yt-dlp 포맷 문자열을 만든다. 조건에 맞는 스트림이 없으면 단계적으로 완화한다."""
    vm = VIDEO_MODES[video_mode]
    h = f"[height<={height}]" if height else ""
    a = "[acodec^=mp4a]" if vm["filter"] else AUDIO_MODES[audio_mode]
    chain = [
        f"bv*{h}{vm['filter']}+ba{a}",
        f"bv*{h}+ba{a}",
        f"bv*{h}+ba",
        f"b{h}",
        "bv*+ba",
        "b",
    ]
    return {"format": "/".join(dict.fromkeys(chain)), "format_sort": vm["format_sort"]}


def resolution_options(raw):
    """영상이 실제로 제공하는 해상도 목록 {표시 이름: 높이}. 높은 화질 순."""
    best = {}
    for f in raw.get("formats") or []:
        h = f.get("height")
        if h and f.get("vcodec") not in (None, "none"):
            best[h] = max(best.get(h, 0), f.get("fps") or 0)
    options = {"최고 화질": None}
    for h in sorted(best, reverse=True):
        fps = best[h]
        label = f"{h}p{int(fps) if fps > 30 else ''}"
        if h in RES_NAMES:
            label = f"{RES_NAMES[h]} · {label}"
        options[label] = h
    return options


def default_resolution(options, cap):
    """최대 해상도(cap)에 맞는 카드 선택값"""
    if cap is None:
        return "최고 화질"
    fitting = [label for label, h in options.items() if h and h <= cap]
    if fitting:
        return fitting[0]
    return list(options)[-1]


def fetch_thumbnail(raw):
    thumbs = sorted(raw.get("thumbnails") or [], key=lambda t: (t.get("preference") or 0, t.get("width") or 0),
                    reverse=True)
    urls = [t["url"] for t in thumbs if t.get("url")]
    if raw.get("thumbnail"):
        urls.insert(0, raw["thumbnail"])
    for url in urls[:5]:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as r:
                img = Image.open(io.BytesIO(r.read())).convert("RGB")
            break
        except Exception:
            continue
    else:
        return None
    # 16:9로 가운데 자르고 리사이즈 후 모서리 둥글게
    w, h = img.size
    target = 16 / 9
    if w / h > target:
        nw = int(h * target)
        img = img.crop(((w - nw) // 2, 0, (w - nw) // 2 + nw, h))
    else:
        nh = int(w / target)
        img = img.crop((0, (h - nh) // 2, w, (h - nh) // 2 + nh))
    scale = 2  # 고해상도 디스플레이 대비
    img = img.resize((THUMB_W * scale, THUMB_H * scale), Image.LANCZOS)
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, *img.size), radius=12 * scale, fill=255)
    img = img.convert("RGBA")
    img.putalpha(mask)
    return img


def fmt_bytes(n):
    if not n:
        return ""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def fmt_eta(e):
    if e is None:
        return ""
    e = int(e)
    h, rem = divmod(e, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def quality_label(info):
    h = info.get("height")
    fps = info.get("fps")
    vcodec = (info.get("vcodec") or "").split(".")[0].upper().replace("AVC1", "H.264").replace("VP09", "VP9").replace("AV01", "AV1")
    acodec = (info.get("acodec") or "").split(".")[0].upper().replace("MP4A", "AAC")
    audio = next((f for f in info.get("requested_formats") or [info] if f.get("acodec", "none") != "none"), {})
    if acodec and acodec != "NONE":
        abr = audio.get("abr")
        acodec += f" {int(abr)}k" if abr else ""
        acodec += " (CBR)" if acodec.startswith("AAC") else " (VBR)" if acodec.startswith("OPUS") else ""
    q = f"{h}p{int(fps) if fps and fps > 30 else ''}" if h else ""
    return " · ".join(p for p in (q, vcodec, acodec) if p and p != "NONE")


def selection_summary(info):
    """선택된 스트림 설명과 예상 용량"""
    formats = info.get("requested_formats") or [info]
    sizes = {f.get("format_id", "?"): f.get("filesize") or f.get("filesize_approx") for f in formats}
    known = all(sizes.values())
    total = sum(s for s in sizes.values() if s)
    text = " · ".join(p for p in (quality_label(info), f"약 {fmt_bytes(total)}" if known else "") if p)
    return text, {k: v for k, v in sizes.items() if v}


def short_folder(path):
    name = Path(path).name or str(path)
    return name if len(name) <= 14 else name[:13] + "…"


class Cancelled(Exception):
    pass


class Dropdown(ctk.CTkButton):
    """가벼운 드롭다운. CTkOptionMenu는 다시 그릴 때마다 화면 전체를 갱신해서
    카드가 많으면 화면이 멈추므로, 버튼 + 같은 팝업 메뉴로 대신한다."""

    def __init__(self, master, values, command, font, dropdown_font, width, height, corner_radius=8, accent=True):
        # accent=False 는 테두리만 있는 차분한 모양 (카드 안 보조 옵션용)
        style = ({"fg_color": ACCENT, "hover_color": ACCENT_HOVER, "text_color": "#FFFFFF",
                  "text_color_disabled": ("#E5E7EB", "#9CA3AF")} if accent else
                 {"fg_color": INPUT, "hover_color": GHOST_HOVER, "text_color": TEXT, "text_color_disabled": MUTED,
                  "border_width": 1, "border_color": BORDER})
        super().__init__(master, text="", width=width, height=height, corner_radius=corner_radius, font=font,
                         anchor="w", command=self._open, **style)
        self._value = None
        # CTkButton이 클릭 처리에 self._command를 쓰므로 선택 콜백은 다른 이름으로 둔다
        self._on_select = command
        self._menu = DropdownMenu(master=self, values=list(values), command=self._pick, font=dropdown_font)

    def _open(self):
        self._menu.open(self.winfo_rootx(), self.winfo_rooty() + self.winfo_height())

    def _pick(self, value):
        self.set(value)
        if self._on_select:
            self._on_select(value)

    def set(self, value):
        if value != self._value:
            self._value = value
            self.configure(text=f"{value}   ▾")

    def get(self):
        return self._value

    def set_values(self, values):
        self._menu.configure(values=list(values))


class Job:
    _ids = itertools.count(1)

    def __init__(self, url, out_dir, video_mode, cap, audio_mode, auto, title=None, playlist=False, group=None,
                 index=None):
        self.id = next(self._ids)
        self.url = url
        self.auto = auto  # 정보 확인이 끝나면 바로 다운로드
        self.playlist = playlist  # 영상+재생목록 주소에서 재생목록 전체를 받을지
        self.is_list = playlist or classify_url(url) in ("playlist", "channel")  # 재생목록으로 펼쳐질 주소
        self.group = group  # 속한 재생목록 묶음 id
        self.index = index  # 재생목록 안의 순번
        self.out_dir = Path(out_dir)
        self.video_mode = video_mode
        self.cap = cap  # 최대 해상도 (카드 기본 선택값 계산용)
        self.height = cap
        self.audio_mode = audio_mode
        self.title = title or url
        self.state = "fetching"
        self.raw = None  # 포맷 선택 전의 영상 정보
        self.raw_time = 0.0
        self.res_options = {"최고 화질": None}
        self.run_id = 0
        self.preview_seq = 0
        self.cancel = threading.Event()
        self.sizes = {}  # format_id -> 전체 바이트
        self.done = {}  # format_id -> 받은 바이트
        self.last_emit = 0.0
        self.filepath = None


class DownloadCard(ctk.CTkFrame):
    def __init__(self, master, app, job):
        super().__init__(master, fg_color=SURFACE, corner_radius=16, border_width=1, border_color=BORDER)
        self.app = app
        self.job = job
        f = app.font

        self.thumb = ctk.CTkLabel(self, text="▶", width=THUMB_W, height=THUMB_H, corner_radius=12,
                                  fg_color=TRACK, text_color=MUTED, font=f(26))
        self.thumb.grid(row=0, column=0, rowspan=5, padx=(14, 16), pady=14, sticky="n")

        self.title = ctk.CTkLabel(self, text="", font=f(15, "bold"), text_color=TEXT,
                                  anchor="w", justify="left", wraplength=540)
        self.title.grid(row=0, column=1, sticky="we", pady=(14, 0))
        self.set_title(job.title)

        self.chip = ctk.CTkLabel(self, text="", font=f(11, "bold"), text_color="#FFFFFF",
                                 corner_radius=10, height=22, padx=10)
        self.chip.grid(row=0, column=2, sticky="ne", padx=(8, 14), pady=(14, 0))

        self.meta = ctk.CTkLabel(self, text="", font=f(12), text_color=MUTED, anchor="w")
        self.meta.grid(row=1, column=1, columnspan=2, sticky="we", pady=(2, 0))

        # 영상별 옵션
        self.opts = opts = ctk.CTkFrame(self, fg_color="transparent")
        opts.grid(row=2, column=1, columnspan=2, sticky="w", pady=(8, 0))
        # 카드가 많아도 가볍도록 모두 Dropdown 하나짜리 위젯으로 구성
        self.mode = Dropdown(opts, CARD_VIDEO, self._on_change, f(11, "bold"), f(12), width=112, height=28,
                             accent=False)
        self.mode.set(next(k for k, v in CARD_VIDEO.items() if v == job.video_mode))
        self.mode.pack(side="left")
        self.res = Dropdown(opts, job.res_options, self._on_change, f(11, "bold"), f(12), width=136, height=28)
        self.res.set("최고 화질")
        self.res.pack(side="left", padx=8)
        self.audio = Dropdown(opts, CARD_AUDIO, self._on_change, f(11, "bold"), f(12), width=112, height=28,
                              accent=False)
        self.audio.set(next(k for k, v in CARD_AUDIO.items() if v == job.audio_mode))
        self.audio.pack(side="left")
        self.folder = ctk.CTkButton(opts, text="", width=140, height=28, corner_radius=8, font=f(11),
                                    fg_color="transparent", border_width=1, border_color=BORDER,
                                    text_color=TEXT, hover_color=GHOST_HOVER, anchor="w",
                                    command=self._choose_folder)
        self.folder.pack(side="left", padx=8)
        self.update_folder()

        self.bar = ctk.CTkProgressBar(self, height=8, corner_radius=4, fg_color=TRACK)
        self.bar.set(0)
        self.bar.grid(row=3, column=1, columnspan=2, sticky="we", padx=(0, 14), pady=(10, 0))

        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.grid(row=4, column=1, columnspan=2, sticky="we", padx=(0, 14), pady=(6, 12))
        bottom.grid_columnconfigure(0, weight=1)
        self.stats = ctk.CTkLabel(bottom, text="", font=f(12), text_color=MUTED, anchor="w")
        self.stats.grid(row=0, column=0, sticky="w")
        self.remove = ctk.CTkButton(bottom, text="삭제", width=56, height=28, corner_radius=8, font=f(12),
                                    fg_color="transparent", text_color=MUTED, hover_color=GHOST_HOVER,
                                    command=lambda: self.app.remove_job(self.job))
        self.remove.grid(row=0, column=1, sticky="e", padx=(0, 6))
        self.action = ctk.CTkButton(bottom, text="", width=92, height=28, corner_radius=8, font=f(12, "bold"))
        self.action.grid(row=0, column=2, sticky="e")

        self.grid_columnconfigure(1, weight=1)
        if job.is_list:
            # 재생목록을 불러오는 동안은 묶음 자리 표시 카드로 보여 준다
            self.configure(border_width=2, border_color=ACCENT)
            self.thumb.configure(text="☰", text_color=ACCENT)
            self.title.configure(text="재생목록을 불러오는 중…")
            self.meta.configure(text=job.url)
            opts.grid_remove()
        self.set_state(job.state, "재생목록의 영상 목록을 가져오는 중" if job.is_list else
                       "차례를 기다리는 중" if job.group else "영상 정보를 가져오는 중")

    def as_video(self):
        """재생목록 주소였지만 영상 하나로 확인된 경우 일반 카드로 되돌린다"""
        self.configure(border_width=1, border_color=BORDER)
        self.thumb.configure(text="▶", text_color=MUTED)
        self.opts.grid()

    # ---- 옵션 ----
    def apply_to_job(self):
        self.job.video_mode = CARD_VIDEO[self.mode.get()]
        self.job.height = self.job.res_options.get(self.res.get())
        self.job.audio_mode = CARD_AUDIO[self.audio.get()]

    def _on_change(self, _=None):
        self._sync_audio_lock()
        self.apply_to_job()
        self.app.preview(self.job)

    def _sync_audio_lock(self):
        # 호환 모드는 항상 AAC(고정 비트레이트)
        editable = self.job.state in EDITABLE
        if VIDEO_MODES[CARD_VIDEO[self.mode.get()]]["filter"]:
            self.audio.set("AAC 고정")
            self.audio.configure(state="disabled")
        else:
            self.audio.configure(state="normal" if editable else "disabled")

    def _choose_folder(self):
        d = filedialog.askdirectory(initialdir=str(self.job.out_dir), title="이 영상의 저장 폴더")
        if d:
            self.job.out_dir = Path(d)
            self.update_folder()

    def update_folder(self):
        self.folder.configure(text=f"폴더: {short_folder(self.job.out_dir)}")

    def set_resolutions(self, options):
        self.job.res_options = options
        self.res.set_values(options)
        self.apply_cap(self.job.cap)

    def apply_cap(self, cap):
        """최대 해상도에 맞춰 선택을 바꾼다 (재생목록 일괄 변경에도 사용)"""
        self.job.cap = cap
        self.res.set(default_resolution(self.job.res_options, cap))
        self.apply_to_job()

    # ---- 상태 ----
    def _primary(self, text, command):
        self.action.configure(text=text, command=command, fg_color=ACCENT, hover_color=ACCENT_HOVER,
                              text_color="#FFFFFF", border_width=0, state="normal")

    def _ghost(self, text, command):
        self.action.configure(text=text, command=command, fg_color="transparent", hover_color=GHOST_HOVER,
                              text_color=TEXT, border_width=1, border_color=BORDER, state="normal")

    def set_state(self, state, message=None):
        prev = getattr(self, "_shown_state", None)
        self.job.state = state
        self._shown_state = state
        text, color = STATES[state]
        if state != prev:
            self.chip.configure(text=text, fg_color=color)

        # 위젯을 다시 그리는 비용이 크므로 실제로 바뀔 때만 설정한다
        editable = state in EDITABLE
        if editable != getattr(self, "_editable", None):
            self._editable = editable
            for w in (self.mode, self.res, self.folder):
                w.configure(state="normal" if editable else "disabled")
            self._sync_audio_lock()
        removable = state not in ACTIVE
        if removable != getattr(self, "_removable", None):
            self._removable = removable
            self.remove.configure(state="normal" if removable else "disabled")

        # 진행 바 애니메이션은 MP4 합치는 중과 재생목록 불러오는 중만
        # (정보 확인 중인 카드가 수십 개일 때 모두 움직이면 화면이 느려진다 → 대신 글자 스피너 사용)
        list_loading = state == "fetching" and self.job.is_list
        if state == "merging" or list_loading:
            self.bar.configure(mode="indeterminate", progress_color=color if state == "merging" else ACCENT)
            self.bar.start()
        elif prev == "merging" or state != prev:
            self.bar.stop()
            self.bar.configure(mode="determinate", progress_color=color)
        # 정보 확인·준비 상태에서는 빈 진행 바를 숨긴다
        if state in ("fetching", "ready") and not list_loading:
            self.bar.grid_remove()
        elif prev in (None, "fetching", "ready"):
            if not list_loading:
                self.bar.set(0)
            self.bar.grid()

        if state == "fetching":
            if prev != "fetching":
                self._load_start = time.monotonic()
                self._load_detail = ""
            self._load_msg = message or "영상 정보를 가져오는 중"
            self._show_loading()
            self.action.configure(text="불러오는 중", state="disabled")
        elif state == "ready":
            self.stats.configure(text=message or "화질과 저장 폴더를 고른 뒤 다운로드를 누르세요")
            self._primary("다운로드", lambda: self.app.enqueue(self.job))
        elif state == "done":
            self.bar.set(1)
            self.stats.configure(text=message or "저장 완료")
            self._ghost("폴더 열기", self._open)
        elif state in ("failed", "cancelled"):
            self.stats.configure(text=message or text)
            self._primary("다시 시도", lambda: self.app.retry(self.job))
        elif state == "merging":
            self.stats.configure(text="영상과 음성을 MP4로 합치는 중 (재인코딩 없음)")
            self._ghost("취소", lambda: self.app.cancel(self.job))
        else:
            if message:
                self.stats.configure(text=message)
            self._ghost("취소", lambda: self.app.cancel(self.job))

    def tick_loading(self, frame):
        """불러오는 중 표시: 돌아가는 기호 + 하는 일 + 찾은 개수 + 경과 시간"""
        secs = int(time.monotonic() - self._load_start)
        parts = [f"{frame}  {self._load_msg}", self._load_detail, f"{secs}초" if secs else ""]
        self.stats.configure(text="  ·  ".join(p for p in parts if p))

    def set_loading(self, message=None, detail=None):
        if message is not None:
            self._load_msg = message
        if detail is not None:
            self._load_detail = detail
        self._show_loading()

    def _show_loading(self):
        # 재생목록 속 카드는 수십 개라 매번 움직이면 화면이 느려진다 → 문구만 표시하고
        # 움직이는 표시는 재생목록 머리 한 곳에서 보여 준다
        if self.job.group:
            self.stats.configure(text=self._load_msg)
        else:
            self.tick_loading(SPINNER[self.app._spin])

    def progress(self):
        return 1.0 if self.job.state == "done" else self.bar.get() if self.job.state == "downloading" else 0.0

    def set_progress(self, frac, text):
        self.bar.set(max(0.0, min(1.0, frac)))
        self.stats.configure(text=text)

    def set_title(self, title):
        self.job.title = title
        self.title.configure(text=f"{self.job.index}.  {title}" if self.job.index else title)

    def set_meta(self, meta):
        self.meta.configure(text=meta)

    def set_thumb(self, pil_img):
        self.thumb_img = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=(THUMB_W, THUMB_H))
        self.thumb.configure(image=self.thumb_img, text="", fg_color="transparent")

    def _open(self):
        if self.job.filepath and Path(self.job.filepath).exists():
            subprocess.Popen(["explorer", "/select,", str(Path(self.job.filepath))])
        else:
            os.startfile(self.job.out_dir)


class PlaylistGroup(ctk.CTkFrame):
    """재생목록 묶음: 머리글(제목·영상 수·전체 진행률·일괄 설정) + 영상 카드들"""

    _ids = itertools.count(1)

    def __init__(self, master, app, title, channel, out_dir, cap):
        super().__init__(master, fg_color=SURFACE_2, corner_radius=20, border_width=2, border_color=ACCENT)
        self.id = next(self._ids)
        self.app = app
        self.out_dir = Path(out_dir)
        self.channel = channel
        self.job_ids = []
        self.pending = []  # 아직 카드를 만들지 않은 (순번, 항목)
        self.total = 0
        self.defaults = None
        self.expanded = True
        self.auto_expand = False  # 불러오기가 끝나면 자동으로 펼칠지
        f = app.font

        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", padx=18, pady=(16, 6))
        head.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(head, text="☰  재생목록", font=f(12, "bold"), text_color="#FFFFFF", fg_color=ACCENT,
                     corner_radius=10, height=26, padx=12).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(head, text=title, font=f(17, "bold"), text_color=TEXT, anchor="w", justify="left",
                     wraplength=620).grid(row=0, column=1, sticky="we", padx=12)
        self.toggle_btn = ctk.CTkButton(head, text="접기  ▴", width=84, height=30, corner_radius=8, font=f(12),
                                        fg_color="transparent", border_width=1, border_color=BORDER,
                                        text_color=TEXT, hover_color=GHOST_HOVER, command=self._toggle_by_user)
        self.toggle_btn.grid(row=0, column=2, sticky="e")
        self.sub = ctk.CTkLabel(head, text="", font=f(12), text_color=MUTED, anchor="w")
        self.sub.grid(row=1, column=0, columnspan=3, sticky="w", pady=(8, 0))
        # 불러오는 중 표시 (끝나면 숨김)
        self.loading = ctk.CTkLabel(head, text="", font=f(13, "bold"), text_color=ACCENT, anchor="w")
        self.loading.grid(row=2, column=0, columnspan=3, sticky="w", pady=(6, 0))
        self._loading_shown = True
        self._load_start = time.monotonic()

        tools = ctk.CTkFrame(self, fg_color="transparent")
        tools.pack(fill="x", padx=18, pady=(4, 0))
        ctk.CTkLabel(tools, text="일괄 화질", font=f(12), text_color=MUTED).pack(side="left", padx=(0, 8))
        self.res = Dropdown(tools, RESOLUTIONS, self._bulk_resolution, f(12, "bold"), f(12), width=136, height=30)
        self.res.set(next(k for k, v in RESOLUTIONS.items() if v == cap))
        self.res.pack(side="left")
        self.folder = ctk.CTkButton(tools, text="", width=170, height=30, corner_radius=8, font=f(12),
                                    fg_color="transparent", border_width=1, border_color=BORDER, text_color=TEXT,
                                    hover_color=GHOST_HOVER, anchor="w", command=self._choose_folder)
        self.folder.pack(side="left", padx=8)
        self.folder.configure(text=f"폴더: {short_folder(self.out_dir)}")
        ctk.CTkButton(tools, text="재생목록 전체 다운로드", width=170, height=30, corner_radius=8, font=f(12, "bold"),
                      fg_color=ACCENT, hover_color=ACCENT_HOVER, command=self._download_all).pack(side="right")
        ctk.CTkButton(tools, text="묶음 삭제", width=80, height=30, corner_radius=8, font=f(12),
                      fg_color="transparent", text_color=MUTED, hover_color=GHOST_HOVER,
                      command=lambda: self.app.remove_group(self)).pack(side="right", padx=6)

        prog = ctk.CTkFrame(self, fg_color="transparent")
        prog.pack(fill="x", padx=18, pady=(12, 4))
        prog.grid_columnconfigure(0, weight=1)
        self.bar = ctk.CTkProgressBar(prog, height=10, corner_radius=5, fg_color=TRACK, progress_color=ACCENT)
        self.bar.set(0)
        self.bar.grid(row=0, column=0, sticky="we")
        self.pct = ctk.CTkLabel(prog, text="0%", font=f(12, "bold"), text_color=TEXT, width=48, anchor="e")
        self.pct.grid(row=0, column=1, padx=(10, 0))

        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.pack(fill="x", padx=12, pady=(8, 12))

    def jobs(self):
        return [self.app.jobs[i] for i in self.job_ids if i in self.app.jobs]

    def add(self, job):
        self.job_ids.append(job.id)
        return DownloadCard(self.body, self.app, job)

    def place(self, card):
        card.pack(fill="x", pady=(0, 10))

    def refresh(self):
        jobs = self.jobs()
        n = len(jobs) or 1
        states = [j.state for j in jobs]
        frac = sum(self.app.cards[j.id].progress() for j in jobs) / n
        self.bar.set(frac)
        self.bar.configure(progress_color=GREEN if states and all(s == "done" for s in states) else ACCENT)
        self.pct.configure(text=f"{frac * 100:.0f}%")
        count = len(jobs) + len(self.pending)
        parts = [f"영상 {count}개", self.channel,
                 f"완료 {states.count('done')}/{count}",
                 f"진행 {sum(s in ACTIVE for s in states)}" if any(s in ACTIVE for s in states) else "",
                 f"실패 {states.count('failed')}" if "failed" in states else ""]
        self.sub.configure(text="  ·  ".join(p for p in parts if p))

    def tick_loading(self, frame):
        """묶음 머리의 불러오는 중 표시를 갱신하고, 다 끝나면 숨긴다"""
        jobs = self.jobs()
        fetching = sum(j.state == "fetching" for j in jobs)
        if self.pending or fetching:
            secs = int(time.monotonic() - self._load_start)
            count = len(jobs) + len(self.pending)
            if self.pending:
                text = f"{frame}  영상 카드 만드는 중  {len(jobs)} / {self.total}"
            else:
                text = f"{frame}  영상 정보 확인 중  {count - fetching} / {count}"
            hint = "  ·  끝나면 자동으로 펼쳐집니다" if self.auto_expand and not self.expanded else ""
            self.loading.configure(text=f"{text}  ·  {secs}초{hint}")
            if not self._loading_shown:  # 다시 시도 등으로 다시 불러오기 시작
                self._load_start = time.monotonic()
                self.loading.grid()
                self._loading_shown = True
        elif self._loading_shown:
            self.loading.grid_remove()
            self._loading_shown = False
            if self.auto_expand:
                self.auto_expand = False
                if not self.expanded:
                    self.toggle()

    def _toggle_by_user(self):
        self.auto_expand = False  # 사용자가 직접 접거나 펼쳤으면 그대로 둔다
        self.toggle()

    def toggle(self):
        self.expanded = not self.expanded
        if self.expanded:
            self.body.pack(fill="x", padx=12, pady=(8, 12))
            self.toggle_btn.configure(text="접기  ▴")
        else:
            self.body.pack_forget()
            self.toggle_btn.configure(text="펼치기  ▾")

    def _bulk_resolution(self, value):
        cap = RESOLUTIONS[value]
        if self.defaults:  # 아직 만들지 않은 카드에도 적용
            video_mode, _, audio_mode, auto = self.defaults
            self.defaults = (video_mode, cap, audio_mode, auto)
        for job in self.jobs():
            card = self.app.cards[job.id]
            if job.state == "fetching":
                job.cap = job.height = cap
            elif job.state in EDITABLE:
                card.apply_cap(cap)
                self.app.preview(job)

    def _choose_folder(self):
        d = filedialog.askdirectory(initialdir=str(self.out_dir), title="재생목록 저장 폴더")
        if not d:
            return
        self.out_dir = Path(d)
        self.folder.configure(text=f"폴더: {short_folder(self.out_dir)}")
        for job in self.jobs():
            if job.state in EDITABLE or job.state == "fetching":
                job.out_dir = self.out_dir
                self.app.cards[job.id].update_folder()

    def _download_all(self):
        for job in self.jobs():
            if job.state == "ready":
                self.app.enqueue(job)


class App:
    def __init__(self, root):
        self.root = root
        self.events = queue.Queue()
        self.jobs = {}
        self.cards = {}
        self.groups = {}
        self.top = []  # 목록 최상위 항목 (카드 또는 재생목록 묶음) 순서
        self.executor = None
        self.executor_size = 0
        # 작업 줄을 나눠서, 큰 재생목록의 영상 정보 확인이 새로 추가한 주소나 화질 미리보기를 막지 않게 한다
        self.add_executor = ThreadPoolExecutor(max_workers=3)  # 사용자가 추가한 주소 불러오기
        self.info_executor = ThreadPoolExecutor(max_workers=4)  # 재생목록 속 영상 정보 확인
        self.preview_executor = ThreadPoolExecutor(max_workers=2)  # 화질 선택 미리보기
        self.ffmpeg_dir = find_ffmpeg()
        self.js_runtime = find_js_runtime()
        self.settings = load_settings()
        self._fonts = {}
        self._flash_after = None

        root.title(f"{APP_NAME} {APP_VERSION}  —  {COPYRIGHT}")
        icon = find_resource("assets", "app.ico")
        if icon:
            root.iconbitmap(default=str(icon))
        root.geometry("1100x900")
        root.minsize(940, 680)
        root.configure(fg_color=BG)
        self._build_ui()
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        root.after(80, self._poll_events)
        self._spin = 0
        root.after(150, self._tick_loading)

        if not self.ffmpeg_dir:
            messagebox.showwarning(
                "FFmpeg 없음",
                "FFmpeg를 찾을 수 없습니다.\n영상+음성 합치기(MP4)를 위해 필요합니다.\n\n"
                "설치: winget install Gyan.FFmpeg",
            )

    def font(self, size, weight="normal"):
        key = (size, weight)
        if key not in self._fonts:
            self._fonts[key] = ctk.CTkFont(family=FONT_FAMILY, size=size, weight=weight)
        return self._fonts[key]

    def _setting(self, key, allowed, default):
        value = self.settings.get(key)
        return value if value in allowed else default

    # ---------------- UI ----------------
    def _build_ui(self):
        f = self.font
        # 저작권 표기 (창 맨 아래 고정)
        footer = ctk.CTkFrame(self.root, fg_color="transparent")
        footer.pack(side="bottom", fill="x", padx=28, pady=(0, 10))
        ctk.CTkLabel(footer, text=f"{COPYRIGHT}  ·  {NOTICE}", font=f(11), text_color=MUTED).pack(side="left")
        ctk.CTkLabel(footer, text=f"제작자 {AUTHOR}  ·  v{APP_VERSION}", font=f(11), text_color=MUTED).pack(
            side="right")

        wrap = ctk.CTkFrame(self.root, fg_color="transparent")
        wrap.pack(fill="both", expand=True, padx=28, pady=(22, 8))

        # 헤더
        header = ctk.CTkFrame(wrap, fg_color="transparent")
        header.pack(fill="x")
        logo = ctk.CTkLabel(header, text="▶", width=40, height=40, corner_radius=12,
                            fg_color=ACCENT, text_color="#FFFFFF", font=f(18, "bold"))
        logo.pack(side="left")
        titles = ctk.CTkFrame(header, fg_color="transparent")
        titles.pack(side="left", padx=12)
        ctk.CTkLabel(titles, text="YouTube Downloader", font=f(22, "bold"), text_color=TEXT,
                     anchor="w").pack(anchor="w")
        ctk.CTkLabel(titles, text="원본 스트림 그대로 · 재인코딩 없는 MP4 · 동시 다운로드", font=f(12),
                     text_color=MUTED, anchor="w").pack(anchor="w")
        self.theme = ctk.CTkSegmentedButton(header, values=["라이트", "다크", "시스템"], font=f(12),
                                            command=self._set_theme, height=30,
                                            selected_color=ACCENT, selected_hover_color=ACCENT_HOVER)
        self.theme.set(self._setting("theme", ["라이트", "다크", "시스템"], "다크"))
        self.theme.pack(side="right")

        # 입력 카드
        card = ctk.CTkFrame(wrap, fg_color=SURFACE, corner_radius=18, border_width=1, border_color=BORDER)
        card.pack(fill="x", pady=(18, 14))

        add = ctk.CTkFrame(card, fg_color="transparent")
        add.pack(fill="x", padx=20, pady=(18, 0))
        add.grid_columnconfigure(0, weight=1)
        self.link = ctk.CTkEntry(add, height=48, corner_radius=12, border_width=2, border_color=BORDER,
                                 fg_color=INPUT, text_color=TEXT, font=f(14),
                                 placeholder_text="https://www.youtube.com/watch?v=…   또는   …/playlist?list=…")
        self.link.grid(row=0, column=0, sticky="we")
        self.link.bind("<Return>", lambda e: self.add_from_entry())
        self.link.bind("<KeyRelease>", lambda e: self._update_detect())
        self.link._entry.bind("<<Paste>>", self._on_paste)  # 여러 줄 붙여넣기 지원
        ctk.CTkButton(add, text="붙여넣기", width=92, height=48, corner_radius=12, font=f(13),
                      fg_color="transparent", border_width=1, border_color=BORDER, text_color=TEXT,
                      hover_color=GHOST_HOVER, command=self._paste_button).grid(row=0, column=1, padx=(8, 0))
        ctk.CTkButton(add, text="추가  +", width=110, height=48, corner_radius=12, font=f(15, "bold"),
                      fg_color=ACCENT, hover_color=ACCENT_HOVER, command=self.add_from_entry).grid(
            row=0, column=2, padx=(8, 0))

        detect = ctk.CTkFrame(card, fg_color="transparent", height=30)
        detect.pack(fill="x", padx=20, pady=(10, 0))
        self.kind_chip = ctk.CTkLabel(detect, text="", font=f(12, "bold"), text_color="#FFFFFF",
                                      corner_radius=10, height=26, padx=12)
        self.kind_hint = ctk.CTkLabel(detect, text="", font=f(12), text_color=MUTED, anchor="w")
        self.list_choice = ctk.CTkSegmentedButton(detect, values=LIST_CHOICES, font=f(12, "bold"), height=28,
                                                  selected_color=ACCENT, selected_hover_color=ACCENT_HOVER)
        self.list_choice.set(self._setting("list_choice", LIST_CHOICES, LIST_CHOICES[0]))
        self.kind_hint.pack(side="left")
        self._update_detect()

        ctk.CTkFrame(card, height=1, fg_color=BORDER).pack(fill="x", padx=20, pady=(14, 0))

        # 기본 설정 (평소에는 한 줄 요약, 누르면 펼침)
        sum_row = ctk.CTkFrame(card, fg_color="transparent")
        sum_row.pack(fill="x", padx=20, pady=12)
        ctk.CTkLabel(sum_row, text="기본 설정", font=f(13, "bold"), text_color=TEXT).pack(side="left")
        self.defaults_summary = ctk.CTkLabel(sum_row, text="", font=f(12), text_color=MUTED, anchor="w")
        self.defaults_summary.pack(side="left", padx=12)
        self.defaults_btn = ctk.CTkButton(sum_row, text="", width=100, height=30, corner_radius=8, font=f(12),
                                          fg_color="transparent", border_width=1, border_color=BORDER,
                                          text_color=TEXT, hover_color=GHOST_HOVER, command=self._toggle_defaults)
        self.defaults_btn.pack(side="right")
        self.defaults_panel = panel = ctk.CTkFrame(card, fg_color="transparent")

        base = ctk.CTkFrame(panel, fg_color="transparent")
        base.pack(fill="x", padx=20)
        base.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(base, text="기본 저장 폴더", font=f(12), text_color=MUTED).grid(row=0, column=0, sticky="w",
                                                                                padx=(0, 10))
        self.out_var = ctk.StringVar(value=self.settings.get("out_dir") or str(DEFAULT_OUT))
        ctk.CTkEntry(base, textvariable=self.out_var, height=34, corner_radius=10, border_width=1,
                     border_color=BORDER, fg_color=INPUT, text_color=TEXT, font=f(12)).grid(
            row=0, column=1, sticky="we")
        self._ghost(base, "찾아보기", self._choose_dir).grid(row=0, column=2, padx=(8, 0))
        self._ghost(base, "폴더 열기", self._open_dir).grid(row=0, column=3, padx=(8, 0))

        opts = ctk.CTkFrame(panel, fg_color="transparent")
        opts.pack(fill="x", padx=20, pady=(12, 0))
        seg = {"font": f(12, "bold"), "height": 34, "selected_color": ACCENT, "selected_hover_color": ACCENT_HOVER}

        def label(text, row, col, padx=(0, 10)):
            ctk.CTkLabel(opts, text=text, font=f(12), text_color=MUTED).grid(row=row, column=col, sticky="w", padx=padx)

        label("영상", 0, 0)
        self.mode = ctk.CTkSegmentedButton(opts, values=list(VIDEO_MODES), command=self._on_video_mode, **seg)
        self.mode.set(self._setting("video_mode", VIDEO_MODES, list(VIDEO_MODES)[0]))
        self.mode.grid(row=0, column=1, sticky="w")
        label("해상도", 0, 2, padx=(22, 10))
        self.resolution = Dropdown(opts, RESOLUTIONS, lambda _: self._update_defaults_summary(), f(12, "bold"),
                                   f(12), width=150, height=34, corner_radius=10)
        self.resolution.set(self._setting("resolution", RESOLUTIONS, list(RESOLUTIONS)[0]))
        self.resolution.grid(row=0, column=3, sticky="w")

        label("오디오", 1, 0)
        self.audio = ctk.CTkSegmentedButton(opts, values=list(AUDIO_MODES),
                                            command=lambda _: self._update_defaults_summary(), **seg)
        self.audio.set(self._setting("audio", AUDIO_MODES, list(AUDIO_MODES)[0]))
        self.audio.grid(row=1, column=1, sticky="w", pady=(10, 0))
        label("동시 다운로드", 1, 2, padx=(22, 10))
        worker_values = ["1", "2", "3", "4", "6", "8"]
        self.workers = ctk.CTkSegmentedButton(opts, values=worker_values,
                                              command=lambda _: self._update_defaults_summary(), **seg)
        self.workers.set(self._setting("workers", worker_values, "3"))
        self.workers.grid(row=1, column=3, sticky="w", pady=(10, 0))

        opts.grid_columnconfigure(4, weight=1)
        checks = ctk.CTkFrame(opts, fg_color="transparent")
        checks.grid(row=0, column=5, rowspan=2, sticky="e")
        check = {"font": f(12), "text_color": TEXT, "checkbox_width": 18, "checkbox_height": 18, "corner_radius": 5,
                 "fg_color": ACCENT, "hover_color": ACCENT_HOVER}
        self.auto_start = ctk.BooleanVar(value=bool(self.settings.get("auto_start", False)))
        ctk.CTkCheckBox(checks, text="추가하면 바로 다운로드", variable=self.auto_start,
                        command=self._update_defaults_summary, **check).pack(anchor="w")
        self.playlist_folder = ctk.BooleanVar(value=bool(self.settings.get("playlist_folder", True)))
        ctk.CTkCheckBox(checks, text="재생목록은 이름으로 하위 폴더에 저장", variable=self.playlist_folder,
                        **check).pack(anchor="w", pady=(10, 0))

        ctk.CTkLabel(panel, text="위 설정은 새로 추가하는 영상의 기본값이며, 카드에서 영상마다 따로 바꿀 수 있습니다.",
                     font=f(11), text_color=MUTED).pack(anchor="w", padx=20, pady=(12, 16))
        self._on_video_mode(self.mode.get())
        self.defaults_open = not self.settings.get("defaults_open", False)
        self._toggle_defaults()

        # 목록 헤더
        bar = ctk.CTkFrame(wrap, fg_color="transparent")
        bar.pack(fill="x", pady=(4, 8))
        ctk.CTkLabel(bar, text="다운로드 목록", font=f(16, "bold"), text_color=TEXT).pack(side="left")
        self.summary = ctk.CTkLabel(bar, text="", font=f(12), text_color=MUTED)
        self.summary.pack(side="left", padx=12)
        self._ghost(bar, "완료 항목 지우기", self._clear_done, width=120).pack(side="right")
        self._ghost(bar, "모두 취소", self.cancel_all).pack(side="right", padx=8)
        ctk.CTkButton(bar, text="전체 다운로드", width=120, height=34, corner_radius=10, font=f(12, "bold"),
                      fg_color=ACCENT, hover_color=ACCENT_HOVER, command=self.start_all).pack(side="right")

        self.list = ctk.CTkScrollableFrame(wrap, fg_color="transparent", corner_radius=0)
        self.list.pack(fill="both", expand=True)
        self.list.grid_columnconfigure(0, weight=1)
        # 스크롤바는 목록 크기가 바뀔 때마다 화면 전체를 갱신해서 카드가 많으면 멈춘다 → 그 갱신만 끈다
        self.list._scrollbar._canvas.update_idletasks = lambda: None
        self.empty = ctk.CTkLabel(self.list, text="아직 추가된 영상이 없습니다.\n위 칸에 주소를 붙여넣고 Enter를 누르세요.",
                                  font=f(13), text_color=MUTED, justify="center")
        self.empty.grid(row=0, column=0, pady=60)
        self._update_summary()

    def _ghost(self, master, text, command, width=84):
        return ctk.CTkButton(master, text=text, command=command, width=width, height=34, corner_radius=10,
                             font=self.font(12), fg_color="transparent", border_width=1, border_color=BORDER,
                             text_color=TEXT, hover_color=GHOST_HOVER)

    # ---- 주소 입력 ----
    def _update_detect(self):
        if self._flash_after:
            return
        kind = classify_url(self.link.get())
        chip, color, hint = URL_KINDS[kind]
        for w in (self.kind_chip, self.kind_hint, self.list_choice):
            w.pack_forget()
        if chip:
            self.kind_chip.configure(text=chip, fg_color=color)
            self.kind_chip.pack(side="left", padx=(0, 10))
        self.kind_hint.configure(text=hint, text_color=MUTED)
        self.kind_hint.pack(side="left")
        if kind == "mixed":
            self.list_choice.pack(side="left", padx=(12, 0))
        highlight = {"playlist": ACCENT, "mixed": ACCENT, "channel": ACCENT, "invalid": WARN[1]}.get(kind, BORDER)
        self.link.configure(border_color=highlight)

    def _flash(self, text, color):
        """추가 결과를 잠깐 보여 준 뒤 원래 안내로 돌아간다"""
        if self._flash_after:
            self.root.after_cancel(self._flash_after)
        for w in (self.kind_chip, self.kind_hint, self.list_choice):
            w.pack_forget()
        self.link.configure(border_color=BORDER)
        self.kind_hint.configure(text=text, text_color=color)
        self.kind_hint.pack(side="left")
        self._flash_after = self.root.after(2500, self._end_flash)

    def _end_flash(self):
        self._flash_after = None
        self._update_detect()

    def _on_paste(self, _event):
        try:
            text = self.root.clipboard_get()
        except TclError:
            return "break"
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        if len(lines) > 1:
            self.add_urls(lines)
            return "break"
        self.root.after_idle(self._update_detect)
        return None

    def _paste_button(self):
        try:
            text = self.root.clipboard_get()
        except TclError:
            self._flash("클립보드가 비어 있습니다", WARN[1])
            return
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        if len(lines) > 1:
            self.add_urls(lines)
        else:
            self.link.delete(0, "end")
            self.link.insert(0, lines[0] if lines else "")
            self._update_detect()
            self.link.focus_set()

    def add_from_entry(self):
        url = self.link.get().strip()
        if not url:
            self.link.focus_set()
            return
        if classify_url(url) == "invalid":
            self._update_detect()
            return
        self.add_urls([url])

    def add_urls(self, urls):
        self._save_settings()
        added, skipped, lists = 0, 0, 0
        for url in urls:
            kind = classify_url(url)
            if kind == "invalid":
                skipped += 1
                continue
            url = normalize_url(url)
            playlist = kind == "mixed" and self.list_choice.get() == LIST_CHOICES[1]
            lists += self._new_job(url, playlist=playlist).is_list
            added += 1
        self.link.delete(0, "end")
        if lists:
            msg = f"✓  {added}개 추가했습니다 · 재생목록은 아래 목록 맨 위에서 불러오는 상황을 볼 수 있어요"
        else:
            msg = f"✓  {added}개 추가했습니다"
        msg += f" (주소가 잘못된 {skipped}개 제외)" if skipped else ""
        self._flash(msg, GREEN[1] if added else WARN[1])
        self.link.focus_set()

    # ---- 기본 설정 ----
    def _toggle_defaults(self):
        self.defaults_open = not self.defaults_open
        if self.defaults_open:
            self.defaults_panel.pack(fill="x")
            self.defaults_btn.configure(text="닫기  ▴")
        else:
            self.defaults_panel.pack_forget()
            self.defaults_btn.configure(text="변경  ▾")
        self._update_defaults_summary()

    def _update_defaults_summary(self):
        parts = [self.mode.get(), self.resolution.get(), self.audio.get(), f"동시 {self.workers.get()}개",
                 f"폴더: {short_folder(self.out_var.get())}"]
        if self.auto_start.get():
            parts.append("바로 다운로드")
        self.defaults_summary.configure(text="  ·  ".join(parts))

    def _on_video_mode(self, value):
        # 호환성 우선은 항상 AAC(고정 비트레이트) 오디오를 쓴다
        if VIDEO_MODES[value]["filter"]:
            self.audio.set(list(AUDIO_MODES)[1])
            self.audio.configure(state="disabled")
        else:
            self.audio.configure(state="normal")
        self._update_defaults_summary()

    def _set_theme(self, value):
        ctk.set_appearance_mode({"라이트": "light", "다크": "dark", "시스템": "system"}[value])

    def _choose_dir(self):
        d = filedialog.askdirectory(initialdir=self.out_var.get() or str(APP_DIR), title="기본 저장 폴더")
        if d:
            self.out_var.set(d)
            self._save_settings()

    def _open_dir(self):
        d = Path(self.out_var.get())
        d.mkdir(parents=True, exist_ok=True)
        os.startfile(d)

    def _save_settings(self):
        self.settings = {
            "out_dir": self.out_var.get(),
            "video_mode": self.mode.get(),
            "resolution": self.resolution.get(),
            "audio": self.audio.get(),
            "workers": self.workers.get(),
            "theme": self.theme.get(),
            "auto_start": self.auto_start.get(),
            "playlist_folder": self.playlist_folder.get(),
            "list_choice": self.list_choice.get(),
            "defaults_open": self.defaults_open,
        }
        self._update_defaults_summary()
        try:
            SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
            SETTINGS_FILE.write_text(json.dumps(self.settings, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass

    def _on_close(self):
        self._save_settings()
        for job in self.jobs.values():
            job.cancel.set()
        self.root.destroy()

    # ---- 목록 ----
    def _relayout(self):
        if self.top:
            self.empty.grid_remove()
        else:
            self.empty.grid(row=0, column=0, pady=60)
        for i, w in enumerate(self.top):
            w.grid(row=i + 1, column=0, sticky="we", pady=(0, 12), padx=(0, 6))

    def _update_summary(self):
        states = [j.state for j in self.jobs.values()]
        active = sum(s in ACTIVE for s in states)
        lists = f"재생목록 {len(self.groups)}  ·  " if self.groups else ""
        self.summary.configure(text=f"{lists}영상 {len(states)}  ·  준비 {states.count('ready')}  ·  진행 {active}  ·  "
                                    f"완료 {states.count('done')}  ·  실패 {states.count('failed')}")

    def _clear_done(self):
        for job in list(self.jobs.values()):
            if job.state == "done":
                self.remove_job(job)

    def remove_job(self, job):
        if job.state in ACTIVE:
            return
        job.cancel.set()
        job.run_id += 1  # 진행 중인 정보 확인 결과는 무시
        card = self.cards.pop(job.id)
        del self.jobs[job.id]
        group = self.groups.get(job.group)
        if group:
            group.job_ids.remove(job.id)
            card.destroy()
            if group.job_ids:
                group.refresh()
            else:
                self._drop_group(group)
        else:
            self.top.remove(card)
            card.destroy()
        self._relayout()
        self._update_summary()

    def remove_group(self, group):
        group.pending.clear()  # 아직 만들지 않은 카드도 취소
        for job in group.jobs():
            self.remove_job(job)
        if group.id not in self.groups:
            return
        if group.job_ids:  # 다운로드 중인 영상이 남아 있으면 묶음은 유지
            group.refresh()
        else:
            self._drop_group(group)
            self._relayout()
            self._update_summary()

    def _drop_group(self, group):
        del self.groups[group.id]
        self.top.remove(group)
        group.destroy()

    # ---------------- 추가 / 시작 / 취소 ----------------
    def _get_executor(self):
        size = int(self.workers.get())
        idle = not any(j.state in ACTIVE for j in self.jobs.values())
        if self.executor is None or (idle and size != self.executor_size):
            if self.executor:
                self.executor.shutdown(wait=False)
            self.executor = ThreadPoolExecutor(max_workers=size)
            self.executor_size = size
        return self.executor

    def _new_job(self, url, playlist=False):
        job = Job(url, self.out_var.get() or DEFAULT_OUT, self.mode.get(), RESOLUTIONS[self.resolution.get()],
                  self.audio.get(), self.auto_start.get(), playlist=playlist)
        self.jobs[job.id] = job
        card = DownloadCard(self.list, self, job)
        self.cards[job.id] = card
        self.top.insert(0, card)  # 새로 추가한 항목은 맨 위에 보이게
        self._relayout()
        self._update_summary()
        self.list._parent_canvas.yview_moveto(0)
        self.add_executor.submit(self._resolve, job, job.run_id)
        return job

    def _expand(self, job, title, channel, entries):
        """재생목록 주소 카드를 재생목록 묶음으로 바꾼다"""
        out_dir = job.out_dir / safe_folder_name(title) if self.playlist_folder.get() else job.out_dir
        group = PlaylistGroup(self.list, self, title, channel, out_dir, job.cap)
        self.groups[group.id] = group
        old = self.cards.pop(job.id)
        del self.jobs[job.id]
        self.top[self.top.index(old)] = group
        old.destroy()
        group.pending = list(enumerate(entries, 1))
        group.total = len(entries)
        group.defaults = (job.video_mode, job.cap, job.audio_mode, job.auto)
        if group.total > AUTO_COLLAPSE:
            # 영상이 많으면 불러오는 동안 접어 둔다 (카드 수십 개가 동시에 바뀌면 화면이 멈칫한다)
            # 진행 상황은 묶음 머리에 보이고, 다 불러오면 자동으로 펼친다
            group.toggle()
            group.auto_expand = True
        group.refresh()
        self._relayout()
        self._build_group(group)

    def _build_group(self, group):
        """카드를 몇 개씩 나눠 만들어 재생목록이 커도 화면이 멈추지 않게 한다"""
        if group.id not in self.groups:
            return
        video_mode, cap, audio_mode, auto = group.defaults
        for i, e in group.pending[:2]:
            vurl = e.get("url") or e.get("webpage_url") or f"https://www.youtube.com/watch?v={e['id']}"
            child = Job(vurl, group.out_dir, video_mode, cap, audio_mode, auto,
                        title=e.get("title"), group=group.id, index=i)
            self.jobs[child.id] = child
            self.cards[child.id] = card = group.add(child)
            group.place(card)
            self.info_executor.submit(self._resolve, child, child.run_id)
        del group.pending[:2]
        group.refresh()
        self._update_summary()
        if group.pending:
            self.root.after(15, self._build_group, group)

    def enqueue(self, job):
        card = self.cards[job.id]
        card.apply_to_job()
        job.out_dir.mkdir(parents=True, exist_ok=True)
        job.run_id += 1
        job.cancel = threading.Event()
        job.sizes.clear()
        job.done.clear()
        card.set_progress(0, "")
        card.set_state("queued", "대기 중")
        self._job_changed(job)
        self._get_executor().submit(self._download, job, job.run_id)

    def start_all(self):
        for job in list(self.jobs.values()):
            if job.state == "ready":
                self.enqueue(job)

    def retry(self, job):
        if job.raw is None:
            # 정보 확인부터 실패한 경우
            job.run_id += 1
            self.cards[job.id].set_state("fetching", "다시 불러오는 중")
            self._job_changed(job)
            executor = self.info_executor if job.group else self.add_executor
            executor.submit(self._resolve, job, job.run_id, True)
        else:
            self.enqueue(job)

    def cancel(self, job):
        job.cancel.set()
        if job.state == "queued":
            job.run_id += 1  # 아직 시작 전이면 바로 취소 처리
            self.cards[job.id].set_state("cancelled")
            self._job_changed(job)

    def cancel_all(self):
        for job in list(self.jobs.values()):
            if job.state in ACTIVE:
                self.cancel(job)

    def preview(self, job):
        if job.raw is None:
            return
        job.preview_seq += 1
        self.preview_executor.submit(self._preview, job, job.preview_seq)

    def _job_changed(self, job):
        group = self.groups.get(job.group)
        if group:
            group.refresh()
        self._update_summary()

    # ---------------- 작업 스레드 ----------------
    def _emit(self, kind, job, data=None, run=None):
        self.events.put((kind, job, data, run))

    def _base_opts(self, noplaylist=True):
        opts = {"quiet": True, "no_warnings": True, "noprogress": True, "noplaylist": noplaylist}
        if self.ffmpeg_dir:
            opts["ffmpeg_location"] = self.ffmpeg_dir
        if self.js_runtime:
            opts["js_runtimes"] = self.js_runtime
        return opts

    def _extract_raw(self, url, noplaylist=True):
        with yt_dlp.YoutubeDL(self._base_opts(noplaylist)) as ydl:
            return ydl.extract_info(url, download=False, process=False)

    def _resolve(self, job, run, auto=None):
        """영상 정보를 가져온다. 재생목록이면 재생목록 묶음으로 펼친다."""
        try:
            if run != job.run_id:  # 기다리는 동안 삭제됨
                return
            self._emit("loading", job, ("재생목록의 영상 목록을 가져오는 중" if job.is_list else
                                        "영상 정보를 가져오는 중", None), run)
            url = job.url
            for _ in range(3):  # 단축 주소 등 리다이렉트
                raw = self._extract_raw(url, noplaylist=not job.playlist)
                if raw.get("_type") not in ("url", "url_transparent"):
                    break
                url = raw["url"]
            if raw.get("_type") in ("playlist", "multi_video"):
                # 재생목록은 페이지 단위로 받아 오므로 찾은 개수를 중간중간 알려 준다
                self._emit("loading", job, (None, "목록 받는 중"), run)
                entries, last = [], 0.0
                for e in raw.get("entries") or []:
                    if run != job.run_id:
                        return
                    if e:
                        entries.append(e)
                    if time.monotonic() - last > 0.3:
                        last = time.monotonic()
                        self._emit("loading", job, (None, f"영상 {len(entries)}개 찾음"), run)
                title = raw.get("title") or "재생목록"
                channel = raw.get("channel") or raw.get("uploader") or ""
                self._emit("expand", job, (title, channel, entries), run)
                return
            job.raw, job.raw_time = raw, time.time()
            self._emit("ready", job, (raw.get("title") or job.url, resolution_options(raw),
                                      job.auto if auto is None else auto), run)
            thumb = fetch_thumbnail(raw)
            if thumb:
                self._emit("thumb", job, thumb, run)
        except Exception as e:
            self._emit("state", job, ("failed", self._short_err(e)), run)

    def _preview(self, job, seq):
        try:
            mode = build_mode(job.video_mode, job.height, job.audio_mode)
            with yt_dlp.YoutubeDL(self._base_opts() | mode) as ydl:
                info = ydl.process_ie_result(copy.deepcopy(job.raw), download=False)
            text, _ = selection_summary(info)
            self._emit("preview", job, (seq, f"선택: {text}"))
        except Exception as e:
            self._emit("preview", job, (seq, f"선택한 조건의 스트림이 없습니다: {self._short_err(e)}"))

    def _download(self, job, run):
        if run != job.run_id:
            return
        cancel = job.cancel

        def hook(d):
            if cancel.is_set():
                raise Cancelled
            info = d.get("info_dict") or {}
            fid = info.get("format_id", "?")
            if d["status"] == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate")
                if total:
                    job.sizes[fid] = total
                job.done[fid] = d.get("downloaded_bytes") or 0
                now = time.monotonic()
                if now - job.last_emit < 0.15:
                    return
                job.last_emit = now
                total_all = sum(job.sizes.values())
                done_all = sum(job.done.values())
                frac = done_all / total_all if total_all else 0
                part = "영상" if info.get("vcodec", "none") != "none" else "음성"
                speed = d.get("speed")
                text = "   ".join(p for p in (
                    f"{frac * 100:.1f}%",
                    f"{fmt_bytes(done_all)} / {fmt_bytes(total_all)}" if total_all else "",
                    f"{fmt_bytes(speed)}/s" if speed else "",
                    f"남은 시간 {fmt_eta(d.get('eta'))}" if d.get("eta") is not None else "",
                    f"({part})",
                ) if p)
                self._emit("progress", job, (frac, text), run)
            elif d["status"] == "finished":
                job.done[fid] = job.sizes.get(fid, job.done.get(fid, 0))

        def pp_hook(d):
            if d["status"] == "started" and d.get("postprocessor") in ("Merger", "VideoRemuxer"):
                self._emit("state", job, ("merging", None), run)

        opts = self._base_opts() | build_mode(job.video_mode, job.height, job.audio_mode) | {
            "merge_output_format": "mp4",
            "remux_video": "mp4",  # 단일 파일이 webm 등일 경우에도 재인코딩 없이 MP4 컨테이너로 변환
            "outtmpl": str(job.out_dir / "%(title)s [%(id)s].%(ext)s"),
            "windowsfilenames": True,
            "concurrent_fragment_downloads": 4,
            "retries": 10,
            "fragment_retries": 10,
            "continuedl": True,
            "progress_hooks": [hook],
            "postprocessor_hooks": [pp_hook],
        }
        try:
            if cancel.is_set():
                raise Cancelled
            if job.raw is None or time.time() - job.raw_time > RAW_MAX_AGE:
                job.raw, job.raw_time = self._extract_raw(job.url), time.time()
            with yt_dlp.YoutubeDL(opts) as ydl:
                selected = ydl.process_ie_result(copy.deepcopy(job.raw), download=False)
                text, sizes = selection_summary(selected)
                job.sizes.update(sizes)
                self._emit("meta", job, text, run)
                self._emit("state", job, ("downloading", "다운로드 시작"), run)
                info = ydl.process_ie_result(copy.deepcopy(job.raw), download=True)
            downloads = info.get("requested_downloads") or [{}]
            job.filepath = downloads[0].get("filepath") or info.get("filepath")
            size = Path(job.filepath).stat().st_size if job.filepath and Path(job.filepath).exists() else 0
            self._emit("state", job, ("done", f"저장 완료 · {fmt_bytes(size)}"), run)
        except Cancelled:
            self._emit("state", job, ("cancelled", None), run)
        except Exception as e:
            if cancel.is_set():
                self._emit("state", job, ("cancelled", None), run)
            else:
                self._emit("state", job, ("failed", self._short_err(e)), run)

    @staticmethod
    def _short_err(e):
        msg = str(e).replace("ERROR: ", "").strip()
        return msg[:140]

    # ---------------- 이벤트 처리 (메인 스레드) ----------------
    def _tick_loading(self):
        """불러오는 중인 카드·재생목록의 스피너와 경과 시간을 갱신"""
        self._spin = (self._spin + 1) % len(SPINNER)
        frame = SPINNER[self._spin]
        for card in self.cards.values():
            if card.job.state == "fetching" and not card.job.group:
                card.tick_loading(frame)
        for group in self.groups.values():
            group.tick_loading(frame)
        self.root.after(150, self._tick_loading)

    def _poll_events(self):
        # 한 번에 오래 붙잡지 않도록 처리 시간을 나눈다 (남은 이벤트는 곧바로 이어서 처리)
        deadline = time.perf_counter() + 0.04
        try:
            while time.perf_counter() < deadline:
                kind, job, data, run = self.events.get_nowait()
                card = self.cards.get(job.id)
                if card is None or (run is not None and run != job.run_id):
                    continue
                if kind == "state":
                    card.set_state(*data)
                    self._job_changed(job)
                elif kind == "progress":
                    card.set_progress(*data)
                    group = self.groups.get(job.group)
                    if group:
                        group.refresh()
                elif kind == "meta":
                    card.set_meta(data)
                elif kind == "thumb":
                    card.set_thumb(data)
                elif kind == "ready":
                    title, options, auto = data
                    if job.is_list:
                        job.is_list = False
                        card.as_video()
                    card.set_title(title)
                    card.set_resolutions(options)
                    card.set_state("ready")
                    self._job_changed(job)
                    self.preview(job)
                    if auto:
                        self.enqueue(job)
                elif kind == "preview":
                    seq, text = data
                    if seq == job.preview_seq and job.state in EDITABLE:
                        card.set_meta(text)
                elif kind == "loading":
                    if job.state == "fetching":
                        card.set_loading(*data)
                elif kind == "expand":
                    self._expand(job, *data)
        except queue.Empty:
            pass
        self.root.after(80 if self.events.empty() else 10, self._poll_events)


def main():
    settings = load_settings()
    ctk.set_appearance_mode({"라이트": "light", "다크": "dark", "시스템": "system"}.get(settings.get("theme"), "dark"))
    root = ctk.CTk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
