const BASE_URL = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? 'http://localhost:8000'

// ── Error types ────────────────────────────────────────────────────────────────

export interface ValidationErrorItem {
  loc: (string | number)[]
  msg: string
  type: string
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public rawBody?: unknown,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

export class ConflictError extends ApiError {
  constructor(message: string) {
    super(409, message)
    this.name = 'ConflictError'
  }
}

export class ValidationApiError extends ApiError {
  constructor(public errors: ValidationErrorItem[]) {
    super(422, 'Validation failed')
    this.name = 'ValidationApiError'
  }
}

// ── Response handler ───────────────────────────────────────────────────────────

async function handleResponse<T>(res: Response): Promise<T> {
  if (res.ok) {
    // 204 No Content or similar
    const text = await res.text()
    if (!text) return undefined as unknown as T
    return JSON.parse(text) as T
  }

  let body: Record<string, unknown> = {}
  try {
    body = (await res.json()) as Record<string, unknown>
  } catch {
    // ignore parse error
  }

  if (res.status === 409) {
    const msg =
      typeof body.detail === 'string'
        ? body.detail
        : 'Conflict: operation not allowed in current state.'
    throw new ConflictError(msg)
  }

  if (res.status === 422) {
    const detail = body.detail
    const errors: ValidationErrorItem[] = Array.isArray(detail)
      ? (detail as ValidationErrorItem[])
      : [{ loc: [], msg: String(detail ?? 'Validation error'), type: 'unknown' }]
    throw new ValidationApiError(errors)
  }

  const msg =
    typeof body.detail === 'string' ? body.detail : `HTTP ${res.status}`
  throw new ApiError(res.status, msg, body)
}

// ── Client ────────────────────────────────────────────────────────────────────

export const apiClient = {
  get: async <T>(path: string): Promise<T> => {
    const res = await fetch(`${BASE_URL}${path}`, {
      headers: { Accept: 'application/json' },
    })
    return handleResponse<T>(res)
  },

  post: async <T>(path: string, body?: unknown): Promise<T> => {
    const res = await fetch(`${BASE_URL}${path}`, {
      method: 'POST',
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json',
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    })
    return handleResponse<T>(res)
  },

  postForm: async <T>(path: string, formData: FormData): Promise<T> => {
    const res = await fetch(`${BASE_URL}${path}`, {
      method: 'POST',
      headers: { Accept: 'application/json' },
      body: formData,
    })
    return handleResponse<T>(res)
  },
}
