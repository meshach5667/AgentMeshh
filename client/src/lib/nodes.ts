import { parseApiDate } from './format';
import type { Node } from '@/types';

export type NodeAvailability = { label: string; tone: 'green' | 'amber' | 'red' | 'gray'; detail: string };

const WORKER_REASON: Record<string, string> = {
  paused: 'paused on the machine (agentmesh-worker pause)',
  draining: 'draining on the machine (agentmesh-worker drain)',
  schedule: 'outside the availability schedule set on the machine',
};

/** Whether new deployments can be placed on the node, and why not. Mirrors the scheduler's checks. */
export function nodeAvailability(node: Node, heartbeatTimeoutSeconds = 90): NodeAvailability {
  if (node.status === 'REVOKED') return { label: 'Revoked', tone: 'red', detail: 'Its credential no longer works. Enroll the machine again to reuse it.' };
  if (node.status === 'SUSPENDED') return { label: 'Suspended', tone: 'red', detail: 'Suspended by an operator.' };
  const beat = parseApiDate(node.last_heartbeat);
  if (node.status === 'OFFLINE' || !beat || Date.now() - beat.getTime() > heartbeatTimeoutSeconds * 1000) {
    return { label: 'Offline', tone: 'red', detail: 'The worker is not sending heartbeats. Check that it is running (agentmesh-worker doctor).' };
  }
  if (!node.accepting_workloads) return { label: 'Paused', tone: 'amber', detail: 'Paused in AgentMesh. Running deployments continue; no new ones are placed.' };
  if (!node.worker_available) {
    const why = node.worker_unavailable_reason ?? '';
    return { label: 'Unavailable', tone: 'amber', detail: `Not taking work: ${WORKER_REASON[why] ?? why ?? 'reported by the worker'}.` };
  }
  return { label: 'Accepting work', tone: 'green', detail: 'New deployments can be placed here when they fit.' };
}

export function capacityRows(node: Node) {
  return [
    { label: 'CPU cores', reserved: node.reserved_cpu_cores, allocated: node.allocated_cpu_cores, unit: '' },
    { label: 'Memory', reserved: node.reserved_ram_mb, allocated: node.allocated_ram_mb, unit: 'mb' },
    { label: 'Disk', reserved: node.reserved_disk_mb, allocated: node.allocated_disk_mb, unit: 'mb' },
    { label: 'GPU memory', reserved: node.reserved_vram_mb, allocated: node.allocated_vram_mb, unit: 'mb' },
  ].filter((r) => r.allocated > 0 || r.reserved > 0);
}
