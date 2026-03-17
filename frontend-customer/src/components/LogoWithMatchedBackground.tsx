import { useEffect, useRef, useState } from 'react'
import { cn } from '@/lib/utils'

/** Charcoal (matches --background in index.css) */
const CHARCOAL_BG = { r: 10, g: 10, b: 10 }

/** Parse computed backgroundColor (e.g. "rgb(204, 37, 41)", "rgb(204 37 41)", "rgba(...)") to { r, g, b } */
function parseRgb(str: string): { r: number; g: number; b: number } | null {
  const rgb = str.match(/rgba?\((\d+)[,\s]+(\d+)[,\s]+(\d+)/)
  if (rgb) {
    return { r: +rgb[1], g: +rgb[2], b: +rgb[3] }
  }
  const hex = str.match(/^#([0-9a-fA-F]{6})$/)
  if (hex) {
    return {
      r: parseInt(hex[1].slice(0, 2), 16),
      g: parseInt(hex[1].slice(2, 4), 16),
      b: parseInt(hex[1].slice(4, 6), 16),
    }
  }
  return null
}

/** Resolve primary (sidebar) red from the actual sidebar element so logo background matches exactly */
function getPrimaryColorFromSidebar(img: HTMLImageElement): { r: number; g: number; b: number } {
  const sidebar = img.closest('aside')
  if (sidebar) {
    const bg = getComputedStyle(sidebar).backgroundColor
    const parsed = parseRgb(bg)
    if (parsed) return parsed
  }
  // Fallback: sample via var(--primary) to match exactly what the sidebar uses
  const el = document.createElement('div')
  el.style.cssText = 'position:absolute;left:-9999px;width:1px;height:1px;pointer-events:none;background:var(--primary)'
  document.body.appendChild(el)
  const bg = getComputedStyle(el).backgroundColor
  document.body.removeChild(el)
  const parsed = parseRgb(bg)
  if (parsed) return parsed
  return { r: 204, g: 37, b: 41 }
}

/** Charcoal for logo graphic when on red background (#1a1a1a) */
const LOGO_CHARCOAL = { r: 26, g: 26, b: 26 }

/** Pixels where R≈G≈B and luminance is in charcoal range get replaced with target bg */
function isCharcoalBg(r: number, g: number, b: number): boolean {
  const gray = (r + g + b) / 3
  const isNeutral =
    Math.abs(r - g) < 30 &&
    Math.abs(g - b) < 30 &&
    Math.abs(r - b) < 30
  return isNeutral && gray >= 12 && gray <= 90
}

/** White/light pixels (logo mark) — when on red, replace with charcoal so logo appears charcoal */
function isLight(r: number, g: number, b: number): boolean {
  const gray = (r + g + b) / 3
  const isNeutral =
    Math.abs(r - g) < 30 &&
    Math.abs(g - b) < 30 &&
    Math.abs(r - b) < 30
  return isNeutral && gray > 140
}

/** Red pixels (logo on red bg) — replace with white so logo is visible on red sidebar */
function isRed(r: number, g: number, b: number): boolean {
  return r > 120 && g < 80 && b < 80
}

const WHITE = { r: 255, g: 255, b: 255 }

interface Props {
  className?: string
  alt?: string
  /** Match logo background to 'charcoal' (page) or 'primary' (red sidebar) */
  background?: 'charcoal' | 'primary'
}

export function LogoWithMatchedBackground({ className = '', alt = 'ReconAI', background = 'charcoal' }: Props) {
  const imgRef = useRef<HTMLImageElement>(null)
  const [processedSrc, setProcessedSrc] = useState<string | null>(null)
  const [size, setSize] = useState<{ w: number; h: number } | null>(null)

  useEffect(() => {
    const img = imgRef.current
    if (!img) return

    const process = () => {
      if (img.naturalWidth === 0 || img.naturalHeight === 0) return

      const runCanvas = () => {
        const bg = background === 'primary' ? getPrimaryColorFromSidebar(img) : CHARCOAL_BG
        const canvas = document.createElement('canvas')
        canvas.width = img.naturalWidth
        canvas.height = img.naturalHeight
        const ctx = canvas.getContext('2d')
        if (!ctx) return

        ctx.drawImage(img, 0, 0)
        const data = ctx.getImageData(0, 0, canvas.width, canvas.height)
        const pixels = data.data

        for (let i = 0; i < pixels.length; i += 4) {
          const r = pixels[i]
          const g = pixels[i + 1]
          const b = pixels[i + 2]
          const a = pixels[i + 3]
          if (a < 200) continue
          if (isCharcoalBg(r, g, b)) {
            if (background === 'primary') {
              pixels[i + 3] = 0
            } else {
              pixels[i] = bg.r
              pixels[i + 1] = bg.g
              pixels[i + 2] = bg.b
            }
          } else if (background === 'primary' && isRed(r, g, b)) {
            pixels[i] = WHITE.r
            pixels[i + 1] = WHITE.g
            pixels[i + 2] = WHITE.b
          } else if (background === 'primary' && isLight(r, g, b)) {
            pixels[i] = LOGO_CHARCOAL.r
            pixels[i + 1] = LOGO_CHARCOAL.g
            pixels[i + 2] = LOGO_CHARCOAL.b
          }
        }
        ctx.putImageData(data, 0, 0)
        setProcessedSrc(canvas.toDataURL('image/png'))
        setSize({ w: canvas.width, h: canvas.height })
      }

      // Defer color sampling to after paint so sidebar styles are fully applied
      if (background === 'primary') {
        requestAnimationFrame(() => requestAnimationFrame(runCanvas))
      } else {
        runCanvas()
      }
    }

    if (img.complete && img.naturalWidth > 0) {
      process()
    } else {
      img.onload = process
    }
  }, [background])

  if (processedSrc && size) {
    return (
      <img
        src={processedSrc}
        alt={alt}
        className={className}
        width={size.w}
        height={size.h}
      />
    )
  }

  // Show raw logo visibly while processing. If processing never completes
  // (e.g. image 404, CORS, canvas failure), user still sees the logo.
  // Min dimensions ensure space is reserved even if image fails to load.
  return (
    <img
      ref={imgRef}
      src="/logo.png"
      alt={alt}
      className={cn(className, 'min-h-[2rem] min-w-[6rem]')}
    />
  )
}
