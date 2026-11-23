# Benchmark de respostas em português sobre o SIHRD9

O **agent-text-to-sql-sus** entregou **62 de 64 respostas finais corretas (96,9%)**. O **health-system-chatbot** entregou **59 de 64 (92,2%)**. São 32 perguntas distintas, duas rodadas e 128 respostas revisadas. A vantagem observada do SUS em linguagem natural foi de **4,7 pontos percentuais**. O intervalo pareado de 95% vai de **−6,3 a +14,1 pontos** e inclui zero. O SUS liderou nesta amostra. A diferença é pequena demais para afirmar superioridade geral.

[Explorar as respostas lado a lado e filtrar falhas](comparacao.html) · [Abrir a comparação em CSV](comparacao.csv) · [Métricas por execução](scorecard.csv)

| Medida | health-system-chatbot | agent-text-to-sql-sus |
|---|---:|---:|
| Resposta final integralmente correta (NL) | 59/64 · 92,2% | 62/64 · 96,9% |
| Resultado SQL equivalente ao gabarito (EX estrita) | 48/64 · 75,0% | 50/64 · 78,1% |
| SQL final executável | 62/64 · 96,9% | 62/64 · 96,9% |
| Perguntas com NL correta nas duas rodadas | 29/32 | 31/32 |
| Chamadas ao Luna 6, todas com esforço baixo | 200 | 127 |

Dos 64 pares de respostas, os dois acertaram juntos em 57. O SUS acertou sozinho em cinco, e o health em dois. Para EX, houve 46 empates, dez vitórias do SUS e oito do health. A diferença de EX foi de 3,1 pontos percentuais, com intervalo pareado de 95% de −10,9 a +17,2.

### Onde o texto mudou a conclusão

| Caso | O que a pessoa recebeu |
|---|---|
| C30 · Câncer de mama ou de próstata em 2022 | Nas duas rodadas o SUS identificou mama, com **79.047** internações, e próstata, com **35.231**. O health agrupou por descrição da subcategoria CID e reteve apenas a primeira linha. O texto declarou próstata a mais frequente e omitiu o total de mama. |
| C29 · Internações respiratórias de residentes do RS no primeiro trimestre de 2019 | O SUS respondeu **8,53%** nas duas rodadas. O health recusou ambas porque seu validador exigiu incluir o trimestre como coluna, embora o pedido fosse um único percentual para um trimestre já definido. |
| C08 · Registros municipais de população para 2022 | O health respondeu **zero registros** nas duas rodadas. O SUS reconheceu que 2022 está ausente, mas afirmou que a contagem era indeterminável. A pergunta pede o número de linhas existentes na tabela. |
| C07 · Valor médio das internações com óbito | Em uma rodada o health devolveu **R$ 4.198,9955** e obteve crédito parcial. A média subjacente estava correta. O pedido especificava reais e centavos, **R$ 4.199,00**. Aceitar casas extras elevaria o health a 60/64. |

### Como SQL e texto se relacionam

| Combinação | health-system-chatbot | agent-text-to-sql-sus |
|---|---:|---:|
| EX correta e NL correta | 47 | 50 |
| EX correta e NL parcial, incorreta ou ausente | 1 | 0 |
| EX divergente ou ausente e NL correta | 12 | 12 |
| EX divergente ou ausente e NL parcial, incorreta ou ausente | 4 | 2 |

A equivalência estrita da tabela subestima a utilidade das respostas em ambos os sistemas. Por exemplo, em C19 os dois retornaram **segunda-feira, 81.681**. A referência representou segunda-feira pelo inteiro ISO **1**, o que reprovou as tabelas nas quatro execuções. Outras diferenças incluem uma descrição adicional ao lado do código de procedimento ou hospital e as duas categorias de câncer apresentadas em colunas no lugar de linhas.

### Resultado por grupo

Cada célula tem 16 observações, correspondentes a oito perguntas repetidas duas vezes.

| Grupo | NL health | NL SUS | EX health | EX SUS |
|---|---:|---:|---:|---:|
| Medidas e cadastro | 15 | 14 | 14 | 14 |
| Clínica e geografia | 16 | 16 | 14 | 16 |
| Distribuições e rankings | 16 | 16 | 13 | 7 |
| Comparações | 12 | 16 | 7 | 13 |

A vantagem de NL do SUS veio principalmente das comparações. Nos rankings, o health teve mais tabelas estritamente equivalentes e os dois acertaram todos os textos. [Resumo numérico e intervalos](summary.json)

## Como o gabarito foi escolhido

A auditoria verificou se cada SQL histórico podia ser resolvido pelo DuckDB contra o esquema físico do SIHRD9. O conjunto “228” contém de fato 220 perguntas. Só 23 dos seus SQLs passam nessa verificação sem adaptação. O conjunto difícil de 73 é um subconjunto dele e nenhum dos 73 SQLs compila diretamente. A suíte densa teve 18 de 43 e a suíte de CID, zero de 15. Os 16 SQLs da suíte mais recente já compilam. Ainda assim, o M13 pergunta *qual dia da semana* e sua única coluna de saída é a contagem.

