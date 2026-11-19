import { useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import CreateVideoSheet from '../launch/CreateVideoSheet'
import { Button } from '../ui/Button'
import { PageHeader } from '../ui/PageHeader'
import { buttonClass } from '../ui/styles'
import { Tabs } from '../ui/Tabs'
import { useToast } from '../ui/useToast'
import MesEnvois from './MesEnvois'
import Tendances from './Tendances'

const TABS = [{ id: 'tendances', label: 'Tendances' }, { id: 'envois', label: 'Mes envois' }] as const
type Tab = (typeof TABS)[number]['id']

/** Everything the AI works from (step 135): trending Reels, and the Reels the owner sends by DM.
 * French labels: the owner's page. The tab sits in the URL (?tab=envois) so it can be linked.
 * « Créer une vidéo » (138): a video from a topic alone; it lands in Mes envois. */
export default function TrendingPage() {
  const [params, setParams] = useSearchParams()
  const [creating, setCreating] = useState(false)
  const [sent, setSent] = useState(0) // bumped: Mes envois reloads
  const toast = useToast()
  const tab: Tab = params.get('tab') === 'envois' ? 'envois' : 'tendances'
  return (
    <section lang="fr">
      <PageHeader title="Trending" actions={
        <>
          <Button variant="primary" size="sm" onClick={() => setCreating(true)}>Créer une vidéo</Button>
          <Link to="/trends" className={buttonClass('ghost', 'sm')}>Rapport</Link>
        </>
      }>
        Ce sur quoi l'IA travaille : les tendances, et les Reels que tu lui envoies.
      </PageHeader>
      <Tabs label="Trending" tabs={[...TABS]} value={tab}
        onChange={(id) => setParams(id === 'envois' ? { tab: id } : {}, { replace: true })} />
      <div role="tabpanel" aria-label={TABS.find((t) => t.id === tab)!.label} className="mt-4">
        {tab === 'tendances' ? <Tendances /> : <MesEnvois key={sent} />}
      </div>
      {creating && (
        <CreateVideoSheet onClose={() => setCreating(false)} onSent={() => {
          setCreating(false)
          setSent((n) => n + 1)
          setParams({ tab: 'envois' }, { replace: true })
          toast({ message: "Envoyé à l'IA : la vidéo est dans Mes envois." })
        }} />
      )}
    </section>
  )
}
