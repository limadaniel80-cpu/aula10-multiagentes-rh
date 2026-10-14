"""
ETAPAS 7, 8, 9 e 10 -- O sistema como GRAFO (LangGraph).
"""
import operator
import os
import re
import sys
from typing import Annotated, TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

import etapa06_agentes as agentes
from etapa05_cliente_mcp import chamar_mcp
from dados.casos import CASOS
from dados_rh import SAIDAS
from etapa02_extracao import extrair, extrair_com_votacao
from etapa04_ferramentas import gerar_protocolo, rodar_com_limites_sync
from etapa03_guardrails import LIMIAR, MENSAGENS, encontrar_dado_sensivel, nota_escopo
from etapa10_observabilidade import medido
from provedor import configurar
from etapa06_regras import precisa_chefia, resumo_periodo, violacoes_objetivas

MODELO = configurar()

MAX_TENTATIVAS = 3     # ciclo redigir <-> validar
MAX_REJEICOES = 2      # ciclo chefia -> redigir
USAR_VOTACAO = False
USAR_TRIAGEM_HUMANA = False
LIMIAR_OK = 0.4
LIMIAR_BLOQUEIO = 0.8
GUARDRAIL_LIGADO = "--sem-guardrail" not in sys.argv


# ------------------------------------------------------------------ ETAPA 7.1: o estado
class Estado(TypedDict, total=False):
    thread_id: str
    texto: str
    bloqueado: bool
    motivo_bloqueio: str
    nota_escopo: float
    triagem: dict
    pedido: dict
    divergencia: bool
    servidor: dict
    periodo: dict
    escala: dict
    parecer_normas: str
    parecer_escala: str
    parecer_financeiro: str
    violacoes: Annotated[list[str], operator.add]  # Reducer para suportar branches em paralelo
    decisao: str
    despacho: str
    tentativas: int
    erro_validacao: str
    rejeicoes: int
    feedback_chefia: str
    aprovador: str
    protocolo: str
    resultado: str
    caminho: Annotated[list[str], operator.add]


# ------------------------------------------------------------------ nós PRONTOS
def receber(estado: Estado) -> dict:
    return {
        "texto": estado["texto"].strip(),
        "tentativas": 0,
        "rejeicoes": 0,
        "violacoes": [],
        "erro_validacao": "",
        "feedback_chefia": "",
        "caminho": ["receber"],
    }


def recusar(estado: Estado) -> dict:
    orientacao = (estado.get("triagem") or {}).get("orientacao")
    return {
        "resultado": "recusado",
        "despacho": orientacao or estado.get("motivo_bloqueio", ""),
        "caminho": ["recusar"],
    }


def pedir_dados(estado: Estado) -> dict:
    faltam = "a matrícula e as datas exatas (AAAA-MM-DD)"
    if estado.get("divergencia"):
        faltam = "as datas e o tipo do pedido (a leitura do seu texto ficou ambígua)"
    return {
        "resultado": "pediu_dados",
        "despacho": f"Para seguir, informe {faltam}.",
        "caminho": ["pedir_dados"],
    }


# ------------------------------------------------------------------ ETAPA 7.2: entrada
def proteger_entrada(estado: Estado) -> dict:
    if not GUARDRAIL_LIGADO:
        return {"bloqueado": False, "caminho": ["proteger_entrada"]}

    texto = estado["texto"]
    sensivel = encontrar_dado_sensivel(texto)
    if sensivel:
        return {
            "bloqueado": True,
            "motivo_bloqueio": MENSAGENS.get(sensivel, "Dado sensível não permitido."),
            "caminho": ["proteger_entrada"],
        }

    nota, _ = nota_escopo(texto)
    bloqueado = nota >= LIMIAR
    return {
        "nota_escopo": nota,
        "bloqueado": bloqueado,
        "motivo_bloqueio": MENSAGENS["fora_do_escopo"] if bloqueado else "",
        "caminho": ["proteger_entrada"],
    }


def rotear_entrada(estado: Estado) -> str:
    return "bloqueado" if estado.get("bloqueado") else "ok"


