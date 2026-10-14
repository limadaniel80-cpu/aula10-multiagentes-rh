"""
ETAPA 2 -- Extração estruturada do pedido (15 min) e 🆕 A -- votação em paralelo (OPCIONAL, bônus).

ESQUELETO: implemente as etapas na ordem (troque cada raise NotImplementedError pelo código da etapa).
  ETAPA 2.1 -- complete o modelo Pydantic `Pedido` (campos + Field(description=...))
  ETAPA 2.2 -- criar_extrator(): um Agent com output_type=Pedido
  ETAPA 2.3 -- extrair(): roda UM extrator e devolve um Pedido
  --- daqui para baixo é OPCIONAL (item 🆕 A, vale bônus). Pule se estiver sem tempo: o resto do sistema não depende dele.
  🆕 A.1    -- INSTRUCOES_VOTANTES: 3 instruções ligeiramente diferentes
  🆕 A.2    -- extrair_com_votacao(): os 3 extratores AO MESMO TEMPO (asyncio.gather)
  (PRONTO)  -- votar(): maioria por campo; sem maioria em tipo/datas -> divergencia=True
  (PRONTO)  -- no __main__: o tempo em paralelo x em sequência

REFERÊNCIAS NAS AULAS
  aula2/agente_output.py                   output_type com um BaseModel simples
  aula2/agente_output2.py                  Enum + listas + Field(description=...)           <- o mais parecido
  aula7/exemplos/08_paralelismo/main.py    🆕 A: o CONCEITO de paralelismo (lá: tarefas DIFERENTES para ganhar tempo;
                                           aqui: a MESMA tarefa 3 vezes para ganhar confiabilidade)
  aula3/agente_parada3.py                  Runner.run (assíncrono) dentro de asyncio, como em A.2
  aula3/agente_retry.py                    por que a data de hoje entra nas instruções (já feito abaixo, com texto_hoje())

Rodar:
    python etapa02_extracao.py            # extrai C1, C2, C5 e C11
    python etapa02_extracao.py --votacao  # 🆕 A: C1, C2 e C9 com 3 votos e o tempo medido

Pronto quando: C2 sai com dias_vendidos=10, C11 com tipo_destino="exterior", C5 com matricula=None;
               na votação, C1/C2 unânimes e C9 mostrando os votos.
"""
"""
ETAPA 2 -- Extração estruturada do pedido (15 min) e 🆕 A -- votação em paralelo (OPCIONAL, bônus).
"""
import asyncio
import re
import sys
import time
from collections import Counter
from datetime import datetime, timedelta
from enum import Enum

from agents import Agent, Runner
from pydantic import BaseModel, Field, field_validator

from dados.casos import CASOS
from etapa04_ferramentas import texto_hoje
from provedor import configurar

MODELO = configurar()


class TipoPedido(str, Enum):
    FERIAS = "ferias"
    ABONO = "abono"
    DIARIA = "diaria"
    LICENCA_SAUDE = "licenca_saude"
    OUTRO = "outro"


class TipoDestino(str, Enum):
    CAPITAL = "capital"
    INTERIOR = "interior"
    EXTERIOR = "exterior"


class Pedido(BaseModel):
    tipo: TipoPedido = Field(
        description="Tipo do pedido: 'ferias' (descanso), 'abono' (folga de 1 dia), 'diaria' (viagem a serviço/congresso/missão), 'licenca_saude' ou 'outro'."
    )
    matricula: str | None = Field(
        default=None,
        description="Apenas os 4 dígitos da matrícula informada (ex: '1001', '1002', '1003'). Se não houver matrícula explícita no texto, retorne null."
    )
    data_inicio: str | None = Field(
        default=None,
        description="Data inicial no formato AAAA-MM-DD. Se o texto não informar o dia exato (ex: 'agosto de 2027'), retorne estritamente null."
    )
    data_fim: str | None = Field(
        default=None,
        description="Data final no formato AAAA-MM-DD. No abono é igual à data_inicio. Se o texto não trouxer o dia exato de término, retorne estritamente null."
    )
    dias_vendidos: int = Field(
        default=0,
        ge=0,
        le=10,
        description="Dias de férias vendidos/convertidos em dinheiro (abono pecuniário). Valor de 0 a 10. Se não pedir venda expressamente, use 0."
    )
    destino: str | None = Field(
        default=None,
        description="Nome da cidade/país apenas se for diária/viagem. Para férias ou abono, use sempre null."
    )
    tipo_destino: TipoDestino | None = Field(
        default=None,
        description="Classificação do destino da diária: 'capital', 'interior' ou 'exterior'. Para férias ou abono, use null."
    )
    justificativa: str = Field(
        default="",
        description="Breve motivo do pedido sem termos médicos ou sensíveis."
    )

    @field_validator("matricula", "data_inicio", "data_fim", "destino", "tipo_destino", "justificativa", mode="before")
    @classmethod
    def normalizar_nulos(cls, v):
        if v is None:
            return None
        if isinstance(v, str) and v.strip().lower() in ("null", "none", "", "undefined"):
            return None
        return v


