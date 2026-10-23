import { readFileSync } from 'fs';
import { join } from 'path';
import { WORKER_VERSION } from '../config';
import { agentInstallCommand, workerDownloadBase, workerWheel } from '../worker';

describe('worker release install', () => {
  it('uses the worker version the server packages', () => {
    const config = readFileSync(join(__dirname, '../../../../server/node_agent/config.py'), 'utf8');
    expect(config).toContain(`WORKER_VERSION = "${WORKER_VERSION}"`);
  });

  it('downloads versioned assets and verifies them before installing', () => {
    const cmd = agentInstallCommand({ token: 'am_enroll_secret' });
    expect(workerDownloadBase()).toBe(`https://github.com/meshach5667/AgentMeshh/releases/download/worker-v${WORKER_VERSION}`);
    expect(workerWheel()).toBe(`agentmesh_worker-${WORKER_VERSION}-py3-none-any.whl`);
    expect(cmd.indexOf('SHA256SUMS; else')).toBeLessThan(cmd.indexOf('./install.sh'));
    expect(cmd).toContain('--wheel ./agentmesh_worker-$VERSION-py3-none-any.whl');
  });

  it('never puts the enrollment token in a download URL', () => {
    const cmd = agentInstallCommand({ token: 'am_enroll_secret' });
    const urlLines = cmd.split('\n').filter((l) => /https?:\/\/|curl /.test(l) && !l.includes('--control-plane'));
    expect(urlLines.length).toBeGreaterThan(0);
    urlLines.forEach((l) => expect(l).not.toContain('am_enroll_secret'));
    expect(cmd).toContain('--token am_enroll_secret');
  });
});
