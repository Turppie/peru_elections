"""Scraping, parsing, and dataset validation for ONPE summaries."""

from __future__ import annotations

import logging
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from onpe_client import ID_ELECCION, ONPEClient

LOGGER = logging.getLogger(__name__)

AMBITOS = {
    1: "PERU",
    2: "EXTRANJERO",
}

MAX_LEVELS = {
    "departamento": 1,
    "provincia": 2,
    "distrito": 3,
}

DATA_COLUMNS = [
    "snapshot_ts",
    "ambito_geografico_id",
    "ambito_geografico_nombre",
    "nivel",
    "departamento_ubigeo",
    "departamento_nombre",
    "provincia_ubigeo",
    "provincia_nombre",
    "distrito_ubigeo",
    "distrito_nombre",
    "keiko_votes",
    "sanchez_votes",
    "keiko_pct_valid",
    "sanchez_pct_valid",
    "total_votos_validos",
    "total_votos_emitidos",
    "actas_contabilizadas",
    "total_actas",
    "actas_contabilizadas_pct",
    "actas_enviadas_jee",
    "actas_pendientes_jee",
    "participacion_ciudadana_pct",
    "fecha_actualizacion",
]

PARTICIPANTE_COLUMNS = [
    "keiko_votes",
    "keiko_pct_valid",
    "keiko_pct_emitidos",
    "keiko_candidate",
    "keiko_party",
    "sanchez_votes",
    "sanchez_pct_valid",
    "sanchez_pct_emitidos",
    "sanchez_candidate",
    "sanchez_party",
]


def build_resumen_params(
    nivel: str,
    id_ambito_geografico: int | None = None,
    dep: str | None = None,
    prov: str | None = None,
    dist: str | None = None,
) -> dict[str, Any]:
    """Build params for ONPE resumen-general endpoints."""

    if nivel == "eleccion":
        return {"idEleccion": ID_ELECCION, "tipoFiltro": "eleccion"}

    if nivel == "ambito_geografico":
        _require(id_ambito_geografico, "id_ambito_geografico")
        return {
            "idEleccion": ID_ELECCION,
            "tipoFiltro": "ambito_geografico",
            "idAmbitoGeografico": id_ambito_geografico,
        }

    if nivel == "departamento":
        _require(id_ambito_geografico, "id_ambito_geografico")
        _require(dep, "dep")
        return {
            "idEleccion": ID_ELECCION,
            "tipoFiltro": "ubigeo_nivel_01",
            "idAmbitoGeografico": id_ambito_geografico,
            "idUbigeoDepartamento": dep,
        }

    if nivel == "provincia":
        _require(id_ambito_geografico, "id_ambito_geografico")
        _require(dep, "dep")
        _require(prov, "prov")
        return {
            "idEleccion": ID_ELECCION,
            "tipoFiltro": "ubigeo_nivel_02",
            "idAmbitoGeografico": id_ambito_geografico,
            "idUbigeoDepartamento": dep,
            "idUbigeoProvincia": prov,
        }

    if nivel == "distrito":
        _require(id_ambito_geografico, "id_ambito_geografico")
        _require(dep, "dep")
        _require(prov, "prov")
        _require(dist, "dist")
        return {
            "idEleccion": ID_ELECCION,
            "tipoFiltro": "ubigeo_nivel_03",
            "idAmbitoGeografico": id_ambito_geografico,
            "idUbigeoDepartamento": dep,
            "idUbigeoProvincia": prov,
            "idUbigeoDistrito": dist,
        }

    raise ValueError(f"Unsupported nivel: {nivel}")


