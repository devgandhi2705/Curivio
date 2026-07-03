export default function AuthLoadingScreen() {
  return (
    <div className="min-h-screen min-h-dvh bg-slate-950 flex items-center justify-center">
      <div className="flex flex-col items-center gap-5">
        <div className="relative w-12 h-12 flex-shrink-0">
          <div className="absolute inset-0 rounded-2xl bg-gradient-to-br from-blue-500 via-indigo-500 to-violet-600 shadow-lg shadow-violet-950/50 animate-pulse" />
          <div className="absolute inset-0 rounded-2xl flex items-center justify-center">
            <svg style={{ width: '22px', height: '22px' }} viewBox="0 0 20 20" fill="none">
              <circle cx="10" cy="8" r="4" fill="white" fillOpacity="0.95" />
              <rect x="8.25" y="12" width="3.5" height="1.2" rx="0.6" fill="white" fillOpacity="0.8" />
              <rect x="8.75" y="13.6" width="2.5" height="1.1" rx="0.55" fill="white" fillOpacity="0.6" />
              <path d="M10 4 L10 2.5" stroke="white" strokeWidth="1.2" strokeLinecap="round" strokeOpacity="0.7" />
              <path d="M13.5 5.5 L14.6 4.4" stroke="white" strokeWidth="1.2" strokeLinecap="round" strokeOpacity="0.7" />
              <path d="M6.5 5.5 L5.4 4.4" stroke="white" strokeWidth="1.2" strokeLinecap="round" strokeOpacity="0.7" />
              <path d="M14.5 8 L16 8" stroke="white" strokeWidth="1.2" strokeLinecap="round" strokeOpacity="0.7" />
              <path d="M5.5 8 L4 8" stroke="white" strokeWidth="1.2" strokeLinecap="round" strokeOpacity="0.7" />
            </svg>
          </div>
        </div>
        <div className="flex gap-1.5">
          <span className="w-1.5 h-1.5 bg-slate-700 rounded-full animate-bounce [animation-delay:-0.3s]" />
          <span className="w-1.5 h-1.5 bg-slate-700 rounded-full animate-bounce [animation-delay:-0.15s]" />
          <span className="w-1.5 h-1.5 bg-slate-700 rounded-full animate-bounce" />
        </div>
      </div>
    </div>
  )
}
