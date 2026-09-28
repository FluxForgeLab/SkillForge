import { Link } from 'react-router'

import { DgxRuntimePanel } from '@/components/DgxRuntimePanel'

/** Standalone DGX Runtime view (C9.10). */
export default function RuntimePage() {
  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-4 p-4 sm:p-6">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b pb-4">
        <h1 className="text-xl font-semibold tracking-tight sm:text-2xl">
          DGX 运行时
        </h1>
        <Link
          className="text-sm text-muted-foreground underline underline-offset-4 hover:text-foreground"
          to="/demo"
        >
          返回演示
        </Link>
      </header>
      <p className="text-sm text-muted-foreground">
        显示当前配置的模型身份。Token/秒和内存在 StepFun 适配器上报实测值之前保持
        <span className="text-foreground">未测量</span>
        （C10.2）。
      </p>
      <DgxRuntimePanel variant="section" />
    </div>
  )
}
