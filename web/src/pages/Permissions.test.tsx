import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { PermissionRequest } from '../api/client'
import { ToastProvider } from '../ui/Toast'
import PermissionsSection, { AskPermissionButton } from './Permissions'

const REQ: PermissionRequest = {
  id: 3, source_id: 7, creator: 'ann', channel: 'dm', status: 'requested',
  requested_at: '2026-11-18T08:00:00+00:00', answered_at: null, proof_note: null, ads_allowed: false,
  url: 'https://www.instagram.com/reel/AbC/', rights_basis: 'commentary', has_file: false,
}

function stubApi(lists: PermissionRequest[][], draftCreator: string | null = 'ann') {
  const calls: { key: string; body?: unknown }[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    const key = `${init?.method ?? 'GET'} ${url}`
    calls.push({ key, body: init?.body ? JSON.parse(init.body as string) : undefined })
    const body = key === 'GET /api/permissions' ? (lists.length > 1 ? lists.shift() : lists[0])
      : key.startsWith('GET /api/permissions/draft')
        ? { creator: draftCreator, url: REQ.url, message: `Hi @${draftCreator ?? 'there'}, may we repost?` }
        : { request: REQ, draft: {} }
    return new Response(JSON.stringify(body), { status: 200 })
  }))
  return calls
}

class FakeXHR {
  static last: FakeXHR
  upload = { onprogress: null }
  status = 0
  responseText = ''
  onload: (() => void) | null = null
  url = ''
  body: unknown
  open(_method: string, url: string) { this.url = url }
  setRequestHeader() {}
  send(body: unknown) {
    this.body = body
    FakeXHR.last = this
  }
}

beforeEach(() => {
  HTMLDialogElement.prototype.showModal = function () { this.open = true }
  HTMLDialogElement.prototype.close = function () { this.open = false; this.dispatchEvent(new Event('close')) }
})
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('AskPermissionButton', () => {
  it('shows the editable draft, copies it and saves the request', async () => {
    const calls = stubApi([[]])
    const writeText = vi.fn(async () => {})
    vi.stubGlobal('navigator', { clipboard: { writeText } })
    render(<ToastProvider><AskPermissionButton target={{ source_id: 7 }} /></ToastProvider>)
    fireEvent.click(screen.getByRole('button', { name: 'Ask for permission' }))
    const box = await screen.findByRole('textbox', { name: 'Message' })
    expect((box as HTMLTextAreaElement).value).toBe('Hi @ann, may we repost?')
    expect(calls[0].key).toBe('GET /api/permissions/draft?source_id=7')
    expect(screen.queryByRole('textbox', { name: 'Creator' })).toBeNull() // known already
    fireEvent.change(box, { target: { value: 'Hi Ann!' } })
    fireEvent.click(screen.getByRole('button', { name: 'Copy message' }))
    await vi.waitFor(() => expect(writeText).toHaveBeenCalledWith('Hi Ann!'))
    fireEvent.change(screen.getByRole('combobox', { name: 'Sent by' }), { target: { value: 'email' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save request' }))
    await vi.waitFor(() => expect(calls.at(-1)).toEqual({
      key: 'POST /api/permissions', body: { source_id: 7, channel: 'email' } }))
    expect(await screen.findByText(/^Saved\./)).toBeTruthy()
    // the studio never sends: no other request than the draft and the save
    expect(calls.map((c) => c.key)).toEqual(['GET /api/permissions/draft?source_id=7', 'POST /api/permissions'])
  })

  it('asks for the creator of an inspiration link and redrafts with it', async () => {
    const calls = stubApi([[]], null)
    render(<ToastProvider><AskPermissionButton target={{ url: REQ.url! }} /></ToastProvider>)
    fireEvent.click(screen.getByRole('button', { name: 'Ask for permission' }))
    const name = await screen.findByRole('textbox', { name: 'Creator' })
    fireEvent.change(name, { target: { value: 'bob' } })
    fireEvent.blur(name)
    await vi.waitFor(() => expect(calls.at(-1)?.key).toBe(
      `GET /api/permissions/draft?${new URLSearchParams({ url: REQ.url!, creator: 'bob' })}`))
  })
})

describe('PermissionsSection', () => {
  it('records a no', async () => {
    const calls = stubApi([[REQ, { ...REQ, id: 4, creator: 'cy' }], [{ ...REQ, status: 'granted', proof_note: 'DM', ads_allowed: true }]])
    render(<PermissionsSection />)
    const rows = await screen.findAllByRole('listitem')
    fireEvent.click(within(rows[1]).getByRole('button', { name: 'They said no' }))
    await vi.waitFor(() => expect(calls.some((c) => c.key === 'POST /api/permissions/4/answer')).toBe(true))
    expect(calls.find((c) => c.key === 'POST /api/permissions/4/answer')?.body).toEqual({ status: 'denied' })
  })

  it('records a yes', async () => {
    const calls = stubApi([[REQ], [{ ...REQ, status: 'granted', proof_note: 'DM', ads_allowed: true }]])
    render(<PermissionsSection />)
    fireEvent.click(await screen.findByRole('button', { name: 'They said yes' }))
    const form = screen.getByRole('form', { name: 'Yes from @ann' })
    fireEvent.change(within(form).getByRole('textbox', { name: 'Proof' }), { target: { value: ' DM 18 Nov ' } })
    fireEvent.click(within(form).getByRole('checkbox'))
    fireEvent.click(within(form).getByRole('button', { name: 'Save answer' }))
    await vi.waitFor(() => expect(calls.find((c) => c.key === 'POST /api/permissions/3/answer')?.body).toEqual(
      { status: 'granted', proof_note: 'DM 18 Nov', ads_allowed: true }))
    expect(await screen.findByText('ads allowed')).toBeTruthy()
  })

  it('attaches the file once granted, then shows it attached', async () => {
    const granted = { ...REQ, status: 'granted' as const, proof_note: 'DM' }
    stubApi([[granted], [{ ...granted, rights_basis: 'permission', has_file: true }]])
    vi.stubGlobal('XMLHttpRequest', FakeXHR)
    render(<PermissionsSection />)
    expect(await screen.findByText('Attach file')).toBeTruthy()
    fireEvent.change(screen.getByRole('combobox', { name: 'Is the sound covered?' }), { target: { value: 'covered' } })
    const file = new File(['video'], 'from ann.mp4', { type: 'video/mp4' })
    fireEvent.change(screen.getByLabelText('Attach file'), { target: { files: [file] } })
    expect(FakeXHR.last.url).toBe('/api/permissions/3/attach?name=from+ann.mp4&audio_rights=covered')
    expect(FakeXHR.last.body).toBe(file)
    FakeXHR.last.status = 200
    FakeXHR.last.responseText = '{}'
    FakeXHR.last.onload?.()
    expect(await screen.findByText('File attached: clip #7 can be used with credit.')).toBeTruthy()
  })

  it('a denied request says commentary only, with no answer buttons', async () => {
    stubApi([[{ ...REQ, status: 'denied' }]])
    render(<PermissionsSection />)
    expect(await screen.findByText('The clip stays usable as commentary only.')).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'They said yes' })).toBeNull()
  })
})
