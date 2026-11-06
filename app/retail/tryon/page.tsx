import { headers } from "next/headers";
import { redirect } from "next/navigation";
import { getRetailPhone } from "../../lib/retail-session";
import RetailTryonPortal from "./retail-tryon-portal";

export const dynamic = "force-dynamic";

export default async function RetailTryonPage() {
  const requestHeaders = await headers();
  const phone = await getRetailPhone(requestHeaders.get("cookie"));
  if (!phone) redirect("/retail/login");
  return <RetailTryonPortal />;
}
