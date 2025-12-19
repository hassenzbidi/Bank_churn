"""
Détection de Data Drift avec visualisations et alertes
Compatible API / Docker / Azure
"""

# =========================
# BACKEND MATPLOTLIB SAFE
# =========================
import matplotlib
matplotlib.use("Agg")

# =========================
# IMPORTS
# =========================
import pandas as pd
import numpy as np
from scipy.stats import ks_2samp, chi2_contingency
import json
from datetime import datetime
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path
import os

# =========================
# PATHS ROBUSTES
# =========================
BASE_DIR = Path(__file__).resolve().parent.parent  # racine projet
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "drift_reports"


# =========================
# FONCTION PRINCIPALE
# =========================
def detect_drift(
    reference_file: str,
    production_file: str,
    threshold: float = 0.05,
    output_dir: Path | None = None
):
    """
    Détecte le drift entre données de référence et production
    """

    # -------- Paths sécurisés
    if output_dir is None:
        output_dir = OUTPUT_DIR

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    reference_file = Path(reference_file)
    production_file = Path(production_file)

    # -------- Vérification fichiers
    if not reference_file.exists():
        raise FileNotFoundError(f"Fichier de référence introuvable: {reference_file}")

    if not production_file.exists():
        raise FileNotFoundError(f"Fichier de production introuvable: {production_file}")

    # -------- Chargement données
    ref_data = pd.read_csv(reference_file)
    prod_data = pd.read_csv(production_file)

    drift_results = {}
    continuous_features = []
    categorical_features = []

    # -------- Classification des features
    for col in ref_data.columns:
        if col == "Exited":
            continue
        if col in prod_data.columns:
            if ref_data[col].dtype in ["int64", "float64"] and ref_data[col].nunique() > 10:
                continuous_features.append(col)
            else:
                categorical_features.append(col)

    # =========================
    # DRIFT CONTINU
    # =========================
    for col in continuous_features:
        ref_values = ref_data[col].dropna()
        prod_values = prod_data[col].dropna()

        statistic, p_value = ks_2samp(ref_values, prod_values)
        drift_detected = p_value < threshold

        drift_results[col] = {
            "p_value": float(p_value),
            "statistic": float(statistic),
            "drift_detected": bool(drift_detected),
            "type": "continuous",
            "ref_mean": float(ref_values.mean()),
            "prod_mean": float(prod_values.mean()),
            "ref_std": float(ref_values.std()),
            "prod_std": float(prod_values.std()),
        }

    # =========================
    # DRIFT CATÉGORIEL
    # =========================
    for col in categorical_features:
        try:
            ref_counts = ref_data[col].value_counts()
            prod_counts = prod_data[col].value_counts()

            all_values = set(ref_counts.index) | set(prod_counts.index)
            ref_aligned = [ref_counts.get(v, 0) for v in all_values]
            prod_aligned = [prod_counts.get(v, 0) for v in all_values]

            contingency_table = np.array([ref_aligned, prod_aligned])
            chi2, p_value, _, _ = chi2_contingency(contingency_table)

            drift_results[col] = {
                "p_value": float(p_value),
                "chi2": float(chi2),
                "drift_detected": bool(p_value < threshold),
                "type": "categorical",
            }
        except Exception:
            continue

    # =========================
    # RÉSUMÉ
    # =========================
    drifted_features = [
        f for f, r in drift_results.items() if r["drift_detected"]
    ]

    drift_percentage = (
        len(drifted_features) / len(drift_results) * 100
        if drift_results
        else 0
    )

    # =========================
    # VISUALISATIONS
    # =========================
    create_drift_visualizations(
        ref_data,
        prod_data,
        drift_results,
        continuous_features,
        output_dir,
    )

    # =========================
    # SAUVEGARDE RAPPORT JSON
    # =========================
    report = {
        "timestamp": datetime.utcnow().isoformat(),
        "threshold": threshold,
        "features_analyzed": len(drift_results),
        "features_drifted": len(drifted_features),
        "drift_percentage": drift_percentage,
        "results": drift_results,
    }

    report_path = output_dir / f"drift_report_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    return drift_results


# =========================
# VISUALISATIONS
# =========================
def create_drift_visualizations(
    ref_data,
    prod_data,
    drift_results,
    continuous_features,
    output_dir: Path,
):
    """
    Crée les graphiques de drift
    """

    # -------- Distributions
    if continuous_features:
        n_cols = 3
        n_rows = (len(continuous_features) + n_cols - 1) // n_cols

        fig, axes = plt.subplots(n_rows, n_cols, figsize=(15, 5 * n_rows))
        axes = axes.flatten()

        for idx, col in enumerate(continuous_features):
            ax = axes[idx]

            ax.hist(ref_data[col].dropna(), bins=30, alpha=0.5, density=True, label="Référence")
            ax.hist(prod_data[col].dropna(), bins=30, alpha=0.5, density=True, label="Production")

            status = "DRIFT" if drift_results[col]["drift_detected"] else "OK"
            p_val = drift_results[col]["p_value"]

            ax.set_title(f"{col} | {status} (p={p_val:.4f})")
            ax.legend()
            ax.grid(alpha=0.3)

        for idx in range(len(continuous_features), len(axes)):
            axes[idx].set_visible(False)

        plt.tight_layout()
        plt.savefig(output_dir / "drift_distributions.png", dpi=150)
        plt.close()

    # -------- Heatmap p-values
    features = list(drift_results.keys())
    p_values = [drift_results[f]["p_value"] for f in features]

    fig, ax = plt.subplots(figsize=(10, max(6, len(features) * 0.3)))
    sns.heatmap(
        np.array(p_values).reshape(-1, 1),
        annot=True,
        fmt=".4f",
        yticklabels=features,
        xticklabels=["P-value"],
        cmap="RdYlGn_r",
        vmin=0,
        vmax=0.1,
        ax=ax,
    )

    ax.set_title("Heatmap des p-values (drift en rouge)")
    plt.tight_layout()
    plt.savefig(output_dir / "drift_heatmap.png", dpi=150)
    plt.close()