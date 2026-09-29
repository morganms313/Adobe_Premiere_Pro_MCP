/**
 * The file-queue handoff between the server and the CEP panel.
 *
 * The protocol is a directory of command-<id>.json and response-<id>.json files
 * polled by both sides, so every failure here is a race or a partial read rather
 * than a logic error, and each one was visible in practice: stale response files
 * accumulated in the bridge directory, and a malformed payload was reported as
 * "Ensure Premiere Pro is open".
 */

import { PremiereProBridge } from '../../bridge/index.js';
import { promises as fs } from 'fs';
import path from 'path';

jest.mock('fs', () => ({
  promises: {
    mkdir: jest.fn(),
    access: jest.fn(),
    readdir: jest.fn(),
    writeFile: jest.fn(),
    readFile: jest.fn(),
    unlink: jest.fn(),
    rename: jest.fn(),
    rm: jest.fn(),
  }
}));

jest.mock('node:crypto', () => ({
  randomUUID: jest.fn(() => 'test-uuid-1234')
}));

describe('bridge file-queue protocol', () => {
  const mockFs = fs as jest.Mocked<typeof fs>;
  const dir = '/tmp/premiere-mcp-bridge-test';
  const commandPath = path.join(dir, 'command-test-uuid-1234.json');
  const responsePath = path.join(dir, 'response-test-uuid-1234.json');
  const stagingPath = path.join(dir, '.tmp-test-uuid-1234.json');

  beforeEach(() => {
    jest.clearAllMocks();
    process.env.PREMIERE_TEMP_DIR = dir;
    mockFs.mkdir.mockResolvedValue(undefined);
    mockFs.access.mockRejectedValue(new Error('Not found'));
    mockFs.writeFile.mockResolvedValue(undefined);
    mockFs.rename.mockResolvedValue(undefined);
    mockFs.unlink.mockResolvedValue(undefined);
  });

  afterEach(() => {
    delete process.env.PREMIERE_TEMP_DIR;
  });

  const readyBridge = async (): Promise<PremiereProBridge> => {
    const bridge = new PremiereProBridge();
    await bridge.initialize();
    return bridge;
  };

  describe('publishing a command', () => {
    it('renames into place rather than writing the polled name directly', async () => {
      // The panel picks up anything matching command-*.json the moment it appears.
      // Writing that name directly publishes it before the content is complete.
      mockFs.readFile.mockResolvedValue(JSON.stringify({ ok: true }));
      const bridge = await readyBridge();

      await bridge.executeScript('return 1;');

      expect(mockFs.writeFile).toHaveBeenCalledWith(stagingPath, expect.any(String));
      expect(mockFs.writeFile).not.toHaveBeenCalledWith(commandPath, expect.any(String));
      expect(mockFs.rename).toHaveBeenCalledWith(stagingPath, commandPath);
    });

    it('stages under a name the panel will not mistake for a command', async () => {
      // The panel matches on a "command-" prefix, so the scratch name must not
      // start with one or it defeats the point of staging.
      mockFs.readFile.mockResolvedValue(JSON.stringify({ ok: true }));
      const bridge = await readyBridge();

      await bridge.executeScript('return 1;');

      const staged = mockFs.writeFile.mock.calls[0][0] as string;
      expect(path.basename(staged).startsWith('command-')).toBe(false);
    });

    it('removes the scratch file when the rename into place fails', async () => {
      // Nothing else ever matches that name, so a failed rename leaves it on disk
      // for good. The shared bridge directory is not removed on shutdown, so these
      // accumulate there indefinitely.
      mockFs.rename.mockRejectedValue(new Error('EXDEV'));
      const bridge = await readyBridge();

      await expect(bridge.executeScript('return 1;')).rejects.toThrow();

      expect(mockFs.unlink).toHaveBeenCalledWith(stagingPath);
    });
  });

  describe('a response that will not parse', () => {
    it('recovers from a torn read once the whole file lands', async () => {
      const whole = JSON.stringify({ result: { ok: true } });
      mockFs.readFile
        .mockResolvedValueOnce(whole.slice(0, 12) as any)  // caught mid-write
        .mockResolvedValue(whole as any);
      const bridge = await readyBridge();

      await expect(bridge.executeScript('return 1;')).resolves.toEqual({ ok: true });
    });

    it('reports the payload, not a connection problem, when it never parses', async () => {
      // Previously every failure here fell through to the same timeout message,
      // sending the reader to check whether Premiere was running when the real
      // problem was the bytes on disk.
      mockFs.readFile.mockResolvedValue('{"result": "unterminated' as any);
      const bridge = await readyBridge();

      await expect(bridge.executeScript('return 1;', 500)).rejects.toThrow(
        /never became valid JSON/,
      );
      await expect(bridge.executeScript('return 1;', 500)).rejects.toThrow(
        /Last parse error/,
      );
    });

    it('includes what was actually on disk so the payload can be diagnosed', async () => {
      mockFs.readFile.mockResolvedValue('NOT JSON AT ALL' as any);
      const bridge = await readyBridge();

      await expect(bridge.executeScript('return 1;', 500)).rejects.toThrow(
        /NOT JSON AT ALL/,
      );
    });
  });

  describe('cleanup', () => {
    it('removes both files when the response never arrives', async () => {
      // Cleanup used to sit after the await, so a timeout skipped it entirely and
      // the response file was left behind once the panel finally wrote one.
      mockFs.readFile.mockRejectedValue(new Error('ENOENT'));
      const bridge = await readyBridge();

      await expect(bridge.executeScript('return 1;', 400)).rejects.toThrow(/timeout/i);

      expect(mockFs.unlink).toHaveBeenCalledWith(commandPath);
      expect(mockFs.unlink).toHaveBeenCalledWith(responsePath);
    });
    it('removes both files on the ordinary path too', async () => {
      mockFs.readFile.mockResolvedValue(JSON.stringify({ result: { ok: true } }));
      const bridge = await readyBridge();

      await bridge.executeScript('return 1;');

      expect(mockFs.unlink).toHaveBeenCalledWith(commandPath);
      expect(mockFs.unlink).toHaveBeenCalledWith(responsePath);
    });

    it('does not let a cleanup failure mask the result', async () => {
      mockFs.readFile.mockResolvedValue(JSON.stringify({ result: { ok: true } }));
      mockFs.unlink.mockRejectedValue(new Error('EPERM'));
      const bridge = await readyBridge();

      await expect(bridge.executeScript('return 1;')).resolves.toEqual({ ok: true });
    });
  });

  describe('panel heartbeat', () => {
    const heartbeatPath = path.join(dir, 'bridge-heartbeat.json');

    it('fails in a couple of seconds when Premiere is not listening, instead of hanging for a minute', async () => {
      mockFs.readFile.mockRejectedValue(new Error('ENOENT'));
      const bridge = await readyBridge();
      const started = Date.now();

      await expect(bridge.executeScript('return 1;', 20000)).rejects.toThrow(
        /MCP Bridge is not running/,
      );

      expect(Date.now() - started).toBeLessThan(5000);
    });

    it('tells the caller to click Start Bridge when the panel is open but idle', async () => {
      mockFs.readFile.mockImplementation(async (file) => {
        if (String(file) === heartbeatPath) {
          return JSON.stringify({ t: Date.now(), started: false });
        }
        throw new Error('ENOENT');
      });
      const bridge = await readyBridge();

      await expect(bridge.executeScript('return 1;', 20000)).rejects.toThrow(
        /click Start Bridge/i,
      );
    });

    it('keeps waiting when the panel is alive and working on the command', async () => {
      mockFs.readFile.mockImplementation(async (file) => {
        if (String(file) === heartbeatPath) {
          return JSON.stringify({ t: Date.now(), started: true });
        }
        throw new Error('ENOENT');
      });
      const bridge = await readyBridge();
      const started = Date.now();

      await expect(bridge.executeScript('return 1;', 700)).rejects.toThrow(/timeout/i);
      expect(Date.now() - started).toBeGreaterThanOrEqual(700);
    });

    // While Premiere runs a long evalScript (encodeSequence handing a job to AME on
    // a network mount), the panel stops writing heartbeats. Reading that as "not
    // running" made export_sequence report failure for jobs AME went on to render,
    // and re-sending them produced _1 duplicates.
    it('keeps waiting when the heartbeat goes stale mid-command, and returns the response', async () => {
      const sentAt = Date.now();
      mockFs.readFile.mockImplementation(async (file) => {
        const elapsed = Date.now() - sentAt;
        if (String(file) === heartbeatPath) {
          // Fresh at the first check, then frozen: the host is busy, not gone.
          return JSON.stringify({ t: sentAt, started: true });
        }
        if (String(file) === responsePath && elapsed >= 4500) {
          return JSON.stringify({ result: { success: true, jobID: 'ame-1' } });
        }
        throw new Error('ENOENT');
      });
      const bridge = await readyBridge();

      await expect(bridge.executeScript('return 1;', 20000)).resolves.toEqual({
        success: true,
        jobID: 'ame-1',
      });
      expect(Date.now() - sentAt).toBeGreaterThanOrEqual(4500);
    }, 10000);

    it('still fails fast when the panel was never alive while the command waited', async () => {
      // A heartbeat left behind by a panel that stopped long ago must not count.
      mockFs.readFile.mockImplementation(async (file) => {
        if (String(file) === heartbeatPath) {
          return JSON.stringify({ t: Date.now() - 60000, started: true });
        }
        throw new Error('ENOENT');
      });
      const bridge = await readyBridge();
      const started = Date.now();

      await expect(bridge.executeScript('return 1;', 20000)).rejects.toThrow(
        /MCP Bridge is not running/,
      );
      expect(Date.now() - started).toBeLessThan(5000);
    });

    it('does not fail a command queued behind one the busy panel is still running', async () => {
      // The panel runs one evalScript at a time. A second call sent while the first
      // has frozen the heartbeat is waiting its turn, not talking to a dead panel.
      const t0 = Date.now();
      const firstResponse = path.join(dir, 'response-first.json');
      const secondResponse = path.join(dir, 'response-second.json');
      mockFs.readFile.mockImplementation(async (file) => {
        const elapsed = Date.now() - t0;
        if (String(file) === heartbeatPath) {
          // Alive until the first command starts blocking the host at ~1s, then
          // frozen until it returns at 5s, then alive again.
          const t = elapsed < 5000 ? t0 : Date.now();
          return JSON.stringify({ t, started: true });
        }
        if (String(file) === firstResponse && elapsed >= 5000) {
          return JSON.stringify({ result: 'first-done' });
        }
        if (String(file) === secondResponse && elapsed >= 6000) {
          return JSON.stringify({ result: 'second-done' });
        }
        throw new Error('ENOENT');
      });
      const bridge = await readyBridge();
      const { randomUUID } = jest.requireMock('node:crypto') as { randomUUID: jest.Mock };
      randomUUID.mockReturnValueOnce('first').mockReturnValueOnce('second');

      const first = bridge.executeScript('return 1;', 20000);
      first.catch(() => {}); // asserted below; keep an early rejection from crashing the run
      // Sent after the heartbeat is already stale, so it never sees a fresh one
      // before its own first check.
      await new Promise((resolve) => setTimeout(resolve, 3000));
      const second = bridge.executeScript('return 2;', 20000);
      second.catch(() => {});

      await expect(first).resolves.toBe('first-done');
      await expect(second).resolves.toBe('second-done');
    }, 15000);

    it('warns that the command may have run when a live panel never answers', async () => {
      // Once the panel was seen alive, a timeout no longer means "not connected":
      // the command may have executed, and blindly re-sending duplicates it.
      mockFs.readFile.mockImplementation(async (file) => {
        if (String(file) === heartbeatPath) {
          return JSON.stringify({ t: Date.now(), started: true });
        }
        throw new Error('ENOENT');
      });
      const bridge = await readyBridge();

      await expect(bridge.executeScript('return 1;', 2000)).rejects.toThrow(
        /may still be running or may already have completed/,
      );
    });
  });
});
