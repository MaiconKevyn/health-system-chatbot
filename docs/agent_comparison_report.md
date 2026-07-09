# Report: Comparacao entre Pydantic AI e LangGraph/simple

Data da avaliacao: 2026-07-09

## Objetivo

Comparar o agente atual do `health-system-chatbot`, baseado em Pydantic AI, com o
agente localizado em `/Users/maiconkevyn/PycharmProjects/agent-txt2sql-langgraph`,
usando o mesmo banco DuckDB e os mesmos datasets de ground truth.

O foco da avaliacao foi medir se cada agente entende a pergunta, gera SQL
executavel e retorna o mesmo resultado do SQL gold.

## Escopo avaliado

O repo `agent-txt2sql-langgraph` possui codigo/documentacao de um
`LangGraphOrchestrator`, mas esse caminho nao esta executavel no estado atual:
o import falha porque `orchestrator.py` espera funcoes ausentes em
`orchestrator_support.py`.

Por isso, a comparacao usou o runtime funcional daquele repo:
`SimpleSQLAgent`, que o proprio codigo descreve como o novo caminho de runtime.
Esse fluxo e:

```text
pergunta -> contexto do banco no prompt -> SQL -> execucao -> resposta
```

O agente Pydantic AI avaliado foi o runtime atual deste projeto, com:

- recuperacao de contexto de schema;
- catalogos clinicos e value hints;
- SQL estruturado via Pydantic AI;
- validacao deterministica;
- self-correction quando aplicavel;
- execucao read-only em DuckDB;
- sintese final em linguagem natural.

## Metodologia

Para cada item:

1. carregar pergunta e SQL gold do dataset;
2. executar o SQL gold no mesmo DuckDB local;
3. chamar o agente Pydantic AI e capturar a SQL gerada;
4. chamar o agente LangGraph/simple e capturar a SQL gerada;
5. executar cada SQL gerada no mesmo DuckDB;
6. comparar o resultado produzido contra o resultado gold.

Metricas usadas:

- `agent_success_rate`: o agente conseguiu retornar uma resposta/SQL;
- `sql_execution_rate`: a SQL gerada executou sem erro;
- `content_match_rate`: os valores retornados batem com o gold, tolerando
  diferencas de alias/nomes de coluna quando o conteudo e equivalente;
- `strict_match_rate`: colunas e valores batem exatamente;
- `scalar_answer_match_rate`: em respostas escalares, a resposta textual contem
  o valor correto.

## Datasets

Foram rodadas 288 perguntas por agente:

| Dataset | Itens | Descricao |
| --- | ---: | --- |
| `cid_disease_tooling_eval.jsonl` | 15 | Perguntas focadas em doencas, CID e diagnosticos |
| `dense_current_db_all.jsonl` | 45 | Perguntas densas sobre o schema atual, tabelas e joins |
| `ground_truth_228_validated.jsonl` | 228 | Ground truth validado principal do projeto |

Todos os SQLs gold executaram com sucesso no DuckDB atual.

## Resultado geral

Resultado consolidado dos 288 itens:

| Agente | Match de resultado | SQL executou | Agent success | Strict match | Tempo medio |
| --- | ---: | ---: | ---: | ---: | ---: |
| Pydantic AI | 89,2% | 98,6% | 98,6% | 69,4% | 6,03s |
| LangGraph/simple | 49,7% | 95,1% | 96,2% | 8,7% | 4,63s |

Conclusao direta: o Pydantic AI foi substancialmente melhor em corretude de
resultado. O LangGraph/simple foi mais rapido, mas errou muito mais perguntas
medium/hard e queries que exigem grounding de CID, joins ou formato de resposta.

## Resultado por suite

### CID/doencas

| Agente | Match de resultado | SQL executou | Agent success | Strict match |
| --- | ---: | ---: | ---: | ---: |
| Pydantic AI | 93,3% | 100,0% | 100,0% | 26,7% |
| LangGraph/simple | 26,7% | 100,0% | 100,0% | 0,0% |

Principal diferenca: o Pydantic AI usa catalogos clinicos para resolver
conceitos como pneumonia `J12-J18`; o LangGraph/simple frequentemente usa apenas
um prefixo parcial, como `J18%`.

Exemplo:

- Pergunta: "Quantas internacoes por pneumonia foram registradas?"
- Gold: `J12-J18`, resultado `8.200.676`
- Pydantic AI: `J12-J18`, correto
- LangGraph/simple: `J18%`, resultado `5.013.865`, incorreto

### Dense current DB

| Agente | Match de resultado | SQL executou | Agent success | Strict match |
| --- | ---: | ---: | ---: | ---: |
| Pydantic AI | 91,1% | 100,0% | 100,0% | 48,9% |
| LangGraph/simple | 53,3% | 97,8% | 97,8% | 4,4% |

