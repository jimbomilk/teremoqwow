# Security review — QoS data-plane diagnostics

**Fecha del informe:** 2026-10-05
**Branch analizado:** `fix/qos-data-plane-diagnostics`
**Alcance:** rondas adversariales de QoS de esta conversación. Este informe enumera
únicamente findings concretos confirmados; no convierte hipótesis, resultados
refutados ni elementos fuera de alcance en vulnerabilidades.

En el momento del informe el árbol de trabajo estaba sucio y no había un commit
de QoS que contuviera estos cambios. La revisión fue adversarial y se ejecutó sin
Docker real: se usaron shims/fixtures de prueba. Por tanto, los resultados no
constituyen una validación del despliegue productivo con Docker.

## Estado resumido

| Finding confirmado | Severidad | Ubicación | Estado |
| --- | --- | --- | --- |
| Exposición de valores sensibles quoted con newline literal en el sanitizador | **MEDIUM residual** | `qos/scripts/qos-diagnostics.sh`, `qos_report_tool_diagnostic` | Residual |
| Gap de aserción de un marcador `[REDACTED]` | **LOW** | `qos/scripts/test_data_plane_readiness.py`, tests del sanitizador | Residual de cobertura; no es por sí solo una nueva ruta de exposición |
| TOCTOU entre path-check y `open` en writers principales | **MEDIUM** | `qos/scripts/verify-lipsync.sh` y `qos/scripts/verify-pts-sync.sh` | Residual; no corregido |
| Overlay writer omite parent/nlink guards | **MEDIUM** | writer de overlay en `qos/scripts/verify-pts-sync.sh` | Residual; no corregido |
| Race de artefactos en `/tmp` | **MEDIUM** | artefactos temporales de los scripts de QoS | Corregido mediante directorio privado |
| Inyección JSON en el report PTS | **HIGH** | writer de `qos/scripts/verify-pts-sync.sh` | Corregido |
| Overflow y weak floor de `MIN_SAMPLES` | **HIGH** | `qos/scripts/measure-e2e.sh` | Corregido |
| Inyección de `duration` | **HIGH** | `qos/scripts/measure-e2e.sh` | Corregido; con tests de sanitizer |
| Sanitización insuficiente de entradas mixed-quotes | **MEDIUM** | `qos/scripts/qos-diagnostics.sh` | Corregido para mixed-quotes; permanece el residual multiline descrito arriba |

## Findings residuales o no corregidos

### 1. Sanitizador: secreto quoted con newline literal — MEDIUM residual

`qos/scripts/qos-diagnostics.sh`, dentro de `qos_report_tool_diagnostic`, usa
patrones de sanitización para valores quoted. La cobertura confirmada corrigió
los casos de comillas mixtas, pero todavía existe una fuga cuando el valor
quoted sensible contiene un newline literal, por ejemplo un `token` o
`password` multiline. El patrón quoted no consume ese caso completo; el valor
puede alcanzar la salida diagnóstica.

**Reproducción/impacto:** hacer que una herramienta escriba en stderr un campo
`token` o `password` quoted cuyo valor contenga un newline literal y pasar ese
stderr por `qos_report_tool_diagnostic`. Parte del secreto puede imprimirse en
el reporte. Esto contradice el objetivo del sanitizador y puede revelar
credenciales en logs de CI/diagnóstico. Es el residual actual, aunque los casos
de mixed-quotes ya estén corregidos.

### 2. Escritura de reports: TOCTOU residual — MEDIUM

La ronda `security r15`, realizada después de los cambios del developer,
confirmó una carrera TOCTOU entre comprobar la ruta y abrir/escribirla en los
writers principales de reports. Las ubicaciones principales son
`qos/scripts/verify-lipsync.sh` y `qos/scripts/verify-pts-sync.sh`, en sus rutas
`REPORT_FILE`/`PTS_REPORT_FILE`.

**Reproducción/impacto:** un atacante local que pueda manipular la ruta de
salida durante la ventana entre la validación y la apertura puede sustituirla y
redirigir la escritura. El impacto es sobrescritura/arbitraria modificación de
archivos accesibles por la identidad que ejecuta el job, además de posible
corrupción o exposición de reports.

