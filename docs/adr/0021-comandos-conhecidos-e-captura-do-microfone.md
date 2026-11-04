# ADR-0021 · Comandos conhecidos na voz e captura sem os efeitos do Windows

- **Status:** Aceito (os limiares ainda dependem da medição nas gravações reais)
- **Data:** 2026-11-04
- **Requisitos:** RF-01, RNF-01, RNF-03
- **Complementa:** [ADR-0004](0004-pipeline-de-voz-local.md), [ADR-0015](0015-implementacao-da-voz.md)

## Contexto

O reconhecimento falhou nos comandos mais simples, num headset sem fio:

- "abra a Steam" virou "Abra, Einstein.";
- "abra o Chrome" virou "Apra o crome.";
- "pausa a música" virou "Ausa música.";
- "que horas são" virou "E olha só.".

Em 7 gravações da voz do usuário, o melhor modelo na CPU acertou 4 comandos (Whisper medium, ~10 s por frase). O `small` acertou 1, e o `large-v3-turbo` acertou 2.

O diagnóstico das gravações mostrou que o trecho antes da fala chega com amostras exatamente zeradas e que o som salta de uma vez quando a voz começa. Há um portão de ruído (noise gate) no caminho, e ele abre atrasado: a primeira sílaba some antes de chegar ao Whisper. Subir o ganho não resolveu, e o usuário não tem supressão de ruído ligada no Windows.

A SHIRO abria o microfone pelo MME. O MME passa pelo motor de áudio do Windows e pelos efeitos instalados no aparelho (APOs). O nome do aparelho no Windows sugere um efeito de som do fabricante.

### O que os projetos abertos fazem

- **Home Assistant / Rhasspy:** para comandos, não transcrevem livremente. O [speech-to-phrase](https://github.com/OHF-Voice/speech-to-phrase) reconhece só as frases que o sistema conhece (modelo Kaldi treinado a partir dos modelos de frase e dos nomes dos aparelhos), com uma correção aproximada no fim. É rápido num Raspberry Pi e muito mais robusto que o Whisper em comandos curtos. Em 2026, ainda não tem português.
- **Vosk:** tem um modelo pequeno em português (31 MB, Apache-2.0) que aceita uma gramática em tempo de execução. Só aceita palavras do vocabulário do modelo, e esse vocabulário não tem "steam", "chrome" nem "discord". Acrescentar palavras exige recompilar o grafo com as ferramentas do Kaldi.
- **RealtimeSTT e semelhantes (faster-whisper + VAD):** guardam 1 s de áudio antes da fala detectada (pre-roll). A SHIRO já faz isso. Não adianta quando o próprio microfone entrega silêncio zerado no começo.
- **Modelos Whisper ajustados para português** (Common Voice): melhoram a transcrição livre, mas são do tamanho do `large` e lentos demais na CPU deste PC.

## Decisão

### 1. Reconhecimento restrito com o próprio Whisper

Quando a transcrição livre é curta (até 6 palavras) e o Tier 0 não a reconhece, o Whisper funciona como juiz:

1. `CommandCatalog` gera as frases que o roteador entende, escritas como o Whisper escreve ("Abra o Steam.", "Pausa a música.", "Volume em 30."). Para cada app configurado, entram os verbos de abrir e fechar. Uma frase só entra no catálogo se `IntentRouter.match_tier0` a reconhece, e a ação que ela dispara agrupa as variantes ("Abra o Steam." e "Abre a Steam." não competem).
2. `FasterWhisperSTT.score` mede quanto cada frase explica o áudio: a média do log da probabilidade por token, com o fim de frase incluído. O codificador, a parte cara, roda uma vez. A saída dele é repetida e o decodificador é forçado a seguir cada frase (`ctranslate2 … Whisper.align`), em lotes de 16. O prompt é o mesmo da transcrição (vocabulário e hotwords).
3. A transcrição livre é medida do mesmo jeito. `RescoreRule` troca o texto pelo comando só se as três condições valerem:
   - o comando fica a até `slack` (1,0) da nota da transcrição livre;
   - ganha da melhor frase de outra ação por `margin` (0,3);
   - não fica abaixo de `floor` (−2,5).
   Uma pergunta livre explica o áudio muito melhor que qualquer comando e passa sem mudança.
4. `CommandRescoringSTT` é um Decorator de `SpeechToText`. A sessão de voz, a palavra de ativação, `shiro voice listen` e o bench usam o mesmo caminho. Se a frase começa chamando a SHIRO ("Ei, Shiro, ausa música."), os comandos ganham o mesmo começo.

Liga e desliga em `[voice.stt] commands`. O custo é uma passada a mais do codificador, só nas frases curtas que não viraram comando.

### 2. Modos de captura

`[voice] capture` escolhe como pedir o som ao Windows:

| Modo | Caminho | Efeitos (APOs) |
|---|---|---|
| `mme` (padrão) | MME, o Windows converte a taxa | sim |
| `wasapi` | WASAPI compartilhado, na taxa do aparelho | sim |
| `raw` | WASAPI compartilhado com `eStreamOptionRaw` | não, se o aparelho permitir |
| `exclusive` | WASAPI exclusivo, direto do aparelho | não; nenhum outro app usa o microfone |

O sounddevice não expõe a opção "raw". O campo `streamOption` da estrutura do PortAudio é preenchido direto.

Se o modo configurado não abrir, a SHIRO volta para o MME e avisa no log.

`shiro voice mic-test` grava a mesma frase em cada modo, mede o silêncio zerado e o salto no começo, transcreve e diz qual modo não corta a fala. Se todos cortarem, o corte vem do próprio headset ou do receptor sem fio. As gravações ficam no formato do `record` e podem ser medidas com `bench --samples`.

### 3. Medição

`shiro voice bench --samples --commands both` compara com e sem a correção nas gravações do usuário. Para cada correção, mostra a nota da transcrição livre e as duas melhores frases, e é assim que os limiares serão calibrados.

## Alternativas consideradas

| Alternativa | Por que não (por enquanto) |
|---|---|
| speech-to-phrase | Sem português; roda como serviço Wyoming à parte |
| Vosk com gramática | O vocabulário do modelo pequeno em português não tem os nomes dos apps; o modelo grande (1,6 GB, GPL) não aceita gramática |
| Modelo Whisper ajustado para português | Do tamanho do `large`: ~30 s por frase na CPU deste PC |
| Whisper na GPU | Fica para um próximo passo: divide os 4 GB com o Ollama (ADR-0010) e precisa das DLLs do CUDA 12 e do cuDNN 9 |
| Só aumentar o pre-roll | O áudio antes da fala já chega zerado; não há o que guardar |
| Corrigir só por semelhança de texto | Já existe para nomes de apps (`sound_key`). Não ajuda quando o Whisper ouve outra frase inteira ("E olha só." para "que horas são") |

## Consequências

- Os comandos curtos passam a ser reconhecidos contra uma lista fechada, mesmo quando o Whisper não os transcreve direito. Pedidos fora da lista continuam com a transcrição livre.
- Frases curtas que não são comando custam uma passada a mais do codificador (≈ 1 s no `small` na CPU).
- O risco é trocar uma frase livre e curta por um comando parecido. A margem, o piso e a comparação com a própria transcrição limitam isso. Abrir e fechar apps continuam pela política (ADR-0005).
- Os limiares precisam ser calibrados nas gravações reais antes de qualquer mudança no padrão.
- Fica aberto: o celular como microfone (app Android), o Whisper na GPU e aliases ensinados pelo usuário entrando no catálogo.
