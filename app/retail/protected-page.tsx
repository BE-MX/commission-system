import { headers } from "next/headers";
import { redirect } from "next/navigation";
import ShopApp from "../shop-app";
import { getRetailPhone } from "../lib/retail-session";

export default async function RetailProtectedPage({ view }: { view: "home" | "category" | "marketing" | "cart" | "profile" }) {
  const requestHeaders = await headers(); const phone = await getRetailPhone(requestHeaders.get("cookie"));
  if (!phone) redirect("/retail/login");
  return <ShopApp mode="retail" view={view} retailPhone={phone} />;
}
