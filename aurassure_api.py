"""
aurassure_api.py
================
Cliente HTTP para a plataforma Aurassure IoT.

Endpoints descobertos via DevTools (Network tab):
  Login:    POST  /accounts/login           → retorna auth_token no body
  Locais:   GET   /clients/{cid}/applications/{aid}/things/list   → {"things": [...]}
  Dados:    POST  /clients/{cid}/applications/{aid}/things/data
"""

import requests
import logging
import json
import os
import time
import calendar
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from dataclasses import dataclass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("aurassure_api")

# ─────────────────────────────────────────────
# Constantes
# ─────────────────────────────────────────────
LOGIN_URL      = "https://app.aurassure.com/-/api/iot-platform/v1.1.0/accounts/login"
BASE_URL       = "https://app.aurassure.com/-/api/iot-platform/v1.1.0"
CLIENT_ID      = int(os.getenv("AURASSURE_CLIENT_ID",  "17429"))
APPLICATION_ID = int(os.getenv("AURASSURE_APP_ID",     "16"))
THING_ID       = int(os.getenv("AURASSURE_THING_ID",   "28463"))
TOKEN_TTL      = int(os.getenv("AURASSURE_TOKEN_TTL",  "3300"))  # 55 min

ALL_PARAMETERS = ["aqi", "temp", "humid", "pm1", "pm2.5", "pm10", "no2", "o3", "co2", "tvoc"]
ALL_ATTRIBUTES = ["min", "max", "avg", "value", "min_at", "max_at"]

_BASE_HEADERS = {
    "Content-Type": "application/json",
    "Accept":       "application/json, text/plain, */*",
    "User-Agent":   "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Origin":       "https://app.aurassure.com",
    "Referer":      "https://app.aurassure.com/",
}


# ─────────────────────────────────────────────
# Cache de sessão  (auth_token + PHPSESSID)
# ─────────────────────────────────────────────

