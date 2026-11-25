# UI audit — Growth Studio web app — 2026-11-25
Commit: `d6f09e2` · URL: local (`ig-campaign serve`, built `web/dist`) · Viewports: desktop 1440×900,
tablet 768×1024, phone 390×844 · Themes: dark (all), light (6 pages) · Role: owner (no password
set) · Data: fake (throw-away database, `dev seed --days 14 --seed 7`, fake Instagram token,
Graph API pointed at a dead local port). Nothing was sent to Instagram, ElevenLabs or Claude.

> **How to review:** every correction below is ON. Untick `[x] DO` (or delete the
> block) for the ones you don't want, add a note if you want one changed, commit.
> Team-up will implement every correction still ticked.

Screenshots are in `screenshots/` (git-ignored, on this machine only).

## Summary
The studio looks consistent and calm: one amber accent, good empty states, 44 px touch targets,
visible keyboard focus, no console errors on most pages and no sideways scrolling on any phone
page. **Biggest risk:** on the phone, a quick double-tap on **Approve** in the Inbox approves
the *next* video too, one the owner never saw (UI-001, reproduced 2/2). A second publish risk:
on the video page, **Approve ignores a caption you typed but did not save**, so the old caption
goes out (UI-002, reproduced 2/2). **Biggest quick wins:** the Planning launch bar that covers a
third of the phone screen (UI-003) and the Calendar's missing week label on phone (UI-004).
The owner answered the six questions (see « Answered questions »): the whole app goes French
(UI-013), Planning gets a phone tab (UI-014), plain job names (UI-015), a Settings index
(UI-016), the video page uses the Inbox's four decisions (UI-017); technical wording stays.

Counts: P0 1 · P1 3 · P2 13 · Open questions 0.

## Scorecard
| Screen | Beauty | Logic | Bug safety | One-line reason |
|---|---|---|---|---|
| Inbox (feed) | 4 | 4 | 2 | Focused and fast; double-tap decides an unseen video (UI-001); rail discs vanish on black bars (UI-007) |
| Video page | 3 | 3 | 2 | Approve drops an unsaved caption (UI-002); its verdict words differ from the Inbox (Q6) |
| Créer | 4 | 4 | 5 | Clear form, 500-char limit explained, no double submit, script text shown as text |
| Planning | 2 | 3 | 4 | Launch bar covers 31 % of the phone screen (UI-003); 7 equal amber buttons (UI-010); job names (Q3) |
| Trending | 3 | 3 | 4 | Two primaries; big « Actualiser » with no topics |
| Calendar | 4 | 2 | 4 | On phone and tablet no way to tell which week is shown (UI-004) |
| Analytics | 4 | 4 | 4 | Good funnel; a 404 logged on every load when there is no report |
| Posts / What works / Report / Trends | 4 | 4 | 5 | Plain empty states, nothing broken |
| Learnings | 4 | 3 | 5 | Four rows of filters on an empty page |
| Styles | 4 | 4 | 5 | Desktop category row is cut off with no scroll hint (UI-008) |
| Voix | 3 | 3 | 4 | Switched-off cards fail contrast (UI-009); descriptions cut mid-word (UI-012) |
| Ads | 4 | 4 | 5 | Clear caps; kill switch prominent even when nothing can spend |
| Agent | 3 | 3 | 4 | Five amber buttons; each run asks for confirmation (good) |
| Settings | 3 | 2 | 4 | 6 600 px tall on phone, no section jump list (Q4) |
| App shell | 4 | 4 | 3 | Blank screen while the session check is slow (UI-005); load errors have no retry (UI-006) |

## Corrections

### UI-001 · P0 · Bug risk · A double-tap on Approve also approves the next video, unseen
- [x] **DO**   Note: ____
- **Where:** Inbox › Today feed · phone (touch). Desktop double-click approved only one video.
- **Before:** ![](screenshots/inbox-doubletap__mobile__before.png)
- **Reproduce:** 1. Phone, `/inbox`, at least two undecided videos. 2. Tap **Approve** twice
  at the same spot, 180 ms apart (also 250 ms). 3. Wait out the 5 s undo. → two
  `approve-and-queue` calls: the video tapped (133) **and** the next one (134), which slid under
  the finger after the first tap. Reproduced twice (133+134, 135+131).
- **Why:** Q3. The owner reviews on the phone in a hurry; a nervous double-tap queues a video
  for publishing that they never watched. The undo toast shows only the latest decision.
- **Correction (exact):** after any rail decision (Approve, Change, Decline, Save for later),
  the feed ignores rail taps for **600 ms**. Keyboard shortcuts (a, d, c, s) are unchanged.
  No visual change.
- **After:** ![](screenshots/UI-001__after__mobile.png) — same double-tap with the lock
  injected: one call only (133), then (134) on the second run; the next video stays undecided.
- **Test (fails today, must pass):** phone viewport, `page.touchscreen.tap(x, y)` on the first
  card's Approve, wait 180 ms, tap the same `(x, y)` again, dispatch `pagehide` → exactly one
  `POST /api/assets/*/approve-and-queue`, for the first card's id. Vitest equivalent in
  `InboxPage.test.tsx`: two clicks on two consecutive cards' Approve within 100 ms → the second
  is ignored.
