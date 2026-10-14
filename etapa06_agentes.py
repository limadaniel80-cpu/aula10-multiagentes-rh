"""
ETAPA 6 -- Os especialistas, cada um com UMA responsabilidade e SÓ as tools de que precisa.

ESQUELETO:
  ETAPA 6.1 -- criar_normas(), criar_escala(), criar_financeiro(), criar_redator()
  ETAPA 6.2 -- criar_coordenador(): usa Normas, Escala e Financeiro como TOOLS (as_tool)

As tools abaixo (PRONTAS) só repassam a chamada ao MCP Server do RH (cliente_mcp.chamar_mcp_async). Dar a cada agente
só as tools dele é o PRIVILÉGIO MÍNIMO (Etapa 9.1); o hook do 🆕 B (etapa10_governanca.py) confere isso em tempo de execução.

REFERÊNCIAS NAS AULAS
  aula4/ex03_agente_as_tool.py                         Coordenador que chama especialistas como tools    <- o mais parecido
  aula2/agente_handoff2.py                             as_tool com tool_name e tool_description
  aula4/ex02_handoff_roteamento.py                     handoff: compare (quem responde no fim?)
  aula7/exemplos/02_agentes_especializados/main.py     uma responsabilidade por agente
  aula7/agentes.py                                     ModelSettings(temperature=0) para respostas mais estáveis
  aula8/exemplos/06_excessive_agency/1_codigo_pronto/main.py   o problema de dar tools DEMAIS a um agente
"""
import json

from agents import Agent, ModelSettings, RunHooks, function_tool

from etapa05_cliente_mcp import chamar_mcp_async
from etapa04_ferramentas import cotacao_usd_brl

CONFIG = ModelSettings(temperature=0)


# ------------------------------------------------------------------ tools (PRONTAS)
@function_tool
async def consultar_normas(tema: str) -> str:
    """Regras da norma interna sobre um tema: férias, prazos, escala, abono, diária, aprovação, saúde ou dados."""
    return json.dumps(await chamar_mcp_async("consultar_normas", {"tema": tema}), ensure_ascii=False)


@function_tool
async def consultar_escala(equipe: str, inicio: str, fim: str) -> str:
    """Afastamentos da equipe que se sobrepõem ao período (AAAA-MM-DD) e o limite de afastados da regra N5."""
    return json.dumps(await chamar_mcp_async("consultar_escala", {"equipe": equipe, "inicio": inicio, "fim": fim}),
                      ensure_ascii=False)


@function_tool
async def tabela_diarias(tipo_destino: str) -> str:
    """Moeda e valor da diária para o tipo de destino: capital, interior ou exterior."""
    return json.dumps(await chamar_mcp_async("tabela_diarias", {"tipo_destino": tipo_destino}), ensure_ascii=False)


@function_tool
async def consultar_remuneracao(matricula: str) -> str:
    """[RESTRITA] Salário-base de um servidor. Só para calcular a venda de férias (N2)."""
    print(f"[tool] consultar_remuneracao({matricula}) EXECUTOU")  # o 🆕 B prova que, barrada, ela NÃO executa
    return json.dumps(await chamar_mcp_async("consultar_remuneracao", {"matricula": matricula}), ensure_ascii=False)


@function_tool
def cotacao_dolar() -> str:
    """Cotação atual do dólar em reais (USD->BRL). Devolve 'indisponível' se a API falhar: nunca invente o câmbio."""
    cotacao = cotacao_usd_brl()
    return f"{cotacao:.4f}" if cotacao else "indisponível"


# ------------------------------------------------------------------ ETAPA 6.1: especialistas
def criar_normas() -> Agent:
    # ETAPA 6.1: Especialista em regras e normas internas
    return Agent(
        name="Normas",
        instructions=(
            "Você é o especialista em Normas e Legislação interna de Recursos Humanos.\n"
            "Sua única responsabilidade é identificar e explicar as regras aplicáveis ao pedido (ex.: N1 a N10) "
            "em linguagem clara e objetiva.\n"
            "Use a tool 'consultar_normas' para embasar sua resposta.\n"
            "NÃO realize cálculos financeiros e NÃO avalie escalas de equipes."
        ),
        tools=[consultar_normas],
        model_settings=CONFIG,
    )


