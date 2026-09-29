"""Leitura e limpeza da planilha de métricas do Instagram (export do Google Forms)."""

import io
import re
import unicodedata

import pandas as pd


def _norm(texto: str) -> str:
    """Normaliza nomes de coluna: sem acento, minúsculo, espaços simples."""
    texto = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", texto).strip().lower()


# nome normalizado da coluna na planilha -> nome interno
COLUNAS = {
    "carimbo de data/hora": "registro",
    "data da publicacao": "data",
    "tag": "tag",
    "tipo de conteudo": "tipo",
    "chapeu": "chapeu",
    "titulo": "titulo",
    "visualizacoes": "visualizacoes",
    "visualizadores": "visualizadores",
    "visitas ao perfil": "visitas_perfil",
    "toques no link da bio": "cliques_link",
    "seguidores": "novos_seguidores",
    "link": "url",
    "feed (%)": "orig_feed",
    "stories (%)": "orig_stories",
    "perfil (%)": "orig_perfil",
    "reels (%)": "orig_reels",
    "explorar (%)": "orig_explorar",
    "pesquisa (%)": "orig_pesquisa",
    "curtidas": "curtidas",
    "comentarios": "comentarios",
    "reposts": "reposts",
    "compartilhamentos": "compartilhamentos",
    "salvamentos": "salvamentos",
    "seguidores (%)": "pct_seguidores",
    "nao seguidores (%)": "pct_nao_seguidores",
    "13 - 17": "idade_13_17",
    "18 - 14": "idade_18_24",  # erro de digitação no formulário original
    "18 - 24": "idade_18_24",
    "25 - 34": "idade_25_34",
    "35 - 44": "idade_35_44",
    "45 - 54": "idade_45_54",
    "55 - 64": "idade_55_64",
    "65+": "idade_65",
    "alcance": "alcance",
    "engajamento": "engajamento_form",
    "impressao": "impressoes",
    "taxa de reels pulados (%)": "reels_pulados",
    "taxa de compartilhamentos (%)": "taxa_compart_form",
    "tempo medio de visualizacao": "tempo_medio",
    "tempo de visualizacao": "tempo_total",
}

INTEIROS = [
    "visualizacoes", "visualizadores", "visitas_perfil", "cliques_link", "novos_seguidores",
    "curtidas", "comentarios", "reposts", "compartilhamentos", "salvamentos",
    "alcance", "engajamento_form", "impressoes", "nota",
]
ORIGENS = ["orig_feed", "orig_stories", "orig_perfil", "orig_reels", "orig_explorar", "orig_pesquisa"]
IDADES = ["idade_13_17", "idade_18_24", "idade_25_34", "idade_35_44", "idade_45_54", "idade_55_64", "idade_65"]
PERCENTUAIS = ORIGENS + IDADES + ["pct_seguidores", "pct_nao_seguidores", "reels_pulados", "taxa_compart_form"]
INTERACOES = ["curtidas", "comentarios", "reposts", "compartilhamentos", "salvamentos"]

ROTULOS = {
    "orig_feed": "Feed", "orig_stories": "Stories", "orig_perfil": "Perfil",
    "orig_reels": "Reels", "orig_explorar": "Explorar", "orig_pesquisa": "Pesquisa",
    "idade_13_17": "13-17", "idade_18_24": "18-24", "idade_25_34": "25-34", "idade_35_44": "35-44",
    "idade_45_54": "45-54", "idade_55_64": "55-64", "idade_65": "65+",
    "curtidas": "Curtidas", "comentarios": "Comentários", "reposts": "Reposts",
    "compartilhamentos": "Compartilhamentos", "salvamentos": "Salvamentos",
}


def _renomear(df: pd.DataFrame) -> pd.DataFrame:
    novos = {}
    for col in df.columns:
        chave = _norm(col)
        if chave.startswith("avaliacao da performance"):
            novos[col] = "nota"
        elif chave in COLUNAS:
            novos[col] = COLUNAS[chave]
    return df.rename(columns=novos)[list(dict.fromkeys(novos.values()))]


def _para_numero(serie: pd.Series) -> pd.Series:
    """Converte textos como '1.234', '85,6%' ou '0,856' em número."""
    if pd.api.types.is_numeric_dtype(serie):
        return serie.astype(float)

    def conv(v):
        if pd.isna(v):
            return None
        s = str(v).strip().replace(" ", "")
        if s == "":
            return None
        pct = s.endswith("%")
        s = s.rstrip("%")
        if re.fullmatch(r"-?\d{1,3}(\.\d{3})+", s):  # milhar pt-BR: 15.151
            s = s.replace(".", "")
        s = s.replace(",", ".")
        try:
            n = float(s)
        except ValueError:
            return None
        return n / 100 if pct else n

    return serie.map(conv).astype(float)


