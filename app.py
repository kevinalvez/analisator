from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from data_loader import IDADES, INTERACOES, ORIGENS, ROTULOS, ler_arquivo, preparar

st.set_page_config(page_title="Instagram · Métricas", page_icon="📊", layout="wide")

# Paleta categórica validada (ordem fixa; a cor segue a entidade, não o ranking)
PALETA = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
SEQUENCIAL = ["#cde2fb", "#86b6ef", "#3987e5", "#256abf", "#184f95", "#0d366b"]
EXEMPLO = Path(__file__).parent / "csv" / "insta.xlsx"


def cores_para(valores) -> dict:
    """Mapa estável valor -> cor (ordem alfabética); acima de 8 vira cinza."""
    return {v: (PALETA[i] if i < len(PALETA) else "#8a8984") for i, v in enumerate(sorted(set(valores)))}


def estilo(fig, altura=380, legenda=True):
    fig.update_layout(
        height=altura,
        margin=dict(l=8, r=8, t=40, b=8),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, title=None) if legenda else None,
        showlegend=legenda,
        bargap=0.25,
        hoverlabel=dict(namelength=-1),
    )
    fig.update_traces(selector=dict(type="bar"), marker_line_width=0, marker_cornerradius=4)
    fig.update_xaxes(showgrid=False, title=None)
    fig.update_yaxes(gridcolor="rgba(128,128,128,0.15)", title=None)
    return fig


def mostrar(fig):
    st.plotly_chart(fig, width="stretch", theme="streamlit")


def pct(v):
    return "–" if pd.isna(v) else f"{v:.1%}".replace(".", ",")


def num(v):
    return "–" if pd.isna(v) else f"{v:,.0f}".replace(",", ".")


@st.cache_data(show_spinner=False)
def carregar(conteudo: bytes, nome: str) -> pd.DataFrame:
    return preparar(ler_arquivo(conteudo, nome))


# ---------------------------------------------------------------- dados
st.sidebar.header("📁 Dados")
arquivo = st.sidebar.file_uploader(
    "Suba o CSV/XLSX atualizado do formulário", type=["csv", "xlsx"],
    help="Export do Google Forms/Sheets (Arquivo › Fazer download › CSV ou XLSX).",
)
if arquivo is not None:
    conteudo, nome = arquivo.getvalue(), arquivo.name
elif EXEMPLO.exists():
    conteudo, nome = EXEMPLO.read_bytes(), EXEMPLO.name
    st.sidebar.caption(f"Usando arquivo local: `{EXEMPLO.name}`")
else:
    st.title("📊 Métricas do Instagram")
    st.info("Suba o CSV ou XLSX com as respostas do formulário na barra lateral para começar.")
    st.stop()

try:
    base = carregar(conteudo, nome)
except Exception as erro:  # noqa: BLE001
    st.error(f"Não consegui ler o arquivo: {erro}")
    st.stop()

if base.empty:
    st.warning("O arquivo não tem publicações válidas (com data e visualizações).")
    st.stop()

COR_TAG = cores_para(base["tag"])
COR_TIPO = cores_para(base["tipo"])

# ---------------------------------------------------------------- filtros
st.sidebar.header("🔎 Filtros")
dmin, dmax = base["data"].min().date(), base["data"].max().date()
periodo = st.sidebar.date_input("Período de publicação", (dmin, dmax), min_value=dmin, max_value=dmax, format="DD/MM/YYYY")
tags = st.sidebar.multiselect("TAG", sorted(base["tag"].unique()), default=sorted(base["tag"].unique()))
tipos = st.sidebar.multiselect("Tipo de conteúdo", sorted(base["tipo"].unique()), default=sorted(base["tipo"].unique()))

ini, fim = (periodo if isinstance(periodo, tuple) and len(periodo) == 2 else (dmin, dmax))
df = base[
    base["data"].dt.date.between(ini, fim) & base["tag"].isin(tags) & base["tipo"].isin(tipos)
].copy()

st.title("📊 Métricas do Instagram")
st.caption(f"{len(df)} publicações · {ini:%d/%m/%Y} a {fim:%d/%m/%Y}")
if df.empty:
    st.warning("Nenhuma publicação com os filtros atuais.")
    st.stop()


