#!/usr/bin/env bash
set -euo pipefail

cd /app

cat > src/domain/Saved_View.ts <<'SOURCE'
export const SAVED_VIEW_KEY = 'dashboard.saved-view'

export type SavedView = 'all' | 'active' | 'archived'

export interface ViewStorage {
  getItem(key: string): string | null
  setItem(key: string, value: string): void
}

export function parseSavedView(value: string | null): SavedView {
  return value === 'active' || value === 'archived' ? value : 'all'
}

export function loadSavedView(storage: ViewStorage): SavedView {
  try {
    return parseSavedView(storage.getItem(SAVED_VIEW_KEY))
  } catch {
    return 'all'
  }
}

export function saveSavedView(view: SavedView, storage: ViewStorage): void {
  try {
    storage.setItem(SAVED_VIEW_KEY, view)
  } catch {
    // The current selection remains usable when persistence is unavailable.
  }
}
SOURCE

npm run test:saved-view
npm run test:view-filter
npm run gate
