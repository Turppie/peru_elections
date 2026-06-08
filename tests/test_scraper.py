import unittest

from scraper import build_resumen_params, parse_participantes


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


if __name__ == "__main__":
    unittest.main()
