"""
Streamlit Data Viz App - Version API
Visualisation avancée avec appel à l'API Modal pour les prévisions
"""
from __future__ import annotations
import io
import numpy as np
import plotly.graph_objects as go
import logging
from pathlib import Path
import requests
import streamlit as st
import pandas as pd
import tempfile
import os

# Configuration
IS_STREAMLIT_CLOUD = os.getenv("STREAMLIT_RUNTIME_ENV") == "cloud" or not os.path.exists("/home")

if not IS_STREAMLIT_CLOUD:
    TEMP_DIR = Path(tempfile.gettempdir()) / "dataviz_cache"
    try:
        TEMP_DIR.mkdir(parents=True, exist_ok=True)
    except Exception:
        TEMP_DIR = Path(tempfile.gettempdir())

    logger = logging.getLogger("DataVizApp")
    logger.setLevel(logging.INFO)
    try:
        LOG_PATH = TEMP_DIR / "dataviz_app.log"
        if not logger.handlers:
            fh = logging.FileHandler(LOG_PATH, encoding="utf-8")
            fmt = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
            fh.setFormatter(fmt)
            logger.addHandler(fh)
    except Exception:
        pass
else:
    logger = logging.getLogger("DataVizApp")
    logger.addHandler(logging.NullHandler())

# Configuration API Modal
try:
    MODAL_API_URL = st.secrets["MODAL_API_URL"]
except (KeyError, FileNotFoundError):
    MODAL_API_URL = "https://hichemsaada0--forecast-api-predict-api.modal.run"

# =========================
# Fonctions utilitaires
# =========================

def prepare_daily_df(df, col_article="Description article", col_date="Date de livraison", col_qte="Quantite"):
    """Prépare un DataFrame avec 1 ligne par (article, date) et quantités = 0 si absence."""
    df[col_date] = pd.to_datetime(df[col_date], dayfirst=True, errors="coerce")
    df[col_qte] = (
        df[col_qte]
        .astype(str)
        .str.replace(",", "", regex=False)
        .str.replace("\u00a0", "", regex=False)
        .astype(float)
    )

    grouped = (
        df.groupby([col_article, col_date], as_index=False)[col_qte]
        .sum()
        .rename(columns={col_qte: "Quantité_totale"})
    )

    all_dates = pd.date_range(start=grouped[col_date].min(), end=grouped[col_date].max(), freq="D")
    all_articles = grouped[col_article].unique()
    full_index = pd.MultiIndex.from_product([all_articles, all_dates], names=[col_article, col_date])

    result = (
        grouped
        .set_index([col_article, col_date])
        .reindex(full_index, fill_value=0)
        .reset_index()
    )

    return result


def aggregate_quantities(df_daily, freq="D"):
    """Agrège les quantités par article sur la fréquence donnée."""
    if freq == "D":
        out = df_daily.copy()
        out = out.rename(columns={"Date de livraison": "Période"})
        return out

    agg = (
        df_daily
        .groupby(["Description article", pd.Grouper(key="Date de livraison", freq=freq)])["Quantité_totale"]
        .sum()
        .reset_index()
        .rename(columns={"Date de livraison": "Période"})
    )
    return agg


def call_modal_api(series_data, horizon, dates=None, product_name="Unknown"):
    """Appelle l'API Modal pour obtenir des prévisions."""
    payload = {
        "product_name": product_name,
        "series": series_data.tolist() if isinstance(series_data, np.ndarray) else list(series_data),
        "horizon": horizon,
    }

    if dates is not None:
        payload["dates"] = [d.isoformat() if hasattr(d, 'isoformat') else str(d) for d in dates]

    try:
        response = requests.post(MODAL_API_URL, json=payload, timeout=600)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        st.error(f"❌ Erreur API : {str(e)}")
        logger.error(f"API Error: {e}")
        return None


# =========================
# Interface Streamlit
# =========================

st.set_page_config(page_title="Data Viz - Prévisions IA", layout="wide")
st.title("📊 Visualisation & Prévisions IA par Article")

st.markdown(
    "Importez votre fichier (CSV ou Excel) contenant au minimum : "
    "`Description article`, `Date de livraison`, `Quantite`."
)

uploaded_file = st.file_uploader("Choisissez votre fichier", type=["csv", "xlsx"])

