const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8100/api';

function getToken(): string | null {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem('vm_token');
}

async function apiFetch(path: string, options: RequestInit = {}) {
  const token = getToken();
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string> || {}),
  };
  if (token) headers['Authorization'] = `Bearer ${token}`;

  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });

  if (res.status === 401) {
    if (typeof window !== 'undefined') {
      localStorage.removeItem('vm_token');
      window.location.href = '/login';
    }
    throw new Error('Unauthorized');
  }

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || res.statusText);
  }

  if (res.status === 204) return null;
  return res.json();
}

// Auth
export async function login(username: string, password: string) {
  const res = await apiFetch('/v1/auth/login', {
    method: 'POST',
    body: JSON.stringify({ username, password }),
  });
  if (res.access_token) {
    localStorage.setItem('vm_token', res.access_token);
  }
  return res;
}

export function logout() {
  localStorage.removeItem('vm_token');
  window.location.href = '/login';
}

export function isAuthenticated(): boolean {
  return !!getToken();
}

// Dashboard
export const getDashboard = () => apiFetch('/v1/dashboard');

// Servers
export const getServers = () => apiFetch('/v1/servers');
export const getServer = (id: string) => apiFetch(`/v1/servers/${id}`);
export const createServer = (data: any) => apiFetch('/v1/servers', { method: 'POST', body: JSON.stringify(data) });
export const updateServer = (id: string, data: any) => apiFetch(`/v1/servers/${id}`, { method: 'PUT', body: JSON.stringify(data) });
export const deleteServer = (id: string) => apiFetch(`/v1/servers/${id}`, { method: 'DELETE' });
export const testServer = (id: string) => apiFetch(`/v1/servers/${id}/test`, { method: 'POST' });
export const browseServer = (id: string, path: string) => apiFetch(`/v1/servers/${id}/browse?path=${encodeURIComponent(path)}`);

// Jobs
export const getJobs = (params?: string) => apiFetch(`/v1/jobs${params ? '?' + params : ''}`);
export const getJob = (id: string) => apiFetch(`/v1/jobs/${id}`);
export const createJob = (data: any) => apiFetch('/v1/jobs', { method: 'POST', body: JSON.stringify(data) });
export const updateJob = (id: string, data: any) => apiFetch(`/v1/jobs/${id}`, { method: 'PUT', body: JSON.stringify(data) });
export const deleteJob = (id: string) => apiFetch(`/v1/jobs/${id}`, { method: 'DELETE' });
export const triggerJob = (id: string) => apiFetch(`/v1/jobs/${id}/trigger`, { method: 'POST' });
export const getJobSchedule = (id: string, count?: number) => apiFetch(`/v1/jobs/${id}/schedule-preview?count=${count || 5}`);

// Runs
export const getRuns = (params?: string) => apiFetch(`/v1/runs${params ? '?' + params : ''}`);
export const getRun = (id: string) => apiFetch(`/v1/runs/${id}`);
export const cancelRun = (id: string) => apiFetch(`/v1/runs/${id}/cancel`, { method: 'POST' });

// Artifacts
export const getArtifacts = (params?: string) => apiFetch(`/v1/artifacts${params ? '?' + params : ''}`);
export const getArtifact = (id: string) => apiFetch(`/v1/artifacts/${id}`);
export const restoreArtifact = (id: string, data?: any) => apiFetch(`/v1/artifacts/${id}/restore`, { method: 'POST', body: JSON.stringify(data || {}) });
export const verifyArtifact = (id: string) => apiFetch(`/v1/artifacts/${id}/verify`, { method: 'POST' });

// Storage
export const getStorageDestinations = () => apiFetch('/v1/storage');
export const getStorageDestination = (id: string) => apiFetch(`/v1/storage/${id}`);
export const createStorageDestination = (data: any) => apiFetch('/v1/storage', { method: 'POST', body: JSON.stringify(data) });
export const updateStorageDestination = (id: string, data: any) => apiFetch(`/v1/storage/${id}`, { method: 'PUT', body: JSON.stringify(data) });
export const deleteStorageDestination = (id: string) => apiFetch(`/v1/storage/${id}`, { method: 'DELETE' });
export const testStorage = (id: string) => apiFetch(`/v1/storage/${id}/test`, { method: 'POST' });
export const getStorageUsage = (id: string) => apiFetch(`/v1/storage/${id}/usage`);
export const browseStorage = (id: string, path: string) => apiFetch(`/v1/storage/${id}/browse?path=${encodeURIComponent(path)}`);

// Retention
export const getRetentionPolicies = () => apiFetch('/v1/retention');
export const getRetentionPolicy = (id: string) => apiFetch(`/v1/retention/${id}`);
export const createRetentionPolicy = (data: any) => apiFetch('/v1/retention', { method: 'POST', body: JSON.stringify(data) });
export const updateRetentionPolicy = (id: string, data: any) => apiFetch(`/v1/retention/${id}`, { method: 'PUT', body: JSON.stringify(data) });
export const deleteRetentionPolicy = (id: string) => apiFetch(`/v1/retention/${id}`, { method: 'DELETE' });
export const previewRotation = (id: string) => apiFetch(`/v1/retention/${id}/preview`, { method: 'POST' });

// Notifications
export const getNotificationChannels = () => apiFetch('/v1/notifications/channels');
export const createNotificationChannel = (data: any) => apiFetch('/v1/notifications/channels', { method: 'POST', body: JSON.stringify(data) });
export const updateNotificationChannel = (id: string, data: any) => apiFetch(`/v1/notifications/channels/${id}`, { method: 'PUT', body: JSON.stringify(data) });
export const deleteNotificationChannel = (id: string) => apiFetch(`/v1/notifications/channels/${id}`, { method: 'DELETE' });
export const testNotificationChannel = (id: string) => apiFetch(`/v1/notifications/channels/${id}/test`, { method: 'POST' });

// Setup
export const getSetupStatus = () => fetch(`${API_BASE}/v1/auth/setup-status`).then(r => r.json());
export async function setupAdmin(username: string, password: string) {
  const res = await apiFetch('/v1/auth/setup', {
    method: 'POST',
    body: JSON.stringify({ username, password }),
  });
  if (res.access_token) {
    localStorage.setItem('vm_token', res.access_token);
  }
  return res;
}

// Health
export const getHealth = () => fetch(`${API_BASE}/health`).then(r => r.json());
