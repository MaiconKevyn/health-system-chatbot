# Benchmark text-to-SQL sobre o SIHRD9

Compara, com as mesmas perguntas, o mesmo banco e o mesmo modelo, três sistemas de
pergunta-e-resposta sobre internações do SUS:

| id | sistema | ponto de entrada |
|---|---|---|
| **A** | health-system-chatbot — motor histórico (Pydantic AI) | `health_system_chatbot.workflow.run_chat` |
| **P** | health-system-chatbot — produto atual (motor SUS integrado) | `health_system_chatbot.chat.run_chat` com `CHATBOT_CHAT_ENGINE=sus` |
| **B** | agent-text-to-sql-sus (`../text-to-sql-chatbot`) | `src.agent.TextToSQLAgent.ask` |

Duas perguntas guiam a avaliação:

1. **O SQL final está certo?** Acurácia de execução (EX): o SQL que cada sistema
   executou é reexecutado e o resultado é comparado ao do gabarito.
2. **A resposta escrita está certa?** (NL): um juiz cego compara o texto final
   entregue ao usuário com o resultado do gabarito.

A comparação das duas separa erro de SQL de erro de redação.

## Gabarito (`gt_sihrd9.jsonl`)

281 perguntas: 276 respondíveis e 5 que a base não responde de forma confiável
(ex.: gestação de risco, cujo campo é TRUE em 99,7% das linhas). O gabarito vem
de duas fontes, migradas do sihrd5 para o sihrd9 e curadas de novo:

- `text-to-sql-chatbot/eval/ground_truth.yaml`: 272 casos (57 nativos + 215 dos
  228 compartilhados, já sem duplicatas e com as perguntas desambiguadas);
- `evaluation/chatbot/model_comparison/questions_sihrd9.json`: 16 perguntas
  escritas para o sihrd9.

`build_gt.py` faz a migração e aplica as decisões de `curation.yaml`, executa
cada gold e cada alternativa no `sihrd9.duckdb` e grava o resultado esperado.
`curation_report.md` lista cada decisão com o motivo.

### Princípios da curadoria

1. **O gold é a resposta correta segundo os dados do sihrd9.** Golds que rodavam,
   mas davam resposta errada, foram reescritos. Exemplos: `CID_MORTE <> '0'`
   devolvia o placeholder `'0000'` como causa de morte nº 1; o join de `ESPEC`
   com a tabela `especialidade` trocava "Obstétrico" por "CARDIOLOGIA";
   `INNER JOIN municipios` perdia 1,26 milhão de residentes do DF.
2. **Alternativas só para ambiguidade de interpretação da pergunta**: ano de
   internação × ano de alta (gerada automaticamente quando a pergunta não diz),
   residência × local do atendimento, contagem por internação × por linha de
   procedimento, definições clínicas não fixadas (ex.: IAM em I21 ou I21-I22).
   Erro de manipulação de dado não ganha alternativa.
3. **O gold devolve só o que a pergunta pede.** `compare_columns` lista as
   colunas que a predição precisa reproduzir. Rótulos construídos com `CASE`
   (faixa etária, especialidade do leito) ficam fora da comparação de execução;
   o juiz de linguagem natural confere se o texto usa o rótulo certo.
4. **DF**: `municipios` só tem 530010 (Brasília). Os códigos 5300xx de regiões
   administrativas usados no fato e em `hospital` são tratados como Brasília.
5. **Sem vazamento**: uma pergunta idêntica a um exemplo few-shot do sistema B
   foi removida. O banco de exemplos do sistema A não tem perguntas do gabarito.

Duas revisões semânticas independentes leram todas as perguntas mantidas. Os
apontamentos foram verificados executando o SQL proposto antes de entrar em
`curation.yaml`.

## Como cada métrica é calculada (`score.py`)

**EX estrito.** O SQL final é reexecutado (leitura, 180 s, até 5.000 linhas) e
comparado ao gold e a cada alternativa:

- nomes e ordem de colunas são ignorados, e colunas extras na predição são aceitas;
- cada coluna de `compare_columns` precisa corresponder a uma coluna da predição,
  e os multiconjuntos de linhas precisam ser iguais (a ordem das linhas não conta);
- inteiros precisam ser exatos; decimais são comparados na precisão do valor
  menos preciso (no mínimo 1 casa); colunas de taxa e percentual aceitam ×100;
