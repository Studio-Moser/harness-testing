export const SAVED_VIEW_KEY = 'dashboard.saved-view'

export type SavedView = 'all' | 'active' | 'archived'

export interface ViewStorage {
  getItem(key: string): string | null
  setItem(key: string, value: string): void
}

export function parseSavedView(value: string | null): SavedView {
  void value
  return 'all'
}

export function loadSavedView(storage: ViewStorage): SavedView {
  return parseSavedView(storage.getItem(SAVED_VIEW_KEY))
}

export function saveSavedView(view: SavedView, storage: ViewStorage): void {
  void view
  void storage
}
