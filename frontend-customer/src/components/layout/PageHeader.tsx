import { cn } from '@/lib/utils'

interface PageHeaderProps {
  title: string
  className?: string
}

export function PageHeader({ title, className }: PageHeaderProps) {
  return (
    <header className={cn('mb-6', className)}>
      <h1 className="text-2xl font-bold tracking-tight text-foreground md:text-3xl">
        {title}
      </h1>
    </header>
  )
}