def parse_participantes(payload: Any) -> dict[str, Any]:
    """Parse participant rows without relying on candidate order."""

    participantes = _unwrap_data(payload)
    result = {column: None for column in PARTICIPANTE_COLUMNS}
    if not isinstance(participantes, list):
        return result

    for participante in participantes:
        if not isinstance(participante, Mapping):
            continue
        party = participante.get("nombreAgrupacionPolitica")
        candidate = participante.get("nombreCandidato")
        code = _safe_int(participante.get("codigoAgrupacionPolitica"))

        if _is_keiko(participante, code):
            _fill_participant(result, "keiko", participante, party, candidate)
        elif _is_sanchez(participante, code):
            _fill_participant(result, "sanchez", participante, party, candidate)

    return result


def parse_totales(payload: Any) -> dict[str, Any]:
    """Parse ONPE totals into snake_case fields."""

    totales = _unwrap_data(payload)
    if not isinstance(totales, Mapping):
        totales = {}
    return {
        "actas_contabilizadas_pct": _safe_float(totales.get("actasContabilizadas")),
        "actas_contabilizadas": _safe_float(totales.get("contabilizadas")),
        "total_actas": _safe_float(totales.get("totalActas")),
        "participacion_ciudadana_pct": _safe_float(
            totales.get("participacionCiudadana")
        ),
        "actas_enviadas_jee_pct": _safe_float(totales.get("actasEnviadasJee")),
        "actas_enviadas_jee": _safe_float(totales.get("enviadasJee")),
        "actas_pendientes_jee_pct": _safe_float(totales.get("actasPendientesJee")),
        "actas_pendientes_jee": _safe_float(totales.get("pendientesJee")),
        "fecha_actualizacion": totales.get("fechaActualizacion"),
        "total_votos_emitidos": _safe_float(totales.get("totalVotosEmitidos")),
        "total_votos_validos": _safe_float(totales.get("totalVotosValidos")),
        "porcentaje_votos_emitidos": _safe_float(
            totales.get("porcentajeVotosEmitidos")
        ),
        "porcentaje_votos_validos": _safe_float(totales.get("porcentajeVotosValidos")),
    }


