import { useCallback, useEffect, useState } from 'react'
import {
  ApiError, errorMessage, getAgentLog, getAgentRuns, getPlaybooks, startAgentRun, type AgentRun,
} from '../api/client'
import { button, chip } from '../inbox/ui'

const POLL_MS = 10_000
// The started process needs a moment to write its `running` row: keep polling meanwhile.
const START_GRACE_MS = 60_000

const STATUS_CHIP: Record<AgentRun['status'], string> = {
  running: 'bg-blue-100 text-blue-800',
  succeeded: 'bg-green-100 text-green-800',
  failed: 'bg-red-100 text-red-800',
  cancelled: 'bg-gray-200 text-gray-700',
}

function duration(s: number) {
  const m = Math.floor(s / 60)
  return m ? `${m} min ${s % 60} s` : `${s} s`
}

function RunCard({ run }: { run: AgentRun }) {
  const [expanded, setExpanded] = useState(false)
  const [log, setLog] = useState<string | null>(null)

  async function toggleLog() {
    if (log !== null) return setLog(null)
    try {
      setLog((await getAgentLog(run.id)).lines.join('\n'))
    } catch (e) {
      setLog(errorMessage(e))
    }
  }

  return (
    <li className="rounded-lg border border-gray-200 bg-white p-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-semibold">{run.playbook}</span>
        <span className={`${chip} ${STATUS_CHIP[run.status]}`}>{run.status}</span>
        <span className="text-gray-500">{new Date(run.started_at).toLocaleString()}</span>
      </div>
      <p className="mt-1 text-gray-600">
        {duration(run.duration_s)}
        {run.num_turns !== null && ` · ${run.num_turns} turns`}
        {run.cost_usd !== null && ` · $${run.cost_usd.toFixed(2)}`}
      </p>
      {run.summary && (
        <>
          <p className={`mt-1 break-words whitespace-pre-wrap ${expanded ? '' : 'line-clamp-2'}`}>{run.summary}</p>
          <button type="button" className="text-xs text-blue-600" onClick={() => setExpanded(!expanded)}>
            {expanded ? 'Less' : 'More'}
          </button>
        </>
      )}
      {run.has_log && (
        <div className="mt-1">
          <button type="button" className={`${button} bg-gray-100`} aria-expanded={log !== null}
            onClick={() => void toggleLog()}>
            Log
          </button>
          {log !== null && (
            <pre className="mt-2 max-h-80 overflow-auto rounded bg-gray-900 p-2 text-xs text-gray-100">{log}</pre>
          )}
        </div>
      )}
    </li>
  )
}

export default function Agent() {
  const [playbooks, setPlaybooks] = useState<string[] | null>(null)
  const [runs, setRuns] = useState<AgentRun[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [startedAt, setStartedAt] = useState(0)

  const loadRuns = useCallback(() => {
    getAgentRuns().then(setRuns, (e: unknown) => setError(errorMessage(e)))
  }, [])

  useEffect(() => {
    getPlaybooks().then(setPlaybooks, (e: unknown) => setError(errorMessage(e)))
    loadRuns()
  }, [loadRuns])

  // Poll while a run is going (or one was just started); each answer re-arms the timer.
  useEffect(() => {
    if (!runs) return
    if (!runs.some((r) => r.status === 'running') && Date.now() - startedAt > START_GRACE_MS) return
    const t = setTimeout(loadRuns, POLL_MS)
    return () => clearTimeout(t)
  }, [runs, startedAt, loadRuns])

  async function runNow(playbook: string) {
    if (!window.confirm(`Run ${playbook} now? Starts a Claude Code run; it uses your plan's usage.`)) return
    setError(null)
    try {
      await startAgentRun(playbook)
      setStartedAt(Date.now())
      loadRuns()
    } catch (e) {
      setError(e instanceof ApiError && e.code === 'already_running'
        ? `${playbook} is already running` : errorMessage(e))
    }
  }

  return (
    <section>
      <h2 className="text-2xl font-semibold">Agent</h2>
      {error && <p role="alert" className="mt-2 text-sm text-red-700">{error}</p>}

      <section aria-label="Playbooks" className="mt-4">
        <h3 className="font-semibold">Playbooks</h3>
        {playbooks === null ? (
          <p className="mt-2 text-sm text-gray-500">Loading…</p>
        ) : playbooks.length === 0 ? (
          <p className="mt-2 text-sm text-gray-500">No playbooks yet</p>
        ) : (
          <ul className="mt-2 flex flex-wrap gap-2">
            {playbooks.map((p) => (
              <li key={p}>
                <button type="button" className={`${button} bg-blue-600 text-white`}
                  disabled={runs?.some((r) => r.playbook === p && r.status === 'running')}
                  onClick={() => void runNow(p)}>
                  Run {p} now
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-label="Runs" className="mt-6">
        <h3 className="font-semibold">Runs</h3>
        {runs === null ? (
          <p className="mt-2 text-sm text-gray-500">Loading…</p>
        ) : runs.length === 0 ? (
          <p className="mt-2 text-sm text-gray-500">No runs yet</p>
        ) : (
          <ul className="mt-2 space-y-2">
            {runs.map((r) => <RunCard key={r.id} run={r} />)}
          </ul>
        )}
      </section>
    </section>
  )
}