def resumo(grupo: str) -> pd.DataFrame:
    """Agrega por dimensão; taxas são ponderadas (soma/soma), não média de médias."""
    g = df.groupby(grupo).agg(
        posts=("visualizacoes", "size"),
        visualizacoes=("visualizacoes", "sum"),
        media_views=("visualizacoes", "mean"),
        visualizadores=("visualizadores", "sum"),
        interacoes=("interacoes", "sum"),
        compartilhamentos=("compartilhamentos", "sum"),
        salvamentos=("salvamentos", "sum"),
        visitas_perfil=("visitas_perfil", "sum"),
        cliques_link=("cliques_link", "sum"),
        novos_seguidores=("novos_seguidores", "sum"),
        nota_media=("nota", "mean"),
    )
    g["taxa_engajamento"] = g["interacoes"] / g["visualizadores"]
    g["taxa_compartilhamento"] = g["compartilhamentos"] / g["visualizadores"]
    g["taxa_visita_perfil"] = g["visitas_perfil"] / g["visualizadores"]
    g["conversao_seguidor"] = g["novos_seguidores"] / g["visitas_perfil"].where(g["visitas_perfil"] > 0)
    g["seguidores_por_mil"] = g["novos_seguidores"] / g["visualizadores"] * 1000
    return g.reset_index().sort_values("visualizacoes", ascending=False)


def media_ponderada(cols, grupo=None):
    """Média de colunas percentuais ponderada pelas visualizações de cada post."""
    d = df.dropna(subset=cols, how="all")
    pesos = d["visualizacoes"]
    if grupo is None:
        return (d[cols].mul(pesos, axis=0).sum() / pesos.sum()).rename(index=ROTULOS)
    out = d[cols].mul(pesos, axis=0).groupby(d[grupo]).sum().div(pesos.groupby(d[grupo]).sum(), axis=0)
    return out.rename(columns=ROTULOS)


# ---------------------------------------------------------------- KPIs
k = st.columns(6)
k[0].metric("Publicações", len(df))
k[1].metric("Visualizações", num(df["visualizacoes"].sum()), help="Soma das visualizações dos posts")
k[2].metric("Visualizadores", num(df["visualizadores"].sum()), help="Contas únicas por post (somadas entre posts)")
k[3].metric("Interações", num(df["interacoes"].sum()), help="Curtidas + comentários + reposts + compartilhamentos + salvamentos")
k[4].metric("Taxa de engajamento", pct(df["interacoes"].sum() / df["visualizadores"].sum()), help="Interações ÷ visualizadores")
k[5].metric("Novos seguidores", num(df["novos_seguidores"].sum()))

abas = st.tabs(["Visão geral", "Por TAG", "Formato", "Descoberta", "Audiência", "Conversão", "Avaliação interna", "Reels", "Dados"])

# ---------------------------------------------------------------- Visão geral
with abas[0]:
    c1, c2 = st.columns([3, 2])
    with c1:
        fig = px.bar(
            df, x="data", y="visualizacoes", color="tag", color_discrete_map=COR_TAG,
            hover_data={"titulo": True, "tipo": True, "data": "|%d/%m/%Y", "visualizacoes": ":,.0f", "tag": False},
            labels={"visualizacoes": "Visualizações", "data": "Publicação", "titulo": "Título", "tipo": "Tipo"},
            title="Visualizações por publicação",
        )
        fig.update_xaxes(tickformat="%d/%m")
        mostrar(estilo(fig))
    with c2:
        top = df.nlargest(10, "visualizacoes").sort_values("visualizacoes")
        fig = px.bar(
            top, x="visualizacoes", y="rotulo", orientation="h", color="tag", color_discrete_map=COR_TAG,
            text="visualizacoes", title="Top 10 em visualizações",
            hover_data={"rotulo": False, "tipo": True, "taxa_engajamento": ":.1%"},
            labels={"visualizacoes": "Visualizações", "tipo": "Tipo", "taxa_engajamento": "Engajamento"},
        )
        fig.update_traces(texttemplate="%{text:,.0f}", textposition="outside", cliponaxis=False)
        fig.update_yaxes(categoryorder="total ascending")
        mostrar(estilo(fig, legenda=False))

    st.subheader("Ranking das publicações")
    ranking = df.sort_values("visualizacoes", ascending=False)[
        ["data", "tag", "tipo", "titulo", "visualizacoes", "visualizadores", "interacoes",
         "taxa_engajamento", "compartilhamentos", "salvamentos", "novos_seguidores", "nota", "url"]
    ]
    st.dataframe(
        ranking, hide_index=True, width="stretch",
        column_config={
            "data": st.column_config.DateColumn("Data", format="DD/MM/YYYY"),
            "tag": "TAG", "tipo": "Tipo", "titulo": st.column_config.TextColumn("Título", width="large"),
            "visualizacoes": st.column_config.NumberColumn("Views", format="localized"),
            "visualizadores": st.column_config.NumberColumn("Visualizadores", format="localized"),
            "interacoes": st.column_config.NumberColumn("Interações", format="localized"),
            "taxa_engajamento": st.column_config.ProgressColumn(
                "Engajamento", format="percent", min_value=0, max_value=float(max(df["taxa_engajamento"].max(), 0.01))),
            "compartilhamentos": "Compart.", "salvamentos": "Salv.", "novos_seguidores": "Seguidores",
            "nota": st.column_config.NumberColumn("Nota", format="%d ⭐"),
            "url": st.column_config.LinkColumn("Link", display_text="abrir"),
        },
    )

