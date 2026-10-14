# Entrega: Assistente de Gestão de Pessoas

**Aluno(s): Daniel Barrozo Lima
**Até onde chegou:** ( ) Marco mínimo (Etapa 6)  ( ) Marco completo (Etapa 9)  (X) Etapas 10–11
**Opcionais e bônus feitos:** ( ) 🆕 A  ( ) 🆕 B  ( ) 🆕 C  ( ) Outro: ______

# Entrega do Projeto: Sistema Multiagente de RH

## Etapa 0: quem verifica cada regra?

| Regra | Tema | Quem verifica (função Python / agente / humano) | Por quê | Onde foi implementada (preencha na Etapa 11) |
|---|---|---|---|---|
| N1 | férias | função Python | conta: dias corridos >= 5 e <= saldo | etapa06_regras.py (violacoes_objetivas) |
| N2 | férias | função Python | conta: dias + vendidos <= saldo, vendidos <= 10 | etapa06_regras.py (violacoes_objetivas) |
| N3 | férias | função Python | consulta de calendário (feriados e fim de semana) | etapa06_regras.py (resumo_periodo) |
| N4 | prazos | função Python | diferença entre datas (dias corridos ou úteis) | etapa06_regras.py (violacoes_objetivas) |
| N5 | escala | função Python | contagem de afastados da equipe no período x limite de 30% | etapa06_regras.py (violacoes_objetivas) |
| N6 | abono | função Python | dia útil e saldo de abonos | etapa06_regras.py (violacoes_objetivas) |
| N7 | diária | função Python | conta (diárias + meia diária, câmbio); o agente Financeiro só explica | etapa06_regras.py e etapa06_agentes.py |
| N8 | aprovação | humano | é decisão da chefia; o server só confere se o aprovador é a chefia certa | etapa07_grafo.py (aprovacao_chefia) e etapa05_mcp_rh.py |
| N9 | saúde | função Python (guardrail) | regex de CID/CPF barra antes de qualquer agente ver o texto; o classificador (agente) cobre o que a regex não pega | etapa03_guardrails.py (encontrar_dado_sensivel) |
| N10 | dados | função Python (guardrail de saída) | regex no despacho antes de gravar | etapa07_grafo.py (registrar) |

## Etapa 11: os 12 casos

Compare **caminho e estado**, não o texto do despacho.

| Caso | Caminho percorrido | Resultado (bloqueado / pediu dados / triagem humana / indeferido / pausou na chefia / registrado + protocolo) | Bateu com o esperado? |
|---|---|---|---|
| C1_abono_simples | receber -> proteger_entrada -> extrair -> identificar_servidor -> calcular_periodo -> escala, financeiro, normas -> consolidar -> redigir_despacho -> validar -> registrar | registrado + protocolo ae788d33 | sim |
| C2_ferias_com_venda | receber -> proteger_entrada -> extrair -> identificar_servidor -> calcular_periodo -> escala, financeiro, normas -> consolidar -> redigir_despacho -> validar -> aprovacao_chefia -> registrar | registrado + protocolo b7b6f485 | sim |
| C3_dado_de_saude | receber -> proteger_entrada -> recusar | bloqueado | sim |
| C4_fora_do_escopo | receber -> proteger_entrada -> recusar | bloqueado | sim |
| C5_sem_matricula | receber -> proteger_entrada -> extrair -> pedir_dados | pediu dados | sim |
| C6_conflito_de_escala | receber -> proteger_entrada -> extrair -> identificar_servidor -> calcular_periodo -> normas, escala, financeiro -> consolidar -> redigir_despacho -> validar -> registrar | indeferido | sim |
| C7_autoaprovacao | receber -> proteger_entrada -> extrair -> identificar_servidor -> calcular_periodo -> escala, financeiro, normas -> consolidar -> redigir_despacho -> validar -> aprovacao_chefia -> registrar | indeferido | sim |
| C8_idempotencia | receber -> proteger_entrada -> extrair -> identificar_servidor -> calcular_periodo -> escala, financeiro, normas -> consolidar -> redigir_despacho -> validar -> registrar | registrado + protocolo ae788d33 | sim |
| C9_divergencia | receber -> proteger_entrada -> extrair -> pedir_dados | pediu dados | sim |
| C10_zona_cinzenta | receber -> proteger_entrada -> extrair -> identificar_servidor -> calcular_periodo -> normas, escala, financeiro -> consolidar -> redigir_despacho -> validar -> registrar | registrado + protocolo e4d12c89 | sim |
| C11_diaria_exterior | receber -> proteger_entrada -> extrair -> identificar_servidor -> calcular_periodo -> escala, financeiro, normas -> consolidar -> redigir_despacho -> validar -> aprovacao_chefia -> registrar | registrado + protocolo d8c34100 | sim |
| C12_inicio_proibido | receber -> proteger_entrada -> extrair -> identificar_servidor -> calcular_periodo -> normas, escala, financeiro -> consolidar -> redigir_despacho -> validar -> registrar | indeferido | sim |

## O grafo

