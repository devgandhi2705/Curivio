import LogoMark from './shared/LogoMark.jsx'
import Plate from './shared/Plate.jsx'
import WaveDots from './shared/WaveDots.jsx'

export default function AuthLoadingScreen() {
  return (
    <div className="relative isolate min-h-screen min-h-dvh bg-slate-950 flex items-center justify-center overflow-hidden">
      <Plate seed={7} count={14} className="u-plate u-plate-empty" />
      <div className="relative flex flex-col items-center gap-5 u-rise">
        <LogoMark size={48} className="animate-pulse" />
        <WaveDots className="text-slate-500" />
      </div>
    </div>
  )
}
