import { useEffect, useState, type ReactNode } from 'react'
import { useLocation } from 'react-router'
import {
  errorMessage, getAccount, getAgentSchedule, getDownloaderStatus, getHealth, getStorage, getToken,
  getWorkerStatus, setPublishingPaused, type AgentScheduleEntry, type DownloaderStatus, type RunResult,
  type TokenStatus,
} from '../api/client'
import StylesSection from '../launch/StylesSection'
import { ago } from '../trending/format'
import { Button } from '../ui/Button'
import { Card, Skeleton } from '../ui/Card'
import { Chip } from '../ui/Chip'
import { PageHeader } from '../ui/PageHeader'
import { ThemeToggle } from '../ui/ThemeToggle'
import ClipsSection from './Clips'
import DmPicksSection from './DmPicks'
import { dateTime, playbookName, RUN_STATUS } from './load'
import PermissionsSection from './Permissions'
import ReactionReelSection from './ReactionReel'
import SettingsSection from './SettingsSection'

// ponytail: fixed threshold (~a week of daily batches); make it a setting if it nags.
const LOW_FREE_BYTES = 5e9

type Load<T> = { data?: T; error?: unknown }

/** Loads once on mount; `set` replaces the data (e.g. with a route's answer). */
function useLoad<T>(fn: () => Promise<T>) {
  const [state, setState] = useState<Load<T>>({})
  useEffect(() => {
    fn().then((data) => setState({ data }), (error: unknown) => setState({ error }))
  }, [fn])
  return [state, (data: T) => setState({ data })] as const
}

/** 2.5e9 → "2,5 Go". */
function formatBytes(n: number) {
  const units = ['o', 'Ko', 'Mo', 'Go', 'To']
  let i = 0
  while (n >= 1000 && i < units.length - 1) { n /= 1000; i++ }
  const digits = i ? 1 : 0
  return `${n.toLocaleString('fr-FR', { minimumFractionDigits: digits, maximumFractionDigits: digits })} ${units[i]}`
}

// The worker's last run per outcome: [one, several].
const RUN_COUNTS = {
  published: ['publié', 'publiés'], failed: ['en échec', 'en échec'], retrying: ['à réessayer', 'à réessayer'],
  replanned: ['replanifié', 'replanifiés'],
} as const

function runSummary(r: RunResult | null) {
  if (!r) return 'Pas encore de run'
  if (r.error) return `Échec : ${r.error}`
  if (r.paused) return 'En pause, rien de publié'
  const counts = (Object.keys(RUN_COUNTS) as (keyof typeof RUN_COUNTS)[])
    .filter((k) => r[k]?.length).map((k) => `${r[k]!.length} ${RUN_COUNTS[k][r[k]!.length > 1 ? 1 : 0]}`)
  return counts.join(', ') || 'Rien à publier'
}

function Section({ id, title, load, children }: { id?: string; title: string; load: Load<unknown>; children?: ReactNode }) {
  return (
    <Card as="section" id={id} aria-label={title} className="scroll-mt-16 lg:scroll-mt-4">
      <h2 className="font-semibold">{title}</h2>
      {load.error !== undefined ? (
        <p role="alert" className="mt-2 text-sm text-danger">{errorMessage(load.error)}</p>
      ) : load.data === undefined ? (
        <Skeleton className="mt-3 h-12" />
      ) : (
        <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-sm">{children}</dl>
      )}
    </Card>
  )
}

const Row = ({ label, children }: { label: string; children: ReactNode }) => (
  <>
    <dt className="text-muted">{label}</dt>
    <dd>{children}</dd>
  </>
)

function tokenExpiry(t: TokenStatus) {
  if (!t.configured) return 'Pas de token'
  if (t.valid === null) return 'Inconnue'
  if (!t.valid) return 'Expiré ou invalide'
  if (!t.expires_at) return 'Jamais (token utilisateur système)'
  return `${new Date(t.expires_at).toLocaleDateString('fr-FR')} (encore ${t.days_left} jours)`
}

function scheduleLine(e: AgentScheduleEntry) {
  const next = e.exists ? `Prochain run le ${dateTime(e.next_at)}` : 'Playbook pas encore écrit'
  const last = e.last_run ? `dernier run ${RUN_STATUS[e.last_run.status][1]} ${ago(e.last_run.started_at)}` : 'jamais lancé'
  return `${next} · ${last}`
}

const DOWNLOADER = {
  up: ['success', 'en marche'], down: ['danger', 'arrêté'], broken: ['danger', 'en panne'],
  not_configured: ['neutral', 'non configuré'],
} as const

