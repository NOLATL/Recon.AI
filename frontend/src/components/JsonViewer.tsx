interface Props {
  data: unknown
  maxHeight?: string
}

export default function JsonViewer({ data, maxHeight = '400px' }: Props) {
  return (
    <pre
      className="bg-gray-900 text-green-400 text-xs p-4 rounded-md overflow-auto font-mono"
      style={{ maxHeight }}
    >
      {JSON.stringify(data, null, 2)}
    </pre>
  )
}
