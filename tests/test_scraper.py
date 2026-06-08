import unittest

from scraper import build_resumen_params, parse_participantes, scrape_geography


class BuildResumenParamsTest(unittest.TestCase):
    def test_builds_all_levels(self):
        self.assertEqual(
            build_resumen_params("eleccion"),
            {"idEleccion": 10, "tipoFiltro": "eleccion"},
        )
        self.assertEqual(
            build_resumen_params("ambito_geografico", 1),
            {
                "idEleccion": 10,
                "tipoFiltro": "ambito_geografico",
                "idAmbitoGeografico": 1,
            },
        )
        self.assertEqual(
            build_resumen_params("departamento", 1, dep="010000"),
            {
                "idEleccion": 10,
                "tipoFiltro": "ubigeo_nivel_01",
                "idAmbitoGeografico": 1,
                "idUbigeoDepartamento": "010000",
            },
        )
        self.assertEqual(
            build_resumen_params("provincia", 1, dep="010000", prov="010200"),
            {
                "idEleccion": 10,
                "tipoFiltro": "ubigeo_nivel_02",
                "idAmbitoGeografico": 1,
                "idUbigeoDepartamento": "010000",
                "idUbigeoProvincia": "010200",
            },
        )
        self.assertEqual(
            build_resumen_params(
                "distrito", 1, dep="010000", prov="010200", dist="010202"
            ),
            {
                "idEleccion": 10,
                "tipoFiltro": "ubigeo_nivel_03",
                "idAmbitoGeografico": 1,
                "idUbigeoDepartamento": "010000",
                "idUbigeoProvincia": "010200",
                "idUbigeoDistrito": "010202",
            },
        )

    def test_requires_missing_fields(self):
        with self.assertRaises(ValueError):
            build_resumen_params("departamento", 1)
        with self.assertRaises(ValueError):
            build_resumen_params("not-a-level")


class ParseParticipantesTest(unittest.TestCase):
    def test_parses_candidates_without_order_assumption(self):
        payload = {
            "success": True,
            "data": [
                {
                    "codigoAgrupacionPolitica": "10",
                    "nombreAgrupacionPolitica": "JUNTOS POR EL PERU",
                    "nombreCandidato": "ROBERTO HELBERT SANCHEZ PALOMINO",
                    "totalVotosValidos": 47,
                    "porcentajeVotosValidos": 47.0,
                    "porcentajeVotosEmitidos": 45.0,
                },
                {
                    "codigoAgrupacionPolitica": 8,
                    "nombreAgrupacionPolitica": "FUERZA POPULAR",
                    "nombreCandidato": "KEIKO SOFIA FUJIMORI HIGUCHI",
                    "totalVotosValidos": 53,
                    "porcentajeVotosValidos": 53.0,
                    "porcentajeVotosEmitidos": 50.0,
                },
            ],
        }

        result = parse_participantes(payload)

        self.assertEqual(result["keiko_votes"], 53.0)
        self.assertEqual(result["sanchez_votes"], 47.0)
        self.assertEqual(result["keiko_party"], "FUERZA POPULAR")
        self.assertEqual(result["sanchez_candidate"], "ROBERTO HELBERT SANCHEZ PALOMINO")

    def test_parses_sanchez_with_accent_and_missing_participant(self):
        result = parse_participantes(
            [
                {
                    "nombreAgrupacionPolitica": "Movimiento local",
                    "nombreCandidato": "ROBERTO SÁNCHEZ",
                    "totalVotosValidos": 100,
                }
            ]
        )

        self.assertIsNone(result["keiko_votes"])
        self.assertEqual(result["sanchez_votes"], 100.0)


class ScrapeGeographyTest(unittest.TestCase):
    def test_foreign_max_level_stops_at_country(self):
        client = _FakeClient()

        df = scrape_geography(
            client=client,
            include_peru=False,
            include_foreign=True,
            max_level="distrito",
            foreign_max_level="provincia",
            save_snapshot=False,
        )

        self.assertIn("provincia", df["nivel"].tolist())
        self.assertNotIn("distrito", df["nivel"].tolist())
        self.assertEqual(client.district_calls, 0)


class _FakeClient:
    def __init__(self):
        self.district_calls = 0

    def check_api_available(self):
        return None

    def get_departamentos(self, _ambito):
        return [{"ubigeo": "920000", "nombre": "AMÉRICA"}]

    def get_provincias(self, _ambito, _dep):
        return [{"ubigeo": "920100", "nombre": "MEXICO"}]

    def get_distritos(self, _ambito, _prov):
        self.district_calls += 1
        return [{"ubigeo": "920101", "nombre": "CIUDAD DE MEXICO"}]

    def get_totales(self, _params):
        return {
            "actasContabilizadas": 0,
            "contabilizadas": 0,
            "totalActas": 1,
            "totalVotosEmitidos": 0,
            "totalVotosValidos": 0,
        }

    def get_participantes(self, _params):
        return []


if __name__ == "__main__":
    unittest.main()
