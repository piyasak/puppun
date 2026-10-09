"""E-50: the setup's PATH edits (pure parts; the registry write is checked on the real PC)."""

from pathlib import Path

from agent.setup_win import path_with, path_without

APP = Path(r"C:\Users\u\AppData\Local\Programs\punpun-agent")


def test_adds_the_folder_once():
    assert path_with(r"C:\a;C:\b", APP) == rf"C:\a;C:\b;{APP}"
    assert path_with("", APP) == str(APP)
    assert path_with(rf"C:\a;{APP}", APP) is None


def test_already_there_ignores_case_quotes_and_trailing_slash():
    assert path_with(rf'C:\a;"{str(APP).upper()}\"', APP) is None


def test_empty_entries_are_dropped_not_multiplied():
    assert path_with(r"C:\a;;C:\b;", APP) == rf"C:\a;C:\b;{APP}"


def test_remove_only_that_folder():
    assert path_without(rf"C:\a;{APP};C:\b", APP) == r"C:\a;C:\b"
    assert path_without(r"C:\a;C:\b", APP) is None
