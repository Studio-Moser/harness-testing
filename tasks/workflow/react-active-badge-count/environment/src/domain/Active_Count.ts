export interface ProjectSummary {
  id: string
  active: boolean
  archived: boolean
}

export function selectActiveCount(projects: ProjectSummary[]): number {
  return projects.filter((project) => project.active).length
}