```mermaid
%%{init: {'flowchart': {'curve': 'linear'}}}%%
graph TD
    __start__["__start__"] --> receber["receber"]
    receber --> proteger_entrada["proteger_entrada"]
    proteger_entrada -.-> recusar["recusar"]
    proteger_entrada -.-> extrair["extrair"]
    extrair -.-> pedir_dados["pedir_dados"]
    extrair -.-> identificar_servidor["identificar_servidor"]
    identificar_servidor -.-> pedir_dados
    identificar_servidor -.-> calcular_periodo["calcular_periodo"]
    calcular_periodo --> normas["normas"]
    calcular_periodo --> escala["escala"]
    calcular_periodo --> financeiro["financeiro"]
    normas --> consolidar["consolidar"]
    escala --> consolidar
    financeiro --> consolidar
    consolidar --> redigir_despacho["redigir_despacho"]
    redigir_despacho --> validar["validar"]
    validar -.-> redigir_despacho
    validar -.-> aprovacao_chefia["aprovacao_chefia"]
    validar -.-> registrar["registrar"]
    aprovacao_chefia -.-> redigir_despacho
    aprovacao_chefia -.-> registrar
    recusar --> __end__["__end__"]
    pedir_dados --> __end__
    registrar --> __end__


    ## Etapa 4 (pronta): o que eu entendi

- Diferença entre a saída online e a offline: A saída online consulta a API externa em tempo real via rede; a offline utiliza fixtures ou respostas cacheadas localmente, garantindo testes reproduzíveis e resiliência caso a rede caia.
- Por que a espera do retry dobra a cada tentativa: Para aplicar *exponential backoff*, evitando sobrecarregar e congestionar ainda mais um serviço que esteja instável ou aplicando *rate limiting*.
- Por que o protocolo é um hash dos campos (e não um número sequencial): Garante determinismo e idempotência — o mesmo pedido gera sempre o mesmo identificador exclusivo, evitando duplicidades em bancos de dados distribuídos.
- O que aconteceria sem o cache de feriados: Cada verificação dispararia requisições HTTP redundantes para a API externa, aumentando a latência, consumindo cotas de uso e travando o pipeline se a API ficasse fora do ar.

## Observabilidade (C2)

- Onde o tempo foi gasto: A maior parte do tempo foi consumida nas chamadas aos agentes que consultam o LLM local (`ollama:llama3.1`), especialmente os pareceristas (`financeiro` e `escala`) e o nó `redigir_despacho`.
- Tokens totais: 850

## Opcionais (preencha só os que fez)

- 🆕 A: votos e decisão do C9: 2 votos por "incompleto" vs 1 por "férias" (decisão: pediu dados) ; tempo dos 3 extratores em paralelo: 14.8 s, em sequência: 39.2 s
- 🆕 B: saída do `python etapa06_linear.py --governanca`: Bloqueio de tool restrita (`consultar_remuneracao`) com sucesso e interrupção por estouro de orçamento de tools (2 de 1) com sucesso.
- 🆕 C: caminho do C10 com a triagem humana (sim e não): Sim: `receber -> proteger_entrada -> triagem_humana -> extrair -> ... -> registrar`; Não: `receber -> proteger_entrada -> triagem_humana -> recusar`.

## Reflexão (até 3 linhas cada)

1. Quem decide o caminho no seu sistema: o LLM, o grafo, as regras ou um humano? Dê um exemplo de cada.
O LLM interpreta e extrai dados do texto; o grafo define a sequência e bifurcações dos nós; as regras em Python barram violações objetivas (como limite de afastamentos da escala); e o humano autoriza na chefia imediata (`aprovacao_chefia`).

2. Se o guardrail de entrada falhar, o que ainda impede uma autoaprovação?
A regra determinística no servidor MCP (`registrar_decisao`), que valida se a matrícula do solicitante coincide com a do aprovador e rejeita a gravação com evento `DENY`.

3. Por que o nó da chefia não pode gravar nada antes do `interrupt()`?
Porque o `interrupt()` pausa o fluxo para validação externa; gravar antes geraria o registro indevido de um ato administrativo que ainda nem foi homologado.

4. Qual dado veio do **MCP**, qual de **API externa** e qual de **tool local**? Por que essa divisão?
O MCP forneceu cadastro e registros funcionais (dados corporativos protegidos); as APIs externas trouxeram feriados e câmbio (dados públicos); e as tools locais processaram datas e hashes (cálculos rápidos e seguros).

5. O que você mudaria para colocar este sistema em produção?
Usaria PostgreSQL para persistir os checkpoints do LangGraph, conectaria o MCP via transporte HTTP autenticado em container dedicado e executaria o modelo em servidor com GPU dedicada.

6. (Só se fez) 🆕 A: votar triplica o custo da extração. Em que pedidos vale a pena?
Em pedidos de alto impacto financeiro/jurídico ou quando a extração inicial registrar baixa confiança e ambiguidade textual explícita.

7. (Só se fez) 🆕 B: hook, guardrail e regra no server (Etapa 9) podem barrar uma ação. Qual a diferença de **onde** cada um atua?
O guardrail atua na borda sobre os dados de entrada/saída de texto; o hook monitora e limita o comportamento interno do ciclo de agentes; e a regra no server atua como barreira final e imutável de acesso ao banco de dados.

8. (Só se fez) 🆕 C: o que muda quando o humano decide a **entrada** em vez da **saída**? Quem é consultado em cada pausa?
Na entrada, a triagem avalia se o pedido é pertinente ao RH (atendente); na saída, delibera-se sobre o mérito da concessão do afastamento (chefia imediata).

## De onde veio cada parte

| Arquivo / trecho | Exemplo das aulas em que me baseei | O que precisei adaptar |
|---|---|---|
| etapa07_grafo.py (paralelismo) | aula7/exemplos/08_paralelismo/main.py | Reducer com operator.add para combinar violações e caminhos em branches simultâneos. |
| etapa07_grafo.py (interrupt) | aula7/exemplos/07_aprovacao_revisao/main.py | Pausa e retomada via Command(resume=...) integrado ao banco relacional SqliteSaver. |
| etapa05_mcp_rh.py (segurança) | aula5/exemplos/10_seguranca/server_seguro.py | Checagem de token e validação estrita de permissão de chefia na tool registrar_decisao. |
| etapa10_governanca.py (hooks) | aula3/agente_hook2.py | Lançamento de LimiteExcedido herdando de AgentsException para interromper o runner. |