def scrape_geography(
    client: ONPEClient | None = None,
    include_peru: bool = True,
    include_foreign: bool = True,
    max_level: str = "distrito",
    foreign_max_level: str | None = None,
    output_dir: str | Path = "data",
    save_snapshot: bool = True,
) -> pd.DataFrame:
    """Scrape national, scope, and geographic ONPE summaries into a snapshot CSV."""

    if max_level not in MAX_LEVELS:
        raise ValueError("max_level must be one of: departamento, provincia, distrito")
    if foreign_max_level is not None and foreign_max_level not in MAX_LEVELS:
        raise ValueError(
            "foreign_max_level must be one of: departamento, provincia, distrito"
        )

    client = client or ONPEClient()
    client.check_api_available()
    snapshot_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    rows: list[dict[str, Any]] = []

    rows.append(
        _summary_row(
            client,
            snapshot_ts=snapshot_ts,
            nivel="eleccion",
            params=build_resumen_params("eleccion"),
        )
    )

    ambitos_to_scrape: list[int] = []
    if include_peru:
        ambitos_to_scrape.append(1)
    if include_foreign:
        ambitos_to_scrape.append(2)

    for ambito_id in ambitos_to_scrape:
        ambito_nombre = AMBITOS.get(ambito_id, str(ambito_id))
        scope_max_level = (
            foreign_max_level if ambito_id == 2 and foreign_max_level else max_level
        )
        LOGGER.info("Scraping ambito %s %s", ambito_id, ambito_nombre)
        rows.append(
            _summary_row(
                client,
                snapshot_ts=snapshot_ts,
                nivel="ambito_geografico",
                ambito_geografico_id=ambito_id,
                ambito_geografico_nombre=ambito_nombre,
                params=build_resumen_params("ambito_geografico", ambito_id),
            )
        )

        departamentos = client.get_departamentos(ambito_id)
        for dep_row in departamentos:
            dep = str(dep_row.get("ubigeo"))
            dep_nombre = dep_row.get("nombre")
            rows.append(
                _summary_row(
                    client,
                    snapshot_ts=snapshot_ts,
                    nivel="departamento",
                    ambito_geografico_id=ambito_id,
                    ambito_geografico_nombre=ambito_nombre,
                    departamento_ubigeo=dep,
                    departamento_nombre=dep_nombre,
                    params=build_resumen_params("departamento", ambito_id, dep=dep),
                )
            )

            if MAX_LEVELS[scope_max_level] < 2:
                continue

            provincias = client.get_provincias(ambito_id, dep)
            for prov_row in provincias:
                prov = str(prov_row.get("ubigeo"))
                prov_nombre = prov_row.get("nombre")
                rows.append(
                    _summary_row(
                        client,
                        snapshot_ts=snapshot_ts,
                        nivel="provincia",
                        ambito_geografico_id=ambito_id,
                        ambito_geografico_nombre=ambito_nombre,
                        departamento_ubigeo=dep,
                        departamento_nombre=dep_nombre,
                        provincia_ubigeo=prov,
                        provincia_nombre=prov_nombre,
                        params=build_resumen_params(
                            "provincia", ambito_id, dep=dep, prov=prov
                        ),
                    )
                )

                if MAX_LEVELS[scope_max_level] < 3:
                    continue

                distritos = client.get_distritos(ambito_id, prov)
                for dist_row in distritos:
                    dist = str(dist_row.get("ubigeo"))
                    rows.append(
                        _summary_row(
                            client,
                            snapshot_ts=snapshot_ts,
                            nivel="distrito",
                            ambito_geografico_id=ambito_id,
                            ambito_geografico_nombre=ambito_nombre,
                            departamento_ubigeo=dep,
                            departamento_nombre=dep_nombre,
                            provincia_ubigeo=prov,
                            provincia_nombre=prov_nombre,
                            distrito_ubigeo=dist,
                            distrito_nombre=dist_row.get("nombre"),
                            params=build_resumen_params(
                                "distrito",
                                ambito_id,
                                dep=dep,
                                prov=prov,
                                dist=dist,
                            ),
                        )
                    )

    df = pd.DataFrame(rows)
    df = df.reindex(columns=DATA_COLUMNS + _extra_columns(df, DATA_COLUMNS))

    validate_dataset(df)

    if save_snapshot:
        output_path = Path(output_dir) / f"onpe_resumen_geografico_{snapshot_ts}.csv"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(output_path, index=False)
        df.attrs["output_path"] = str(output_path)
        LOGGER.info("Saved snapshot CSV: %s", output_path)
    return df


def validate_dataset(df: pd.DataFrame) -> pd.DataFrame:
    """Return a marked validation copy and print a compact warning summary."""

    marked = df.copy()
    numeric_columns = [
        "keiko_votes",
        "sanchez_votes",
        "total_votos_validos",
        "actas_contabilizadas",
        "total_actas",
    ]
    for column in numeric_columns:
        marked[column] = pd.to_numeric(marked.get(column), errors="coerce")

    participant_sum = marked["keiko_votes"].fillna(0) + marked["sanchez_votes"].fillna(0)
    marked["warning_valid_votes_mismatch"] = (
        marked["total_votos_validos"].notna()
        & (marked["total_votos_validos"] > 0)
        & ((participant_sum - marked["total_votos_validos"]).abs() > 1)
    )
    marked["warning_total_votos_validos_zero"] = (
        marked["total_votos_validos"].fillna(0) == 0
    )
    marked["warning_actas_contabilizadas_zero"] = (
        marked["actas_contabilizadas"].fillna(0) == 0
    )
    marked["error_total_actas_null"] = marked["total_actas"].isna()
    marked["error_total_actas_lt_contabilizadas"] = (
        marked["total_actas"].notna()
        & marked["actas_contabilizadas"].notna()
        & (marked["total_actas"] < marked["actas_contabilizadas"])
    )
    marked["warning_participantes_empty"] = (
        marked["keiko_votes"].isna() & marked["sanchez_votes"].isna()
    )

    validation_columns = [
        "warning_valid_votes_mismatch",
        "warning_total_votos_validos_zero",
        "warning_actas_contabilizadas_zero",
        "error_total_actas_null",
        "error_total_actas_lt_contabilizadas",
        "warning_participantes_empty",
    ]
    print("Validation summary:")
    for column in validation_columns:
        print(f"- {column}: {int(marked[column].sum())}")
    return marked