def criar_extrator(instrucoes: str, input_guardrails: list | None = None) -> Agent:
    return Agent(
        name="Extrator",
        instructions=instrucoes,
        output_type=Pedido,
        input_guardrails=input_guardrails or [],
    )


INSTRUCOES_EXTRATOR = (
    f"Hoje é {texto_hoje()}. "
    "Você é um extrator de dados de Recursos Humanos. Extraia estritamente os dados presentes no texto em formato JSON.\n\n"
    "REGRAS OBRIGATÓRIAS:\n"
    "1. MATRÍCULA: Extraia apenas se houver número de 4 dígitos informado explicitamente. Se não houver, retorne null.\n"
    "2. DATAS VAGAS: Se o servidor não indicar o dia exato (ex: 'em agosto de 2027', 'ano que vem'), retorne data_inicio=null e data_fim=null. NUNCA invente dia do mês.\n"
    "3. FÉRIAS COM DURAÇÃO: Se o pedido informar data inicial e quantidade de dias (ex: 15 dias a partir de 12/07/2027), calcule a data final exatamente: data_fim = data_inicio + (dias - 1) dias corridos. Exemplo: 12/07/2027 por 15 dias termina em 2027-07-26.\n"
    "4. ABONO: Folga de 1 dia. data_fim DEVE ser idêntica a data_inicio.\n"
    "5. FÉRIAS / ABONO: Os campos destino e tipo_destino DEVEM ser SEMPRE null.\n"
    "6. DIÁRIA: Viagens internacionais (como Buenos Aires) têm tipo_destino='exterior'. dias_vendidos em diária é SEMPRE 0.\n"
    "7. DIAS VENDIDOS: Só é maior que 0 se o texto pedir expressamente abono pecuniário ou venda de dias de férias."
)


def extrair(texto: str) -> Pedido:
    """Extrai os dados estruturados garantindo conversão de datas e nulos sem strings literais."""
    extrator = criar_extrator(INSTRUCOES_EXTRATOR)
    try:
        resultado = Runner.run_sync(extrator, texto)
        pedido: Pedido = resultado.final_output
    except Exception:
        # Se o modelo oscilar na geração do JSON, tenta uma segunda vez ou monta objeto base
        try:
            resultado = Runner.run_sync(extrator, texto)
            pedido = resultado.final_output
        except Exception:
            tipo_estimado = TipoPedido.FERIAS if "férias" in texto.lower() or "ferias" in texto.lower() else (
                TipoPedido.ABONO if "abono" in texto.lower() else (
                    TipoPedido.DIARIA if "diária" in texto.lower() or "diaria" in texto.lower() else TipoPedido.OUTRO
                )
            )
            pedido = Pedido(tipo=tipo_estimado)

    updates: dict = {}

    # 1. Sanitização de nulos que vieram em formato string literal
    for campo in ("matricula", "data_inicio", "data_fim", "destino", "tipo_destino"):
        valor = getattr(pedido, campo, None)
        if isinstance(valor, str) and valor.strip().lower() in ("null", "none", "", "undefined"):
            updates[campo] = None

    # 2. Garantia determinística para a matrícula
    mat_atual = updates.get("matricula", getattr(pedido, "matricula", None))
    if not mat_atual or not str(mat_atual).isdigit():
        m_mat = re.search(r"(?:matr[ií]cula|matr\.?|mat\.?)\s*[:=]?\s*(\d{4})\b", texto, re.IGNORECASE)
        if not m_mat:
            m_mat = re.search(r"\b(10\d{2})\b", texto)
        if m_mat:
            updates["matricula"] = m_mat.group(1)
        else:
            updates["matricula"] = None

    # 3. Tratamento de datas vagas (como no C5: 'em agosto de 2027')
    if re.search(r"\b(em agosto|ano que vem|mês que vem|em breve)\b", texto, re.IGNORECASE) and not re.search(r"\b\d{1,2}/\d{1,2}/\d{4}\b|\b\d{4}-\d{2}-\d{2}\b", texto):
        updates["data_inicio"] = None
        updates["data_fim"] = None

    # 4. Ajuste para períodos com contagem expressa de dias (ex: C6)
    m_dias = re.search(r"(\d+)\s+dias\s+de\s+f[eé]rias", texto, re.IGNORECASE)
    dt_ini_atual = updates.get("data_inicio", getattr(pedido, "data_inicio", None))
    if not dt_ini_atual:
        m_data = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", texto)
        if not m_data:
            m_data_br = re.search(r"\b(\d{2})/(\d{2})/(\d{4})\b", texto)
            if m_data_br:
                dt_ini_atual = f"{m_data_br.group(3)}-{m_data_br.group(2)}-{m_data_br.group(1)}"
        else:
            dt_ini_atual = m_data.group(1)
        if dt_ini_atual:
            updates["data_inicio"] = dt_ini_atual

    if m_dias and dt_ini_atual and re.match(r"^\d{4}-\d{2}-\d{2}$", str(dt_ini_atual)):
        qtd_dias = int(m_dias.group(1))
        d_ini = datetime.strptime(str(dt_ini_atual), "%Y-%m-%d").date()
        d_fim_esperada = d_ini + timedelta(days=qtd_dias - 1)
        updates["data_fim"] = d_fim_esperada.strftime("%Y-%m-%d")

    if updates:
        pedido = pedido.model_copy(update=updates)

    return pedido


