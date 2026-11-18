import { execFile, spawn, type ChildProcess } from 'node:child_process'
import { existsSync, mkdtempSync, rmSync } from 'node:fs'
import { createServer, type Server } from 'node:http'
import type { AddressInfo } from 'node:net'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { promisify } from 'node:util'
import { expect, test, type Locator } from '@playwright/test'

// The owner's main path, end to end (step 099): seed → Inbox feed (save for later, change,
// approve) → the slot in the Calendar → the publish run against a local Graph API stub →
// published. No request leaves this machine: the studio's Graph base URL is the stub, and the
// access token is a fake one.

const WEB = resolve(import.meta.dirname, '..')
const ROOT = resolve(WEB, '..')
const PYTHON = process.env.PYTHON ?? [join(ROOT, '.venv/Scripts/python.exe'), join(ROOT, '.venv/bin/python')]
  .find((p) => existsSync(p)) ?? 'python'
const TOKEN = 'e2e-fake-token'
const ACCOUNT = '17841400000000001'
const run = promisify(execFile)

test.describe.configure({ mode: 'serial' })

const seen: { call: string; auth?: string }[] = [] // every request the stub got
let stub: Server
let studio: ChildProcess
let tmp: string
let base: string
let env: NodeJS.ProcessEnv

// Just the calls the Reel publish path makes: container create, upload, status, publish, lookup.
const ROUTES: [RegExp, object][] = [
  [new RegExp(`^POST /v[\\d.]+/${ACCOUNT}/media$`), { id: 'C1' }],
  [/^POST \/ig-api-upload\/v[\d.]+\/C1$/, { success: true }],
  [/^GET \/v[\d.]+\/C1$/, { id: 'C1', status_code: 'FINISHED' }],
  [new RegExp(`^POST /v[\\d.]+/${ACCOUNT}/media_publish$`), { id: 'M1' }],
  [/^GET \/v[\d.]+\/M1$/, { id: 'M1', permalink: 'https://www.instagram.com/reel/e2e/', media_product_type: 'REELS' }],
]
const called = (re: RegExp) => seen.some((s) => re.test(s.call))

const listen = (server: Server) =>
  new Promise<number>((ok) => server.listen(0, '127.0.0.1', () => ok((server.address() as AddressInfo).port)))

test.beforeAll(async () => {
  stub = createServer((req, res) => {
    const call = `${req.method} ${new URL(req.url ?? '/', 'http://stub').pathname}`
    seen.push({ call, auth: req.headers.authorization })
    req.resume() // drain the upload
    req.on('end', () => {
      const hit = ROUTES.find(([re]) => re.test(call))
      res.writeHead(hit ? 200 : 400, { 'content-type': 'application/json' })
      res.end(JSON.stringify(hit ? hit[1] : { error: { message: `not stubbed: ${call}`, code: 100 } }))
    })
  })
  const stubPort = await listen(stub)

  tmp = mkdtempSync(join(tmpdir(), 'studio-e2e-'))
  env = {
    ...process.env,
    IG_MCP_ENV_FILE: join(tmp, 'none.env'), // never the developer's own .env
    DATABASE_PATH: join(tmp, 'studio.db'),
    MEDIA_ROOT: join(tmp, 'media'),
    WEB_DIST: join(WEB, 'dist'),
    TIMEZONE: 'UTC',
    INSTAGRAM_ACCESS_TOKEN: TOKEN,
    INSTAGRAM_BUSINESS_ACCOUNT_ID: ACCOUNT,
    INSTAGRAM_API_BASE_URL: `http://127.0.0.1:${stubPort}`,
    CONTAINER_POLL_INTERVAL_SECONDS: '0',
  }
  delete env.UI_PASSWORD
  // --seed 3: today's batch has two undecided videos and one saved for later.
  // --force: the configured database with Instagram "configured" (the stub) is refused otherwise.
  await run(PYTHON, ['-m', 'src.scheduler', 'dev', 'seed', '--days', '1', '--seed', '3', '--force'], { cwd: ROOT, env })

  // A free port: the OS picks one, the studio takes it a moment later.
  const probe = createServer()
  const port = await listen(probe)
  await new Promise((ok) => probe.close(ok))
  base = `http://127.0.0.1:${port}`
  studio = spawn(PYTHON, ['-m', 'src.scheduler', 'serve', '--port', String(port)], { cwd: ROOT, env, stdio: 'inherit' })
  await expect.poll(() => fetch(`${base}/api/health`).then((r) => r.ok, () => false), { timeout: 30_000 }).toBe(true)
})

