# DDC/CI 控制台 · Win7 版构建说明

为在 **Windows 7 (64 位)** 上运行而做的 Qt 版本。和 Win11 版共用同一套
`app.py` / `ddcci_core.py` / `backends` / `ui`,只是把 pywebview 的渲染后端
从 **WebView2(Edge)** 换成 **Qt(PyQt5 + QtWebEngine,自带 Chromium)**。

## 为什么需要单独一版

| 问题 | Win11 版 | Win7 版 |
|------|----------|---------|
| Python | 3.14(不支持 Win7) | **3.8**(Win7 最后支持版) |
| UI 渲染 | WebView2 运行时(Win7 上微软已停止支持) | **QtWebEngine 自带 Chromium**,无需目标机装任何东西 |
| flex `gap` | WebView2 是新 Chromium,原生支持 | QtWebEngine 5.15 = Chromium 83,**不支持 flex gap** → 用 `ui/style.css` 末尾的兼容补丁(margin)复刻间距 |

## 如何构建

需要 **Python 3.8 (64 位)**。本仓库已建好虚拟环境 `.venv38`。

```powershell
# (首次) 建环境 + 装依赖
py -3.8 -m venv .venv38
.\.venv38\Scripts\python.exe -m pip install PyQt5==5.15.2 PyQtWebEngine==5.15.2 qtpy pywebview pyinstaller

# 打包
.\.venv38\Scripts\pyinstaller.exe --noconfirm --clean DDCCI-Win7.spec
```

产物:`dist\DDCCI-Console-Win7\`(整目录,约 290 MB)。
把**整个目录**拷到 Win7,运行里面的 `DDCCI-Console.exe` 即可。

## 关键实现点

- **入口** `app_win7.py`:①设 `DDCCI_GUI=qt` 让 pywebview 走 Qt 后端;
  ②设 `QT_ENABLE_HIGHDPI_SCALING=1` 开启 DPI 感知(否则高 DPI 屏上窗口被系统位图
  拉伸 → 白皮肤露黑边 + 鼠标点击位置偏移);③默认 **GPU 渲染**(resize 流畅)。
  若某机器 QtWebEngine 白屏,启动前设环境变量 `DDCCI_DISABLE_GPU=1` 退回软件渲染。
- **`app.py`** 新增 `DDCCI_GUI` 环境变量选择后端(不设则保持原 Win11 自动探测)。
- **`ui/app.js`**:Qt 后端不处理 `pywebview-drag-region`,故检测到 `QtWebEngine`
  时手动给标题栏挂拖动(复用 `start_resize(HTCAPTION)` 走系统移动循环)。
- **`ui/style.css`** 末尾:Win7/Chromium 83 的 flex-gap 兼容补丁。
- **`DDCCI-Win7.spec`**:`collect_all('PyQt5')` 完整收集 QtWebEngine 运行时
  (QtWebEngineProcess.exe / *.pak / icudtl.dat / locales / ANGLE),UPX 关闭
  (会破坏 Qt DLL)。VC++ 运行库已随包自带,Win7 无需另装。

## Win7 上需确认的事项(本机 Win11 无法替你验的)

1. **窗口拖动 / 边缘缩放**:无边框窗口靠 Win32 消息实现,机制已就绪,但需在
   Win7 上实际拖一拖、拉一拉确认手感。
2. **DDC/CI 控屏**:接上 RL6432 板对应的显示器,确认能枚举到、读到 caps(model RTK)、
   调亮度/对比度/gamma/色温能即时生效。
3. **高分屏**:本版未启用 DPI 缩放;Win7 多为 100% DPI,正常。若是高 DPI 屏可能偏糊。
4. 系统须为 **Windows 7 SP1 (64 位)**(QtWebEngine 5.15 的最低要求)。
