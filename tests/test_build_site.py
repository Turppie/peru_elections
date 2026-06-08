import json
import unittest

import pandas as pd

from src.build_site import build_payload, render_html


class BuildSiteTest(unittest.TestCase):
    def test_payload_is_json_serializable_without_nan(self):
        df = _fixture_df()
        projection = _fixture_projection()

        payload = build_payload(
            df=df,
            projection=projection,
            max_level="provincia",
            include_foreign=True,
            foreign_fallback="continent",
        )

        encoded = json.dumps(payload, allow_nan=False)
        self.assertIn("projected_keiko_votes", encoded)
        self.assertNotIn("bootstrap", payload)
        self.assertEqual(len(payload["department_table"]), 1)
        self.assertEqual(len(payload["foreign_continents"]), 1)
        self.assertEqual(len(payload["foreign_countries"]), 1)
        self.assertEqual(payload["foreign_summary"]["unprojected_actas"], 3.0)
        self.assertEqual(payload["summary"]["actas_contabilizadas_pct"], 75.0)

    def test_html_contains_dashboard_copy_and_assets(self):
        payload = build_payload(
            df=_fixture_df(),
            projection=_fixture_projection(),
            max_level="provincia",
            include_foreign=True,
            foreign_fallback="continent",
        )

        html = render_html(payload)

        self.assertIn("cdn.plot.ly", html)
        self.assertIn("latest.json", html)
        self.assertIn("latest.csv", html)
        self.assertIn("Metodología en simple", html)
        self.assertIn("no es resultado oficial", html)
        self.assertIn("Voto extranjero", html)
        self.assertIn("política continental", html)
        self.assertIn("foreign-country-table", html)
        self.assertIn("table-scroll", html)
        self.assertNotIn("simulación bootstrap", html)


def _fixture_df():
    return pd.DataFrame(
        [
            {
                "snapshot_ts": "20260608_012139",
                "ambito_geografico_id": None,
                "nivel": "eleccion",
                "fecha_actualizacion": 1780899361682,
                "keiko_votes": 1000,
                "sanchez_votes": 900,
                "actas_contabilizadas_pct": 75.0,
                "actas_contabilizadas": 90,
                "total_actas": 120,
                "actas_pendientes_jee": 12,
                "actas_enviadas_jee": 3,
            },
            {
                "snapshot_ts": "20260608_012139",
                "ambito_geografico_id": 1,
                "nivel": "ambito_geografico",
                "fecha_actualizacion": 1780899361682,
                "keiko_votes": 1000,
                "sanchez_votes": 900,
                "actas_contabilizadas_pct": 80.0,
                "actas_contabilizadas": 80,
                "total_actas": 100,
                "actas_pendientes_jee": 10,
                "actas_enviadas_jee": 2,
            },
            {
                "snapshot_ts": "20260608_012139",
                "ambito_geografico_id": 1,
                "nivel": "departamento",
                "departamento_nombre": "AMAZONAS",
                "keiko_votes": 1000,
                "sanchez_votes": 900,
                "keiko_pct_valid": 52.6,
                "sanchez_pct_valid": 47.4,
                "total_votos_validos": 1900,
                "actas_contabilizadas_pct": 80.0,
                "actas_pendientes_jee": 10,
                "actas_enviadas_jee": 2,
            },
            {
                "snapshot_ts": "20260608_012139",
                "ambito_geografico_id": 2,
                "nivel": "ambito_geografico",
                "fecha_actualizacion": 1780899361682,
                "keiko_votes": 100,
                "sanchez_votes": 200,
                "actas_contabilizadas_pct": 10.0,
                "actas_contabilizadas": 10,
                "total_actas": 100,
                "actas_pendientes_jee": 0,
                "actas_enviadas_jee": 0,
            },
            {
                "snapshot_ts": "20260608_012139",
                "ambito_geografico_id": 2,
                "nivel": "departamento",
                "departamento_ubigeo": "920000",
                "departamento_nombre": "AMÉRICA",
                "keiko_votes": 100,
                "sanchez_votes": 200,
                "total_votos_validos": 300,
                "actas_contabilizadas": 10,
                "total_actas": 100,
                "actas_contabilizadas_pct": 10.0,
            },
        ]
    )


def _fixture_projection():
    projection_units = pd.DataFrame(
        [
            {
                "ambito_geografico_id": 1,
                "nivel": "provincia",
                "departamento_nombre": "AMAZONAS",
                "provincia_nombre": "BAGUA",
                "missing_actas": 5,
                "missing_valid_votes_est": 500,
                "used_fallback": False,
                "fallback_level": None,
                "foreign_unprojected": False,
            },
            {
                "ambito_geografico_id": 2,
                "nivel": "provincia",
                "departamento_nombre": "AMÉRICA",
                "provincia_nombre": "MEXICO",
                "actas_contabilizadas": 0,
                "total_actas": 3,
                "missing_actas": 3,
                "missing_valid_votes_est": 0,
                "current_keiko_votes": 0,
                "current_sanchez_votes": 0,
                "projected_keiko_votes": 0,
                "projected_sanchez_votes": 0,
                "used_fallback": False,
                "fallback_level": None,
                "foreign_unprojected": True,
            },
        ]
    )
    return {
        "current_keiko_votes": 1000.0,
        "current_sanchez_votes": 900.0,
        "current_margin_sanchez_minus_keiko": -100.0,
        "projected_keiko_votes": 1250.0,
        "projected_sanchez_votes": 1150.0,
        "projected_keiko_pct": 52.08,
        "projected_sanchez_pct": 47.92,
        "projected_margin_sanchez_minus_keiko": -100.0,
        "projected_winner": "Keiko Fujimori",
        "total_missing_actas": 5.0,
        "projected_missing_valid_votes": 500.0,
        "rows_with_fallback": 0,
        "foreign_current_keiko_votes": 100.0,
        "foreign_current_sanchez_votes": 200.0,
        "foreign_projected_keiko_votes": 150.0,
        "foreign_projected_sanchez_votes": 300.0,
        "foreign_fallback_actas": 4.0,
        "foreign_unprojected_actas": 3.0,
        "foreign_eligible_continents": ["AMÉRICA"],
        "top_missing_units": projection_units,
        "projection_units": projection_units,
    }


if __name__ == "__main__":
    unittest.main()
