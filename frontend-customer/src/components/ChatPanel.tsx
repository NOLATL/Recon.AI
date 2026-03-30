import { useState, useRef, useEffect, useCallback } from 'react'
import { MessageCircle, X, Send, Loader2, CheckCircle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  chatMessage,
  type ChatMessage,
  type MatchingConfigUpdate,
  type DeterministicScenarioConfig,
  type ProbabilisticConfig,
} from '@/api/endpoints'

interface Props {
  sessionId: string
  matchingContext?: { deterministic: DeterministicScenarioConfig[]; probabilistic: ProbabilisticConfig } | null
  onConfigUpdate?: (update: MatchingConfigUpdate) => void
}

interface DisplayMessage {
  role: 'user' | 'assistant'
  content: string
  pendingUpdate?: MatchingConfigUpdate
  updateApplied?: boolean
}

export function ChatPanel({ sessionId, matchingContext, onConfigUpdate }: Props) {
  const [open, setOpen] = useState(false)
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [messages, setMessages] = useState<DisplayMessage[]>([
    {
      role: 'assistant',
      content: 'How can I help you better understand your data?',
    },
  ])
  const bottomRef = useRef<HTMLDivElement>(null)
  const inputRef  = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (open) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
      inputRef.current?.focus()
    }
  }, [open, messages])

  const historyForApi = useCallback((): ChatMessage[] => {
    return messages
      .filter((m) => m.role === 'user' || m.role === 'assistant')
      .map((m) => ({ role: m.role as 'user' | 'assistant', content: m.content }))
  }, [messages])

  const handleSend = useCallback(async () => {
    const text = input.trim()
    if (!text || loading) return

    setInput('')
    setMessages((prev) => [...prev, { role: 'user', content: text }])
    setLoading(true)

    try {
      const res = await chatMessage(sessionId, text, historyForApi(), matchingContext)
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: res.reply,
          pendingUpdate: res.config_update ?? undefined,
          updateApplied: false,
        },
      ])
    } catch (err) {
      const detail = err instanceof Error ? err.message : 'Unknown error'
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: `Sorry, something went wrong: ${detail}` },
      ])
    } finally {
      setLoading(false)
    }
  }, [input, loading, sessionId, matchingContext, historyForApi])

  const handleApplyUpdate = useCallback((msgIndex: number, update: MatchingConfigUpdate) => {
    onConfigUpdate?.(update)
    setMessages((prev) =>
      prev.map((m, i) => (i === msgIndex ? { ...m, updateApplied: true } : m))
    )
  }, [onConfigUpdate])

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <>
      {/* Floating trigger */}
      <button
        onClick={() => setOpen((v) => !v)}
        aria-label="Open AI assistant"
        className="fixed bottom-6 right-6 z-50 flex items-center gap-2 rounded-full bg-[#98002E] px-4 py-3 text-sm font-semibold text-white shadow-lg hover:bg-[#7a0025] transition-colors"
      >
        <MessageCircle className="size-4" aria-hidden />
        Ask AI
      </button>

      {/* Panel */}
      {open && (
        <div className="fixed bottom-20 right-6 z-50 flex flex-col w-96 h-[560px] rounded-2xl bg-white shadow-2xl border border-gray-200 overflow-hidden">
          {/* Header */}
          <div className="flex items-center justify-between px-4 py-3 bg-[#333333] text-white shrink-0">
            <span className="font-semibold text-sm">Recon Assistant</span>
            <button onClick={() => setOpen(false)} aria-label="Close" className="text-gray-300 hover:text-white">
              <X className="size-4" />
            </button>
          </div>

          {/* Messages */}
          <div className="flex-1 overflow-y-auto px-3 py-3 space-y-3">
            {messages.map((msg, i) => (
              <div key={i} className={`flex flex-col gap-1 ${msg.role === 'user' ? 'items-end' : 'items-start'}`}>
                <div
                  className={`max-w-[85%] rounded-2xl px-3 py-2 text-sm leading-relaxed ${
                    msg.role === 'user'
                      ? 'bg-[#98002E] text-white rounded-br-sm'
                      : 'bg-gray-100 text-[#1a1a1a] rounded-bl-sm'
                  }`}
                >
                  {msg.content}
                </div>

                {/* Config update proposal */}
                {msg.pendingUpdate && onConfigUpdate && (
                  <div className="max-w-[85%] rounded-xl border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-[#1a1a1a]">
                    {msg.updateApplied ? (
                      <div className="flex items-center gap-1.5 text-[#009966] font-semibold">
                        <CheckCircle className="size-3.5" />
                        Plan updated
                      </div>
                    ) : (
                      <>
                        <p className="font-semibold text-amber-800 mb-1.5">Plan changes ready to apply</p>
                        {msg.pendingUpdate.deterministic && (
                          <p className="mb-0.5">
                            {msg.pendingUpdate.deterministic.length} deterministic scenario
                            {msg.pendingUpdate.deterministic.length !== 1 ? 's' : ''}
                          </p>
                        )}
                        {msg.pendingUpdate.probabilistic?.weights && (
                          <p className="mb-1.5">
                            Weights:{' '}
                            {Object.entries(msg.pendingUpdate.probabilistic.weights)
                              .map(([k, v]) => `${k} ${(v as number).toFixed(2)}`)
                              .join(', ')}
                          </p>
                        )}
                        <div className="flex gap-2">
                          <button
                            onClick={() => handleApplyUpdate(i, msg.pendingUpdate!)}
                            className="rounded-lg bg-[#98002E] px-2.5 py-1 text-white font-semibold hover:bg-[#7a0025] transition-colors"
                          >
                            Apply to Plan
                          </button>
                          <button
                            onClick={() => setMessages((prev) => prev.map((m, idx) => idx === i ? { ...m, pendingUpdate: undefined } : m))}
                            className="rounded-lg border border-gray-300 px-2.5 py-1 text-[#1a1a1a] hover:bg-gray-100 transition-colors"
                          >
                            Dismiss
                          </button>
                        </div>
                      </>
                    )}
                  </div>
                )}
              </div>
            ))}

            {loading && (
              <div className="flex items-start">
                <div className="bg-gray-100 rounded-2xl rounded-bl-sm px-3 py-2 text-sm text-[#1a1a1a] flex items-center gap-1.5">
                  <Loader2 className="size-3.5 animate-spin" />
                  Thinking…
                </div>
              </div>
            )}
            <div ref={bottomRef} />
          </div>

          {/* Input */}
          <div className="shrink-0 flex gap-2 px-3 py-3 border-t border-gray-200 bg-white">
            <input
              ref={inputRef}
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask about your data or the plan…"
              disabled={loading}
              className="flex-1 rounded-lg border border-gray-300 px-3 py-2 text-sm text-[#1a1a1a] placeholder:text-gray-400 focus:outline-none focus:ring-1 focus:ring-[#98002E] disabled:opacity-50"
            />
            <Button
              size="sm"
              variant="brand"
              disabled={!input.trim() || loading}
              onClick={handleSend}
              aria-label="Send"
            >
              <Send className="size-4" />
            </Button>
          </div>
        </div>
      )}
    </>
  )
}
