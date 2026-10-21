"""TODO 6.1 – izolace prostředí testů a menu bez načítání .env při importu."""
import importlib
import os
import sys


def test_env_is_isolated_by_autouse_fixture():
    assert os.environ.get("FAE_AUTO_HISTORY") == "0"
    assert not [k for k in os.environ if k.startswith("OLLAMA_")]
    assert [k for k in os.environ if k.startswith("FAE_")] == ["FAE_AUTO_HISTORY"]


def test_menu_import_does_not_touch_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("FAE_PROBE_ENV", "puvodni")
    before = dict(os.environ)
    sys.modules.pop("menu", None)
    menu = importlib.import_module("menu")
    assert dict(os.environ) == before
    assert callable(menu._load_local_env)


def test_menu_main_loads_env_without_overriding(monkeypatch, tmp_path):
    import menu

    fake_root = tmp_path
    (fake_root / ".env").write_text('FAE_MENU_TEST_NEW="abc"\nFAE_MENU_TEST_KEEP=z\n', encoding="utf-8")
    monkeypatch.setattr(menu.os.path, "abspath", lambda p: str(fake_root / "menu.py"))
    monkeypatch.setenv("FAE_MENU_TEST_KEEP", "puvodni")
    monkeypatch.delenv("FAE_MENU_TEST_NEW", raising=False)

    monkeypatch.setattr("builtins.input", lambda *a, **k: "7")
    menu.main()

    assert os.environ["FAE_MENU_TEST_NEW"] == "abc"
    assert os.environ["FAE_MENU_TEST_KEEP"] == "puvodni"
    monkeypatch.delenv("FAE_MENU_TEST_NEW", raising=False)
