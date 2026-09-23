import { authClient } from '../auth/client';

export type WorkflowStatus = 'draft' | 'pending' | 'approved' | 'rejected' | 'returned';
export type WorkflowDecision = 'approve' | 'reject' | 'return';
export type WorkflowPermissionLoader = () => Promise<string[]>;

export interface WorkflowRequest {
  id: string;
  tenant_id: string;
  requester_membership_id: string;
  approver_membership_id: string;
  request_type: string;
  title: string;
  description: string;
  status: WorkflowStatus;
  version: number;
  created_at: string;
  updated_at: string;
  submitted_at: string | null;
  completed_at: string | null;
}

export interface ApprovalTask {
  id: string;
  request_id: string;
  title: string;
  request_type: string;
  requester_membership_id: string;
  status: string;
  version: number;
  created_at: string;
  due_at: string;
}

export interface WorkflowEvent {
  id: string;
  actor_membership_id: string;
  actor_kind: 'requester' | 'approver';
  event_type: string;
  from_status: string | null;
  to_status: string;
  note: string | null;
  created_at: string;
}

export interface Approver {
  membership_id: string;
  display_name: string;
}

export interface WorkflowDocument {
  id: string;
  tenant_id: string;
  request_id: string;
  uploaded_by_membership_id: string;
  filename: string;
  content_type: string;
  byte_size: number;
  sha256: string;
  created_at: string;
}

export interface DocumentCenterItem extends WorkflowDocument {
  request_title: string;
  request_status: WorkflowStatus;
  relation: 'requester' | 'approver';
}

async function json<T>(path: string, init: RequestInit = {}): Promise<T> {
  return (await (await authClient.request(path, init)).json()) as T;
}

export const workflowClient = {
  permissions: () => json<string[]>('/workflows/permissions'),
  approvers: () => json<Approver[]>('/workflows/approvers'),
  requests: () => json<WorkflowRequest[]>('/workflows/requests'),
  create: (payload: {
    request_type: string;
    title: string;
    description: string;
    approver_membership_id: string;
  }) =>
    json<WorkflowRequest>('/workflows/requests', { method: 'POST', body: JSON.stringify(payload) }),
  update: (
    id: string,
    payload: {
      expected_version: number;
      title: string;
      description: string;
      approver_membership_id: string;
    },
  ) =>
    json<WorkflowRequest>(`/workflows/requests/${id}`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    }),
  submit: (id: string, expectedVersion: number) =>
    json<WorkflowRequest>(`/workflows/requests/${id}/submit`, {
      method: 'POST',
      body: JSON.stringify({ expected_version: expectedVersion }),
    }),
  history: (id: string) => json<WorkflowEvent[]>(`/workflows/requests/${id}/history`),
  documents: (requestId: string) =>
    json<WorkflowDocument[]>(`/workflows/requests/${requestId}/documents`),
  documentCenter: () => json<DocumentCenterItem[]>('/documents'),
  uploadDocument: (requestId: string, file: File) => {
    const body = new FormData();
    body.set('upload', file);
    return json<WorkflowDocument>(`/workflows/requests/${requestId}/documents`, {
      method: 'POST',
      body,
    });
  },
  downloadDocument: (requestId: string, documentId: string) =>
    authClient.request(`/workflows/requests/${requestId}/documents/${documentId}/download`),
  inbox: () => json<ApprovalTask[]>('/workflows/approvals/inbox'),
  decide: (id: string, decision: WorkflowDecision, expectedVersion: number, note: string) =>
    json<WorkflowRequest>(`/workflows/approvals/${id}/decision`, {
      method: 'POST',
      body: JSON.stringify({ decision, expected_version: expectedVersion, note }),
    }),
};
