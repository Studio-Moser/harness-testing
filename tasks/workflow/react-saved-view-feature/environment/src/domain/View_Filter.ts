import type { SavedView } from './Saved_View.ts'

export interface ViewProject {
  id: string
  archived: boolean
}

export function filterProjects<Project extends ViewProject>(
  projects: Project[],
  view: SavedView,
): Project[] {
  if (view === 'active') return projects.filter((project) => !project.archived)
  if (view === 'archived') return projects.filter((project) => project.archived)
  return projects
}
