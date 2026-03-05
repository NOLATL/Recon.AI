import { Link } from 'react-router-dom'
import { ArrowRight, Binary, Sliders, Sparkles, ClipboardCheck, FileCheck } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { PageLayout } from '@/components/layout/PageLayout'
import { cn } from '@/lib/utils'

const processSteps = [
  {
    title: 'Deterministic Matching',
    description:
      'Exact rules and keys align the highest-confidence transactions first.',
    icon: Binary,
  },
  {
    title: 'Probabilistic Matching',
    description:
      'Fuzzy logic and scoring surface near-matches and partial overlaps.',
    icon: Sliders,
  },
  {
    title: 'AI Matching',
    description:
      'Machine learning and patterns handle the long tail and edge cases.',
    icon: Sparkles,
  },
  {
    title: 'Review & Override',
    description:
      'Row-level review with accept, override, or mark unmatched—you stay in control.',
    icon: ClipboardCheck,
  },
  {
    title: 'Audit-Ready Export',
    description:
      'Complete reconciliation package: datasets, logs, and optional executive summary PDF.',
    icon: FileCheck,
  },
] as const

export function Landing() {
  return (
    <PageLayout
      title="ReconAI"
      description="Reconcile your GL in minutes with audit-ready outputs."
    >
      <section className="flex flex-col items-center text-center">
        <p className="max-w-2xl text-sm text-muted-foreground">
          Matches begin with the strongest signal and progressively expand through
          deterministic, probabilistic, and AI-assisted matching. You maintain
          full control with row-level review and override capabilities. The
          result is a complete reconciliation with an audit-ready export package.
        </p>
        <Button asChild size="lg" className="mt-6">
          <Link to="/load-files">
            Get Started
            <ArrowRight className="size-4" aria-hidden />
          </Link>
        </Button>
      </section>

      <section>
        <h2 className="sr-only">How it works</h2>
        <div
          className={cn(
            'grid gap-6',
            'grid-cols-1 md:grid-cols-2 lg:grid-cols-3'
          )}
        >
          {processSteps.map(({ title, description, icon: Icon }) => (
            <Card
              key={title}
              className="flex flex-col transition-shadow hover:shadow-md"
            >
              <CardHeader>
                <div className="flex size-10 items-center justify-center rounded-lg bg-primary/10 text-primary">
                  <Icon className="size-5" aria-hidden />
                </div>
                <CardTitle>{title}</CardTitle>
              </CardHeader>
              <CardContent className="pt-0">
                <CardDescription className="text-sm leading-relaxed">
                  {description}
                </CardDescription>
              </CardContent>
            </Card>
          ))}
        </div>
      </section>
    </PageLayout>
  )
}
