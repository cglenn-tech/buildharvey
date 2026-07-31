import { NextResponse } from 'next/server'
import type { NextRequest } from 'next/server'

const PROTECTED_PATHS = ['/download', '/activate']

export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl
  if (PROTECTED_PATHS.some((p) => pathname.startsWith(p))) {
    // Supabase SSR stores session in a cookie named sb-{project}-auth-token.
    // Check for presence; server routes do full validation independently.
    const hasSession = request.cookies
      .getAll()
      .some(
        (c) => c.name.startsWith('sb-') && c.name.endsWith('-auth-token')
      )
    if (!hasSession) return NextResponse.redirect(new URL('/', request.url))
  }
  return NextResponse.next()
}

export const config = {
  matcher: ['/((?!_next/static|_next/image|favicon.ico|api).*)'],
}
