import { headers } from "next/headers";
import { redirect } from "next/navigation";
import { getRetailPhone } from "../../lib/retail-session";

export default async function RetailAiTryOnPage() {
  const requestHeaders = await headers();
  const phone = await getRetailPhone(requestHeaders.get("cookie"));
  if (!phone) redirect("/retail/login");
  redirect("https://leshine.cloud/expo/kiosk");
}
