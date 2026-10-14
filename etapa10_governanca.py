"""
🆕 B (OPCIONAL, bônus) -- Hooks para CONTROLAR, não só para observar. E ETAPA 10.1 (obrigatória): o hook que registra.

Sem tempo? Pule os itens 🆕 B: a classe Governanca já funciona como hook "só observador" (conta as chamadas) e a
Etapa 10.1 usa este mesmo arquivo.

Conceito que você já conhece: em aula3/agente_hook2.py e aula3/agente_loop.py os RunHooks só IMPRIMIAM
("turno 2", "chamou a ferramenta X"). Contexto novo: o mesmo gancho roda ANTES de cada tool (on_tool_start) e
ANTES de cada chamada ao modelo (on_llm_start) -- então ele pode BARRAR a execução. Não há exemplo pronto disto.

ESQUELETO:
  🆕 B.1 (opcional) -- PERMISSOES: quais tools cada agente pode chamar
  🆕 B.2 (opcional) -- on_tool_start: tool fora da lista do agente OU orçamento de tools estourado -> LimiteExcedido
  🆕 B.3 (opcional) -- on_llm_start: orçamento de chamadas ao modelo estourado -> LimiteExcedido
  ETAPA 10.1 -- on_tool_end / on_agent_end: registre tool, argumentos, resultado e tokens (o MESMO hook, outro papel)

REFERÊNCIAS NAS AULAS
  aula3/agente_hook2.py, aula3/agente_hook3.py   a assinatura dos métodos de RunHooks (on_llm_start, on_tool_start...)
  aula3/agente_loop.py                           o hook contando turnos e tools do loop do agente
  aula8/exemplos/06_excessive_agency/1_codigo_pronto/main.py   o risco que a lista de permissões evita

Por que funciona: o SDK chama on_tool_start ANTES de executar a tool. Uma exceção levantada ali interrompe o
Runner e a tool NÃO roda. Trate LimiteExcedido em volta do Runner (etapa06_linear.py). Dois detalhes do SDK:
  1. LimiteExcedido herda de AgentsException. Se herdasse de Exception, o SDK a embrulharia num UserError
     ("Error running tool ...") e o seu `except LimiteExcedido` não a pegaria.
  2. Dentro de um especialista chamado via as_tool, o SDK, por padrão, transforma QUALQUER erro em uma mensagem
     de texto para o Coordenador, e a execução continua: o bloqueio seria engolido. Por isso, em
     agentes.criar_coordenador(), as as_tool recebem failure_error_function=None (o erro sobe de verdade).
"""
"""
🆕 B (OPCIONAL, bônus) -- Hooks para CONTROLAR, não só para observar. E ETAPA 10.1 (obrigatória): o hook que registra.
"""
import json
from agents import AgentsException, RunHooks


class LimiteExcedido(AgentsException):
    """Levantada pelo hook quando um agente sai do que lhe é permitido."""


# 🆕 B.1 -- agente -> conjunto de nomes de tools permitidas.
PERMISSOES: dict[str, set[str]] = {
    "Normas": {"consultar_normas"},
    "Escala": {"consultar_escala"},
    "Financeiro": {"consultar_remuneracao", "tabela_diarias"},
    "Coordenador": {"parecer_normas", "parecer_escala", "parecer_financeiro"},
    "Redator": set(),
}


class Governanca(RunHooks):
    def __init__(self, max_tools: int = 6, max_llm: int = 12, verbose: bool = True):
        self.max_tools, self.max_llm, self.verbose = max_tools, max_llm, verbose
        self.tools_chamadas = 0
        self.chamadas_llm = 0
        self.eventos: list[dict] = []  # ETAPA 10.1

    async def on_tool_start(self, context, agent, tool) -> None:
        self.tools_chamadas += 1

        # 🆕 B.2: Verificação de lista de permissões
        permitidas = PERMISSOES.get(agent.name, set())
        if tool.name not in permitidas:
            msg = f"{agent.name} não tem permissão para usar a ferramenta '{tool.name}'"
            if self.verbose:
                print(f"[governança] BLOQUEADO: {msg}")
            raise LimiteExcedido(msg)

        # 🆕 B.2: Verificação de orçamento de chamadas a ferramentas
        if self.tools_chamadas > self.max_tools:
            msg = f"orçamento de tools estourado ({self.tools_chamadas} de {self.max_tools})"
            if self.verbose:
                print(f"[governança] BLOQUEADO: {msg}")
            raise LimiteExcedido(msg)

        if self.verbose:
            print(f"[governança] {agent.name} -> {tool.name}: OK")

    async def on_llm_start(self, context, agent, system_prompt, input_items) -> None:
        self.chamadas_llm += 1
        # 🆕 B.3: Verificação de orçamento de chamadas ao modelo
        if self.chamadas_llm > self.max_llm:
            msg = f"orçamento de chamadas ao modelo estourado ({self.chamadas_llm} de {self.max_llm})"
            if self.verbose:
                print(f"[governança] BLOQUEADO: {msg}")
            raise LimiteExcedido(msg)

    async def on_tool_end(self, context, agent, tool, result) -> None:
        # ETAPA 10.1: Registro detalhado da execução da ferramenta
        args = getattr(context, "tool_arguments", None)
        if args is None and hasattr(context, "arguments"):
            args = context.arguments

        resultado_truncado = str(result)[:200] if result is not None else ""

        self.eventos.append({
            "tipo": "tool",
            "agente": agent.name,
            "tool": tool.name,
            "argumentos": args,
            "resultado": resultado_truncado,
        })

    async def on_agent_end(self, context, agent, output) -> None:
        # ETAPA 10.1: Registro de tokens consumidos pelo agente
        tokens = 0
        usage = getattr(context, "usage", None)
        if usage:
            tokens = getattr(usage, "total_tokens", 0)

        self.eventos.append({
            "tipo": "agente_end",
            "agente": agent.name,
            "tokens": tokens,
        })