- **Suggested diff:**
  ```diff
  // web/src/inbox/InboxPage.tsx
     const scroller = useRef<HTMLDivElement>(null)
  +  // After a decision the next card slides in under the finger: a double-tap must not decide it.
  +  const settle = useRef(0)
  +  const tap = (f: () => void) => () => {
  +    if (Date.now() < settle.current) return
  +    settle.current = Date.now() + 600
  +    f()
  +  }
  …
  -              onApprove={() => void approve(a)}
  +              onApprove={tap(() => void approve(a))}
  …
  -              onDecline={() => setDeclineFor(a)}
  -              onChange={() => openChange(a)}
  -              onSave={tab === 'today' ? () => save(a) : undefined}
  +              onDecline={tap(() => setDeclineFor(a))}
  +              onChange={tap(() => openChange(a))}
  +              onSave={tab === 'today' ? tap(() => save(a)) : undefined}
  ```
- **Likely files:** `web/src/inbox/InboxPage.tsx`, `web/src/inbox/InboxPage.test.tsx`
- **Acceptance:** - [ ] double-tap test passes on phone - [ ] two deliberate taps on two
  videos more than 600 ms apart still decide both - [ ] keyboard `a a` unchanged
- **Effort:** S · **Risk:** low · **Confidence:** high

### UI-002 · P1 · Bug risk · Approve on the video page publishes the old caption when the new one isn't saved
- [x] **DO**   Note: ____
- **Where:** Video page `/assets/:id` › Caption + Approve · desktop and phone
- **Before:** ![](screenshots/asset-caption__mobile__approve-unsaved.png)
- **Reproduce:** 1. Open a ready video. 2. Type a new caption, do **not** press Save.
  3. Press **Approve** → the schedule sheet opens; the field still shows the new caption but the
  stored caption is the old one. Accepting queues it with the old caption, and a scheduled video
  refuses caption edits afterwards. Reproduced twice (videos 139 phone, 137 desktop).
- **Why:** Q3 + Q2. Editing then approving is the natural order; nothing says the edit was
  dropped. The wrong caption reaches Instagram.
- **Correction (exact):** Approve first saves a caption that differs from the stored one
  (same `editAsset` call as Save); if that save fails, the error shows in the existing error
  line and the video is **not** approved. Best-before is left to Save (a scheduled video still
  accepts it).
- **After:** ![](screenshots/UI-002__after__mobile.png) · ![](screenshots/UI-002__after__desktop.png)
  — with the save injected before approve, the stored caption is the typed one on both runs.
- **Test (fails today, must pass):** `/assets/:id`, fill caption "NEW", click Approve →
  `GET /api/assets/:id` returns `caption: "NEW"` and `status: "approved"`.
- **Suggested diff:**
  ```diff
  // web/src/inbox/AssetPage.tsx
     async function approve() {
  +    // An edited caption not saved yet goes first: a scheduled video refuses caption edits.
  +    if (caption !== (asset?.caption ?? '') && !(await act(() => editAsset(id, { caption })))) return
       if (await act(() => approveAsset(id))) setScheduling(true) // then the explicit second step
     }
  ```
- **Likely files:** `web/src/inbox/AssetPage.tsx`, `web/src/inbox/AssetPage.test.tsx`
- **Acceptance:** - [ ] test passes - [ ] approve with an unchanged caption makes no PATCH
  - [ ] a failed caption save leaves the video unapproved with the error shown
- **Effort:** S · **Risk:** low · **Confidence:** high

### UI-003 · P1 · Layout · On the phone the Planning launch bar covers a third of the screen, even with nothing selected
- [x] **DO**   Note: ____
- **Where:** Planning › « Lancer la sélection (0) » bar · phone (also desktop)
- **Before:** ![](screenshots/planning__mobile__default.png) (viewport: bar 158 px + tab bar
  56 px + header 48 px = 262 of 844 px always covered)
- **Why:** Q1/Q2. The cards the owner reads are hidden behind a bar whose main button is
  disabled; the long explanation repeats on every scroll.
- **Correction (exact):** while **no card is selected**, the bar is not sticky (it sits at the
  end of the list, in the flow) and shows its explanation. Once **one or more** cards are
  selected it becomes sticky as today, without the explanation sentence (bar 122 px on phone).
  « Tout lancer » stays in the bar in both states.
- **After:** ![](screenshots/UI-003__after__mobile.png) · ![](screenshots/UI-003__after__mobile-selected.png)
  · ![](screenshots/UI-003__after__desktop.png) (computed `position: static` with 0 selected)
- **Suggested diff:**
  ```diff
  // web/src/pages/Planning.tsx
          <div role="region" aria-label="Lancer"
  -          className="sticky bottom-[calc(3.5rem+env(safe-area-inset-bottom))] z-20 mt-6 rounded-card border border-line bg-surface/95 p-3 text-sm shadow-overlay backdrop-blur-md lg:bottom-4">
  +          className={`mt-6 rounded-card border border-line bg-surface/95 p-3 text-sm ${chosen.length
  +            ? 'sticky bottom-[calc(3.5rem+env(safe-area-inset-bottom))] z-20 shadow-overlay backdrop-blur-md lg:bottom-4' : ''}`}>
  …
  -            <span className="text-muted">Un seul travail lourd à la fois : …</span>
  +            {!chosen.length && <span className="text-muted">Un seul travail lourd à la fois : …</span>}
  ```
