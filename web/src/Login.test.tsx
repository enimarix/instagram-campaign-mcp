import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { getAccount } from './api/client'
import Login from './Login'

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status })

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('Login', () => {
  it('lets the studio through when no password is set', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => json(200, { authenticated: false, password_required: false })))
    render(<Login><p>studio</p></Login>)
    expect(await screen.findByText('studio')).toBeTruthy()
  })

  it('asks the password, says when it is wrong, then lets the studio through', async () => {
    const fetch = vi.fn()
      .mockResolvedValueOnce(json(200, { authenticated: false, password_required: true }))
      .mockResolvedValueOnce(json(401, { error: 'bad_password' }))
      .mockResolvedValueOnce(json(200, { authenticated: true }))
    vi.stubGlobal('fetch', fetch)
    render(<Login><p>studio</p></Login>)
    fireEvent.change(await screen.findByLabelText('Password'), { target: { value: 'pw' } })
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect((await screen.findByRole('alert')).textContent).toBe('Wrong password.')
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByText('studio')).toBeTruthy()
    expect(fetch).toHaveBeenLastCalledWith('/api/login', expect.objectContaining({ method: 'POST', body: '{"password":"pw"}' }))
  })

  it('shows the form again when any API call answers 401, then the studio without a reload', async () => {
    const fetch = vi.fn()
      .mockResolvedValueOnce(json(200, { authenticated: true, password_required: true }))
      .mockResolvedValueOnce(json(401, { error: 'login_required' }))
      .mockResolvedValueOnce(json(200, { authenticated: true }))
    vi.stubGlobal('fetch', fetch)
    render(<Login><p>studio</p></Login>)
    expect(await screen.findByText('studio')).toBeTruthy()
    await expect(getAccount()).rejects.toThrow('401')
    fireEvent.change(await screen.findByLabelText('Password'), { target: { value: 'pw' } })
    expect(screen.queryByText('studio')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByText('studio')).toBeTruthy()
  })
})