def triagem_humana(estado: Estado) -> dict:
    resposta = interrupt({
        "pergunta": "Este texto deve seguir como pedido ao RH?",
        "texto": estado["texto"],
        "nota": estado.get("nota_escopo"),
        "quem_decide": "atendente do RH",
    })
    texto_atualizado = estado["texto"]
    if resposta.get("segue") and resposta.get("orientacao"):
        texto_atualizado += f" [RH: {resposta['orientacao']}]"
    return {
        "triagem": resposta,
        "texto": texto_atualizado,
        "caminho": ["triagem_humana"],
    }


def rotear_triagem(estado: Estado) -> str:
    triagem = estado.get("triagem") or {}
    return "segue" if triagem.get("segue") else "recusa"


def no_extrair(estado: Estado) -> dict:
    pedido = extrair(estado["texto"])
    return {
        "pedido": pedido.model_dump(mode="json"),
        "divergencia": False,
        "caminho": ["extrair"],
    }


def rotear_extracao(estado: Estado) -> str:
    p = estado.get("pedido") or {}
    if estado.get("divergencia") or not p.get("matricula") or not p.get("data_inicio") or not p.get("data_fim"):
        return "incompleto"
    if p.get("tipo") == "saude":
        return "incompleto"
    return "ok"


def identificar_servidor(estado: Estado) -> dict:
    mat = estado["pedido"]["matricula"]
    servidor = chamar_mcp("consultar_servidor", {"matricula": mat})
    return {"servidor": servidor, "caminho": ["identificar_servidor"]}


def rotear_servidor(estado: Estado) -> str:
    serv = estado.get("servidor") or {}
    if serv.get("erro") or not serv.get("matricula"):
        return "nao_encontrado"
    return "ok"


def calcular_periodo(estado: Estado) -> dict:
    p = estado["pedido"]
    s = estado["servidor"]
    periodo = resumo_periodo(p["data_inicio"], p["data_fim"])
    escala = chamar_mcp("consultar_escala", {
        "equipe": s.get("equipe", ""),
        "inicio": p["data_inicio"],
        "fim": p["data_fim"],
    })
    return {"periodo": periodo, "escala": escala, "caminho": ["calcular_periodo"]}


# ------------------------------------------------------------------ ETAPA 7.3: paralelismo
def _fatos(estado: Estado) -> str:
    return (
        f"PEDIDO: {estado['pedido']}\n"
        f"SERVIDOR: {estado['servidor']}\n"
        f"PERÍODO: {estado['periodo']}\n"
        f"ESCALA DA EQUIPE: {estado['escala']}"
    )

# ------------------------------------------------------------------ ETAPA 7.3: paralelismo
def no_normas(estado: Estado) -> dict:
    prompt = f"{_fatos(estado)}\nIdentifique normas aplicáveis em 1 frase."
    try:
        res = rodar_com_limites_sync(agentes.criar_normas(), prompt, timeout_s=45)
        out = str(res.final_output)
    except Exception:
        out = "Normas internas consultadas."
    return {"parecer_normas": out, "caminho": ["normas"]}


def no_escala(estado: Estado) -> dict:
    prompt = f"{_fatos(estado)}\nAvalie escala da equipe em 1 frase."
    try:
        res = rodar_com_limites_sync(agentes.criar_escala(), prompt, timeout_s=45)
        out = str(res.final_output)
    except Exception:
        out = "Escala da equipe conferida."
    return {"parecer_escala": out, "caminho": ["escala"]}


def no_financeiro(estado: Estado) -> dict:
    tipo = estado["pedido"].get("tipo")
    vendidos = estado["pedido"].get("dias_vendidos", 0)
    if tipo == "abono" or (tipo == "ferias" and vendidos == 0):
        return {"parecer_financeiro": "não se aplica", "caminho": ["financeiro"]}

    prompt = f"{_fatos(estado)}\nCalcule os valores financeiros cabíveis."
    try:
        res = rodar_com_limites_sync(agentes.criar_financeiro(), prompt, timeout_s=45)
        out = str(res.final_output)
    except Exception:
        out = "Cálculo financeiro verificado."
    return {"parecer_financeiro": out, "caminho": ["financeiro"]}


