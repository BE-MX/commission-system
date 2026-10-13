import fs from 'node:fs'
import path from 'node:path'
import { createServer } from 'vite'
import { execFileSync } from 'node:child_process'
import { createHash } from 'node:crypto'

/**
 * 构建收尾时导出 <outDir>/nav-manifest.json，供任务中心后端启动时同步模块注册表。
 * 用 vite SSR 加载 navigation.js（它依赖 @ 别名与图标包，组件是懒加载不会执行）。
 * 常用导航保存需要此权限清单；导出失败阻断构建，避免发布缺失的权限元数据。
 */
export function navManifestPlugin() {
  let root
  let outDir
  return {
    name: 'ark-nav-manifest',
    apply: 'build',
    configResolved(config) {
      root = config.root
      outDir = path.resolve(config.root, config.build.outDir)
    },
    async closeBundle() {
      let server
      try {
        server = await createServer({
          configFile: false,
          root,
          logLevel: 'error',
          appType: 'custom',
          server: { middlewareMode: true, hmr: false },
          resolve: { alias: { '@': path.resolve(root, 'src') } },
          optimizeDeps: { noDiscovery: true, include: [] },
        })
        const nav = await server.ssrLoadModule('/src/config/navigation.js')
        const { buildNavManifest } = await server.ssrLoadModule('/src/config/navManifest.js')
        let gitSha = null
        try {
          gitSha = execFileSync('git', ['rev-parse', 'HEAD'], { cwd: root, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).trim()
        } catch {
          console.warn('[nav-manifest] git SHA unavailable; manifest will contain null')
        }
        const manifest = buildNavManifest(nav.MENU_GROUPS, nav.NAV_ENTRIES, gitSha)
        fs.writeFileSync(path.join(outDir, 'nav-manifest.json'), JSON.stringify(manifest, null, 2))
        // Backends and static sites have different deployment roots. Ship a tracked
        // policy with backend source, without relying on an ignored frontend dist.
        const navigationSource = fs.readFileSync(path.join(root, 'src/config/navigation.js'), 'utf8').replace(/\r\n/g, '\n')
        const accessManifest = {
          source_sha256: createHash('sha256').update(navigationSource).digest('hex'),
          favorite_access: manifest.favorite_access,
        }
        fs.writeFileSync(path.resolve(root, '../backend/app/system/navigation_access_manifest.json'), JSON.stringify(accessManifest, null, 2) + '\n')
        console.log(`[nav-manifest] ${manifest.entries.length} entries -> nav-manifest.json`)
      } catch (err) {
        throw new Error(`[nav-manifest] export failed: ${err.message}`, { cause: err })
      } finally {
        await server?.close()
      }
    },
  }
}
