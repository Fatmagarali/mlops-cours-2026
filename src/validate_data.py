
"""Valide un fichier de données brutes contre le contrat dataset.yaml."""

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

from src.dataset_config import DatasetConfig, load_config

REPORT_JSON = Path("reports/validation.json")


def run_checks(cfg: DatasetConfig, df: pd.DataFrame) -> dict[str, bool]:
    """Retourne un booléen par contrôle : True signifie conforme."""
    try:
        cfg.validate_columns(df)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return {"colonnes_du_contrat": False}

    target = df[cfg.target]
    classes = set(target.dropna().astype(str))

    return {
        "colonnes_du_contrat": True,
        "table_non_vide": len(df) > 0,
        "cible_sans_valeur_manquante": bool(target.notna().all()),
        "cible_avec_classe_positive_et_autre": (
            str(cfg.positive_class) in classes and len(classes) >= 2
        ),
        "numeriques_de_type_nombre": all(
            pd.api.types.is_numeric_dtype(df[col]) for col in cfg.numeric
        ),
        "aucune_variable_entierement_vide": not any(
            df[col].isna().all() for col in cfg.features
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0]
    )
    parser.add_argument(
        "csv",
        nargs="?",
        help="Fichier à valider (par défaut : raw_path de dataset.yaml)",
    )
    args = parser.parse_args()

    cfg = load_config()
    df = pd.read_csv(args.csv or cfg.raw_path)
    checks = run_checks(cfg, df)
    failed = [name for name, ok in checks.items() if not ok]
    has_target = cfg.target in df.columns and len(df) > 0

    summary = {
        "success": not failed,
        "n_checks": len(checks),
        "n_failed": len(failed),
        "failed": failed,
        "rows": len(df),
        "positive_rate": (
            round(float(cfg.encode_target(df[cfg.target]).mean()), 4)
            if has_target
            else None
        ),
    }

    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0 if summary["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
