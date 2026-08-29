import RetailProtectedPage from "../protected-page";

export const dynamic = "force-dynamic";

export default function RetailMarketing() {
  return <RetailProtectedPage view="marketing" />;
}