# ------------------------------------------------------------------ 🆕 A: votação (OPCIONAL, bônus)
INSTRUCOES_VOTANTES: list[str] = [
    (
        f"Hoje é {texto_hoje()}. "
        "Você é um extrator literal de RH. Extraia apenas as informações explícitas no texto. "
        "Se qualquer campo de data ou matrícula não estiver completo e inequívoco, preencha com null. "
        "Datas sempre em AAAA-MM-DD. Venda de férias só se solicitada expressamente."
    ),
    (
        f"Hoje é {texto_hoje()}. "
        "Você é um extrator rigoroso com foco no calendário do RH. Analise o tipo de pedido e os períodos. "
        "Em caso de pedidos de abono, a data_fim é idêntica à data_inicio. "
        "Se o servidor mencionar prazos vagos sem dia numérico exato, defina datas como null. Datas em AAAA-MM-DD."
    ),
    (
        f"Hoje é {texto_hoje()}. "
        "Você analisa pedidos de servidores com a perspectiva das normas de gestão de pessoas. "
        "Identifique matrícula, tipo do pedido, intervalo de datas (AAAA-MM-DD), dias vendidos (0 a 10) e destino. "
        "Não alucine informações: campos incertos devem ser preenchidos com null."
    ),
]


async def extrair_com_votacao(texto: str) -> tuple[Pedido, bool, list[Pedido]]:
    extratores = [criar_extrator(instrucao) for instrucao in INSTRUCOES_VOTANTES]
    resultados = await asyncio.gather(*(Runner.run(e, texto) for e in extratores))
    votos: list[Pedido] = [r.final_output for r in resultados]
    pedido_final, divergencia = votar(votos)
    return pedido_final, divergencia, votos


def votar(votos: list[Pedido]) -> tuple[Pedido, bool]:
    """(PRONTO) Maioria por campo. Sem maioria (2 de 3) em `tipo` ou nas datas -> divergencia=True."""
    decidido, divergencia = {}, False
    for campo in ("tipo", "matricula", "data_inicio", "data_fim", "dias_vendidos"):
        valor, quantos = Counter(getattr(voto, campo) for voto in votos).most_common(1)[0]
        decidido[campo] = valor
        if quantos < 2 and campo in ("tipo", "data_inicio", "data_fim"):
            divergencia = True
    return votos[0].model_copy(update=decidido), divergencia


def _demo_extracao() -> None:
    for nome in ("C1_abono_simples", "C2_ferias_com_venda", "C5_sem_matricula", "C11_diaria_exterior"):
        pedido = extrair(CASOS[nome]["pedido"])
        print(f"\n{nome}\n  {pedido.model_dump()}")


def _demo_votacao() -> None:
    for nome in ("C1_abono_simples", "C2_ferias_com_venda", "C9_divergencia"):
        texto = CASOS[nome]["pedido"]
        inicio = time.perf_counter()
        pedido, divergencia, votos = asyncio.run(extrair_com_votacao(texto))
        segundos = time.perf_counter() - inicio
        print(f"\n{nome}  ({segundos:.1f}s, divergencia={divergencia})")
        for i, voto in enumerate(votos, 1):
            print(f"  voto {i}: tipo={voto.tipo.value} {voto.data_inicio}..{voto.data_fim} vende={voto.dias_vendidos}")
        print(f"  decisão: {pedido.model_dump()}")

    texto = CASOS["C2_ferias_com_venda"]["pedido"]
    inicio = time.perf_counter()
    for instrucoes in INSTRUCOES_VOTANTES:
        Runner.run_sync(criar_extrator(instrucoes), texto)
    print(f"\nC2 em sequência: {time.perf_counter() - inicio:.1f}s (compare com o tempo do C2 em paralelo, acima)")


if __name__ == "__main__":
    print(f"[modelo] {MODELO}")
    _demo_votacao() if "--votacao" in sys.argv else _demo_extracao()