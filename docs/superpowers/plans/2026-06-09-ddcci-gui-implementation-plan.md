# DDC/CI 控制 GUI · 实现计划书

**日期:** 2026-06-09
**状态:** 待执行
**基准设计:** [`specs/2026-06-09-ddcci-gui-design.md`](../specs/2026-06-09-ddcci-gui-design.md)（已通过评审）
**关联:** 上位机 `ddcci.py`（已打通），固件侧 VCP 0x72 gamma 已验证

> 本文把设计稿拆成可执行、可逐阶段验收的实现步骤。每个阶段结束都有明确的"完成判定"，做完一阶段确认无误再进下一阶段。

---

## 0. 前置与约定

- **工作目录:** `C:\Users\61093\Desktop\monitor firmware\ddcci_host`
- **新增唯一三方依赖:** `pywebview`（`py -3 -m pip install pywebview`）。Win11 自带 Edge WebView2 运行时，无需另装。
- **Python:** 复用现有 `py -3`（当前环境 3.14）。
- **不破坏现状:** `ddcci.py` 的 CLI 行为保持可用（抽取核心后改为薄壳调用，命令行接口与输出不变）。
- **运行时编码:** 沿用 `PYTHONUTF8=1`，避免中文控制台乱码。
- **目标目录结构（最终）:**

```
ddcci_host/
├ ddcci.py                  # CLI 薄壳（保留命令行入口）
├ ddcci_core.py             # 纯逻辑 API，无 CLI 无界面，可单测
├ backends/
│  ├ __init__.py
│  ├ base.py                # Backend 抽象基类
│  └ dxva2_backend.py       # Backend A（从 ddcci.py 抽取 dxva2/ctypes）
├ app.py                    # pywebview 启动 + JS 桥
├ ui/
│  ├ index.html
│  ├ style.css
│  └ app.js
├ tests/
│  ├ test_core.py
│  └ test_caps_render.py    # caps→控件集（如用 JS 测则放 ui 下）
└ docs/superpowers/{specs,plans}/...
```

---

## 阶段 1 · 核心抽取与可插拔后端骨架

**目标:** 把 dxva2/ctypes 逻辑从 `ddcci.py` 抽到 `backends/dxva2_backend.py`，对外统一 `Backend` 接口；`ddcci_core.py` 选定后端并暴露语义 API；`ddcci.py` 改为薄壳。**不碰界面。**

**步骤:**

1. **`backends/base.py`** — 定义抽象 `Backend`，方法签名固定为设计稿的四件套：
   - `enum_monitors() -> list[Monitor]`（`Monitor` = 描述 + 不透明句柄/id）
   - `get_vcp(handle, code) -> (current, maximum) | None`
   - `set_vcp(handle, code, value) -> bool`
   - `read_caps(handle) -> str | None`
   - 外加生命周期 `close()`（对应 dxva2 的 `DestroyPhysicalMonitor`）。
2. **`backends/dxva2_backend.py`** — 从 `ddcci.py` 平移这些片段（行号为当前文件参考）：
   - dxva2 `WinDLL` 加载 + `PHYSICAL_MONITOR` 结构 + 全部 `argtypes/restype` 声明（`ddcci.py:32–55`）—— **64 位句柄截断坑、VCP code 用 `c_ubyte` 这两条必须原样带过来**。
   - `_enum_hmonitors` / `get_physical_monitors` / `destroy` / `vcp_get` / `vcp_set` / `read_caps`（`ddcci.py:58–127`）映射到 Backend 方法。
   - 句柄生命周期：后端内部持有 physical monitor 句柄表，`enum` 时建、`close` 时 `DestroyPhysicalMonitor`，不让上层管 ctypes 句柄。
3. **`ddcci_core.py`** — `select_backend(name="dxva2")` 返回后端实例；再暴露 `enum_monitors / get_vcp / set_vcp / read_caps` 透传，外加：
   - `pick_default_monitor()` —— 读各显示器 caps，认 `model(RTK)` 那块板做默认选中（内存记录：板=显示器序号易变，靠 caps 的 `model(RTK)` 认）。
   - `parse_caps(caps_str) -> {vcp_codes:set, raw:str, ...}` —— 解析 caps 串取支持的 VCP 列表（阶段 3 控件生成要用，这里先实现并单测）。
