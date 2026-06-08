"""Build a static GitHub Pages dashboard from ONPE results."""

from __future__ import annotations

import argparse
import json
import logging
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from onpe_client import BASE_URL, ONPEClient, ONPEClientError
from projection import bootstrap_projection, project_results
from scraper import scrape_geography

LOGGER = logging.getLogger(__name__)


FOREIGN_NOTE_DEFAULT = (
    "No se incluyen votos del extranjero en la proyección porque sus actas aún "
    "no han sido contabilizadas; el modelo no inventa votos para ese ámbito."
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build static ONPE dashboard")
    parser.add_argument(
        "--max-level",
        choices=["departamento", "provincia", "distrito"],
        default="provincia",
        help="Maximum geography level to scrape",
    )
    parser.add_argument(
        "--output-dir",
        default="site",
        help="Directory where static site files will be written",
    )
    parser.add_argument(
        "--foreign-fallback",
        choices=["none", "national", "manual"],
        default="none",
        help="Fallback policy for foreign rows with zero counted actas",
    )
    parser.add_argument(
        "--bootstrap-sims",
        type=int,
        default=5000,
        help="Number of bootstrap simulations; use 0 to skip",
    )
    parser.add_argument(
        "--include-foreign",
        action="store_true",
        help="Include foreign geography in scrape and projection",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.2,
        help="Minimum seconds between API requests",
    )
    parser.add_argument(
        "--non-json-retries",
        type=int,
        default=8,
        help="Retries when ONPE returns HTML instead of JSON",
    )
    parser.add_argument(
        "--base-url",
        default=BASE_URL,
        help="ONPE API base URL",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    client = ONPEClient(
        base_url=args.base_url,
        sleep_seconds=args.sleep,
        non_json_retries=args.non_json_retries,
    )
    try:
        df = scrape_geography(
            client=client,
            include_peru=True,
            include_foreign=args.include_foreign,
            max_level=args.max_level,
            save_snapshot=False,
        )
    except ONPEClientError as exc:
        raise SystemExit(f"ONPE API error: {exc}") from None

    build_site(
        df=df,
        output_dir=Path(args.output_dir),
        max_level=args.max_level,
        include_foreign=args.include_foreign,
        foreign_fallback=args.foreign_fallback,
        bootstrap_sims=args.bootstrap_sims,
    )


def build_site(
    *,
    df: pd.DataFrame,
    output_dir: Path,
    max_level: str,
    include_foreign: bool,
    foreign_fallback: str,
    bootstrap_sims: int,
) -> dict[str, Any]:
    """Write latest CSV, latest JSON, and index HTML to ``output_dir``."""

    output_dir.mkdir(parents=True, exist_ok=True)
    data_dir = output_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    projection = project_results(
        df,
        include_foreign=include_foreign,
        foreign_fallback=foreign_fallback,
        print_output=False,
    )
    bootstrap = (
        bootstrap_projection(
            df,
            n_sim=bootstrap_sims,
            include_foreign=include_foreign,
            foreign_fallback=foreign_fallback,
        )
        if bootstrap_sims > 0
        else None
    )

    latest_csv = data_dir / "latest.csv"
    df.to_csv(latest_csv, index=False)

    payload = build_payload(
        df=df,
        projection=projection,
        bootstrap=bootstrap,
        max_level=max_level,
        include_foreign=include_foreign,
        foreign_fallback=foreign_fallback,
        bootstrap_sims=bootstrap_sims,
    )

    latest_json = data_dir / "latest.json"
    latest_json.write_text(
        json.dumps(to_jsonable(payload), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    index_html = output_dir / "index.html"
    index_html.write_text(render_html(payload), encoding="utf-8")

    LOGGER.info("Wrote %s", latest_csv)
    LOGGER.info("Wrote %s", latest_json)
    LOGGER.info("Wrote %s", index_html)
    return payload


def build_payload(
    *,
    df: pd.DataFrame,
    projection: dict[str, Any],
    bootstrap: dict[str, Any] | None,
    max_level: str,
    include_foreign: bool,
    foreign_fallback: str,
    bootstrap_sims: int,
) -> dict[str, Any]:
    """Build a JSON-serializable dashboard payload."""

    national = _first_row(df, "eleccion")
    peru = _first_row(df, "ambito_geografico")
    snapshot_ts = str(df["snapshot_ts"].dropna().iloc[0])
    scrape_dt = _parse_snapshot_ts(snapshot_ts)
    onpe_updated_at = _onpe_updated_at(national)
    next_update = scrape_dt + timedelta(minutes=10)

    summary = {
        "current_keiko_votes": projection["current_keiko_votes"],
        "current_sanchez_votes": projection["current_sanchez_votes"],
        "current_margin_sanchez_minus_keiko": projection[
            "current_margin_sanchez_minus_keiko"
        ],
        "projected_keiko_votes": projection["projected_keiko_votes"],
        "projected_sanchez_votes": projection["projected_sanchez_votes"],
        "projected_keiko_pct": projection["projected_keiko_pct"],
        "projected_sanchez_pct": projection["projected_sanchez_pct"],
        "projected_margin_sanchez_minus_keiko": projection[
            "projected_margin_sanchez_minus_keiko"
        ],
        "projected_winner": projection["projected_winner"],
        "actas_contabilizadas_pct": _value(peru, "actas_contabilizadas_pct"),
        "actas_contabilizadas": _value(peru, "actas_contabilizadas"),
        "total_actas": _value(peru, "total_actas"),
        "actas_pendientes_jee": _value(peru, "actas_pendientes_jee"),
        "actas_enviadas_jee": _value(peru, "actas_enviadas_jee"),
        "total_missing_actas": projection["total_missing_actas"],
        "projected_missing_valid_votes": projection["projected_missing_valid_votes"],
    }

    payload = {
        "metadata": {
            "snapshot_ts": snapshot_ts,
            "scrape_timestamp_iso": scrape_dt.isoformat(),
            "onpe_updated_at_iso": onpe_updated_at.isoformat()
            if onpe_updated_at
            else None,
            "next_update_approx_iso": next_update.isoformat(),
            "max_level": max_level,
            "include_foreign": include_foreign,
            "foreign_fallback": foreign_fallback,
            "bootstrap_sims": bootstrap_sims,
            "latest_csv": "data/latest.csv",
            "latest_json": "data/latest.json",
            "foreign_note": _foreign_note(include_foreign, df),
        },
        "summary": summary,
        "projection": {
            key: value
            for key, value in projection.items()
            if key not in {"top_missing_units", "projection_units"}
        },
        "bootstrap": bootstrap,
        "top_missing_provinces": _top_missing_records(projection),
        "department_table": _department_records(df),
        "methodology": {
            "title": "Metodología en simple",
            "bullets": [
                "No extrapolamos el resultado nacional directamente.",
                "Miramos provincia por provincia porque las actas no llegan al mismo ritmo en todo el país.",
                "Para las actas faltantes de una provincia, asumimos que se parecen a las actas ya contabilizadas en esa misma provincia.",
                "Si una provincia aún no tiene datos suficientes, usamos un nivel más agregado como respaldo.",
                "El bootstrap no predice el futuro: muestra qué tan sensible es la proyección si lo que falta se mueve un poco.",
            ],
        },
        "disclaimer": (
            "Esto no es resultado oficial, no reemplaza a ONPE y no es "
            "recomendación de apuestas."
        ),
    }
    return to_jsonable(payload)


def render_html(payload: dict[str, Any]) -> str:
    """Render the static dashboard HTML."""

    data_json = json.dumps(to_jsonable(payload), ensure_ascii=False)
    return f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Proyección electoral Perú 2026</title>
  <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f6f7fb;
      --card: #ffffff;
      --ink: #172033;
      --muted: #64748b;
      --border: #dbe3ef;
      --keiko: #f97316;
      --sanchez: #2563eb;
      --accent: #0f766e;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--ink);
    }}
    header {{
      padding: 32px 20px;
      background: linear-gradient(135deg, #111827, #1d4ed8);
      color: white;
    }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 24px 20px 48px; }}
    h1, h2, h3 {{ margin: 0 0 12px; }}
    p {{ line-height: 1.5; }}
    .hero {{ max-width: 1180px; margin: 0 auto; }}
    .hero p {{ color: #dbeafe; max-width: 760px; }}
    .grid {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; }}
    .card {{
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 16px;
      padding: 16px;
      box-shadow: 0 8px 30px rgba(15, 23, 42, 0.06);
    }}
    .metric-label {{ color: var(--muted); font-size: 13px; margin-bottom: 8px; }}
    .metric-value {{ font-size: 26px; font-weight: 800; }}
    .metric-sub {{ color: var(--muted); font-size: 13px; margin-top: 6px; }}
    .section {{ margin-top: 22px; }}
    .two-col {{ display: grid; grid-template-columns: 1.1fr 0.9fr; gap: 16px; }}
    .note {{
      border-left: 4px solid var(--accent);
      background: #ecfdf5;
      padding: 14px 16px;
      border-radius: 12px;
    }}
    .warning {{
      border-left: 4px solid #f59e0b;
      background: #fffbeb;
      padding: 14px 16px;
      border-radius: 12px;
    }}
    table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
    th, td {{ padding: 10px 8px; border-bottom: 1px solid var(--border); text-align: right; }}
    th:first-child, td:first-child {{ text-align: left; }}
    th {{ color: var(--muted); font-weight: 700; }}
    .plot {{ min-height: 360px; }}
    .muted {{ color: var(--muted); }}
    .links a {{ color: #bfdbfe; margin-right: 14px; }}
    @media (max-width: 920px) {{
      .grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .two-col {{ grid-template-columns: 1fr; }}
    }}
    @media (max-width: 560px) {{
      .grid {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <header>
    <div class="hero">
      <h1>Proyección electoral Perú 2026</h1>
      <p>Dashboard estático generado con datos públicos de ONPE. Actualiza aproximadamente cada 10 minutos cuando GitHub Actions está activo.</p>
      <p class="links"><a href="data/latest.json">latest.json</a><a href="data/latest.csv">latest.csv</a></p>
    </div>
  </header>
  <main>
    <section class="grid" id="metrics"></section>

    <section class="section two-col">
      <div class="card">
        <h2>Votos actuales vs proyectados</h2>
        <div id="votes-chart" class="plot"></div>
      </div>
      <div class="card">
        <h2>Estado de actualización</h2>
        <p><strong>Scrape:</strong> <span id="scrape-time"></span></p>
        <p><strong>Actualización ONPE:</strong> <span id="onpe-time"></span></p>
        <p><strong>Próxima actualización aproximada:</strong> <span id="countdown"></span></p>
        <div class="warning" id="foreign-note"></div>
      </div>
    </section>

    <section class="section card">
      <h2>Proyección alternativa: simulación bootstrap</h2>
      <p class="muted">Simulamos miles de escenarios donde las actas faltantes pueden moverse un poco alrededor del patrón observado.</p>
      <div class="grid" id="bootstrap-metrics"></div>
    </section>

    <section class="section card">
      <h2>Top 20 provincias con más votos faltantes estimados</h2>
      <div id="missing-chart" class="plot"></div>
      <div id="top-table"></div>
    </section>

    <section class="section card">
      <h2>Tabla por departamento</h2>
      <div id="department-table"></div>
    </section>

    <section class="section two-col">
      <div class="card">
        <h2>Metodología en simple</h2>
        <ul id="methodology"></ul>
      </div>
      <div class="card">
        <h2>Disclaimer</h2>
        <p id="disclaimer"></p>
      </div>
    </section>
  </main>

  <script>
    const DATA = {data_json};

    const fmtNumber = (value) => {{
      if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
      return new Intl.NumberFormat("es-PE", {{ maximumFractionDigits: 0 }}).format(Number(value));
    }};
    const fmtPct = (value) => {{
      if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
      return `${{Number(value).toFixed(2)}}%`;
    }};
    const fmtMargin = (value) => {{
      const n = Number(value || 0);
      const label = n >= 0 ? "Sánchez +" : "Keiko +";
      return `${{label}}${{fmtNumber(Math.abs(n))}}`;
    }};
    const fmtDate = (iso) => iso ? new Date(iso).toLocaleString("es-PE") : "—";

    function metric(label, value, sub = "") {{
      return `<article class="card"><div class="metric-label">${{label}}</div><div class="metric-value">${{value}}</div><div class="metric-sub">${{sub}}</div></article>`;
    }}

    function renderMetrics() {{
      const s = DATA.summary;
      document.getElementById("metrics").innerHTML = [
        metric("Keiko actual", fmtNumber(s.current_keiko_votes), "votos contabilizados"),
        metric("Sánchez actual", fmtNumber(s.current_sanchez_votes), "votos contabilizados"),
        metric("Keiko proyectado", fmtNumber(s.projected_keiko_votes), fmtPct(s.projected_keiko_pct)),
        metric("Sánchez proyectado", fmtNumber(s.projected_sanchez_votes), fmtPct(s.projected_sanchez_pct)),
        metric("Margen actual", fmtMargin(s.current_margin_sanchez_minus_keiko), "Sánchez - Keiko"),
        metric("Margen proyectado", fmtMargin(s.projected_margin_sanchez_minus_keiko), DATA.projection.projected_winner),
        metric("Actas contabilizadas", fmtPct(s.actas_contabilizadas_pct), `${{fmtNumber(s.actas_contabilizadas)}} de ${{fmtNumber(s.total_actas)}}`),
        metric("Actas pendientes", fmtNumber(s.actas_pendientes_jee), "pendientes según ONPE"),
        metric("Actas enviadas JEE", fmtNumber(s.actas_enviadas_jee), "observadas o por resolver"),
      ].join("");
    }}

    function renderVotesChart() {{
      const s = DATA.summary;
      Plotly.newPlot("votes-chart", [
        {{ x: ["Keiko", "Sánchez"], y: [s.current_keiko_votes, s.current_sanchez_votes], name: "Actual", type: "bar", marker: {{ color: ["#f97316", "#2563eb"] }} }},
        {{ x: ["Keiko", "Sánchez"], y: [s.projected_keiko_votes, s.projected_sanchez_votes], name: "Proyectado", type: "bar", marker: {{ color: ["#fdba74", "#93c5fd"] }} }}
      ], {{ barmode: "group", margin: {{ t: 20, r: 10, b: 50, l: 70 }} }}, {{ responsive: true, displayModeBar: false }});
    }}

    function renderBootstrap() {{
      const b = DATA.bootstrap;
      if (!b) {{
        document.getElementById("bootstrap-metrics").innerHTML = metric("Bootstrap", "No ejecutado", "");
        return;
      }}
      document.getElementById("bootstrap-metrics").innerHTML = [
        metric("Prob. Keiko", fmtPct(b.probability_keiko_wins * 100), "simulación"),
        metric("Prob. Sánchez", fmtPct(b.probability_sanchez_wins * 100), "simulación"),
        metric("Margen mediano", fmtMargin(b.margin_p50), "p50"),
        metric("Rango probable", `${{fmtMargin(b.margin_p2_5)}} a ${{fmtMargin(b.margin_p97_5)}}`, "p2.5 a p97.5"),
      ].join("");
    }}

    function renderMissing() {{
      const rows = DATA.top_missing_provinces || [];
      Plotly.newPlot("missing-chart", [{{
        x: rows.map(r => r.missing_valid_votes_est),
        y: rows.map(r => `${{r.provincia_nombre || ""}}, ${{r.departamento_nombre || ""}}`),
        type: "bar",
        orientation: "h",
        marker: {{ color: "#0f766e" }}
      }}], {{
        margin: {{ t: 10, r: 20, b: 50, l: 180 }},
        yaxis: {{ autorange: "reversed" }}
      }}, {{ responsive: true, displayModeBar: false }});
      document.getElementById("top-table").innerHTML = renderTable(rows, [
        ["Provincia", r => r.provincia_nombre],
        ["Departamento", r => r.departamento_nombre],
        ["Actas faltantes", r => fmtNumber(r.missing_actas)],
        ["Votos faltantes est.", r => fmtNumber(r.missing_valid_votes_est)],
      ]);
    }}

    function renderDepartments() {{
      document.getElementById("department-table").innerHTML = renderTable(DATA.department_table || [], [
        ["Departamento", r => r.departamento_nombre],
        ["Keiko", r => fmtNumber(r.keiko_votes)],
        ["Sánchez", r => fmtNumber(r.sanchez_votes)],
        ["Votos válidos", r => fmtNumber(r.total_votos_validos)],
        ["Actas cont.", r => fmtPct(r.actas_contabilizadas_pct)],
        ["Pendientes", r => fmtNumber(r.actas_pendientes_jee)],
        ["JEE", r => fmtNumber(r.actas_enviadas_jee)],
      ]);
    }}

    function renderTable(rows, columns) {{
      const head = `<thead><tr>${{columns.map(([name]) => `<th>${{name}}</th>`).join("")}}</tr></thead>`;
      const body = `<tbody>${{rows.map(row => `<tr>${{columns.map(([, fn]) => `<td>${{fn(row) ?? "—"}}</td>`).join("")}}</tr>`).join("")}}</tbody>`;
      return `<table>${{head}}${{body}}</table>`;
    }}

    function renderText() {{
      document.getElementById("scrape-time").textContent = fmtDate(DATA.metadata.scrape_timestamp_iso);
      document.getElementById("onpe-time").textContent = fmtDate(DATA.metadata.onpe_updated_at_iso);
      document.getElementById("foreign-note").textContent = DATA.metadata.foreign_note;
      document.getElementById("methodology").innerHTML = DATA.methodology.bullets.map(item => `<li>${{item}}</li>`).join("");
      document.getElementById("disclaimer").textContent = DATA.disclaimer;
    }}

    function startCountdown() {{
      const target = new Date(DATA.metadata.next_update_approx_iso).getTime();
      const el = document.getElementById("countdown");
      const tick = () => {{
        const diff = target - Date.now();
        if (diff <= 0) {{
          el.textContent = "actualizando pronto...";
          setTimeout(() => window.location.reload(), 60000);
          return;
        }}
        const minutes = Math.floor(diff / 60000);
        const seconds = Math.floor((diff % 60000) / 1000);
        el.textContent = `${{minutes}}m ${{seconds.toString().padStart(2, "0")}}s`;
      }};
      tick();
      setInterval(tick, 1000);
    }}

    renderMetrics();
    renderVotesChart();
    renderBootstrap();
    renderMissing();
    renderDepartments();
    renderText();
    startCountdown();
  </script>
</body>
</html>
"""


def _top_missing_records(projection: dict[str, Any]) -> list[dict[str, Any]]:
    units = projection["projection_units"].copy()
    if "provincia_nombre" not in units.columns:
        return []
    units = units.sort_values("missing_valid_votes_est", ascending=False).head(20)
    columns = [
        "departamento_nombre",
        "provincia_nombre",
        "missing_actas",
        "missing_valid_votes_est",
        "used_fallback",
        "fallback_level",
    ]
    return units[[column for column in columns if column in units.columns]].to_dict(
        orient="records"
    )


def _department_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    departments = df[df["nivel"] == "departamento"].copy()
    if departments.empty:
        return []
    departments = departments.sort_values("departamento_nombre")
    columns = [
        "departamento_nombre",
        "keiko_votes",
        "sanchez_votes",
        "keiko_pct_valid",
        "sanchez_pct_valid",
        "total_votos_validos",
        "actas_contabilizadas_pct",
        "actas_pendientes_jee",
        "actas_enviadas_jee",
    ]
    return departments[[column for column in columns if column in departments.columns]].to_dict(
        orient="records"
    )


def _first_row(df: pd.DataFrame, nivel: str) -> pd.Series:
    rows = df[df["nivel"] == nivel]
    if rows.empty:
        return pd.Series(dtype=object)
    return rows.iloc[0]


def _value(row: pd.Series, column: str) -> Any:
    if row.empty or column not in row:
        return None
    return row[column]


def _parse_snapshot_ts(snapshot_ts: str) -> datetime:
    return datetime.strptime(snapshot_ts, "%Y%m%d_%H%M%S").replace(
        tzinfo=timezone.utc
    )


def _onpe_updated_at(row: pd.Series) -> datetime | None:
    value = _value(row, "fecha_actualizacion")
    if value is None or pd.isna(value):
        return None
    return datetime.fromtimestamp(float(value) / 1000, timezone.utc)


def _foreign_note(include_foreign: bool, df: pd.DataFrame) -> str:
    if not include_foreign:
        return FOREIGN_NOTE_DEFAULT
    foreign = df[df.get("ambito_geografico_id") == 2]
    if foreign.empty:
        return FOREIGN_NOTE_DEFAULT
    counted = pd.to_numeric(foreign.get("actas_contabilizadas"), errors="coerce").fillna(0).sum()
    if counted <= 0:
        return FOREIGN_NOTE_DEFAULT
    return (
        "El scrape incluye extranjero porque ya hay actas contabilizadas o el "
        "usuario lo activó explícitamente."
    )


def to_jsonable(value: Any) -> Any:
    """Convert pandas/numpy values to JSON-safe builtins, replacing NaN with None."""

    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [to_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [to_jsonable(item) for item in value]
    if isinstance(value, pd.DataFrame):
        return to_jsonable(value.to_dict(orient="records"))
    if isinstance(value, pd.Series):
        return to_jsonable(value.to_dict())
    if pd.isna(value):
        return None
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


if __name__ == "__main__":
    main()
