/**
 * Intrinsic Motion/Opacity readback must ignore effects that happen to have
 * same-named parameters.
 *
 * The Timecode effect (AE.ADBE PPro Timecode) carries its own Position and
 * Opacity. replace_clip used to read Motion by display name across every
 * component, so the Timecode overlay's Position [0.5, 0.06] and Opacity 40 were
 * written back onto the replacement clip's intrinsic Motion and Opacity — the
 * picture jumped to y=64.8 and the clip dropped to 40% (SBH S1 Ep5 clip pull,
 * 2026-09-29). These tests execute the generated ExtendScript against a fake
 * clip rather than greping it.
 */

import vm from 'vm';
import { PremiereProBridge } from '../../bridge/index.js';
import { PremiereProTools } from '../../tools/index.js';

type Sandbox = Record<string, unknown>;

/** Fake-clip builders, in ExtendScript source so they live inside the sandbox. */
const FIXTURES = `
  function __prop(name, value) {
    var p = { displayName: name, value: value, writes: [] };
    p.getValue = function () { return p.value; };
    p.setValue = function (v) { p.value = v; p.writes.push(v); };
    p.isTimeVarying = function () { return false; };
    return p;
  }
  function __comp(displayName, matchName, props) {
    var c = { displayName: displayName, matchName: matchName, properties: { numItems: props.length } };
    for (var i = 0; i < props.length; i++) c.properties[i] = props[i];
    return c;
  }
  function __clipOf(comps) {
    var c = { components: { numItems: comps.length } };
    for (var i = 0; i < comps.length; i++) c.components[i] = comps[i];
    return c;
  }
  // Premiere's intrinsic components, then a Timecode overlay with its own
  // Position and Opacity. Scale Width follows Scale, as it does in Premiere.
  function __timecodeClip(withMatchNames) {
    return __clipOf([
      __comp('Opacity', withMatchNames ? 'AE.ADBE Opacity' : undefined, [
        __prop('Opacity', 100), __prop('Blend Mode', 0)
      ]),
      __comp('Motion', withMatchNames ? 'AE.ADBE Motion' : undefined, [
        __prop('Position', [0.5, 0.5]), __prop('Scale', 80), __prop('Scale Width', 100),
        __prop('Rotation', 0), __prop('Anchor Point', [0.5, 0.5])
      ]),
      __comp('Timecode', withMatchNames ? 'AE.ADBE PPro Timecode' : undefined, [
        __prop('Position', [0.5, 0.06]), __prop('Size', 10), __prop('Opacity', 40)
      ])
    ]);
  }
`;

const buildScript = (script: string): string =>
  (new PremiereProBridge() as unknown as { buildExecutableScript(s: string): string })
    .buildExecutableScript(script);

/** Runs `body` after the prelude and the fixtures, returning the sandbox. */
const runWithPrelude = (body: string): Sandbox => {
  const full = buildScript('return 1;');
  const prelude = full.slice(0, full.indexOf('(function(){'));
  const sandbox: Sandbox = { app: { enableQE: () => {} } };
  vm.createContext(sandbox);
  vm.runInContext(prelude + '\n' + FIXTURES + '\n' + body, sandbox);
  return sandbox;
};

/** Captures the script a tool sends, then runs it after `setup` with the prelude. */
const runTool = async (tool: string, args: Record<string, unknown>, setup: string): Promise<{ result: any; sandbox: Sandbox }> => {
  const executeScript = jest.fn().mockResolvedValue({ success: true });
  const tools = new PremiereProTools({ executeScript } as any);
  await tools.executeTool(tool, args);
  const toolScript = executeScript.mock.calls[0][0] as string;
  const full = buildScript(toolScript);
  const split = full.indexOf('(function(){');
  const sandbox: Sandbox = { app: { enableQE: () => {} }, Time: function Time(this: any) { this.seconds = 0; } };
  vm.createContext(sandbox);
  vm.runInContext(full.slice(0, split) + '\n' + FIXTURES + '\n' + setup + '\n__out = ' + full.slice(split), sandbox);
  return { result: JSON.parse(sandbox.__out as string), sandbox };
};