4. **`ddcci.py` 改薄壳** — `cmd_list/caps/get/set/probe/gamma/main`（`ddcci.py:136–213`）改为调用 `ddcci_core`，删掉重复的 ctypes 实现。命令行用法与输出保持不变。
5. **`tests/test_core.py`** — mock dxva2 调用，断言：`get_vcp` 句柄不被 32 位截断（传 8 字节句柄值校验 argtypes 生效路径）、`set_vcp` 返回布尔、`parse_caps` 对给定 caps 串取出正确 VCP 集合（含 `72`）。

**完成判定:**
- `set PYTHONUTF8=1 && py -3 ddcci.py list` / `caps 3` / `gamma 4 3` 行为与抽取前一致（对真板冒烟，gamma 切档肉眼可见）。
- `py -3 -m pytest tests/test_core.py` 全绿。
- `ddcci.py` 内不再直接出现 `dxva2.` 调用（全部下沉到后端）。

---

## 阶段 2 · pywebview 外壳与 JS 桥（最小可跑窗口）

**目标:** 起一个空壳窗口，前端能通过 `window.pywebview.api.*` 拿到真实显示器列表。**只验证桥通，不做样式。**

**步骤:**

1. 安装并验证 `pywebview`（`pip install pywebview`；起一个 hello 窗口确认 WebView2 可用）。
2. **`app.py`** — `Api` 类把 `ddcci_core` 方法暴露给前端：`list_monitors()` / `get_vcp(code, mon_id)` / `set_vcp(code, value, mon_id)` / `get_caps(mon_id)` / `set_backend(name)`。
   - **桥接层职责（设计稿 §4）:** 捕获后端异常，**翻译成前端可显示的状态对象** `{ok, value?, error?, hint?}`，绝不把异常抛进 JS。
   - 启动即 `enum_monitors()`，默认选中 `pick_default_monitor()`。
3. **`ui/index.html` + `ui/app.js`** 最小版 — 页面加载后调 `list_monitors()`，把显示器渲染成下拉，控制台打印 caps。无 CSS。
4. 句柄/线程注意：pywebview 的 JS 调用在独立线程，dxva2 句柄按"每次调用取→用→可缓存于后端"处理，避免跨线程持有失效句柄；必要时每次操作前按 `mon_id` 重新解析当前句柄。

**完成判定:** 启动 `py -3 app.py` 弹窗，下拉里出现真实显示器、默认选中 RTK 板，控制台能打印其 caps 串。

---

## 阶段 3 · caps 驱动的动态控件引擎（核心）

**目标:** 落地设计稿 §6 —— 选定显示器 → `read_caps` → 据 caps 自动生成控件集，**不同显示器控件不同**。这是整个项目的扩展地基，优先于美化。

**步骤:**

1. **`ui/app.js` 控件渲染器:**
   - `CONTROL_HINTS` 表（设计稿 §6）：0x72 segment(OFF/1.8/2.0/2.2/2.4)、0x10 slider、0x12 slider、0x14 segment（options 据 caps 实际回报填）。
   - 控件类型注册表：`slider`（滑块 + 可点输入读数 + −/+ 微调）、`segment`（分段按钮）、`stepper`（±步进，调试预留）、`raw`（任意 VCP 手输，调试/自定义预留）。
   - 渲染流程：`parse_caps` 给的 VCP 集合 → 命中 hints 用友好控件，未命中落 `raw` 兜底。
2. **读写接线:** 每个控件初始化时 `get_vcp` 填当前值/最大值；用户操作 → `api.set_vcp` → 成功后**即时回读确认**并更新读数（设计稿 §9 步骤 3）。
3. **信息条:** 显示器接口/分辨率、信号源 0x60（只读展示）。"待验证"VCP（0x12/0x14/0x60）设了读不回 → 控件标"未响应"，不阻塞其余。
4. **切显示器** → 重跑 caps→控件集刷新（设计稿 §9 步骤 4）。
5. **`tests/test_caps_render.py`**（或 JS 测）— 给定不同 caps 串，断言生成对应控件 DOM，含 raw 兜底与色温 options 填充。

