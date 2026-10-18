/**
 * RED TEST: readJsonAcrossGroups debe detectar connection.closed mid-window
 *
 * Verificar que si connection.closed se resuelve DURANTE la ventana de observación,
 * readJsonAcrossGroups lo detecta y lo propaga como error (no devuelve array vacío silenciosamente).
 */

import { test } from 'node:test';
import { strict as assert } from 'node:assert';
import * as Moq from '@moq/net';
import { readJsonAcrossGroups } from '../src/observer.mjs';

test('RED: readJsonAcrossGroups detects connection.closed mid-window and throws', async (t) => {
  const origin = new Moq.Origin.Producer();
  const broadcast = origin.createBroadcast(Moq.Path.from('test/meta'));
  const track = broadcast.createTrack('heartbeat', {
    timescale: 1000,
    maxAge: 60000,
  });

  // Publicar 1 heartbeat
  const group1 = track.appendGroup();
  group1.writeJson({ v: 1, boot_id: 'aabbccddeeff0011', seq: 0 });
  group1.close();

  const subscriber = track.subscribe({ maxAge: 60000 });
  const ordered = subscriber.ordered();

  // Simular cierre de conexión durante observación:
  // Después de 1s, simular que connection se cierra
  const deadline = Date.now() + 5000; // 5s window

  // Lanzar lectura
  const readPromise = readJsonAcrossGroups(ordered, deadline);

  // Después de 1s, simular cierre de conexión
  await new Promise(r => setTimeout(r, 1000));
  subscriber.close(); // Simula que connection se cerró

  // La lectura debería detectar esto y lanzar error (no devolver [] silenciosamente)
  let errorDetected = false;
  let objectsRead = 0;

  try {
    const objects = await Promise.race([
      readPromise,
      new Promise((_, reject) =>
        setTimeout(() => reject(new Error('readJsonAcrossGroups hung')), 3000)
      ),
    ]);
    objectsRead = objects.length;
  } catch (err) {
    if (err.message.includes('Track closed')) {
      errorDetected = true;
      console.log(`✓ RED test: Connection closure was detected and propagated: ${err.message}`);
    } else {
      console.log(`RED test: Got error but wrong type: ${err.message}`);
      throw err;
    }
  }

  assert.ok(errorDetected, 'Should detect connection closure and throw, not return silently');
  console.log(`✓ RED test passes: closure detected (${objectsRead} objects read before closure)`);
});
