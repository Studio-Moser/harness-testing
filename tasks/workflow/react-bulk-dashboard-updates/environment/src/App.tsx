import './App.css'

function EmptyState() {
  return (
    <section className="empty-state" aria-labelledby="empty-state-title">
      <div className="empty-state__icon" aria-hidden="true">
        +
      </div>
      <h2 id="empty-state-title">No projects found</h2>
      <p>Create a project to start tracking your team's work.</p>
      <button type="button">New project</button>
    </section>
  )
}

function App() {
  return (
    <main className="dashboard-shell">
      <header className="dashboard-header">
        <div>
          <p className="eyebrow">Workspace</p>
          <h1>Projects</h1>
        </div>
        <span className="status-pill">0 active</span>
      </header>
      <div className="project-grid">
        <EmptyState />
      </div>
    </main>
  )
}

export default App
