"""Iniciar com o Windows (ADR-0008): tarefa no Agendador, no logon do usuário.

A tarefa roda ``shiro-tray.exe`` (sem janela de console) 30 s depois do logon,
sem privilégio de administrador, só com o usuário conectado, e reinicia se
falhar. Se o Windows negar a criação da tarefa (algumas contas exigem
elevação para gatilho de logon), cai para a chave ``Run`` do registro do
usuário, que não pede permissão.

O XML da tarefa leva o nome do usuário e caminhos da máquina: é gerado na hora
num arquivo temporário e nunca vai para o repositório.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape

TASK_NAME = "SHIRO"
_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_CREATE_NO_WINDOW = 0x08000000


class AutostartError(RuntimeError):
    pass


@dataclass(frozen=True)
class Launcher:
    command: str
    arguments: str
    working_dir: str

    @property
    def command_line(self) -> str:
        return f'"{self.command}" {self.arguments}'.strip()


def launcher(python: Path | None = None) -> Launcher:
    """O executável da bandeja ao lado do Python do ambiente (criado pelo ``uv sync``)."""
    python = python or Path(sys.executable)
    scripts = python.parent
    tray = scripts / ("shiro-tray.exe" if sys.platform == "win32" else "shiro-tray")
    project = scripts.parent.parent if scripts.parent.name == ".venv" else Path.cwd()
    if tray.is_file():
        return Launcher(str(tray), "", str(project))
    pythonw = scripts / "pythonw.exe"
    interpreter = pythonw if pythonw.is_file() else python
    return Launcher(str(interpreter), "-m shiro.tray_main", str(project))


def task_xml(target: Launcher, user: str, delay_s: int = 30) -> str:
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>SHIRO: assistente pessoal. Inicia na bandeja depois do logon.</Description>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <UserId>{escape(user)}</UserId>
      <Delay>PT{delay_s}S</Delay>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{escape(user)}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <RestartOnFailure>
      <Interval>PT1M</Interval>
      <Count>3</Count>
    </RestartOnFailure>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <Enabled>true</Enabled>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{escape(target.command)}</Command>
      <Arguments>{escape(target.arguments)}</Arguments>
      <WorkingDirectory>{escape(target.working_dir)}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def _windows_user() -> str:
    domain = os.environ.get("USERDOMAIN", "")
    name = os.environ.get("USERNAME", "")
    return f"{domain}\\{name}" if domain else name


def _schtasks(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - argumentos fixos, sem shell
        ["schtasks", *args],  # noqa: S607 - ferramenta do sistema, no PATH do Windows
        capture_output=True,
        text=True,
        check=False,
        creationflags=_CREATE_NO_WINDOW,
    )


def status() -> str | None:
    """Como o SHIRO inicia com o Windows: "tarefa", "registro" ou ``None``."""
    if sys.platform != "win32":
        return None
    if _schtasks("/Query", "/TN", TASK_NAME).returncode == 0:
        return "tarefa"
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            winreg.QueryValueEx(key, TASK_NAME)
    except OSError:
        return None
    return "registro"


def enable() -> str:
    """Liga o início no logon. Devolve o mecanismo usado."""
    if sys.platform != "win32":
        msg = "iniciar com o sistema só está implementado no Windows"
        raise AutostartError(msg)
    target = launcher()
    with tempfile.TemporaryDirectory(prefix="shiro-") as folder:
        xml = Path(folder) / "tarefa.xml"
        xml.write_text(task_xml(target, _windows_user()), encoding="utf-16")
        result = _schtasks("/Create", "/TN", TASK_NAME, "/XML", str(xml), "/F")
    if result.returncode == 0:
        _remove_run_key()
        return "tarefa"
    import winreg

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
        winreg.SetValueEx(key, TASK_NAME, 0, winreg.REG_SZ, target.command_line)
    return "registro"


def disable() -> bool:
    """Desliga o início no logon. ``True`` se havia algo para remover."""
    if sys.platform != "win32":
        return False
    removed = _schtasks("/Delete", "/TN", TASK_NAME, "/F").returncode == 0
    return _remove_run_key() or removed


def _remove_run_key() -> bool:
    if sys.platform != "win32":
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, TASK_NAME)
    except OSError:
        return False
    return True
