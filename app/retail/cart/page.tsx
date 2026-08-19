import RetailProtectedPage from "../protected-page";

export const dynamic = "force-dynamic";

export default function RetailCart() {
  return <RetailProtectedPage view="cart" />;
}
