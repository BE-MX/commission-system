import RetailProtectedPage from "../protected-page";

export const dynamic = "force-dynamic";

export default function RetailCategory() {
  return <RetailProtectedPage view="category" />;
}
