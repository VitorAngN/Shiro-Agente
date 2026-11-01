# Guia · treinar a palavra de ativação "Ei, Shiro"

O motor padrão (`engine = "whisper"`) já reconhece "Ei, Shiro" sem treino. Ele confere com o Whisper cada fala que ouve, e isso gasta CPU. Um modelo openWakeWord treinado faz o mesmo com ~5% de um núcleo. Este guia explica como gerar esse modelo.

## O que você precisa

- uma conta Google, para usar o **Colab** (GPU grátis);
- ~1 a 2 horas: a maior parte é espera;
- opcional: 20 a 50 gravações suas dizendo "Ei, Shiro", para conferir o modelo.

## Passo a passo

1. Abra o notebook de treino automático do openWakeWord: `notebooks/automatic_model_training.ipynb` no repositório [dscripka/openWakeWord](https://github.com/dscripka/openWakeWord).
2. Em **Runtime → Change runtime type**, escolha **GPU**.
3. Na célula de configuração:
   - `target_phrase`: `["ei shiro", "ei xiro"]`. A grafia fonética ajuda o gerador de voz a pronunciar como em português;
   - `model_name`: `ei_shiro`;
   - `n_samples`: comece com `20000`;
   - `steps`: `50000`.
4. Rode todas as células. O notebook:
   - gera milhares de exemplos sintéticos de "ei shiro" com várias vozes;
   - baixa os dados negativos (horas de fala e ruído sem a frase);
   - treina e exporta `ei_shiro.onnx`.
5. Baixe o `ei_shiro.onnx` e salve, por exemplo, em `%LOCALAPPDATA%\SHIRO\models\openwakeword\ei_shiro.onnx`.
6. No `shiro.toml`:

   ```toml
   [voice]
   activation = "both"

   [voice.wake_word]
   engine = "openwakeword"
   model = 'C:\Users\SEU_USUARIO\AppData\Local\SHIRO\models\openwakeword\ei_shiro.onnx'
   threshold = 0.5
   ```

   O `shiro.toml` fica fora do repositório. Mesmo assim, não cole esse caminho em issues públicas.

7. Rode `uv run shiro voice -v` e fale "Ei, Shiro" de vários jeitos e distâncias.

## Ajuste fino

| Sintoma | O que mexer |
|---|---|
| Não acorda quando você chama | Baixe `threshold` (0,4 → 0,3) |
| Acorda sozinha com TV ou conversa | Suba `threshold` (0,6 → 0,7) ou treine com mais `n_samples` |
| Só acorda de perto | Grave exemplos seus de longe e use a etapa de *custom verifier* do openWakeWord |

## Licença

O código do openWakeWord é Apache-2.0. Um modelo treinado com os dados negativos do notebook herda a restrição **não comercial** desses dados. Para o SHIRO, que é pessoal, não há problema.
