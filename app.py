"""
app.py  —  Dashboard Aurassure · UFOPA
"""

import os, io, logging
from datetime import datetime
from typing import Dict, List

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from aurassure_api import (
    validar_credenciais,
    listar_dispositivos,
    buscar_dados_sensor,
    normalizar_resposta,
    intervalo_unix_mensal,
    ErroAutenticacao,
    ErroBuscaDados,
)

# ── Configuração ──────────────────────────────
st.set_page_config(page_title="Aurassure · UFOPA", page_icon="🌿", layout="wide")
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("app")

# ── CSS ───────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=Inter:wght@300;400;500;600&display=swap');
html,body,[class*="css"] { font-family:'Inter',sans-serif; }
.main                     { background:#080d0a; }
.block-container          { padding:1.6rem 2rem 3rem; }

/* sidebar */
section[data-testid="stSidebar"] { background:#04100a; border-right:1px solid #0d2a16; }
section[data-testid="stSidebar"] * { color:#8fcca0 !important; }
section[data-testid="stSidebar"] input {
    background:#081a0e !important; border:1px solid #1a4228 !important;
    color:#c8e8d2 !important; border-radius:6px !important;
}

/* cartão KPI */
.kpi { background:linear-gradient(135deg,#0b1f12,#0e2a18);
       border:1px solid #1a4228; border-radius:12px;
       padding:1rem 1.2rem .9rem; }
.kpi-lbl { font-family:'Space Mono',monospace; font-size:.62rem;
           letter-spacing:.14em; text-transform:uppercase;
           color:#3a9458; margin-bottom:.3rem; }
.kpi-val { font-family:'Space Mono',monospace; font-size:1.9rem;
           font-weight:700; color:#dff2e5; line-height:1.1; }
.kpi-unit { font-size:.75rem; color:#5cad78; margin-left:2px; }
.kpi-cat  { font-size:.68rem; margin-top:4px; }

/* separador de seção */
.sec { font-family:'Space Mono',monospace; font-size:.65rem;
       letter-spacing:.15em; text-transform:uppercase; color:#3a9458;
       border-bottom:1px solid #0f2218; padding-bottom:.4rem; margin:1.5rem 0 .7rem; }

/* cabeçalho de local */
.loc-hdr { font-family:'Space Mono',monospace; font-size:.9rem; font-weight:700;
           color:#55cc7a; background:#091a0e; border-left:3px solid #2a8050;
           padding:.5rem 1rem; margin:1rem 0 .6rem; border-radius:0 8px 8px 0; }

/* card de local na seleção */
.loc-card { background:#091a0e; border:1px solid #153520; border-radius:10px;
            padding:.8rem 1rem; margin:.3rem 0; cursor:pointer;
            transition:border-color .2s; }
.loc-card:hover { border-color:#2a8050; }

/* passos */
.step-box { background:#060f09; border:1px solid #0d2216; border-radius:12px;
            padding:1.5rem 1.8rem; margin:1rem 0; }
.step-num { font-family:'Space Mono',monospace; font-size:.65rem;
            letter-spacing:.1em; color:#3a9458; text-transform:uppercase;
            margin-bottom:.5rem; }
.step-title { font-size:1rem; font-weight:600; color:#c8e8d2; margin-bottom:.3rem; }
.step-desc  { font-size:.8rem; color:#3a6a4a; line-height:1.5; }

/* badge */
.badge-ok  { background:#0a2616;border:1px solid #246040;color:#4ec870;
             border-radius:20px;padding:3px 12px;font-size:.72rem;
             font-family:'Space Mono',monospace; }
.badge-err { background:#200a0a;border:1px solid #7a2020;color:#d06060;
             border-radius:20px;padding:3px 12px;font-size:.72rem;
             font-family:'Space Mono',monospace; }
</style>
""", unsafe_allow_html=True)

# ── Paleta ────────────────────────────────────
BG, GRID, FONT = "#080d0a", "#0e1e12", "#b0d4bc"
CORES = {
    "aqi":"#4caf74","pm2.5":"#81c784","pm10":"#c5e1a5","pm1":"#e6ee9c",
    "temp":"#ff8a65","humid":"#4dd0e1","no2":"#f06292",
    "o3":"#ce93d8","co2":"#ffb74d","tvoc":"#4db6ac",
}
# Paleta de locais com cores maximamente distantes entre si e do verde do dashboard.
# Matizes espaçados ~45° no círculo cromático: laranja, azul, vermelho, ciano, amarelo, violeta, rosa, branco-acinzentado.
PALETA_LOCAIS = ["#FF6D00","#2979FF","#D50000","#00BCD4","#FFD600","#7C4DFF","#F50057","#BDBDBD"]

LAYOUT = dict(
    paper_bgcolor=BG, plot_bgcolor=BG,
    font=dict(color=FONT, family="Inter, sans-serif", size=12),
    xaxis=dict(gridcolor=GRID, linecolor=GRID, zerolinecolor=GRID),
    yaxis=dict(gridcolor=GRID, linecolor=GRID, zerolinecolor=GRID),
    margin=dict(l=44,r=16,t=56,b=32),
    showlegend=True,
    legend=dict(
        bgcolor="rgba(8,13,10,0.85)", bordercolor="#1a4228", borderwidth=1,
        font=dict(size=11, color=FONT),
        orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0,
    ),
)

MESES = ["Janeiro","Fevereiro","Março","Abril","Maio","Junho",
         "Julho","Agosto","Setembro","Outubro","Novembro","Dezembro"]


# ─────────────────────────────────────────────
# Gráficos
# ─────────────────────────────────────────────

def _rgb(h):
    h = h.lstrip("#")
    return f"{int(h[:2],16)},{int(h[2:4],16)},{int(h[4:],16)}"

def _tit(t):
    return dict(text=t, font=dict(size=12, family="Space Mono, monospace", color="#4ec870"))

def _vazio(fig):
    fig.add_annotation(text="Sem dados", showarrow=False, font=dict(color="#2a5a38", size=13))

def g_area(pivot, param, titulo, unidade=""):
    fig = go.Figure()
    cor = CORES.get(param, "#4caf74")
    if param in pivot.columns and pivot[param].notna().any():
        fig.add_trace(go.Scatter(
            x=pivot["timestamp"], y=pivot[param], mode="lines",
            name=param.upper(), line=dict(color=cor, width=2),
            fill="tozeroy", fillcolor=f"rgba({_rgb(cor)},.07)",
        ))
    else:
        _vazio(fig)
    fig.update_layout(**LAYOUT, title=_tit(titulo), yaxis_title=unidade)
    return fig

def g_comparativo(pivots, param, titulo, unidade=""):
    """Uma linha por local."""
    fig = go.Figure()
    tem = False
    for i, (nome, piv) in enumerate(pivots.items()):
        cor = PALETA_LOCAIS[i % len(PALETA_LOCAIS)]
        if param in piv.columns and piv[param].notna().any():
            fig.add_trace(go.Scatter(
                x=piv["timestamp"], y=piv[param], mode="lines",
                name=nome, line=dict(color=cor, width=2),
            ))
            tem = True
    if not tem:
        _vazio(fig)
    fig.update_layout(**LAYOUT, title=_tit(titulo), yaxis_title=unidade)
    return fig

def g_multiplo(pivot, params, titulo, unidade=""):
    fig = go.Figure()
    tem = False
    for p in params:
        if p in pivot.columns and pivot[p].notna().any():
            fig.add_trace(go.Scatter(
                x=pivot["timestamp"], y=pivot[p], mode="lines",
                name=p.upper(), line=dict(color=CORES.get(p,"#4caf74"), width=1.8),
            ))
            tem = True
    if not tem:
        _vazio(fig)
    fig.update_layout(**LAYOUT, title=_tit(titulo), yaxis_title=unidade)
    return fig

def g_calor(pivot, param):
    fig = go.Figure()
    if param not in pivot.columns or not pivot[param].notna().any():
        _vazio(fig); fig.update_layout(**LAYOUT); return fig
    p = pivot[["timestamp", param]].copy()
    p["hora"] = p["timestamp"].dt.hour
    p["dia"]  = p["timestamp"].dt.day
    m   = p.groupby(["dia","hora"])[param].mean().unstack("hora")
    cor = CORES.get(param, "#4caf74")
    fig.add_trace(go.Heatmap(
        z=m.values,
        x=[f"{h:02d}h" for h in m.columns],
        y=[f"Dia {d:02d}" for d in m.index],
        colorscale=[[0,BG],[.5,f"rgba({_rgb(cor)},.4)"],[1,cor]],
        colorbar=dict(tickfont=dict(color=FONT, size=9)),
    ))
    fig.update_layout(**LAYOUT, title=_tit(f"Mapa de Calor — {param.upper()}"),
                      xaxis_title="Hora", yaxis_title="")
    return fig

def g_barras(diario, param, unidade=""):
    fig = go.Figure()
    if diario.empty or param not in diario.columns or not diario[param].notna().any():
        _vazio(fig); fig.update_layout(**LAYOUT); return fig
    cor = CORES.get(param,"#4caf74")
    fig.add_trace(go.Bar(
        x=diario["data"].astype(str), y=diario[param],
        marker_color=cor, marker_opacity=.75, name=param.upper(),
    ))
    fig.update_layout(**LAYOUT, title=_tit(f"Média Diária — {param.upper()}"),
                      yaxis_title=unidade, xaxis_tickangle=-45)
    return fig


# ─────────────────────────────────────────────
# Processamento
# ─────────────────────────────────────────────

def pivot_de(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    return (
        df[df["media"].notna()]
        .groupby(["timestamp","parametro"])["media"].mean()
        .unstack("parametro").reset_index().sort_values("timestamp")
    )

def diario_de(pivot: pd.DataFrame) -> pd.DataFrame:
    if pivot.empty:
        return pivot
    p = pivot.copy()
    p["data"] = pd.to_datetime(p["timestamp"]).dt.date
    return p.groupby("data").mean(numeric_only=True).reset_index()

def aqi_cat(v):
    if v is None:  return "—",                     "#2a5a38"
    if v <= 50:    return "Boa",                   "#4caf74"
    if v <= 100:   return "Moderada",              "#d4a020"
    if v <= 150:   return "Insalubre (sens.)",     "#e07040"
    if v <= 200:   return "Insalubre",             "#cc3030"
    return              "Muito Insalubre",          "#8b1010"


# ─────────────────────────────────────────────
# KPIs
# ─────────────────────────────────────────────

def kpis(pivot: pd.DataFrame):
    metricas = [
        ("aqi","AQI",""), ("pm2.5","PM2.5","µg/m³"),
        ("pm10","PM10","µg/m³"), ("temp","Temperatura","°C"),
        ("humid","Umidade","%"), ("co2","CO₂","ppm"),
    ]
    cols = st.columns(len(metricas))
    for col,(p,label,u) in zip(cols, metricas):
        with col:
            v   = pivot[p].mean() if p in pivot.columns else None
            vs  = f"{v:.1f}" if v is not None else "—"
            ext = ""
            if p == "aqi" and v is not None:
                cat,cor = aqi_cat(v)
                ext = f"<div class='kpi-cat' style='color:{cor}'>{cat}</div>"
            st.markdown(f"""
            <div class='kpi'>
              <div class='kpi-lbl'>{label}</div>
              <div class='kpi-val'>{vs}<span class='kpi-unit'>{u}</span></div>
              {ext}
            </div>""", unsafe_allow_html=True)


# ─────────────────────────────────────────────
# Exportação Excel
# ─────────────────────────────────────────────

METRICAS_XLS = ["aqi","pm2.5","pm10","pm1","temp","humid","co2","tvoc","no2","o3"]

def gerar_excel(df: pd.DataFrame, mapa: Dict[str,str], rotulo: str) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xls:

        # Aba Resumo
        rows = []
        for tid, nome in mapa.items():
            sub = df[df["thing_id"]==tid]
            p   = pivot_de(sub)
            row = {"Local": nome}
            for m in METRICAS_XLS:
                row[m.upper()] = round(p[m].mean(),2) if m in p.columns else None
            rows.append(row)
        pg = pivot_de(df)
        rg = {"Local":"MÉDIA GERAL"}
        for m in METRICAS_XLS:
            rg[m.upper()] = round(pg[m].mean(),2) if m in pg.columns else None
        rows.append(rg)
        pd.DataFrame(rows).to_excel(xls, sheet_name="Resumo", index=False)

        # Médias diárias
        dg = diario_de(pg)
        if not dg.empty:
            cols = ["data"]+[m for m in METRICAS_XLS if m in dg.columns]
            de   = dg[[c for c in cols if c in dg.columns]].copy()
            de.columns = ["Data" if c=="data" else c.upper() for c in de.columns]
            de.to_excel(xls, sheet_name="Médias Diárias", index=False)

        # Aba por local
        for tid, nome in mapa.items():
            sub = df[df["thing_id"]==tid]
            p   = pivot_de(sub)
            if not p.empty:
                p.to_excel(xls, sheet_name=nome[:31], index=False)

        # Dados brutos
        de = df.copy()
        de["local"]     = de["thing_id"].map(mapa)
        de["timestamp"] = de["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S")
        de.to_excel(xls, sheet_name="Dados Brutos", index=False)

    return buf.getvalue()



def gerar_pdf(df: pd.DataFrame, mapa: Dict[str,str], rotulo: str) -> bytes:
    """
    Gera PDF com gráficos do dashboard.
    Estrutura:
      - Capa com resumo geral (KPIs de todos os locais)
      - Uma página por local com todos os gráficos
    Requer: kaleido (plotly → PNG) + reportlab (PDF)
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Image as RLImage,
        PageBreak, Table, TableStyle, HRFlowable,
    )
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    import io as _io

    W, H = A4  # 595 x 842 pts

    # ── Estilos ──
    estilos = getSampleStyleSheet()
    titulo_doc = ParagraphStyle(
        "titulo_doc", parent=estilos["Title"],
        fontSize=18, textColor=colors.HexColor("#1a5e32"),
        spaceAfter=4, alignment=TA_CENTER,
    )
    subtit = ParagraphStyle(
        "subtit", parent=estilos["Normal"],
        fontSize=9, textColor=colors.HexColor("#3a7a50"),
        spaceAfter=2, alignment=TA_CENTER,
    )
    sec_hdr = ParagraphStyle(
        "sec_hdr", parent=estilos["Heading2"],
        fontSize=13, textColor=colors.HexColor("#1a5e32"),
        spaceBefore=10, spaceAfter=4,
    )
    normal = ParagraphStyle(
        "normal_txt", parent=estilos["Normal"],
        fontSize=8, textColor=colors.HexColor("#2a4a32"),
        spaceAfter=2,
    )
    kpi_label_style = ParagraphStyle(
        "kpi_lbl", parent=estilos["Normal"],
        fontSize=7, textColor=colors.HexColor("#3a7a50"),
        alignment=TA_CENTER,
    )
    kpi_val_style = ParagraphStyle(
        "kpi_val", parent=estilos["Normal"],
        fontSize=14, textColor=colors.HexColor("#0d3320"),
        alignment=TA_CENTER, fontName="Helvetica-Bold",
    )

    def _fig_para_png(fig, w_px=560, h_px=240):
        """Converte figura Plotly para bytes PNG. Tamanho reduzido para geração rápida."""
        fig2 = go.Figure(fig)
        fig2.update_layout(
            paper_bgcolor="white", plot_bgcolor="#f8fdf9",
            font=dict(color="#1a3a22", family="Arial, sans-serif", size=10),
            xaxis=dict(gridcolor="#dde8e0", linecolor="#b0c8b8", showticklabels=True),
            yaxis=dict(gridcolor="#dde8e0", linecolor="#b0c8b8"),
            legend=dict(bgcolor="rgba(255,255,255,0.8)", bordercolor="#b0c8b8", font=dict(size=9)),
            margin=dict(l=44, r=12, t=32, b=32),
            showlegend=True,
        )
        # scale=1 é muito mais rápido que scale=1.5
        return fig2.to_image(format="png", width=w_px, height=h_px, scale=1)

    def _png_para_rl(png_bytes, largura_cm=16):
        """Converte PNG bytes para objeto Image do ReportLab."""
        buf = _io.BytesIO(png_bytes)
        largura_pts = largura_cm * cm
        img = RLImage(buf, width=largura_pts, height=largura_pts * 340 / 800)
        return img

    def _tabela_kpi(pivot, locais_nomes=None):
        """Tabela de KPIs horizontais."""
        metricas = [
            ("aqi",   "AQI",    ""),
            ("pm2.5", "PM2.5",  "µg/m³"),
            ("pm10",  "PM10",   "µg/m³"),
            ("temp",  "Temp.",  "°C"),
            ("humid", "Umid.",  "%"),
            ("co2",   "CO₂",   "ppm"),
        ]
        headers = [Paragraph(f"<b>{lbl}</b>", kpi_label_style) for _, lbl, _ in metricas]
        valores = []
        for param, _, unid in metricas:
            v = pivot[param].mean() if param in pivot.columns else None
            txt = f"{v:.1f}{unid}" if v is not None else "—"
            valores.append(Paragraph(txt, kpi_val_style))

        t = Table([headers, valores], colWidths=[(W - 4*cm) / len(metricas)] * len(metricas))
        t.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#e8f5ec")),
            ("BACKGROUND", (0,1), (-1,1), colors.HexColor("#f4faf6")),
            ("BOX",        (0,0), (-1,-1), 0.5, colors.HexColor("#b0d4bc")),
            ("INNERGRID",  (0,0), (-1,-1), 0.3, colors.HexColor("#c8e4d0")),
            ("TOPPADDING",    (0,0), (-1,-1), 4),
            ("BOTTOMPADDING", (0,0), (-1,-1), 4),
        ]))
        return t

    # ── Construção do documento ──
    buf_pdf = _io.BytesIO()
    doc = SimpleDocTemplate(
        buf_pdf, pagesize=A4,
        leftMargin=2*cm, rightMargin=2*cm,
        topMargin=2*cm, bottomMargin=2*cm,
    )

    ids   = sorted(df["thing_id"].unique().tolist())
    nomes = [mapa.get(tid, f"Dispositivo {tid}") for tid in ids]
    story = []

    # ════ CAPA ════
    story.append(Spacer(1, 1.5*cm))
    story.append(Paragraph("🌿 Monitor de Qualidade do Ar", titulo_doc))
    story.append(Paragraph("Plataforma Aurassure IoT — UFOPA", subtit))
    story.append(Paragraph(f"Período: {rotulo}", subtit))
    story.append(Spacer(1, 0.5*cm))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#2a8050")))
    story.append(Spacer(1, 0.4*cm))

    # Resumo geral — tabela com todos os locais
    story.append(Paragraph("Resumo Geral — Todos os Locais", sec_hdr))
    metricas_res = ["aqi","pm2.5","pm10","temp","humid","co2","tvoc","no2","o3"]
    cab_res = ["Local"] + [m.upper() for m in metricas_res]
    linhas_res = [[Paragraph(f"<b>{c}</b>", normal) for c in cab_res]]
    for tid, nome in zip(ids, nomes):
        sub = df[df["thing_id"]==tid]
        p   = pivot_de(sub)
        linha = [Paragraph(nome, normal)]
        for m in metricas_res:
            v = p[m].mean() if m in p.columns else None
            linha.append(Paragraph(f"{v:.2f}" if v is not None else "—", normal))
        linhas_res.append(linha)

    col_w = [(W - 4*cm) / len(cab_res)] * len(cab_res)
    col_w[0] = 4.5*cm
    t_res = Table(linhas_res, colWidths=col_w)
    t_res.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#d0ead8")),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.HexColor("#f4faf6"), colors.white]),
        ("BOX",       (0,0), (-1,-1), 0.5, colors.HexColor("#90c4a0")),
        ("INNERGRID", (0,0), (-1,-1), 0.3, colors.HexColor("#b8d8c4")),
        ("TOPPADDING",    (0,0), (-1,-1), 3),
        ("BOTTOMPADDING", (0,0), (-1,-1), 3),
        ("FONTSIZE", (0,0), (-1,-1), 7),
    ]))
    story.append(t_res)

    # Comparativo AQI na capa
    story.append(Spacer(1, 0.6*cm))
    story.append(Paragraph("AQI Comparativo por Local", sec_hdr))
    pivs = {mapa.get(t, t): pivot_de(df[df["thing_id"]==t]) for t in ids}
    try:
        png = _fig_para_png(g_comparativo(pivs,"aqi","AQI — Comparativo","AQI"), w_px=760, h_px=280)
        story.append(_png_para_rl(png, largura_cm=17))
    except Exception:
        story.append(Paragraph("(gráfico indisponível — instale kaleido)", normal))

    # ════ PÁGINA POR LOCAL ════
    for tid, nome in zip(ids, nomes):
        story.append(PageBreak())
        story.append(Paragraph(f"📍 {nome}", sec_hdr))
        story.append(Paragraph(f"Período: {rotulo}", subtit))
        story.append(Spacer(1, 0.2*cm))
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#2a8050")))
        story.append(Spacer(1, 0.3*cm))

        df_l = df[df["thing_id"]==tid]
        piv  = pivot_de(df_l)
        diar = diario_de(piv)

        # KPIs
        story.append(_tabela_kpi(piv))
        story.append(Spacer(1, 0.4*cm))

        # Gráficos: 4 pares essenciais lado a lado (sem mapas de calor — mais rápido)
        pares = [
            (g_area(piv,"aqi","AQI","AQI"),         g_area(piv,"pm2.5","PM2.5","µg/m³")),
            (g_area(piv,"temp","Temperatura","°C"),  g_area(piv,"humid","Umidade","%")),
            (g_area(piv,"co2","CO₂","ppm"),          g_area(piv,"no2","NO₂","µg/m³")),
            (g_barras(diar,"aqi","AQI"),              g_barras(diar,"pm2.5","µg/m³")),
        ]
        for fig_esq, fig_dir in pares:
            try:
                img_e = _png_para_rl(_fig_para_png(fig_esq), largura_cm=8.2)
                img_d = _png_para_rl(_fig_para_png(fig_dir), largura_cm=8.2)
                t_par = Table([[img_e, img_d]], colWidths=[8.4*cm, 8.4*cm])
                t_par.setStyle(TableStyle([
                    ("VALIGN",(0,0),(-1,-1),"TOP"),
                    ("LEFTPADDING",(0,0),(-1,-1),2),
                    ("RIGHTPADDING",(0,0),(-1,-1),2),
                ]))
                story.append(t_par)
                story.append(Spacer(1, 0.1*cm))
            except Exception:
                story.append(Paragraph("(gráfico indisponível — instale kaleido)", normal))

        # Material particulado — largura total
        try:
            png_pm = _fig_para_png(
                g_multiplo(piv,["pm1","pm2.5","pm10"],"PM1 / PM2.5 / PM10","µg/m³"),
                w_px=760, h_px=220,
            )
            story.append(_png_para_rl(png_pm, largura_cm=17))
        except Exception:
            pass

    doc.build(story)
    return buf_pdf.getvalue()


def bloco_exportar(df, mapa, rotulo):
    st.markdown("<div class='sec'>📥 Exportar Relatório</div>", unsafe_allow_html=True)

    c2, c3 = st.columns(2)

    # ── CSV (dados brutos) ──
    with c2:
        dc = df.copy()
        dc["local"] = dc["thing_id"].map(mapa)
        st.download_button(
            "📄 CSV — dados brutos",
            data=dc.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"aurassure_{rotulo.replace(' ','_')}.csv",
            mime="text/csv",
            use_container_width=True,
            help="Todos os registros em CSV com coluna de local",
        )

    # ── PDF (gráficos) ──
    with c3:
        try:
            import reportlab  # noqa: F401
            with st.spinner("Gerando PDF com os gráficos..."):
                pdf_bytes = gerar_pdf(df, mapa, rotulo)
            st.download_button(
                "🖼️ PDF — gráficos por local",
                data=pdf_bytes,
                file_name=f"aurassure_{rotulo.replace(' ','_')}.pdf",
                mime="application/pdf",
                use_container_width=True,
                help="PDF com capa de resumo + página de gráficos para cada local",
            )
        except ImportError:
            st.warning(
                "Para exportar PDF instale as dependências: "
                "`pip install reportlab kaleido`"
            )
        except Exception as e:
            st.error(f"Erro ao gerar PDF: {e}")


# ─────────────────────────────────────────────
# Cache
# ─────────────────────────────────────────────

@st.cache_data(ttl=600, show_spinner=False)
def _cache_dispositivos(email, senha):
    return listar_dispositivos(email, senha)

@st.cache_data(ttl=300, show_spinner=False)
def _cache_dados(email, senha, ano, mes, thing_ids_t):
    from_ts, upto_ts = intervalo_unix_mensal(ano, mes)
    raw  = buscar_dados_sensor(email, senha, from_ts, upto_ts, list(thing_ids_t))
    rows = normalizar_resposta(raw)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df


# ─────────────────────────────────────────────
# Barra lateral  (só credenciais + período)
# ─────────────────────────────────────────────

def sidebar():
    with st.sidebar:
        st.markdown("""
        <div style='padding:.5rem 0 .3rem'>
          <div style='font-family:Space Mono,monospace;font-size:1rem;
                      color:#4caf74;font-weight:700'>🌿 AURASSURE</div>
          <div style='font-size:.6rem;color:#1e4a28;letter-spacing:.12em;
                      text-transform:uppercase'>Monitor de Qualidade do Ar · UFOPA</div>
        </div>""", unsafe_allow_html=True)
        st.markdown("---")

        st.markdown("<div style='font-size:.68rem;color:#3a9458;font-family:Space Mono,monospace;letter-spacing:.1em;text-transform:uppercase;margin-bottom:.4rem'>🔐 Acesso</div>", unsafe_allow_html=True)
        email = st.text_input("E-mail", value=os.getenv("AURASSURE_EMAIL","lambdaufopa@gmail.com"),
                              placeholder="seu@email.com", label_visibility="collapsed")
        st.caption("E-mail da plataforma Aurassure")
        senha = st.text_input("Senha", value=os.getenv("AURASSURE_PASSWORD","L@mbda2025"),
                              type="password", placeholder="Senha", label_visibility="collapsed")
        st.caption("Senha")

        st.markdown("---")
        st.markdown("<div style='font-size:.68rem;color:#3a9458;font-family:Space Mono,monospace;letter-spacing:.1em;text-transform:uppercase;margin-bottom:.4rem'>📅 Período</div>", unsafe_allow_html=True)

        now = datetime.now()
        cm, ca = st.columns([3,2])
        with cm:
            mes_nome = st.selectbox("Mês", MESES, index=now.month-1, label_visibility="collapsed")
            st.caption("Mês")
        with ca:
            anos = list(range(2022, now.year+1))
            ano  = st.selectbox("Ano", anos, index=len(anos)-1, label_visibility="collapsed")
            st.caption("Ano")

        st.markdown("""
        <div style='font-size:.58rem;color:#152a1c;text-align:center;margin-top:2rem'>
          Dados: plataforma Aurassure IoT<br>Horário UTC · Cache 5 min
        </div>""", unsafe_allow_html=True)

    return {"email": email, "senha": senha,
            "mes": MESES.index(mes_nome)+1, "mes_nome": mes_nome, "ano": ano}


# ─────────────────────────────────────────────
# Telas do fluxo principal
# ─────────────────────────────────────────────

def tela_boas_vindas():
    st.markdown("""
    <div style='max-width:500px;margin:3rem auto'>
      <div style='text-align:center;margin-bottom:2.5rem'>
        <div style='font-size:3rem'>🌿</div>
        <div style='font-family:Space Mono,monospace;font-size:1rem;color:#2a6040;margin-top:.5rem'>
          Monitor de Qualidade do Ar — UFOPA
        </div>
        <div style='font-size:.78rem;color:#163520;margin-top:.3rem'>
          Informe suas credenciais na barra lateral para começar
        </div>
      </div>
      <div style='background:#060f09;border:1px solid #0d2216;border-radius:12px;padding:1.5rem 1.8rem'>
        <div style='font-family:Space Mono,monospace;font-size:.65rem;color:#3a9458;
                    letter-spacing:.1em;text-transform:uppercase;margin-bottom:1rem'>
          Como usar
        </div>
        <div style='display:flex;flex-direction:column;gap:.8rem'>
          <div style='display:flex;gap:.8rem;align-items:flex-start'>
            <div style='font-family:Space Mono,monospace;font-size:.8rem;color:#3a9458;min-width:1.2rem'>①</div>
            <div style='font-size:.8rem;color:#3a6a4a;line-height:1.5'>
              Digite seu <strong style='color:#5cad78'>e-mail e senha</strong> da plataforma Aurassure na barra lateral
            </div>
          </div>
          <div style='display:flex;gap:.8rem;align-items:flex-start'>
            <div style='font-family:Space Mono,monospace;font-size:.8rem;color:#3a9458;min-width:1.2rem'>②</div>
            <div style='font-size:.8rem;color:#3a6a4a;line-height:1.5'>
              Selecione o <strong style='color:#5cad78'>mês e ano</strong> que deseja analisar
            </div>
          </div>
          <div style='display:flex;gap:.8rem;align-items:flex-start'>
            <div style='font-family:Space Mono,monospace;font-size:.8rem;color:#3a9458;min-width:1.2rem'>③</div>
            <div style='font-size:.8rem;color:#3a6a4a;line-height:1.5'>
              Escolha os <strong style='color:#5cad78'>locais de monitoramento</strong> que deseja ver
            </div>
          </div>
          <div style='display:flex;gap:.8rem;align-items:flex-start'>
            <div style='font-family:Space Mono,monospace;font-size:.8rem;color:#3a9458;min-width:1.2rem'>④</div>
            <div style='font-size:.8rem;color:#3a6a4a;line-height:1.5'>
              Visualize os dados e <strong style='color:#5cad78'>exporte o relatório</strong> em Excel ou CSV
            </div>
          </div>
        </div>
      </div>
    </div>
    """, unsafe_allow_html=True)


def tela_selecao_locais(email, senha, mes_nome, ano):
    """
    Tela de seleção de locais.
    Carrega a lista da API e apresenta como checkboxes visuais.
    """
    st.markdown(f"""
    <h2 style='font-family:Space Mono,monospace;font-size:1.1rem;
               color:#4caf74;margin-bottom:.2rem'>
      Escolher Locais de Monitoramento
    </h2>
    <p style='color:#3a6a4a;font-size:.8rem;margin-bottom:1.5rem'>
      Período: <strong style='color:#5cad78'>{mes_nome} {ano}</strong>
      — Selecione os locais que deseja incluir no relatório
    </p>
    """, unsafe_allow_html=True)

    # Carrega dispositivos
    with st.spinner("Carregando locais da plataforma Aurassure..."):
        try:
            dispositivos = _cache_dispositivos(email, senha)
        except ErroAutenticacao as e:
            st.error(f"🔐 Credenciais inválidas: {e}")
            return None
        except Exception as e:
            st.error(f"Erro ao carregar locais: {e}")
            return None

    if not dispositivos:
        st.warning("Nenhum local encontrado na conta.")
        return None

    # Detecta fallback (só 1 dispositivo padrão retornado)
    eh_fallback = len(dispositivos) == 1 and dispositivos[0].get("_fallback")

    if eh_fallback:
        st.warning(
            "⚠️ Não foi possível carregar os nomes dos locais automaticamente. "
            "O sistema encontrou apenas o dispositivo padrão. "
            "Veja a seção de **Debug** abaixo para identificar o endpoint correto."
        )

    # Checkboxes por local
    st.markdown("<div class='sec'>📍 Locais disponíveis</div>", unsafe_allow_html=True)

    selecionados = []
    cols_locais = st.columns(min(len(dispositivos), 2))
    for i, disp in enumerate(dispositivos):
        with cols_locais[i % 2]:
            marcado = st.checkbox(
                f"**{disp['nome']}**",
                value=True,
                key=f"loc_{disp['id']}",
            )
            if marcado:
                selecionados.append(disp)

    st.markdown("<br>", unsafe_allow_html=True)

    if not selecionados:
        st.info("Selecione ao menos um local para continuar.")
        return None

    if st.button("🔍 Gerar Relatório", type="primary", use_container_width=False):
        return selecionados

    return None


def tela_relatorio(df: pd.DataFrame, mapa: Dict[str,str], rotulo: str):
    """Tela principal do relatório com abas por local."""
    ids   = sorted(df["thing_id"].unique().tolist())
    nomes = [mapa.get(tid, f"Dispositivo {tid}") for tid in ids]

    abas_labels = ["📊 Comparativo"] + nomes
    abas = st.tabs(abas_labels)

    # ── Aba Comparativo ─────────────────────────────
    with abas[0]:
        pg = pivot_de(df)
        st.markdown(f"<div class='sec'>Todos os Locais — {rotulo}</div>", unsafe_allow_html=True)
        kpis(pg)
        pivs = {mapa.get(t, t): pivot_de(df[df["thing_id"]==t]) for t in ids}
        st.markdown("<div class='sec'>📈 Comparativo por Local</div>", unsafe_allow_html=True)
        st.plotly_chart(g_comparativo(pivs,"aqi","AQI — Todos os Locais","AQI"), use_container_width=True, key="cmp_aqi")
        c1,c2 = st.columns(2)
        with c1:
            st.plotly_chart(g_comparativo(pivs,"pm2.5","PM2.5 por Local","µg/m³"), use_container_width=True, key="cmp_pm25")
        with c2:
            st.plotly_chart(g_comparativo(pivs,"temp","Temperatura por Local","°C"), use_container_width=True, key="cmp_temp")
        c3,c4 = st.columns(2)
        with c3:
            st.plotly_chart(g_comparativo(pivs,"humid","Umidade por Local","%"), use_container_width=True, key="cmp_humid")
        with c4:
            st.plotly_chart(g_comparativo(pivs,"co2","CO₂ por Local","ppm"), use_container_width=True, key="cmp_co2")
        dg = diario_de(pg)
        st.markdown("<div class='sec'>📅 Médias Diárias (geral)</div>", unsafe_allow_html=True)
        c5,c6 = st.columns(2)
        with c5:
            st.plotly_chart(g_barras(dg,"aqi","AQI"), use_container_width=True, key="cmp_bar_aqi")
        with c6:
            st.plotly_chart(g_barras(dg,"pm2.5","µg/m³"), use_container_width=True, key="cmp_bar_pm25")

    # ── Aba por local — key usa tid para garantir unicidade ──
    for aba, tid, nome in zip(abas[1:], ids, nomes):
        with aba:
            k = "loc_" + "".join(c for c in tid if c.isalnum() or c == "_")
            df_l = df[df["thing_id"]==tid]
            piv  = pivot_de(df_l)
            diar = diario_de(piv)
            st.markdown(f"<div class='loc-hdr'>📍 {nome}</div>", unsafe_allow_html=True)
            kpis(piv)
            st.markdown("<div class='sec'>📈 Tendências</div>", unsafe_allow_html=True)
            c1,c2 = st.columns(2)
            with c1:
                st.plotly_chart(g_area(piv,"aqi","Índice de Qualidade do Ar","AQI"), use_container_width=True, key=f"{k}_aqi")
            with c2:
                st.plotly_chart(g_area(piv,"pm2.5","PM2.5","µg/m³"), use_container_width=True, key=f"{k}_pm25")
            c3,c4 = st.columns(2)
            with c3:
                st.plotly_chart(g_area(piv,"temp","Temperatura","°C"), use_container_width=True, key=f"{k}_temp")
            with c4:
                st.plotly_chart(g_area(piv,"humid","Umidade","%"), use_container_width=True, key=f"{k}_humid")
            st.markdown("<div class='sec'>🔬 Material Particulado</div>", unsafe_allow_html=True)
            st.plotly_chart(g_multiplo(piv,["pm1","pm2.5","pm10"],"PM1 / PM2.5 / PM10","µg/m³"), use_container_width=True, key=f"{k}_pm_multi")
            st.markdown("<div class='sec'>🧪 Outros Poluentes</div>", unsafe_allow_html=True)
            c5,c6 = st.columns(2)
            with c5:
                st.plotly_chart(g_area(piv,"co2","CO₂","ppm"), use_container_width=True, key=f"{k}_co2")
            with c6:
                st.plotly_chart(g_area(piv,"tvoc","TVOC","ppb"), use_container_width=True, key=f"{k}_tvoc")
            c7,c8 = st.columns(2)
            with c7:
                st.plotly_chart(g_area(piv,"no2","NO₂","µg/m³"), use_container_width=True, key=f"{k}_no2")
            with c8:
                st.plotly_chart(g_area(piv,"o3","O₃","µg/m³"), use_container_width=True, key=f"{k}_o3")
            st.markdown("<div class='sec'>🌡️ Padrão Horário</div>", unsafe_allow_html=True)
            c9,c10 = st.columns(2)
            with c9:
                st.plotly_chart(g_calor(piv,"aqi"), use_container_width=True, key=f"{k}_calor_aqi")
            with c10:
                st.plotly_chart(g_calor(piv,"pm2.5"), use_container_width=True, key=f"{k}_calor_pm25")
            st.markdown("<div class='sec'>📅 Médias Diárias</div>", unsafe_allow_html=True)
            c11,c12 = st.columns(2)
            with c11:
                st.plotly_chart(g_barras(diar,"aqi","AQI"), use_container_width=True, key=f"{k}_bar_aqi")
            with c12:
                st.plotly_chart(g_barras(diar,"pm2.5","µg/m³"), use_container_width=True, key=f"{k}_bar_pm25")

    # Dados brutos + exportar (fora das abas)
    with st.expander("🔍 Dados brutos"):
        de = df.copy()
        de["local"] = de["thing_id"].map(mapa)
        st.dataframe(de.sort_values("timestamp").head(500), use_container_width=True)
        st.caption(f"{len(df)} registros · locais: {nomes}")

    bloco_exportar(df, mapa, rotulo)


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────

def main():
    sb = sidebar()

    st.markdown("""
    <h1 style='font-family:Space Mono,monospace;font-size:1.35rem;
               color:#4caf74;margin-bottom:0'>🌿 Monitor de Qualidade do Ar</h1>
    <p style='color:#2a6040;font-size:.78rem;margin-top:2px'>
      Plataforma Aurassure IoT — UFOPA
    </p>""", unsafe_allow_html=True)

    email  = sb["email"]
    senha  = sb["senha"]
    mes    = sb["mes"]
    mes_nome = sb["mes_nome"]
    ano    = sb["ano"]
    rotulo = f"{mes_nome} {ano}"

    # Estado
    for k,v in [("pagina","boas_vindas"),("df",None),("mapa",{}),("rotulo","")]:
        if k not in st.session_state:
            st.session_state[k] = v

    # ── Roteamento de páginas ──────────────────
    if not email or not senha:
        st.session_state["pagina"] = "boas_vindas"

    if st.session_state["pagina"] == "boas_vindas":
        tela_boas_vindas()

        if email and senha:
            if st.button("▶ Continuar", type="primary"):
                st.session_state["pagina"] = "selecao"
                st.rerun()

    elif st.session_state["pagina"] == "selecao":
        st.markdown("---")
        selecionados = tela_selecao_locais(email, senha, mes_nome, ano)

        if selecionados is not None:
            ids   = [d["id"] for d in selecionados]
            mapa  = {str(d["id"]): d["nome"] for d in selecionados}
            nomes = [d["nome"] for d in selecionados]

            with st.spinner(f"Buscando dados de {rotulo} — {', '.join(nomes)}..."):
                try:
                    df = _cache_dados(email, senha, ano, mes, tuple(ids))
                    if df.empty:
                        st.warning(
                            "Nenhum dado encontrado para este período. "
                            "Os equipamentos podem ter estado offline. "
                            "Tente um mês anterior."
                        )
                    else:
                        st.session_state["df"]     = df
                        st.session_state["mapa"]   = mapa
                        st.session_state["rotulo"] = rotulo
                        st.session_state["pagina"] = "relatorio"
                        st.rerun()
                except ErroAutenticacao as e:
                    st.error(f"🔐 {e}")
                except ErroBuscaDados as e:
                    st.error(f"📡 {e}")
                except Exception as e:
                    st.error(f"Erro: {e}")

        st.markdown("---")
        if st.button("← Voltar"):
            st.session_state["pagina"] = "boas_vindas"
            st.rerun()

    elif st.session_state["pagina"] == "relatorio":
        df    = st.session_state["df"]
        mapa  = st.session_state["mapa"]
        rot   = st.session_state["rotulo"]

        col_titulo, col_voltar = st.columns([5,1])
        with col_voltar:
            if st.button("← Alterar seleção"):
                st.session_state["pagina"] = "selecao"
                st.rerun()

        if df is not None and not df.empty:
            tela_relatorio(df, mapa, rot)
        else:
            st.info("Sem dados. Volte e tente outro período.")


if __name__ == "__main__":
    main()