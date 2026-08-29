import { useState } from 'react'

import './App.css'

import {
  loadSavedView,
  saveSavedView,
  type SavedView,
} from './domain/Saved_View.ts'
import { filterProjects } from './domain/View_Filter.ts'

const projects = [
  { id: 'current', name: 'Current launch', archived: false },
  { id: 'archived', name: 'Archived migration', archived: true },
]

function App() {
  const [view, setView] = useState<SavedView>(() =>
    loadSavedView(window.localStorage),
  )
  const visibleProjects = filterProjects(projects, view)

  function chooseView(nextView: SavedView) {
    setView(nextView)
    saveSavedView(nextView, window.localStorage)
  }

  return (
    <main className="dashboard-shell">
      <header className="dashboard-header">
        <div>
          <p className="eyebrow">Workspace</p>
          <h1>Projects</h1>
        </div>
        <nav aria-label="Project views">
          {(['all', 'active', 'archived'] as const).map((candidate) => (
            <button
              aria-pressed={view === candidate}
              key={candidate}
              onClick={() => chooseView(candidate)}
              type="button"
            >
              {candidate}
            </button>
          ))}
        </nav>
      </header>
      <section className="project-grid" aria-live="polite">
        {visibleProjects.map((project) => (
          <article className="empty-state" key={project.id}>
            <h2>{project.name}</h2>
          </article>
        ))}
      </section>
    </main>
  )
}

export default App
