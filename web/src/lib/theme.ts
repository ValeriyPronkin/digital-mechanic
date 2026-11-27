// The theme of the screen: dark, light or as the system says (Валерий, 27.11: «в гараже темно — может
// захотеться светлый фон, дать людям выбор»). Kept on the device: it is a setting of the screen, not of the
// mechanic (the mechanic's level is not kept, #91). Tested in web/tests/theme.test.ts.

export type ThemeChoice = 'dark' | 'light' | 'system'
export type Theme = 'dark' | 'light'

export const THEME_KEY = 'dm-theme'
export const THEMES: ThemeChoice[] = ['dark', 'light', 'system']
// the colour of the browser's bar, as the page's --color-bg of each theme (index.css)
export const BAR: Record<Theme, string> = { dark: '#0b0c0e', light: '#f6f7f9' }

/** What is stored, if it is a choice: anything else (nothing, an old value) is the dark theme, as before. */
export const readChoice = (stored: string | null): ThemeChoice =>
  stored === 'light' || stored === 'system' ? stored : 'dark'

/** The theme drawn: «Как в системе» follows the system's light or dark. */
export const resolve = (choice: ThemeChoice, systemLight: boolean): Theme =>
  choice === 'system' ? (systemLight ? 'light' : 'dark') : choice

const lightQuery = () => window.matchMedia('(prefers-color-scheme: light)')

export function storedChoice(): ThemeChoice {
  try {
    return readChoice(localStorage.getItem(THEME_KEY))
  } catch {
    return 'dark' // storage blocked: the default
  }
}

/** Draws a choice: the attribute the light tokens hang on, and the colour of the browser's bar. */
export function applyTheme(choice: ThemeChoice): void {
  const theme = resolve(choice, lightQuery().matches)
  document.documentElement.dataset.theme = theme
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', BAR[theme])
}

export function saveChoice(choice: ThemeChoice): void {
  try {
    localStorage.setItem(THEME_KEY, choice)
  } catch {
    // storage blocked: the choice holds until the page is closed
  }
  applyTheme(choice)
}

/** At start, before the first render: the stored choice, and «Как в системе» follows the system as it
 *  changes (evening mode on the phone). */
export function startTheme(): void {
  applyTheme(storedChoice())
  lightQuery().addEventListener('change', () => applyTheme(storedChoice()))
}
