/**
 * RED TEST: readJson() must be raced against deadline
 *
 * Issue #1: group.readJson() sin timeout puede esperar indefinidamente
 * después del deadline si la grupo está abierta.
 *
 * Ejemplo:
 *  - Deadline: 1s
 *  - nextGroup() retorna grupo a 900ms
 *  - readJson() se llama, pero grupo está abierto
 *  - readJson() espera indefinidamente
 *  - Nunca respeta el deadline
 */

import { test } from 'node:test';
import { strict as assert } from 'node:assert';
import * as Moq from '@moq/net';
import { readJsonAcrossGroups } from '../src/observer.mjs';

test('RED: readJson() must timeout if group holds open past deadline', async (t) => {
  const origin = new Moq.Origin.Producer();
  const broadcast = origin.createBroadcast(Moq.Path.from('test/meta'));
  const track = broadcast.createTrack('heartbeat', {
    timescale: 1000,
    maxAge: 60000,
  });

  // Publicar 1 grupo
  const group1 = track.appendGroup();
  group1.writeJson({ v: 1, boot_id: 'aabbccddeeff0011', seq: 0 });
  // NO cerrar el grupo - dejarlo abierto
  // group1.close();

  const subscriber = track.subscribe({ maxAge: 60000 });
  const ordered = subscriber.ordered();

  // Deadline: 500ms (corta ventana)
  const deadline = Date.now() + 500;

  const readPromise = readJsonAcrossGroups(ordered, deadline);

  // Esperar un poco para que nextGroup() lea la grupo
  await new Promise(r => setTimeout(r, 100));

  // Ahora readJson() está esperando en la grupo abierta
  // El readPromise debería respetar el deadline de 500ms y terminar
  // (no esperar indefinidamente a que la grupo se cierre)

  let result = null;
  let error = null;
  let actualDuration = 0;

  const startTime = Date.now();
  try {
    result = await readPromise;
  } catch (err) {
    error = err;
  }
  actualDuration = Date.now() - startTime;

  console.log(`Duration: ${actualDuration}ms (deadline was 500ms)`);

  // readJsonAcrossGroups debería retornar/error dentro de ~500ms
  // Si tomó más de 1.5s, significa que readJson() se colgó
  assert.ok(
    actualDuration < 1500,
    `readJsonAcrossGroups should respect deadline. Took ${actualDuration}ms (deadline: 500ms). ` +
    'Bug: readJson() not raced against deadline, waited for open group indefinitely.'
  );

  if (result) {
    console.log(`✓ RED: Returned ${result.length} objects, duration respected`);
  } else if (error) {
    console.log(`✓ RED: Threw error, duration respected: ${error.message}`);
  }
});

test('RED: Deadline crossing while reading open group must not hang', async (t) => {
  const origin = new Moq.Origin.Producer();
  const broadcast = origin.createBroadcast(Moq.Path.from('test/meta'));
  const track = broadcast.createTrack('heartbeat', {
    timescale: 1000,
    maxAge: 60000,
  });

  // Publicar grupo sin cerrar
  const groupProducer = track.appendGroup();
  groupProducer.writeJson({ v: 1, boot_id: 'test', seq: 0 });
  // Dejar abierto - simula que hay más datos llegando

  const subscriber = track.subscribe({ maxAge: 60000 });
  const ordered = subscriber.ordered();

  // Deadline muy corta: 300ms
  const deadline = Date.now() + 300;

  const readPromise = readJsonAcrossGroups(ordered, deadline);

  // readJsonAcrossGroups debería completar en ~300ms aunque la grupo esté abierta
  let completed = false;
  let timedOut = false;

  try {
    await Promise.race([
      readPromise.then(() => { completed = true; }),
      new Promise((_, reject) =>
        setTimeout(() => {
          timedOut = true;
          reject(new Error('readJsonAcrossGroups hung (deadline not respected)'));
        }, 1000)
      ),
    ]);
  } catch (err) {
    if (timedOut) {
      assert.fail(
        'readJsonAcrossGroups did not respect deadline. ' +
        'Bug: readJson() waiting on open group indefinitely.'
      );
    }
  }

  assert.ok(completed, 'readJsonAcrossGroups should complete before safety timeout');
  console.log(`✓ RED: Deadline respected even with open group`);
});
