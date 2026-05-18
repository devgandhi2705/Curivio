function Bone({ className }) {
  return <div className={`bg-slate-800 rounded-lg animate-pulse ${className}`} />
}

function InsightSkeleton() {
  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden">
      <div className="border-l-4 border-slate-700 p-5">
        <Bone className="h-3 w-24 mb-4" />
        <Bone className="h-5 w-3/4 mb-3" />
        <Bone className="h-4 w-full mb-1.5" />
        <Bone className="h-4 w-5/6 mb-5" />
        <div className="bg-slate-800/60 rounded-xl p-4 mb-4">
          <Bone className="h-3 w-28 mb-2.5" />
          <Bone className="h-4 w-full mb-1.5" />
          <Bone className="h-4 w-4/5" />
        </div>
        <div className="grid grid-cols-2 gap-2">
          <Bone className="h-9 rounded-xl" />
          <Bone className="h-9 rounded-xl" />
        </div>
      </div>
    </div>
  )
}

function TopicsSkeleton() {
  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 space-y-3">
      <Bone className="h-3 w-44 mb-2" />
      {[0, 1, 2, 3].map(i => (
        <div key={i} className="flex items-start gap-4">
          <Bone className="h-8 w-8 rounded-xl flex-shrink-0" />
          <div className="flex-1">
            <Bone className="h-4 w-1/2 mb-2" />
            <Bone className="h-3 w-full" />
          </div>
        </div>
      ))}
    </div>
  )
}

function SidebarSkeleton() {
  return (
    <div className="space-y-5">
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5">
        <Bone className="h-3 w-28 mb-4" />
        <Bone className="h-4 w-full mb-2" />
        <Bone className="h-4 w-4/5 mb-2" />
        <Bone className="h-4 w-3/4" />
      </div>
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5">
        <Bone className="h-3 w-36 mb-4" />
        {[0, 1, 2].map(i => (
          <div key={i} className="flex items-center gap-3 mb-3">
            <Bone className="h-4 w-4 rounded" />
            <Bone className="h-4 flex-1" />
          </div>
        ))}
        <Bone className="h-9 rounded-xl mt-2" />
      </div>
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5">
        <Bone className="h-3 w-24 mb-4" />
        <Bone className="h-4 w-full mb-1.5" />
        <Bone className="h-4 w-3/4" />
      </div>
    </div>
  )
}

export default function LoadingState() {
  return (
    <div className="grid grid-cols-1 lg:grid-cols-5 gap-5">
      <div className="lg:col-span-3 space-y-5">
        <InsightSkeleton />
        <TopicsSkeleton />
      </div>
      <div className="lg:col-span-2">
        <SidebarSkeleton />
      </div>
    </div>
  )
}
