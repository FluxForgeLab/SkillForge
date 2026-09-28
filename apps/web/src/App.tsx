import { NavLink, Outlet, useLocation, useMatch } from 'react-router'

function navClass(isActive: boolean): string {
  return isActive
    ? 'text-foreground'
    : 'text-muted-foreground hover:text-foreground'
}

export default function App() {
  const location = useLocation()
  const skillMatch = useMatch('/skills/:id/*')
  const skillId = skillMatch?.params.id
  const onEvaluations = /\/skills\/[^/]+\/evaluations\/?$/.test(
    location.pathname,
  )
  const evaluationsTo =
    skillId && skillId.length > 0
      ? `/skills/${encodeURIComponent(skillId)}/evaluations`
      : '/skills'
  const studioActive =
    location.pathname.startsWith('/skills') && !onEvaluations

  return (
    <div className="flex min-h-svh flex-col bg-background text-foreground">
      <nav className="flex items-center gap-4 border-b px-6 py-3 text-sm">
        <span className="font-semibold tracking-tight">SkillForge</span>
        <NavLink to="/" end className={({ isActive }) => navClass(isActive)}>
          Home
        </NavLink>
        <NavLink to="/demo" className={({ isActive }) => navClass(isActive)}>
          Demo
        </NavLink>
        <NavLink to="/skills" className={() => navClass(studioActive)} end>
          Studio
        </NavLink>
        <NavLink
          to={evaluationsTo}
          className={() => navClass(onEvaluations)}
        >
          Evaluations
        </NavLink>
      </nav>
      <Outlet />
    </div>
  )
}
