// Next proxy (formerly middleware). One job: a path with a malformed percent escape
// (`/agents/%E0%A4%A`) gets the normal 404 page, not a 500 from Next's router.
import { NextResponse, type NextRequest } from "next/server";

import { NOT_FOUND_PATH, pathDecodes } from "./lib/safePath";

export function proxy(request: NextRequest) {
  if (pathDecodes(request.nextUrl.pathname)) return NextResponse.next();
  return NextResponse.rewrite(new URL(NOT_FOUND_PATH, request.url), { status: 404 });
}

export const config = {
  // Pages only: static assets and the /api proxy (the backend answers its own) are skipped.
  matcher: ["/((?!_next/static|_next/image|api/|favicon.ico).*)"],
};