- **Likely files:** `web/src/pages/Planning.tsx`, `web/src/pages/Planning.test.tsx`
- **Acceptance:** - [ ] 0 selected: bar not sticky, explanation shown - [ ] ≥1 selected: bar
  sticky above the tab bar, explanation hidden - [ ] « Tout lancer » works in both states
- **Effort:** S · **Risk:** low · **Confidence:** high

### UI-004 · P1 · Logic · On phone and tablet the Calendar never says which week it shows
- [x] **DO**   Note: ____
- **Where:** Calendar · phone and tablet (below 1280 px, empty days are hidden, and in an empty
  week nothing on screen names the week)
- **Before:** ![](screenshots/calendar__mobile__next-week.png) (after « Next week »: same
  screen as this week)
- **Why:** Q2. After Previous/Next week the owner can't tell where they are; « Nothing queued
  this week » is ambiguous.
- **Correction (exact):** under the title, on every viewport, the week range in the
  PageHeader subtitle slot (`text-sm text-muted`), built with the existing `dayLabel`:
  « Mon, Nov 30 – Sun, Dec 6 » (en dash with spaces).
- **After:** ![](screenshots/UI-004__after__mobile.png) · ![](screenshots/UI-004__after__tablet.png)
- **Suggested diff:**
  ```diff
  // web/src/calendar/CalendarPage.tsx
  -      <PageHeader title="Calendar" actions={
  +      <PageHeader title="Calendar" actions={
           …
  -      } />
  +      }>
  +        {cal && `${dayLabel(cal.days[0].date)} – ${dayLabel(cal.days.at(-1)!.date)}`}
  +      </PageHeader>
  ```
- **Likely files:** `web/src/calendar/CalendarPage.tsx`, `CalendarPage.test.tsx`
- **Acceptance:** - [ ] range shown on phone, tablet, desktop - [ ] it changes with
  Previous / This / Next week
- **Effort:** S · **Risk:** low · **Confidence:** high

### UI-005 · P2 · Feedback · Blank screen while the app checks the session
- [x] **DO**   Note: ____
- **Where:** every page, first load · phone and desktop
- **Before:** ![](screenshots/inbox__mobile__slow.png) (API slowed to 3 s: nothing at all for
  the whole wait; `Login` returns `null` while `checking`)
- **Why:** Q1/Q2. On a phone over a slow link the owner sees an empty dark page and may think
  the studio is down.
- **Correction (exact):** while `state === 'checking'`, render a centred spinner reusing the
  Button spinner style: `size-8 animate-spin rounded-full border-2 border-current
  border-r-transparent text-accent`, in a `role="status"` wrapper with `aria-label="Chargement"`.
- **After:** ![](screenshots/UI-005__after__mobile.png) · ![](screenshots/UI-005__after__desktop.png)
- **Suggested diff:**
  ```diff
  // web/src/Login.tsx
  -  if (state === 'checking') return null
  +  if (state === 'checking')
  +    return (
  +      <div role="status" aria-label="Chargement" className="grid min-h-dvh place-items-center">
  +        <span aria-hidden className="size-8 animate-spin rounded-full border-2 border-current border-r-transparent text-accent" />
  +      </div>
  +    )
  ```
- **Likely files:** `web/src/Login.tsx`, `web/src/Login.test.tsx`
- **Acceptance:** - [ ] slow `/api/session` shows the spinner - [ ] fast load goes straight to
  the page
- **Effort:** S · **Risk:** low · **Confidence:** high

### UI-006 · P2 · Errors · Inbox load error has no way to try again
- [x] **DO**   Note: ____
- **Where:** Inbox › « Could not load the batch (…) » · phone and desktop
- **Before:** ![](screenshots/inbox__mobile__api500.png)
- **Why:** Q2. The only way out is a full browser refresh, which on a home-screen app is hidden.
- **Correction (exact):** after the error text, a text button **« Réessayer »** (French,
  per Q1): `ml-1 min-h-11 font-semibold underline
  underline-offset-2`. It clears the error and refetches the feed. Note `reload()` alone does
  not refetch (the feed effect depends on `[date, tab]`): add an `attempt` counter to that
  effect's dependencies and bump it.
- **After:** ![](screenshots/UI-006__after__mobile.png) · ![](screenshots/UI-006__after__desktop.png)
- **Test:** mock `/api/assets?…` 500 once then 200 → click Retry → the feed shows cards.
- **Likely files:** `web/src/inbox/InboxPage.tsx`, `InboxPage.test.tsx`
- **Acceptance:** - [ ] Retry refetches and clears the error - [ ] a save error keeps the same
  button and refreshes the feed
- **Effort:** S · **Risk:** low · **Confidence:** high