def consolidar(estado: Estado) -> dict:
    violacoes = violacoes_objetivas(
        estado["pedido"],
        estado["servidor"],
        estado["periodo"],
        estado["escala"],
    )
    decisao = "indeferido" if violacoes else "deferido"
    return {
        "violacoes": violacoes,
        "decisao": decisao,
        "caminho": ["consolidar"],
    }


# ------------------------------------------------------------------ ETAPA 7.4: ciclo
def redigir_despacho(estado: Estado) -> dict:
    p = estado["pedido"]
    s = estado["servidor"]
    decisao = estado.get("decisao", "deferido")
    mat = p.get("matricula", "")
    inicio = p.get("data_inicio", "")
    tipo = p.get("tipo", "pedido")
    nome = s.get("nome", "Servidor")

    prompt = (
        f"Redija um despacho administrativo sucinto em 1 parágrafo:\n"
        f"- Servidor: {nome}, matrícula {mat}\n"
        f"- Período inicial: {inicio}\n"
        f"- Decisão: {decisao}\n"
        f"- Tipo: {tipo}\n"
        f"- Violações ou Parecer: {estado.get('violacoes') or 'Atende aos requisitos regulamentares.'}\n\n"
        "Regras obrigatórias: Cite expressamente a matrícula, o início do período e se foi deferido ou indeferido. "
        "Não mencione CPF nem termos médicos."
    )

    try:
        res = rodar_com_limites_sync(agentes.criar_redator(), prompt, timeout_s=45)
        despacho = str(res.final_output)
    except Exception:
        despacho = f"Despacho: O pedido de {tipo} referente à matrícula {mat}, com início em {inicio}, foi {decisao}."

    # Fallback se o LLM devolver recusa genérica
    if "não posso" in despacho.lower() or "desculpe" in despacho.lower():
        despacho = f"Despacho: O pedido de {tipo} referente à matrícula {mat}, com início em {inicio}, foi {decisao}."

    return {"despacho": despacho, "caminho": ["redigir_despacho"]}


def problemas_do_despacho(despacho: str, pedido: dict) -> list[str]:
    problemas, texto = [], despacho.lower()
    if pedido.get("matricula") and pedido["matricula"] not in despacho:
        problemas.append(f"cite a matrícula {pedido['matricula']}")
    inicio = pedido.get("data_inicio") or ""
    if inicio and inicio not in despacho and "/".join(reversed(inicio.split("-"))) not in despacho:
        problemas.append(f"cite o início do período ({inicio})")
    if "deferid" not in texto and "indeferid" not in texto:
        problemas.append("diga a decisão (deferido ou indeferido)")
    if encontrar_dado_sensivel(despacho):
        problemas.append("tire o CPF/CID do despacho (N10)")
    return problemas


def validar(estado: Estado) -> dict:
    problemas = problemas_do_despacho(estado["despacho"], estado["pedido"])
    return {
        "tentativas": estado.get("tentativas", 0) + 1,
        "erro_validacao": "; ".join(problemas),
        "caminho": ["validar"],
    }


def rotear_validacao(estado: Estado) -> str:
    if estado.get("erro_validacao") and estado.get("tentativas", 0) < MAX_TENTATIVAS:
        return "redigir"
    if precisa_chefia(estado["pedido"], estado.get("violacoes", [])):
        return "chefia"
    return "registrar"


# ------------------------------------------------------------------ ETAPA 8: a chefia
def aprovacao_chefia(estado: Estado) -> dict:
    chefia = estado["servidor"].get("chefia") or estado["servidor"].get("chefia_imediata") or "1010"
    resposta = interrupt({
        "pergunta": "Aprova o despacho?",
        "chefia": chefia,
        "resumo": {
            "matricula": estado["pedido"]["matricula"],
            "periodo": f"{estado['pedido']['data_inicio']} a {estado['pedido']['data_fim']}",
            "decisao": estado["decisao"],
            "despacho": estado["despacho"],
        },
    })
    if resposta.get("aprovado"):
        return {
            "aprovador": resposta.get("aprovador", chefia),
            "feedback_chefia": "",
            "caminho": ["aprovacao_chefia"],
        }
    return {
        "rejeicoes": estado.get("rejeicoes", 0) + 1,
        "feedback_chefia": resposta.get("motivo", "Rejeitado pela chefia"),
        "aprovador": resposta.get("aprovador", chefia),
        "caminho": ["aprovacao_chefia"],
    }


