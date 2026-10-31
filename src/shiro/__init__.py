"""SHIRO: assistente pessoal com IA para Windows.

A documentação de arquitetura fica em ``docs/03-arquitetura.md``.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("shiro")
except PackageNotFoundError:  # pragma: no cover - só acontece fora de um ambiente instalado
    __version__ = "0.0.0+desconhecida"

__all__ = ["__version__"]
