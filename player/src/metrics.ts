export const HISTORY_SIZE = 60;

export class CircularBuffer {
  private readonly buf: number[];
  private readonly size: number;
  private pos = 0;
  private _length = 0;

  constructor(size: number) {
    this.size = size;
    this.buf = new Array(size).fill(0);
  }

  push(value: number): void {
    this.buf[this.pos] = value;
    this.pos = (this.pos + 1) % this.size;
    if (this._length < this.size) this._length++;
  }

  /** Returns all buffered values in insertion order (oldest first). */
  toArray(): number[] {
    if (this._length < this.size) {
      return this.buf.slice(0, this._length);
    }
    const result: number[] = new Array(this.size);
    for (let i = 0; i < this.size; i++) {
      result[i] = this.buf[(this.pos + i) % this.size];
    }
    return result;
  }

  get length(): number { return this._length; }
}

/**
 * p-th percentile (0–1) of a pre-sorted ascending array.
 * Linear interpolation (same as numpy default).
 */
export function percentile(sorted: number[], p: number): number {
  if (sorted.length === 0) return 0;
  const idx = p * (sorted.length - 1);
  const lo = Math.floor(idx);
  const hi = Math.ceil(idx);
  if (lo === hi) return sorted[lo];
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (idx - lo);
}
