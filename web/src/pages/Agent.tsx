import { useCallback, useEffect, useState } from 'react'
import {
  ApiError, errorMessage, getAgentLog, getAgentRuns, getPlaybooks, startAgentRun, type AgentRun,
} from '../api/client'
import { Button } from '../ui/Button'
import { Card, EmptyState, Skeleton } from '../ui/Card'
import { Chip } from '../ui/Chip'
import { PageHeader } from '../ui/PageHeader'
import { link } from '../ui/styles'
import { dateTime, playbookName, RUN_STATUS } from './load'
import StyleRequests from './StyleRequests'

const POLL_MS = 10_000
// The started process needs a moment to write its `running` row: keep polling meanwhile.
const START_GRACE_MS = 60_000

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
    <Card as="li" className="text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-semibold">{playbookName(run.playbook)}</span>
        <Chip tone={RUN_STATUS[run.status][0]}>{RUN_STATUS[run.status][1]}</Chip>
        <span className="text-muted">{dateTime(run.started_at)}</span>
      </div>
      <p className="mt-1 text-muted">
        {duration(run.duration_s)}
        {run.num_turns !== null && ` · ${run.num_turns} tours`}
        {run.cost_usd !== null && ` · ${run.cost_usd.toLocaleString('fr-FR', { style: 'currency', currency: 'USD' })}`}
      </p>
      {run.summary && (
        <>
          <p className={`mt-1 break-words whitespace-pre-wrap ${expanded ? '' : 'line-clamp-2'}`}>{run.summary}</p>
          <button type="button" className={`min-h-11 text-xs ${link}`} onClick={() => setExpanded(!expanded)}>
            {expanded ? 'Moins' : 'Plus'}
          </button>
        </>
      )}
      {run.has_log && (
        <div className="mt-1">
          <Button size="sm" aria-expanded={log !== null} onClick={() => void toggleLog()}>Journal</Button>
          {log !== null && (
            <pre className="mt-2 max-h-80 overflow-auto rounded-control bg-bg p-3 font-mono text-xs text-fg">{log}</pre>
          )}
        </div>
      )}
    </Card>
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
    if (!window.confirm(`Lancer «\u00a0${playbookName(playbook)}\u00a0» maintenant\u00a0? Ça démarre un run Claude Code, qui utilise le quota de ton abonnement.`)) return
    setError(null)
    try {
      await startAgentRun(playbook)
      setStartedAt(Date.now())
      loadRuns()
    } catch (e) {
      setError(e instanceof ApiError && e.code === 'already_running'
        ? `${playbookName(playbook)} tourne déjà` : errorMessage(e))
    }
  }

  return (
    <section>
      <PageHeader title="Agent" />
      {error && <p role="alert" className="mb-3 text-sm text-danger">{error}</p>}

      <Card as="section" aria-label="Playbooks">
        <h2 className="font-semibold">Playbooks</h2>
        {playbooks === null ? (
          <Skeleton className="mt-3 h-11" />
        ) : playbooks.length === 0 ? (
          <p className="mt-2 text-sm text-muted">Pas encore de playbooks</p>
        ) : (
          <ul className="mt-3 flex flex-wrap gap-2">
            {playbooks.map((p) => (
              <li key={p}>
                <Button variant="primary" disabled={runs?.some((r) => r.playbook === p && r.status === 'running')}
                  onClick={() => void runNow(p)}>
                  {`Lancer\u00a0: ${playbookName(p)}`}
                </Button>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <StyleRequests />

      <section aria-label="Runs de l’IA" className="mt-8">
        <h2 className="text-lg font-semibold">Runs de l’IA</h2>
        {runs === null ? (
          <Skeleton className="mt-3 h-24" />
        ) : runs.length === 0 ? (
          <div className="mt-3"><EmptyState title="Pas encore de runs">Les runs apparaissent ici quand un playbook démarre.</EmptyState></div>
        ) : (
          <ul className="mt-3 space-y-2">
            {runs.map((r) => <RunCard key={r.id} run={r} />)}
          </ul>
        )}
      </section>
    </section>
  )
}
