"""Um Whisper minúsculo com pesos aleatórios, montado na hora (sem baixar nada).

Serve para exercitar o caminho de verdade do CTranslate2 e do faster-whisper
(codificar, ``align``, tokenizador) nos testes. As notas não significam nada;
o que se testa é a mecânica: formatos, lotes e o prompt.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

_D, _HEADS, _FFN, _MELS = 32, 2, 64, 80
WORDS = (
    *("Abra", "o", "a", "Abre", "Feche", "Fecha", "Steam", "Chrome", "Pausa", "música"),
    *("Que", "horas", "são", "Shiro", "Volume", "em", "30", ".", ",", "?"),
    *("Ausa", "Einstein", "me", "conta", "uma", "piada"),
)
_SPECIAL = (
    "<|endoftext|>",
    "<|startoftranscript|>",
    "<|pt|>",
    "<|translate|>",
    "<|transcribe|>",
    "<|startoflm|>",
    "<|startofprev|>",
    "<|nospeech|>",
    "<|notimestamps|>",
)


def build_tiny_whisper(folder: Path) -> Path:
    """Grava em ``folder`` um modelo que ``faster_whisper.WhisperModel`` carrega."""
    import tokenizers
    from ctranslate2.specs import whisper_spec  # pyright: ignore[reportMissingTypeStubs]

    rng = np.random.default_rng(7)
    tokens = ["<unk>", *WORDS, *_SPECIAL, "<|0.00|>"]
    vocab = len(tokens)

    def rand(*shape: int) -> np.ndarray:
        return (rng.standard_normal(shape) * 0.05).astype(np.float32)

    def norm(spec: Any) -> None:
        spec.gamma = np.ones(_D, np.float32)
        spec.beta = np.zeros(_D, np.float32)

    def linear(spec: Any, out: int, inp: int) -> None:
        spec.weight = rand(out, inp)
        spec.bias = rand(out)

    def ffn(spec: Any) -> None:
        linear(spec.linear_0, _FFN, _D)
        linear(spec.linear_1, _D, _FFN)
        norm(spec.layer_norm)

    def self_attention(spec: Any) -> None:
        linear(spec.linear[0], 3 * _D, _D)
        linear(spec.linear[1], _D, _D)
        norm(spec.layer_norm)

    spec: Any = whisper_spec.WhisperSpec(1, _HEADS, 2, _HEADS)
    encoder: Any = spec.encoder
    encoder.conv1.weight, encoder.conv1.bias = rand(_D, _MELS, 3), rand(_D)
    encoder.conv2.weight, encoder.conv2.bias = rand(_D, _D, 3), rand(_D)
    encoder.position_encodings.encodings = rand(1500, _D)
    norm(encoder.layer_norm)
    for layer in encoder.layer:
        self_attention(layer.self_attention)
        ffn(layer.ffn)
    decoder: Any = spec.decoder
    decoder.embeddings.weight = rand(vocab, _D)
    decoder.position_encodings.encodings = rand(448, _D)
    norm(decoder.layer_norm)
    for layer in decoder.layer:
        self_attention(layer.self_attention)
        linear(layer.attention.linear[0], _D, _D)
        linear(layer.attention.linear[1], 2 * _D, _D)
        linear(layer.attention.linear[2], _D, _D)
        norm(layer.attention.layer_norm)
        ffn(layer.ffn)
    decoder.projection.weight = decoder.embeddings.weight
    spec.register_vocabulary(tokens)
    spec.config.suppress_ids = []
    spec.config.suppress_ids_begin = []
    spec.config.lang_ids = [tokens.index("<|pt|>")]
    spec.config.alignment_heads = [(1, 0), (1, 1)]
    spec.validate()
    spec.optimize(quantization="int8")
    folder.mkdir(parents=True, exist_ok=True)
    spec.save(str(folder))

    word_level = tokenizers.models.WordLevel(
        {token: index for index, token in enumerate(tokens)},
        unk_token="<unk>",  # noqa: S106 - token, não senha
    )
    tokenizer = tokenizers.Tokenizer(word_level)
    tokenizer.pre_tokenizer = tokenizers.pre_tokenizers.Whitespace()
    tokenizer.add_special_tokens(list(_SPECIAL))
    tokenizer.save(str(folder / "tokenizer.json"))
    return folder
