# Política de Seguridad

## Versiones soportadas

Durante la Fase 0 no existen releases estables; la rama `main` es la única soportada.

## Cómo reportar una vulnerabilidad

- **No abras una issue pública** para vulnerabilidades.
- Usa **[GitHub Security Advisories](https://github.com/jimbomilk/teremoqwow/security/advisories/new)** ("Report a vulnerability") para enviar el informe de forma privada.
- Alternativa: contactar por email a `security@teremoqwow.dev` (si está configurado).

Incluye en el reporte:

- Descripción clara del problema y el impacto.
- Pasos reproducibles o PoC.
- Versión / commit afectado.
- Datos de contacto para acuse de recibo.

## Acuse de recibo y tiempos

- Acuse en 72 h laborables.
- Triage y clasificación de severidad (CVSS v3.1) en 7 días.
- Coordinación de fix + publicación de advisory antes de divulgación pública.

## Alcance

- Código en este repositorio.
- Contratos publicados en [`schemas/`](schemas/).

Quedan **fuera de alcance** vulnerabilidades en dependencias upstream ya reportadas a sus proyectos (reenvíanos el CVE si aplica al despliegue de teremoqwow).

## Programa de reconocimiento

No hay bug bounty monetario en Fase 0. Los reporters válidos serán reconocidos en el advisory publicado.
