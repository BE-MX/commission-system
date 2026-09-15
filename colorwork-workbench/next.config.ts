import type { NextConfig } from 'next';
import { WORKBENCH_PATH } from './lib/workbench-url';

const nextConfig: NextConfig = { basePath: WORKBENCH_PATH };

export default nextConfig;
