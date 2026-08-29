import { describe, expect, it } from 'vitest'

import { filterProjects } from './View_Filter.ts'

const projects = [
  { id: 'current', archived: false },
  { id: 'archived', archived: true },
]

describe('dashboard view filter', () => {
  it('selects all, active, and archived projects', () => {
    expect(filterProjects(projects, 'all').map(({ id }) => id)).toEqual([
      'current',
      'archived',
    ])
    expect(filterProjects(projects, 'active').map(({ id }) => id)).toEqual([
      'current',
    ])
    expect(filterProjects(projects, 'archived').map(({ id }) => id)).toEqual([
      'archived',
    ])
  })
})
