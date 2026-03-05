import { useCallback, useState } from 'react'
import { Upload, FileSpreadsheet } from 'lucide-react'
import { cn } from '@/lib/utils'

const ACCEPT = '.csv,.xlsx,.xls'
const ACCEPT_TYPES = ['text/csv', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'application/vnd.ms-excel']

export type UploadStatus = 'idle' | 'uploading' | 'done' | 'error'

interface FileDropzoneProps {
  label: string
  accept?: string
  value: File | null
  onChange: (file: File | null) => void
  status?: UploadStatus
  errorMessage?: string
  className?: string
}

export function FileDropzone({
  label,
  accept = ACCEPT,
  value,
  onChange,
  status = 'idle',
  errorMessage,
  className,
}: FileDropzoneProps) {
  const [dragOver, setDragOver] = useState(false)

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault()
      setDragOver(false)
      const file = e.dataTransfer.files[0]
      if (file && isAccepted(file)) onChange(file)
    },
    [onChange]
  )

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setDragOver(true)
  }, [])

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setDragOver(false)
  }, [])

  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0]
      if (file) onChange(file)
      e.target.value = ''
    },
    [onChange]
  )

  const hasFile = value != null

  return (
    <div className={cn('flex flex-col gap-2', className)}>
      <span className="text-sm font-medium text-foreground">{label}</span>
      <label
        onDrop={handleDrop}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        className={cn(
          'flex min-h-[140px] cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed p-4 transition-colors',
          dragOver && 'border-primary bg-primary/5',
          !dragOver && 'border-muted-foreground/25 hover:border-muted-foreground/50 hover:bg-muted/30',
          status === 'error' && 'border-destructive/50 bg-destructive/5'
        )}
      >
        <input
          type="file"
          accept={accept}
          onChange={handleChange}
          className="sr-only"
          aria-label={`Choose ${label} file`}
        />
        {hasFile ? (
          <>
            <FileSpreadsheet className="size-8 text-muted-foreground" aria-hidden />
            <span className="text-center text-sm font-medium text-foreground truncate max-w-full">
              {value.name}
            </span>
            <span className="text-xs text-muted-foreground">CSV or Excel</span>
          </>
        ) : (
          <>
            <Upload className="size-8 text-muted-foreground" aria-hidden />
            <span className="text-center text-sm text-muted-foreground">
              Drag and drop or click to browse
            </span>
            <span className="text-xs text-muted-foreground">CSV or Excel</span>
          </>
        )}
      </label>
      <div className="flex items-center gap-2">
        {status === 'uploading' && (
          <span className="text-xs text-muted-foreground">Uploading…</span>
        )}
        {status === 'done' && hasFile && (
          <span className="text-xs text-green-600 dark:text-green-500">Uploaded</span>
        )}
        {status === 'error' && (
          <span className="text-xs text-destructive">{errorMessage ?? 'Upload failed'}</span>
        )}
      </div>
    </div>
  )
}

function isAccepted(file: File): boolean {
  if (ACCEPT_TYPES.some((t) => file.type === t)) return true
  const name = file.name.toLowerCase()
  return name.endsWith('.csv') || name.endsWith('.xlsx') || name.endsWith('.xls')
}
