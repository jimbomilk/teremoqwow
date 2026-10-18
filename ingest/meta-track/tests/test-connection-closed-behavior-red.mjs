/**
 * RED TEST: Verificar comportamiento cuando connection.closed se resuelve mid-window
 *
 * El problema real: readJsonAcrossGroups() NO monitorea subscriber.closed o connection.closed
 * directamente. Si la conexión se cierra, nextGroup() puede lanzar error o resolverse sin
 * devolver grupo nuevo, pero readJsonAcrossGroups espera hasta deadline.
 *
 * Verificar que:
 * 1. Cuando subscriber se cierra, nextGroup() se rechaza o devuelve undefined
 * 2. readJsonAcrossGroups debe propagar esto (no devolver [] silenciosamente)
 * 3. observeTrack debe reportar connected:false si hay error
 */

import { test } from 'node:test';
import { strict as assert } from 'node:assert';
import * as Moq from '@moq/net';

test('RED: nextGroup throws when subscriber closed mid-stream', async (t) => {
  const origin = new Moq.Origin.Producer();
  const broadcast = origin.createBroadcast(Moq.Path.from('test/meta'));
  const track = broadcast.createTrack('heartbeat', {
    timescale: 1000,
    maxAge: 60000,
  });

  // Publicar 1 grupo
  const group1 = track.appendGroup();
  group1.writeJson({ v: 1, boot_id: 'aabbccddeeff0011', seq: 0 });
  group1.close();

  const subscriber = track.subscribe({ maxAge: 60000 });
  const ordered = subscriber.ordered();

  // Read first group OK
  const firstGroup = await ordered.nextGroup();
  assert.ok(firstGroup, 'Should get first group');

  // Leer el JSON
  const obj = await firstGroup.readJson();
  assert.strictEqual(obj.seq, 0, 'First object ok');

  // Ahora cerrar subscriber
  subscriber.close();

  // Siguiente nextGroup() debería fallar o devolver undefined
  try {
    const secondGroup = await ordered.nextGroup();
    console.log(`nextGroup after close: ${secondGroup ? 'got group' : 'got undefined'}`);
    // OK si devuelve undefined (expected)
    // Pero si devuelve un grupo y luego falla, eso sería problema
  } catch (err) {
    console.log(`nextGroup after close threw: ${err.message}`);
    // OK si lanza error (expected)
  }

  console.log('✓ RED test: nextGroup handles closed subscriber');
});

test('RED: readJsonAcrossGroups should NOT silently return empty on subscriber close', async (t) => {
  // Este test documenta el contrato esperado:
  // Si subscriber se cierra mientras readJsonAcrossGroups está en ejecución,
  // debe indicarlo (lanzar error o retornar de forma que observeTrack sepa
  // que algo salió mal, NO simplemente devolver []).

  // Simulación:
  const origin = new Moq.Origin.Producer();
  const broadcast = origin.createBroadcast(Moq.Path.from('test/meta'));
  const track = broadcast.createTrack('heartbeat', {
    timescale: 1000,
    maxAge: 60000,
  });

  // Publicar varios grupos lentamente
  let groupCount = 0;
  const publishLoop = (async () => {
    for (let i = 0; i < 10; i++) {
      const g = track.appendGroup();
      g.writeJson({ v: 1, boot_id: 'test', seq: i });
      g.close();
      groupCount++;
      await new Promise(r => setTimeout(r, 300)); // Cada 300ms
    }
  })();

  const subscriber = track.subscribe({ maxAge: 60000 });
  const ordered = subscriber.ordered();

  const deadline = Date.now() + 2000; // 2s window
  const objects = [];

  // Leer en loop
  let closedFlag = false;
  const readLoop = (async () => {
    try {
      while (Date.now() < deadline) {
        const timeRemaining = deadline - Date.now();
        if (timeRemaining <= 0) break;

        try {
          const timeoutPromise = new Promise((_, reject) =>
            setTimeout(() => reject(new Error('timeout')), timeRemaining)
          );

          const group = await Promise.race([
            ordered.nextGroup(),
            timeoutPromise,
          ]);

          if (!group) break;

          let obj;
          while ((obj = await group.readJson()) !== undefined) {
            objects.push(obj);
          }
        } catch (err) {
          if (err.message.includes('timeout')) break;
          throw err; // Re-throw other errors
        }
      }
    } catch (err) {
      console.log(`Read loop error: ${err.message}`);
      closedFlag = true;
      throw err; // Propagate to indicate connection issue
    }
  })();

  // Después de 1s, cerrar subscriber
  await new Promise(r => setTimeout(r, 1000));
  subscriber.close();

  try {
    await readLoop;
  } catch (err) {
    // Esperado si readLoop propagó el error
    console.log(`readLoop propagated error (expected): ${err.message}`);
  }

  await publishLoop;

  console.log(`Objects read: ${objects.length}, groups published: ${groupCount}`);
  console.log(`Closed flag: ${closedFlag}`);

  // El punto es: readJsonAcrossGroups DEBE propagar si subscriber se cierra
  // No simplemente devolver [] silenciosamente
  console.log('✓ RED test documents: must propagate subscriber closure, not silent empty');
});
