# Curadoria do ground truth sihrd9

- Pool: 288 casos; mantidos 281; descartados 7.
- Respondíveis: 276; irrespondíveis (avaliados só pela resposta em linguagem natural): 5.
- Com alternativa de interpretação: 115.
- Decisões manuais: 144.
- Problemas pendentes: 0.

## Decisões manuais

| id | ação | motivo |
|---|---|---|
| temp_serie_anual | rewrite | must_mention exigia citar 2007 parcial, fato do sihrd5 que não existe no sihrd9. |
| temp_ano_mais_obitos | adjust | Pergunta pede só o ano. |
| demo_mulheres_2019 | drop | Pergunta idêntica a um exemplo few-shot do dicionário do sistema B (vazamento de gabarito). |
| demo_raca_cor | rewrite | INNER JOIN com raca_cor descartava RACA_COR = 99 (22,9% da base) no sihrd9. Rótulo de 'sem informação' varia: compara as contagens; must_mention checa a categoria. |
| demo_faixa_etaria | adjust | Rótulo de faixa é CASE: compara as contagens. |
| cid_infarto_2023 | adjust | IAM aceita I21 ou I21-I22 (convenção DATASUS). |
| cid_por_capitulo | adjust | Bucket 'Sem capítulo' é escolha de apresentação: aceita INNER JOIN e capítulo completado por cid_manuais. |
| cid_letalidade_top | adjust | Pergunta pede diagnósticos e taxa; contagem é apoio. |
| proc_top5 | rewrite | PROC_REA não existe mais em internacao; procedimento migrado para internacao_procedimento. Aceita contagem por internação ou por linha. |
| proc_partos_cesarea_vs_normal | rewrite | PROC_REA migrado. Rótulo do tipo de parto é construído por CASE: compara só o total. |
| proc_custo_medio_top | rewrite | PROC_REA migrado. Custo médio por internação com o procedimento; a variante sem DISTINCT pesa linhas repetidas e também é aceita. |
| geo_por_uf | rewrite | INNER JOIN com municipios perdia 1.262.450 internações de residentes do DF (códigos 5300xx). |
| geo_top10_municipios | rewrite | DF corrigido (Brasília recebe as regiões administrativas). |
| geo_mortalidade_por_uf | rewrite | DF corrigido; gold devolve só a taxa pedida. |
| geo_custo_medio_uf_2023 | adjust | 'Por UF' aceita residência ou local do atendimento. |
| uti_mortalidade_comparada | adjust | Rótulo 'usou UTI' é CASE; contagem é apoio. |
| especialidade_permanencia | rewrite | Mesmo problema do join ESPEC x especialidade. |
| dq_sp_subrepresentado | rewrite | SP não está mais subrepresentado no sihrd9 (é a maior UF): must_mention removido. DF corrigido. |
| multi_mortalidade_faixa_sexo | adjust | Rótulo de faixa é CASE; contagem é apoio. |
| multi_top_diag_por_uf | rewrite | DF corrigido; diagnóstico agrupado pelo código. |
| trap_municipios_validos | rewrite | Códigos 5300xx são regiões administrativas do DF, não municípios. Aceita contar municípios reais (DF uma vez), só os que casam com municipios, ou os códigos crus. |
| unans_nome_hospital | answerable | hospital tem dados no sihrd9. |
| unans_populacao | answerable | socioeconomico tem população; ano fixado no enunciado (sem ano o denominador é indefinido). Residência, DF corrigido. |
| unans_leitos | answerable | socioeconomico tem leitos SUS; ano e top-N fixados (5.570 municípios x 14 anos não cabem numa resposta). |
| unans_municipio_hospital | answerable | hospital.MUNIC_MOV dá o local do atendimento. 'Rio de Janeiro' aceita município ou estado. |
| gt_gt003 | adjust | 'Cadastrados' aceita incluir procedimentos_manuais. |
| gt_gt004 | adjust | 'Disponíveis' aceita incluir cid_manuais. |
| gt_gt005 | answerable | hospital tem 7.071 estabelecimentos no sihrd9. |
| gt_gt006 | answerable | socioeconomico tem dados no sihrd9. |
| gt_gt010 | adjust | 'Obstétrico' aceita leito obstétrico (ESPEC 2) ou capítulo O da CID. |
| gt_gt014 | adjust | Meningite por texto da descrição ou por faixa de códigos (G00-G03, A87, A39.0, A17.0). |
| gt_gt018 | answerable | socioeconomico tem população; ano fixado no enunciado (a população muda por ano). |
| gt_gt019 | rewrite | DF corrigido. |
| gt_gt024 | answerable | Lista de milhares de hospitais reescrita como contagem. |
| gt_gt027 | adjust | 'Obstétrico' aceita ESPEC 2 ou capítulo O. |
| gt_gt028 | rewrite | DF corrigido; gold devolve só a taxa pedida. |
| gt_gt029 | adjust | Base de UTI aceita VAL_UTI > 0 ou MARCA_UTI > 0. |
| gt_gt035 | adjust | Pergunta pede só o diagnóstico. |
| gt_gt038 | adjust | Pergunta pede o município (São Paulo por residência e por hospital). |
| gt_gt039 | rewrite | Mesmo problema de placeholder do gt_gt048. |
| gt_gt040 | answerable | socioeconomico tem óbitos infantis e nascidos vivos; ano e definição fixados no enunciado. |
| gt_gt043 | rewrite | `DIAG_SECUN <> '0'` casava a base inteira. Diagnóstico secundário vive em DIAG_SECUN até 2014 e em DIAGSEC1..9 depois; aceita só DIAG_SECUN ou as duas fontes. |
| gt_gt044 | rewrite | Faixas etárias não definidas na pergunta (explicitadas); rótulo CASE fora da comparação; base de UTI aceita VAL_UTI > 0 ou MARCA_UTI > 0. |
| gt_gt048 | rewrite | Gold antigo (`CID_MORTE <> '0'`) colocava o placeholder '0000' como causa nº 1. Aceita CID_MORTE real (só 2008-2014) ou DIAG_PRINC dos óbitos. |
| gt_gt049 | adjust | 'No estado do RS' aceita residência ou local do atendimento. |
| gt_gt051 | rewrite | DF corrigido. |
| gt_gt065 | adjust | Linhas de códigos fora da dimensão são escolha de apresentação: aceita INNER JOIN. |
| gt_gt067 | rewrite | Join ESPEC x especialidade troca os rótulos no sihrd9 (2 viraria CARDIOLOGIA). Agrupa pelo código ESPEC; rótulo conferido na resposta NL. |
| gt_gt068 | rewrite | PROC_REA migrado para internacao_procedimento. |
| gt_gt071 | adjust | Pergunta pede só a raça (Branca supera também o código 99). |
| gt_gt072 | adjust | 'Para o estado' aceita residência ou local do atendimento. |
| gt_gt075 | adjust | 'Em cada estado' aceita residência ou local do atendimento. |
| gt_gt076 | answerable | 'Municípios que atendem' = município do hospital. DF corrigido. |
| gt_gt077 | drop | Média por município devolve mais de 5 mil linhas: inviável como resposta em linguagem natural. |
| gt_gt078 | rewrite | Gold agrupava pela descrição do CID e fundia O034/O044/O054/O064, mudando o top 10 de 18-64. Agrupa pelo código; faixa é rótulo CASE. |
| gt_gt079 | rewrite | PROC_REA migrado. 'Nas cidades do RS' admite residência ou local do atendimento. |
| gt_gt080 | adjust | 'No estado do RS' aceita residência ou local do atendimento. |
| gt_gt081 | rewrite | PROC_REA migrado. |
| gt_gt082 | adjust | Top 3 igual por residência ou hospital; contagem é apoio. |
| gt_gt083 | adjust | Taxas iguais por residência ou hospital; contagem é apoio. |
| gt_gt084 | rewrite | Gold antigo devolvia o top 3 geral, mas a pergunta pede o top 3 DE CADA faixa etária. PROC_REA migrado. Rótulo de faixa é CASE: compara procedimento e total. |
| gt_gt085 | rewrite | Mesmo problema do join ESPEC x especialidade. Gold devolve só a taxa pedida. |
| gt_gt086 | answerable | hospital tem UF. 'Custo médio de UTI' aceita base VAL_UTI > 0 ou MARCA_UTI > 0. |
| gt_gt087 | adjust | 'Por estado' aceita residência ou local do atendimento. |
| gt_gt088 | adjust | Município de residência ou do hospital dão top 5 diferentes: aceita os dois; UF é apoio. |
| gt_gt089 | answerable | hospital tem dados. 'Obstétrica' = ESPEC 2 (convenção dos demais golds); capítulo O da CID aceito como alternativa. |
| gt_gt090 | rewrite | Gold agrupava pela descrição e fundia 6 códigos F7x1 (F721 sumia do top 10, B220 entrava). Agrupa pelo código. |
| gt_gt091 | drop | 'Custo por dia' sem definição (SUM/SUM x média de razões; DIAS_PERM = 0) — ambíguo demais para um gold único. |
| gt_gt092 | rewrite | Mesmo problema do join ESPEC x especialidade; agrupa diagnóstico pelo código. |
| gt_gt093 | adjust | Pergunta pede o ano (2021 nos dois estados, por residência ou hospital). |
| gt_gt099 | adjust | 'Total gasto em internações de UTI' aceita SUM(VAL_UTI) ou o custo total das internações com UTI. |
| gt_gt106 | rewrite | Mesmo problema do join ESPEC x especialidade. |
| gt_gt107 | adjust | 'Psiquiátricas' aceita leito psiquiátrico (5), leitos de saúde mental (5, 14, 87) ou capítulo F. |
| gt_gt112 | adjust | 'No estado do RS' aceita residência ou local do atendimento. |
| gt_gt113 | adjust | 'Municípios do RS' aceita residência ou local do atendimento. |
| gt_gt114 | adjust | 'Obstétricas' aceita ESPEC 2 ou capítulo O. |
| gt_gt115 | rewrite | Mesmo problema do join ESPEC x especialidade. |
| gt_gt119 | rewrite | Mesmo problema do join ESPEC x especialidade. |
| gt_gt120 | adjust | Residência ou hospital; 'percentual' aceita a fatia anual de cada trimestre ou a fatia respiratória dentro do trimestre. |
| gt_gt121 | drop | Ambíguo em duas dimensões: top-20 conjunto ou por estado, e município de residência ou do hospital. |
| gt_gt122 | rewrite | PROC_REA migrado. Base de contagem (internação x linha) aceita nas duas formas. |
| gt_gt124 | adjust | 'No estado do RS' aceita residência ou local do atendimento. |
| gt_gt128 | adjust | Taxa de UTI do município aceita residência ou local do atendimento. |
| gt_gt129 | rewrite | Lista com milhares de códigos; reescrita para contagem. |
| gt_gt130 | adjust | Município de residência ou do hospital; 'obstétrica' aceita ESPEC 2 ou capítulo O. |
| gt_gt131 | rewrite | PROC_REA migrado; RACA_COR é numérico no sihrd9 (5 = indígena). |
| gt_gt132 | answerable | hospital tem UF. |
| gt_gt134 | rewrite | Mesmo problema do join ESPEC x especialidade. |
| gt_gt140 | adjust | COVID aceita B342 só (código documentado) ou B342+B972. |
| gt_gt144 | adjust | IAM aceita I21 ou I21-I22. |
| gt_gt152 | adjust | 'Valor informado' aceita VAL_TOT não nulo ou VAL_TOT > 0. |
| gt_gt153 | rewrite | `CID_MORTE <> '0'` casava as 211,8 milhões de linhas no sihrd9. |
| gt_gt161 | answerable | hospital tem UF (via MUNIC_MOV). |
| gt_gt163 | answerable | socioeconomico tem dados. |
| gt_gt164 | answerable | socioeconomico tem dados. |
| gt_gt165 | answerable | socioeconomico tem dados. |
| gt_gt166 | rewrite | Pergunta antiga não batia com o gold (que contava códigos sem correspondência). Reescrita para o que o gold mede, agora em internacao_procedimento. |
| gt_gt170 | adjust | INNER JOIN com complexidade perde 12 linhas com COMPLEX = 0; aceita incluí-las. Rótulo do bucket varia. |
| gt_gt171 | adjust | Mesmo caso do gt_gt170; pergunta pede a taxa. |
| gt_gt172 | rewrite | Gold antigo (LEFT JOIN) podia trazer um grupo NULL das regiões administrativas do DF; DF corrigido. |
| gt_gt174 | rewrite | Códigos só em cid_manuais caíam num capítulo NULL; gold completa o capítulo por cid_manuais e aceita a versão antiga e o INNER JOIN. |
| gt_gt179 | rewrite | Gold devolve só a taxa pedida. |
| gt_gt182 | adjust | COVID aceita B342 só ou B342+B972. |
| gt_gt185 | answerable | hospital tem dados. UTI = MARCA_UTI > 0 (indicador); VAL_UTI > 0 aceito. |
| gt_gt186 | answerable | hospital tem dados. |
| gt_gt189 | answerable | socioeconomico tem médicos e população. 'Média por UF' aceita razão de somas ou média simples das taxas municipais. |
| gt_gt190 | answerable | socioeconomico tem mortalidade infantil; top-N e volume mínimo fixados (sem eles o topo é de municípios com 1 nascimento). |
| gt_gt191 | adjust | Rótulo 'Reservado' agrupa códigos que não são nacionalidade; aceita excluí-los. |
| gt_gt192 | adjust | INNER JOIN com vincprev descarta o 0 (99,99%); aceita incluir 'não informado'. |
| gt_gt196 | rewrite | Cesárea é procedimento: o diagnóstico O82 capta só 35-45% das cesáreas. Gold passa a usar internacao_procedimento. |
| gt_gt197 | rewrite | Faixas etárias não ditas na pergunta (explicitadas); 'obstétrica' aceita capítulo O ou leito obstétrico. Rótulo de faixa é CASE. |
| gt_gt199 | rewrite | PROC_REA migrado. |
| gt_gt201 | adjust | COVID aceita B342 só ou B342+B972. |
| gt_gt202 | rewrite | Faixas não ditas (explicitadas); COVID aceita B342 só ou B342+B972. Rótulo de faixa é CASE. |
| gt_gt204 | adjust | MA/RS aceita residência ou local do atendimento. |
| gt_gt205 | adjust | Municípios do RS aceita residência ou local do atendimento. |
| gt_gt206 | adjust | 'Razão entre uso de UTI' aceita razão de taxas ou razão de contagens. |
| gt_gt207 | adjust | Pergunta pede diagnóstico e custo; contagem é apoio. |
| gt_gt208 | rewrite | Gold agrupava pela descrição e fundia códigos F70x-F79x; 'crianças' explicitado como menores de 18. |
| gt_gt209 | drop | Saída indefinida ('qual hospital ... por especialidade': um por especialidade? o par de maior taxa?). |
| gt_gt210 | rewrite | PROC_REA migrado. Exclui diagnósticos sem capítulo (códigos só em cid_manuais); variantes com LEFT JOIN e contagem por linha aceitas. |
| gt_gt211 | adjust | Capítulo NULL para códigos de cid_manuais; aceita completar por cid_manuais. |
| gt_gt212 | adjust | MA/RS aceita residência ou local do atendimento. |
| gt_gt213 | rewrite | Faixas não ditas (explicitadas). Rótulos de faixa e caráter são CASE. |
| gt_gt214 | answerable | hospital tem dados; lista longa reescrita como contagem. |
| gt_gt215 | rewrite | Lista com mais de 300 municípios; reescrita para contagem. Agrupa pelo código (DF mapeado para Brasília). |
| gt_gt216 | adjust | RS aceita residência ou local do atendimento. |
| gt_gt217 | adjust | Capítulo completado por cid_manuais muda o capítulo II; aceita as duas. |
| gt_gt218 | rewrite | Gold aplicava um mínimo de 1000 internações que a pergunta não dizia; mínimo explicitado no enunciado. |
| gt_gt219 | rewrite | Gold aplicava um mínimo de 1000 internações por período que a pergunta não dizia; mínimo explicitado. |
| gt_gt221 | answerable | hospital tem UF. UTI = MARCA_UTI > 0. |
| gt_gt222 | answerable | socioeconomico tem população; top-N e porte mínimo fixados. Residência, DF corrigido. |
| gt_gt223 | drop | Quintil de PIB per capita indefinido (de municípios ou ponderado por população). |
| gt_gt224 | drop | Quintil de leitos SUS por mil habitantes indefinido. |
| gt_gt225 | rewrite | Faixas não ditas (explicitadas); COVID aceita B342 só. Rótulo de faixa é CASE. |
| gt_gt226 | rewrite | PROC_REA migrado. |
| gt_gt227 | rewrite | Pergunta não definia as faixas etárias que o gold usava; faixas explicitadas no enunciado. PROC_REA migrado. |
| gt_gt228 | answerable | hospital dá a UF do atendimento. DF corrigido nos dois lados. |
| gt_gt229 | answerable | hospital dá a UF do atendimento; top-N fixado. DF corrigido. |
| gt_gt230 | rewrite | Mesmo problema do join ESPEC x especialidade. |
| gt_gt231 | rewrite | Mesmo problema de placeholder; aceita DIAG_SECUN só ou DIAG_SECUN + DIAGSEC1. |
| gt_gt234 | adjust | Capítulo completado por cid_manuais; aceita as duas. |
| M13 | rewrite | Gold devolvia só a contagem, mas a pergunta pede o dia da semana. Nome do dia varia entre sistemas: compara a contagem do dia vencedor; o nome é conferido na resposta NL. |
| M16 | adjust | IAM aceita I21-I22 ou só I21. |
