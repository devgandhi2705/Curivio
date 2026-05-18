import { useState, useMemo } from 'react'
import DashboardHeader from './DashboardHeader.jsx'
import CategoryFilter  from './CategoryFilter.jsx'
import InsightCard     from './InsightCard.jsx'
import LearningPanel   from './LearningPanel.jsx'
import ActionPanel     from './ActionPanel.jsx'

// Section display order and metadata
const SECTION_META = {
  development: {
    title: 'Important Developments',
    icon: (
      <svg className="w-4 h-4" viewBox="0 0 20 20" fill="currentColor">
        <path fillRule="evenodd" d="M11.3 1.046A1 1 0 0 0 10 2v4H5a1 1 0 0 0-.812 1.59l7 10A1 1 0 0 0 13 17v-4h5a1 1 0 0 0 .812-1.59l-7-10a1 1 0 0 0-.512-.364Z" clipRule="evenodd" />
      </svg>
    ),
    iconColor: 'text-amber-400',
    divider:   'border-amber-500/20',
  },
  industry_news: {
    title: 'Industry Insights',
    icon: (
      <svg className="w-4 h-4" viewBox="0 0 20 20" fill="currentColor">
        <path fillRule="evenodd" d="M2 3.5A1.5 1.5 0 0 1 3.5 2h9A1.5 1.5 0 0 1 14 3.5v11.75A2.75 2.75 0 0 0 16.75 18h-12A2.75 2.75 0 0 1 2 15.25V3.5Zm3.75 7a.75.75 0 0 0 0 1.5h4.5a.75.75 0 0 0 0-1.5h-4.5Zm0 3a.75.75 0 0 0 0 1.5h4.5a.75.75 0 0 0 0-1.5h-4.5ZM5 5.75A.75.75 0 0 1 5.75 5h4.5a.75.75 0 0 1 .75.75v2.5a.75.75 0 0 1-.75.75h-4.5A.75.75 0 0 1 5 8.25v-2.5Z" clipRule="evenodd" />
        <path d="M16.5 6.5h-1v8.75a1.25 1.25 0 0 0 2.5 0V8a1.5 1.5 0 0 0-1.5-1.5Z" />
      </svg>
    ),
    iconColor: 'text-blue-400',
    divider:   'border-blue-500/20',
  },
  market_trends: {
    title: 'Market Trends',
    icon: (
      <svg className="w-4 h-4" viewBox="0 0 20 20" fill="currentColor">
        <path fillRule="evenodd" d="M12 7a1 1 0 1 1-2 0 1 1 0 0 1 2 0ZM7 9a1 1 0 1 1-2 0 1 1 0 0 1 2 0Zm7-1a1 1 0 1 1-2 0 1 1 0 0 1 2 0Zm-5.5 5.5a1 1 0 1 1-2 0 1 1 0 0 1 2 0Zm7-1a1 1 0 1 1-2 0 1 1 0 0 1 2 0Z" clipRule="evenodd" />
        <path fillRule="evenodd" d="M2 2.75A.75.75 0 0 1 2.75 2h14.5a.75.75 0 0 1 .75.75v14.5a.75.75 0 0 1-.75.75H2.75a.75.75 0 0 1-.75-.75V2.75Zm1.5.75v13h13V3.5h-13Z" clipRule="evenodd" />
      </svg>
    ),
    iconColor: 'text-emerald-400',
    divider:   'border-emerald-500/20',
  },
  technical_discovery: {
    title: 'Research & Discoveries',
    icon: (
      <svg className="w-4 h-4" viewBox="0 0 20 20" fill="currentColor">
        <path fillRule="evenodd" d="M8.5 3.528v4.644c0 .729-.29 1.428-.805 1.944l-1.217 1.216a8.75 8.75 0 0 1 3.55.621l.502.201a7.25 7.25 0 0 0 4.178.221l2.290-.512a.75.75 0 0 1 .524 1.4l-2.29.513a8.75 8.75 0 0 1-5.046-.267l-.502-.201a7.25 7.25 0 0 0-4.17-.221l-2.289.512A.75.75 0 0 1 2.7 12.6l2.29-.512a8.75 8.75 0 0 0 1.1-.301L4.805 10.5A3.25 3.25 0 0 1 4 8.172V3.528a.75.75 0 0 1 .75-.75h.5V1.75a.75.75 0 0 1 1.5 0v1.028h1V1.75a.75.75 0 0 1 1.5 0v1.028h.5a.75.75 0 0 1 .75.75Z" clipRule="evenodd" />
      </svg>
    ),
    iconColor: 'text-violet-400',
    divider:   'border-violet-500/20',
  },
}

const SECTION_ORDER = ['development', 'industry_news', 'market_trends', 'technical_discovery']

// Normalise old sections[] shape to the new insights[] shape
function normalise(feed) {
  if (!feed) return feed
  if (feed.insights) return feed

  const insights = []
  for (const section of (feed.sections || [])) {
    for (const item of (section.items || [])) {
      insights.push({
        id:             `${section.type}-${item.title}`,
        category:       'AI/Technology',
        type:           section.type === 'technical_discoveries' ? 'technical_discovery' : section.type,
        urgency:        'medium',
        title:          item.title,
        insight:        item.insight,
        why_it_matters: item.why_it_matters,
        sources:        item.sources || [],
      })
    }
  }

  return {
    ...feed,
    insights,
    generated_at: feed.generated_at || new Date().toISOString(),
  }
}