### UI-007 · P2 · Visual · Change and Decline circles disappear on the black bars of the phone feed
- [x] **DO**   Note: ____
- **Where:** Inbox feed › right rail · phone (any video narrower than the screen's ratio)
- **Before:** ![](screenshots/inbox__mobile__default.png) — Change / Decline discs are
  `bg-black/55` on black: only the icons and labels float
- **Why:** Q1. The buttons look unfinished and their tap area is invisible.
- **Correction (exact):** on the non-primary rail disc only, add a 1 px inner ring
  `ring-1 ring-inset ring-white/25` (removed from `lg` where the disc is `bg-surface-2`:
  `lg:ring-0`).
- **After:** ![](screenshots/UI-007__after__mobile.png)
- **Suggested diff:**
  ```diff
  // web/src/inbox/AssetCard.tsx (RailButton)
  -        primary ? 'bg-accent text-on-accent' : 'bg-black/55 backdrop-blur group-hover:bg-black/70 lg:bg-surface-2 lg:text-fg lg:group-hover:bg-line'}`}>
  +        primary ? 'bg-accent text-on-accent' : 'bg-black/55 ring-1 ring-white/25 ring-inset backdrop-blur group-hover:bg-black/70 lg:bg-surface-2 lg:text-fg lg:ring-0 lg:group-hover:bg-line'}`}>
  ```
- **Acceptance:** - [ ] discs visible on black and on bright video - [ ] desktop unchanged
- **Effort:** S · **Risk:** low · **Confidence:** high

### UI-008 · P2 · Layout · Desktop style categories are cut off at the right edge
- [x] **DO**   Note: ____
- **Where:** Styles › Famille and Catégorie chip rows · desktop (15 categories, last ones
  clipped, no scroll hint; « L… » cut in half)
- **Before:** ![](screenshots/styles__desktop__default.png)
- **Why:** Q1/Q2. Half the categories are unreachable without a trackpad side-scroll the page
  never suggests.
- **Correction (exact):** from `lg` the two rows wrap: add `lg:flex-wrap lg:overflow-visible`.
  Phone keeps the swipe row.
- **After:** ![](screenshots/UI-008__after__desktop.png) (2 lines, nothing clipped)
- **Suggested diff:** in `web/src/styles/StyleGallery.tsx` lines 149 and 156:
  `"flex gap-2 overflow-x-auto pb-1 [&>*]:shrink-0"` → `"flex gap-2 overflow-x-auto pb-1 lg:flex-wrap lg:overflow-visible [&>*]:shrink-0"`
- **Acceptance:** - [ ] all 15 categories visible at 1440 px - [ ] phone row still swipes
- **Effort:** S · **Risk:** low · **Confidence:** high

### UI-009 · P2 · Accessibility · Switched-off voice cards fail contrast (4.05:1 dark, 2.82:1 light)
- [x] **DO**   Note: ____
- **Where:** Voix › cards « Désactivée » · all viewports, both themes (axe `color-contrast`,
  7 nodes)
- **Before:** ![](screenshots/voices__desktop__default.png)
- **Why:** Q1. `opacity-70` on the whole card pushes the chips below WCAG AA.
- **Correction (exact):** a switched-off card keeps full opacity and gets `border-dashed`, and
  its title `h2` gets `text-muted`. The « Désactivée » checkbox stays as is.
- **After:** ![](screenshots/UI-009__after__mobile.png) · ![](screenshots/UI-009__after__desktop.png)
  — axe `color-contrast`: 7 → 0 on both viewports; off cards still read as off.
- **Suggested diff:**
  ```diff
  // web/src/voices/VoicesPage.tsx
  -    <Card as="li" className={`space-y-3 ${v.enabled ? '' : 'opacity-70'}`}>
  +    <Card as="li" className={`space-y-3 ${v.enabled ? '' : 'border-dashed'}`}>
  …
  -          <h2 className="font-semibold">{v.label}</h2>
  +          <h2 className={`font-semibold ${v.enabled ? '' : 'text-muted'}`}>{v.label}</h2>
  ```
- **Acceptance:** - [ ] axe colour-contrast clean on /voices in dark and light
- **Effort:** S · **Risk:** low · **Confidence:** high

### UI-010 · P2 · Hierarchy · Planning shows seven amber « Lancer maintenant » buttons
- [x] **DO**   Note: ____
- **Where:** Planning › every card · desktop and phone
- **Before:** ![](screenshots/planning__desktop__default.png)
- **Why:** Q1. Every card shouts the same action; it is an override (jump the queue), not the
  page's main action, and on the phone a misplaced thumb starts a heavy job.
- **Correction (exact):** the per-card « Lancer maintenant » on run / render / film cards
  (`Planning.tsx` lines ~268 and ~373) uses the **secondary** variant (drop
  `variant="primary"`). « Valider » on idea cards stays primary.
- **After:** ![](screenshots/UI-010__after__mobile.png) · ![](screenshots/UI-010__after__desktop.png)
  (7 buttons, computed `rgb(44, 48, 73)` = surface-2)
- **Acceptance:** - [ ] only « Valider » and « Lancer la sélection » are amber on Planning
- **Effort:** S · **Risk:** low · **Confidence:** high

