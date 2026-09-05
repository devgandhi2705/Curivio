import LogoMark from './shared/LogoMark.jsx'

export default function AuthLoadingScreen() {
  return (
    <div className="min-h-screen min-h-dvh bg-slate-950 flex items-center justify-center">
      <div className="flex flex-col items-center gap-5">
        <LogoMark size={48} className="animate-pulse" />
        <div className="flex gap-1.5">
          <span className="w-1.5 h-1.5 bg-slate-700 rounded-full animate-bounce [animation-delay:-0.3s]" />
          <span className="w-1.5 h-1.5 bg-slate-700 rounded-full animate-bounce [animation-delay:-0.15s]" />
          <span className="w-1.5 h-1.5 bg-slate-700 rounded-full animate-bounce" />
        </div>
      </div>
    </div>
  )
}