Los guards actuales de los writers principales sí corrigen las comprobaciones de
symlink final, hardlink/nlink y directorio padre real. No deben describirse como
ausentes. La sustitución posterior a esos checks sigue siendo el residual
TOCTOU **MEDIUM**. El usuario declinó los fixes de seguridad de `r15`; por ello
este residual permanece explícitamente no corregido.

### 3. Overlay writer incompleto — MEDIUM

`qos/scripts/verify-pts-sync.sh` tiene un writer de overlay que omite los
guards de parent real-dir y nlink/hardlink aplicados a las rutas principales.
Conserva por ello una superficie de redirección mediante padre symlink o
hardlink. Si se gana la ventana entre su path-check y `open`, también conserva
la misma clase de TOCTOU; el reporte original no justificó elevar la severidad
por encima de **MEDIUM**.

**Impacto:** el atacante puede apuntar `OVERLAY_REPORT_FILE` a una ruta
manipulada y obtener sobrescritura arbitraria de archivos accesibles por el job.
Estado: **residual, no corregido**. El usuario declinó los fixes de seguridad
`r15`, incluido este writer.

### 4. Checks de hardlink y padre en reports principales — corregido

Los cambios del developer aplicaron a los writers principales los checks de
symlink final, `st_nlink`/hardlink y directorio padre real. El finding anterior
de esas protecciones ausentes queda **corregido para los reports principales**;
no se extiende al overlay writer incompleto ni elimina la carrera TOCTOU
descrita arriba.

## Findings corregidos

### 5. Race de artefactos en `/tmp` — MEDIUM, corregido

Los artefactos temporales de las pruebas podían competir o ser interferidos al
usar nombres en `/tmp`. La cobertura actual crea y usa un directorio privado
por ejecución (incluido el fixture `isolated_ci_path` de
`qos/scripts/test_data_plane_readiness.py`), eliminando la colisión entre jobs
y reduciendo la interferencia de otros usuarios del host. Estado: **corregido
por directorio privado**.

### 6. Inyección JSON en el report PTS — HIGH, corregido

La entrada no confiable usada para construir el report PTS podía inyectar
contenido JSON si se interpolaba sin serialización segura. El writer de
`qos/scripts/verify-pts-sync.sh` fue ajustado para generar el JSON mediante
serialización, y la cobertura de tests verifica que el contenido permanezca
datos y no sintaxis adicional. Estado: **corregido**.

### 7. `MIN_SAMPLES`: overflow y weak floor — HIGH, corregido

`qos/scripts/measure-e2e.sh` aceptaba valores de `MIN_SAMPLES` que podían
provocar overflow numérico y/o un mínimo demasiado débil para la duración
efectiva. La validación actual impone entero positivo acotado y el floor
coherente con la duración; los casos de overflow y de mínimo insuficiente están
cubiertos por `qos/scripts/test_data_plane_readiness.py`. Estado: **corregido**.

### 8. Inyección de `duration` y sanitización — HIGH, corregido

El argumento `--duration` llegaba a operaciones de shell/temporización sin una
validación suficientemente estricta. Un valor especialmente construido podía
alterar la ejecución del comando. `qos/scripts/measure-e2e.sh` valida ahora
antes de ejecutar y limita el rango; los tests de sanitizer confirman que un
payload inyectado no se ejecuta. Estado: **corregido**.

### 9. Mixed-quotes en el sanitizador — MEDIUM, corregido parcialmente

La ronda adversarial confirmó que combinaciones de claves/valores con comillas
simples y dobles podían evitar una regla que sólo contemplaba una forma de
quote. `qos/scripts/qos-diagnostics.sh` incorporó el manejo mixed-quotes y los
tests cubren esos casos. Estado: **corregido para mixed-quotes**; no debe
confundirse con el residual independiente de valores quoted con newline literal
descrito en el finding 1.

## Cobertura y exclusiones

Los tests reportaron además un gap **LOW**: falta una aserción explícita para
uno de los marcadores `[REDACTED]` esperados en la salida sanitizada. Se
registra como deuda de cobertura, no como evidencia de que el secreto concreto
se haya filtrado.

El remote probe/remote latency fue excluido del alcance de seguridad y no se
considera una vulnerabilidad confirmada. No se incluyen findings inventados,
secretos, ni resultados refutados o fuera de alcance.