def criar_escala() -> Agent:
    # ETAPA 6.1: Especialista em escalas e conflitos de afastamento
    return Agent(
        name="Escala",
        instructions=(
            "Você é o especialista em Escala e Afastamentos de Recursos Humanos.\n"
            "Sua responsabilidade é verificar se o período solicitado respeita o limite de afastamentos da equipe (regra N5).\n"
            "Use a tool 'consultar_escala' para checar sobreposições no período informado.\n"
            "Se houver conflito com o limite permitido, aponte o choque e sugira um período alternativo viável "
            "com a mesma quantidade de dias e iniciando em dia útil permitido."
        ),
        tools=[consultar_escala],
        model_settings=CONFIG,
    )


def criar_financeiro() -> Agent:
    # ETAPA 6.1: Especialista em cálculos de pecúnia e diárias
    return Agent(
        name="Financeiro",
        instructions=(
            "Você é o especialista Financeiro de Recursos Humanos.\n"
            "Sua função é calcular exclusivamente os valores financeiros cabíveis:\n"
            "1. Venda de férias (abono pecuniário - N2): (dias_vendidos * salario_base) / 30. Use 'consultar_remuneracao'.\n"
            "2. Diárias (N7): quantidade de pernoites integral + meia diária no retorno. Use 'tabela_diarias'.\n"
            "   Se o destino for exterior, use 'cotacao_dolar' para converter USD para BRL. Se indisponível, informe 'a calcular'.\n"
            "Sempre demonstre a memória de cálculo de forma explícita e resumida."
        ),
        tools=[tabela_diarias, consultar_remuneracao, cotacao_dolar],
        model_settings=CONFIG,
    )


def criar_redator() -> Agent:
    # ETAPA 6.1: Redator de despachos formais (sem tools externas)
    return Agent(
        name="Redator",
        instructions=(
            "Você é o Redator oficial de despachos de Recursos Humanos.\n"
            "Sua função é redigir o texto final do despacho (deferimento ou indeferimento) fundamentado "
            "estritamente nas informações e pareceres recebidos (matrícula, período, decisão, regras, valores e sugestões).\n"
            "REGRAS ESTRITAS (N10):\n"
            "- NUNCA mencione CPF, números de documentos pessoais ou dados médicos/sensíveis (como CID).\n"
            "- Seja direto, formal, impessoal e claro."
        ),
        tools=[],
        model_settings=CONFIG,
    )


# ------------------------------------------------------------------ ETAPA 6.2: coordenador
def criar_coordenador(hooks: RunHooks | None = None, tools_extras: list | None = None) -> Agent:
    # ETAPA 6.2: Orquestrador via as_tool
    tool_normas = criar_normas().as_tool(
        tool_name="parecer_normas",
        tool_description="Consulta o especialista em normas para verificar regras aplicáveis e explicar violações normativas.",
        hooks=hooks,
        failure_error_function=None,
    )
    tool_escala = criar_escala().as_tool(
        tool_name="parecer_escala",
        tool_description="Consulta o especialista em escala para checar disponibilidade da equipe e limites da regra N5.",
        hooks=hooks,
        failure_error_function=None,
    )
    tool_financeiro = criar_financeiro().as_tool(
        tool_name="parecer_financeiro",
        tool_description="Consulta o especialista financeiro para calcular valores de diárias ou indenização de férias vendidas.",
        hooks=hooks,
        failure_error_function=None,
    )

    lista_tools = [tool_normas, tool_escala, tool_financeiro] + (tools_extras or [])

    return Agent(
        name="Coordenador",
        instructions=(
            "Você é o Coordenador do processo de RH. Sua tarefa é analisar o pedido e consultar apenas os especialistas "
            "estritamente necessários usando as tools disponíveis:\n"
            "- 'parecer_normas': use para checar regras em vigor;\n"
            "- 'parecer_escala': use para pedidos de férias de modo a validar escala da equipe;\n"
            "- 'parecer_financeiro': use somente quando houver venda de dias de férias ou diárias a calcular (abono simples não necessita do financeiro).\n"
            "Consolide os pareceres recebidos de forma concisa e objetiva para o encaminhamento da decisão."
        ),
        tools=lista_tools,
        model_settings=CONFIG,
    )