def _summary_row(
    client: ONPEClient,
    *,
    snapshot_ts: str,
    nivel: str,
    params: Mapping[str, Any],
    ambito_geografico_id: int | None = None,
    ambito_geografico_nombre: str | None = None,
    departamento_ubigeo: str | None = None,
    departamento_nombre: str | None = None,
    provincia_ubigeo: str | None = None,
    provincia_nombre: str | None = None,
    distrito_ubigeo: str | None = None,
    distrito_nombre: str | None = None,
) -> dict[str, Any]:
    row = {
        "snapshot_ts": snapshot_ts,
        "ambito_geografico_id": ambito_geografico_id,
        "ambito_geografico_nombre": ambito_geografico_nombre,
        "nivel": nivel,
        "departamento_ubigeo": departamento_ubigeo,
        "departamento_nombre": departamento_nombre,
        "provincia_ubigeo": provincia_ubigeo,
        "provincia_nombre": provincia_nombre,
        "distrito_ubigeo": distrito_ubigeo,
        "distrito_nombre": distrito_nombre,
    }
    try:
        row.update(parse_totales(client.get_totales(params)))
    except Exception:
        LOGGER.exception("Failed to fetch totals for nivel=%s params=%s", nivel, params)
        row.update(parse_totales({}))

    try:
        row.update(parse_participantes(client.get_participantes(params)))
    except Exception:
        LOGGER.exception(
            "Failed to fetch participants for nivel=%s params=%s", nivel, params
        )
        row.update(parse_participantes([]))
    return row


def _fill_participant(
    result: dict[str, Any],
    prefix: str,
    participante: Mapping[str, Any],
    party: Any,
    candidate: Any,
) -> None:
    result[f"{prefix}_votes"] = _safe_float(participante.get("totalVotosValidos"))
    result[f"{prefix}_pct_valid"] = _safe_float(
        participante.get("porcentajeVotosValidos")
    )
    result[f"{prefix}_pct_emitidos"] = _safe_float(
        participante.get("porcentajeVotosEmitidos")
    )
    result[f"{prefix}_candidate"] = candidate
    result[f"{prefix}_party"] = party


def _is_keiko(participante: Mapping[str, Any], code: int | None) -> bool:
    party = _fold_text(participante.get("nombreAgrupacionPolitica"))
    candidate = _fold_text(participante.get("nombreCandidato"))
    return code == 8 or "FUERZA POPULAR" in party or "FUJIMORI" in candidate


def _is_sanchez(participante: Mapping[str, Any], code: int | None) -> bool:
    party = _fold_text(participante.get("nombreAgrupacionPolitica"))
    candidate = _fold_text(participante.get("nombreCandidato"))
    return (
        code == 10
        or "JUNTOS POR EL PERU" in party
        or "SANCHEZ" in candidate
    )


def _unwrap_data(payload: Any) -> Any:
    current = payload
    while isinstance(current, Mapping):
        if "success" in current and "data" in current:
            current = current.get("data")
            continue
        if {"url", "captured_at", "data"}.issubset(set(current.keys())):
            current = current.get("data")
            continue
        break
    return current


def _fold_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).upper()
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _safe_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _require(value: Any, name: str) -> None:
    if value is None:
        raise ValueError(f"{name} is required")


def _extra_columns(df: pd.DataFrame, expected: list[str]) -> list[str]:
    return [column for column in df.columns if column not in expected]