describe('intrinsic Motion/Opacity readback with a Timecode effect', () => {
  describe('__readIntrinsicMotion', () => {
    it('reads Motion and Opacity from the intrinsic components, not the Timecode effect', () => {
      const sandbox = runWithPrelude(`__result = __readIntrinsicMotion(__timecodeClip(true));`);
      expect(sandbox.__result).toEqual({ opacity: 100, scale: 80, rotation: 0, position: [0.5, 0.5] });
    });

    it('falls back to the first two components when matchName is unavailable', () => {
      const sandbox = runWithPrelude(`__result = __readIntrinsicMotion(__timecodeClip(false));`);
      expect(sandbox.__result).toEqual({ opacity: 100, scale: 80, rotation: 0, position: [0.5, 0.5] });
    });

    it('keeps Scale rather than letting Scale Width overwrite it', () => {
      const sandbox = runWithPrelude(`__result = __readIntrinsicMotion(__timecodeClip(true)).scale;`);
      expect(sandbox.__result).toBe(80);
    });

    it('ignores a Timecode effect listed ahead of the intrinsic components', () => {
      const sandbox = runWithPrelude(`
        var c = __timecodeClip(true);
        __result = __readIntrinsicMotion(__clipOf([c.components[2], c.components[0], c.components[1]]));
      `);
      expect(sandbox.__result).toEqual({ opacity: 100, scale: 80, rotation: 0, position: [0.5, 0.5] });
    });
  });

  describe('__resolveClipProperty', () => {
    it('resolves Timecode > Opacity to the Timecode effect, not the intrinsic Opacity', () => {
      const sandbox = runWithPrelude(`
        var r = __resolveClipProperty(__timecodeClip(true), 'Timecode', 'Opacity');
        __result = { ok: r.ok, comp: String(r.component.displayName), value: r.property.getValue() };
      `);
      expect(sandbox.__result).toEqual({ ok: true, comp: 'Timecode', value: 40 });
    });

    it('resolves Timecode > Position to the Timecode effect', () => {
      const sandbox = runWithPrelude(`
        __result = __resolveClipProperty(__timecodeClip(true), 'Timecode', 'Position').property.getValue();
      `);
      expect(sandbox.__result).toEqual([0.5, 0.06]);
    });

    it('still maps Motion > Opacity to the intrinsic Opacity component and reports it', () => {
      const sandbox = runWithPrelude(`
        var r = __resolveClipProperty(__timecodeClip(true), 'Motion', 'Opacity');
        __result = { comp: String(r.component.displayName), value: r.property.getValue() };
      `);
      expect(sandbox.__result).toEqual({ comp: 'Opacity', value: 100 });
    });

    it('resolves Motion > Position to the intrinsic Motion component', () => {
      const sandbox = runWithPrelude(`
        __result = __resolveClipProperty(__timecodeClip(true), 'Motion', 'Position').property.getValue();
      `);
      expect(sandbox.__result).toEqual([0.5, 0.5]);
    });
  });

  it('get_keyframes reads the Timecode effect Opacity (40), not the clip Opacity', async () => {
    const { result } = await runTool('get_keyframes', { clipId: 'c1', componentName: 'Timecode', paramName: 'Opacity' }, `
      var __clip = __timecodeClip(true);
      __findClip = function () { return { clip: __clip }; };
    `);
    expect(result.success).toBe(true);
    expect(result.staticValue).toBe(40);
  });

  it('get_clip_properties reports intrinsic Motion/Opacity, not the Timecode effect', async () => {
    const { result } = await runTool('get_clip_properties', { clipId: 'c1' }, `
      var __clip = __timecodeClip(true);
      __clip.name = 'A'; __clip.disabled = false;
      __clip.start = { seconds: 0 }; __clip.end = { seconds: 5 }; __clip.duration = { seconds: 5 };
      __clip.inPoint = { seconds: 0 }; __clip.outPoint = { seconds: 5 };
      __clip.getSpeed = function () { return 1; };
      __findClip = function () {
        return { clip: __clip, trackIndex: 0, trackType: 'video', sequenceId: 's1', sequenceName: 'Seq',
                 sequence: { frameSizeHorizontal: 1920, frameSizeVertical: 1080 } };
      };
    `);
    expect(result.success).toBe(true);
    expect(result.properties.motion).toEqual({
      opacity: 100,
      scale: 80,
      rotation: 0,
      positionNormalized: { x: 0.5, y: 0.5 },
      position: { x: 960, y: 540 },
    });
  });

  it('replace_clip restores the old clip Motion/Opacity, not the Timecode effect values', async () => {
    const { sandbox } = await runTool('replace_clip', { clipId: 'c1', newProjectItemId: 'item-2' }, `
      var __old = __timecodeClip(true);
      __old.start = { seconds: 0 }; __old.end = { seconds: 5 };
      __old.inPoint = { seconds: 0 }; __old.outPoint = { seconds: 5 };
      __old.disabled = false;
      __old.remove = function () {};
      var __placed = __clipOf([
        __comp('Opacity', 'AE.ADBE Opacity', [__prop('Opacity', 100), __prop('Blend Mode', 0)]),
        __comp('Motion', 'AE.ADBE Motion', [
          __prop('Position', [0.5, 0.5]), __prop('Scale', 100), __prop('Scale Width', 100),
          __prop('Rotation', 0), __prop('Anchor Point', [0.5, 0.5])
        ])
      ]);
      __placed.start = { seconds: 0 }; __placed.inPoint = { seconds: 0 }; __placed.outPoint = { seconds: 5 };
      __placed.nodeId = 'new';
      var __track = { clips: { numItems: 0 }, overwriteClip: function () { __track.clips.numItems = 1; __track.clips[0] = __placed; } };
      __findClip = function () {
        return { clip: __old, track: __track, trackIndex: 0, trackType: 'video',
                 sequence: { videoTracks: { 0: __track } } };
      };
      __findProjectItem = function () { return { name: 'B.mp4' }; };
      __qeSequenceFor = function () { return null; };
    `);
    const placed = (sandbox.__placed as any).components;
    expect(placed[0].properties[0].value).toBe(100);
    expect(placed[1].properties[0].value).toEqual([0.5, 0.5]);
    expect(placed[1].properties[1].value).toBe(80);
  });
});
