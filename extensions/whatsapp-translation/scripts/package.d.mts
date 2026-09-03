export type Release = {
  extension_id: string
  filename: string
  sha256: string
  size: number
  version: string
}

export function packageRelease(options?: {
  distDir?: string
  manifestPath?: string
  outputDir?: string
  repositoryRoot?: string
}): Release