function DownloaderRows({ d }: { d: DownloaderStatus }) {
  const h = d.health
  return (
    <>
      <Row label="Statut">
        {!d.set_up ? <Chip tone="warn">pas installé</Chip>
          : h ? <Chip tone={DOWNLOADER[h.status][0]}>{DOWNLOADER[h.status][1]}</Chip>
            : <Chip tone="neutral">pas encore vérifié</Chip>}
      </Row>
      {h && <Row label="Dernière vérification">{ago(h.checked_at)}{h.detail && ` · ${h.detail}`}</Row>}
      {!d.set_up && (
        <Row label="L’installer">
          Lance <code className="rounded bg-surface-2 px-1.5 py-0.5 select-all">ig-campaign downloader setup</code>
        </Row>
      )}
      {!d.health_configured && <Row label="Contrôle de santé">Désactivé : mets <code>DOWNLOADER_HEALTH_URL</code> dans .env</Row>}
      <Row label="Adresse">{d.host}:{d.port} (cet ordinateur seulement)</Row>
    </>
  )
}

// The section index (UI-016): page order, each id on its section's root; each label = its section's title.
const SECTIONS = [
  ['appearance', 'Apparence'], ['worker', 'Worker'], ['instagram', 'Instagram'], ['storage', 'Stockage'],
  ['backups', 'Sauvegardes'], ['agent-schedule', "Planning de l'IA"], ['studio', 'Studio'], ['styles', 'Styles'],
  ['ads', 'Pubs'], ['clips', 'Clips'], ['permissions', 'Autorisations'], ['reaction-reel', 'Reel réaction'],
  ['dm-picks', 'DM'], ['reel-downloader', 'Téléchargeur'], ['server', 'Serveur'],
] as const

const str = (v: unknown) => (typeof v === 'string' || typeof v === 'number' ? String(v) : undefined)

