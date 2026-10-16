/**
 * set_footage_interpretation used to pass frameRate through as given. Premiere
 * keeps a caller's 23.976 as 23.9760000 (reads back 23.9760000013456), not
 * 24000/1001, so on a 23.976 sequence frame k maps to source time k * 0.999999
 * and floors to source frame k - 1: an interpreted 24p bumper or end card
 * renders ONE FRAME LATE. Seen on a CR pre-roll proof, 2026-10-15; setting
 * 23.976023976023978 made the render frame-exact.
 */

import { PremiereProTools } from '../../tools/index.js';
import { snapNtscFrameRate } from '../../tools/domains/project.js';

describe('snapNtscFrameRate', () => {
  it.each([
    [23.976, 24000 / 1001],
    [23.98, 24000 / 1001],
    [29.97, 30000 / 1001],
    [59.94, 60000 / 1001],
    [24000 / 1001, 24000 / 1001],
  ])('snaps %p to the exact NTSC ratio', (input, exact) => {
    expect(snapNtscFrameRate(input)).toBe(exact);
  });

  it.each([24, 25, 30, 50, 60, 12, 23.5])('leaves %p alone', (rate) => {
    expect(snapNtscFrameRate(rate)).toBe(rate);
  });

  it('maps every 23.976 sequence frame to the same source frame', () => {
    // The bug in arithmetic: the drifted rate floors frame k to source k - 1.
    const seqRate = 24000 / 1001;
    const lands = (srcRate: number, k: number) => Math.floor((k / seqRate) * srcRate + 1e-9);
    expect(lands(23.976, 1)).toBe(0);
    for (let k = 0; k < 2000; k++) {
      expect(lands(snapNtscFrameRate(23.976), k)).toBe(k);
    }
  });
});

describe('set_footage_interpretation', () => {
  let tools: PremiereProTools;
  let bridge: { executeScript: jest.Mock };

  beforeEach(() => {
    bridge = { executeScript: jest.fn().mockResolvedValue({ success: true }) };
    tools = new PremiereProTools(bridge as any);
  });

  const scriptFor = async (args: Record<string, unknown>): Promise<string> => {
    await tools.executeTool('set_footage_interpretation', { projectItemId: 'item', ...args });
    return bridge.executeScript.mock.calls[0][0] as string;
  };

  it('writes 24000/1001, not the 23.976 it was given', async () => {
    const script = await scriptFor({ frameRate: 23.976 });

    expect(script).toContain('interp.frameRate = 23.976023976023978;');
    expect(script).not.toContain('interp.frameRate = 23.976;');
    expect(script).toContain('requestedFrameRate: 23.976,');
  });

  it('passes a non-NTSC rate through unchanged', async () => {
    const script = await scriptFor({ frameRate: 25 });

    expect(script).toContain('interp.frameRate = 25;');
  });

  it('reports the value Premiere stored, not the one it was handed', async () => {
    const script = await scriptFor({ frameRate: 29.97 });

    expect(script).toContain('var stored = item.getFootageInterpretation();');
    expect(script).toContain('frameRate: stored.frameRate');
  });

  it('leaves the frame rate alone when only the pixel aspect ratio is set', async () => {
    const script = await scriptFor({ pixelAspectRatio: 1 });

    expect(script).not.toContain('interp.frameRate =');
    expect(script).not.toContain('requestedFrameRate');
  });
});
