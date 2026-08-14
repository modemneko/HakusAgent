/**
 * Projects store — Codex-style "work on a project" picker.
 *
 * A project is just a named folder on disk. The user picks a folder via
 * the Tauri folder dialog, we register it on the server, and the active
 * project's id is sent with every chat turn so the agent runs inside
 * that folder.
 *
 * The "active project" is per-session-ish: we persist it to localStorage
 * so it survives page refresh, but it's not strictly per-session — the
 * user can switch it any time from the Composer's picker. The chat
 * request carries the current value at send time, so there's no need
 * to sync it back to the session store.
 */
import { create } from 'zustand'
import { apiClient } from '@/api/client'
import type { Project, ProjectCreateBody } from '@/api/types'

const ACTIVE_PROJECT_KEY = 'hakusai-active-project-id'

interface ProjectsStore {
  projects: Project[]
  /** Loaded flag — false until first successful listProjects(). */
  loaded: boolean
  /** Currently active project id (null = "不在项目中工作"). */
  activeProjectId: string | null
  /** Convenience: the full Project object for activeProjectId, or null. */
  activeProject: Project | null

  load: () => Promise<void>
  setActive: (projectId: string | null) => void
  create: (body: ProjectCreateBody) => Promise<Project>
  rename: (projectId: string, name: string) => Promise<void>
  togglePinned: (projectId: string, pinned: boolean) => Promise<void>
  remove: (projectId: string) => Promise<void>
}

function readActiveFromStorage(): string | null {
  try {
    return localStorage.getItem(ACTIVE_PROJECT_KEY) || null
  } catch {
    return null
  }
}

function writeActiveToStorage(id: string | null): void {
  try {
    if (id) localStorage.setItem(ACTIVE_PROJECT_KEY, id)
    else localStorage.removeItem(ACTIVE_PROJECT_KEY)
  } catch {
    /* ignore quota / privacy mode errors */
  }
}

function findActive(projects: Project[], id: string | null): Project | null {
  if (!id) return null
  return projects.find((p) => p.id === id) || null
}

export const useProjectsStore = create<ProjectsStore>((set, get) => ({
  projects: [],
  loaded: false,
  activeProjectId: readActiveFromStorage(),
  activeProject: null,

  load: async () => {
    try {
      const projects = await apiClient.listProjects()
      const activeId = get().activeProjectId
      // If the persisted active id is no longer in the registry
      // (deleted from another device / hand-edited projects.json),
      // fall back to null — don't silently keep sending a stale id.
      const stillExists = activeId ? projects.some((p) => p.id === activeId) : false
      const nextActiveId = stillExists ? activeId : null
      if (!stillExists) writeActiveToStorage(null)
      set({
        projects,
        loaded: true,
        activeProjectId: nextActiveId,
        activeProject: findActive(projects, nextActiveId),
      })
    } catch (e) {
      // Don't crash the UI if /api/projects is unavailable (e.g. backend
      // too old). The picker will just show an empty list + "新建项目".
      console.warn('[projects] load failed:', e)
      set({ loaded: true })
    }
  },

  setActive: (projectId) => {
    writeActiveToStorage(projectId)
    const projects = get().projects
    set({
      activeProjectId: projectId,
      activeProject: findActive(projects, projectId),
    })
  },

  create: async (body) => {
    const project = await apiClient.createProject(body)
    const projects = [project, ...get().projects.filter((p) => p.id !== project.id)]
    set({ projects })
    return project
  },

  rename: async (projectId, name) => {
    const updated = await apiClient.updateProject(projectId, { name })
    const projects = get().projects.map((p) => (p.id === projectId ? updated : p))
    set({
      projects,
      activeProject: findActive(projects, get().activeProjectId),
    })
  },

  togglePinned: async (projectId, pinned) => {
    const updated = await apiClient.updateProject(projectId, { pinned })
    const projects = get().projects.map((p) => (p.id === projectId ? updated : p))
    set({
      projects,
      activeProject: findActive(projects, get().activeProjectId),
    })
  },

  remove: async (projectId) => {
    await apiClient.deleteProject(projectId)
    const projects = get().projects.filter((p) => p.id !== projectId)
    const activeId = get().activeProjectId
    const nextActiveId = activeId === projectId ? null : activeId
    if (activeId === projectId) writeActiveToStorage(null)
    set({
      projects,
      activeProjectId: nextActiveId,
      activeProject: findActive(projects, nextActiveId),
    })
  },
}))
