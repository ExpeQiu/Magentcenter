import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { DEFAULT_WORKSPACE_SLUG, LEGACY_PREFIXES } from "@/lib/paths";

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const slug =
    request.cookies.get("last_workspace_slug")?.value || DEFAULT_WORKSPACE_SLUG;

  for (const prefix of LEGACY_PREFIXES) {
    if (pathname === `/${prefix}` || pathname.startsWith(`/${prefix}/`)) {
      const url = request.nextUrl.clone();
      url.pathname = `/${slug}${pathname}`;
      return NextResponse.redirect(url);
    }
  }

  return NextResponse.next();
}

export const config = {
  matcher: [
    "/tasks/:path*",
    "/projects/:path*",
    "/agents/:path*",
    "/squads/:path*",
    "/autopilots/:path*",
    "/skills/:path*",
  ],
};
