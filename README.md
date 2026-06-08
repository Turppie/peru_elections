# Mini Proyector Electoral ONPE Peru 2026

Proyecto Python para descargar resultados publicos de ONPE, calcular una
proyeccion electoral provincial y publicar un dashboard estatico en GitHub
Pages. No usa Streamlit y no requiere secrets.

El entrypoint principal para produccion es:

```bash
python src/build_site.py
```

## Que genera

`src/build_site.py` scrapea ONPE, calcula la proyeccion y escribe:

- `site/index.html`: dashboard estatico con HTML + Plotly
- `site/data/latest.json`: payload listo para consumo web
- `site/data/latest.csv`: dataset geografico mas reciente

Por defecto:

- scrapea Peru; el workflow publicado también incluye extranjero
- usa `--max-level provincia`
- usa `--foreign-fallback none`

## Uso local

Instala dependencias:

```bash
python -m pip install -r requirements.txt
```

Si tu shell no tiene `python`, usa `python3` o el ejecutable del entorno virtual:

```bash
.venv/bin/python -m pip install -r requirements.txt
```

Construir el dashboard:

```bash
.venv/bin/python src/build_site.py --max-level provincia --output-dir site --include-foreign --foreign-fallback continent
```

Si ONPE/CloudFront devuelve HTML en vez de JSON durante un scrape largo, sube
pausa y reintentos:

```bash
.venv/bin/python src/build_site.py --max-level provincia --output-dir site --sleep 0.3 --non-json-retries 8
```

Luego abre `site/index.html` o sirve la carpeta:

```bash
python3 -m http.server 8000 --directory site
```

## Dashboard

El dashboard muestra:

- votos actuales Keiko/Sanchez
- votos proyectados Keiko/Sanchez
- margen actual y proyectado
- porcentaje de actas contabilizadas
- actas pendientes y actas enviadas JEE
- top 20 provincias con mas votos faltantes estimados
- tabla por departamento
- sección de voto extranjero por continente y país
- metodologia simple y disclaimer

El voto extranjero se incluye de forma conservadora. Cada país usa primero sus
propios resultados. Si un país sigue en cero, solo usa el patrón de su
continente cuando ese continente tiene al menos 10 actas contabilizadas y datos
de 2 países. Las actas de continentes sin señal suficiente quedan explícitamente
sin proyectar.

## Metodologia en simple

No extrapolamos el resultado nacional directamente, porque las actas no llegan
al mismo ritmo en todo el pais. Miramos provincia por provincia.

Para las actas faltantes de una provincia, asumimos que se parecen a las actas
ya contabilizadas en esa misma provincia. Si una provincia aun no tiene datos
suficientes, usamos un nivel mas agregado como respaldo.

En extranjero miramos país por país. Nunca usamos el patrón nacional de Perú
para inventar votos extranjeros. El dashboard periódico no baja a ciudades.

Esto no es resultado oficial, no reemplaza a ONPE y no es recomendacion de
apuestas.

## GitHub Pages con GitHub Actions

El workflow esta en:

```text
.github/workflows/update-dashboard.yml
```

Corre:

- cada 10 minutos, desplazado al minuto 7, con `cron: "7-59/10 * * * *"`
- manualmente con `workflow_dispatch`

El workflow:

1. instala Python 3.11
2. instala `requirements.txt`
3. ejecuta:

```bash
python src/build_site.py --max-level provincia --output-dir site --include-foreign --foreign-fallback continent
```

4. despliega `site/` con:

- `actions/configure-pages`
- `actions/upload-pages-artifact`
- `actions/deploy-pages`

### Activar Pages

En GitHub:

1. Ve a `Settings`.
2. Entra a `Pages`.
3. En `Build and deployment`, elige `Source: GitHub Actions`.
4. Ve a `Actions`.
5. Ejecuta manualmente `Update dashboard` o espera el cron.

No necesitas configurar secrets.

### Si el cron no corre cada 10 minutos

El archivo ya usa:

```yaml
cron: "*/10 * * * *"
```

Pero GitHub Actions no garantiza ejecuciones exactas cada 10 minutos. Si ves
pocas corridas:

- confirma que el workflow ya esta commiteado en la rama default (`main`)
- confirma que `Settings > Actions` permite workflows
- confirma que `Settings > Pages > Source` esta en `GitHub Actions`
- espera unos minutos despues del primer commit del workflow
- usa `workflow_dispatch` para una corrida manual mientras GitHub activa el cron

GitHub puede retrasar o saltarse schedules cuando hay alta carga. El dashboard
mantiene publicado el ultimo deploy exitoso.

## Endpoints ONPE

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

## CLI historico

El CLI anterior sigue disponible:

```bash
.venv/bin/python main.py --scrape --max-level provincia
.venv/bin/python main.py --project --input-csv data/onpe_resumen_geografico_YYYYMMDD_HHMMSS.csv
```

## Tests

```bash
.venv/bin/python -m unittest discover -s tests
.venv/bin/python -m py_compile main.py onpe_client.py scraper.py projection.py src/build_site.py
```
