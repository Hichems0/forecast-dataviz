"""
Streamlit Data Viz App - Version API avec Batch Forecast
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
from datetime import datetime

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
        logger.error(f"API Error for {product_name}: {e}")
        return {"success": False, "error": str(e)}


def create_forecast_excel_with_sum(forecast_df, product_name):
    """Crée un fichier Excel avec ligne de somme."""
    # Ajouter ligne de somme
    sum_row = {}
    for col in forecast_df.columns:
        if col == "Date":
            sum_row[col] = "TOTAL"
        elif pd.api.types.is_numeric_dtype(forecast_df[col]):
            sum_row[col] = forecast_df[col].sum()
        else:
            sum_row[col] = ""

    df_with_sum = pd.concat([forecast_df, pd.DataFrame([sum_row])], ignore_index=True)

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
        df_with_sum.to_excel(writer, sheet_name="Prévisions", index=False)

        # Formater la dernière ligne (somme) en gras
        workbook = writer.book
        worksheet = writer.sheets["Prévisions"]

        from openpyxl.styles import Font
        last_row = len(df_with_sum) + 1
        for cell in worksheet[last_row]:
            cell.font = Font(bold=True)

    buffer.seek(0)
    return buffer


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

    with st.expander("📋 Aperçu des données brutes"):
        st.dataframe(df_raw.head(10), use_container_width=True)

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
    # ONGLETS : Article Unique vs Batch vs Validation
    # ==========
    tab1, tab2, tab3 = st.tabs([
        "📦 Prévision Article Unique",
        "🚀 Prévision Batch (Multiples Articles)",
        "📊 Validation Historique (Backtesting)"
    ])

    # ========================================
    # TAB 1 : ARTICLE UNIQUE
    # ========================================
    with tab1:
        st.subheader("🔍 Visualisation détaillée par article")

        articles_sorted = ranking["Description article"].tolist()

        # Recherche
        search_text = st.text_input(
            "🔎 Rechercher un article :",
            value="",
            placeholder="Ex : VIVA, LINDT, PATES...",
            key="search_single"
        )

        if search_text:
            filtered_articles = [a for a in articles_sorted if search_text.lower() in a.lower()]
        else:
            filtered_articles = articles_sorted

        if not filtered_articles:
            st.warning("Aucun article ne correspond à votre recherche.")
            st.stop()

        selected_article = st.selectbox("📦 Article :", filtered_articles, key="select_single")

        freq_label = st.radio("📅 Fréquence d'agrégation :", ("Jour", "Semaine", "Mois"), horizontal=True, key="freq_single")

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
                start_date = st.date_input("📅 Date de début", value=min_date, min_value=min_date, max_value=max_date, key="start_single")
            with col_end:
                end_date = st.date_input("📅 Date de fin", value=max_date, min_value=start_date, max_value=max_date, key="end_single")

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

        # Graphique historique
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

        # Export Excel historique avec somme
        hist_df = series_hist.to_frame(name="Quantité_totale").reset_index()
        hist_buffer = create_forecast_excel_with_sum(hist_df, selected_article)

        st.download_button(
            label="📥 Télécharger l'historique (Excel avec TOTAL)",
            data=hist_buffer,
            file_name=f"historique_{selected_article}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="download_hist"
        )

        # Prévision IA
        st.subheader("🤖 Prévision IA (via API Modal)")

        horizon_choice = st.selectbox(
            "Horizon de prévision :",
            ["Aucune", "7 jours", "30 jours", "60 jours", "90 jours"],
            index=0,
            key="horizon_single"
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

        run_forecast = st.button("🚀 Lancer la prévision IA", key="run_single")

        if forecast_horizon is not None and run_forecast:
            with st.spinner("⏳ Appel de l'API Modal en cours..."):
                result = call_modal_api(
                    series_data=series_hist.values,
                    horizon=forecast_horizon,
                    dates=series_hist.index,
                    product_name=selected_article
                )
                # Stocker dans session_state
                st.session_state.single_forecast_result = {
                    'result': result,
                    'series_hist': series_hist,
                    'forecast_horizon': forecast_horizon,
                    'selected_article': selected_article
                }

        # Afficher depuis session_state si disponible
        if 'single_forecast_result' in st.session_state:
            stored = st.session_state.single_forecast_result
            result = stored['result']
            series_hist = stored['series_hist']
            forecast_horizon = stored['forecast_horizon']
            selected_article = stored['selected_article']

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

                # Export Excel prévisions avec somme
                forecast_df = pd.DataFrame({
                    "Date": future_index,
                    "Prévision_moyenne": predictions,
                    "IC_95_bas": lower_bound,
                    "IC_95_haut": upper_bound,
                    "Trajectoire_simulée": simulated_path,
                })

                if median_predictions is not None:
                    forecast_df["Prévision_médiane"] = median_predictions

                forecast_buffer = create_forecast_excel_with_sum(forecast_df, selected_article)

                st.download_button(
                    label="📥 Télécharger les prévisions (Excel avec TOTAL)",
                    data=forecast_buffer,
                    file_name=f"previsions_{selected_article}_H{forecast_horizon}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="download_forecast_single"
                )

            elif result:
                st.error(f"❌ Erreur lors de la prévision : {result.get('error', 'Erreur inconnue')}")

    # ========================================
    # TAB 2 : BATCH FORECAST
    # ========================================
    with tab2:
        st.subheader("🚀 Prévision Batch - Multiples Articles")
        st.markdown("Lancez des prévisions sur plusieurs articles en une seule fois et téléchargez tous les résultats.")

        # Sélection des articles
        batch_search = st.text_input(
            "🔎 Filtrer les articles :",
            value="",
            placeholder="Tapez pour filtrer...",
            key="search_batch"
        )

        articles_sorted = ranking["Description article"].tolist()
        if batch_search:
            filtered_batch = [a for a in articles_sorted if batch_search.lower() in a.lower()]
        else:
            filtered_batch = articles_sorted

        selected_articles = st.multiselect(
            "📦 Sélectionnez les articles (plusieurs possibles) :",
            filtered_batch,
            default=[],
            key="select_batch"
        )

        st.write(f"**{len(selected_articles)}** article(s) sélectionné(s)")

        # Paramètres batch
        col1, col2 = st.columns(2)
        with col1:
            batch_freq = st.radio("📅 Fréquence :", ("Jour", "Semaine", "Mois"), horizontal=True, key="freq_batch")
        with col2:
            batch_horizon = st.selectbox(
                "🎯 Horizon de prévision :",
                ["7 jours", "30 jours", "60 jours", "90 jours"],
                index=1,
                key="horizon_batch"
            )

        # Sélection de plage de dates pour le batch
        st.subheader("📅 Plage de dates pour l'historique")

        # Obtenir min/max dates globales
        if len(selected_articles) > 0:
            temp_freq = "D" if batch_freq == "Jour" else ("W-MON" if batch_freq == "Semaine" else "M")
            df_temp = aggregate_quantities(df_daily, freq=temp_freq)
            all_dates = df_temp["Période"].unique()
            global_min_date = pd.to_datetime(all_dates).min().date()
            global_max_date = pd.to_datetime(all_dates).max().date()
        else:
            global_min_date = df_daily["Date de livraison"].min().date()
            global_max_date = df_daily["Date de livraison"].max().date()

        col_batch_start, col_batch_end = st.columns(2)
        with col_batch_start:
            batch_start_date = st.date_input(
                "📅 Date de début",
                value=global_min_date,
                min_value=global_min_date,
                max_value=global_max_date,
                key="batch_start_date"
            )
        with col_batch_end:
            batch_end_date = st.date_input(
                "📅 Date de fin",
                value=global_max_date,
                min_value=batch_start_date,
                max_value=global_max_date,
                key="batch_end_date"
            )

        if batch_freq == "Jour":
            freq_batch_val = "D"
        elif batch_freq == "Semaine":
            freq_batch_val = "W-MON"
        else:
            freq_batch_val = "M"

        if batch_horizon == "7 jours":
            horizon_batch_val = 7
        elif batch_horizon == "30 jours":
            horizon_batch_val = 30
        elif batch_horizon == "60 jours":
            horizon_batch_val = 60
        else:
            horizon_batch_val = 90

        run_batch = st.button("🚀 Lancer le Batch Forecast", key="run_batch", type="primary")

        if run_batch and len(selected_articles) > 0:
            st.info(f"🔄 Traitement de {len(selected_articles)} article(s)...")

            # Initialiser stockage des résultats
            st.session_state.batch_results = {}  # Reset
            st.session_state.all_forecasts = []  # Reset
            st.session_state.batch_config = {
                'freq': freq_batch_val,
                'horizon': horizon_batch_val,
                'start_date': batch_start_date,
                'end_date': batch_end_date
            }

            progress_bar = st.progress(0)
            status_text = st.empty()

            all_forecasts = []

            for idx, article in enumerate(selected_articles):
                status_text.text(f"⏳ Traitement de {article} ({idx+1}/{len(selected_articles)})...")

                # Préparer données
                df_agg_batch = aggregate_quantities(df_daily, freq=freq_batch_val)
                df_art = df_agg_batch[df_agg_batch["Description article"] == article].copy()
                df_art = df_art.sort_values("Période")

                # Trimming
                nonzero_mask = df_art["Quantité_totale"] != 0
                if nonzero_mask.any():
                    first_idx = df_art.index[nonzero_mask][0]
                    last_idx = df_art.index[nonzero_mask][-1]
                    df_art = df_art.loc[first_idx:last_idx]

                # Apply date range filter
                mask_batch_window = (
                    (df_art["Période"] >= pd.to_datetime(batch_start_date)) &
                    (df_art["Période"] <= pd.to_datetime(batch_end_date))
                )
                df_art = df_art.loc[mask_batch_window].copy()

                if df_art.empty:
                    st.warning(f"⚠️ Pas de données pour {article}, ignoré.")
                    continue

                series_data = df_art.set_index("Période")["Quantité_totale"]

                # Appel API
                result = call_modal_api(
                    series_data=series_data.values,
                    horizon=horizon_batch_val,
                    dates=series_data.index,
                    product_name=article
                )

                if result and result.get("success"):
                    # Stocker résultat
                    st.session_state.batch_results[article] = result

                    # Construction future index
                    if isinstance(series_data.index, pd.DatetimeIndex):
                        inferred_freq = pd.infer_freq(series_data.index)
                        if inferred_freq is None:
                            inferred_freq = "D"
                        start_future = series_data.index[-1] + pd.tseries.frequencies.to_offset(inferred_freq)
                        future_index = pd.date_range(start=start_future, periods=horizon_batch_val, freq=inferred_freq)
                    else:
                        last_idx = series_data.index[-1]
                        future_index = np.arange(last_idx + 1, last_idx + 1 + horizon_batch_val)

                    # Créer DataFrame prévision
                    forecast_df = pd.DataFrame({
                        "Article": article,
                        "Date": future_index,
                        "Prévision_moyenne": result["predictions"],
                        "IC_95_bas": result["lower_bound"],
                        "IC_95_haut": result["upper_bound"],
                        "Trajectoire_simulée": result["simulated_path"],
                        "Modèle": result["model_used"]
                    })

                    if result.get("median_predictions"):
                        forecast_df["Prévision_médiane"] = result["median_predictions"]

                    all_forecasts.append(forecast_df)

                else:
                    st.warning(f"⚠️ Échec pour {article}: {result.get('error', 'Erreur inconnue')}")

                progress_bar.progress((idx + 1) / len(selected_articles))

            # Stocker all_forecasts dans session_state
            st.session_state.all_forecasts = all_forecasts

            status_text.text("✅ Batch terminé !")
            st.success(f"✅ Prévisions générées pour {len(all_forecasts)}/{len(selected_articles)} article(s)")

        # Afficher depuis session_state si disponible
        if 'all_forecasts' in st.session_state and len(st.session_state.all_forecasts) > 0:
            all_forecasts = st.session_state.all_forecasts
            freq_batch_val = st.session_state.batch_config['freq']
            horizon_batch_val = st.session_state.batch_config['horizon']

            if True:  # Always display if we have results
                st.subheader("📊 Résumé des prévisions")

                summary_data = []
                for article, res in st.session_state.batch_results.items():
                    summary_data.append({
                        "Article": article,
                        "Modèle utilisé": res["model_used"],
                        "Total prévu (moyenne)": sum(res["predictions"]),
                        "Zero ratio": f"{res['routing_info']['zero_ratio']*100:.1f}%"
                    })

                summary_df = pd.DataFrame(summary_data)
                st.dataframe(summary_df, use_container_width=True)

                # Visualisation individuelle par article
                st.subheader("📊 Visualisation par article")

                selected_viz_article = st.selectbox(
                    "Sélectionnez un article pour voir son graphique :",
                    list(st.session_state.batch_results.keys()),
                    key="viz_article_select"
                )

                if selected_viz_article:
                    viz_result = st.session_state.batch_results[selected_viz_article]

                    # Récupérer les données historiques de cet article
                    df_agg_viz = aggregate_quantities(df_daily, freq=freq_batch_val)
                    df_art_viz = df_agg_viz[df_agg_viz["Description article"] == selected_viz_article].copy()
                    df_art_viz = df_art_viz.sort_values("Période")

                    # Trimming
                    nonzero_mask_viz = df_art_viz["Quantité_totale"] != 0
                    if nonzero_mask_viz.any():
                        first_idx_viz = df_art_viz.index[nonzero_mask_viz][0]
                        last_idx_viz = df_art_viz.index[nonzero_mask_viz][-1]
                        df_art_viz = df_art_viz.loc[first_idx_viz:last_idx_viz]

                    series_viz = df_art_viz.set_index("Période")["Quantité_totale"]

                    # Construction future index
                    if isinstance(series_viz.index, pd.DatetimeIndex):
                        inferred_freq_viz = pd.infer_freq(series_viz.index)
                        if inferred_freq_viz is None:
                            inferred_freq_viz = "D"
                        start_future_viz = series_viz.index[-1] + pd.tseries.frequencies.to_offset(inferred_freq_viz)
                        future_index_viz = pd.date_range(start=start_future_viz, periods=horizon_batch_val, freq=inferred_freq_viz)
                    else:
                        last_idx_viz = series_viz.index[-1]
                        future_index_viz = np.arange(last_idx_viz + 1, last_idx_viz + 1 + horizon_batch_val)

                    # Créer graphique
                    fig_viz = go.Figure()

                    # Historique
                    fig_viz.add_trace(
                        go.Scatter(
                            x=series_viz.index,
                            y=series_viz.values,
                            mode="lines",
                            name="Historique",
                            line=dict(color="black", width=1.5),
                        )
                    )

                    # Prévision moyenne
                    fig_viz.add_trace(
                        go.Scatter(
                            x=future_index_viz,
                            y=viz_result["predictions"],
                            mode="lines",
                            name="Prévision (moyenne)",
                            line=dict(color="blue", width=2),
                        )
                    )

                    # IC
                    fig_viz.add_trace(
                        go.Scatter(
                            x=future_index_viz,
                            y=viz_result["upper_bound"],
                            mode="lines",
                            name="IC 95%",
                            line=dict(color="rgba(0,100,255,0.3)", width=1, dash="dot"),
                            showlegend=False,
                        )
                    )

                    fig_viz.add_trace(
                        go.Scatter(
                            x=future_index_viz,
                            y=viz_result["lower_bound"],
                            mode="lines",
                            name="IC 95%",
                            line=dict(color="rgba(0,100,255,0.3)", width=1, dash="dot"),
                            fill="tonexty",
                            fillcolor="rgba(0,100,255,0.2)",
                        )
                    )

                    # Trajectoire
                    if viz_result["model_used"] == "BayesianLSTM":
                        label_viz = "Trajectoire simulée (MC Dropout)"
                        color_viz = "rgba(124, 252, 0, 0.9)"
                    elif viz_result["model_used"] == "SparseSpikeForecaster":
                        label_viz = "Pics périodiques simulés"
                        color_viz = "rgba(255, 165, 0, 0.9)"
                    else:
                        label_viz = "Scénario simulé 0/spikes"
                        color_viz = "rgba(255, 0, 0, 0.9)"

                    fig_viz.add_trace(
                        go.Scatter(
                            x=future_index_viz,
                            y=viz_result["simulated_path"],
                            mode="markers+lines",
                            name=label_viz,
                            line=dict(color=color_viz, width=1.5),
                            marker=dict(size=6),
                        )
                    )

                    fig_viz.update_layout(
                        template="plotly_white",
                        height=500,
                        xaxis_title="Temps",
                        yaxis_title="Quantité",
                        legend=dict(x=0.01, y=0.99),
                        title=f"{selected_viz_article} - {viz_result['model_used']}",
                    )

                    st.plotly_chart(fig_viz, use_container_width=True)

                    # Téléchargement individuel
                    st.caption(f"📥 Téléchargement pour {selected_viz_article}")

                    forecast_df_viz = pd.DataFrame({
                        "Date": future_index_viz,
                        "Prévision_moyenne": viz_result["predictions"],
                        "IC_95_bas": viz_result["lower_bound"],
                        "IC_95_haut": viz_result["upper_bound"],
                        "Trajectoire_simulée": viz_result["simulated_path"],
                    })

                    if viz_result.get("median_predictions"):
                        forecast_df_viz["Prévision_médiane"] = viz_result["median_predictions"]

                    individual_buffer = create_forecast_excel_with_sum(forecast_df_viz, selected_viz_article)

                    st.download_button(
                        label=f"📥 Télécharger prévision de {selected_viz_article}",
                        data=individual_buffer,
                        file_name=f"prevision_{selected_viz_article}_H{horizon_batch_val}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key=f"download_individual_{selected_viz_article}"
                    )

                # Téléchargement groupé
                st.subheader("📥 Téléchargement groupé de tous les articles")

                combined_df = pd.concat(all_forecasts, ignore_index=True)

                # Créer Excel avec toutes les prévisions
                batch_buffer = io.BytesIO()
                with pd.ExcelWriter(batch_buffer, engine='openpyxl') as writer:
                    # Une feuille par article
                    for article in combined_df["Article"].unique():
                        article_df = combined_df[combined_df["Article"] == article].copy()
                        article_df = article_df.drop(columns=["Article"])

                        # Ajouter ligne somme
                        sum_row = {}
                        for col in article_df.columns:
                            if col == "Date":
                                sum_row[col] = "TOTAL"
                            elif col == "Modèle":
                                sum_row[col] = ""
                            elif pd.api.types.is_numeric_dtype(article_df[col]):
                                sum_row[col] = article_df[col].sum()
                            else:
                                sum_row[col] = ""

                        article_df_with_sum = pd.concat([article_df, pd.DataFrame([sum_row])], ignore_index=True)

                        # Nettoyer le nom de feuille (Excel interdit certains caractères)
                        sheet_name = article[:31]  # Excel limit
                        for char in ['\\', '/', '?', '*', '[', ']', ':']:
                            sheet_name = sheet_name.replace(char, '_')
                        sheet_name = sheet_name.strip("'")  # Pas d'apostrophe au début/fin

                        article_df_with_sum.to_excel(writer, sheet_name=sheet_name, index=False)

                        # Formater dernière ligne
                        from openpyxl.styles import Font
                        worksheet = writer.sheets[sheet_name]
                        last_row = len(article_df_with_sum) + 1
                        for cell in worksheet[last_row]:
                            cell.font = Font(bold=True)

                    # Feuille de synthèse
                    summary_df.to_excel(writer, sheet_name="Synthèse", index=False)

                    # Feuille des totaux par produit
                    product_totals = []
                    for article in combined_df["Article"].unique():
                        article_data = combined_df[combined_df["Article"] == article]
                        product_totals.append({
                            "Article": article,
                            "Total_Prévision_Moyenne": article_data["Prévision_moyenne"].sum(),
                            "Total_IC_95_Bas": article_data["IC_95_bas"].sum(),
                            "Total_IC_95_Haut": article_data["IC_95_haut"].sum(),
                            "Total_Trajectoire_Simulée": article_data["Trajectoire_simulée"].sum(),
                            "Modèle": article_data["Modèle"].iloc[0] if len(article_data) > 0 else ""
                        })

                    totals_df = pd.DataFrame(product_totals)
                    totals_df.to_excel(writer, sheet_name="Totaux_par_Produit", index=False)

                batch_buffer.seek(0)

                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                st.download_button(
                    label=f"📥 Télécharger TOUTES les prévisions ({len(all_forecasts)} articles)",
                    data=batch_buffer,
                    file_name=f"batch_forecast_{timestamp}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="download_batch",
                    type="primary"
                )

        elif run_batch and len(selected_articles) == 0:
            st.warning("⚠️ Veuillez sélectionner au moins un article.")

    # ========================================
    # TAB 3 : VALIDATION HISTORIQUE (BACKTESTING)
    # ========================================
    with tab3:
        st.subheader("📊 Validation Historique - Backtesting")
        st.markdown(
            "Testez la précision du modèle en comparant ses prédictions avec des données historiques réelles. "
            "Le modèle est entraîné sur une période et prédit sur une autre période dont vous connaissez déjà les résultats."
        )

        # Sélection articles multiples
        st.subheader("🔍 Sélection des articles")

        search_text_val = st.text_input(
            "🔎 Rechercher des articles :",
            value="",
            placeholder="Ex : VIVA, LINDT, PATES...",
            key="search_validation"
        )

        if search_text_val:
            filtered_articles_val = [a for a in articles_sorted if search_text_val.lower() in a.lower()]
        else:
            filtered_articles_val = articles_sorted

        if not filtered_articles_val:
            st.warning("Aucun article ne correspond à votre recherche.")
            st.stop()

        selected_articles_val = st.multiselect(
            "📦 Sélectionnez un ou plusieurs articles :",
            filtered_articles_val,
            default=[],
            key="articles_validation"
        )

        if not selected_articles_val:
            st.info("👆 Sélectionnez au moins un article pour commencer")
            st.stop()

        st.write(f"**{len(selected_articles_val)}** article(s) sélectionné(s)")

        # Fréquence
        freq_label_val = st.radio(
            "📅 Fréquence d'agrégation :",
            ("Jour", "Semaine", "Mois"),
            horizontal=True,
            key="freq_validation"
        )

        if freq_label_val == "Jour":
            freq_val = "D"
        elif freq_label_val == "Semaine":
            freq_val = "W-MON"
        else:
            freq_val = "M"

        # Obtenir les dates globales pour tous les articles sélectionnés
        df_agg_val = aggregate_quantities(df_daily, freq=freq_val)
        df_selected_val = df_agg_val[df_agg_val["Description article"].isin(selected_articles_val)].copy()

        if df_selected_val.empty:
            st.warning("Aucune donnée disponible pour les articles sélectionnés.")
            st.stop()

        # Sélection des périodes train/test
        st.subheader("📅 Définition des périodes")

        min_date_val = df_selected_val["Période"].min().date()
        max_date_val = df_selected_val["Période"].max().date()

        col_train_start, col_train_end = st.columns(2)
        with col_train_start:
            train_start_date = st.date_input(
                "📅 Début période d'entraînement",
                value=min_date_val,
                min_value=min_date_val,
                max_value=max_date_val,
                key="train_start"
            )
        with col_train_end:
            train_end_date = st.date_input(
                "📅 Fin période d'entraînement",
                value=min_date_val + (max_date_val - min_date_val) * 0.7,  # 70% pour train
                min_value=train_start_date,
                max_value=max_date_val,
                key="train_end"
            )

        col_test_start, col_test_end = st.columns(2)
        with col_test_start:
            test_start_date = st.date_input(
                "📅 Début période de test",
                value=train_end_date + pd.Timedelta(days=1),
                min_value=train_end_date,
                max_value=max_date_val,
                key="test_start"
            )
        with col_test_end:
            test_end_date = st.date_input(
                "📅 Fin période de test",
                value=max_date_val,
                min_value=test_start_date,
                max_value=max_date_val,
                key="test_end"
            )

        # Bouton validation
        run_validation = st.button("🚀 Lancer la validation batch", key="run_validation", type="primary")

        if run_validation:
            st.info(f"🔄 Validation de {len(selected_articles_val)} article(s)...")

            # Initialiser stockage
            st.session_state.validation_results = []
            st.session_state.validation_config = {
                'train_start': train_start_date,
                'train_end': train_end_date,
                'test_start': test_start_date,
                'test_end': test_end_date,
                'freq': freq_val
            }

            progress_bar = st.progress(0)
            status_text = st.empty()

            validation_summary = []

            for idx, article in enumerate(selected_articles_val):
                status_text.text(f"⏳ Validation de {article} ({idx+1}/{len(selected_articles_val)})...")

                # Préparer données pour cet article
                df_article_val = df_agg_val[df_agg_val["Description article"] == article].copy()
                df_article_val = df_article_val.sort_values("Période")

                # Trimming
                nonzero_mask_val = df_article_val["Quantité_totale"] != 0
                if nonzero_mask_val.any():
                    first_idx_val = df_article_val.index[nonzero_mask_val][0]
                    last_idx_val = df_article_val.index[nonzero_mask_val][-1]
                    df_article_val = df_article_val.loc[first_idx_val:last_idx_val]

                # Filtrer train
                mask_train = (
                    (df_article_val["Période"] >= pd.to_datetime(train_start_date)) &
                    (df_article_val["Période"] <= pd.to_datetime(train_end_date))
                )
                df_train = df_article_val.loc[mask_train].copy()

                # Filtrer test
                mask_test = (
                    (df_article_val["Période"] >= pd.to_datetime(test_start_date)) &
                    (df_article_val["Période"] <= pd.to_datetime(test_end_date))
                )
                df_test = df_article_val.loc[mask_test].copy()

                if df_train.empty or df_test.empty:
                    st.warning(f"⚠️ Pas assez de données pour {article}, ignoré.")
                    continue

                # Préparer séries
                series_train = df_train.set_index("Période")["Quantité_totale"]
                true_values = df_test.set_index("Période")["Quantité_totale"].values
                horizon_val = len(df_test)

                # Appel API
                result_val = call_modal_api(
                    series_data=series_train.values,
                    horizon=horizon_val,
                    dates=series_train.index,
                    product_name=article
                )

                if result_val and result_val.get("success"):
                    predictions_val = np.array(result_val["predictions"])
                    lower_bound_val = np.array(result_val["lower_bound"])
                    upper_bound_val = np.array(result_val["upper_bound"])
                    simulated_path_val = np.array(result_val["simulated_path"])

                    # Calculer totaux et métriques
                    total_predicted = predictions_val.sum()
                    total_real = true_values.sum()
                    total_ic_bas = lower_bound_val.sum()
                    total_ic_haut = upper_bound_val.sum()
                    total_trajectoire = simulated_path_val.sum()

                    mae = np.mean(np.abs(predictions_val - true_values))
                    rmse = np.sqrt(np.mean((predictions_val - true_values) ** 2))

                    # MAPE
                    mask_nonzero = true_values != 0
                    if mask_nonzero.any():
                        mape = np.mean(np.abs((true_values[mask_nonzero] - predictions_val[mask_nonzero]) / true_values[mask_nonzero])) * 100
                    else:
                        mape = np.nan

                    validation_summary.append({
                        "Article": article,
                        "Total_Prévision_Moyenne": total_predicted,
                        "Total_IC_95_Bas": total_ic_bas,
                        "Total_IC_95_Haut": total_ic_haut,
                        "Total_Trajectoire_Simulée": total_trajectoire,
                        "Total_Réel": total_real,
                        "Erreur_Absolue": abs(total_predicted - total_real),
                        "Erreur_Relative_%": abs(total_predicted - total_real) / total_real * 100 if total_real != 0 else np.nan,
                        "MAE": mae,
                        "RMSE": rmse,
                        "MAPE_%": mape,
                        "Modèle": result_val["model_used"],
                        "Points_Train": len(series_train),
                        "Points_Test": len(df_test)
                    })
                else:
                    st.warning(f"⚠️ Échec pour {article}")

                progress_bar.progress((idx + 1) / len(selected_articles_val))

            # Stocker résultats
            st.session_state.validation_results = validation_summary

            status_text.text("✅ Validation terminée !")
            st.success(f"✅ Validation réussie pour {len(validation_summary)}/{len(selected_articles_val)} article(s)")

        # Afficher résultats depuis session_state
        if 'validation_results' in st.session_state and len(st.session_state.validation_results) > 0:
            validation_summary = st.session_state.validation_results
            validation_df = pd.DataFrame(validation_summary)

            st.subheader("📊 Résultats de la validation")

            # Afficher métriques globales
            col1, col2, col3 = st.columns(3)
            with col1:
                avg_mae = validation_df["MAE"].mean()
                st.metric("MAE Moyenne", f"{avg_mae:.2f}")
            with col2:
                avg_rmse = validation_df["RMSE"].mean()
                st.metric("RMSE Moyenne", f"{avg_rmse:.2f}")
            with col3:
                avg_mape = validation_df["MAPE_%"].mean()
                if not np.isnan(avg_mape):
                    st.metric("MAPE Moyenne", f"{avg_mape:.2f}%")
                else:
                    st.metric("MAPE Moyenne", "N/A")

            # Afficher tableau synthétique
            st.subheader("📋 Tableau synthétique par article")
            st.dataframe(validation_df, use_container_width=True)

            # Export Excel
            st.subheader("📥 Téléchargement")

            validation_buffer = io.BytesIO()
            with pd.ExcelWriter(validation_buffer, engine='openpyxl') as writer:
                # UNE SEULE feuille avec le tableau synthétique
                validation_df.to_excel(writer, sheet_name="Validation_Synthèse", index=False)

                # Formater les nombres
                from openpyxl.styles import Font
                worksheet = writer.sheets["Validation_Synthèse"]

                # En-têtes en gras
                for cell in worksheet[1]:
                    cell.font = Font(bold=True)

            validation_buffer.seek(0)

            timestamp_val = datetime.now().strftime("%Y%m%d_%H%M%S")
            st.download_button(
                label=f"📥 Télécharger validation ({len(validation_summary)} articles)",
                data=validation_buffer,
                file_name=f"validation_batch_{timestamp_val}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="download_validation"
            )
