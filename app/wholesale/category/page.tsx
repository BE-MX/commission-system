import WholesaleProtectedPage from "../protected-page";

export const dynamic = "force-dynamic";

export default function WholesaleCategory() {
  return <WholesaleProtectedPage view="category" />;
}