**完成判定:**
- 选 RTK 板：自动出现 Gamma 分段 + 亮度滑块（已验证 VCP），对比度/色温按 caps 出现或标未响应。
- Gamma 切 1.8↔2.4 屏幕肉眼可见变化（端到端冒烟，固件已知支持）。
- 喂一个构造的不同 caps 串，控件集随之不同。

---

## 阶段 4 · 视觉与换肤（科技感）

**目标:** 落地设计稿 §8。功能已通后再上样式，避免样式返工。

**步骤:**

1. **`ui/style.css` 双主题 CSS 变量:** `--bg/--surface/--text/--accent/--border`…；深色（#0d0d0f 底 / 白强调 / 绿状态点）、白底（#fafafa / 黑强调）。根节点 `data-theme="dark|light"` 切换，一键换肤按钮，`localStorage` 记忆（或经后端配置文件）。
2. **共同视觉语言:** 大留白、`tabular-nums` 等宽数字、24px 等比线性图标、整体字号偏大一号、单一强调色。
3. **科技感元素:** 顶部链路**呼吸脉冲点**（连接状态）、Gamma **实时 γ 曲线预览**、色温**暖→冷渐变滑轨**、控件 hover/按压微反馈（**只动 `transform/opacity`**，不触发重排）。
4. 对照 `web-design-guidelines` skill 自查一遍（对比度、焦点态、动效克制）。

**完成判定:** 深/浅皮肤一键切换且记忆生效；γ 曲线随档位实时变化；动效仅 transform/opacity；过一遍 web-design-guidelines 无明显违规。

---

## 阶段 5 · 错误处理、后端选择位与收尾

**目标:** 落地设计稿 §5/§10，补齐健壮性与未来扩展的 UI 预留位。

**步骤:**

1. **错误处理（§10）:** 没找到物理显示器 / VCP 读写失败 / 选错显示器 → **顶部状态栏变灰 + 文案含下一步建议**，不弹炸窗。状态更新用 `aria-live`。
2. **"扫不到可控显示器"专项提示:** 明确文案——"请确认屏接在独立显卡输出、且该显卡 DDC/CI 已开"（核显常不暴露 DDC/CI = 用户"核显不通独显通"的根因，属环境问题，不是地址问题）。
3. **后端 + 地址选择位（§5）:** UI 放"通信后端 / 地址"选择位，雏形里**后端锁 dxva2、地址灰显锁 0x6E**；Backend B（硬件调试器 / 低层 I2C / 0x5E）接口预留不实现。
4. 收尾：README（启动方式 `py -3 app.py`、依赖、已知约束），更新内存 `project_ddcci_control` 标注 GUI 雏形完成。

**完成判定:** 拔线/选错屏/接核显各场景都给友好灰条提示不崩；后端/地址位可见且按设计锁定；端到端冒烟（启动→选板→Gamma 1.8↔2.4 肉眼可见）通过。

---

## 本期不做（YAGNI，设计稿 §12）

- Backend B（硬件调试器 / 低层 I2C / 自定义地址 0x5E）—— 仅预留接口与 UI 位。
- 高级/调试区完整实现 —— 架构（stepper/raw 控件、hints 表）已预留。
- 信号源切换写入（本期只读展示）。
- exe 打包（PyInstaller，后续）、多语言、自动更新、云同步、第三套皮肤。

---

## 风险与依赖

| 风险 | 影响 | 缓解 |
|------|------|------|
| pywebview / WebView2 在该机不可用 | 阶段 2 阻塞 | 先用 hello 窗口验证；必要时回退到本地 http + 系统浏览器方案（接口不变） |
| dxva2 句柄跨 JS 线程失效 | 控件读写偶发失败 | 后端按 `mon_id` 每次操作重解析句柄，不长持 |
| "待验证"VCP（0x12/0x14/0x60）真机读不回 | 控件显示未响应 | 设计已允许：标未响应、不阻塞框架 |
| caps 串格式与预期不符 | 控件集生成异常 | `parse_caps` 单测覆盖 + raw 兜底 |

## 执行顺序

阶段严格串行（1→5），每阶段"完成判定"通过再进下一阶段。阶段 1、3 是关键路径（抽取质量 + caps 引擎决定后续扩展性），值得多花时间；阶段 4 纯前端可快速迭代。