# ---------------------------------------------------------------- Por TAG
with abas[1]:
    rt = resumo("tag")
    c1, c2, c3 = st.columns(3)
    with c1:
        fig = px.bar(rt, x="tag", y="visualizacoes", color="tag", color_discrete_map=COR_TAG, text="visualizacoes",
                     title="Visualizações totais", hover_data={"posts": True, "media_views": ":,.0f"},
                     labels={"posts": "Posts", "media_views": "Média por post", "visualizacoes": "Views"})
        fig.update_traces(texttemplate="%{text:,.0f}", textposition="outside", cliponaxis=False)
        mostrar(estilo(fig, legenda=False))
    with c2:
        fig = px.bar(rt, x="tag", y="media_views", color="tag", color_discrete_map=COR_TAG, text="media_views",
                     title="Média de visualizações por post", labels={"media_views": "Média"})
        fig.update_traces(texttemplate="%{text:,.0f}", textposition="outside", cliponaxis=False)
        mostrar(estilo(fig, legenda=False))
    with c3:
        fig = px.bar(rt, x="tag", y="taxa_engajamento", color="tag", color_discrete_map=COR_TAG, text="taxa_engajamento",
                     title="Taxa de engajamento (ponderada)", labels={"taxa_engajamento": "Engajamento"})
        fig.update_traces(texttemplate="%{text:.1%}", textposition="outside", cliponaxis=False)
        fig.update_yaxes(tickformat=".0%")
        mostrar(estilo(fig, legenda=False))

    c1, c2 = st.columns(2)
    with c1:
        mix = df.groupby("tag")[INTERACOES].sum()
        mix = mix.div(mix.sum(axis=1), axis=0).rename(columns=ROTULOS).reset_index().melt("tag", var_name="Interação", value_name="Participação")
        fig = px.bar(mix, x="Participação", y="tag", color="Interação", orientation="h", barmode="stack",
                     color_discrete_sequence=PALETA, title="Composição das interações por TAG")
        fig.update_xaxes(tickformat=".0%")
        fig.update_traces(hovertemplate="%{fullData.name}: %{x:.1%}<extra></extra>")
        mostrar(estilo(fig))
    with c2:
        cruz = df.pivot_table(index="tag", columns="tipo", values="visualizacoes", aggfunc="mean")
        cont = df.pivot_table(index="tag", columns="tipo", values="visualizacoes", aggfunc="size")
        fig = go.Figure(go.Heatmap(
            z=cruz.values, x=cruz.columns, y=cruz.index, colorscale=SEQUENCIAL, xgap=2, ygap=2,
            text=[[("" if pd.isna(v) else f"{v:,.0f}".replace(",", ".") + f"<br>({int(n)} post{'s' if n > 1 else ''})")
                   for v, n in zip(lv, ln)] for lv, ln in zip(cruz.values, cont.fillna(0).values)],
            texttemplate="%{text}", hovertemplate="%{y} · %{x}<br>Média de views: %{z:,.0f}<extra></extra>",
            colorbar=dict(title="Média views"),
        ))
        fig.update_layout(title="Média de visualizações: TAG × formato")
        mostrar(estilo(fig, legenda=False))

    st.subheader("Tabela comparativa por TAG")
    st.dataframe(
        rt[["tag", "posts", "visualizacoes", "media_views", "taxa_engajamento", "taxa_compartilhamento",
            "taxa_visita_perfil", "novos_seguidores", "seguidores_por_mil", "cliques_link", "nota_media"]],
        hide_index=True, width="stretch",
        column_config={
            "tag": "TAG", "posts": "Posts",
            "visualizacoes": st.column_config.NumberColumn("Views", format="localized"),
            "media_views": st.column_config.NumberColumn("Média views", format="localized"),
            "taxa_engajamento": st.column_config.NumberColumn("Engajamento", format="percent"),
            "taxa_compartilhamento": st.column_config.NumberColumn("Compart./visualiz.", format="percent"),
            "taxa_visita_perfil": st.column_config.NumberColumn("Visita perfil", format="percent"),
            "novos_seguidores": "Seguidores",
            "seguidores_por_mil": st.column_config.NumberColumn("Seg. / mil visualiz.", format="%.1f"),
            "cliques_link": "Cliques link bio",
            "nota_media": st.column_config.NumberColumn("Nota média", format="%.1f"),
        },
    )