Principal diferenca: o Pydantic AI conhece melhor o schema atual e usa melhor as
dimensoes. O LangGraph/simple ainda erra em perguntas que exigem tabelas de
staging, dimensoes descritivas, shape controlado e joins.

Exemplo:

- Pergunta: "Quantos registros existem na tabela de staging de internacoes?"
- Gold: `_staging_internacoes`, resultado `39.622.048`
- LangGraph/simple: contou `internacoes`, resultado `144.386.772`

### GT228 completo

| Agente | Match de resultado | SQL executou | Agent success | Strict match |
| --- | ---: | ---: | ---: | ---: |
| Pydantic AI | 88,6% | 98,2% | 98,2% | 76,3% |
| LangGraph/simple | 50,4% | 94,3% | 95,6% | 10,1% |

Por dificuldade:

| Agente | Easy | Medium | Hard |
| --- | ---: | ---: | ---: |
| Pydantic AI | 97,3% | 88,2% | 80,5% |
| LangGraph/simple | 97,3% | 43,4% | 11,7% |

Conclusao: os dois agentes vao bem em perguntas faceis. A diferenca aparece nas
perguntas medium/hard, onde o Pydantic AI mantem desempenho alto e o
LangGraph/simple degrada bastante.

## Padroes de falha

### Pydantic AI

Falhas consolidadas em 288 itens:

| Categoria | Quantidade |
| --- | ---: |
| Alias/shape/conteudo parcial | 13 |
| Row count mismatch | 8 |
| Content mismatch | 6 |
| SQL vazia | 4 |

Exemplos:

- `CID007`: pergunta sobre municipios do RS com mais internacoes por diabetes
  incluiu bucket "Nao mapeado" por uso de `LEFT JOIN` com filtro de UF no `ON`.
- `DENSE_JOIN_013`: "contraceptivo 1 informado" foi interpretado como filtro
  `CONTRACEP1 = 1`, quando o esperado era distribuir a coluna `CONTRACEP1`.
- `GT014`: meningite retornou escopo CID mais amplo que o gold.
- `GT019`: internacoes obstetricas foram interpretadas via CID obstetrico, mas
  o gold usa regra de dominio por especialidade.

### LangGraph/simple

Falhas consolidadas em 288 itens:

| Categoria | Quantidade |
| --- | ---: |
| Alias/shape/conteudo parcial | 86 |
| Row count mismatch | 41 |
| SQL execution error | 11 |
| Content mismatch | 4 |
| SQL vazia | 3 |

Exemplos:

- uso de CID incompleto para pneumonia, asma, dengue, tuberculose e HIV/AIDS;
- uso de tabela inexistente `internacao_procedimento`;
- contagem em `internacoes` quando a pergunta pedia `_staging_internacoes`;
- adicao de colunas extras, percentuais ou ordenacao diferente do gold;
- erros fortes em perguntas hard: apenas 11,7% de match no GT228 hard.

## Interpretacao arquitetural

O resultado sugere que a diferenca principal nao e apenas "Pydantic AI versus
LangGraph" como framework. A diferenca esta no desenho do fluxo.

O agente Pydantic AI tem mais camadas de grounding, validacao e correcao:

- contexto de schema atual;
- catalogos clinicos;
- exemplos e hints;
- validacao deterministica;
- self-correction;
- separacao entre SQL, execucao e resposta final.

O LangGraph/simple avaliado e mais curto e mais rapido, mas depende muito mais
do prompt e da memoria do modelo. Isso funciona em perguntas faceis, mas falha
quando a pergunta exige:

- resolver codigos CID corretamente;
- escolher tabela atual versus tabela antiga;
- controlar formato exato de linhas/colunas;
- aplicar regra de dominio especifica;
- compor joins com dimensoes reais.

## Recomendacao

Manter Pydantic AI como framework central do fluxo atual.

Proximas melhorias recomendadas:

1. reforcar regras de shape para evitar colunas extras quando o gold/usuario pede
   uma saida especifica;
2. melhorar interpretacao de frases ambiguitas como "contraceptivo 1 informado";
3. expandir catalogo clinico para conceitos como meningite e obstetricia;
4. transformar erros recorrentes do report em casos de regressao automatizados;
5. manter LangGraph apenas como referencia comparativa ou para experimentos, nao
   como runtime principal neste momento.

## Artefatos gerados

Resumo consolidado versionado:

- `evaluation/chatbot/results/agent_comparison_consolidated_summary.json`

Resultados locais detalhados:

- `evaluation/chatbot/results/agent_comparison_cid_full/results.json`
- `evaluation/chatbot/results/agent_comparison_dense_current_db_all/results.json`
- `evaluation/chatbot/results/agent_comparison_gt228_full/results.json`
- `evaluation/chatbot/results/agent_comparison_gt228_stratified30/results.json`

Os resultados detalhados sao uteis para auditoria local. O resumo consolidado e
o presente report sao suficientes para documentar a decisao arquitetural no
repositorio.