if uploaded_file is not None:
    # Lecture du fichier
    if uploaded_file.name.lower().endswith(".csv"):
        df_raw = pd.read_csv(uploaded_file, sep=";")
    else:
        df_raw = pd.read_excel(uploaded_file)

    st.success("✅ Fichier chargé avec succès")
    st.write("Aperçu des premières lignes :")
    st.dataframe(df_raw.head())

    # Préparation du DataFrame journalier
    df_daily = prepare_daily_df(df_raw)

    # ==========
    # Classement des produits
    # ==========
    st.subheader("🏆 Classement des produits par quantité mensuelle (cumulée)")

    df_monthly_all = aggregate_quantities(df_daily, freq="M")
    ranking = (
        df_monthly_all
        .groupby("Description article")["Quantité_totale"]
        .sum()
        .sort_values(ascending=False)
        .reset_index()
        .rename(columns={"Quantité_totale": "Quantité_mensuelle_cumulée"})
    )

    st.dataframe(ranking, use_container_width=True)

    # ==========
    # Visualisation détaillée
    # ==========
    st.subheader("🔍 Visualisation détaillée par article")

    articles_sorted = ranking["Description article"].tolist()

    # Recherche
    search_text = st.text_input(
        "🔎 Rechercher un article :",
        value="",
        placeholder="Ex : VIVA, LINDT, PATES..."
    )

    if search_text:
        filtered_articles = [a for a in articles_sorted if search_text.lower() in a.lower()]
    else:
        filtered_articles = articles_sorted

    if not filtered_articles:
        st.warning("Aucun article ne correspond à votre recherche.")
        st.stop()

    selected_article = st.selectbox("📦 Article :", filtered_articles)

    freq_label = st.radio("📅 Fréquence d'agrégation :", ("Jour", "Semaine", "Mois"), horizontal=True)

    if freq_label == "Jour":
        freq = "D"
    elif freq_label == "Semaine":
        freq = "W-MON"
    else:
        freq = "M"

    df_agg = aggregate_quantities(df_daily, freq=freq)
    df_article = df_agg[df_agg["Description article"] == selected_article].copy()
    df_article = df_article.sort_values("Période")

    # Trimming des dates avec zéros
    nonzero_mask = df_article["Quantité_totale"] != 0
    if nonzero_mask.any():
        first_idx = df_article.index[nonzero_mask][0]
        last_idx = df_article.index[nonzero_mask][-1]
        df_article = df_article.loc[first_idx:last_idx]

    # Sélection de fenêtre temporelle
    if not df_article.empty:
        min_date = df_article["Période"].min().date()
        max_date = df_article["Période"].max().date()

        col_start, col_end = st.columns(2)
        with col_start:
            start_date = st.date_input("📅 Date de début", value=min_date, min_value=min_date, max_value=max_date)
        with col_end:
            end_date = st.date_input("📅 Date de fin", value=max_date, min_value=start_date, max_value=max_date)

        mask_window = (
            (df_article["Période"] >= pd.to_datetime(start_date)) &
            (df_article["Période"] <= pd.to_datetime(end_date))
        )
        df_article = df_article.loc[mask_window].copy()

        if df_article.empty:
            st.warning("La fenêtre de dates choisie ne contient aucune donnée.")
            st.stop()
    else:
        st.warning("Aucune donnée non nulle pour cet article.")
        st.stop()

    st.write(f"📦 Article sélectionné : **{selected_article}**")
    st.write(f"📊 Points de données : {len(df_article)}")

    st.dataframe(df_article, use_container_width=True)

    # ==========
    # Graphique historique
    # ==========
    st.subheader("📈 Historique des quantités")

    series_hist = df_article.set_index("Période")["Quantité_totale"]

    fig_hist = go.Figure()
    fig_hist.add_trace(
        go.Scatter(
            x=series_hist.index,
            y=series_hist.values,
            mode="lines",
            name="Historique",
            line=dict(color="black", width=1.5),
        )
    )

    fig_hist.update_layout(
        template="plotly_white",
        height=400,
        margin=dict(l=40, r=20, t=40, b=40),
        xaxis_title="Date",
        yaxis_title="Quantité",
        legend=dict(x=0.01, y=0.99),
    )

    st.plotly_chart(fig_hist, use_container_width=True)

    # Export Excel historique
    hist_buffer = io.BytesIO()
    series_hist.to_frame(name="Quantité_totale").to_excel(hist_buffer, sheet_name="Historique")
    hist_buffer.seek(0)

    st.download_button(
        label="📥 Télécharger l'historique (Excel)",
        data=hist_buffer,
        file_name=f"historique_{selected_article}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    # ==========
    # Prévision IA via API Modal
    # ==========
    st.subheader("🤖 Prévision IA (via API Modal)")

    horizon_choice = st.selectbox(
        "Horizon de prévision :",
        ["Aucune", "7 jours", "30 jours", "60 jours", "90 jours"],
        index=0,
    )

    if horizon_choice == "Aucune":
        forecast_horizon = None
    elif horizon_choice == "7 jours":
        forecast_horizon = 7
    elif horizon_choice == "30 jours":
        forecast_horizon = 30
    elif horizon_choice == "60 jours":
        forecast_horizon = 60
    else:
        forecast_horizon = 90

    run_forecast = st.button("🚀 Lancer la prévision IA")

    if forecast_horizon is not None and run_forecast:
        with st.spinner("⏳ Appel de l'API Modal en cours..."):
            result = call_modal_api(
                series_data=series_hist.values,
                horizon=forecast_horizon,
                dates=series_hist.index,
                product_name=selected_article
            )

        if result and result.get("success"):
            st.success(f"✅ Prévision réussie avec le modèle : **{result['model_used']}**")

            # Affichage diagnostics
            st.caption("📊 Diagnostics du routage intelligent :")
            routing_info = result.get("routing_info", {})
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Ratio de zéros", f"{routing_info.get('zero_ratio', 0)*100:.1f}%")
            with col2:
                st.metric("Dispersion", f"{routing_info.get('dispersion', 0):.3f}")
            with col3:
                st.metric("Autocorrélation", f"{routing_info.get('acf_lag1', 0):.3f}")

            # Construction de l'index futur
            if isinstance(series_hist.index, pd.DatetimeIndex):
                inferred_freq = pd.infer_freq(series_hist.index)
                if inferred_freq is None:
                    inferred_freq = "D"
                start_future = series_hist.index[-1] + pd.tseries.frequencies.to_offset(inferred_freq)
                future_index = pd.date_range(start=start_future, periods=forecast_horizon, freq=inferred_freq)
            else:
                last_idx = series_hist.index[-1]
                future_index = np.arange(last_idx + 1, last_idx + 1 + forecast_horizon)

            # Extraction des résultats
            predictions = np.array(result["predictions"])
            lower_bound = np.array(result["lower_bound"])
            upper_bound = np.array(result["upper_bound"])
            simulated_path = np.array(result["simulated_path"])
            median_predictions = result.get("median_predictions")

            # Graphique historique + prévisions
            st.subheader("📊 Historique et prévisions")

            fig_pred = go.Figure()

            # Historique
            fig_pred.add_trace(
                go.Scatter(
                    x=series_hist.index,
                    y=series_hist.values,
                    mode="lines",
                    name="Historique",
                    line=dict(color="black", width=1.5),
                )
            )

            # Prévision moyenne
            fig_pred.add_trace(
                go.Scatter(
                    x=future_index,
                    y=predictions,
                    mode="lines",
                    name="Prévision (moyenne)",
                    line=dict(color="blue", width=2),
                )
            )

            # Intervalle de confiance
            fig_pred.add_trace(
                go.Scatter(
                    x=future_index,
                    y=upper_bound,
                    mode="lines",
                    name="IC 95% (haut)",
                    line=dict(color="rgba(0,100,255,0.3)", width=1, dash="dot"),
                    showlegend=False,
                )
            )

            fig_pred.add_trace(
                go.Scatter(
                    x=future_index,
                    y=lower_bound,
                    mode="lines",
                    name="IC 95%",
                    line=dict(color="rgba(0,100,255,0.3)", width=1, dash="dot"),
                    fill="tonexty",
                    fillcolor="rgba(0,100,255,0.2)",
                )
            )

            # Médiane si disponible
            if median_predictions is not None:
                fig_pred.add_trace(
                    go.Scatter(
                        x=future_index,
                        y=median_predictions,
                        mode="lines",
                        name="Prévision (médiane)",
                        line=dict(color="green", width=2, dash="dash"),
                    )
                )

            # Trajectoire simulée
            if result["model_used"] == "BayesianLSTM":
                label = "Trajectoire simulée (MC Dropout)"
                color = "rgba(124, 252, 0, 0.9)"
            elif result["model_used"] == "SparseSpikeForecaster":
                label = "Pics périodiques simulés"
                color = "rgba(255, 165, 0, 0.9)"
            else:
                label = "Scénario simulé 0/spikes"
                color = "rgba(255, 0, 0, 0.9)"

            fig_pred.add_trace(
                go.Scatter(
                    x=future_index,
                    y=simulated_path,
                    mode="markers+lines",
                    name=label,
                    line=dict(color=color, width=1.5),
                    marker=dict(size=6),
                )
            )

            fig_pred.update_layout(
                template="plotly_white",
                height=500,
                xaxis_title="Temps",
                yaxis_title="Quantité",
                legend=dict(x=0.01, y=0.99),
                title=f"Prévisions H={forecast_horizon} - {result['model_used']}",
            )

            st.plotly_chart(fig_pred, use_container_width=True)

            # Export Excel prévisions
            forecast_df = pd.DataFrame({
                "Date": future_index,
                "Prévision_moyenne": predictions,
                "IC_95_bas": lower_bound,
                "IC_95_haut": upper_bound,
                "Trajectoire_simulée": simulated_path,
            })

            if median_predictions is not None:
                forecast_df["Prévision_médiane"] = median_predictions

            forecast_buffer = io.BytesIO()
            forecast_df.to_excel(forecast_buffer, sheet_name="Prévisions", index=False)
            forecast_buffer.seek(0)

            st.download_button(
                label="📥 Télécharger les prévisions (Excel)",
                data=forecast_buffer,
                file_name=f"previsions_{selected_article}_H{forecast_horizon}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

        elif result:
            st.error(f"❌ Erreur lors de la prévision : {result.get('error', 'Erreur inconnue')}")