# ---------------------------------------------------------------- Formato
with abas[2]:
    rf = resumo("tipo")
    c1, c2 = st.columns(2)
    with c1:
        fig = px.bar(rf, x="tipo", y="media_views", color="tipo", color_discrete_map=COR_TIPO, text="media_views",
                     hover_data={"posts": True}, title="Média de visualizações por formato",
                     labels={"media_views": "Média", "posts": "Posts"})
        fig.update_traces(texttemplate="%{text:,.0f}", textposition="outside", cliponaxis=False)
        mostrar(estilo(fig, legenda=False))
    with c2:
        fig = px.bar(rf, x="tipo", y="taxa_engajamento", color="tipo", color_discrete_map=COR_TIPO, text="taxa_engajamento",
                     title="Taxa de engajamento por formato", labels={"taxa_engajamento": "Engajamento"})
        fig.update_traces(texttemplate="%{text:.1%}", textposition="outside", cliponaxis=False)
        fig.update_yaxes(tickformat=".0%")
        mostrar(estilo(fig, legenda=False))

    fig = px.scatter(
        df, x="visualizacoes", y="taxa_engajamento", color="tag", symbol="tipo", color_discrete_map=COR_TAG,
        size="novos_seguidores", size_max=36, hover_name="titulo",
        hover_data={"tipo": True, "novos_seguidores": True, "visualizacoes": ":,.0f", "taxa_engajamento": ":.1%"},
        labels={"visualizacoes": "Visualizações", "taxa_engajamento": "Engajamento", "novos_seguidores": "Novos seguidores",
                "tipo": "Formato", "tag": "TAG"},
        title="Alcance × engajamento (tamanho = novos seguidores)",
    )
    fig.update_traces(marker=dict(line=dict(width=2, color="rgba(255,255,255,0.9)"), sizemin=8))
    fig.update_yaxes(tickformat=".0%")
    fig.add_hline(y=df["interacoes"].sum() / df["visualizadores"].sum(), line_dash="dot", line_color="#8a8984",
                  annotation_text="média geral", annotation_position="top left")
    mostrar(estilo(fig, altura=440))
    st.caption("Posts acima da linha engajam mais que a média; à direita, alcançam mais. O ideal é o quadrante superior direito.")

# ---------------------------------------------------------------- Descoberta
with abas[3]:
    st.markdown("De onde vieram as visualizações e quanto do público já seguia o perfil.")
    c1, c2 = st.columns(2)
    with c1:
        orig = media_ponderada(ORIGENS, "tag").reset_index().melt("tag", var_name="Origem", value_name="Participação")
        fig = px.bar(orig, x="Participação", y="tag", color="Origem", orientation="h", color_discrete_sequence=PALETA,
                     title="Origem das visualizações por TAG")
        fig.update_xaxes(tickformat=".0%")
        fig.update_traces(hovertemplate="%{fullData.name}: %{x:.1%}<extra></extra>")
        mostrar(estilo(fig))
    with c2:
        orig = media_ponderada(ORIGENS, "tipo").reset_index().melt("tipo", var_name="Origem", value_name="Participação")
        fig = px.bar(orig, x="Participação", y="tipo", color="Origem", orientation="h", color_discrete_sequence=PALETA,
                     title="Origem das visualizações por formato")
        fig.update_xaxes(tickformat=".0%")
        fig.update_traces(hovertemplate="%{fullData.name}: %{x:.1%}<extra></extra>")
        mostrar(estilo(fig))

    seg = df[["rotulo", "tag", "pct_seguidores", "pct_nao_seguidores"]].dropna().sort_values("pct_nao_seguidores")
    seg = seg.rename(columns={"pct_seguidores": "Seguidores", "pct_nao_seguidores": "Não seguidores"})
    fig = px.bar(seg, x=["Não seguidores", "Seguidores"], y="rotulo", orientation="h",
                 color_discrete_sequence=[PALETA[1], PALETA[0]], hover_data={"tag": True},
                 title="Público por publicação: seguidores × não seguidores (quanto mais laranja, mais o post furou a bolha)")
    fig.update_xaxes(tickformat=".0%")
    fig.update_traces(hovertemplate="%{fullData.name}: %{x:.1%}<extra></extra>")
    mostrar(estilo(fig, altura=max(320, 36 * len(seg) + 80)))

