import './App.css'

import { selectActiveCount, type ProjectSummary } from './domain/Active_Count.ts'

const projects: ProjectSummary[] = [
  { id: 'current', active: true, archived: false },
  { id: 'archived', active: true, archived: true },
  { id: 'paused', active: false, archived: false },
]

function App() {
  const activeCount = selectActiveCount(projects)

  return (
    <main className="dashboard-shell">
      <header className="dashboard-header">
        <div>
          <p className="eyebrow">Workspace</p>
          <h1>Projects</h1>
        </div>
        <span className="status-pill">{activeCount} active</span>
      </header>
      <section className="empty-state" aria-labelledby="summary-title">
        <h2 id="summary-title">Project summary</h2>
        <p>Archived projects stay available without affecting the active badge.</p>
      </section>
    </main>
  )
}

export default App