@dataclass
class _Sessao:
    auth_token: str  = ""
    phpsessid:  str  = ""
    client_id:  int  = 0
    user_nome:  str  = ""
    obtido_em:  float = 0.0

    def valida(self) -> bool:
        # A API da Aurassure exige os dois: auth_token + PHPSESSID.
        return (
            bool(self.auth_token)
            and bool(self.phpsessid)
            and (time.time() - self.obtido_em) < TOKEN_TTL
        )

    def salvar(self, auth_token: str, phpsessid: str, client_id: int = 0, user_nome: str = ""):
        self.auth_token = auth_token
        self.phpsessid  = phpsessid
        self.client_id  = client_id
        self.user_nome  = user_nome
        self.obtido_em  = time.time()
        logger.info("Sessão salva para '%s' (client_id=%s). Válida por ~%d min.",
                    user_nome, client_id, TOKEN_TTL // 60)

    def limpar(self):
        self.auth_token = ""
        self.phpsessid  = ""
        self.obtido_em  = 0.0


_sessao = _Sessao()


def _headers_auth() -> Dict[str, str]:
    """
    Headers autenticados.
    O Aurassure usa DOIS mecanismos simultaneamente:
      - Header  'auth_token'  com o token JWT retornado no login
      - Cookie  'PHPSESSID'   com a sessão PHP
    Ambos são necessários — confirmado via DevTools.
    """
    h = dict(_BASE_HEADERS)
    if _sessao.auth_token:
        h["auth_token"] = _sessao.auth_token
    if _sessao.phpsessid:
        h["Cookie"] = f"PHPSESSID={_sessao.phpsessid}"
    return h


# ─────────────────────────────────────────────
# Login
# ─────────────────────────────────────────────

def autenticar(email: str, senha: str) -> str:
    """
    Faz login na plataforma Aurassure.
    Extrai auth_token do body JSON e PHPSESSID do cookie Set-Cookie.
    Retorna o auth_token.
    """
    logger.info("Fazendo login: %s", email)
    payload = {
        "email_id":  email,
        "password":  senha,
        "source":    "website",
        "source_id": 1,
        "target":    "https://app.aurassure.com/",
    }
    try:
        resp = requests.post(LOGIN_URL, json=payload, headers=_BASE_HEADERS, timeout=20)
    except requests.exceptions.RequestException as exc:
        raise ErroAutenticacao(f"Erro de rede no login: {exc}") from exc

    if resp.status_code not in (200, 201):
        try:
            msg = resp.json().get("message", resp.text[:300])
        except Exception:
            msg = resp.text[:300]
        raise ErroAutenticacao(f"Login falhou (HTTP {resp.status_code}): {msg}")

    try:
        body = resp.json()
        logger.debug("Body do login: %s", json.dumps(body, indent=2, ensure_ascii=False)[:1000])
    except ValueError:
        body = {}

    def _buscar_chave(obj, nomes):
        """Procura chaves possíveis também em JSON aninhado."""
        if isinstance(obj, dict):
            for n in nomes:
                if obj.get(n):
                    return obj.get(n)
            for v in obj.values():
                achou = _buscar_chave(v, nomes)
                if achou:
                    return achou
        elif isinstance(obj, list):
            for v in obj:
                achou = _buscar_chave(v, nomes)
                if achou:
                    return achou
        return ""

    # auth_token — normalmente vem no body JSON, às vezes dentro de data/user/session.
    auth_token = str(_buscar_chave(body, ["auth_token", "session_id", "token", "access_token", "jwt"]) or "").strip()

    # PHPSESSID — normalmente vem no cookie Set-Cookie.
    phpsessid = (
        resp.cookies.get("PHPSESSID")
        or resp.cookies.get("phpsessid")
        or str(_buscar_chave(body, ["PHPSESSID", "phpsessid"]) or "").strip()
    )

    if not auth_token or not phpsessid:
        faltando = []
        if not auth_token:
            faltando.append("session_id/auth_token")
        if not phpsessid:
            faltando.append("PHPSESSID")
        raise ErroAutenticacao(
            "Login respondeu, mas faltou: " + ", ".join(faltando) + ". "
            "A API exige session_id/auth_token e PHPSESSID juntos. "
            f"Chaves recebidas no JSON: {list(body.keys())}; "
            f"cookies recebidos: {list(resp.cookies.keys())}"
        )

    cid  = body.get("client_id", 0)
    nome = str(body.get("user_name") or body.get("name") or "").strip()

    _sessao.salvar(
        auth_token=auth_token,
        phpsessid=phpsessid,
        client_id=int(cid) if cid else CLIENT_ID,
        user_nome=nome,
    )
    return auth_token


def _garantir_sessao(email: str, senha: str):
    if not _sessao.valida():
        autenticar(email, senha)


def validar_credenciais(email: str, senha: str) -> Dict[str, Any]:
    if not email or not senha:
        return {"valido": False, "mensagem": "Preencha e-mail e senha."}
    try:
        autenticar(email, senha)
        return {
            "valido": True,
            "mensagem": f"Conectado como {_sessao.user_nome or email} ✓",
        }
    except ErroAutenticacao as e:
        return {"valido": False, "mensagem": str(e)}
    except Exception as e:
        return {"valido": False, "mensagem": f"Erro inesperado: {e}"}


# ─────────────────────────────────────────────
# Listar dispositivos (things/list)
# ─────────────────────────────────────────────

def listar_dispositivos(
    email: str,
    senha: str,
    client_id: Optional[int] = None,
    application_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    Retorna os locais de monitoramento com seus nomes reais.
    Endpoint correto descoberto via DevTools:
        GET /clients/{cid}/applications/{aid}/things/list

    Retorna lista de dicts:
        [{"id": 28463, "nome": "Campus Santarém"}, ...]
    """
    _garantir_sessao(email, senha)
    cid = client_id      or _sessao.client_id or CLIENT_ID
    aid = application_id or APPLICATION_ID

    # Endpoint correto: /things/list  (não /things)
    url = f"{BASE_URL}/clients/{cid}/applications/{aid}/things/list"
    logger.info("Listando locais: GET %s", url.replace(BASE_URL, ""))

    try:
        resp = requests.get(url, headers=_headers_auth(), timeout=20)
    except requests.exceptions.RequestException as exc:
        raise ErroBuscaDados(f"Erro de rede ao listar locais: {exc}") from exc

    # Renova token em caso de 401
    if resp.status_code == 401:
        _sessao.limpar()
        autenticar(email, senha)
        cid = client_id or _sessao.client_id or CLIENT_ID
        url = f"{BASE_URL}/clients/{cid}/applications/{aid}/things/list"
        resp = requests.get(url, headers=_headers_auth(), timeout=20)

    if resp.status_code != 200:
        raise ErroBuscaDados(
            f"Listagem de locais retornou HTTP {resp.status_code}: {resp.text[:300]}"
        )

    try:
        data = resp.json()
    except ValueError:
        raise ErroBuscaDados("Resposta da listagem não é JSON válido.")

    logger.debug("Resposta /things/list: %s",
                 json.dumps(data, indent=2, ensure_ascii=False)[:2000])

    # A resposta tem a chave "things" com a lista — confirmado via DevTools
    lista = data.get("things") or []
    if not isinstance(lista, list) or not lista:
        raise ErroBuscaDados(
            f"Nenhum local encontrado. Chaves na resposta: {list(data.keys())}"
        )

    dispositivos = []
    for item in lista:
        if not isinstance(item, dict):
            continue
        tid = item.get("id") or item.get("thing_id")
        if not tid:
            continue
        nome = (
            item.get("name")
            or item.get("thing_name")
            or item.get("label")
            or item.get("description")
            or f"Dispositivo {tid}"
        )
        dispositivos.append({"id": int(tid), "nome": str(nome).strip()})

    logger.info(
        "%d local(is) encontrado(s): %s",
        len(dispositivos),
        [(d["nome"], d["id"]) for d in dispositivos],
    )
    return dispositivos


# ─────────────────────────────────────────────
# Busca de dados do sensor
# ─────────────────────────────────────────────

def buscar_dados_sensor(
    email: str,
    senha: str,
    from_time: int,
    upto_time: int,
    thing_ids: List[int],
    parametros: Optional[List[str]] = None,
    periodo_agregacao: int = 900,
    client_id: Optional[int] = None,
    application_id: Optional[int] = None,
    _tentativa: bool = True,
) -> Dict[str, Any]:
    """
    Busca dados agregados para uma lista de dispositivos.
    A API aceita múltiplos IDs no campo 'things'.
    """
    _garantir_sessao(email, senha)
    cid    = client_id      or _sessao.client_id or CLIENT_ID
    aid    = application_id or APPLICATION_ID
    params = parametros     or ALL_PARAMETERS

    endpoint = f"{BASE_URL}/clients/{cid}/applications/{aid}/things/data"
    payload  = {
        "data_type":            "aggregate",
        "aggregation_period":   periodo_agregacao,
        "parameters":           params,
        "parameter_attributes": ALL_ATTRIBUTES,
        "things":               thing_ids,
        "from_time":            from_time,
        "upto_time":            upto_time,
        "data_source":          ["processed"],
        "summarize":            [],
    }

    logger.info(
        "Buscando dados: things=%s | %s → %s",
        thing_ids,
        datetime.utcfromtimestamp(from_time).strftime("%Y-%m-%d"),
        datetime.utcfromtimestamp(upto_time).strftime("%Y-%m-%d"),
    )

    try:
        resp = requests.post(endpoint, json=payload, headers=_headers_auth(), timeout=60)
    except requests.exceptions.RequestException as exc:
        raise ErroBuscaDados(f"Erro de rede ao buscar dados: {exc}") from exc

    if resp.status_code == 401 and _tentativa:
        _sessao.limpar()
        return buscar_dados_sensor(
            email, senha, from_time, upto_time, thing_ids,
            parametros, periodo_agregacao, client_id, application_id,
            _tentativa=False,
        )

    if resp.status_code != 200:
        raise ErroBuscaDados(f"API retornou HTTP {resp.status_code}: {resp.text[:300]}")

    try:
        return resp.json()
    except ValueError:
        raise ErroBuscaDados("Resposta não é JSON válido.")


# ─────────────────────────────────────────────
# Normalização → lista de dicts para o pandas
# ─────────────────────────────────────────────

def normalizar_resposta(raw: Dict[str, Any]) -> list:
    """
    Converte resposta bruta da API em lista plana.
    Cada linha corresponde a um timestamp + dispositivo + parâmetro.
    """
    rows      = []
    registros = raw.get("data", [])

    if not isinstance(registros, list):
        logger.warning("Campo 'data' não é lista: %s", type(registros).__name__)
        return rows

    for entrada in registros:
        if not isinstance(entrada, dict):
            continue
        ts       = entrada.get("time") or entrada.get("from_time") or 0
        thing_id = str(entrada.get("thing_id", "?"))
        params   = entrada.get("parameter_values", {})
        if not isinstance(params, dict):
            continue
        for param, vals in params.items():
            if not isinstance(vals, dict):
                continue
            rows.append({
                "timestamp": datetime.fromtimestamp(ts, tz=timezone.utc).replace(tzinfo=None),
                "thing_id":  thing_id,
                "parametro": param,
                "media":     _f(vals.get("avg")   or vals.get("value")),
                "minimo":    _f(vals.get("min")),
                "maximo":    _f(vals.get("max")),
                "valor":     _f(vals.get("value") or vals.get("avg")),
            })

    logger.info("Normalizado: %d linhas de %d registros.", len(rows), len(registros))
    return rows


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def intervalo_unix_mensal(ano: int, mes: int):
    """Retorna início e fim do mês em Unix timestamp UTC."""
    _, ultimo_dia = calendar.monthrange(ano, mes)
    inicio = datetime(ano, mes, 1, 0, 0, 0, tzinfo=timezone.utc)
    fim = datetime(ano, mes, ultimo_dia, 23, 59, 59, tzinfo=timezone.utc)
    return int(inicio.timestamp()), int(fim.timestamp())


def _f(v) -> Optional[float]:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


# ─────────────────────────────────────────────
# Exceções
# ─────────────────────────────────────────────

class AurassureErro(Exception):
    pass

class ErroAutenticacao(AurassureErro):
    pass

class ErroBuscaDados(AurassureErro):
    pass


# ─────────────────────────────────────────────
# Teste rápido via terminal
# ─────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    e = os.getenv("AURASSURE_EMAIL", "")
    s = os.getenv("AURASSURE_PASSWORD", "")
    if not e:
        print("Defina AURASSURE_EMAIL e AURASSURE_PASSWORD")
        sys.exit(1)

    print("=== Login ===")
    r = validar_credenciais(e, s)
    print(r)

    print("\n=== Locais de monitoramento ===")
    for d in listar_dispositivos(e, s):
        print(f"  [{d['id']}] {d['nome']}")
