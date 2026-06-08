import unittest

import pandas as pd

from projection import project_results


class ProjectionSmokeTest(unittest.TestCase):
    def test_projects_districts_with_fallback_and_unprojected_foreign(self):
        df = pd.DataFrame(
            [
                _row(
                    nivel="eleccion",
                    ambito=None,
                    keiko=1000,
                    sanchez=1000,
                    valid=2000,
                    counted=20,
                    total=40,
                ),
                _row(
                    nivel="ambito_geografico",
                    ambito=1,
                    keiko=600,
                    sanchez=400,
                    valid=1000,
                    counted=10,
                    total=25,
                ),
                _row(
                    nivel="departamento",
                    ambito=1,
                    dep="010000",
                    dep_name="AMAZONAS",
                    keiko=600,
                    sanchez=400,
                    valid=1000,
                    counted=10,
                    total=25,
                ),
                _row(
                    nivel="provincia",
                    ambito=1,
                    dep="010000",
                    dep_name="AMAZONAS",
                    prov="010200",
                    prov_name="BAGUA",
                    keiko=200,
                    sanchez=800,
                    valid=1000,
                    counted=10,
                    total=15,
                ),
                _row(
                    nivel="distrito",
                    ambito=1,
                    dep="010000",
                    dep_name="AMAZONAS",
                    prov="010200",
                    prov_name="BAGUA",
                    dist="010202",
                    dist_name="ARAMANGO",
                    keiko=600,
                    sanchez=400,
                    valid=1000,
                    counted=10,
                    total=20,
                ),
                _row(
                    nivel="distrito",
                    ambito=1,
                    dep="010000",
                    dep_name="AMAZONAS",
                    prov="010200",
                    prov_name="BAGUA",
                    dist="010205",
                    dist_name="BAGUA",
                    keiko=0,
                    sanchez=0,
                    valid=0,
                    counted=0,
                    total=5,
                ),
                _row(
                    nivel="ambito_geografico",
                    ambito=2,
                    keiko=0,
                    sanchez=0,
                    valid=0,
                    counted=0,
                    total=3,
                ),
            ]
        )

        result = project_results(
            df,
            include_foreign=True,
            foreign_fallback="none",
            print_output=False,
        )

        self.assertEqual(result["current_keiko_votes"], 600.0)
        self.assertEqual(result["current_sanchez_votes"], 400.0)
        self.assertAlmostEqual(result["projected_keiko_votes"], 1300.0)
        self.assertAlmostEqual(result["projected_sanchez_votes"], 1200.0)
        self.assertEqual(result["rows_with_fallback"], 1)
        self.assertEqual(result["foreign_unprojected_actas"], 3.0)
        self.assertEqual(result["total_missing_actas"], 18.0)
        self.assertEqual(result["projected_missing_valid_votes"], 1500.0)

    def test_manual_foreign_fallback_is_reserved(self):
        with self.assertRaises(ValueError):
            project_results(
                pd.DataFrame([_row(nivel="eleccion", ambito=None)]),
                foreign_fallback="manual",
                print_output=False,
            )


def _row(
    *,
    nivel,
    ambito,
    dep=None,
    dep_name=None,
    prov=None,
    prov_name=None,
    dist=None,
    dist_name=None,
    keiko=0,
    sanchez=0,
    valid=0,
    counted=0,
    total=0,
):
    return {
        "snapshot_ts": "20260608_000000",
        "ambito_geografico_id": ambito,
        "ambito_geografico_nombre": "PERU" if ambito == 1 else "EXTRANJERO",
        "nivel": nivel,
        "departamento_ubigeo": dep,
        "departamento_nombre": dep_name,
        "provincia_ubigeo": prov,
        "provincia_nombre": prov_name,
        "distrito_ubigeo": dist,
        "distrito_nombre": dist_name,
        "keiko_votes": keiko,
        "sanchez_votes": sanchez,
        "keiko_pct_valid": None,
        "sanchez_pct_valid": None,
        "total_votos_validos": valid,
        "total_votos_emitidos": valid,
        "actas_contabilizadas": counted,
        "total_actas": total,
        "actas_contabilizadas_pct": None,
        "actas_enviadas_jee": None,
        "actas_pendientes_jee": None,
        "participacion_ciudadana_pct": None,
        "fecha_actualizacion": None,
    }


if __name__ == "__main__":
    unittest.main()
