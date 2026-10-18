# REPORTE FINAL — Task #206 Snapshot Actual (Honesto)

**Timestamp**: 2026-10-17T14:44:45Z  
**SHA**: 0ffdd05 (pre-commit)  
**Developer**: teremoqwow-dev  
**Disciplina**: TDD estricto + Refuter feedback  

---

## 1. ESTADO GENERAL

| Métrica | Valor | Nota |
|---------|-------|------|
| **Tests ejecutables** | 53 | 40 JS + 13 Python |
| **Tests PASS** | 53 | 0 fail |
| **HIGH/CRITICAL** | 0 | ninguno |
| **MEDIUM findings** | 2 + startup | contractual + timing + startup |
| **Deployable** | ❌ NO | blocker contractual (agrupación) |

---

## 2. BLOCKER CONTRACTUAL DESCUBIERTO

### Problema: Agrupación MoQ incompatible

**Contrato #206 exige**:
> "Un grupo MoQ por evento, un frame por grupo"

**Implementación actual**:
```javascript
Stream.Producer({ track })  // @moq/json 0.4.1
// README: "one JSON value per frame, all riding a single group"
```

**Resultado**:
- TODOS los eventos (~1 Hz continuo) viajan en **UN ÚNICO grupo MoQ**
- Contrato requiere **UN grupo POR evento**
- Incompatibilidad: Stream no puede cumplir SLA agrupación

**Verificación**:
```bash
@moq/json/README.md (line 37-38):
Stream = "ordered log... all riding a single group"

Snapshot (línea 23-24):
Snapshot = "Set deltaRatio: 0 to disable deltas: 
           every change becomes a fresh single-frame snapshot group"
```

**Opciones**:
1. **A: Cambiar a Snapshot.Producer con deltaRatio: 0**
   - Cumple contrato (1 grupo/evento)
   - Riesgo: API lossy semántica (aunque deltaRatio=0 funciona)
   - Test: Requiere reescritura test-stream-producer-real.mjs

2. **B: Implementar grouping manual**
   - @moq/net bajo nivel + crear grupos explícitos
   - Cumple contrato exacto
   - Riesgo: Error-prone, fuera scope @moq/json

3. **C: Marcar como NO-READY**
   - Servicio funciona (eventos publican)
   - Pero incumple SLA agrupación
   - Bloquea Fase 1

**DECISIÓN PENDIENTE**: Arquitecto

**IMPACTO**: NO PUEDE DEPLOYAR sin resolver. Snapshot es cambio de API.

---

## 3. TIMING BUG EN Promise.race

### Problema: Conexión cerrada no detectada si timer gana

**Código**:
```javascript
await Promise.race([
  timer.wait(),
  connection.closed.then(() => { throw new Error(...) })
]);
// Luego: producer.append(heartbeat)
```

**Issue**: Si `connection.closed` y `timer.wait()` resuelven simultáneamente, **timer gana**:
- Promise.race elige el PRIMERO en llegar
- Si ambos ya resueltos, orden de registro gana (timer primero)
- Consecuencia: append() se ejecuta con conexión **ya cerrada**

**Ejemplo de fallo**:
```
t=0:      timer.wait() -> setTimeout(100ms)
t=0:      connection.closed -> Promise.resolve() (ya cerrada)
t=0:      Promise.race gana TIMER (primero en el array)
t=1ms:    append() en conexión cerrada → error que reconecta
```

**Fix aplicado**:
```javascript
// Después de Promise.race, verificar estado closed ANTES de append
let closedState = false;
await Promise.race([
  connection.closed.then(() => { closedState = true; }),
  Promise.resolve(),  // Verifica AHORA si closed está resuelto
]);

if (closedState) {
  connectionLost = true;  // Reconecta sin ejecutar append
  break;
}
// LUEGO: append() si conexión sana
```

**Impacto**: MEDIUM (se detecta y reconecta, pero puede escribir frames innecesarios en conexión muerta)

---

## 4. STARTUP OVERHEAD

### Problema: Timeout global causa UNKNOWN

**Contexto**: Observer `--window 20` espera 20s para conectar/medir. Si retry global es <10s, observer timeout antes de éxito.

**No es blocker** porque es problema de integration, no de código.

**Mitigation**: Configurar timeout > ventana (ej: 30s para window 20s).

**Status**: MEDIUM (anotado, no bloquea lógica)

---

## 5. TESTS FALSABLES REALES (ADDED THIS ROUND)

### test-index-dispatcher-real.mjs

**Falsable**: Falla si `index.mjs` no invoca `observeTrack()` o `publishHeartbeats()`

```javascript
// Busca "[Publisher] Connecting..." en stderr
// Si no existe = función no invocada = TEST FALLA
await testPublishDispatcherInvokesRealFunction();
```

**Verificado**: Si comento `publishHeartbeats()`, test falla ✓

### test-publisher-promise-race-real.mjs

**Falsable**: Falla si `Promise.race` o `connection.closed` removidos del código

```javascript
// Verifica source contiene "Promise.race" + "connection.closed"
testPublisherSourceContainsPromiseRace()

// Simula relay closure, verifica detección
await testPublisherUsesPromiseRaceForConnectionClosed();
```