### UI-011 · P2 · Accessibility · Planning strip and Calendar headings fail axe
- [x] **DO**   Note: ____
- **Where:** Planning › « Les prochaines 24 h » (all viewports); Calendar day headings
- **Before:** axe: `aria-prohibited-attr` (the « Maintenant » line is a `div` with
  `aria-label`), `scrollable-region-focusable` (phone: the strip scrolls but can't be reached by
  keyboard), `heading-order` (Calendar jumps from h1 to h3).
- **Correction (exact):** « Maintenant » line gets `role="img"`; the strip's scroll container
  gets `tabIndex={0}` (keeps the existing focus ring); Calendar day headings and « Did these
  reach Instagram? » become `h2` with the same classes.
- **After:** axe on the patched pages: Planning 2 → 0 (phone), 1 → 0 (desktop); Calendar
  `heading-order` 1 → 0.
- **Likely files:** `web/src/pages/Planning.tsx` (Strip), `web/src/calendar/CalendarPage.tsx`
- **Effort:** S · **Risk:** low · **Confidence:** high

### UI-012 · P2 · Copy · Imported ElevenLabs voice descriptions are cut mid-word
- [x] **DO**   Note: ____
- **Where:** Voix › ElevenLabs cards « L'IA la choisit pour » (« …Key qualities: clear,
  dynami », « …Native French spe »)
- **Before:** ![](screenshots/voices__desktop__default.png)
- **Why:** Q1 and the AI reads this text to pick a voice.
- **Correction (exact):** when a library voice becomes a card, cut the description at the last
  space before 400 characters and end it with « … » (total ≤ 400). Name cut (60) the same way.
  Existing cards are not rewritten.
- **Suggested diff:**
  ```diff
  // web/src/voices/ElevenLibrary.tsx
  +/** At most n characters, cut on a word, with … when cut. */
  +const clip = (s: string, n: number) => {
  +  if (s.length <= n) return s
  +  const cut = s.lastIndexOf(' ', n - 1)
  +  return s.slice(0, cut > n / 2 ? cut : n - 1).trimEnd() + '…'
  +}
  -  const [useFor, setUseFor] = useState(v.description.slice(0, 400))
  +  const [useFor, setUseFor] = useState(clip(v.description, 400))
  …
  -      description: v.description.slice(0, 400), …
  +      description: clip(v.description, 400), …
  ```
  Checked: Hugo's 411-char text → 394 chars ending « Key qualities: clear,… »; short text unchanged.
- **Acceptance:** - [ ] unit test: 411-char input → ≤ 400, ends with « … », no half word
- **Effort:** S · **Risk:** low · **Confidence:** high

### UI-013 · P2 · Copy · The whole app in French, dates in fr-FR (answer to Q1)
- [x] **DO**   Note: ____
- **Where:** every page, nav, toasts, sheets, errors · all viewports
- **Before:** ![](screenshots/inbox__desktop__default.png) (« Inbox, Créer, Planning, Trending,
  Calendar, Analytics, Learnings, Styles, Voix, Ads, Agent, Settings »; « 6 of 7 decided »)
