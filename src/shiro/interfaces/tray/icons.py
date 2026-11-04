"""Ícones da bandeja, desenhados na hora com a paleta da SHIRO (docs/08-identidade.md).

Um disco escuro com um anel na cor do estado e um "visor" no centro:

* livre: branco · ouvindo: vermelho · pensando: âmbar · falando: ciano · pausada: cinza.
"""

from __future__ import annotations

from PIL import Image, ImageDraw

from shiro.interfaces.voice.session import Phase

BACKGROUND = (17, 20, 27, 255)  # #11141B
EDGE = (38, 44, 56, 255)  # #262C38
COLORS = {
    Phase.IDLE: (238, 241, 246, 255),  # #EEF1F6
    Phase.LISTENING: (255, 46, 77, 255),  # #FF2E4D
    Phase.THINKING: (255, 210, 63, 255),  # #FFD23F
    Phase.SPEAKING: (52, 228, 240, 255),  # #34E4F0
}
PAUSED = (154, 163, 178, 255)  # #9AA3B2

LABELS = {
    Phase.IDLE: "pronta",
    Phase.LISTENING: "ouvindo",
    Phase.THINKING: "pensando",
    Phase.SPEAKING: "falando",
}


def icon_image(phase: Phase, *, paused: bool = False, size: int = 64) -> Image.Image:
    color = PAUSED if paused and phase is Phase.IDLE else COLORS[phase]
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    margin = size // 16
    draw.ellipse(
        (margin, margin, size - margin, size - margin), fill=BACKGROUND, outline=EDGE, width=2
    )
    ring = size // 8
    width = max(3, size // 11)
    draw.ellipse((ring, ring, size - ring, size - ring), outline=color, width=width)
    visor_h = max(4, size // 9)
    top = size // 2 - visor_h // 2
    draw.rounded_rectangle(
        (size * 5 // 16, top, size * 11 // 16, top + visor_h), radius=visor_h // 2, fill=color
    )
    return image


def tooltip(name: str, phase: Phase, *, paused: bool = False) -> str:
    state = "escuta pausada" if paused and phase is Phase.IDLE else LABELS[phase]
    return f"{name}: {state}"
