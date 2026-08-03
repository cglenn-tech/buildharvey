// Mock modules that throw in non-Next.js server contexts
import { vi } from 'vitest'

vi.mock('server-only', () => ({}))
