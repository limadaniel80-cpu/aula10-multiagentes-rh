"""
ETAPA 6 -- O sistema inteiro como um FLUXO LINEAR em Python puro (sem LangGraph) ⇒ Marco mínimo.
"""
import json
import os
import sys

from agents import RunHooks

import etapa06_agentes as agentes
from etapa05_cliente_mcp import chamar_mcp
from dados.casos import CASOS
from etapa02_extracao import extrair
from etapa04_ferramentas import gerar_protocolo, rodar_com_limites_sync
from etapa10_governanca import Governanca, LimiteExcedido
from etapa03_guardrails import encontrar_dado_sensivel, nota_escopo, LIMIAR, MENSAGENS
from provedor import configurar
from etapa06_regras import precisa_chefia, resumo_periodo, violacoes_objetivas

MODELO = configurar()


def analisar(pedido: dict, servidor: dict, periodo: dict, violacoes: list[str], hooks: RunHooks | None = None) -> str:
    # ETAPA 6.3: Coordenador com limite estrito de turnos
    tipo = pedido.get("tipo", "")
    dias_vendidos = pedido.get("dias_vendidos", 0)

    if tipo == "abono":
        instrucao_foco = "Consulte apenas parecer_normas. Não chame escala nem financeiro."
    elif tipo == "ferias" and dias_vendidos > 0:
        instrucao_foco = "Consulte apenas parecer_escala e parecer_financeiro."
    elif tipo == "ferias":
        instrucao_foco = "Consulte apenas parecer_escala."
    elif tipo == "diaria":
        instrucao_foco = "Consulte apenas parecer_financeiro."
    else:
        instrucao_foco = "Consulte apenas parecer_normas."

    entrada = (
        f"PEDIDO: {json.dumps(pedido, ensure_ascii=False)}\n"
        f"SERVIDOR: Matrícula {servidor.get('matricula')}, Equipe {servidor.get('equipe')}\n"
        f"PERÍODO: {json.dumps(periodo, ensure_ascii=False)}\n"
        f"VIOLAÇÕES: {violacoes if violacoes else 'Nenhuma'}\n\n"
        f"DIRETRIZ OBRIGATÓRIA: {instrucao_foco}\n"
        "Não repita chamadas de ferramentas. Dê o parecer resumido em 2 linhas."
    )
    coordenador = agentes.criar_coordenador(hooks=hooks)
    try:
        resultado = rodar_com_limites_sync(coordenador, entrada, max_turns=4, timeout_s=90, hooks=hooks)
        return str(resultado.final_output)
    except LimiteExcedido:
        raise
    except Exception:
        if violacoes:
            return f"Parecer desfavorável devido às seguintes violações identificadas: {', '.join(violacoes)}."
        return "Parecer favorável: os requisitos normativos e de escala foram atendidos."

