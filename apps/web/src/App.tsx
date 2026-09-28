import { NavLink, Outlet, useLocation, useMatch } from 'react-router'

function navClass(isActive: boolean): string {
  return isActive
    ? 'bg-sidebar-accent text-sidebar-accent-foreground'
    : 'text-sidebar-foreground/80 hover:bg-sidebar-accent/80 hover:text-sidebar-foreground'
}

export default function App() {
  const location = useLocation()
  const skillMatch = useMatch('/skills/:id/*')
  const skillId = skillMatch?.params.id
  const onEvaluations = /\/skills\/[^/]+\/evaluations\/?$/.test(
    location.pathname,
  )
  const onTimeline = /\/skills\/[^/]+\/timeline\/?$/.test(location.pathname)
  const evaluationsTo =
    skillId && skillId.length > 0
      ? `/skills/${encodeURIComponent(skillId)}/evaluations`
      : '/skills'
  const timelineTo =
    skillId && skillId.length > 0
      ? `/skills/${encodeURIComponent(skillId)}/timeline`
      : '/skills'
  const studioActive =
    location.pathname.startsWith('/skills') && !onEvaluations && !onTimeline

  const linkClass = (active: boolean) =>
    `shrink-0 whitespace-nowrap rounded-md px-2.5 py-1.5 ${navClass(active)}`

  return (
    <div className="min-h-svh bg-background text-foreground md:pl-56">
      <nav className="flex items-center gap-1 overflow-x-auto border-b border-sidebar-border bg-sidebar px-3 py-2 text-sm text-sidebar-foreground md:fixed md:inset-y-0 md:left-0 md:w-56 md:flex-col md:items-stretch md:gap-1 md:overflow-y-auto md:border-r md:border-b-0 md:px-3 md:py-5">
        <div className="mr-2 shrink-0 px-1 md:mr-0 md:px-2 md:pb-6">
          <div className="text-sm font-semibold tracking-tight">SkillForge</div>
          <div className="mt-0.5 hidden text-xs text-sidebar-foreground/70 md:block">
            技能工厂
          </div>
        </div>
        <NavLink
          to="/"
          end
          className={({ isActive }) => linkClass(isActive)}
        >
          首页
        </NavLink>
        <NavLink
          to="/dashboard"
          className={({ isActive }) => linkClass(isActive)}
        >
          总览
        </NavLink>
        <NavLink to="/demo" className={({ isActive }) => linkClass(isActive)}>
          演示
        </NavLink>
        <NavLink to="/runtime" className={({ isActive }) => linkClass(isActive)}>
          运行时
        </NavLink>
        <NavLink to="/skills" className={() => linkClass(studioActive)} end>
          工作室
        </NavLink>
        <NavLink
          to={evaluationsTo}
          className={() => linkClass(onEvaluations)}
        >
          评测
        </NavLink>
        <NavLink to={timelineTo} className={() => linkClass(onTimeline)}>
          时间线
        </NavLink>
        <NavLink
          to="/knowledge"
          className={({ isActive }) => linkClass(isActive)}
        >
          知识
        </NavLink>
      </nav>
      <Outlet />
    </div>
  )
}
