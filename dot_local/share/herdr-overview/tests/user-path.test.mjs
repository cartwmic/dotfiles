import test from 'node:test';
import assert from 'node:assert/strict';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { fileURLToPath } from 'node:url';
test('public index action and real narrow/wide PTY popup loop complete against disposable scripted Herdr socket', { timeout: 60000 }, async () => {
  const { stdout } = await promisify(execFile)('python3', [fileURLToPath(new URL('./popup_pty.py', import.meta.url))], { timeout: 55000 });
  const receipt = JSON.parse(stdout.trim());
  assert.equal(receipt.current_frame_layout, 'wide workspace columns; narrow stacked workspace two-card rows');
  assert.deepEqual(receipt.display_order, ['p3','p4','p1','p2','p5','p6']);
  assert.deepEqual(receipt.exact_focus_targets, ['p1','p2','p5','p6','moved-p3','p4']);
  assert.equal(receipt.status,'PASS'); assert.equal(receipt.generation_requests,0);
  assert.ok(receipt.narrow_bytes > 1000); assert.ok(receipt.wide_bytes > 1000);
});