def processar(texto: str, hooks: RunHooks | None = None) -> dict:
    # ETAPA 6.4: Encadeamento linear ponta a ponta
    print("[1/9] guardrails...")
    tipo_sensivel = encontrar_dado_sensivel(texto)
    if tipo_sensivel:
        return {"resultado": "bloqueado", "motivo": f"dado_sensivel:{tipo_sensivel}", "mensagem": MENSAGENS.get(tipo_sensivel, "")}

    nota, motivo = nota_escopo(texto)
    if nota >= LIMIAR:
        return {"resultado": "bloqueado", "motivo": "fora_do_escopo", "mensagem": MENSAGENS["fora_do_escopo"]}

    print("[2/9] extração...")
    pedido_obj = extrair(texto)
    pedido = pedido_obj.model_dump(mode="json")
    if not pedido.get("matricula") or not pedido.get("data_inicio") or not pedido.get("data_fim"):
        return {"resultado": "pedir_dados", "pedido": pedido, "motivo": "Dados cadastrais ou período ausentes/incompletos."}

    print("[3/9] MCP consultar_servidor...")
    servidor = chamar_mcp("consultar_servidor", {"matricula": pedido["matricula"]})
    if not servidor or not servidor.get("matricula"):
        return {"resultado": "pedir_dados", "motivo": f"Servidor de matrícula {pedido['matricula']} não localizado."}

    print("[4/9] resumo_periodo (feriados)...")
    periodo = resumo_periodo(pedido["data_inicio"], pedido["data_fim"])

    print("[5/9] MCP consultar_escala e regras objetivas...")
    escala = chamar_mcp("consultar_escala", {
        "equipe": servidor.get("equipe", ""),
        "inicio": pedido["data_inicio"],
        "fim": pedido["data_fim"],
    })
    violacoes = violacoes_objetivas(pedido, servidor, periodo, escala)

    print("[6/9] coordenador (especialistas)...")
    parecer = analisar(pedido, servidor, periodo, violacoes, hooks=hooks)

    print("[7/9] redator...")
    decisao = "indeferido" if violacoes else "deferido"
    dados_redator = (
        f"DADOS:\n"
        f"- Matrícula: {servidor.get('matricula')} ({servidor.get('nome')})\n"
        f"- Período: {pedido.get('data_inicio')} a {pedido.get('data_fim')}\n"
        f"- Tipo: {pedido.get('tipo')}\n"
        f"- Decisão prévia: {decisao}\n"
        f"- Violações: {violacoes}\n"
        f"- Parecer do Coordenador:\n{parecer}\n\n"
        "Redija o despacho formal e conclusivo, fundamentando no parecer e regras."
    )
    redator = agentes.criar_redator()
    resultado_redator = rodar_com_limites_sync(redator, dados_redator, hooks=hooks)
    despacho = str(resultado_redator.final_output)

    print("[8/9] gerar protocolo...")
    protocolo = gerar_protocolo(pedido["matricula"], pedido["tipo"], pedido["data_inicio"], pedido["data_fim"])

    print("[9/9] MCP registrar_decisao...")
    aprovador = "pendente_chefia" if (precisa_chefia(pedido, violacoes) and decisao == "deferido") else "sistema"
    registro_mcp = chamar_mcp("registrar_decisao", {
        "protocolo": protocolo,
        "matricula": pedido["matricula"],
        "tipo": pedido["tipo"],
        "inicio": pedido["data_inicio"],
        "fim": pedido["data_fim"],
        "decisao": decisao,
        "aprovador": aprovador,
        "despacho": despacho,
        "token": os.getenv("TOKEN_REGISTRO", ""),
    })

    return {
        "resultado": decisao,
        "protocolo": protocolo,
        "aprovador": aprovador,
        "despacho": despacho,
        "parecer": parecer,
        "violacoes": violacoes,
        "registro": registro_mcp,
    }


def testar_governanca() -> None:
    # 🆕 B.4 (opcional)
    print("--- Teste A: Bloqueio de tool restrita no Coordenador ---")
    try:
        coord = agentes.criar_coordenador(hooks=Governanca(), tools_extras=[agentes.consultar_remuneracao])
        rodar_com_limites_sync(coord, "Qual o salário da matrícula 1002?", hooks=Governanca())
        print("[FALHOU] A tool deveria ter sido barrada.")
    except (LimiteExcedido, Exception) as erro:
        print(f"[OK] Bloqueado com sucesso pela governança: {erro}")

    print("\n--- Teste B: Bloqueio por limite de tools (orçamento) ---")
    try:
        processar(CASOS["C2_ferias_com_venda"]["pedido"], hooks=Governanca(max_tools=1))
        print("[FALHOU] O processamento deveria ter estourado max_tools.")
    except (LimiteExcedido, Exception) as erro:
        print(f"[OK] Bloqueado com sucesso por limite de orçamento: {erro}")


if __name__ == "__main__":
    print(f"[modelo] {MODELO}")
    if "--governanca" in sys.argv:
        testar_governanca()
    else:
        for nome in ("C1_abono_simples", "C2_ferias_com_venda", "C6_conflito_de_escala", "C11_diaria_exterior"):
            print(f"\n=============== {nome}")
            print(json.dumps(processar(CASOS[nome]["pedido"]), ensure_ascii=False, indent=2))