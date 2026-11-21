import { PageHeader } from '../ui/PageHeader'
import { StyleGallery } from './StyleGallery'

/** /styles: every style the studio knows, to look at and star (the favourites come first
 * wherever a style is picked). */
export default function StylesPage() {
  return (
    <>
      <PageHeader title="Styles">Les styles du studio et de la bibliothèque Lemo-Opuscar. ★ : vos favoris, en tête de liste.</PageHeader>
      <StyleGallery />
    </>
  )
}