Selecionamos 32 temas com utilidade para o chat, por julgamento, em quatro grupos de oito. A origem foi o conjunto histórico para 25 casos, o conjunto de CID para três e a suíte SIHRD9 para quatro. Mudamos períodos e recortes, especificamos a data de entrada, adequamos as junções e limitamos cada lista a um tamanho que permitisse conferir o texto integralmente. Cada caso identifica a pergunta ancestral. Alguns são adaptações substantivas. Por exemplo, C32 usa o tema de mortalidade temporal do GT216 para pedir a diferença em pontos percentuais. Os conjuntos originais seguem disponíveis.

- **Medidas e cadastro** abrangem contagem, mediana, moeda, dias da semana, descrição de CID, população e ausência de dados.
- **Clínica e geografia** distinguem diagnóstico, procedimento, estabelecimento, residência, local de atendimento e uso de UTI.
- **Distribuições e rankings** exigem associação correta entre cada rótulo e seu valor, ordem quando pedida e múltiplas medidas por ano.
- **Comparações** exigem identificar máximos, calcular denominadores e distinguir variação relativa de diferença em pontos percentuais.

As duas rodadas recalcularam o mesmo gabarito antes das respostas. Oito verificações adicionais cobriram, entre outros itens, o fluxo Canoas → Porto Alegre, o primeiro colocado por dia da semana, o corte de 5 mil casos e o denominador de Florianópolis. Nesse último caso, 26.383 internações divididas por 500.973 habitantes resultam em 52,66 por mil. Na questão sobre 2022, a tabela socioeconômica realmente não tem registros.

Também comparamos a redação com os 13 exemplos do projeto health e os cinco exemplos do dicionário do SUS. Nenhuma pergunta coincide literalmente após normalização. Os projetos conservam suas regras, exemplos relacionados e ferramentas de produção. Em particular, o dicionário do SUS já documenta a ausência de 2022 na tabela socioeconômica.

[Casos, proveniência, rubricas e SQL](cases.json) · [Referências em português](respostas_referencia.json) · [Auditoria dos conjuntos](source_audit.json) · [Verificações adicionais no banco](reference_checks.json)

## O que cada métrica mede

**Acurácia da resposta final em português (NL)** é a fração de textos que atendem integralmente ao pedido. A revisão considerou pergunta, fatos de referência e texto efetivamente devolvido, com a identidade do projeto e o SQL ocultos na ficha. Um número correto atribuído à entidade errada reprova. Uma lista incompleta fica parcial. Uma conclusão que contradiz o gabarito fica incorreta, ainda que algum número esteja certo. A avaliação aceita paráfrases, abreviações equivalentes e números com formatações diferentes. Cada resposta tem uma decisão e uma justificativa. A revisão foi feita por um único avaliador, o assistente que fez a curadoria.

**Execution accuracy (EX)** é a fração de SQLs finais que, reexecutados, produzem a tabela do gabarito. Aceitamos mudança de posição das colunas, diferença de caixa em rótulos e arredondamento na precisão pedida. Preservamos a ordem de linhas nos rankings. Colunas adicionais e representações diferentes, como nome do dia e número ISO, podem reprovar uma tabela mesmo quando o texto acerta. Uma consulta que simplesmente executa recebe crédito somente na métrica de *SQL executável*. A ausência de SQL final pontua zero em EX. O acerto é sobre esta instância do banco. Em C12, por exemplo, ocorreram 53.313 registros para 53.313 AIHs distintas. Esse recorte não distingue um SQL que deduplica corretamente de outro que chega ao mesmo valor por coincidência.

Cada projeto recebeu as mesmas perguntas em chats novos, com duas execuções por pergunta. As duas rodadas rodaram em processos concorrentes. A ordem das perguntas foi embaralhada e o primeiro projeto em cada par alternou entre as rodadas. O SDK conferiu o modelo em cada requisição e fixou o esforço de raciocínio em `low`. O health usou Pydantic AI e busca por palavras-chave. O SUS usou seu fluxo nativo e o dicionário SIHRD9 ativo nesta execução. A unidade para o intervalo de incerteza é a pergunta, mantendo as duas repetições juntas em 20 mil reamostragens pareadas dentro dos quatro grupos. O desenho cobre perguntas de turno único sobre dados, sem pontuar dashboards, investigações ou conversas com continuidade.

[Protocolo registrado antes das respostas](protocolo.txt) · [Ficha mascarada](blind_sheet.json) · [Julgamentos de NL](nl_reviews.json) · [Resultado da reexecução SQL](executions.json)

## Como reproduzir

Na raiz de `health-system-chatbot`, o executor [run.py](../run.py) aceita a opção `--cases evaluation/chatbot/project_comparison/curadoria_v1/cases.json`. Para gerar novas saídas, use `--reps 1 --first-rep 1` e `--reps 1 --first-rep 2` com diretórios novos em `--out`. O outro checkout é localizado por `--sus-root`. A revisão de textos precisa ser refeita para respostas novas.

Para recalcular as métricas **da execução entregue**, os comandos abaixo usam os registros e as avaliações preservadas.

```sh
bench=evaluation/chatbot/project_comparison/curadoria_v1
.venv/bin/python "$bench/analyze.py" replay
.venv/bin/python "$bench/analyze.py" aggregate
```

[Configuração da primeira rodada](rodada1/manifest.json) · [Configuração da segunda rodada](rodada2/manifest.json) · [Respostas, SQL e chamadas da rodada 1](rodada1/results.jsonl) · [Rodada 2](rodada2/results.jsonl)
