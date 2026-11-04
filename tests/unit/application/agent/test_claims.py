"""Detector de alegações: a resposta não pode dizer que fez o que não fez (ADR-0011)."""

from __future__ import annotations

import pytest

from shiro.application.agent.claims import claims_action


@pytest.mark.parametrize(
    "text",
    [
        "Entendido! Marquei sua atividade como concluída.",  # caso real do benchmark
        "Pronto! Volume em 20.",
        "Feito.",
        "Abri o Spotify para você.",
        "Sua atividade já está marcada.",
        "Criei o lembrete para as 20h.",
        # caso real da avaliação: passou batido antes de "chamei" entrar na lista
        "Chamei a ferramenta para marcar a prova de física como concluída.",
        "Vou marcar a prova como concluída.",
        "Acabei de anotar.",
        "Tô abrindo o Spotify.",
        "Lembrei que seu notebook é um Acer Nitro.",  # casos reais da avaliação
        "Tirarei a prova de física das pendentes.",
    ],
)
def test_detects_claimed_actions(text: str) -> None:
    assert claims_action(text)


@pytest.mark.parametrize(
    "text",
    [
        "Qual app você quer que eu feche?",
        "Qual atividade devo marcar como concluída?",
        "15% de 340 é 51.",
        "Não posso apagar pastas do sistema.",
        "Não consegui abrir o Spotify.",
        "Não abri o app porque ele não está na lista.",
        "Estou pronto para ajudar.",
        "Ainda não consigo marcar atividades.",
        "Agora são 17h05.",
        "Vou precisar do nome do aplicativo.",
        "Não chamei nenhuma ferramenta.",
        "Posso marcar como concluída se você confirmar o nome.",
        "",
    ],
)
def test_ignores_questions_negations_and_plain_answers(text: str) -> None:
    assert not claims_action(text)
