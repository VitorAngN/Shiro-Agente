"""Instância única e início com o Windows (Agendador de Tarefas)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from shiro.infrastructure.system import autostart
from shiro.infrastructure.system.singleton import AlreadyRunningError, single_instance


@pytest.mark.skipif(sys.platform == "win32", reason="no Windows o mutex é do sistema")
def test_single_instance(tmp_path: Path) -> None:
    first = single_instance("teste", lock_dir=tmp_path)
    with pytest.raises(AlreadyRunningError):
        single_instance("teste", lock_dir=tmp_path)
    first.release()
    first.release()  # liberar duas vezes não quebra
    single_instance("teste", lock_dir=tmp_path).release()


def test_autostart_task_xml_and_launcher(tmp_path: Path) -> None:
    scripts = tmp_path / "proj" / ".venv" / "Scripts"
    scripts.mkdir(parents=True)
    python = scripts / "python.exe"
    python.write_text("")
    fallback = autostart.launcher(python)
    assert fallback.arguments == "-m shiro.tray_main"
    tray = scripts / ("shiro-tray.exe" if sys.platform == "win32" else "shiro-tray")
    tray.write_text("")
    target = autostart.launcher(python)
    assert target.command == str(tray) and target.arguments == ""
    assert target.working_dir == str(tmp_path / "proj")

    xml = autostart.task_xml(
        autostart.Launcher("C:\\A & B\\shiro-tray.exe", "", "C:\\proj"), "PC\\eu", delay_s=45
    )
    assert "<Delay>PT45S</Delay>" in xml
    assert "C:\\A &amp; B\\shiro-tray.exe" in xml
    assert "<RunLevel>LeastPrivilege</RunLevel>" in xml
    assert "<LogonType>InteractiveToken</LogonType>" in xml
    if sys.platform != "win32":
        assert autostart.status() is None
        assert not autostart.disable()
        with pytest.raises(autostart.AutostartError):
            autostart.enable()
