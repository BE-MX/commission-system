import RetailProtectedPage from "../protected-page";

export const dynamic = "force-dynamic";

export default function RetailProfile() {
  return <RetailProtectedPage view="profile" />;
}