// ── Loading skeleton ──────────────────────────────────────────────────────────

function Skeleton() {
  return (
    <div className="space-y-6 animate-pulse">
      <div className="space-y-2">
        <div className="h-3 w-32 bg-slate-800 rounded" />
        <div className="h-5 w-3/4 bg-slate-800 rounded" />
        <div className="h-4 w-full bg-slate-800 rounded" />
        <div className="h-4 w-2/3 bg-slate-800 rounded" />
      </div>
      <div className="flex gap-2">
        {[1,2,3,4,5,6].map(i => (
          <div key={i} className="h-7 w-24 bg-slate-800 rounded-lg" />
        ))}
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 space-y-4">
          {[1,2,3,4].map(i => (
            <div key={i} className="h-32 bg-slate-900 border border-slate-800 rounded-xl" />
          ))}
        </div>
        <div className="space-y-3">
          <div className="h-48 bg-slate-900 border border-slate-800 rounded-2xl" />
          <div className="h-32 bg-slate-900 border border-slate-800 rounded-2xl" />
        </div>
      </div>
    </div>
  )
}

// ── Error state ───────────────────────────────────────────────────────────────

function ErrorState({ message, onRetry }) {
  return (
    <div className="flex flex-col items-center gap-4 py-16 text-center">
      <div className="w-10 h-10 rounded-full bg-red-950/50 border border-red-900/50 flex items-center justify-center text-red-400">
        <svg className="w-5 h-5" viewBox="0 0 20 20" fill="currentColor">
          <path fillRule="evenodd" d="M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0Zm-8-5a.75.75 0 0 1 .75.75v4.5a.75.75 0 0 1-1.5 0v-4.5A.75.75 0 0 1 10 5Zm0 10a1 1 0 1 0 0-2 1 1 0 0 0 0 2Z" clipRule="evenodd" />
        </svg>
      </div>
      <div>
        <p className="text-sm font-medium text-slate-300">Failed to load dashboard</p>
        <p className="text-xs text-slate-500 mt-1">{message}</p>
      </div>
      {onRetry && (
        <button
          onClick={onRetry}
          className="px-4 py-2 rounded-lg border border-slate-700 text-sm text-slate-300
                     hover:border-slate-600 hover:text-slate-100 transition-colors"
        >
          Try again
        </button>
      )}
    </div>
  )
}

// ── Section heading ───────────────────────────────────────────────────────────

function SectionHeading({ type, count }) {
  const meta = SECTION_META[type] || SECTION_META.industry_news
  return (
    <div className={`flex items-center gap-2 pb-3 border-b ${meta.divider}`}>
      <span className={meta.iconColor}>{meta.icon}</span>
      <h2 className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
        {meta.title}
      </h2>
      <span className="ml-auto text-xs text-slate-700 tabular-nums">{count}</span>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export default function IntelligenceDashboard({ feed: rawFeed, loading, error, onRefresh }) {
  const [activeCategory, setActiveCategory] = useState('All')
  const feed = normalise(rawFeed)

  const filteredInsights = useMemo(() => {
    if (!feed?.insights) return []
    const items = activeCategory === 'All'
      ? feed.insights
      : feed.insights.filter(i => i.category === activeCategory)
    // Sort: high urgency first within each section (handled per-group below)
    return items
  }, [feed, activeCategory])

  const grouped = useMemo(() => {
    const map = {}
    for (const item of filteredInsights) {
      if (!map[item.type]) map[item.type] = []
      map[item.type].push(item)
    }
    // Within each group, high urgency first
    for (const key of Object.keys(map)) {
      map[key].sort((a, b) => (a.urgency === 'high' ? -1 : 1) - (b.urgency === 'high' ? -1 : 1))
    }
    return map
  }, [filteredInsights])

  const filteredLearning = useMemo(() => {
    if (!feed?.learning_track) return []
    return activeCategory === 'All'
      ? feed.learning_track
      : feed.learning_track.filter(i => i.category === activeCategory)
  }, [feed, activeCategory])

  if (loading) return <Skeleton />
  if (error)   return <ErrorState message={error} onRetry={onRefresh} />
  if (!feed)   return null

  const activeSections = SECTION_ORDER.filter(t => grouped[t]?.length > 0)

  return (
    <div className="space-y-6">
      <DashboardHeader
        brief={feed.intelligence_brief}
        generatedAt={feed.generated_at}
        onRefresh={onRefresh}
      />

      <CategoryFilter
        insights={feed.insights}
        activeCategory={activeCategory}
        onChange={setActiveCategory}
      />

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">

        {/* Main content: sections + cards */}
        <div className="lg:col-span-2 space-y-8">
          {activeSections.length === 0 ? (
            <p className="text-slate-500 text-sm py-12 text-center">
              No insights for this category yet.
            </p>
          ) : (
            activeSections.map(type => (
              <section key={type}>
                <SectionHeading type={type} count={grouped[type].length} />
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mt-4">
                  {grouped[type].map(item => (
                    <InsightCard key={item.id} item={item} />
                  ))}
                </div>
              </section>
            ))
          )}
        </div>

        {/* Sidebar */}
        <div className="space-y-4">
          <LearningPanel items={filteredLearning} />
          <ActionPanel   items={feed.action_items} />
        </div>
      </div>
    </div>
  )
}
