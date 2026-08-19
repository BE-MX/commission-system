import { headers } from "next/headers";
import { redirect } from "next/navigation";
import ShopApp from "../shop-app";
import { getWholesaleAccount } from "../lib/wholesale-session";

export default async function WholesaleProtectedPage({ view }: { view: "home" | "category" | "cart" | "profile" }) {
  const requestHeaders = await headers();
  const account = await getWholesaleAccount(requestHeaders.get("cookie"));
  if (!account) redirect("/wholesale/login");
  return <ShopApp mode="wholesale" view={view} account={account} />;
}
