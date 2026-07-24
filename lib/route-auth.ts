import { getServerSession } from "next-auth";
import { NextResponse } from "next/server";
import { authOptions } from "@/lib/auth";

export async function ensureAuthenticated() {
  const session = await getServerSession(authOptions);

  if (!session) {
    return {
      session: null,
      response: NextResponse.json({ error: "Authentication required" }, { status: 401 }),
    };
  }

  return { session, response: null };
}
