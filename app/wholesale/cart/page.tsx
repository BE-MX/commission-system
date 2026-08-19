import WholesaleProtectedPage from "../protected-page";

export const dynamic = "force-dynamic";

export default function WholesaleCart() {
  return <WholesaleProtectedPage view="cart" />;
}
