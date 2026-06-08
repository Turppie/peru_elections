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

    def test_foreign_continent_fallback_is_conservative(self):
        result = project_results(
            _foreign_fixture(),
            include_foreign=True,
            foreign_fallback="continent",
            print_output=False,
        )
        countries = result["projection_units"]

        usa = _country(countries, "ESTADOS UNIDOS")
        mexico = _country(countries, "MEXICO")
        france = _country(countries, "FRANCIA")
        egypt = _country(countries, "EGIPTO")

        self.assertFalse(usa["used_fallback"])
        self.assertAlmostEqual(usa["projected_keiko_votes"], 400.0)
        self.assertAlmostEqual(usa["projected_sanchez_votes"], 1600.0)

        self.assertTrue(mexico["used_fallback"])
        self.assertEqual(mexico["fallback_level"], "continente")
        self.assertAlmostEqual(mexico["projected_keiko_votes"], 75.0)
        self.assertAlmostEqual(mexico["projected_sanchez_votes"], 225.0)

        self.assertTrue(france["foreign_unprojected"])
        self.assertEqual(france["projected_keiko_votes"], 0.0)
        self.assertEqual(france["projected_sanchez_votes"], 0.0)
        self.assertTrue(egypt["foreign_unprojected"])

        self.assertEqual(result["foreign_fallback_actas"], 3.0)
        self.assertEqual(result["foreign_unprojected_actas"], 10.0)
        self.assertEqual(result["foreign_eligible_continents"], ["AMÉRICA"])

    def test_foreign_none_leaves_every_zero_country_unprojected(self):
        result = project_results(
            _foreign_fixture(),
            include_foreign=True,
            foreign_fallback="none",
            print_output=False,
        )
        countries = result["projection_units"]

        self.assertTrue(_country(countries, "MEXICO")["foreign_unprojected"])
        self.assertTrue(_country(countries, "FRANCIA")["foreign_unprojected"])
        self.assertTrue(_country(countries, "EGIPTO")["foreign_unprojected"])
        self.assertEqual(result["foreign_fallback_actas"], 0.0)
        self.assertEqual(result["foreign_unprojected_actas"], 13.0)


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


def _foreign_fixture():
    rows = [
        _row(
            nivel="eleccion",
            ambito=None,
            keiko=10000,
            sanchez=1000,
            valid=11000,
            counted=100,
            total=200,
        ),
        _row(
            nivel="ambito_geografico",
            ambito=1,
            keiko=9000,
            sanchez=1000,
            valid=10000,
            counted=80,
            total=100,
        ),
        _row(
            nivel="provincia",
            ambito=1,
            dep="150000",
            dep_name="LIMA",
            prov="150100",
            prov_name="LIMA",
            keiko=9000,
            sanchez=1000,
            valid=10000,
            counted=80,
            total=100,
        ),
        _row(
            nivel="ambito_geografico",
            ambito=2,
            keiko=1400,
            sanchez=1100,
            valid=2500,
            counted=41,
            total=100,
        ),
    ]
    rows.extend(
        [
            _row(
                nivel="departamento",
                ambito=2,
                dep="920000",
                dep_name="AMÉRICA",
                keiko=300,
                sanchez=900,
                valid=1200,
                counted=12,
                total=27,
            ),
            _row(
                nivel="provincia",
                ambito=2,
                dep="920000",
                dep_name="AMÉRICA",
                prov="920100",
                prov_name="ESTADOS UNIDOS",
                keiko=200,
                sanchez=800,
                valid=1000,
                counted=10,
                total=20,
            ),
            _row(
                nivel="provincia",
                ambito=2,
                dep="920000",
                dep_name="AMÉRICA",
                prov="920200",
                prov_name="CANADA",
                keiko=100,
                sanchez=100,
                valid=200,
                counted=2,
                total=4,
            ),
            _row(
                nivel="provincia",
                ambito=2,
                dep="920000",
                dep_name="AMÉRICA",
                prov="920300",
                prov_name="MEXICO",
                total=3,
            ),
            _row(
                nivel="distrito",
                ambito=2,
                dep="920000",
                dep_name="AMÉRICA",
                prov="920300",
                prov_name="MEXICO",
                dist="920301",
                dist_name="CIUDAD DE MEXICO",
                keiko=900,
                sanchez=100,
                valid=1000,
                counted=10,
                total=10,
            ),
            _row(
                nivel="departamento",
                ambito=2,
                dep="940000",
                dep_name="EUROPA",
                keiko=900,
                sanchez=0,
                valid=900,
                counted=9,
                total=18,
            ),
            _row(
                nivel="provincia",
                ambito=2,
                dep="940000",
                dep_name="EUROPA",
                prov="940100",
                prov_name="ALEMANIA",
                keiko=500,
                valid=500,
                counted=5,
                total=5,
            ),
            _row(
                nivel="provincia",
                ambito=2,
                dep="940000",
                dep_name="EUROPA",
                prov="940200",
                prov_name="ITALIA",
                keiko=400,
                valid=400,
                counted=4,
                total=4,
            ),
            _row(
                nivel="provincia",
                ambito=2,
                dep="940000",
                dep_name="EUROPA",
                prov="940300",
                prov_name="FRANCIA",
                total=4,
            ),
            _row(
                nivel="departamento",
                ambito=2,
                dep="910000",
                dep_name="ÁFRICA",
                keiko=200,
                sanchez=200,
                valid=400,
                counted=20,
                total=26,
            ),
            _row(
                nivel="provincia",
                ambito=2,
                dep="910000",
                dep_name="ÁFRICA",
                prov="910100",
                prov_name="SUDAFRICA",
                keiko=200,
                sanchez=200,
                valid=400,
                counted=20,
                total=20,
            ),
            _row(
                nivel="provincia",
                ambito=2,
                dep="910000",
                dep_name="ÁFRICA",
                prov="910200",
                prov_name="EGIPTO",
                total=6,
            ),
        ]
    )
    return pd.DataFrame(rows)


def _country(units, name):
    return units[
        (units["ambito_geografico_id"] == 2)
        & (units["provincia_nombre"] == name)
    ].iloc[0]


if __name__ == "__main__":
    unittest.main()