- **Correction (exact):**
  - `web/index.html`: `<html lang="fr">`.
  - Every `toLocaleDateString / toLocaleTimeString / toLocaleString(undefined, …)` and
    `Intl.DateTimeFormat(undefined, …)` uses `'fr-FR'` (e.g. `dayLabel` → « lun. 30 nov. »,
    `slotLabel` → « lun. 30 nov. 18:53 »). The native date field keeps the browser's own
    format (not changeable from the page).
  - Address the owner with « tu », as the French pages already do; French typography rule
    from DECISIONS.md (no-break space before ? ! : ; » and after «).
  - **Glossary (nav label = page title):** Inbox → « Inbox » (kept: the French copy already says
    « elle arrive dans l'Inbox »), Créer, Planning, Trending (kept), Calendar → « Calendrier »,
    Analytics → « Statistiques », Learnings → « Apprentissages », Styles, Voix, Ads → « Pubs »,
    Agent, Settings → « Réglages », More → « Plus ».
  - **Inbox:** Today → « Aujourd'hui », Saved (n) → « Gardées (n) », « 6 of 7 decided » →
    « 6 sur 7 décidées », Approve / Change / Decline / Save for later → « Approuver / Changer /
    Refuser / Garder », toasts « Approuvée », « Refusée », « Gardée pour plus tard »,
    « Renvoyée pour changements », action « Annuler », « Retry » → « Réessayer », keyboard hint
    « Touches : a approuver, d refuser, c changer, s garder, j / k suivante / précédente, espace
    lecture / pause, m son ».
  - Calendar buttons « Semaine précédente / Cette semaine / Semaine suivante »; week range
    (UI-004) in fr-FR.
  - Everything else: translate the English strings of Analytics (+ Posts, What works → « Ce qui
    marche », Daily report → « Rapport du jour », Trends → « Tendances »), Learnings, Ads, Agent,
    Settings, Alerts, TokenBanner, Login, Not found. Technical words stay (Q5): Worker, token,
    `.env`, command names.
- **After:** ![](screenshots/UI-014__after__mobile-360.png) (French tab labels fit at 360 px:
  « Calendrier » 51 px in a 60 px cell)
- **Test:** every `*.test.tsx` and `web/e2e/smoke.spec.ts` updated to the French names (the
  smoke test clicks « Save for later », « Change », « Approve », the « Calendar » link, the
  « What should change? » sheet); no English UI string left: `grep` for the old labels in
  `web/src` returns only comments.
- **Likely files:** all of `web/src` (≈60 files), `web/index.html`, `web/e2e/smoke.spec.ts`
- **Acceptance:** - [ ] no English UI text on any page (Q5 technical words excepted) - [ ] all
  dates fr-FR - [ ] lint, typecheck, vitest, e2e pass - [ ] DECISIONS.md entry « UI language:
  French » in the first step
- **Effort:** L (split in 5 steps below) · **Risk:** medium (test strings) · **Confidence:** high

### UI-014 · P2 · Navigation · Planning gets a tab on the phone, Agent moves to « Plus » (answer to Q2)
- [x] **DO**   Note: ____
- **Where:** phone bottom tab bar
- **Before:** ![](screenshots/more__mobile__default.png) (tabs Inbox · Créer · Trending ·
  Calendar · Agent · More; Planning behind More)
- **Correction (exact):** in `web/src/App.tsx` `NAV`, move `tab: true` from Agent to
  Planning; tabs become, in NAV order, « Inbox · Créer · Planning · Trending · Calendrier ·
  Plus ». Agent appears in the « Plus » list. Update the 174 / 185 comments.
- **After:** ![](screenshots/UI-014__after__mobile-390.png) · ![](screenshots/UI-014__after__mobile-375.png)
  · ![](screenshots/UI-014__after__mobile-360.png) (all labels fit at 390, 375 and 360 px)
- **Acceptance:** - [ ] Planning tab active on `/planning` - [ ] « Plus » active on `/agent`
  - [ ] `App.test.tsx` updated - [ ] DECISIONS.md entry (reverses choices 174 / 185)
- **Effort:** S · **Risk:** low · **Confidence:** high

### UI-015 · P2 · Copy · The AI's jobs in plain words on Planning and Agent (answer to Q3)
- [x] **DO**   Note: ____
- **Where:** Planning card titles (« Run daily-learn »…), Agent buttons (« Run check-renders
  now »…)
- **Before:** ![](screenshots/planning__desktop__default.png) · ![](screenshots/agent__mobile__default.png)
- **Correction (exact):** names — daily-learn « Analyse de la nuit », daily-produce « Vidéos
  du jour », daily-revise « Tes changements », check-renders « Vérifier les rendus »,
  weekly-ads « Pubs de la semaine »; an unknown playbook keeps its file name.
  - Server: `src/studio/planning.py` builds card titles with these names instead of
    `f"Run {name}"` (one `PLAYBOOK_LABELS` dict in that module, used at the 7 `Run …`
    titles). The « Run de l'IA » / « Run léger » chips stay.
  - Web: `PLAYBOOKS` in `web/src/pages/load.ts` holds the same five names; Agent buttons read
    « Lancer : Vidéos du jour »; the confirm reads « Lancer « Vidéos du jour » maintenant ?
    Ça démarre un run Claude Code, qui utilise le quota de ton abonnement. »
- **After:** ![](screenshots/UI-015__after__mobile.png) (« Tes changements » as the card title)
- **Test:** `tests/test_planning.py` lines 92, 106 and `tests/test_planning_extras.py` line 115
  expect the new titles; `Agent.test.tsx` the new button names.
- **Acceptance:** - [ ] no « Run daily-… » left on Planning or Agent - [ ] pytest + vitest pass
- **Effort:** S · **Risk:** low · **Confidence:** high

### UI-016 · P2 · Navigation · A section index at the top of Réglages (answer to Q4)
- [x] **DO**   Note: ____
- **Where:** Settings · phone (6 600 px, 15 sections) and desktop
- **Before:** ![](screenshots/settings__mobile__default.png)
- **Correction (exact):** under the title, a `nav aria-label="Sections"` of links styled as the
  Styles filter chips (`inline-flex min-h-11 shrink-0 items-center rounded-full border
  border-line bg-surface-2 px-4 text-sm font-medium`): phone one swipe row
  (`flex gap-2 overflow-x-auto pb-1`, bleeding to the screen edges), desktop wraps
  (`lg:flex-wrap`). Links in page order: Apparence, Worker, Instagram, Stockage, Sauvegardes,
  Planning de l'IA, Studio, Styles, Pubs, Clips, Autorisations, Reel réaction, DM,
  Téléchargeur, Serveur → `#appearance, #worker, #instagram, #storage, #backups,
  #agent-schedule, #studio, #styles, #ads, #clips, #permissions, #reaction-reel, #dm-picks,
  #reel-downloader, #server`. Each section root gets that `id` and `scroll-mt-16 lg:scroll-mt-4`
  (clears the phone header). On load, if the URL has a hash, scroll to it once the section
  exists (React Router does not). The Ads page link becomes `<Link to="/settings#ads">`.
- **After:** ![](screenshots/UI-016__after__mobile.png) · ![](screenshots/UI-016__after__desktop.png)
  · tapping « Pubs »: ![](screenshots/UI-016__after__mobile-jumped.png) (section top lands
  at 64 px on phone, 16 px on desktop)
- **Acceptance:** - [ ] every chip jumps to its section, title visible below the header
  - [ ] `/settings#ads` from the Ads page lands on Pubs
- **Effort:** S–M · **Risk:** low · **Confidence:** high

### UI-017 · P2 · Logic · The video page offers the Inbox's four decisions (answer to Q6)
- [x] **DO**   Note: ____
- **Where:** Video page `/assets/:id` while the video is `ready`
- **Before:** ![](screenshots/asset__desktop__default.png) (Dislike / Like / Approve / Archive,
  plus an « Ask for changes » checkbox in Comments)
- **Correction (exact):** the action row shows « Approuver » (primary; keeps UI-002), and
  secondary « Changer », « Refuser », « Garder ». On phone (< 640 px) a 2 × 2 grid
  (`grid grid-cols-2 gap-2 sm:flex sm:flex-wrap`).
  - « Changer » opens the same `ReasonSheet` as the Inbox with `at` = the player's current time,
    `onSave` → `addFeedback` (same as Inbox `change`), `onRestyle` → `restyleAsset`.
  - « Refuser » opens the `ReasonSheet` without `at`, `onSave` → `declineAsset` (motive needed,
    as in the Inbox).
  - « Garder » → `setVerdict(id, 'liked')`.
  - Remove Dislike, Like, Archive, and the « Ask for changes » checkbox in the comment form
    (« Changer » replaces it); plain comments stay.
  - Approved / scheduled states keep their buttons, in French: « Programmer », « Retirer
    l'approbation ».
  - The caption button becomes secondary « Enregistrer » (one primary on the page).
- **After:** ![](screenshots/UI-017__after__mobile.png) · ![](screenshots/UI-017__after__desktop.png)
- **Test:** `AssetPage.test.tsx`: Changer → sheet → save → `addFeedback` called with `at`;
  Refuser → sheet → `declineAsset`; Garder → `setVerdict('liked')`.
- **Likely files:** `web/src/inbox/AssetPage.tsx`, `CommentThread.tsx`, their tests
- **Acceptance:** - [ ] same outcomes as the Inbox's four actions - [ ] no verdict buttons left
  that the Inbox doesn't have
- **Effort:** M · **Risk:** medium (removes Archive without a motive) · **Confidence:** high

## Answered questions (2026-11-25)

| # | Question | Owner's answer | Becomes |
|---|---|---|---|
| Q1 | Language | French | UI-013 |
| Q2 | Planning tab on the phone | OK | UI-014 |
| Q3 | Plain job names | Yes | UI-015 |
| Q4 | Settings section index | OK | UI-016 |
| Q5 | Technical wording | It's OK: keep | no change |
| Q6 | Video page uses the Inbox's words | Correct | UI-017 |

The original questions, for the record:

**Q1 · Language.** The app mixes French and English: nav « Inbox, Créer, Planning, Trending,
Calendar, Analytics, Learnings, Styles, Voix, Ads, Agent, Settings »; Inbox, Calendar,
Analytics, Learnings, Ads, Agent and Settings are English, the rest French; dates show
`11/24/2026`. Options: (a) all French with fr-FR dates (« 24/11/2026 »), (b) all English,
(c) keep as is. **Recommend (a)**: the owner and the content are French and the newer pages
already are. Effort M–L (one step per area). Would go in DECISIONS.md.

**Q2 · Phone tab bar.** Planning (task 3) is behind « More » while Agent (manual runs, each
asks for confirmation and uses your plan) has a tab (choices 174/185). Option: swap Agent and
Planning. Recommend swapping; medium confidence because it reverses a past choice.

**Q3 · Job names on Planning and Agent.** « Run daily-learn / daily-produce / daily-revise »,
« Run check-renders now ». Proposed: « Analyse de la nuit », « Vidéos du jour », « Tes
changements », « Vérifier les rendus », « Pubs de la semaine ». Your wording?

**Q4 · Settings length.** 6 600 px on the phone, 14 sections, no index. Option: a row of
section chips under the title that jump to each card (and lets Ads link to `/settings#ads`).
Recommend yes; effort S–M.

**Q5 · Technical wording on owner pages.** Voix: « (TTS_PROVIDER) », « ajoutez
ELEVENLABS_API_KEY dans .env »; Settings: « Run ig-campaign downloader setup »; token banner:
« Paste a new token in .env ». You run the machine yourself, so this may be fine. Options:
keep, or one plain sentence with the command behind a « Détails » toggle.

**Q6 · Video page verdict words.** Inbox: Approve / Change / Decline / Save for later. Video
page: Dislike / Like / Approve / Archive, and « Ask for changes » is a checkbox in Comments.
Unify on the Inbox's four? Recommend yes, but Like ≠ Save may mean something to you.

## Also noticed (OFF)
- `GET /api/reports/latest` answers 404 when there is no report: a console error on every
  Analytics and Report load (the page handles it). Return `200 null` or `204`.
- Créer › La pile: one unbroken 400-character word scrolls the phone page sideways
  (`grid` with an implicit `auto` track); real Reel links wrap fine. `grid-cols-1` fixes it.
- Offline decision error reads « Could not save video 131 (Failed to fetch) »: say « No
  connection » instead of the browser's text.
- Learnings: four rows of filter chips and two « Add a rule » buttons on an empty page.
- Trending: « Actualiser » is a large primary button while no topic exists; two primaries near
  the top.
- Posts: « No posts match. » is plain text where other pages use the dashed empty state.
- Analytics: the 7 d / 30 d / 90 d chips show with no account data.
- Video page: caption « Save » is always enabled (a no-op save is sent).
- « Published with Instagram's AI label » reads as done on unpublished videos: « Will be posted
  with… ».
- Ads: the big red « Stop all ads » shows while every cap is 0 and nothing can spend.
- Styles: « Pixel 8-bit » has no preview image.

## Team-up plan (built from corrections still ticked)
| Step | Corrections | Scope | Done when |
|---|---|---|---|
| 1 | UI-001, UI-002 | Decision safety: feed tap lock, save caption before approve | both tests pass; before/after screenshots re-captured |
| 2 | UI-003, UI-010, UI-011 (Planning part), UI-015 | Planning: launch bar, button hierarchy, strip a11y, job names (server + web) | acceptance + axe clean on /planning; pytest + vitest pass |
| 3 | UI-004, UI-011 (Calendar part) | Calendar week label and headings | acceptance + axe clean on /calendar |
| 4 | UI-005, UI-006, UI-007 | App shell and Inbox resilience: boot spinner, Retry, rail discs | acceptance; slow / 500 / phone screenshots re-captured |
| 5 | UI-008, UI-009, UI-012 | Styles and Voix polish | acceptance + axe clean on /voices (dark and light) |
| 6 | UI-014, UI-016 | Navigation: Planning tab on the phone, Settings section index, Ads → `/settings#ads` | acceptance; DECISIONS.md entry for the tab bar |
| 7 | UI-017 (after step 1) | Video page: the Inbox's four decisions | its tests + acceptance |
| 8 | UI-013 part 1 | French: `lang="fr"`, fr-FR dates, nav, More, Inbox, video page, sheets, toasts, Alerts, TokenBanner, Login, Not found, e2e smoke test | DECISIONS.md entry « UI language: French »; e2e passes |
| 9 | UI-013 part 2 | French: Calendrier, Statistiques (+ posts, ce qui marche, rapport, tendances) | no English left on these pages |
| 10 | UI-013 part 3 | French: Apprentissages, Pubs, Agent | no English left on these pages |
| 11 | UI-013 part 4 | French: Réglages (all sections) | no English left on Réglages |
| 12 | UI-013 part 5 | French: last sweep (Créer, Planning, Trending, Styles, Voix leftovers) + grep for English labels | acceptance of UI-013 |

French goes last because it rewrites strings the earlier steps touch. Steps 1–7 are S or M
(well under 500 changed lines); each French step stays under ~1 300 lines. Developer prompts include the correction block,
its screenshots, test and acceptance, and: "re-capture the same screenshots after your change
and attach before/after to the PR".

## Coverage
- **Pages:** all 19 routes captured at desktop, tablet and phone (57 screenshots, dark), 6
  pages in light theme on phone + axe on desktop and phone. See `feature-map.md` for the
  inventory.
- **Battery on primary flows:** Inbox: happy path, double-click (desktop) and double-tap (phone),
  API 500, API slowed 3 s, offline decision, keyboard Tab order (focus ring visible on all
  stops), light theme. Créer: empty (Envoyer disabled), 2 000 chars (blocked with « Trop long :
  n/500 »), 400 chars + `<script>` + emoji (shown as text), double-click submit (1 POST).
  Calendar: week navigation. Video page: caption + approve.
- **Not tested, and why:** publishing, renders, agent runs, « Lancer maintenant », « Tout
  lancer », Trending « Actualiser », Ads kill switch (each would start real work or call Meta /
  Claude / the GPU); login form (no `UI_PASSWORD` in the audit run); two tabs editing one video;
  session expiry; volume beyond the seed (≈140 videos, empty calendar, no posts or learnings);
  text expansion for i18n (no i18n layer).
- **Console / network:** no JS errors on any page. `404 /api/reports/latest` on Analytics and
  Report (see Also noticed). Voix: the browser fetches ElevenLabs preview audio from their CDN
  (expected, audio `preload`).
- **axe (serious):** Planning `aria-prohibited-attr` + `scrollable-region-focusable` (UI-011),
  Voix `color-contrast` (UI-009); moderate: Calendar `heading-order` (UI-011). No horizontal
  overflow on any phone page with realistic data.
- **Cold read:** a second reviewer scored the screenshots without code. Agreed and kept: Planning
  hierarchy (UI-010), truncated voice text (UI-012), language (Q1 → UI-013), tab bar (Q2 →
  UI-014), job names (Q3 → UI-015), Settings length (Q4 → UI-016), technical wording (Q5, kept),
  verdict words (Q6 → UI-017). Checked and dropped: « rail
  buttons cut off on phone » (measured inside the screen: 326–382 px of 390, the invisible disc
  is UI-007); « Worker not running / token invalid not surfaced » and « Calendar contradicts
  Planning » (both come from the audit's fake setup: no worker, unreachable Graph, seeded
  approvals without slots).
