# Mini Proyector Electoral ONPE Peru 2026

Proyecto Python para descargar resultados publicos de ONPE por ambito geografico
y construir una proyeccion nacional de la segunda vuelta presidencial 2026 entre
Keiko Fujimori y Roberto Sanchez.

La web oficial muestra resultados por region, provincia, distrito y extranjero:
<https://segundavuelta.onpe.gob.pe/>.

## Endpoints usados

Base:

```text
https://resultadosegundavuelta.onpe.gob.pe/presentacion-backend
```

Parametros principales:

- `idEleccion=10`
- Peru: `idAmbitoGeografico=1`
- Extranjero: `idAmbitoGeografico=2`

Ubigeos:

- `/ubigeos/departamentos`
- `/ubigeos/provincias`
- `/ubigeos/distritos`

Resumenes:

- `/resumen-general/totales`
- `/resumen-general/participantes`

`tipoFiltro=eleccion` devuelve el resumen nacional. `tipoFiltro=ambito_geografico`
divide el resumen entre Peru y extranjero. Los resumenes por geografia usan
`ubigeo_nivel_01`, `ubigeo_nivel_02` y `ubigeo_nivel_03`, con parametros
`idUbigeoDepartamento`, `idUbigeoProvincia` e `idUbigeoDistrito`.

Aunque ONPE pueda devolver ubigeos como enteros sin cero inicial, los requests
usan el string original, por ejemplo `010000`.

## Uso

Instala dependencias:

```bash
python -m pip install -r requirements.txt
```

Si tu shell no tiene el comando `python`, usa `python3` o el ejecutable de tu
entorno virtual, por ejemplo `.venv/bin/python`.

Scraping de Peru:

```bash
python main.py --scrape
```

Scraping de Peru y extranjero:

```bash
python main.py --scrape --include-foreign
```

Scraping completo con pausa corta y JSON crudo:

```bash
python main.py --scrape --max-level distrito --sleep 0.1 --save-raw-json
```

Si durante un scrape largo ONPE/CloudFront devuelve HTML en lugar de JSON,
sube la pausa y los reintentos:

```bash
python main.py --scrape --max-level distrito --sleep 0.3 --non-json-retries 8
```

Si ONPE cambia la ruta del backend, puedes probar otra base sin editar codigo:

```bash
python main.py --scrape --base-url https://NUEVA_BASE_ONPE
```

Proyeccion desde un snapshot:

```bash
python main.py --project --input-csv data/onpe_resumen_geografico_YYYYMMDD_HHMMSS.csv
```

Proyeccion con bootstrap:

```bash
python main.py --project --input-csv data/onpe_resumen_geografico_YYYYMMDD_HHMMSS.csv --bootstrap 5000
```

Politica de extranjero:

```bash
python main.py --project --input-csv data/onpe_resumen_geografico_YYYYMMDD_HHMMSS.csv --foreign-fallback none
```

Los CSV se guardan en `data/`. Si activas `--save-raw-json`, cada respuesta
cruda se guarda en `raw/`.

## Error: `Response is not JSON`

Si ves que el `content-type` es `text/html` y el texto empieza con
`<!doctype html>`, ONPE no esta devolviendo el API sino la app web. En ese caso
no es un problema del parser: el backend usado por el sitio puede estar caido,
haber cambiado de ruta, o estar sirviendo fallback del frontend. Reintenta mas
tarde, sube `--sleep`/`--non-json-retries`, o usa `--base-url` si encuentras la
nueva base del API.

## Logica de proyeccion

La proyeccion no extrapola el nacional directamente, porque el orden de llegada
de actas suele estar sesgado geograficamente.

La proyeccion base usa el nivel mas fino disponible por ambito, normalmente
distrito. Para cada distrito con actas contabilizadas, estima votos validos
faltantes por acta y reparte esos votos segun el patron actual del mismo
distrito.

Si una unidad tiene 0 actas contabilizadas o 0 votos validos, usa fallback con
filas agregadas ya scrapeadas: provincia, departamento, ambito geografico y
nacional. Para extranjero, si todo el ambito esta en 0 votos y 0 actas
contabilizadas, `foreign_fallback=none` no inventa votos y reporta
`foreign_unprojected_actas`.

`foreign_fallback=manual` esta reservado: el CLI acepta el valor, pero falla con
un mensaje claro hasta que se definan inputs manuales.

## Validaciones

`validate_dataset(df)` marca y resume:

- diferencias entre `keiko_votes + sanchez_votes` y `total_votos_validos`
- filas con `total_votos_validos = 0`
- filas con `actas_contabilizadas = 0`
- filas con `total_actas` nulo
- filas con `total_actas < actas_contabilizadas`
- participantes vacios

## Tests

```bash
python -m unittest discover -s tests
```

Los tests no usan red. Cubren el builder de parametros, parser de participantes
y un smoke test de proyeccion con fallback y extranjero no proyectado.

## Advertencias

Esto no es resultado oficial ni recomendacion de apuestas. Las actas enviadas al
JEE, observadas o pendientes pueden cambiar el resultado. Usa siempre los datos
oficiales de ONPE como fuente final.