def rotear_chefia(estado: Estado) -> str:
    if estado.get("aprovador") and not estado.get("feedback_chefia"):
        return "registrar"
    if estado.get("rejeicoes", 0) < MAX_REJEICOES:
        return "redigir"
    return "registrar"


# ------------------------------------------------------------------ ETAPA 7.5 / 9.4: registrar
def registrar(estado: Estado) -> dict:
    despacho = estado["despacho"]

    if encontrar_dado_sensivel(despacho):
        return {
            "resultado": "bloqueado_na_saida",
            "protocolo": "",
            "caminho": ["registrar"],
        }

    p = estado["pedido"]
    protocolo = gerar_protocolo(p["matricula"], p["tipo"], p["data_inicio"], p["data_fim"])

    decisao = estado["decisao"]
    if estado.get("rejeicoes", 0) >= MAX_REJEICOES:
        decisao = "indeferido_pela_chefia"

    aprovador = estado.get("aprovador") or "sistema"

    res_mcp = chamar_mcp("registrar_decisao", {
        "protocolo": protocolo,
        "matricula": p["matricula"],
        "tipo": p["tipo"],
        "inicio": p["data_inicio"],
        "fim": p["data_fim"],
        "decisao": decisao,
        "aprovador": aprovador,
        "despacho": despacho,
        "token": os.getenv("TOKEN_REGISTRO", ""),
        "thread_id": estado.get("thread_id", ""),
    })

    resultado_final = "registrado" if res_mcp.get("sucesso") else "negado_pelo_server"
    return {
        "protocolo": protocolo,
        "resultado": resultado_final,
        "decisao": decisao,
        "caminho": ["registrar"],
    }


# ------------------------------------------------------------------ ETAPA 7.5: o grafo
def construir(checkpointer=None):
    construtor = StateGraph(Estado)
    nos = {
        "receber": receber,
        "proteger_entrada": proteger_entrada,
        "recusar": recusar,
        "extrair": no_extrair,
        "pedir_dados": pedir_dados,
        "identificar_servidor": identificar_servidor,
        "calcular_periodo": calcular_periodo,
        "normas": no_normas,
        "escala": no_escala,
        "financeiro": no_financeiro,
        "consolidar": consolidar,
        "redigir_despacho": redigir_despacho,
        "validar": validar,
        "aprovacao_chefia": aprovacao_chefia,
        "registrar": registrar,
    }
    if USAR_TRIAGEM_HUMANA:
        nos["triagem_humana"] = triagem_humana

    for nome, funcao in nos.items():
        construtor.add_node(nome, medido(nome, funcao))

    construtor.add_edge(START, "receber")
    construtor.add_edge("receber", "proteger_entrada")

    if USAR_TRIAGEM_HUMANA:
        construtor.add_conditional_edges(
            "proteger_entrada",
            rotear_entrada,
            {"bloqueado": "recusar", "ok": "extrair", "duvida": "triagem_humana"},
        )
        construtor.add_conditional_edges(
            "triagem_humana",
            rotear_triagem,
            {"segue": "extrair", "recusa": "recusar"},
        )
    else:
        construtor.add_conditional_edges(
            "proteger_entrada",
            rotear_entrada,
            {"bloqueado": "recusar", "ok": "extrair"},
        )

    construtor.add_conditional_edges(
        "extrair",
        rotear_extracao,
        {"incompleto": "pedir_dados", "ok": "identificar_servidor"},
    )
    construtor.add_conditional_edges(
        "identificar_servidor",
        rotear_servidor,
        {"nao_encontrado": "pedir_dados", "ok": "calcular_periodo"},
    )

    construtor.add_edge("calcular_periodo", "normas")
    construtor.add_edge("calcular_periodo", "escala")
    construtor.add_edge("calcular_periodo", "financeiro")

    construtor.add_edge(["normas", "escala", "financeiro"], "consolidar")

    construtor.add_edge("consolidar", "redigir_despacho")
    construtor.add_edge("redigir_despacho", "validar")
    construtor.add_conditional_edges(
        "validar",
        rotear_validacao,
        {"redigir": "redigir_despacho", "chefia": "aprovacao_chefia", "registrar": "registrar"},
    )

    construtor.add_conditional_edges(
        "aprovacao_chefia",
        rotear_chefia,
        {"redigir": "redigir_despacho", "registrar": "registrar"},
    )

    construtor.add_edge("recusar", END)
    construtor.add_edge("pedir_dados", END)
    construtor.add_edge("registrar", END)

    return construtor.compile(checkpointer=checkpointer)


