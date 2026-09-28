import { NavLink, Outlet } from 'react-router'

export default function App() {
  return (
    <div className="flex min-h-svh flex-col bg-background text-foreground">
      <nav className="flex items-center gap-4 border-b px-6 py-3 text-sm">
        <span className="font-semibold tracking-tight">SkillForge</span>
        <NavLink
          to="/"
          end
          className={({ isActive }) =>
            isActive
              ? 'text-foreground'
              : 'text-muted-foreground hover:text-foreground'
          }
        >
          Home
        </NavLink>
        <NavLink
          to="/demo"
          className={({ isActive }) =>
            isActive
              ? 'text-foreground'
              : 'text-muted-foreground hover:text-foreground'
          }
        >
          Demo
        </NavLink>
      </nav>
      <Outlet />
    </div>
  )
}