export default function Settings() {
  const [health] = useLoad(getHealth)
  const [account] = useLoad(getAccount)
  const [worker, setWorker] = useLoad(getWorkerStatus)
  const [storage] = useLoad(getStorage)
  const [token] = useLoad(getToken)
  const [schedule] = useLoad(getAgentSchedule)
  const [downloader] = useLoad(getDownloaderStatus)
  const [toggleError, setToggleError] = useState<string | null>(null)
  const { hash } = useLocation()

  // React Router does not jump to a #section. Every section's root is there from the first render,
  // but the ones above it grow as their data comes in: follow it until the owner scrolls (or 5 s).
  useEffect(() => {
    const el = hash && document.getElementById(hash.slice(1))
    if (!el) return
    const jump = () => el.scrollIntoView?.({ block: 'start' })
    jump()
    if (!window.ResizeObserver) return
    const ro = new ResizeObserver(jump)
    for (const s of el.parentElement!.children) ro.observe(s)
    const stop = () => ro.disconnect()
    const INPUT = ['wheel', 'touchstart', 'keydown', 'pointerdown'] as const
    for (const e of INPUT) window.addEventListener(e, stop, { once: true, passive: true })
    const timer = setTimeout(stop, 5000)
    return () => {
      stop()
      clearTimeout(timer)
      for (const e of INPUT) window.removeEventListener(e, stop)
    }
  }, [hash])

  const setupMode = health.data?.instagram_configured === false || account.data?.configured === false

  async function togglePause(paused: boolean) {
    const question = paused
      ? 'Mettre la publication en pause ? Rien ne part tant que tu ne reprends pas.'
      : 'Reprendre la publication ? Les posts prévus partent au prochain run.'
    if (!window.confirm(question)) return
    setToggleError(null)
    try {
      setWorker(await setPublishingPaused(paused))
    } catch (e) {
      setToggleError(errorMessage(e))
    }
  }

  const w = worker.data
  const profile = account.data?.profile
  const limit = account.data?.publishing_limit
  const quotaTotal = (limit?.config as Record<string, unknown> | undefined)?.quota_total
  const s = storage.data

  return (
    <section>
      <PageHeader title="Réglages" />
      <nav aria-label="Sections" className="-mx-4 mb-4 flex gap-2 overflow-x-auto px-4 pb-1 lg:mx-0 lg:flex-wrap lg:px-0">
        {SECTIONS.map(([id, label]) => (
          <a key={id} href={`#${id}`}
            className="inline-flex min-h-11 shrink-0 items-center rounded-full border border-line bg-surface-2 px-4 text-sm font-medium">
            {label}
          </a>
        ))}
      </nav>
      {setupMode && (
        <p role="status" className="mb-4 rounded-card border border-warn/30 bg-warn/12 p-4 font-medium text-warn">
          Mode configuration : ajoute ton token Instagram
        </p>
      )}

      <div className="gap-4 lg:columns-2 [&>*]:mb-4 [&>*]:break-inside-avoid">
        <Card as="section" id="appearance" aria-label="Apparence" className="scroll-mt-16 lg:scroll-mt-4">
          <h2 className="font-semibold">Apparence</h2>
          <p className="mt-1 text-sm text-muted">Le sombre va mieux pour regarder les vidéos ; le choix reste dans ce navigateur.</p>
          <div className="mt-3"><ThemeToggle /></div>
        </Card>

        <div id="worker" className="scroll-mt-16 lg:scroll-mt-4">
          <Section title="Worker" load={worker}>
            {w && (
              <>
                <Row label="Statut">
                  <span aria-hidden className={`mr-1.5 inline-block size-2 rounded-full ${w.alive ? 'bg-success' : 'bg-danger'}`} />
                  {w.alive ? 'En marche' : 'Arrêté'}
                </Row>
                <Row label="Dernier signe de vie">{w.heartbeat_at ? ago(w.heartbeat_at) : 'Jamais'}</Row>
                <Row label="Prochain créneau">{w.next_slot ? dateTime(w.next_slot) : 'Rien en attente'}</Row>
                <Row label="Dernier run">{runSummary(w.last_result)}</Row>
                <Row label="Publication">{w.paused ? 'En pause' : 'Active'}</Row>
              </>
            )}
          </Section>
          {w && (
            <div className="mt-2">
              <Button variant={w.paused ? 'primary' : 'secondary'} className={`w-full md:w-auto ${w.paused ? '' : 'text-warn!'}`}
                onClick={() => void togglePause(!w.paused)}>
                {w.paused ? 'Reprendre la publication' : 'Mettre la publication en pause'}
              </Button>
              {toggleError && <p role="alert" className="mt-1 text-sm text-danger">{toggleError}</p>}
            </div>
          )}
        </div>

        <Section id="instagram" title="Instagram" load={setupMode ? { data: true } : account}>
          <Row label="Configuré">{setupMode ? 'Non' : 'Oui'}</Row>
          {!setupMode && (
            <>
              <Row label="Token">{account.data?.token_valid ? 'Valide' : 'Invalide'}</Row>
              <Row label="Compte">{str(profile?.username) ?? '—'}</Row>
              <Row label="Limite de publication">
                {str(limit?.quota_usage) ?? '?'} / {str(quotaTotal) ?? '?'} en 24 h
              </Row>
            </>
          )}
          <Row label="Fin du token">
            {token.error !== undefined ? errorMessage(token.error) : token.data ? tokenExpiry(token.data) : 'Chargement…'}
          </Row>
        </Section>

        <Section id="storage" title="Stockage" load={storage}>
          {s && (
            <>
              <Row label="Médias">{formatBytes(s.media_bytes)}</Row>
              <Row label="Base de données">{formatBytes(s.db_bytes)}</Row>
              <Row label="Espace libre">
                {formatBytes(s.free_bytes)}
                {s.free_bytes < LOW_FREE_BYTES && (
                  <span role="alert" className="ml-2 font-medium text-danger">Faible : libère de la place</span>
                )}
              </Row>
            </>
          )}
        </Section>

        <Section id="backups" title="Sauvegardes" load={storage}>
          <Row label="Dernière sauvegarde">{s?.last_backup ? dateTime(s.last_backup) : 'Pas encore de sauvegarde'}</Row>
        </Section>

        <Section id="agent-schedule" title="Planning de l'IA" load={schedule}>
          {schedule.data?.length === 0 && <Row label="Runs">Aucun (AGENT_SCHEDULE est vide)</Row>}
          {schedule.data?.map((e) => (
            <Row key={e.playbook} label={`${playbookName(e.playbook)} à ${e.time}`}>{scheduleLine(e)}</Row>
          ))}
        </Section>

        <SettingsSection section="studio" title="Studio" />
        <StylesSection />
        <SettingsSection section="ads" title="Pubs" />
        <ClipsSection />
        <PermissionsSection />
        <ReactionReelSection />
        <DmPicksSection />
        <Section id="reel-downloader" title="Téléchargeur" load={downloader}>
          {downloader.data && <DownloaderRows d={downloader.data} />}
        </Section>

        <Section id="server" title="Serveur" load={health}>
          <Row label="Version">{health.data ? `${health.data.status}, v${health.data.version}` : ''}</Row>
        </Section>
      </div>
    </section>
  )
}
