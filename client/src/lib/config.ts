export const API_URL = process.env.NEXT_PUBLIC_API_URL || 'https://agentmesh-riuz.onrender.com/api/v1';

export const CONTROL_PLANE_URL = API_URL.replace(/\/api\/v\d+\/?$/, '');

export const DASHBOARD_URL = 'https://agent-mesh-ten.vercel.app';
export const REPO_URL = 'https://github.com/meshach5667/AgentMeshh';
export const RELEASES_URL = `${REPO_URL}/releases`;
export const WORKER_VERSION = '0.3.0';
