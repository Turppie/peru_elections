"""Election projection logic for ONPE geographic snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

LEVEL_ORDER = ["distrito", "provincia", "departamento", "ambito_geografico"]


@dataclass(frozen=True)
class Fallback:
    level: str
    keiko_share: float
    sanchez_share: float
    valid_votes_per_acta: float
    keiko_alpha: float
    sanchez_alpha: float


def project_results(
    df: pd.DataFrame,
    include_foreign: bool = True,
    foreign_fallback: str = "none",
    foreign_continent_min_actas: int = 10,
    foreign_continent_min_countries: int = 2,
    print_output: bool = True,
) -> dict[str, Any]:
    """Project final national result from the finest available geography."""

    prepared = _prepare_projection_units(
        df,
        include_foreign=include_foreign,
        foreign_fallback=foreign_fallback,
        foreign_continent_min_actas=foreign_continent_min_actas,
        foreign_continent_min_countries=foreign_continent_min_countries,
    )

    current_keiko = float(prepared["current_keiko_votes"].sum())
    current_sanchez = float(prepared["current_sanchez_votes"].sum())
    projected_keiko = float(prepared["projected_keiko_votes"].sum())
    projected_sanchez = float(prepared["projected_sanchez_votes"].sum())
    projected_total = projected_keiko + projected_sanchez
    foreign = prepared[prepared["ambito_geografico_id"] == 2]
    foreign_fallback_rows = foreign[foreign["used_fallback"]]

    top_missing = prepared.sort_values(
        "missing_valid_votes_est", ascending=False
    ).head(20)

    result = {
        "current_keiko_votes": current_keiko,
        "current_sanchez_votes": current_sanchez,
        "current_margin_sanchez_minus_keiko": current_sanchez - current_keiko,
        "projected_keiko_votes": projected_keiko,
        "projected_sanchez_votes": projected_sanchez,
        "projected_keiko_pct": _pct(projected_keiko, projected_total),
        "projected_sanchez_pct": _pct(projected_sanchez, projected_total),
        "projected_margin_sanchez_minus_keiko": projected_sanchez
        - projected_keiko,
        "projected_winner": _winner(projected_keiko, projected_sanchez),
        "total_missing_actas": float(prepared["missing_actas"].sum()),
        "projected_missing_valid_votes": float(
            prepared["missing_valid_votes_est"].sum()
        ),
        "rows_with_fallback": int(prepared["used_fallback"].sum()),
        "foreign_unprojected_actas": float(
            prepared.loc[prepared["foreign_unprojected"], "missing_actas"].sum()
        ),
        "foreign_current_keiko_votes": float(foreign["current_keiko_votes"].sum()),
        "foreign_current_sanchez_votes": float(
            foreign["current_sanchez_votes"].sum()
        ),
        "foreign_projected_keiko_votes": float(
            foreign["projected_keiko_votes"].sum()
        ),
        "foreign_projected_sanchez_votes": float(
            foreign["projected_sanchez_votes"].sum()
        ),
        "foreign_fallback_actas": float(foreign_fallback_rows["missing_actas"].sum()),
        "foreign_eligible_continents": sorted(
            foreign.loc[
                foreign["continent_eligible"], "departamento_nombre"
            ].dropna().unique().tolist()
        ),
        "top_missing_units": top_missing[
            [
                "ambito_geografico_id",
                "nivel",
                "departamento_nombre",
                "provincia_nombre",
                "distrito_nombre",
                "missing_actas",
                "missing_valid_votes_est",
                "used_fallback",
                "fallback_level",
            ]
        ].reset_index(drop=True),
        "projection_units": prepared,
    }
    if print_output:
        _print_projection(result)
    return result


def bootstrap_projection(
    df: pd.DataFrame,
    n_sim: int = 5000,
    seed: int = 42,
    include_foreign: bool = True,
    foreign_fallback: str = "none",
    foreign_continent_min_actas: int = 10,
    foreign_continent_min_countries: int = 2,
    return_simulations: bool = False,
) -> dict[str, Any]:
    """Bootstrap projected margin using beta shares by geography."""

    if n_sim <= 0:
        raise ValueError("n_sim must be positive")

    prepared = _prepare_projection_units(
        df,
        include_foreign=include_foreign,
        foreign_fallback=foreign_fallback,
        foreign_continent_min_actas=foreign_continent_min_actas,
        foreign_continent_min_countries=foreign_continent_min_countries,
    )
    rng = np.random.default_rng(seed)

    keiko = np.full(n_sim, float(prepared["current_keiko_votes"].sum()))
    sanchez = np.full(n_sim, float(prepared["current_sanchez_votes"].sum()))

    for row in prepared.itertuples(index=False):
        missing = float(row.missing_valid_votes_est)
        if missing <= 0 or not np.isfinite(row.keiko_alpha) or not np.isfinite(row.sanchez_alpha):
            continue
        sample_keiko_share = rng.beta(row.keiko_alpha, row.sanchez_alpha, n_sim)
        keiko += missing * sample_keiko_share
        sanchez += missing * (1.0 - sample_keiko_share)

    margin = sanchez - keiko
    result: dict[str, Any] = {
        "probability_keiko_wins": float(np.mean(keiko > sanchez)),
        "probability_sanchez_wins": float(np.mean(sanchez > keiko)),
        "probability_tie": float(np.mean(keiko == sanchez)),
        "margin_p2_5": float(np.percentile(margin, 2.5)),
        "margin_p50": float(np.percentile(margin, 50)),
        "margin_p97_5": float(np.percentile(margin, 97.5)),
    }
    if return_simulations:
        result["simulations"] = pd.DataFrame(
            {
                "sim": np.arange(n_sim),
                "projected_keiko_votes": keiko,
                "projected_sanchez_votes": sanchez,
                "margin_sanchez_minus_keiko": margin,
            }
        )
    return result


def _prepare_projection_units(
    df: pd.DataFrame,
    *,
    include_foreign: bool,
    foreign_fallback: str,
    foreign_continent_min_actas: int,
    foreign_continent_min_countries: int,
) -> pd.DataFrame:
    if foreign_fallback not in {"none", "continent", "national", "manual"}:
        raise ValueError(
            "foreign_fallback must be one of: none, continent, national, manual"
        )
    if foreign_fallback == "manual":
        raise ValueError(
            "foreign_fallback='manual' is reserved; manual inputs are not implemented."
        )
    if foreign_continent_min_actas < 1 or foreign_continent_min_countries < 1:
        raise ValueError("Foreign continent thresholds must be positive")

    working = _coerce_numeric(df.copy())
    selected = _select_projection_units(working, include_foreign=include_foreign)

    records: list[dict[str, Any]] = []
    for _, unit in selected.iterrows():
        ambito_id = _safe_int(unit.get("ambito_geografico_id"))
        continent_fallback = (
            _find_continent_fallback(
                working,
                unit,
                min_actas=foreign_continent_min_actas,
                min_countries=foreign_continent_min_countries,
            )
            if ambito_id == 2
            else None
        )
        continent_eligible = continent_fallback is not None
        counted = _num(unit.get("actas_contabilizadas"))
        total_actas = _num(unit.get("total_actas"))
        valid_votes = _num(unit.get("total_votos_validos"))
        keiko_votes = _num(unit.get("keiko_votes"))
        sanchez_votes = _num(unit.get("sanchez_votes"))
        missing_actas = max(total_actas - counted, 0.0) if total_actas > 0 else 0.0

        current_keiko = keiko_votes
        current_sanchez = sanchez_votes
        missing_valid = 0.0
        used_fallback = False
        fallback_level: str | None = None
        foreign_unprojected = False
        share_keiko: float | None = None
        share_sanchez: float | None = None
        keiko_alpha = np.nan
        sanchez_alpha = np.nan

        if missing_actas > 0:
            vote_sum = keiko_votes + sanchez_votes
            if counted > 0 and valid_votes > 0 and vote_sum > 0:
                valid_votes_per_acta = valid_votes / counted
                missing_valid = missing_actas * valid_votes_per_acta
                share_keiko = keiko_votes / vote_sum
                share_sanchez = sanchez_votes / vote_sum
                keiko_alpha = keiko_votes + 1.0
                sanchez_alpha = sanchez_votes + 1.0
            else:
                if ambito_id == 2 and foreign_fallback == "none":
                    foreign_unprojected = True
                elif ambito_id == 2 and foreign_fallback == "continent":
                    if continent_fallback is not None:
                        used_fallback = True
                        fallback_level = continent_fallback.level
                        missing_valid = (
                            missing_actas * continent_fallback.valid_votes_per_acta
                        )
                        share_keiko = continent_fallback.keiko_share
                        share_sanchez = continent_fallback.sanchez_share
                        keiko_alpha = continent_fallback.keiko_alpha
                        sanchez_alpha = continent_fallback.sanchez_alpha
                    else:
                        foreign_unprojected = True
                else:
                    fallback = _find_fallback(working, unit)
                    if fallback is not None:
                        used_fallback = True
                        fallback_level = fallback.level
                        missing_valid = missing_actas * fallback.valid_votes_per_acta
                        share_keiko = fallback.keiko_share
                        share_sanchez = fallback.sanchez_share
                        keiko_alpha = fallback.keiko_alpha
                        sanchez_alpha = fallback.sanchez_alpha

        if share_keiko is None or share_sanchez is None:
            share_keiko = 0.0
            share_sanchez = 0.0

        projected_keiko = current_keiko + missing_valid * share_keiko
        projected_sanchez = current_sanchez + missing_valid * share_sanchez

        record = unit.to_dict()
        record.update(
            {
                "current_keiko_votes": current_keiko,
                "current_sanchez_votes": current_sanchez,
                "missing_actas": missing_actas,
                "missing_valid_votes_est": missing_valid,
                "projected_keiko_votes": projected_keiko,
                "projected_sanchez_votes": projected_sanchez,
                "used_fallback": used_fallback,
                "fallback_level": fallback_level,
                "foreign_unprojected": foreign_unprojected,
                "continent_eligible": continent_eligible,
                "keiko_alpha": keiko_alpha,
                "sanchez_alpha": sanchez_alpha,
            }
        )
        records.append(record)

    return pd.DataFrame(records)


def _find_continent_fallback(
    df: pd.DataFrame,
    unit: pd.Series,
    *,
    min_actas: int,
    min_countries: int,
) -> Fallback | None:
    """Return a continent fallback only when it has enough foreign-country signal."""

    if _safe_int(unit.get("ambito_geografico_id")) != 2:
        return None
    department = unit.get("departamento_ubigeo")
    if department is None or pd.isna(department):
        return None

    continent_rows = df[
        (df["nivel"] == "departamento")
        & (df["ambito_geografico_id"] == 2)
        & (df["departamento_ubigeo"] == department)
    ]
    if continent_rows.empty:
        return None

    continent = continent_rows.iloc[0]
    counted = _num(continent.get("actas_contabilizadas"))
    valid = _num(continent.get("total_votos_validos"))
    keiko = _num(continent.get("keiko_votes"))
    sanchez = _num(continent.get("sanchez_votes"))
    vote_sum = keiko + sanchez

    country_rows = df[
        (df["nivel"] == "provincia")
        & (df["ambito_geografico_id"] == 2)
        & (df["departamento_ubigeo"] == department)
    ]
    countries_with_signal = 0
    for _, country in country_rows.iterrows():
        if (
            _num(country.get("actas_contabilizadas")) > 0
            and _num(country.get("total_votos_validos")) > 0
            and (
                _num(country.get("keiko_votes"))
                + _num(country.get("sanchez_votes"))
            )
            > 0
        ):
            countries_with_signal += 1

    if (
        counted < min_actas
        or countries_with_signal < min_countries
        or valid <= 0
        or vote_sum <= 0
    ):
        return None
    return Fallback(
        level="continente",
        keiko_share=keiko / vote_sum,
        sanchez_share=sanchez / vote_sum,
        valid_votes_per_acta=valid / counted,
        keiko_alpha=keiko + 1.0,
        sanchez_alpha=sanchez + 1.0,
    )


def _select_projection_units(df: pd.DataFrame, *, include_foreign: bool) -> pd.DataFrame:
    scoped = df.copy()
    if not include_foreign and "ambito_geografico_id" in scoped.columns:
        scoped = scoped[scoped["ambito_geografico_id"].fillna(1).astype(float) != 2]

    selected_parts: list[pd.DataFrame] = []
    ambito_values = [
        value
        for value in scoped.get("ambito_geografico_id", pd.Series(dtype=float)).dropna().unique()
    ]
    if ambito_values:
        for ambito_id in sorted(ambito_values):
            if not include_foreign and int(float(ambito_id)) == 2:
                continue
            ambito_df = scoped[scoped["ambito_geografico_id"] == ambito_id]
            level = (
                _finest_foreign_level(ambito_df)
                if int(float(ambito_id)) == 2
                else _finest_level(ambito_df)
            )
            if level is not None:
                selected_parts.append(ambito_df[ambito_df["nivel"] == level])
    else:
        level = _finest_level(scoped)
        if level is not None:
            selected_parts.append(scoped[scoped["nivel"] == level])

    if selected_parts:
        return pd.concat(selected_parts, ignore_index=True)

    national = scoped[scoped["nivel"] == "eleccion"]
    if not national.empty:
        return national.head(1).copy()
    raise ValueError("No usable projection rows found in dataset")


def _finest_level(df: pd.DataFrame) -> str | None:
    for level in LEVEL_ORDER:
        if not df[df["nivel"] == level].empty:
            return level
    return None


def _finest_foreign_level(df: pd.DataFrame) -> str | None:
    for level in ["provincia", "departamento", "ambito_geografico"]:
        if not df[df["nivel"] == level].empty:
            return level
    return None


def _find_fallback(df: pd.DataFrame, unit: pd.Series) -> Fallback | None:
    for level in _fallback_levels(str(unit.get("nivel"))):
        candidate = _fallback_candidate(df, unit, level)
        if candidate is None:
            continue
        counted = _num(candidate.get("actas_contabilizadas"))
        valid = _num(candidate.get("total_votos_validos"))
        keiko = _num(candidate.get("keiko_votes"))
        sanchez = _num(candidate.get("sanchez_votes"))
        vote_sum = keiko + sanchez
        if counted <= 0 or valid <= 0 or vote_sum <= 0:
            continue
        return Fallback(
            level=level,
            keiko_share=keiko / vote_sum,
            sanchez_share=sanchez / vote_sum,
            valid_votes_per_acta=valid / counted,
            keiko_alpha=keiko + 1.0,
            sanchez_alpha=sanchez + 1.0,
        )
    return None


def _fallback_levels(level: str) -> list[str]:
    if level == "distrito":
        return ["provincia", "departamento", "ambito_geografico", "eleccion"]
    if level == "provincia":
        return ["departamento", "ambito_geografico", "eleccion"]
    if level == "departamento":
        return ["ambito_geografico", "eleccion"]
    if level == "ambito_geografico":
        return ["eleccion"]
    return ["eleccion"]


def _fallback_candidate(
    df: pd.DataFrame, unit: pd.Series, level: str
) -> pd.Series | None:
    matches = df[df["nivel"] == level]
    if level != "eleccion":
        matches = matches[
            matches["ambito_geografico_id"] == unit.get("ambito_geografico_id")
        ]
    if level in {"departamento", "provincia"}:
        matches = matches[matches["departamento_ubigeo"] == unit.get("departamento_ubigeo")]
    if level == "provincia":
        matches = matches[matches["provincia_ubigeo"] == unit.get("provincia_ubigeo")]
    if matches.empty:
        return None
    return matches.iloc[0]


def _coerce_numeric(df: pd.DataFrame) -> pd.DataFrame:
    numeric_columns = [
        "ambito_geografico_id",
        "keiko_votes",
        "sanchez_votes",
        "total_votos_validos",
        "total_votos_emitidos",
        "actas_contabilizadas",
        "total_actas",
    ]
    for column in numeric_columns:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")
    return df


def _num(value: Any) -> float:
    if value is None or pd.isna(value):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _safe_int(value: Any) -> int | None:
    if value is None or pd.isna(value):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _pct(value: float, denominator: float) -> float | None:
    if denominator <= 0:
        return None
    return 100.0 * value / denominator


def _winner(keiko: float, sanchez: float) -> str:
    if keiko > sanchez:
        return "Keiko Fujimori"
    if sanchez > keiko:
        return "Roberto Sanchez"
    return "Tie"


def _print_projection(result: dict[str, Any]) -> None:
    print("Projection summary:")
    fields = [
        "current_keiko_votes",
        "current_sanchez_votes",
        "current_margin_sanchez_minus_keiko",
        "projected_keiko_votes",
        "projected_sanchez_votes",
        "projected_keiko_pct",
        "projected_sanchez_pct",
        "projected_margin_sanchez_minus_keiko",
        "projected_winner",
        "total_missing_actas",
        "projected_missing_valid_votes",
        "rows_with_fallback",
        "foreign_unprojected_actas",
        "foreign_fallback_actas",
        "foreign_current_keiko_votes",
        "foreign_current_sanchez_votes",
        "foreign_projected_keiko_votes",
        "foreign_projected_sanchez_votes",
        "foreign_eligible_continents",
    ]
    for field in fields:
        print(f"- {field}: {result[field]}")
    print("Top 20 units by missing_valid_votes_est:")
    print(result["top_missing_units"].to_string(index=False))
