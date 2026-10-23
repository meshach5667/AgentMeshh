import { CONTROL_PLANE_URL, REPO_URL, WORKER_VERSION } from './config';

export const workerTag = (version = WORKER_VERSION) => `worker-v${version}`;
export const workerWheel = (version = WORKER_VERSION) => `agentmesh_worker-${version}-py3-none-any.whl`;
export const workerReleaseUrl = (version = WORKER_VERSION) => `${REPO_URL}/releases/tag/${workerTag(version)}`;
export const workerDownloadBase = (version = WORKER_VERSION) => `${REPO_URL}/releases/download/${workerTag(version)}`;

export interface InstallOptions {
  token?: string;
  version?: string;
  controlPlane?: string;
  maxRamMb?: number;
  maxCpu?: number;
  maxDiskMb?: number;
}

const TOKEN_PLACEHOLDER = '<enrollment-token>';

/** Downloads the versioned release, checks it against SHA256SUMS, then installs. The token is only ever a CLI argument. */
export function agentInstallCommand({
  token,
  version = WORKER_VERSION,
  controlPlane = CONTROL_PLANE_URL,
  maxRamMb = 8192,
  maxCpu = 4,
  maxDiskMb = 30000,
}: InstallOptions = {}): string {
  return [
    `VERSION=${version}`,
    `BASE=${workerDownloadBase(version)}`,
    'mkdir -p ~/agentmesh-worker-$VERSION && cd ~/agentmesh-worker-$VERSION',
    'for f in install.sh uninstall.sh agentmesh_worker-$VERSION-py3-none-any.whl SHA256SUMS; do',
    '  curl -fsSLO "$BASE/$f" || break',
    'done',
    'if command -v sha256sum >/dev/null; then sha256sum -c SHA256SUMS; else shasum -a 256 -c SHA256SUMS; fi \\',
    '  && chmod +x install.sh uninstall.sh \\',
    '  && ./install.sh --wheel ./agentmesh_worker-$VERSION-py3-none-any.whl \\',
    `       --control-plane ${controlPlane} --token ${token ?? TOKEN_PLACEHOLDER} \\`,
    `       --max-ram-mb ${maxRamMb} --max-cpu ${maxCpu} --max-disk-mb ${maxDiskMb}`,
  ].join('\n');
}

export function sourceInstallCommand({ token, controlPlane = CONTROL_PLANE_URL }: InstallOptions = {}): string {
  return [
    `git clone ${REPO_URL}.git && cd AgentMeshh/server`,
    'python3 scripts/build_worker_wheel.py',
    `./packaging/install.sh --control-plane ${controlPlane} --token ${token ?? TOKEN_PLACEHOLDER} \\`,
    '    --max-ram-mb 8192 --max-cpu 4 --max-disk-mb 30000',
  ].join('\n');
}

export function dockerInstallCommand({ token, controlPlane = CONTROL_PLANE_URL }: InstallOptions = {}): string {
  return [
    `git clone ${REPO_URL}.git && cd AgentMeshh`,
    `export AGENTMESH_CONTROL_PLANE_URL=${controlPlane}`,
    `export AGENTMESH_ENROLLMENT_TOKEN=${token ?? TOKEN_PLACEHOLDER}`,
    'export DOCKER_GID=$(getent group docker | cut -d: -f3)',
    'export AGENTMESH_MAX_RAM_MB=8192 AGENTMESH_MAX_CPU_CORES=4 AGENTMESH_MAX_DISK_MB=30000',
    'docker compose -f docker-compose.worker.yml up -d',
  ].join('\n');
}

export const uninstallCommand = (version = WORKER_VERSION) =>
  `cd ~/agentmesh-worker-${version} && ./uninstall.sh            # add --purge-models to delete downloaded models`;

export const WORKER_BIN = '~/.local/share/agentmesh/venv-agentmesh-worker/bin/agentmesh-worker';

export const statusCommand = [
  'export AGENTMESH_CONFIG_FILE=~/.config/agentmesh/agentmesh-worker.env',
  `${WORKER_BIN} status     # enrollment, connection, workloads`,
  `${WORKER_BIN} doctor     # checks this machine's setup`,
].join('\n');

export const serviceLogCommands = {
  linux: 'systemctl --user status agentmesh-worker\njournalctl --user -u agentmesh-worker -f',
  macos: 'launchctl print gui/$(id -u)/io.agentmesh.agentmesh-worker\ntail -f ~/.local/share/agentmesh/agentmesh-worker/logs/agentmesh-worker.log',
};
