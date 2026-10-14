"""
ETAPA 1 -- Primeiro agente com tool local (15 min).

ESQUELETO: implemente as etapas na ordem. Cada uma está marcada com um comentário e um
raise NotImplementedError: troque esse raise pelo código da etapa e rode o arquivo.
  ETAPA 1.1 -- a tool consultar_servidor (SEM o salário)
  ETAPA 1.2 -- o agente AtendenteRH com a tool
  ETAPA 1.3 -- duas perguntas: uma que precisa da tool e uma que não precisa

REFERÊNCIAS NAS AULAS
  aula1/segundo_agente.py                             Agent + @function_tool + Runner.run_sync (o básico)
  exercicios_resolvidos/aula4/ex10_function_tool.py  tool que consulta uma TABELA e devolve JSON  <- o mais parecido
  aula8/exemplos/02_agente_tool/main.py              o agente decide quando chamar a tool (e quando não)

Rodar (a partir de aula10/):
    python etapa01_agente.py

Pronto quando: a tool é chamada só na primeira pergunta (o print dentro dela prova).
"""
import json

from agents import Agent, Runner, function_tool

from dados_rh import servidor_publico
from provedor import configurar

MODELO = configurar()  # LLM REAL: PROVEDOR no .env (openai ou ollama)


# ETAPA 1.1 -- a tool
#   - ponha um print("[tool] consultar_servidor", matricula) no começo, para provar quando ela roda;
#   - devolva json.dumps(servidor_publico(matricula), ensure_ascii=False). A consulta servidor_publico() (dados_rh.py)
#     já vem pronta: tira o salário (dado restrito, ver Etapas 5 e 9) e trata matrícula inexistente;
#   - capriche na DOCSTRING (com Args:): é o que o LLM lê para decidir chamar a tool. Esse é o ponto da etapa.
#   Referência: exercicios_resolvidos/aula4/ex10_function_tool.py (consultar_protocolo)

@function_tool
def consultar_servidor(matricula: str) -> str:
    """Busca o saldo de férias e dados de um servidor público pelo número exato da matrícula.

    Regra de acionamento:
    - Chame esta ferramenta SOMENTE quando a pergunta fornecer explicitamente uma matrícula numérica (ex.: '1001', '1002').
    - NÃO chame esta ferramenta se a pergunta for teórica, conceitual, geral ou se não houver matrícula informada.

    Args:
        matricula: Número da matrícula do servidor composto apenas por dígitos numéricos.
    """
    # Proteção: só imprime e executa se vier um número de verdade
    matricula_limpa = str(matricula).strip()
    if not matricula_limpa.isdigit():
        return json.dumps({"erro": "matrícula inválida"}, ensure_ascii=False)

    print("[tool] consultar_servidor", matricula_limpa)
    dados = servidor_publico(matricula_limpa)
    return json.dumps(dados, ensure_ascii=False)


def criar_atendente() -> Agent:
    return Agent(
        name="AtendenteRH",
        instructions=(
            "Você é o atendente do setor de Recursos Humanos. Responda sempre em português, com clareza e brevidade.\n\n"
            "CRITÉRIO OBRIGATÓRIO PARA FERRAMENTAS:\n"
            "- Se e somente se a pergunta contiver o número de matrícula de um servidor, acione a ferramenta `consultar_servidor`.\n"
            "- Se a pergunta for teórica, conceitual, legal ou explicativa (sem número de matrícula), "
            "responda fundamentando conceitualmente com seu conhecimento interno, sem acionar nenhuma ferramenta externa."
        ),
        tools=[consultar_servidor],
    )

def main() -> None:
    # ETAPA 1.3 -- rode as duas perguntas com Runner.run_sync e imprima resultado.final_output
    #   1) "Quantos dias de férias a matrícula 1002 ainda tem?"   (precisa da tool)
    #   2) "O que é abono pecuniário?"                            (não precisa)
    #   Referência: aula8/exemplos/02_agente_tool/main.py
    atendente = criar_atendente()

    # Pergunta 1: Requer busca cadastral via tool
    p1 = "Quantos dias de férias a matrícula 1002 ainda tem?"
    r1 = Runner.run_sync(atendente, p1)
    print(r1.final_output)

    # Pergunta 2: Dúvida conceitual geral (não deve disparar a tool)
    p2 = "O que é abono pecuniário?"
    r2 = Runner.run_sync(atendente, p2)
    print(r2.final_output)


if __name__ == "__main__":
    print(f"[modelo] {MODELO}")
    main()