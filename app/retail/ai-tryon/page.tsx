import { headers } from "next/headers";
import { redirect } from "next/navigation";
import { getRetailPhone } from "../../lib/retail-session";
import RetailAiTryOn from "./retail-ai-tryon";

export default async function RetailAiTryOnPage() {
  const requestHeaders = await headers();
  const phone = await getRetailPhone(requestHeaders.get("cookie"));
  if (!phone) redirect("/retail/login");
  return <RetailAiTryOn phone={phone} />;
}
