"""프로그램 아이콘(assets/app.ico) 생성 - 소프트 블루 둥근 사각형 + 흰색 재생 삼각형

Copyright (c) 2026 최승훈. All rights reserved.
"""
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
ACCENT = (76, 125, 240, 255)  # 프로그램 강조색 #4C7DF0

size = 1024
img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle((40, 40, size - 40, size - 40), radius=230, fill=ACCENT)
# 시각적 중심을 맞추려고 삼각형을 약간 오른쪽으로
d.polygon([(400, 290), (400, 734), (770, 512)], fill=(255, 255, 255, 255))

out = ROOT / "assets" / "app.ico"
img.save(out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
img.resize((256, 256), Image.LANCZOS).save(ROOT / "assets" / "app.png")
print("created", out)
