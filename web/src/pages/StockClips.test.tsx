import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import StockClips from './StockClips'

const RESULT = {
  id: 42, url: 'https://www.pexels.com/video/gym-42/', author: 'Ann Lee', duration_s: 12,
  width: 1080, height: 1920, image: 'https://images.pexels.com/videos/42/p.jpg',
}

function stubApi(configured: boolean) {
  const calls: string[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    const key = `${init?.method ?? 'GET'} ${url}`
    calls.push(init?.body ? `${key} ${init.body as string}` : key)
    const routes: Record<string, [number, unknown]> = {
      'GET /api/stock': [200, { configured, provider: 'pexels' }],
      'GET /api/stock/search?q=gym+day': [200, [RESULT]],
      'POST /api/stock/add': [200, { id: 9 }],
    }
    const [status, body] = routes[key] ?? [404, { error: 'not_found' }]
    return new Response(JSON.stringify(body), { status })
  }))
  return calls
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('StockClips', () => {
  it('is hidden when no Pexels key is configured', async () => {
    const calls = stubApi(false)
    const { container } = render(<StockClips onAdded={() => {}} />)
    await vi.waitFor(() => expect(calls).toContain('GET /api/stock'))
    expect(container.innerHTML).toBe('')
  })

  it('searches, shows previews and adds a clip', async () => {
    const calls = stubApi(true)
    const onAdded = vi.fn()
    render(<StockClips onAdded={onAdded} />)
    fireEvent.change(await screen.findByRole('searchbox', { name: 'Chercher des clips de banque' }),
      { target: { value: 'gym day' } })
    fireEvent.click(screen.getByRole('button', { name: 'Chercher' }))
    const img = await screen.findByRole('img', { name: 'Vidéo Pexels 42' })
    expect(img.getAttribute('src')).toBe(RESULT.image)
    expect(screen.getByText('Ann Lee · 12 s')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Ajouter la vidéo Pexels 42' }))
    expect(await screen.findByText('Ajoutée')).toBeTruthy()
    expect(calls).toContain('POST /api/stock/add {"result_id":42}')
    expect(onAdded).toHaveBeenCalledOnce()
  })
})
