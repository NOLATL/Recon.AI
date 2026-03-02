import { useRef, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { uploadFiles } from '@/api/endpoints'
import type { UploadSuccessResponse } from '@/schemas'
import ErrorDisplay from '@/components/ErrorDisplay'

interface Props {
  sessionId: string
  onSuccess: () => void
}

function FilePicker({
  label,
  file,
  onChange,
}: {
  label: string
  file: File | null
  onChange: (f: File | null) => void
}) {
  const ref = useRef<HTMLInputElement>(null)
  return (
    <div className="border border-dashed border-gray-300 rounded-md p-4 hover:border-blue-400 transition-colors">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm font-medium text-gray-700">{label}</p>
          {file ? (
            <p className="text-xs text-green-600 mt-0.5">
              {file.name} ({(file.size / 1024).toFixed(1)} KB)
            </p>
          ) : (
            <p className="text-xs text-gray-400 mt-0.5">No file selected</p>
          )}
        </div>
        <button
          type="button"
          onClick={() => ref.current?.click()}
          className="text-xs bg-gray-100 hover:bg-gray-200 px-3 py-1.5 rounded-md transition-colors"
        >
          Choose CSV
        </button>
      </div>
      <input
        ref={ref}
        type="file"
        accept=".csv"
        className="hidden"
        onChange={(e) => onChange(e.target.files?.[0] ?? null)}
      />
    </div>
  )
}

function UploadResult({ data }: { data: UploadSuccessResponse }) {
  return (
    <div className="mt-6 space-y-4">
      <div className="bg-green-50 border border-green-200 rounded-md p-4">
        <p className="text-sm font-medium text-green-800 mb-2">Upload successful</p>
        <div className="grid grid-cols-3 gap-3">
          {Object.entries(data.row_counts).map(([key, count]) => (
            <div key={key} className="bg-white rounded border border-green-100 p-3 text-center">
              <p className="text-xs text-gray-500">{key}</p>
              <p className="text-xl font-bold text-gray-900 mt-0.5">{count}</p>
              <p className="text-xs text-gray-400">rows</p>
            </div>
          ))}
        </div>
      </div>

      <div>
        <h4 className="text-sm font-medium text-gray-700 mb-2">Validation Summary</h4>
        <div className="space-y-2">
          {Object.entries(data.validation).map(([key, v]) => (
            <div
              key={key}
              className={[
                'rounded-md p-3 text-sm border',
                v.is_valid
                  ? 'bg-green-50 border-green-200'
                  : 'bg-red-50 border-red-200',
              ].join(' ')}
            >
              <div className="flex items-center justify-between">
                <span className="font-medium">
                  {v.is_valid ? '✓' : '✗'} {key}
                </span>
                <span className="text-xs text-gray-500">{v.row_count} rows</span>
              </div>
              <p className="text-xs text-gray-500 mt-1">
                Columns: {v.columns_validated.join(', ')}
              </p>
              <p className="font-mono text-xs text-gray-400 mt-0.5">
                Schema hash: {v.schema_hash}
              </p>
            </div>
          ))}
        </div>
      </div>

      <div className="bg-blue-50 border border-blue-200 rounded-md p-3 text-sm text-blue-800">
        State advanced to <strong>{data.state}</strong>. Click "Continue" in the status bar above to
        refresh, or proceed to the Profile step.
      </div>
    </div>
  )
}

export default function UploadStep({ sessionId, onSuccess }: Props) {
  const [coa, setCoa] = useState<File | null>(null)
  const [gl, setGl] = useState<File | null>(null)
  const [sub, setSub] = useState<File | null>(null)

  const mutation = useMutation({
    mutationFn: () => uploadFiles(sessionId, coa!, gl!, sub!),
    onSuccess: (data) => {
      try {
        sessionStorage.setItem(`upload_result_${sessionId}`, JSON.stringify(data))
      } catch {
        // Small payload — skip caching if quota full, step will still advance
      }
      onSuccess()
    },
  })

  const canSubmit = !!coa && !!gl && !!sub && !mutation.isPending

  return (
    <div className="bg-white border border-gray-200 rounded-lg p-6">
      <h2 className="text-base font-semibold text-gray-900 mb-1">Upload Files</h2>
      <p className="text-sm text-gray-500 mb-5">
        Upload Chart of Accounts, General Ledger, and Subledger CSV files to begin.
      </p>

      <div className="space-y-3">
        <FilePicker label="Chart of Accounts (CSV)" file={coa} onChange={setCoa} />
        <FilePicker label="General Ledger — GL (CSV)" file={gl} onChange={setGl} />
        <FilePicker label="Subledger (CSV)" file={sub} onChange={setSub} />
      </div>

      {mutation.error && (
        <div className="mt-4">
          <ErrorDisplay error={mutation.error} onRefresh={onSuccess} />
        </div>
      )}

      <button
        onClick={() => mutation.mutate()}
        disabled={!canSubmit}
        className="mt-5 bg-blue-600 hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm font-medium px-5 py-2 rounded-md transition-colors"
      >
        {mutation.isPending ? 'Uploading…' : 'Upload Files'}
      </button>

      {mutation.data && <UploadResult data={mutation.data} />}
    </div>
  )
}
