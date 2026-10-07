# Guideline: la seguridad se audita al final

## Intención

Avanzar. Cada ronda de revisión de seguridad por task encontraba hallazgos nuevos sobre el mismo código (el ciclo QoS necesitó 4 rondas) y bloqueaba la entrega. La revisión adversarial de seguridad pasa a hacerse **una vez, con el proyecto terminado**.

## Decisión (2026-10-07)

- `refuter-security` **no** se invoca en el ciclo por task. Lo invoca el Arquitecto en la **auditoría de seguridad final**.
- El ciclo por task queda en: `developer` (TDD) → `refuter-correctness` + `refuter-tests` en paralelo → Arquitecto.
- Los hallazgos de seguridad que aparezcan antes se **anotan en el backlog de abajo y no se corrigen** en el task.
- Solo HIGH/CRITICAL de correctness o tests bloquean. MEDIUM/LOW se anotan.
- Cada ronda revisa solo el delta de la anterior.
- Si el HIGH es solo de cobertura de tests y trae mutantes reproducibles, el Arquitecto verifica que mueren; no hace falta otra ronda.

Lo que **no** cambia: el `developer` aplica los invariantes de seguridad de `developer.agent.md` al escribir código, nadie commitea secretos, y CodeQL sigue ejecutándose en CI.

## Cuándo se considera «proyecto terminado»

Cuando el Arquitecto o el usuario lo declaran y, como mínimo, antes de abrir el servicio a usuarios o datos reales (cierre de Fase 7 de producción). La auditoría se registra como issue enlazado al proyecto #3.

## Riesgo aceptado

Hasta la auditoría, el entorno desplegado se trata como **pre-producción**: el push a `main` despliega automáticamente, así que no debe recibir tráfico ni datos reales antes de la auditoría.

## Backlog de seguridad diferida

Origen: ciclo QoS (`fix/qos-diagnostics-timeout`, rondas 1-4). Gravedad según el refuter que lo reportó.

| ID | Gravedad | Hallazgo | Dónde | Sugerencia |
|---|---|---|---|---|
| S-01 | MEDIUM | La excepción de ficheros (`x.key:`) imprime en claro lo que sigue en la misma línea: `api.key: sk_live_abc`, `jwt.key: eyJ…`. La exención va antes que los stems. | `qos-diagnostics.sh`, `is_sensitive` | Limitar la exención a rutas (palabra con `/`) y aplicar los stems antes |
| S-02 | LOW | Nombres sin cobertura: `key` desnuda fuera de query, `EZDRM_KEY_HEX`, `KEY_B64`, `stripe_sk`, `sign=`, `auth=`, `signedurl`; `whsec_…` como valor | `qos-diagnostics.sh` | Ampliar stems y redacción por patrón de valor |
| S-03 | LOW | Memoria con entradas de 8 MiB (`QUOTED_VALUE`) y `read_text()` sin tope en `_qos_exporter_stderr_is_only_broken_pipe` | `qos-diagnostics.sh` | Medir y acotar |
| S-04 | LOW | Los C0 (`\x00`…) se eliminan sin espacio: `x=1\x00sig=…` pega palabras y evade `sig`/`otp` | `qos-diagnostics.sh` | Sustituir por espacio salvo dentro de palabra |
| S-05 | LOW | Formatos sin redactar: userinfo sin `:` o con `/` en la contraseña, `Basic xxx`, `--token abc`, comillas concatenadas de shell, `"bearer":"…"`, `%3D`, XML, unicode/homoglifos | `qos-diagnostics.sh` | Valorar un enfoque por allowlist de lo que se imprime |
| S-06 | MEDIUM | `curl -sk` en CHECK 5 desactiva la verificación TLS | `integration-test.sh` | Quitar `-k` o fijar el certificado |
| S-07 | LOW | Rutas fijas `/tmp/lipsync-report.json` y `/tmp/pts-sync-report.json` leídas ignorando `*_REPORT_FILE` | `integration-test.sh` | Respetar las variables y usar `mktemp` |
| S-08 | LOW | Ficheros temporales con stderr sin redactar no se borran con SIGTERM; writer de overlay sin `nlink`/`fchmod` | `measure-e2e.sh`, `verify-pts-sync.sh` | `trap` en señales; igualar los writers |
| S-09 | LOW | `THRESHOLD_MS` decimal (`45.5`) o con cero a la izquierda (`045`, octal) en `[[ -lt ]]` de lipsync: falla cerrado, pero el mensaje engaña | `verify-lipsync.sh` | Validar entero y normalizar a base 10 |
| S-10 | INFO | `PLAYER_HOST` por defecto es un hostname de tailnet personal | `integration-test.sh` | Mover a variable de entorno sin valor por defecto |
| S-11 | HIGH (a verificar) | Cálculo con datos remotos en `(( … ))` bajo `sudo` en CHECK 5 (ya validado en esta rama) y `bc` con `THRESHOLD_MS` en pts-sync | `integration-test.sh`, `verify-pts-sync.sh` | Confirmar en la auditoría que no queda aritmética con datos no validados |

Pendientes no de seguridad (issues aparte): exporter colgado tras ffprobe 124 (`docker run` sin `--name`), PTS-sync con telemetría vacía siempre FAIL, latencia INCONCLUSIVE por publisher lento, heurística EPIPE con `Caused by:`.

## Checklist

- [x] Guideline recogida en `.github/copilot-instructions.md`.
- [x] `developer`, `arquitecto` y los 3 refuters actualizados.
- [x] Backlog inicial registrado.
- [ ] Issue «Auditoría de seguridad final» creado y vinculado al proyecto #3.
- [ ] Auditoría ejecutada con `refuter-security` y el backlog como punto de partida.
