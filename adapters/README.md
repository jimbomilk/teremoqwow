# adapters/

Integraciones con APIs externas (Opta, Stats Perform, GeoIP…) normalizadas al esquema canónico de `teremoqwow`.

- **Agente responsable**: [Data Adapters](../.github/agents/data-adapters.agent.md).
- **Contratos**: [schemas/sync/](../schemas/sync/), [schemas/common/](../schemas/common/).
- **Regla**: cada adaptador expone un contrato interno estable; los cambios upstream se absorben aquí, no en `core/`.

## Estado

Fase 0 · stub.
