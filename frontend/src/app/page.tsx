import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { DEFAULT_WORKSPACE_SLUG } from "@/lib/paths";

export default async function Home() {
  const jar = await cookies();
  const slug = jar.get("last_workspace_slug")?.value || DEFAULT_WORKSPACE_SLUG;
  redirect(`/${slug}/tasks`);
}