test.afterAll(async () => {
  if (studio && studio.exitCode === null) {
    const exited = new Promise((ok) => studio.once('exit', ok))
    studio.kill()
    await exited // the database file is free before the temp folder goes
  }
  stub?.close()
  if (tmp) rmSync(tmp, { recursive: true, force: true, maxRetries: 5 })
})

test('decide in the feed, see the slot, publish against the stub', async ({ page }) => {
  const idOf = async (card: Locator) =>
    Number((await card.getAttribute('aria-label'))?.replace('Video ', ''))

  await page.goto(`${base}/inbox`)
  const cards = page.getByLabel('Review feed').getByRole('article')
  await expect(cards).toHaveCount(2)

  // 1. Save for later: the video leaves Today for the Saved tab.
  const saved = await idOf(cards.first())
  await cards.first().getByRole('button', { name: 'Save for later' }).click()
  await expect(page.getByRole('article', { name: `Video ${saved}` })).toHaveCount(0)

  // 2. Change, with a reason.
  const changed = await idOf(cards.first())
  await cards.first().getByRole('button', { name: 'Change', exact: true }).click()
  const sheet = page.getByRole('dialog', { name: 'What should change?' })
  await sheet.getByRole('textbox', { name: 'What to change' }).fill('[e2e] a shorter hook')
  await sheet.getByRole('button', { name: 'Send for changes' }).click()
  await expect(page.getByText('All done')).toBeVisible()

  // 3. Approve the saved video from the Saved tab (switching tabs commits the two decisions).
  await page.getByRole('tab', { name: /^Saved/ }).click()
  const queued = page.waitForResponse((r) => r.url().endsWith(`/api/assets/${saved}/approve-and-queue`))
  await page.getByRole('article', { name: `Video ${saved}` }).getByRole('button', { name: 'Approve' }).click()
  // The feed commits after its 5 s undo window, or at once when the page is hidden: hide it.
  await page.evaluate("window.dispatchEvent(new Event('pagehide'))")
  const response = await queued
  expect(response.ok()).toBe(true)
  const { post } = await response.json()
  const asset = (id: number) => page.request.get(`${base}/api/assets/${id}`).then((r) => r.json())
  expect((await asset(changed)).status).toBe('revision_requested')

  // Make the slot due in a few seconds (the planner's slot may be days away).
  const due = new Date(Date.now() + 3000).toISOString()
  expect((await page.request.post(`${base}/api/posts/${post.id}/reschedule`, { data: { publish_at: due } })).ok()).toBe(true)

  // 4. The slot is in the Calendar.
  await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Calendar' }).click()
  const slot = page.getByRole('listitem', { name: `Post ${post.id}` })
  await expect(slot).toContainText('pending')
  await expect(slot.getByRole('link', { name: `Video ${saved}`, exact: true })).toBeVisible()

  // 5. The wake task's publish run: waits for the slot, then publishes through the stub.
  const { stdout } = await run(PYTHON, ['-m', 'src.scheduler', 'run-due', '--wait-until-next'],
    { cwd: ROOT, env, timeout: 60_000 })
  expect(JSON.parse(stdout).published).toHaveLength(1)
  for (const [re] of ROUTES) expect(called(re), `the stub saw ${re}`).toBe(true)
  expect(seen.every((s) => s.auth?.endsWith(TOKEN)), 'only the fake token was sent').toBe(true)

  // 6. Published.
  await page.reload()
  await expect(slot).toContainText('published')
  expect((await asset(saved)).status).toBe('published')
})
