# Comparação dos chats sobre o SIHRD9

O adaptador `health` deste benchmark chama explicitamente `health_system_chatbot.workflow.run_chat`, o motor histórico. A API e a CLI de produto passaram a usar `health_system_chatbot.chat.run_chat`, cujo padrão OpenAI é o motor SUS integrado. Os resultados abaixo descrevem as versões avaliadas.

O benchmark posterior ampliou a avaliação para 32 perguntas curadas e 128 respostas, com revisão semântica do texto final. [Comparação com o novo gabarito](curadoria_v1/README.md)

O `agent-text-to-sql-sus` entregou todos os números e gráficos pedidos nas 24 execuções. O `health-system-chatbot` acertou 22. Na pergunta original sobre partos feitos no Rio Grande do Sul, avaliada à parte, ambos identificaram o diagnóstico e entregaram a série correta de 18 anos.

## Resultado do piloto

| Medida | health-system-chatbot | agent-text-to-sql-sus |
|---|---:|---:|
| Resposta ao usuário com todos os fatos e o gráfico quando solicitado | 22/24 | 24/24 |
| Tabela SQL com as linhas, colunas e valores do gabarito | 18/24 | 24/24 |
| Gráfico de linhas com os pontos corretos e na ordem pedida | 4/4 | 4/4 |
| Requisições ao Luna 6 | 80 | 48 |
| Tempo mediano por pergunta | 6,96 s | 4,20 s |

As 24 comparações pareadas deram 22 empates e duas vitórias do SUS na resposta entregue. São 12 perguntas distintas, cada uma repetida duas vezes. Esta é uma medição descritiva desses casos e dessas versões locais.

### Onde os agentes divergiram

| Pergunta | O que ocorreu no health-system-chatbot |
|---|---|
| Q05 · Internações de residentes de Pelotas no primeiro trimestre de 2019 | Na primeira execução, respondeu **4.434** e incluiu o trimestre como coluna adicional. Na segunda, o validador exigiu projetar o trimestre, embora o usuário o tivesse especificado como filtro, e o chat recusou a resposta. |
| Q07 · Internações por J18.9 em 2017 com mais de dez dias de permanência | Na primeira, respondeu **38.657** e incluiu o CID como coluna adicional. Na segunda, filtrou pelo literal `J18.9`. O SIHRD9 armazena `J189`. O chat informou zero. |
| Q12 · Óbitos anuais de residentes da Bahia | Nas duas execuções, o texto e o gráfico reproduziram os três totais corretos. A tabela SQL incluiu também o número de internações por ano. |

Esses casos explicam as seis divergências de tabela e as duas falhas na resposta final. O SUS acertou os três casos em ambas as rodadas. O tempo inclui geração, ferramentas do agente, consulta local e redação. O número de chamadas é observável nos registros. O custo em dinheiro depende também dos tokens e ficou fora da medição.

## A pergunta original sobre partos

> Demonstre em um gráfico a quantidade de partos espontâneo cefálico anuais feitos no rio grande do sul

Neste teste adicional, os agentes receberam a frase acima sem código CID ou datas. Para o gabarito, “feitos no Rio Grande do Sul” designa o **local de atendimento**. A referência usa o diagnóstico principal `O800`, liga a internação ao hospital pelo CNES e ao município por `hospital.MUNIC_MOV`, e agrupa por ano de entrada. O ano de entrada foi uma escolha de avaliação, pois a pergunta deixa o critério temporal em aberto.

Os dois agentes escolheram essa mesma interpretação e devolveram os 18 pontos corretos. Foram **507.607 internações entre 2008 e 2025**, com pico de **30.639 em 2018** e **24.611 em 2025**. O SUS acrescentou a descrição do diagnóstico na tabela e levantou a possibilidade de 2025 estar incompleto. A consulta de contagem não mediu completude. No outro teste sobre partos, Q11, o pedido especifica **residência** no RS e restringe os anos. Por isso os totais são diferentes.

[Gráfico anual](parto_rs_luna_01/partos_rs.svg) · [SQL de referência](regressao_partos.json) · [Respostas, SQL e pontos dos dois chats](parto_rs_luna_01/results.jsonl)

## Método e reprodução

1. Executamos os SQLs de referência no mesmo arquivo físico `sihrd9.duckdb`, em modo de leitura, antes de apresentar as perguntas aos agentes. O avaliador reteve as consultas e os valores de referência. As perguntas abrangem datas, contagens, óbitos, permanência, valores, geografia, CID, rankings e séries.
2. Cada execução começou sem histórico de conversa. Em cada rodada a ordem das perguntas foi embaralhada com semente registrada. O projeto que respondeu primeiro a cada pergunta foi alternado entre as rodadas.
3. Rodamos os fluxos de chat dos dois projetos. O health usou Pydantic AI e recuperação por palavras-chave. O SUS usou o dicionário migrado para o SIHRD9, seu mecanismo de busca de valores e o SDK da OpenAI. Todas as 128 requisições de modelo do piloto usaram `gpt-6-luna` com esforço `low`, verificados antes do envio. Os prompts, reparos, ferramentas e síntese de cada projeto são parte da comparação. O tempo exclui inicialização dos clientes e carregamento inicial do contexto.
4. A métrica da tabela compara resultados executados, admite mudança na ordem das colunas, exige a ordem nos rankings e considera a precisão pedida para médias, reais e percentuais. Colunas adicionais reprovam a tabela estrita. A métrica de texto verifica os números, as unidades solicitadas e a associação entre rótulos e valores. Conferimos as respostas do piloto com o gabarito, inclusive as tabelas Markdown. Para os dois gráficos pedidos no piloto, verificamos o tipo e cada par ano–valor emitido pelo backend.
5. O piloto cobre perguntas individuais sobre dados estruturados. A construção de painéis, as conversas com múltiplos turnos e as investigações são tarefas diferentes e ficaram fora da pontuação. O caso adicional de regressão tem uma execução por agente e aparece separado das métricas.

A partir da raiz de `health-system-chatbot`, com o outro checkout na pasta irmã `text-to-sql-chatbot`, execute em uma nova pasta de saída. O ambiente Python precisa das dependências dos dois projetos.

```sh
bench=evaluation/chatbot/project_comparison
.venv/bin/python "$bench/run.py" --out "$bench/nova_rodada"
.venv/bin/python "$bench/summarize.py" "$bench/nova_rodada"
.venv/bin/python "$bench/run.py" --cases "$bench/regressao_partos.json" --reps 1 --out "$bench/nova_regressao"
```

[Perguntas e SQLs de referência](cases.json) · [Gabarito numérico](run_luna_01/gold.json) · [Respostas e SQLs gerados](run_luna_01/results.jsonl) · [Configuração e revisões](run_luna_01/manifest.json) · [Pontuação por execução](run_luna_01/summary.json)
