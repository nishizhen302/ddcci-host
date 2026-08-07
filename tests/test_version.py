# -*- coding: utf-8 -*-
"""版本号来源的契约。

版本 = git 提交数, 两条来源: 打包时焊进去的 _build_info, 或源码现场问 git。
两条都不通也必须给出可用的默认值 —— 版本读不到不能让控制台起不来。
"""
import version


def test_get_local_always_returns_full_shape():
    info = version.get_local()
    assert set(info) == {"version", "sha", "sha_full", "date", "source"}
    assert info["source"] in ("build", "git", "unknown")


def test_falls_back_to_unknown_when_both_sources_fail(monkeypatch):
    monkeypatch.setattr(version, "_from_build_info", lambda: None)
    monkeypatch.setattr(version, "_from_git", lambda: None)
    assert version.get_local() == version.UNKNOWN


def test_build_info_wins_over_git(monkeypatch):
    """打包的 exe 里 .git 不存在, 但万一两条都有, 以焊进去的为准 (那才是这份 exe 的版本)。"""
    baked = {"version": "42", "sha": "abc1234", "sha_full": "abc1234" * 5 + "abcde",
             "date": "2026-07-29", "source": "build"}
    monkeypatch.setattr(version, "_from_build_info", lambda: baked)
    monkeypatch.setattr(version, "_from_git", lambda: dict(version.UNKNOWN, version="7"))
    assert version.get_local()["version"] == "42"


def test_unknown_is_not_shared_mutable_state():
    """get_local 返回的默认值必须是副本, 调用方改了不能污染下一次。"""
    got = version.get_local()
    got["version"] = "tampered"
    assert version.UNKNOWN["version"] == "?"


def test_update_check_targets_the_branch_the_nanwei_console_lives_on():
    """南微控制台在 feat/phytune-p0 上, master 是 dxva2 那版旧控制台 —— 别对错分支。"""
    assert version.BRANCH == "feat/phytune-p0"
    assert version.REPO == "nishizhen302/ddcci-host"
    assert version.BRANCH in version.REPO_URL
