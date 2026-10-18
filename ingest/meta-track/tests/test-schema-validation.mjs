import { test } from 'node:test';
import { strict as assert } from 'node:assert';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

// Test: Meta-Heartbeat schema validation with manual validator
// (no ajv dependency; manual validator ensures schema compliance)

const SCHEMA_PATH = resolve('../../schemas/media/v1/meta-heartbeat.json');

function loadSchema() {
  const content = readFileSync(SCHEMA_PATH, 'utf-8');
  return JSON.parse(content);
}

function validateMetaHeartbeat(event) {
  // Validate required fields
  if (typeof event !== 'object' || event === null) {
    return { valid: false, errors: ['Event must be an object'] };
  }

  const errors = [];

  // v: must be integer 1
  if (typeof event.v !== 'number' || event.v !== 1) {
    errors.push('v must be integer 1');
  }

  // boot_id: 16 hex characters
  if (typeof event.boot_id !== 'string') {
    errors.push('boot_id must be string');
  } else if (!/^[0-9a-f]{16}$/.test(event.boot_id)) {
    errors.push('boot_id must match pattern ^[0-9a-f]{16}$');
  }

  // seq: integer >= 0
  if (typeof event.seq !== 'number' || !Number.isInteger(event.seq) || event.seq < 0) {
    errors.push('seq must be integer >= 0');
  }

  // emitted_at: RFC 3339 date-time
  if (typeof event.emitted_at !== 'string') {
    errors.push('emitted_at must be string');
  } else {
    try {
      const date = new Date(event.emitted_at);
      if (isNaN(date.getTime())) {
        errors.push('emitted_at must be valid RFC 3339 date-time');
      }
    } catch {
      errors.push('emitted_at must be valid RFC 3339 date-time');
    }
  }

  // source_id: optional, must match pattern ^[a-z0-9][a-z0-9/_-]{0,63}$ if present
  if (event.source_id !== undefined) {
    if (typeof event.source_id !== 'string') {
      errors.push('source_id must be string');
    } else if (!/^[a-z0-9][a-z0-9/_-]{0,63}$/.test(event.source_id)) {
      errors.push('source_id must match pattern ^[a-z0-9][a-z0-9/_-]{0,63}$');
    }
  }

  // No additional properties
  const allowedProps = new Set(['v', 'boot_id', 'seq', 'emitted_at', 'source_id']);
  for (const prop of Object.keys(event)) {
    if (!allowedProps.has(prop)) {
      errors.push(`additionalProperty: ${prop}`);
    }
  }

  return {
    valid: errors.length === 0,
    errors: errors.length === 0 ? undefined : errors,
  };
}

test('schema: meta-heartbeat.json loads', () => {
  const schema = loadSchema();
  assert.strictEqual(schema.$id, 'https://teremoqwow.dev/schemas/media/v1/meta-heartbeat.json');
});

test('schema: valid minimal heartbeat event passes', () => {
  const event = {
    v: 1,
    boot_id: '0123456789abcdef',
    seq: 0,
    emitted_at: new Date().toISOString(),
  };
  const result = validateMetaHeartbeat(event);
  assert.strictEqual(result.valid, true);
});

test('schema: heartbeat with source_id passes', () => {
  const event = {
    v: 1,
    boot_id: '0123456789abcdef',
    seq: 5,
    emitted_at: new Date().toISOString(),
    source_id: 'anon/live1',
  };
  const result = validateMetaHeartbeat(event);
  assert.strictEqual(result.valid, true);
});

test('schema: missing v fails', () => {
  const event = {
    boot_id: '0123456789abcdef',
    seq: 0,
    emitted_at: new Date().toISOString(),
  };
  const result = validateMetaHeartbeat(event);
  assert.strictEqual(result.valid, false);
  assert.ok(result.errors.some(e => e.includes('v')));
});

test('schema: v != 1 fails', () => {
  const event = {
    v: 2,
    boot_id: '0123456789abcdef',
    seq: 0,
    emitted_at: new Date().toISOString(),
  };
  const result = validateMetaHeartbeat(event);
  assert.strictEqual(result.valid, false);
});

test('schema: invalid boot_id fails', () => {
  const event = {
    v: 1,
    boot_id: 'invalid_bootid!',
    seq: 0,
    emitted_at: new Date().toISOString(),
  };
  const result = validateMetaHeartbeat(event);
  assert.strictEqual(result.valid, false);
  assert.ok(result.errors.some(e => e.includes('boot_id')));
});

test('schema: boot_id with uppercase hex fails', () => {
  const event = {
    v: 1,
    boot_id: '0123456789ABCDEF',
    seq: 0,
    emitted_at: new Date().toISOString(),
  };
  const result = validateMetaHeartbeat(event);
  assert.strictEqual(result.valid, false);
});

test('schema: negative seq fails', () => {
  const event = {
    v: 1,
    boot_id: '0123456789abcdef',
    seq: -1,
    emitted_at: new Date().toISOString(),
  };
  const result = validateMetaHeartbeat(event);
  assert.strictEqual(result.valid, false);
});

test('schema: additional property fails', () => {
  const event = {
    v: 1,
    boot_id: '0123456789abcdef',
    seq: 0,
    emitted_at: new Date().toISOString(),
    extra_field: 'not-allowed',
  };
  const result = validateMetaHeartbeat(event);
  assert.strictEqual(result.valid, false);
});

test('schema: invalid source_id pattern fails', () => {
  const event = {
    v: 1,
    boot_id: '0123456789abcdef',
    seq: 0,
    emitted_at: new Date().toISOString(),
    source_id: 'INVALID-UPPERCASE',
  };
  const result = validateMetaHeartbeat(event);
  assert.strictEqual(result.valid, false);
});

export { validateMetaHeartbeat };
