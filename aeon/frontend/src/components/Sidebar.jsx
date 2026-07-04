import { NavLink } from 'react-router-dom'
import { useEffect, useState } from 'react'
import { getOdysseusStatus } from '../lib/api.js'
import {
  LayoutDashboard, Bot, GitBranch, AlertTriangle,
  Workflow, Network, Layers, Zap, Link2, Search, ExternalLink, Circle,
} from 'lucide-react'

const coreItems = [
  { to: '/',           label: 'Dashboard',      icon: LayoutDashboard },
  { to: '/ai',         label: 'AI Assistant',   icon: Bot },
  { to: '/pipelines',  label: 'Pipelines',      icon: GitBranch },
  { to: '/incidents',  label: 'Incidents',      icon: AlertTriangle },
  { to: '/workflows',  label: 'Workflows',      icon: Workflow },
]

const aiItems = [
  { to: '/graph',      label: 'Knowledge Graph', icon: Network },
  { to: '/provenance', label: 'Code Provenance', icon: Layers },
  { to: '/blast',      label: 'Blast Radius',    icon: Zap },
  { to: '/cochange',   label: 'Co-Change',       icon: Link2 },
]

const ODYSSEUS_URL = 'http://localhost:7000'

function NavItem({ to, label, icon: Icon }) {
  return (
    <NavLink
      to={to}
      end={to === '/'}
      className={({ isActive }) =>
        [
          'flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors',
          isActive
            ? 'bg-aeon-primary text-white'
            : 'text-slate-400 hover:text-white hover:bg-white/5',
        ].join(' ')
      }
    >
      <Icon size={18} />
      {label}
    </NavLink>
  )
}

function SectionLabel({ children }) {
  return (
    <p className="px-3 pt-4 pb-1 text-xs font-semibold uppercase tracking-wider text-slate-600">
      {children}
    </p>
  )
}

export default function Sidebar() {
  const [odysseusOnline, setOdysseusOnline] = useState(null)

  useEffect(() => {
    getOdysseusStatus()
      .then((s) => setOdysseusOnline(s.connected))
      .catch(() => setOdysseusOnline(false))
  }, [])

  return (
    <aside className="w-64 bg-aeon-surface border-r border-aeon-border flex flex-col shrink-0">
      {/* Logo */}
      <div className="px-6 py-5 border-b border-aeon-border">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-lg bg-aeon-primary flex items-center justify-center">
            <span className="text-white font-bold text-sm">A</span>
          </div>
          <div>
            <h1 className="text-white font-bold text-lg leading-none">Aeon</h1>
            <p className="text-slate-400 text-xs">AI Ops Workspace</p>
          </div>
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 px-3 py-3 overflow-y-auto">
        <SectionLabel>Core Ops</SectionLabel>
        <div className="space-y-0.5">
          {coreItems.map(item => <NavItem key={item.to} {...item} />)}
        </div>

        <div className="mt-3 border-t border-aeon-border/50 pt-1">
          <SectionLabel>AI Intelligence</SectionLabel>
          <div className="space-y-0.5">
            {aiItems.map(item => <NavItem key={item.to} {...item} />)}

            {/* Odysseus Research — external link */}
            <a
              href={ODYSSEUS_URL}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium text-slate-400 hover:text-white hover:bg-white/5 transition-colors"
            >
              <Search size={18} />
              <span>Odysseus Research</span>
              <ExternalLink size={11} className="ml-auto text-slate-600" />
              {odysseusOnline !== null && (
                <Circle
                  size={6}
                  className={odysseusOnline ? 'text-green-400 fill-green-400' : 'text-slate-600 fill-slate-600'}
                />
              )}
            </a>
          </div>
        </div>
      </nav>

      {/* Footer */}
      <div className="px-6 py-4 border-t border-aeon-border">
        <p className="text-slate-500 text-xs">Powered by Aeon AI</p>
      </div>
    </aside>
  )
}
