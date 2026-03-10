// src/api/apiClient.ts

// In dev, use "" so requests hit same origin → Vite proxies to backend. Avoids
// CORS and mixed-content (HTTPS page blocking http://localhost) when preview uses HTTPS.
// Production builds use VITE_API_BASE_URL or fallback.
export const API_BASE_URL =
  import.meta.env.DEV
    ? ""
    : (import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000")

type HttpMethod = "GET" | "POST" | "PUT" | "PATCH" | "DELETE"

export class ApiError extends Error {
  status: number
  body?: unknown
  constructor(message: string, status: number, body?: unknown) {
    super(message)
    this.status = status
    this.body = body
  }
}

async function parseJsonSafe(res: Response): Promise<unknown | undefined> {
  const text = await res.text()
  if (!text) return undefined
  try {
    return JSON.parse(text)
  } catch {
    return text
  }
}

/**
 * Fetch with a timeout. Aborts the request after timeoutMs so the UI doesn't hang.
 * Uses AbortController so the request is cancelled and doesn't hang.
 * Composes with caller's signal if provided — either can abort the request.
 */
export function fetchWithTimeout(
  url: string,
  init: RequestInit & { timeoutMs?: number }
): Promise<Response> {
  const { timeoutMs, signal: callerSignal, ...fetchInit } = init
  if (timeoutMs == null || timeoutMs <= 0) {
    return fetch(url, fetchInit)
  }
  const controller = new AbortController()
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs)
  // If caller passed a signal, abort our controller when they abort
  if (callerSignal) {
    callerSignal.addEventListener('abort', () => controller.abort())
  }
  return fetch(url, { ...fetchInit, signal: controller.signal }).finally(() =>
    clearTimeout(timeoutId)
  )
}

export async function apiRequest<T>(
  path: string,
  options: {
    method?: HttpMethod
    headers?: Record<string, string>
    body?: unknown
    signal?: AbortSignal
    /** Abort request after this many ms so the UI doesn't hang (e.g. 15000). */
    timeoutMs?: number
  } = {}
): Promise<T> {
  const { method = "GET", headers = {}, body, signal, timeoutMs } = options

  const res = await fetchWithTimeout(`${API_BASE_URL}${path}`, {
    method,
    headers: {
      ...(body ? { "Content-Type": "application/json" } : {}),
      ...headers,
    },
    body: body ? JSON.stringify(body) : undefined,
    signal,
    timeoutMs,
  })

  if (!res.ok) {
    const errBody = await parseJsonSafe(res)
    throw new ApiError(
      `API request failed: ${method} ${path} (${res.status})`,
      res.status,
      errBody
    )
  }

  // Handle 204 No Content
  if (res.status === 204) return undefined as T

  // Try JSON, fall back safely
  const data = (await parseJsonSafe(res)) as T
  return data
}
