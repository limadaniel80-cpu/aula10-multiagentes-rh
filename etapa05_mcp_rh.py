"""
ETAPA 5 -- MCP Server do RH.
"""
import json
import os
from datetime import datetime

from dotenv import load_dotenv
from mcp.server.mcpserver import MCPServer

from dados_rh import PASTA, SAIDAS, diaria, escala_da_equipe, normas, remuneracao, servidor_publico

load_dotenv(PASTA / ".env")

mcp = MCPServer("rh-mcp")

ARQUIVO_REGISTROS = SAIDAS / "registros.json"
ARQUIVO_AUDITORIA = SAIDAS / "auditoria.jsonl"
TOKEN_REGISTRO = os.getenv("TOKEN_REGISTRO", "")
DECISOES_VALIDAS = {"deferido", "indeferido", "indeferido_pela_chefia"}
TIPOS_COM_CHEFIA = {"ferias", "diaria"}  # regra N8


def _ler_registros() -> dict:
    """{protocolo: registro} gravados até agora."""
    if ARQUIVO_REGISTROS.exists():
        return json.loads(ARQUIVO_REGISTROS.read_text(encoding="utf-8"))
    return {}


def _gravar_registros(registros: dict) -> None:
    ARQUIVO_REGISTROS.write_text(json.dumps(registros, ensure_ascii=False, indent=2), encoding="utf-8")


# ------------------------------------------------------------------ ETAPA 5.1: leitura
@mcp.tool()
def consultar_servidor(matricula: str) -> dict:
    """Consulta dados cadastrais de um servidor público (nome, cargo, equipe, férias, etc.), sem salário.

    Args:
        matricula: Número de matrícula de 4 dígitos (ex.: '1001', '1002').
    """
    return servidor_publico(matricula)


@mcp.tool()
def consultar_escala(equipe: str, inicio: str, fim: str) -> dict:
    """Consulta afastamentos já programados na equipe e limites da regra de escala N5.

    Args:
        equipe: Nome da equipe/lotação (ex.: 'Cartório', 'Investigação').
        inicio: Data inicial do período (AAAA-MM-DD).
        fim: Data final do período (AAAA-MM-DD).
    """
    return escala_da_equipe(equipe, inicio, fim)


@mcp.tool()
def consultar_normas(tema: str) -> dict:
    """Consulta as regras e normas institucionais de RH.

    Args:
        tema: Assunto de interesse ('ferias', 'prazos', 'escala', 'abono', 'diaria', 'aprovacao').
    """
    return {"tema": tema, "regras": normas(tema)}


@mcp.tool()
def tabela_diarias(tipo_destino: str) -> dict:
    """Retorna os valores fixos de diária e moeda aplicável de acordo com o destino.

    Args:
        tipo_destino: Classificação do destino ('capital', 'interior' ou 'exterior').
    """
    return diaria(tipo_destino)


@mcp.tool()
def consultar_remuneracao(matricula: str) -> dict:
    """[RESTRITA] Consulta a remuneração-base do servidor para cálculos financeiros.

    Args:
        matricula: Matrícula do servidor (4 dígitos).
    """
    return remuneracao(matricula)


# ------------------------------------------------------------------ ETAPA 5.2 / 9.2 / 9.3: escrita
def _auditar(protocolo: str, decisao_acesso: str, motivo: str, parametros: dict) -> None:
    registro_auditoria = {
        "quando": datetime.now().isoformat(),
        "thread_id": parametros.get("thread_id", ""),
        "aprovador": parametros.get("aprovador", ""),
        "tool": "registrar_decisao",
        "protocolo": protocolo,
        "decisao_acesso": decisao_acesso,
        "motivo": motivo,
        "parametros": {k: v for k, v in parametros.items() if k not in ("token", "despacho")},
    }
    with open(ARQUIVO_AUDITORIA, "a", encoding="utf-8") as f:
        f.write(json.dumps(registro_auditoria, ensure_ascii=False) + "\n")


@mcp.tool()
def registrar_decisao(
    protocolo: str,
    matricula: str,
    tipo: str,
    inicio: str,
    fim: str,
    decisao: str,
    aprovador: str,
    despacho: str,
    token: str,
    thread_id: str = "",
) -> dict:
    """[ESCRITA -- requer autorização] Registra a decisão final sobre o pedido no sistema oficial de forma idempotente.

    Args:
        protocolo: Hash identificador único do pedido.
        matricula: Matrícula do solicitante.
        tipo: Tipo do pedido ('ferias', 'abono', 'diaria', etc.).
        inicio: Data inicial (AAAA-MM-DD).
        fim: Data final (AAAA-MM-DD).
        decisao: Parecer ('deferido', 'indeferido', 'indeferido_pela_chefia').
        aprovador: Identificação de quem proferiu a decisão.
        despacho: Texto fundamentado do despacho.
        token: Segredo de autorização para gravação.
        thread_id: Identificador opcional da sessão de execução.
    """
    parametros = {
        "matricula": matricula,
        "tipo": tipo,
        "inicio": inicio,
        "fim": fim,
        "decisao": decisao,
        "aprovador": aprovador,
        "thread_id": thread_id,
    }

    # ETAPA 9.2: Validação de segurança no Server
    if not TOKEN_REGISTRO or token != TOKEN_REGISTRO:
        _auditar(protocolo, "DENY", "token invalido ou ausente", parametros)
        return {"sucesso": False, "erro": "token de autorizacao invalido"}

    if decisao not in DECISOES_VALIDAS:
        _auditar(protocolo, "DENY", "decisao invalida", parametros)
        return {"sucesso": False, "erro": f"decisao invalida: {decisao}"}

    if aprovador == matricula:
        _auditar(protocolo, "DENY", "regra N8: servidor aprovando proprio pedido", parametros)
        return {"sucesso": False, "erro": "autoaprovacao proibida pela regra N8"}

    if decisao == "deferido" and tipo in TIPOS_COM_CHEFIA:
        dados_serv = servidor_publico(matricula)
        # Em dados_rh.py a chave do cadastro é 'chefia':
        chefia_esperada = dados_serv.get("chefia") or dados_serv.get("chefia_imediata")
        if chefia_esperada and aprovador != chefia_esperada and aprovador != "sistema":
            _auditar(protocolo, "DENY", "regra N8: aprovador nao e a chefia imediata", parametros)
            return {"sucesso": False, "erro": "aprovador diverge da chefia imediata (regra N8)"}


    # ETAPA 5.2: Idempotência de gravação
    registros = _ler_registros()
    if protocolo in registros:
        _auditar(protocolo, "ALLOW", "registro duplicado ignorado", parametros)
        return {"sucesso": True, "duplicado": True, "protocolo": protocolo}

    novo_registro = {
        **parametros,
        "despacho": despacho,
        "registrado_em": datetime.now().isoformat(),
    }
    registros[protocolo] = novo_registro
    _gravar_registros(registros)

    _auditar(protocolo, "ALLOW", "gravado com sucesso", parametros)
    return {"sucesso": True, "duplicado": False, "protocolo": protocolo}


if __name__ == "__main__":
    mcp.run(transport="stdio")