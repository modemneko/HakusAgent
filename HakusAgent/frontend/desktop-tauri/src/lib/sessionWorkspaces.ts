export type SessionWorkspaceMap = Record<string, string | null>

export const SESSION_WORKSPACE_KEY = 'hakusai:session-workspaces'
export const SESSION_WORKSPACE_EVENT = 'hakusai:session-workspace-changed'

export function readSessionWorkspaceMap(): SessionWorkspaceMap {
  try {
    const raw = localStorage.getItem(SESSION_WORKSPACE_KEY)
    if (!raw) return {}
    const parsed = JSON.parse(raw)
    return parsed && typeof parsed === 'object' ? parsed : {}
  } catch {
    return {}
  }
}

export function writeSessionWorkspaceMap(value: SessionWorkspaceMap): void {
  try {
    localStorage.setItem(SESSION_WORKSPACE_KEY, JSON.stringify(value))
    window.dispatchEvent(new CustomEvent(SESSION_WORKSPACE_EVENT))
  } catch {
    // Private browsing and constrained WebViews can reject storage writes.
  }
}

export function assignSessionWorkspace(sessionId: string, projectId: string | null): void {
  writeSessionWorkspaceMap({ ...readSessionWorkspaceMap(), [sessionId]: projectId })
}

export function removeSessionWorkspace(sessionId: string): void {
  const next = { ...readSessionWorkspaceMap() }
  delete next[sessionId]
  writeSessionWorkspaceMap(next)
}
