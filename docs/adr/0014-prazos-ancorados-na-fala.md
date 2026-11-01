# ADR-0014 · Prazos ancorados na fala e atividades no Tier 0

- **Status:** Aceito
- **Data:** 2026-11-01

## Contexto

A primeira avaliação do agente completo com o modelo real (`evals/run_agent.py`, `qwen3:4b-instruct` na GTX 1650) acertou a ferramenta em 81% dos casos e os argumentos em 67%. Corrigido um defeito no schema das ferramentas (o campo `title` sumia junto com os metadados `title`), sobraram falhas típicas de modelo pequeno:

- **prazo cortado:** "tenho prova de cálculo amanhã às 8h" virou `due_text = "às 8h"`, que é hoje (ou amanhã por acaso);
- **prazo parafraseado:** "às oito da noite" virou "às 20h" (certo) e, em outra rodada, "às 8h" (errado);
- **nenhuma ferramenta:** "tenho prova de física dia 12 às 19h" e "anota que eu preciso comprar café" receberam "anotado!" sem chamada, barrado pela checagem de ação alegada (ADR-0011);
- **concluir × excluir:** "já dei conta daquele relatório, pode tirar da lista" virou `delete_activity`.

Criar atividade por voz é o requisito central do projeto. Depender do modelo acertar a cópia literal do prazo é frágil.

## Decisão

1. **Localizar prazos na frase.** `dates.locate()` acha, numa frase inteira, as maiores sequências de palavras que o resolvedor de prazos entende, usando o próprio `resolve()` como oráculo (sem segunda gramática).
2. **Ancorar o argumento do modelo na fala** (`dates.ground()`), dentro do serviço de atividades:
   - o modelo copiou um pedaço: vale a expressão inteira que o contém ("às 8h" → "amanhã às 8h");
   - o modelo parafraseou e a frase tem uma só expressão de tempo: valem as palavras do usuário;
   - o modelo omitiu o prazo e a frase tem exatamente um, fora do título: vale esse;
   - em qualquer outra situação, fica o que o modelo mandou.
   O pedido do turno chega às ferramentas por `ToolContext.utterance`.
3. **Tier 0 para as frases mais comuns** (`activities/rules.py`), plugado no roteador pela composição (`IntentRouter(rules=...)`, sem o núcleo depender de atividades):
   - "anota/registra/adiciona [que eu preciso] X [prazo]";
   - "tenho/vou ter <prova, trabalho, reunião, consulta…> … <prazo>";
   - "tenho que/tenho de X <prazo>";
   - "me lembra de/que X <quando>".
   O prazo precisa estar no fim e ser o único; pergunta ("?"), título genérico ("anota uma atividade") ou qualquer dúvida vai para o modelo.
4. **Concluir no Tier 0** também para "já dei conta de X", "já fiz X" e "…, pode tirar da lista".
5. **Resolvedor de prazos** passa a entender:
   - hora falada sem período e sem "h" ("às seis") como o próximo seis do relógio (6h ou 18h), como uma pessoa entenderia; "às 6h" continua literal;
   - "daqui a 40 minutos", "em 2 horas", "daqui a meia hora";
   - "de manhã", "à tarde" e "à noite" (9h, 14h e 20h);
   - "estudar 2 horas" é duração, não horário.
6. **A avaliação compara prazos pelo momento que produzem**, depois de ancorados, com relógio fixo (quarta-feira, 10h): "às 20h" e "às oito da noite" valem o mesmo; "às 8h" não.

## Alternativas consideradas

| Alternativa | Por que não |
|---|---|
| Só melhorar o prompt e as descrições | Ajudou (com o schema corrigido, 76% nos argumentos), mas o 4B continua cortando e parafraseando prazos |
| Mandar a frase inteira como `due_text` e o resolvedor procurar o prazo | Mistura título e prazo; o título também pode conter datas ("estudar pra prova de sexta") |
| Gramática própria para localizar prazos | Duas gramáticas divergem com o tempo; usar o `resolve()` como oráculo mantém uma fonte de verdade |
| Modelo maior | Não cabe com folga na GPU de 4 GB (ADR-0010) |
| Escalar para a nuvem sempre que for atividade | Atividades são `local_only` (ameaça A-03) |

## Consequências

- Os pedidos de atividade mais comuns ficam determinísticos, instantâneos e sem chance de "anotado" falso.
- O modelo ainda decide frases fora da gramática, mas o prazo efetivo vem das palavras do usuário sempre que dá para saber.
- `locate()` testa todas as janelas de até 8 palavras: cerca de 2 ms por frase, irrelevante perto do modelo.
- "às seis" de manhã cedo vira 6h; de tarde, 18h. A SHIRO sempre repete a data e a hora absolutas, então um erro de interpretação aparece na hora.
- Frases novas no Tier 0 precisam de teste de tabela em `tests/unit/test_activity_rules.py`, inclusive os casos que **não** podem casar.
