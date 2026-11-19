import { Link, useSearchParams } from 'react-router'
import { PageHeader } from '../ui/PageHeader'
import { buttonClass } from '../ui/styles'
import { Tabs } from '../ui/Tabs'
import MesEnvois from './MesEnvois'
import Tendances from './Tendances'

const TABS = [{ id: 'tendances', label: 'Tendances' }, { id: 'envois', label: 'Mes envois' }] as const
type Tab = (typeof TABS)[number]['id']

/** Everything the AI works from (step 135): trending Reels, and the Reels the owner sends by DM.
 * French labels: the owner's page. The tab sits in the URL (?tab=envois) so it can be linked. */
export default function TrendingPage() {
  const [params, setParams] = useSearchParams()
  const tab: Tab = params.get('tab') === 'envois' ? 'envois' : 'tendances'
  return (
    <section lang="fr">
      <PageHeader title="Trending" actions={<Link to="/trends" className={buttonClass('ghost', 'sm')}>Rapport</Link>}>
        Ce sur quoi l'IA travaille : les tendances, et les Reels que tu lui envoies.
      </PageHeader>
      <Tabs label="Trending" tabs={[...TABS]} value={tab}
        onChange={(id) => setParams(id === 'envois' ? { tab: id } : {}, { replace: true })} />
      <div role="tabpanel" aria-label={TABS.find((t) => t.id === tab)!.label} className="mt-4">
        {tab === 'tendances' ? <Tendances /> : <MesEnvois />}
      </div>
    </section>
  )
}
