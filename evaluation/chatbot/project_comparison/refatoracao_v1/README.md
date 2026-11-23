# Acurácia após a integração do motor SUS

O **SUS integrado acertou 63 de 64 respostas finais em português (98,4%)**, o SUS original acertou 62 (96,9%) e o legado acertou 60 (93,8%). Para SQL, a ordem dos dois primeiros se inverteu. O original produziu 55 tabelas equivalentes ao gabarito e o integrado produziu 53. A integração preservou a qualidade observada do texto neste conjunto. A diferença de SQL e a incerteza amostral ainda permitem uma perda nessa métrica.

[Explorar pergunta, gabarito, respostas, SQL e justificativas](comparacao.html) · [Baixar a comparação em CSV](comparacao.csv)

| Medida | SUS integrado | SUS original | Legado |
|---|---:|---:|---:|
| Resposta final integralmente correta | 63/64 (98,4%) | 62/64 (96,9%) | 60/64 (93,8%) |
| Resultado SQL equivalente ao gabarito (EX) | 53/64 (82,8%) | 55/64 (85,9%) | 44/64 (68,8%) |
| SQL final executável | 62/64 (96,9%) | 63/64 (98,4%) | 62/64 (96,9%) |
| Perguntas com texto correto nas duas rodadas | 31/32 | 30/32 | 30/32 |
| Perguntas com EX correta nas duas rodadas | 26/32 | 27/32 | 21/32 |
| Chamadas ao Luna 6 | 126 | 127 | 198 |

## Diferenças pareadas

Valores em pontos percentuais. Os intervalos descritivos de 95% vêm de 20 mil reamostragens das perguntas dentro dos quatro grupos originais, mantendo juntas as duas rodadas e os três motores. São **32 perguntas distintas**. O conjunto foi escolhido por curadoria e o protocolo não estipulou uma margem de perda admissível para um teste formal de não inferioridade.

| Comparação | Diferença em texto correto (intervalo de 95%) | Diferença em EX (intervalo de 95%) |
|---|---:|---:|
| Integrado menos original | +1,6 [0,0 a +4,7] | −3,1 [−12,5 a +6,3] |
| Integrado menos legado | +4,7 [−3,1 a +12,5] | +14,1 [0,0 a +29,7] |
| Original menos legado | +3,1 [−4,7 a +12,5] | +17,2 [0,0 a +34,4] |

## O que explica o resultado

- **Texto do integrado e do original.** Nos 64 pares, ambos acertaram 62 respostas e erraram juntos uma. A única vantagem do integrado foi C19 na segunda rodada. O original identificou corretamente a segunda-feira e as 81.681 internações, mas afirmou que a *maioria* começou nesse dia. A recontagem dos sete dias resultou em 488.503 internações. Segunda-feira representou 16,72%, a maior frequência entre os dias. Aceitar “maioria” como sinônimo de dia mais frequente elevaria o original a 63/64 e empataria o resultado de texto.
- **Ausência de dados em 2022 (C08).** O gabarito é zero registros com população informada. Na segunda rodada, integrado e original disseram que seria impossível determinar a contagem. Na primeira, o original executou a consulta e respondeu zero. O integrado disse “Não há registros para calcular essa contagem”. A rubrica previamente definida aceita uma declaração explícita de inexistência. O texto recebeu crédito e a ausência de SQL final custou um ponto de EX.
- **Seis divergências de EX entre integrado e original.** O integrado acertou sozinho duas vezes e o original quatro. Cinco diferenças decorreram de colunas extras com informação correta. Em C21, o original acrescentou a descrição dos procedimentos nas duas rodadas. Em C22, o integrado acrescentou os nomes dos hospitais nas duas. Em C32, o integrado incluiu as taxas anuais e a direção junto com a diferença correta de 1,24 ponto percentual na segunda rodada. A sexta divergência foi C08. As respostas em português nos seis pares atenderam à rubrica.
- **Erros do legado.** Em C29, o validador exigiu projetar o trimestre no SQL e impediu a resposta nas duas rodadas. O percentual solicitado era 8,53%. Em C30, a resposta da primeira rodada acertou que mama era mais frequente e deu 79.047, mas omitiu os 35.231 de próstata. Na segunda, declarou próstata mais frequente. Os dois motores SUS deram os dois totais e a conclusão correta nas duas rodadas.

## Como foi medido

Os três motores receberam as mesmas [32 perguntas, SQLs e rubricas](../curadoria_v1/cases.json) em duas rodadas novas cada, com ordem embaralhada, rotação dos motores e perguntas de turno único. Cada processo recalculou o gabarito antes da geração. Os resultados coincidiram com a referência anterior em todos os casos. Os 192 envios usaram o mesmo arquivo físico SIHRD9 e as 451 requisições registradas no SDK usaram `gpt-6-luna` com esforço `low`. O integrado entrou por `health_system_chatbot.chat.run_chat` com o motor SUS selecionado, o original por `TextToSQLAgent.ask_stream` no checkout independente e o legado pelo workflow anterior. As chamadas preservaram os prompts, ferramentas e validações de cada motor. [Versões e hashes dos arquivos locais](source_manifest.json)

A EX compara a tabela resultante do SQL final, reexecutado em leitura, com a referência. A comparação exige o número de colunas e linhas do gabarito, aceita permutar as colunas e aplica a precisão e a ordenação definidas por caso. SQL ausente vale zero. A equivalência mede o resultado nesta instância do banco. [Reexecuções](executions.json)

A revisão de linguagem natural usou a pergunta, o gabarito, a rubrica e o texto apresentado, com os identificadores dos motores, o SQL e as notas de execução ocultos na ficha. A classificação distingue correta, parcial, incorreta e sem resposta. Apenas o acerto integral recebe um ponto. Um único avaliador, o assistente, revisou 140 combinações inéditas de pergunta e texto, correspondentes a 146 respostas. Outras 46 coincidiram exatamente com texto já avaliado para a mesma pergunta e receberam a decisão anterior. Os três motores geraram respostas novas em todos os casos. [Protocolo](../curadoria_v1/protocolo.txt) · [Ficha mascarada](blind_sheet.json) · [Justificativas individuais](nl_reviews.json)

O benchmark cobre o chat de dados em português em turno único. As funcionalidades de dashboards, gráficos e continuidade de conversa têm escopo próprio.

## Reprodução e auditoria

A partir da raiz do projeto, este comando repete a geração dos três motores em novas pastas. Cada rodada faz chamadas ao provedor.

```bash
base=evaluation/chatbot/project_comparison
for rodada in 1 2; do
  .venv/bin/python "$base/run.py" --with-integrated \
    --cases "$base/curadoria_v1/cases.json" \
    --out "$base/nova_execucao/rodada$rodada" --reps 1 --first-rep "$rodada" &
done
wait
```

Para recalcular as métricas desta execução salva, rode os comandos abaixo. A revisão de textos novos requer aplicar as rubricas novamente. [Métricas por execução](scorecard.csv) · [Resumo e intervalos](summary.json)

```bash
base=evaluation/chatbot/project_comparison
.venv/bin/python "$base/refatoracao_v1/compare.py" seal
.venv/bin/python "$base/refatoracao_v1/compare.py" replay
.venv/bin/python "$base/refatoracao_v1/compare.py" aggregate
.venv/bin/python "$base/curadoria_v1/viewer.py" --three-arm "$base/refatoracao_v1"
```