def _para_segundos(v) -> float | None:
    """'10s' -> 10 ; '2:31' -> 151 ; '1:02:03' -> 3723 ; 0 -> None."""
    if pd.isna(v):
        return None
    if hasattr(v, "hour"):  # planilhas às vezes leem como datetime.time
        return v.hour * 3600 + v.minute * 60 + v.second
    s = str(v).strip().lower()
    if s in ("", "0", "0.0"):
        return None
    if s.endswith("s") and s[:-1].replace(",", ".").replace(".", "", 1).isdigit():
        return float(s[:-1].replace(",", "."))
    partes = s.split(":")
    try:
        total = 0.0
        for p in partes:
            total = total * 60 + float(p)
        return total or None
    except ValueError:
        return None


def _para_data(serie: pd.Series) -> pd.Series:
    """Aceita datas já convertidas, ISO (2026-08-31) ou brasileiras (31/08/2026)."""
    if pd.api.types.is_datetime64_any_dtype(serie):
        return serie
    texto = serie.astype(str).str.strip().str.split(" ").str[0]
    iso = pd.to_datetime(texto.where(texto.str.match(r"^\d{4}-")), format="%Y-%m-%d", errors="coerce")
    br = pd.to_datetime(texto.where(~texto.str.match(r"^\d{4}-")), dayfirst=True, errors="coerce")
    return iso.fillna(br)


def ler_arquivo(conteudo: bytes, nome: str) -> pd.DataFrame:
    """Lê CSV (vírgula ou ponto e vírgula, UTF-8 ou Latin-1) ou Excel."""
    if nome.lower().endswith((".xlsx", ".xls")):
        return pd.read_excel(io.BytesIO(conteudo))
    for enc in ("utf-8-sig", "latin-1"):
        try:
            texto = conteudo.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    return pd.read_csv(io.StringIO(texto), sep=None, engine="python")


def preparar(bruto: pd.DataFrame) -> pd.DataFrame:
    df = _renomear(bruto.copy())

    for col in INTEIROS + PERCENTUAIS:
        if col in df:
            df[col] = _para_numero(df[col])
    for col in PERCENTUAIS:
        # Se o arquivo trouxe "85,6" em vez de "0,856", reescala para fração
        if col in df and df[col].max(skipna=True) > 1.5:
            df[col] = df[col] / 100

    df["data"] = _para_data(df["data"])
    for col in ("tag", "tipo", "chapeu", "titulo"):
        if col in df:
            df[col] = df[col].fillna("(sem valor)").astype(str).str.strip()

    for col in ("tempo_medio", "tempo_total"):
        if col in df:
            df[col + "_s"] = df[col].map(_para_segundos)
            df[col] = df[col].map(lambda v: None if pd.isna(v) or str(v).strip() in ("0", "") else str(v))

    # Remove linhas sem data/visualizações e duplicatas do mesmo post
    df = df.dropna(subset=["data", "visualizacoes"])
    if "url" in df:
        df["url_base"] = df["url"].astype(str).str.replace(r"^(https?://)?(www\.)?", "", regex=True).str.split("?").str[0]
        antes = len(df)
        df = df.sort_values("registro" if "registro" in df else "data").drop_duplicates("url_base", keep="last")
        duplicados = antes - len(df)
    else:
        duplicados = 0

    # Métricas derivadas
    presentes = [c for c in INTERACOES if c in df]
    df["interacoes"] = df[presentes].fillna(0).sum(axis=1)
    base = df["visualizadores"].where(df["visualizadores"] > 0)
    df["taxa_engajamento"] = df["interacoes"] / base
    df["taxa_compartilhamento"] = df["compartilhamentos"] / base
    df["taxa_salvamento"] = df["salvamentos"] / base
    df["frequencia"] = df["visualizacoes"] / base
    df["taxa_visita_perfil"] = df["visitas_perfil"] / base
    df["conversao_seguidor"] = df["novos_seguidores"] / df["visitas_perfil"].where(df["visitas_perfil"] > 0)
    df["seguidores_por_mil"] = df["novos_seguidores"] / base * 1000
    df["dia_semana"] = df["data"].dt.dayofweek.map(dict(enumerate(["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"])))
    df["rotulo"] = df["data"].dt.strftime("%d/%m") + " · " + df["titulo"].str.slice(0, 45)

    df = df.sort_values("data").reset_index(drop=True)
    df.attrs["duplicados"] = duplicados
    return df
