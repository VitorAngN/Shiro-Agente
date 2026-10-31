"""Núcleo do SHIRO: lógica pura, sem I/O.

Contém entidades, eventos, portas (``typing.Protocol``), o roteador de intenções,
o loop do agente e o montador de contexto. Não importa nenhum adaptador: a regra
é verificada na CI pelo ``import-linter`` (ADR-0002).
"""