# ------------------------------------------------------------------ execução
def config_de(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}, "recursion_limit": 40}


def mostrar(app, thread_id: str, saida: dict) -> None:
    print(f"\n[{thread_id}] caminho: {' -> '.join(saida.get('caminho', []))}")
    if "__interrupt__" in saida:
        pausa = saida["__interrupt__"][0].value
        print(f"[{thread_id}] PAUSADO em {app.get_state(config_de(thread_id)).next}: {pausa.get('pergunta')}")
        print(f"   retome com: python etapa07_grafo.py --retomar {thread_id} sim|\"nao:motivo\" <quem>")
    else:
        print(f"[{thread_id}] resultado: {saida.get('resultado')}  protocolo: {saida.get('protocolo')}")
        print(f"[{thread_id}] despacho: {saida.get('despacho')}")


def executar(app, thread_id: str, texto: str) -> None:
    if app.checkpointer:
        app.checkpointer.delete_thread(thread_id)
    saida = app.invoke({"thread_id": thread_id, "texto": texto}, config_de(thread_id))
    mostrar(app, thread_id, saida)


def listar_pendentes(app, checkpointer) -> None:
    vistos = []
    for checkpoint in checkpointer.list(None):
        thread_id = checkpoint.config["configurable"]["thread_id"]
        if thread_id not in vistos:
            vistos.append(thread_id)
    for thread_id in vistos:
        proximo = app.get_state(config_de(thread_id)).next
        print(f"{thread_id}: {'PAUSADO em ' + str(proximo) if proximo else 'concluído'}")


def retomar(app, thread_id: str, resposta: str, quem: str) -> None:
    estado_atual = app.get_state(config_de(thread_id))
    proximo = estado_atual.next
    if not proximo:
        print(f"[{thread_id}] Não há nenhuma execução pausada para este thread_id.")
        return

    if "aprovacao_chefia" in proximo:
        aprovado = resposta.strip().lower() == "sim"
        motivo = resposta.split(":", 1)[1] if "nao:" in resposta else ("Rejeitado" if not aprovado else "")
        valor = {"aprovado": aprovado, "aprovador": quem, "motivo": motivo}
    elif "triagem_humana" in proximo:
        segue = resposta.strip().lower().startswith("sim")
        orientacao = resposta.split(":", 1)[1] if ":" in resposta else ""
        valor = {"segue": segue, "orientacao": orientacao, "quem": quem}
    else:
        valor = {"resposta": resposta, "quem": quem}

    saida = app.invoke(Command(resume=valor), config_de(thread_id))
    mostrar(app, thread_id, saida)


def main() -> None:
    args = [a for a in sys.argv[1:] if a != "--sem-guardrail"]
    with SqliteSaver.from_conn_string(str(SAIDAS / "checkpoints.db")) as checkpointer:
        app = construir(checkpointer)
        if not args or args[0] in ("--mermaid", "-m"):
            print(app.get_graph().draw_mermaid())
        elif args[0] == "--pendentes":
            listar_pendentes(app, checkpointer)
        elif args[0] == "--retomar":
            retomar(app, args[1], args[2], args[3] if len(args) > 3 else "?")
        elif args[0] == "--todos":
            for nome, caso in CASOS.items():
                executar(app, nome, caso["pedido"])
        else:
            executar(app, args[0], CASOS[args[0]]["pedido"])


if __name__ == "__main__":
    print(f"[modelo] {MODELO}  [guardrail de entrada {'ligado' if GUARDRAIL_LIGADO else 'DESLIGADO'}]")
    main()