# ---------------------------------------------------------------- Audiência
with abas[4]:
    c1, c2 = st.columns([2, 3])
    with c1:
        idade = media_ponderada(IDADES).reset_index()
        idade.columns = ["Faixa", "Participação"]
        fig = px.bar(idade, x="Faixa", y="Participação", text="Participação", title="Faixa etária (média ponderada por views)",
                     color_discrete_sequence=[PALETA[0]])
        fig.update_traces(texttemplate="%{text:.0%}", textposition="outside", cliponaxis=False)
        fig.update_yaxes(tickformat=".0%")
        mostrar(estilo(fig, legenda=False))
    with c2:
        it = media_ponderada(IDADES, "tag")
        fig = go.Figure(go.Heatmap(
            z=it.values, x=it.columns, y=it.index, colorscale=SEQUENCIAL, xgap=2, ygap=2,
            text=[[f"{v:.0%}" for v in linha] for linha in it.values], texttemplate="%{text}",
            hovertemplate="%{y} · %{x}: %{z:.1%}<extra></extra>", colorbar=dict(tickformat=".0%"),
        ))
        fig.update_layout(title="Faixa etária por TAG")
        mostrar(estilo(fig, legenda=False))

# ---------------------------------------------------------------- Conversão
with abas[5]:
    st.markdown("Quanto cada post levou as pessoas a **visitar o perfil**, **clicar no link da bio** e **seguir**.")
    c1, c2 = st.columns(2)
    with c1:
        tot = df[["visualizadores", "visitas_perfil", "novos_seguidores"]].sum()
        fig = go.Figure(go.Funnel(
            y=["Visualizadores", "Visitas ao perfil", "Novos seguidores"], x=tot.values,
            marker=dict(color=[SEQUENCIAL[2], SEQUENCIAL[3], SEQUENCIAL[4]]),
            textinfo="value+percent initial",
        ))
        fig.update_layout(title="Funil geral")
        mostrar(estilo(fig, legenda=False))
    with c2:
        rt = resumo("tag")
        fig = px.bar(rt, x="tag", y="seguidores_por_mil", color="tag", color_discrete_map=COR_TAG, text="seguidores_por_mil",
                     title="Novos seguidores a cada mil visualizadores", labels={"seguidores_por_mil": "Seg./mil"})
        fig.update_traces(texttemplate="%{text:.1f}", textposition="outside", cliponaxis=False)
        mostrar(estilo(fig, legenda=False))

    conv = df.sort_values("novos_seguidores", ascending=False)[
        ["data", "tag", "titulo", "visualizadores", "visitas_perfil", "taxa_visita_perfil", "cliques_link",
         "novos_seguidores", "conversao_seguidor"]]
    st.dataframe(conv, hide_index=True, width="stretch", column_config={
        "data": st.column_config.DateColumn("Data", format="DD/MM/YYYY"), "tag": "TAG", "titulo": "Título",
        "visualizadores": st.column_config.NumberColumn("Visualizadores", format="localized"),
        "visitas_perfil": "Visitas perfil",
        "taxa_visita_perfil": st.column_config.NumberColumn("Visita/visualiz.", format="percent"),
        "cliques_link": "Cliques link bio", "novos_seguidores": "Seguidores",
        "conversao_seguidor": st.column_config.NumberColumn("Seguiu/visitou", format="percent"),
    })

