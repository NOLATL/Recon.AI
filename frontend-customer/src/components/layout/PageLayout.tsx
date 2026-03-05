import { cn } from '@/lib/utils'

interface PageLayoutProps {
  title: string
  description?: string
  children: React.ReactNode
  className?: string
}

export function PageLayout({ title, description, children, className }: PageLayoutProps) {
  return (
    <div className={cn('mx-auto max-w-6xl', className)}>
      <header className="mb-6">
        <h1 className="text-3xl font-semibold tracking-tight text-foreground">
          {title}
        </h1>
        {description != null && (
          <p className="mt-1 text-sm text-muted-foreground">{description}</p>
        )}
      </header>
      <div className="space-y-6">{children}</div>
    </div>
  )
}
