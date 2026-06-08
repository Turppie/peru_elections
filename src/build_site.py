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
from projection import project_results
from scraper import scrape_geography

LOGGER = logging.getLogger(__name__)


FOREIGN_NOTE_DEFAULT = (
    "El voto extranjero no está incluido en esta publicación. Al activarlo, el "
    "modelo puede usar una política continental conservadora."
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
        choices=["none", "continent", "national", "manual"],
        default="none",
        help="Fallback policy for foreign rows with zero counted actas",
    )
    parser.add_argument(
        "--foreign-continent-min-actas",
        type=int,
        default=10,
        help="Minimum counted actas required to use a continent fallback",
    )
    parser.add_argument(
        "--foreign-continent-min-countries",
        type=int,
        default=2,
        help="Minimum countries with data required to use a continent fallback",
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
            foreign_max_level="provincia",
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
        foreign_continent_min_actas=args.foreign_continent_min_actas,
        foreign_continent_min_countries=args.foreign_continent_min_countries,
    )


def build_site(
    *,
    df: pd.DataFrame,
    output_dir: Path,
    max_level: str,
    include_foreign: bool,
    foreign_fallback: str,
    foreign_continent_min_actas: int = 10,
    foreign_continent_min_countries: int = 2,
) -> dict[str, Any]:
    """Write latest CSV, latest JSON, and index HTML to ``output_dir``."""

    output_dir.mkdir(parents=True, exist_ok=True)
    data_dir = output_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    projection = project_results(
        df,
        include_foreign=include_foreign,
        foreign_fallback=foreign_fallback,
        foreign_continent_min_actas=foreign_continent_min_actas,
        foreign_continent_min_countries=foreign_continent_min_countries,
        print_output=False,
    )
    latest_csv = data_dir / "latest.csv"
    df.to_csv(latest_csv, index=False)

    payload = build_payload(
        df=df,
        projection=projection,
        max_level=max_level,
        include_foreign=include_foreign,
        foreign_fallback=foreign_fallback,
        foreign_continent_min_actas=foreign_continent_min_actas,
        foreign_continent_min_countries=foreign_continent_min_countries,
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
    max_level: str,
    include_foreign: bool,
    foreign_fallback: str,
    foreign_continent_min_actas: int = 10,
    foreign_continent_min_countries: int = 2,
) -> dict[str, Any]:
    """Build a JSON-serializable dashboard payload."""

    national = _first_row(df, "eleccion")
    peru = _scope_row(df, 1, "ambito_geografico")
    status_totals = national if include_foreign and not national.empty else peru
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
        "actas_contabilizadas_pct": _value(
            status_totals, "actas_contabilizadas_pct"
        ),
        "actas_contabilizadas": _value(status_totals, "actas_contabilizadas"),
        "total_actas": _value(status_totals, "total_actas"),
        "actas_pendientes_jee": _value(status_totals, "actas_pendientes_jee"),
        "actas_enviadas_jee": _value(status_totals, "actas_enviadas_jee"),
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
            "foreign_continent_min_actas": foreign_continent_min_actas,
            "foreign_continent_min_countries": foreign_continent_min_countries,
            "latest_csv": "data/latest.csv",
            "latest_json": "data/latest.json",
            "foreign_note": _foreign_note(
                include_foreign,
                foreign_fallback,
                projection,
                foreign_continent_min_actas,
                foreign_continent_min_countries,
            ),
        },
        "summary": summary,
        "projection": {
            key: value
            for key, value in projection.items()
            if key not in {"top_missing_units", "projection_units"}
        },
        "top_missing_provinces": _top_missing_records(projection),
        "department_table": _department_records(df),
        "foreign_summary": _foreign_summary(df, projection),
        "foreign_continents": _foreign_continent_records(df),
        "foreign_countries": _foreign_country_records(projection),
        "methodology": {
            "title": "Metodología en simple",
            "bullets": [
                "No extrapolamos el resultado nacional directamente.",
                "Miramos provincia por provincia porque las actas no llegan al mismo ritmo en todo el país.",
                "Para las actas faltantes de una provincia, asumimos que se parecen a las actas ya contabilizadas en esa misma provincia.",
                "Si una provincia aún no tiene datos suficientes, usamos un nivel más agregado como respaldo.",
                "El voto extranjero ya forma parte de la proyección cuando se activa: cada país usa primero sus propios resultados.",
                "Un país en cero solo usa el patrón de su continente cuando ya hay suficientes actas y varios países con datos.",
                "Si un continente todavía no tiene señal suficiente, dejamos sus actas sin proyectar en vez de inventar votos.",
                "Las actas enviadas al JEE o pendientes pueden cambiar el resultado cuando se resuelvan.",
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
    .table-scroll {{
      width: 100%;
      overflow-x: auto;
      -webkit-overflow-scrolling: touch;
      border: 1px solid var(--border);
      border-radius: 12px;
    }}
    table {{ width: 100%; min-width: 720px; border-collapse: collapse; font-size: 14px; }}
    th, td {{ padding: 10px 8px; border-bottom: 1px solid var(--border); text-align: right; }}
    th:first-child, td:first-child {{ text-align: left; }}
    th {{ color: var(--muted); font-weight: 700; }}
    .plot {{ min-height: 360px; }}
    .muted {{ color: var(--muted); }}
    .links a {{ color: #bfdbfe; margin-right: 14px; }}
    .compact-grid {{ grid-template-columns: repeat(3, minmax(0, 1fr)); }}
    @media (max-width: 920px) {{
      .grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .compact-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .two-col {{ grid-template-columns: 1fr; }}
    }}
    @media (max-width: 560px) {{
      header {{ padding: 24px 16px; }}
      main {{ padding: 18px 12px 36px; }}
      .grid {{ grid-template-columns: 1fr; }}
      .compact-grid {{ grid-template-columns: 1fr; }}
      .card {{ padding: 14px; border-radius: 14px; }}
      .metric-value {{ font-size: 22px; }}
      .plot {{ min-height: 300px; }}
      table {{ min-width: 680px; font-size: 13px; }}
      th, td {{ padding: 9px 7px; }}
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

    <section class="section card" id="foreign-section">
      <h2>Voto extranjero</h2>
      <p id="foreign-explanation" class="note"></p>
      <div class="grid compact-grid section" id="foreign-metrics"></div>
      <div class="section">
        <h3>Resultados por continente</h3>
        <div id="foreign-chart" class="plot"></div>
      </div>
      <div class="section">
        <h3>Países por actas pendientes</h3>
        <div id="foreign-country-table"></div>
      </div>
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

    function renderMissing() {{
      const rows = DATA.top_missing_provinces || [];
      const isMobile = window.innerWidth < 640;
      Plotly.newPlot("missing-chart", [{{
        x: rows.map(r => r.missing_valid_votes_est),
        y: rows.map(r => isMobile ? (r.provincia_nombre || "") : `${{r.provincia_nombre || ""}}, ${{r.departamento_nombre || ""}}`),
        type: "bar",
        orientation: "h",
        marker: {{ color: "#0f766e" }}
      }}], {{
        height: Math.max(320, rows.length * (isMobile ? 25 : 28)),
        margin: {{ t: 10, r: 14, b: 48, l: isMobile ? 100 : 180 }},
        yaxis: {{ autorange: "reversed", automargin: true }}
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

    function renderForeign() {{
      const s = DATA.foreign_summary || {{}};
      const countries = DATA.foreign_countries || [];
      const continents = DATA.foreign_continents || [];
      document.getElementById("foreign-explanation").textContent = DATA.metadata.foreign_note;
      document.getElementById("foreign-metrics").innerHTML = [
        metric("Keiko extranjero actual", fmtNumber(s.current_keiko_votes), fmtPct(s.current_keiko_pct)),
        metric("Sánchez extranjero actual", fmtNumber(s.current_sanchez_votes), fmtPct(s.current_sanchez_pct)),
        metric("Actas extranjeras contabilizadas", fmtPct(s.actas_contabilizadas_pct), `${{fmtNumber(s.actas_contabilizadas)}} de ${{fmtNumber(s.total_actas)}}`),
        metric("Keiko extranjero proyectado", fmtNumber(s.projected_keiko_votes), "incluido en el total nacional"),
        metric("Sánchez extranjero proyectado", fmtNumber(s.projected_sanchez_votes), "incluido en el total nacional"),
        metric("Actas sin proyectar", fmtNumber(s.unprojected_actas), `${{fmtNumber(s.fallback_actas)}} usan fallback continental`),
      ].join("");

      Plotly.newPlot("foreign-chart", [
        {{
          x: continents.map(r => r.departamento_nombre),
          y: continents.map(r => r.keiko_votes),
          name: "Keiko actual",
          type: "bar",
          marker: {{ color: "#f97316" }},
          customdata: continents.map(r => r.actas_contabilizadas_pct),
          hovertemplate: "%{{x}}<br>Keiko: %{{y:,.0f}}<br>Actas: %{{customdata:.2f}}%<extra></extra>"
        }},
        {{
          x: continents.map(r => r.departamento_nombre),
          y: continents.map(r => r.sanchez_votes),
          name: "Sánchez actual",
          type: "bar",
          marker: {{ color: "#2563eb" }},
          customdata: continents.map(r => r.actas_contabilizadas_pct),
          hovertemplate: "%{{x}}<br>Sánchez: %{{y:,.0f}}<br>Actas: %{{customdata:.2f}}%<extra></extra>"
        }},
        {{
          x: continents.map(r => r.departamento_nombre),
          y: continents.map(r => r.actas_contabilizadas_pct),
          name: "% actas contabilizadas",
          type: "scatter",
          mode: "lines+markers",
          yaxis: "y2",
          marker: {{ color: "#0f766e" }},
          line: {{ color: "#0f766e" }},
          hovertemplate: "%{{x}}<br>Actas contabilizadas: %{{y:.2f}}%<extra></extra>"
        }}
      ], {{
        barmode: "group",
        margin: {{ t: 20, r: 55, b: 70, l: 70 }},
        xaxis: {{ automargin: true }},
        yaxis2: {{
          title: "% actas",
          overlaying: "y",
          side: "right",
          range: [0, 100]
        }}
      }}, {{ responsive: true, displayModeBar: false }});

      document.getElementById("foreign-country-table").innerHTML = renderTable(countries, [
        ["País", r => r.provincia_nombre],
        ["Continente", r => r.departamento_nombre],
        ["Actas cont.", r => fmtPct(r.actas_contabilizadas_pct)],
        ["Pendientes", r => fmtNumber(r.missing_actas)],
        ["Keiko actual", r => fmtNumber(r.current_keiko_votes)],
        ["Sánchez actual", r => fmtNumber(r.current_sanchez_votes)],
        ["Keiko proy.", r => fmtNumber(r.projected_keiko_votes)],
        ["Sánchez proy.", r => fmtNumber(r.projected_sanchez_votes)],
        ["Respaldo", r => r.foreign_unprojected ? "Sin proyectar" : (r.fallback_level || "País")],
      ]);
    }}

    function renderTable(rows, columns) {{
      const head = `<thead><tr>${{columns.map(([name]) => `<th>${{name}}</th>`).join("")}}</tr></thead>`;
      const body = `<tbody>${{rows.map(row => `<tr>${{columns.map(([, fn]) => `<td>${{fn(row) ?? "—"}}</td>`).join("")}}</tr>`).join("")}}</tbody>`;
      return `<div class="table-scroll"><table>${{head}}${{body}}</table></div>`;
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
    renderMissing();
    renderDepartments();
    renderForeign();
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
    if "ambito_geografico_id" in units.columns:
        units = units[
            pd.to_numeric(units["ambito_geografico_id"], errors="coerce") == 1
        ]
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
    departments = df[
        (df["nivel"] == "departamento")
        & (pd.to_numeric(df["ambito_geografico_id"], errors="coerce") == 1)
    ].copy()
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


def _foreign_summary(
    df: pd.DataFrame, projection: dict[str, Any]
) -> dict[str, Any]:
    foreign = _scope_row(df, 2, "ambito_geografico")
    current_keiko = float(projection.get("foreign_current_keiko_votes", 0) or 0)
    current_sanchez = float(projection.get("foreign_current_sanchez_votes", 0) or 0)
    current_total = current_keiko + current_sanchez
    return {
        "current_keiko_votes": current_keiko,
        "current_sanchez_votes": current_sanchez,
        "current_keiko_pct": _percent(current_keiko, current_total),
        "current_sanchez_pct": _percent(current_sanchez, current_total),
        "projected_keiko_votes": projection.get("foreign_projected_keiko_votes", 0),
        "projected_sanchez_votes": projection.get(
            "foreign_projected_sanchez_votes", 0
        ),
        "actas_contabilizadas_pct": _value(
            foreign, "actas_contabilizadas_pct"
        ),
        "actas_contabilizadas": _value(foreign, "actas_contabilizadas"),
        "total_actas": _value(foreign, "total_actas"),
        "fallback_actas": projection.get("foreign_fallback_actas", 0),
        "unprojected_actas": projection.get("foreign_unprojected_actas", 0),
        "eligible_continents": projection.get("foreign_eligible_continents", []),
    }


def _foreign_continent_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    continents = df[
        (df["nivel"] == "departamento")
        & (pd.to_numeric(df["ambito_geografico_id"], errors="coerce") == 2)
    ].copy()
    if continents.empty:
        return []
    continents = continents.sort_values("departamento_nombre")
    columns = [
        "departamento_ubigeo",
        "departamento_nombre",
        "keiko_votes",
        "sanchez_votes",
        "total_votos_validos",
        "actas_contabilizadas",
        "total_actas",
        "actas_contabilizadas_pct",
    ]
    return continents[
        [column for column in columns if column in continents.columns]
    ].to_dict(orient="records")


def _foreign_country_records(projection: dict[str, Any]) -> list[dict[str, Any]]:
    units = projection["projection_units"].copy()
    if "ambito_geografico_id" not in units.columns:
        return []
    countries = units[
        (pd.to_numeric(units["ambito_geografico_id"], errors="coerce") == 2)
        & (units["nivel"] == "provincia")
    ].copy()
    if countries.empty:
        return []
    counted = pd.to_numeric(countries["actas_contabilizadas"], errors="coerce")
    total = pd.to_numeric(countries["total_actas"], errors="coerce")
    countries["actas_contabilizadas_pct"] = (
        100 * counted.div(total.where(total > 0))
    )
    countries = countries.sort_values("missing_actas", ascending=False)
    columns = [
        "departamento_nombre",
        "provincia_nombre",
        "actas_contabilizadas",
        "total_actas",
        "actas_contabilizadas_pct",
        "missing_actas",
        "current_keiko_votes",
        "current_sanchez_votes",
        "projected_keiko_votes",
        "projected_sanchez_votes",
        "used_fallback",
        "fallback_level",
        "foreign_unprojected",
    ]
    return countries[
        [column for column in columns if column in countries.columns]
    ].to_dict(orient="records")


def _first_row(df: pd.DataFrame, nivel: str) -> pd.Series:
    rows = df[df["nivel"] == nivel]
    if rows.empty:
        return pd.Series(dtype=object)
    return rows.iloc[0]


def _scope_row(df: pd.DataFrame, ambito_id: int, nivel: str) -> pd.Series:
    rows = df[
        (df["nivel"] == nivel)
        & (pd.to_numeric(df["ambito_geografico_id"], errors="coerce") == ambito_id)
    ]
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


def _foreign_note(
    include_foreign: bool,
    foreign_fallback: str,
    projection: dict[str, Any],
    min_actas: int,
    min_countries: int,
) -> str:
    if not include_foreign:
        return FOREIGN_NOTE_DEFAULT
    unprojected = float(projection.get("foreign_unprojected_actas", 0) or 0)
    eligible = projection.get("foreign_eligible_continents", [])
    eligible_text = ", ".join(eligible) if eligible else "ninguno todavía"
    if foreign_fallback == "continent":
        return (
            "El voto extranjero ya forma parte de la proyección con una política "
            "continental conservadora. Cada país usa primero sus propios resultados; "
            "un país en cero solo usa su continente si este suma al menos "
            f"{min_actas} actas contabilizadas y datos de {min_countries} países. "
            f"Continentes elegibles: {eligible_text}. Quedan {unprojected:,.0f} "
            "actas extranjeras sin proyectar."
        )
    if foreign_fallback == "none":
        return (
            "El voto extranjero contabilizado ya forma parte del total, pero los "
            f"países todavía en cero quedan sin proyectar. Quedan {unprojected:,.0f} "
            "actas extranjeras sin proyectar."
        )
    return (
        "El voto extranjero contabilizado y su proyección forman parte del total "
        f"nacional. Quedan {unprojected:,.0f} actas extranjeras sin proyectar."
    )


def _percent(value: float, total: float) -> float | None:
    if total <= 0:
        return None
    return 100 * value / total


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