# ---------------------------------------------------------------- Avaliação interna
with abas[6]:
    st.markdown("A nota dada pela equipe (1 a 5) conversa com os números? Cada ponto é uma publicação.")
    metrica = st.selectbox("Comparar a nota com", list({
        "visualizacoes": "Visualizações", "taxa_engajamento": "Taxa de engajamento",
        "novos_seguidores": "Novos seguidores", "taxa_compartilhamento": "Taxa de compartilhamento",
    }.items()), format_func=lambda x: x[1])
    col, nome_m = metrica
    fig = px.strip(df, x="nota", y=col, color="tag", color_discrete_map=COR_TAG, hover_name="titulo",
                   labels={"nota": "Nota da equipe", col: nome_m, "tag": "TAG"}, title=f"Nota × {nome_m}")
    fig.update_traces(marker=dict(size=12, line=dict(width=2, color="rgba(255,255,255,0.9)")))
    fig.update_xaxes(dtick=1, range=[0.5, 5.5])
    if col.startswith("taxa"):
        fig.update_yaxes(tickformat=".1%")
    mostrar(estilo(fig, altura=420))
    if df["nota"].nunique() > 1 and len(df) >= 4:
        corr = df[["nota", "visualizacoes", "taxa_engajamento", "novos_seguidores", "taxa_compartilhamento"]].corr(method="spearman")["nota"].drop("nota")
        st.caption("Correlação de Spearman com a nota (−1 a 1): " + " · ".join(
            f"{ {'visualizacoes': 'views', 'taxa_engajamento': 'engajamento', 'novos_seguidores': 'seguidores', 'taxa_compartilhamento': 'compartilhamento'}[k] } {v:+.2f}"
            for k, v in corr.items()) + f". Com {len(df)} posts, trate como indício, não conclusão.")

# ---------------------------------------------------------------- Reels
with abas[7]:
    reels = df[df["tipo"].str.contains("reel|v[ií]deo", case=False, regex=True)]
    if reels.empty:
        st.info("Nenhum Reels/vídeo no filtro atual.")
    else:
        r = st.columns(4)
        r[0].metric("Reels/vídeos", len(reels))
        r[1].metric("Média de views", num(reels["visualizacoes"].mean()))
        pulados = reels["reels_pulados"].where(reels["reels_pulados"] > 0) if "reels_pulados" in reels else pd.Series(dtype=float)
        r[2].metric("Taxa média pulados", pct(pulados.mean()), help="Só posts com o campo preenchido")
        tm = reels.get("tempo_medio_s", pd.Series(dtype=float)).dropna()
        r[3].metric("Tempo médio de visualização", "–" if tm.empty else f"{tm.mean():.0f}s")
        faltando = pulados.isna().sum()
        if faltando:
            st.warning(f"{faltando} de {len(reels)} vídeos estão sem taxa de pulados / tempo de visualização no formulário.")
        st.dataframe(reels[["data", "tag", "titulo", "visualizacoes", "taxa_engajamento", "reels_pulados", "tempo_medio", "tempo_total"]],
                     hide_index=True, width="stretch", column_config={
                         "data": st.column_config.DateColumn("Data", format="DD/MM/YYYY"), "tag": "TAG", "titulo": "Título",
                         "visualizacoes": st.column_config.NumberColumn("Views", format="localized"),
                         "taxa_engajamento": st.column_config.NumberColumn("Engajamento", format="percent"),
                         "reels_pulados": st.column_config.NumberColumn("Pulados", format="percent"),
                         "tempo_medio": "Tempo médio", "tempo_total": "Tempo total"})

# ---------------------------------------------------------------- Dados
with abas[8]:
    avisos = []
    for campo, nome_c in [("alcance", "Alcance"), ("engajamento_form", "Engajamento"), ("impressoes", "Impressão")]:
        if campo in df and (df[campo].fillna(0) == 0).mean() > 0.5:
            avisos.append(nome_c)
    if avisos:
        st.info(f"Os campos **{', '.join(avisos)}** estão zerados na maioria das linhas, então o painel usa "
                "*Visualizadores* como alcance e calcula o engajamento a partir das interações.")
    duplicados = base.attrs.get("duplicados", 0)
    if duplicados:
        st.info(f"{duplicados} respostas duplicadas para o mesmo link foram descartadas (mantida a mais recente).")
    st.dataframe(df, width="stretch", hide_index=True)
    st.download_button("⬇️ Baixar dados tratados (CSV)", df.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig"),
                       file_name="instagram_tratado.csv", mime="text/csv")