- textos são comparados sem caixa, acentos ou pontuação.

**EX numérico.** Mesma regra, exigindo só as colunas numéricas. Isola o caso
"números certos, rótulo com outra redação".

**NL.** O juiz (`gpt-6-luna`, esforço médio, saída JSON estrita) recebe a
pergunta, os resultados aceitos, o texto da resposta e o SQL e o resultado do
próprio sistema. Ele não sabe qual sistema respondeu. Classifica o texto em
`correct`, `partially_correct` ou `incorrect` e diz se o texto é fiel ao
próprio resultado. Regras principais:

- formatação, arredondamento, % × fração e sinônimos de rótulo são aceitos;
- se o resultado esperado tem mais de 10 linhas, o texto pode resumir, porque a
  interface mostra a tabela;
- valor certo com rótulo errado conta como errado;
- se o resultado esperado é zero, dizer que não há registros conta como certo;
- nas perguntas irrespondíveis, recusar ou explicar a limitação sem apresentar
  o número enganoso conta como certo.

`report.py` gera `report.md` com:

- resultado geral, com intervalo de confiança de Wilson;
- confronto pareado entre cada par de sistemas, com teste de McNemar exato;
- matriz EX × NL;
- recortes por dificuldade e por categoria;
- tipos de falha e lista das perguntas em que os sistemas divergem.

## Condições iguais para os três sistemas

- **Modelo e esforço**: `gpt-6-luna` com esforço `low` em todas as chamadas dos
  três sistemas. O B só enviava `reasoning_effort` a modelos `gpt-5`, `o3` e
  `o4`; o snapshot estende isso a `gpt-6` e fixa o esforço por
  `BENCH_REASONING_EFFORT`.
- **Sem memória**: cada pergunta roda sem histórico. No A e no P, o log de
  auditoria aponta para um arquivo vazio, porque o A busca "contexto
  relacionado" nesse log.
- **Código congelado**: `snapshot.py` copia o código dos dois repositórios no
  início da rodada e grava `provenance/` com o commit, o patch local e o hash
  de cada snapshot.

## Reproduzir

A partir da raiz deste repositório, com `text-to-sql-chatbot` na pasta irmã e
os dois venvs instalados:

```bash
ROOT=$PWD; BENCH=$ROOT/evaluation/benchmark_ab; RUN_ID=<run_id>
RUN=$BENCH/runs/$RUN_ID; SNAP=/tmp/bench_snap_$RUN_ID
A_PY=$ROOT/.venv/bin/python; B_PY=$ROOT/../text-to-sql-chatbot/.venv/bin/python
$A_PY $BENCH/build_gt.py                      # só se curation.yaml mudou
$A_PY $BENCH/snapshot.py $RUN_ID $SNAP
(cd $SNAP/A && $A_PY $BENCH/run_a.py $BENCH/gt_sihrd9.jsonl $RUN/pred_A.jsonl --engine legacy)
(cd $SNAP/A && $A_PY $BENCH/run_a.py $BENCH/gt_sihrd9.jsonl $RUN/pred_P.jsonl --engine product)
(cd $SNAP/B && $B_PY $BENCH/run_b.py $BENCH/gt_sihrd9.jsonl $RUN/pred_B.jsonl)
$A_PY $BENCH/score.py $RUN
$A_PY $BENCH/report.py $RUN
```

Os adaptadores retomam de onde pararam se forem interrompidos. O scorer guarda
os julgamentos em cache e só chama o juiz de novo quando a resposta muda.

## Limites conhecidos

- O juiz é o mesmo modelo avaliado. Como os três sistemas usam esse modelo, um
  eventual viés de autopreferência afeta todos igualmente, mas não é eliminado.
- Ordem de linhas não é avaliada na EX. Rankings com a mesma lista em outra ordem
  contam como certos na EX, e o juiz de NL avalia a ordem que o texto apresenta.
- O dicionário do sistema B (`knowledge/sihrd9.yaml`) foi remedido no sihrd9 com
  os mesmos dados que basearam a curadoria do gabarito. Armadilhas que o
  dicionário documenta (DF, `ESPEC`, placeholders) favorecem quem as conhece.
  O recorte por categoria mostra onde isso pesa.
