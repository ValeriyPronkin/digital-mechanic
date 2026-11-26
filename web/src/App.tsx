import { useCallback, useEffect, useState } from 'react'
import { getFleet, type FleetView } from './api'
import { FleetList, type Role } from './components/FleetList'
import { LevelQuestion } from './components/LevelQuestion'
import { VehicleScreen } from './components/VehicleScreen'
import { copy } from './copy'
import { isLevelChosen } from './lib/level'

const fromHash = () => decodeURIComponent(window.location.hash.replace(/^#\/?/, '')) || null
const savedRole = (): Role => (localStorage.getItem('role') === 'chief' ? 'chief' : 'mechanic')

/** Phone: one screen at a time (fleet, then vehicle). Wide screen: the fleet stays on the left. */
export default function App() {
  const [fleet, setFleet] = useState<FleetView | null>(null)
  const [failed, setFailed] = useState(false)
  const [selected, setSelected] = useState<string | null>(fromHash)
  const [role, setRole] = useState<Role>(savedRole)
  // the first visit asks a mechanic once how to explain (#17); the chief mechanic reads the fleet, not answers
  const [askLevel, setAskLevel] = useState(() => !isLevelChosen())

  // Also called after a ticket or an outcome: the list shows «заявка создана» and the outcome counts.
  // If that reload fails, the list already on the screen stays; only an empty screen says it failed.
  const loadFleet = useCallback(() => {
    getFleet()
      .then((view) => {
        setFleet(view)
        setFailed(false)
      })
      .catch(() => setFailed(true))
  }, [])
  const retryFleet = () => {
    setFailed(false) // back to «Загружаем парк…» while the request runs
    loadFleet()
  }

  useEffect(() => {
    loadFleet()
    const onHash = () => setSelected(fromHash())
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [loadFleet])

  const select = (id: string | null) => {
    window.location.hash = id ? `/${encodeURIComponent(id)}` : ''
  }
  const changeRole = (next: Role) => {
    localStorage.setItem('role', next)
    setRole(next)
  }

  return (
    <div className="flex h-dvh">
      {askLevel && role === 'mechanic' && <LevelQuestion onDone={() => setAskLevel(false)} />}
      <aside
        className={`w-full shrink-0 border-line min-[900px]:block min-[900px]:w-[360px] min-[900px]:border-r ${selected ? 'hidden' : ''}`}
      >
        <FleetList
          fleet={fleet}
          failed={failed}
          onRetry={retryFleet}
          role={role}
          onRole={changeRole}
          selected={selected}
          onSelect={select}
        />
      </aside>
      <main className={`min-w-0 flex-1 ${selected ? '' : 'hidden min-[900px]:block'}`}>
        {selected ? (
          <VehicleScreen key={selected} vehicleId={selected} onBack={() => select(null)} onTicketsChanged={loadFleet} />
        ) : (
          <div className="grid h-full place-items-center p-8 text-center">
            <div>
              <p className="text-[17px] font-semibold">{copy.fleet.pick}</p>
              <p className="mt-1 max-w-sm text-dim">{role === 'chief' ? copy.chief.hint : copy.fleet.pickHint}</p>
            </div>
          </div>
        )}
      </main>
    </div>
  )
}