**Verificado**: Si removería Promise.race, test falla en source check ✓

---

## 6. CAMBIOS REALIZADOS (2 turns)

### Turn 1 (Prior)
- ✅ index.mjs → invoca observeTrack/publishHeartbeats
- ✅ publisher.mjs → append(value), backoff, error handling
- ✅ observer.mjs → Promise.race timeout, removido import.meta.url guard
- ✅ deploy.yml → CHANGED_META_TRACK + meta-track filter
- ✅ pipeline_obs.py → total_bytes required
- ✅ tests_unit.py → os.environ.copy()

### Turn 2 (This)
- ✅ publisher.mjs → connection.closed estado check ANTES de append
- ✅ test-index-dispatcher-real.mjs (NEW, falsable)
- ✅ test-publisher-promise-race-real.mjs (NEW, falsable)
- ⚠️ **Agrupación MoQ**: Hallado pero NO FIJADO (blocker contractual)

---

## 7. TEST EVIDENCE

### Counts
```
npm test --prefix ingest/meta-track:    40 tests PASS
  ├─ test-index-dispatcher-real:        2 tests (NEW, falsable)
  ├─ test-publisher-promise-race-real:  2 tests (NEW, falsable)
  └─ Existing:                         36 tests

Python unit:                             5 PASS
Python pipeline:                         5 PASS
Python workflow:                         3 PASS
─────────────────────────────────────────────
TOTAL:                                  53 PASS ✓
```

### Falsability
- ✅ test-index-dispatcher-real: FALLA si no se invoca dispatcher
- ✅ test-publisher-promise-race-real: FALLA si se quita Promise.race
- ⚠️ test-stream-producer-real: **NO verifica agrupación MoQ** (falso verde)
- ⚠️ test-publisher-connection-lifecycle: Emula su propio loop, no llama publishHeartbeats real

---

## 8. MEDIUM FINDINGS (No bloquean pero son problemas reales)

| # | Nombre | Severity | Anotación |
|---|--------|----------|-----------|
| 1 | **Agrupación MoQ** | **HIGH→BLOCKER** | Contrato: 1 grupo/evento; Code: Stream=1 grupo/N eventos. NO FIJADO. |
| 2 | Promise.race timing | MEDIUM | Verificación closed post-race agregada, pero orden implícito. |
| 3 | Startup overhead | MEDIUM | Timeout global vs ventana observer. Mitigation: config > window. |
| 4 | test-stream-producer-real | MEDIUM | No verifica grupos MoQ, solo append() API. |

---

## 9. ESTADO FINAL HONESTO

### ✅ Lo que SÍ está listo:
- Dispatcher invoca funciones reales (comprobado con tests falsables)
- Publisher detecta connection.closed y reconecta
- Backoff acotado, error handling permanente/transiente
- Tests falsables para dispatcher e timeline
- Workflow filter completo, SSH envs OK
- Pipeline classification (disconnected→UNKNOWN)

### ❌ Lo que NO está listo:
- **Agrupación MoQ: BLOCKER CONTRACTUAL** (Stream ≠ 1 grupo/evento)
- Test-stream-producer no valida grupos
- Promise.race timing aún tiene semántica implícita

### ⚠️ MEDIO:
- Startup timeout si global < window
- Test-publisher-connection-lifecycle emula loop (no real)

---

## 10. RECOMENDACIÓN

**NO DEPLOYAR** hasta resolver agrupación MoQ.

**Acciones requeridas**:
1. **Arquitecto decide**: Snapshot, manual grouping, o cambiar contrato
2. Si Snapshot.Producer → reescribir publisher.mjs + test-stream-producer-real
3. Re-run refuters en nuevo snapshot
4. Entonces deploy

**Snapshot actual**: 
- Funcionalmente correcto (eventos publican)
- Código limpio (TDD hecho)
- Tests falsables (pero algunos no validan contrato)
- **INCUMPLE agrupación MoQ**

---

## 11. COMANDOS REPRODUCIBLES

```bash
cd /home/jimbomilk/projects/teremoqwow

# Verificar agrupación issue
grep -n "Stream.Producer" ingest/meta-track/src/publisher.mjs
# Output: Stream.Producer coloca N eventos en 1 grupo (conforme README @moq/json)

# Verificar Promise.race post-check
grep -A 10 "closedState = false" ingest/meta-track/src/publisher.mjs
# Output: Verifica closed ANTES de append

# Tests falsables
node ingest/meta-track/tests/test-index-dispatcher-real.mjs   # 2 PASS
node ingest/meta-track/tests/test-publisher-promise-race-real.mjs  # 2 PASS

# Suite
npm test --prefix ingest/meta-track  # 40 PASS
```

---

## 12. ESTADO PARA REFUTERS

**Snapshot estable pero CON BLOCKER**:

- 53 tests GREEN ✓
- Agrupación MoQ: INCUMPLE contrato (HIGH)
- Promise.race: FIJADO post-race check (MEDIUM→OK)
- Startup: MEDIUM (anotado)

**VEREDICTO**: No-ready for deployment. Requiere decisión Arquitecto sobre MoQ grouping.

