# -*- coding: utf-8 -*-
"""把氛围背景的 blur(70px) saturate(1.5) 预先烘焙成一张小图 ui/nanwei/wall-amb.png。

为什么: 背景原来是 <img src=wall.svg> 上挂实时 CSS 滤镜 blur(70px)。窗口尺寸每变一次,
浏览器都要把整块大模糊重算一遍 —— Win7 版 (QtWebEngine / Chromium 83) 拉大窗口时
新露出的区域先黑一大块, 松手后要 0.6~1s 才铺满 (2026-10-12 实测)。烘焙后窗口缩放只是
缩放一张图, 实时滤镜只剩便宜的 brightness()。

几何按设计尺寸 690x420 复刻 style.css 的 .ambient img:
  盒子 = 140% x 150% = 966 x 630 (CSS px), wall.svg (1600x900) 以 object-fit: cover 铺进盒子;
  blur 作用在盒子局部坐标 (transform: scale(1.1) 仍留给 CSS)。
  CSS blur 在预乘 alpha 空间做、盒子外视为透明 -> 这里同样预乘模糊再反预乘, 存带 alpha 的 PNG,
  浅色皮肤下盒子边缘的渐隐才和原来一致。saturate 按 CSS Filter Effects 规范矩阵, 在反预乘后做。

用法 (仓库根目录): py -3.12 tools/bake_ambient.py
  需要 py3.12 装 numpy + Pillow; SVG 由 .venv38 里的 PyQt5 QtSvg 渲染 (和 Win7 版同一个引擎)。
"""
import os
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SVG = os.path.join(ROOT, "ui", "nanwei", "wall.svg")
OUT = os.path.join(ROOT, "ui", "nanwei", "wall-amb.png")
QT_PY = os.path.join(ROOT, ".venv38", "Scripts", "python.exe")

BOX_W, BOX_H = 966, 630          # 690*1.4, 420*1.5
SIGMA = 70                       # CSS blur(70px) 的标准差
SATURATE = 1.5
PAD = 3 * SIGMA                  # 盒子外留透明边, 让模糊能"吃进"透明
DOWN = 4                         # 模糊后再缩小 4 倍存盘 (σ 仍有 17px, 放大回去看不出块)

_RENDER = r'''
import sys
from PyQt5 import QtCore, QtGui, QtSvg, QtWidgets
app = QtWidgets.QApplication(sys.argv[:1])
w, h, out, svg = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3], sys.argv[4]
img = QtGui.QImage(w, h, QtGui.QImage.Format_ARGB32)
img.fill(QtCore.Qt.transparent)
p = QtGui.QPainter(img)
p.setRenderHint(QtGui.QPainter.Antialiasing)
QtSvg.QSvgRenderer(svg).render(p, QtCore.QRectF(0, 0, w, h))
p.end()
img.save(out)
'''


def render_svg(w, h):
    """wall.svg 按 object-fit: cover 渲染成 w x h 后的完整图 (未裁剪)。"""
    tmp = os.path.join(tempfile.mkdtemp(), "wall.png")
    subprocess.check_call([QT_PY, "-c", _RENDER, str(w), str(h), tmp, SVG])
    return Image.open(tmp).convert("RGB")


def saturate(rgb, s):
    m = np.array([
        [0.213 + 0.787 * s, 0.715 - 0.715 * s, 0.072 - 0.072 * s],
        [0.213 - 0.213 * s, 0.715 + 0.285 * s, 0.072 - 0.072 * s],
        [0.213 - 0.213 * s, 0.715 - 0.715 * s, 0.072 + 0.928 * s],
    ])
    return np.clip(rgb @ m.T, 0, 1)


def main():
    scale = max(BOX_W / 1600.0, BOX_H / 900.0)            # object-fit: cover
    fw, fh = round(1600 * scale), round(900 * scale)
    full = render_svg(fw, fh)
    cx, cy = (fw - BOX_W) // 2, (fh - BOX_H) // 2
    boxed = full.crop((cx, cy, cx + BOX_W, cy + BOX_H))

    cw, ch = BOX_W + 2 * PAD, BOX_H + 2 * PAD
    color = Image.new("RGB", (cw, ch), (0, 0, 0))          # 预乘: 盒子外 = 透明黑
    color.paste(boxed, (PAD, PAD))
    alpha = Image.new("L", (cw, ch), 0)
    alpha.paste(255, (PAD, PAD, PAD + BOX_W, PAD + BOX_H))

    blur = ImageFilter.GaussianBlur(SIGMA)
    c = np.asarray(color.filter(blur), dtype=np.float64) / 255.0
    a = np.asarray(alpha.filter(blur), dtype=np.float64)[..., None] / 255.0
    c, a = c[PAD:PAD + BOX_H, PAD:PAD + BOX_W], a[PAD:PAD + BOX_H, PAD:PAD + BOX_W]
    rgb = saturate(np.where(a > 1e-4, c / np.maximum(a, 1e-4), 0), SATURATE)

    rgba = np.concatenate([rgb, a], axis=2)
    img = Image.fromarray(np.round(rgba * 255).astype(np.uint8), "RGBA")
    img = img.resize((BOX_W // DOWN, BOX_H // DOWN), Image.LANCZOS)
    img.save(OUT, optimize=True)
    print("wrote %s (%dx%d, %d bytes)" % (OUT, img.width, img.height, os.path.getsize(OUT)))


if __name__ == "__main__":
    sys.exit(main())
