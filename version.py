# -*- coding: utf-8 -*-
"""版本信息 —— 标题栏显示 + "检查更新"。

版本号 = git 提交数 (rev-list --count HEAD), 单调递增, 不用手动维护。
- 打包成 exe 时: 由 spec 在构建前生成 `_build_info.py`, 焊进 exe (exe 里没有 .git)。
- 源码直接跑时: 现场读 git 仓库。
两条路都不通 (比如别人拷了一份没 .git 的源码) 就显示 v?, 不影响功能。

南微控制台的代码在 feat/phytune-p0 分支上 (master 是 dxva2 那版旧控制台), 所以
检查更新对比的是这个分支, 不是 main/master。
"""
import os
import subprocess

REPO = "nishizhen302/ddcci-host"
BRANCH = "feat/phytune-p0"
REPO_URL = "https://github.com/nishizhen302/ddcci-host/tree/" + BRANCH

_HERE = os.path.dirname(os.path.abspath(__file__))

UNKNOWN = {"version": "?", "sha": "", "sha_full": "", "date": "", "source": "unknown"}


def _from_build_info():
    """打包时焊进去的版本 (spec 生成 _build_info.py)。"""
    try:
        import _build_info as b
        return {"version": b.VERSION, "sha": b.SHA, "sha_full": b.SHA_FULL,
                "date": b.DATE, "source": "build"}
    except Exception:
        return None


def _from_git():
    """源码直接跑: 现场问 git。"""
    def run(args):
        return subprocess.run(["git"] + args, cwd=_HERE, capture_output=True,
                              text=True, timeout=5).stdout.strip()
    try:
        count = run(["rev-list", "--count", "HEAD"])
        if not count:
            return None
        return {
            "version": count,
            "sha": run(["rev-parse", "--short", "HEAD"]),
            "sha_full": run(["rev-parse", "HEAD"]),
            "date": run(["log", "-1", "--format=%cd", "--date=format:%Y-%m-%d"]),
            "source": "git",
        }
    except Exception:
        return None


def get_local():
    return _from_build_info() or _from_git() or dict(UNKNOWN)
