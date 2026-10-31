from __future__ import annotations

from pathlib import Path

from shiro import paths

WINDOWS_ENV = {
    "APPDATA": "C:/Users/usuario/AppData/Roaming",
    "LOCALAPPDATA": "C:/Users/usuario/AppData/Local",
}


def test_windows_uses_appdata_folders() -> None:
    assert paths.config_file(env=WINDOWS_ENV, platform="win32") == Path(
        "C:/Users/usuario/AppData/Roaming/SHIRO/shiro.toml"
    )
    assert paths.data_dir(env=WINDOWS_ENV, platform="win32") == Path(
        "C:/Users/usuario/AppData/Local/SHIRO"
    )
    assert paths.log_dir(env=WINDOWS_ENV, platform="win32").name == "logs"


def test_other_platforms_follow_xdg() -> None:
    env = {"XDG_CONFIG_HOME": "/cfg", "XDG_DATA_HOME": "/dados"}

    assert paths.config_file(env=env, platform="linux") == Path("/cfg/shiro/shiro.toml")
    assert paths.data_dir(env=env, platform="linux") == Path("/dados/shiro")


def test_fallbacks_when_variables_are_missing() -> None:
    assert paths.config_dir(env={}, platform="win32").parts[-2:] == ("Roaming", "SHIRO")
    assert paths.data_dir(env={}, platform="win32").parts[-2:] == ("Local", "SHIRO")
    assert paths.config_dir(env={}, platform="linux").parts[-2:] == (".config", "shiro")
    assert paths.data_dir(env={}, platform="linux").parts[-3:] == (".local", "share", "shiro")


def test_explicit_overrides_win() -> None:
    env = {**WINDOWS_ENV, "SHIRO_CONFIG": "/x/meu.toml", "SHIRO_DATA_DIR": "/x/dados"}

    assert paths.config_file(env=env, platform="win32") == Path("/x/meu.toml")
    assert paths.data_dir(env=env, platform="win32") == Path("/x/dados")
